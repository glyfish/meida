"""Tests for ``FbiClient`` (``clients/fbi.py``).

Uses ``httpx.MockTransport`` with payloads hand-built to the shapes the live
CDE returns, so the suite never spends against the shared api.data.gov
allowance of a thousand calls an hour.

What is worth asserting here is not parsing but *filtering*. One request
returns four series for as many as three geographies at once, widest first, and
the labels are the only thing that tells them apart: a reader that takes the
first entry of ``rates`` after asking for the NYPD gets New York State, at a
plausible magnitude, with nothing to signal the substitution. These tests pin
the label filter, the nulls that must survive the pivot, and the refusals that
happen before a request is spent.

The client factory is local rather than in ``conftest.py`` so that the key is
injected here: nothing in this module can read a real ``DATA_GOV_KEY`` or reach
the network.
"""
from __future__ import annotations

from typing import Any, Callable

import httpx
import pytest

from clients import FbiAPIError, FbiClient
from clients.models.fbi import FbiEmploymentResponse, FbiOffenseResponse

HttpHandler = Callable[[httpx.Request], httpx.Response]

FBI_BASE_URL = "https://fbi.test/crime/fbi/cde"


@pytest.fixture
async def make_fbi_client() -> Callable[[HttpHandler], FbiClient]:
    """Factory building an FbiClient whose HTTP calls are served by ``handler``."""
    created: list[httpx.AsyncClient] = []

    def _factory(handler: HttpHandler, **kwargs: Any) -> FbiClient:
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=FBI_BASE_URL)
        created.append(http)
        return FbiClient(api_key="test-key", base_url=FBI_BASE_URL, client=http, **kwargs)

    yield _factory

    for http in created:
        await http.aclose()


# --- Sample payloads (the shapes the live CDE returns) -----------------------


def _properties() -> dict[str, Any]:
    return {"max_data_date": {"UCR": "09/2026"}, "last_refresh_date": {"UCR": "09/15/2026"}}


def _state_payload() -> dict[str, Any]:
    """``summarized/state/DC/homicide`` -- the state and the nation.

    ``actuals`` holds the state alone; ``rates`` holds both, nation first.
    """
    return {
        "offenses": {
            "actuals": {
                "District of Columbia Offenses": {"01-2019": 12.0, "02-2019": 9.0},
                "District of Columbia Clearances": {"01-2019": 7.0, "02-2019": 5.0},
            },
            "rates": {
                "United States Offenses": {"01-2019": 0.42, "02-2019": 0.38},
                "United States Clearances": {"01-2019": 0.25, "02-2019": 0.23},
                "District of Columbia Offenses": {"01-2019": 1.71, "02-2019": 1.28},
                "District of Columbia Clearances": {"01-2019": 1.00, "02-2019": 0.71},
            },
        },
        "populations": {"population": {
            "District of Columbia": {"01-2019": 701974.0, "02-2019": 701974.0},
            "United States": {"01-2019": 328239523.0, "02-2019": 328239523.0},
        }},
        "tooltips": {"Percent of Population Coverage": {
            "District of Columbia": {"01-2019": 100.0, "02-2019": 100.0},
            "United States": {"01-2019": 96.2, "02-2019": 96.2},
        }},
        "cde_properties": _properties(),
    }


def _agency_payload() -> dict[str, Any]:
    """``summarized/agency/NY0303000/homicide`` -- three geographies.

    The state comes first in ``rates`` and the agency last, which is the trap
    the label filter exists for. The rate magnitudes differ by a factor of
    three, so a test can tell whose numbers came back.
    """
    return {
        "offenses": {
            "actuals": {
                "New York City Police Department Offenses": {"01-2019": 26.0, "02-2019": 21.0},
                "New York City Police Department Clearances": {"01-2019": 18.0, "02-2019": 14.0},
            },
            "rates": {
                "New York Offenses": {"01-2019": 0.15, "02-2019": 0.12},
                "New York Clearances": {"01-2019": 0.09, "02-2019": 0.08},
                "United States Offenses": {"01-2019": 0.42, "02-2019": 0.38},
                "United States Clearances": {"01-2019": 0.25, "02-2019": 0.23},
                "New York City Police Department Offenses": {"01-2019": 0.31, "02-2019": 0.25},
                "New York City Police Department Clearances": {"01-2019": 0.21, "02-2019": 0.17},
            },
        },
        "populations": {"population": {
            "New York City Police Department": {"01-2019": 8336817.0, "02-2019": 8336817.0},
        }},
        "tooltips": {"Percent of Population Coverage": {
            "New York City Police Department": {"01-2019": 100.0, "02-2019": 100.0},
        }},
        "cde_properties": _properties(),
    }


def _employment_payload() -> dict[str, Any]:
    """``pe/agency/DCMPD0000`` -- counts by sex, and the rates block to ignore.

    1985 is the real Washington PD figure (3,400 + 437), 1986 the shape of a
    year the agency did not report, and the rates block carries the 274 per
    1,000 that makes it unusable.
    """
    return {
        "rates": {
            "Male Officers": {"1985": 35.1, "1986": 274.0},
            "Female Officers": {"1985": 4.5, "1986": 31.0},
        },
        "actuals": {
            "Male Officers": {"1985": 3400.0, "1986": None},
            "Female Officers": {"1985": 437.0, "1986": None},
            "Male Civilians": {"1985": 500.0, "1986": None},
            "Female Civilians": {"1985": 320.0, "1986": None},
        },
        "tooltips": {},
        "populations": {"Population": {"1985": 626000.0, "1986": 617000.0}},
        "cde_properties": _properties(),
    }


def _measures(response: FbiOffenseResponse) -> list[str]:
    """The labels of the offence and clearance series, in payload order."""
    return [s.label for s in response.series if s.measure in ("offenses", "clearances")]


# --- route() -----------------------------------------------------------------


def test_route_sends_national_to_the_national_fragment():
    assert FbiClient.route("national") == ("national", "national")


def test_route_upper_cases_a_two_letter_state():
    """The catalog's scope facet is whatever the caller typed; the path is not."""
    assert FbiClient.route("DC") == ("state/DC", "DC")
    assert FbiClient.route("dc") == ("state/DC", "DC")


def test_route_treats_anything_longer_as_an_ori():
    assert FbiClient.route("DCMPD0000") == ("agency/DCMPD0000", "DCMPD0000")
    assert FbiClient.route("NY0303000") == ("agency/NY0303000", "NY0303000")


# --- Requests ----------------------------------------------------------------


async def test_the_key_travels_as_a_capitalised_query_parameter(make_fbi_client):
    """The CDE routes ignore the lowercase ``api_key`` spelling and 403."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_state_payload())

    async with make_fbi_client(handler) as client:
        await client.get_offenses("homicide", state="DC", start="01-2019", end="02-2019")

    assert seen["path"].endswith("/summarized/state/DC/homicide")
    assert seen["params"]["API_KEY"] == "test-key"
    assert "api_key" not in seen["params"]
    assert seen["params"]["from"] == "01-2019" and seen["params"]["to"] == "02-2019"


async def test_an_ori_scope_is_routed_like_an_ori_argument(make_fbi_client):
    """``scope=`` is the catalog facet, so it must accept all three grains."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json=_agency_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_offenses("homicide", scope="NY0303000")

    assert seen["path"].endswith("/summarized/agency/NY0303000/homicide")
    assert response.scope == "NY0303000"
    assert _measures(response) == [
        "New York City Police Department Offenses",
        "New York City Police Department Clearances",
        "New York City Police Department Offenses",
        "New York City Police Department Clearances",
    ]


# --- The comparison series ---------------------------------------------------


async def test_a_state_request_drops_the_national_comparison(make_fbi_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_state_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_offenses("homicide", state="DC")

    assert isinstance(response, FbiOffenseResponse)
    assert not [s for s in response.series if s.label.startswith("United States")]
    # Six series survive: offences and clearances as counts and as rates, plus
    # the denominator and the coverage percentage, all for DC.
    assert len(response.series) == 6
    assert {s.unit for s in response.series} == {
        "count", "rate per 100,000", "people", "percent"}


async def test_an_agency_request_returns_the_agency_and_not_its_state(make_fbi_client):
    """The trap: the state is listed first in ``rates`` under a similar name.

    "New York Offenses" at 0.15 and "New York City Police Department Offenses"
    at 0.31 are both plausible homicide rates, so taking the first entry is a
    substitution nothing downstream can detect.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_agency_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_offenses("homicide", ori="NY0303000")

    assert all(s.label.startswith("New York City Police Department")
               for s in response.series if s.measure in ("offenses", "clearances"))
    rate = next(s for s in response.series
                if s.measure == "offenses" and s.unit == "rate per 100,000")
    assert [o.value for o in rate.observations] == [0.31, 0.25]   # not the state's 0.15


async def test_an_agency_request_keeps_its_population_and_coverage(make_fbi_client):
    """The denominator and the coverage survive the label filter.

    They are the agency's own -- dropping them with the comparisons would take
    away what makes a value interpretable.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_agency_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_offenses("homicide", ori="NY0303000")

    units = [s.unit for s in response.series]
    assert units.count("people") == 1 and units.count("percent") == 1
    coverage = next(s for s in response.series if s.unit == "percent")
    assert coverage.observations[0].value == 100.0


async def test_include_comparisons_keeps_the_state_and_the_nation(make_fbi_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_agency_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_offenses(
            "homicide", ori="NY0303000", include_comparisons=True)

    assert _measures(response) == [
        "New York City Police Department Offenses",
        "New York City Police Department Clearances",
        "New York Offenses",
        "New York Clearances",
        "United States Offenses",
        "United States Clearances",
        "New York City Police Department Offenses",
        "New York City Police Department Clearances",
    ]


async def test_a_national_request_keeps_its_own_united_states_series(make_fbi_client):
    """At national scope "United States" is the answer, not the comparison."""
    payload = {
        "offenses": {
            "actuals": {"United States Offenses": {"01-2019": 1400.0}},
            "rates": {"United States Offenses": {"01-2019": 0.42}},
        },
        "populations": {"population": {"United States": {"01-2019": 328239523.0}}},
        "tooltips": {"Percent of Population Coverage": {"United States": {"01-2019": 96.2}}},
        "cde_properties": _properties(),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with make_fbi_client(handler) as client:
        response = await client.get_offenses("violent-crime")

    assert response.scope == "national"
    assert len(response.series) == 4
    assert _measures(response) == ["United States Offenses", "United States Offenses"]


# --- The pivot ---------------------------------------------------------------


async def test_unreported_months_survive_the_pivot_as_none(make_fbi_client):
    """A month nobody reported is None, not zero and not absent.

    Dropped it shortens the series silently; zeroed it reads as no crime. 2021
    is full of these, which is the year the question is usually about.
    """
    payload = _state_payload()
    payload["offenses"]["actuals"]["District of Columbia Offenses"] = {
        "01-2019": None, "02-2019": 9.0}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with make_fbi_client(handler) as client:
        response = await client.get_offenses("homicide", state="DC")

    offenses = next(s for s in response.series
                    if s.measure == "offenses" and s.unit == "count")
    assert [(o.period, o.value) for o in offenses.observations] == [
        ("01-2019", None), ("02-2019", 9.0)]
    assert offenses.span == ("02-2019", "02-2019")


async def test_the_vintage_comes_off_the_ucr_property(make_fbi_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_state_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_offenses("homicide", state="DC")

    assert response.offense == "homicide" and response.scope == "DC"
    assert response.max_data_date == "09/2026"
    assert response.last_refresh_date == "09/15/2026"


async def test_a_payload_missing_its_blocks_yields_no_series(make_fbi_client):
    """Scopes with nothing to report answer 200 with empty blocks, not 404."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"offenses": None, "populations": None,
                                         "tooltips": None, "cde_properties": None})

    async with make_fbi_client(handler) as client:
        response = await client.get_offenses("arson", state="WY")

    assert response.series == []
    assert response.max_data_date is None


# --- Refusals, before a request is spent -------------------------------------


async def test_an_unknown_offence_is_refused_without_a_request(make_fbi_client):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=_state_payload())

    with pytest.raises(FbiAPIError) as exc_info:
        async with make_fbi_client(handler) as client:
            await client.get_offenses("shoplifting", state="DC")

    assert "shoplifting" in str(exc_info.value)
    assert calls == []


async def test_two_geographies_at_once_are_refused_without_a_request(make_fbi_client):
    """``state`` and ``ori`` together would silently pick one and drop the other."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=_agency_payload())

    with pytest.raises(FbiAPIError) as exc_info:
        async with make_fbi_client(handler) as client:
            await client.get_offenses("homicide", state="NY", ori="NY0303000")

    assert "one of scope, state or ori" in str(exc_info.value)
    assert calls == []


async def test_employment_before_1985_is_refused_without_a_request(make_fbi_client):
    """The API 400s on a from-year under 1985 rather than clamping to it."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=_employment_payload())

    with pytest.raises(FbiAPIError) as exc_info:
        async with make_fbi_client(handler) as client:
            await client.get_employment("DCMPD0000", start=1960)

    assert "1985" in str(exc_info.value)
    assert calls == []


# --- Employment --------------------------------------------------------------


async def test_employment_reads_the_counts_and_never_the_rates(make_fbi_client):
    """The pe rates divide by a participated population that is sometimes zero.

    The fixture's rates block says 274 officers per 1,000 residents; nothing
    with that magnitude may reach the caller.
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_employment_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_employment("DCMPD0000", start=1985, end=1986)

    assert seen["path"].endswith("/pe/agency/DCMPD0000")
    assert seen["params"]["from"] == "1985" and seen["params"]["to"] == "1986"
    assert isinstance(response, FbiEmploymentResponse)
    assert {s.unit for s in response.series} == {"count", "people"}
    values = [o.value for s in response.series for o in s.observations]
    assert 274.0 not in values and 35.1 not in values
    assert response.officers == {1985: 3837}


async def test_employment_series_are_scoped_to_the_ori(make_fbi_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_employment_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_employment("DCMPD0000")

    assert response.ori == "DCMPD0000"
    assert {s.scope for s in response.series} == {"DCMPD0000"}
    assert {s.measure for s in response.series} == {"officers", "civilians", "value"}


# --- Lookups -----------------------------------------------------------------


async def test_get_states_reads_the_nested_lookup(make_fbi_client):
    """``lookup/states`` buries its rows three levels down and is the only
    lookup that answers at all."""
    payload = {"get_states": {"cde_states_query": {"states": [
        {"abbr": "AL", "name": "Alabama"},
        {"abbr": "DC", "name": "District of Columbia"},
    ]}}}
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json=payload)

    async with make_fbi_client(handler) as client:
        states = await client.get_states()

    assert seen["path"].endswith("/lookup/states")
    assert states == [("AL", "Alabama"), ("DC", "District of Columbia")]


async def test_get_states_survives_an_empty_lookup(make_fbi_client):
    """``lookup/offenses`` answers with nulls; states must fail the same way."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"get_states": None})

    async with make_fbi_client(handler) as client:
        assert await client.get_states() == []


async def test_get_agencies_flattens_the_per_county_map(make_fbi_client):
    """The registry is keyed by county, and the caller wants one list."""
    payload = {
        "District of Columbia": [
            {"ori": "DCMPD0000", "agency_name": "Washington Police Department",
             "agency_type_name": "City", "state_abbr": "DC", "counties": "NOT SPECIFIED",
             "is_nibrs": True, "nibrs_start_date": "2021-08-01"},
            {"ori": "DCMTP0000", "agency_name": "Metro Transit Police",
             "agency_type_name": "Other", "state_abbr": "DC", "is_nibrs": True,
             "nibrs_start_date": "2000-01-01"},
        ],
        "state_abbr": "DC",   # the payload mixes scalars in with the county lists
    }
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json=payload)

    async with make_fbi_client(handler) as client:
        agencies = await client.get_agencies("DC")

    assert seen["path"].endswith("/agency/byStateAbbr/DC")
    assert [a.ori for a in agencies] == ["DCMPD0000", "DCMTP0000"]
    # The per-agency NIBRS date is where that agency's break falls, which is
    # not where the national 2021 dip suggests.
    assert agencies[1].nibrs_start_date == "2000-01-01"


# --- Errors ------------------------------------------------------------------


async def test_an_http_error_is_wrapped(make_fbi_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Please enter a from year greater than 1984")

    with pytest.raises(FbiAPIError) as exc_info:
        async with make_fbi_client(handler) as client:
            await client.get_offenses("homicide", state="DC", start="01-1970")

    assert "400" in str(exc_info.value)
    assert "greater than 1984" in str(exc_info.value)


async def test_the_hourly_allowance_says_so(make_fbi_client):
    """A thousand calls an hour is easy to reach on a bulk harvest."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="OVER_RATE_LIMIT")

    with pytest.raises(FbiAPIError) as exc_info:
        async with make_fbi_client(handler) as client:
            await client.get_offenses("homicide", state="DC")

    assert "rate limit" in str(exc_info.value)


async def test_an_html_answer_is_not_parsed_as_data(make_fbi_client):
    """The retired ``sapi`` service answers with an HTML page, not JSON."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<!DOCTYPE html><html><body>Not Found</body></html>")

    with pytest.raises(FbiAPIError) as exc_info:
        async with make_fbi_client(handler) as client:
            await client.get_offenses("homicide", state="DC")

    assert "expected JSON" in str(exc_info.value)


async def test_injected_client_not_owned(make_fbi_client):
    client = make_fbi_client(lambda request: httpx.Response(200, json={}))
    assert client._owns_client is False
