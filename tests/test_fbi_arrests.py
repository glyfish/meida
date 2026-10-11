"""Tests for the FBI arrest route (``FbiClient.get_arrests`` and its mapper).

Uses ``httpx.MockTransport`` with payloads copied from live CDE responses, so
the suite never spends against the shared api.data.gov allowance.

The arrest route is the same payload family as ``summarized`` and differs in
exactly the two places that are easy to get wrong, so those are what is pinned
here:

* ``actuals`` and ``rates`` sit at the **top level**, with no ``offenses``
  wrapper. A reader copied from ``get_offenses`` finds nothing and returns an
  empty series rather than failing.
* The requested scope has **no fixed place** in ``rates``: a requested agency
  is listed last, a requested state first. Neither position is reliable, so
  the labels in ``actuals`` decide.

Alongside those: the vocabulary this route accepts -- a UCR arrest code from
``ARREST_OFFENSES`` as the offence segment, ``all`` by default, refused before
any request when unknown; ``type=counts``; ``MM-YYYY`` dates -- the offence
carried from the request onto the response, since the labels never name it,
the month-major key order that makes a multi-year series come back out of
sequence, and the notice the mapper states on every response: an arrest is not
a clearance and cannot be differenced against one. The docstrings and the tool
description are checked for the opposite claim, which they used to make.

Three later corrections are pinned after that: a single offence's nulls are
months with no arrest nationally, not missing returns (live code 172, whose
months sum to the FBI's own total), and its quiet final months are held to
the same mass test as any other run at national and state scope; the rates
divide by the participated population, not the resident one, on both routes;
and ``offense`` sits last on the tool so a positional call from before it
existed still binds.

And the corrections to those, last: an agency's trailing run stays open,
because its participated population carries on after it stops filing (live
San Francisco murder arrests, 2024); a single code is judged on its counts,
so the rate is nulled where the count is; only the scope's own participated
population can vouch for a null, and a zero the CDE sent is kept (live Metro
Transit Police, whose participated population is 0 in every month); a rate
over a participated population of 0, published as -1, comes back null; the
notices describe the spelling the CDE actually used; and the documentation
states only what the saved payloads show.

The client factory is local rather than in ``conftest.py`` so that the key is
injected here: nothing in this module can read a real ``DATA_GOV_KEY`` or reach
the network.
"""
from __future__ import annotations

from typing import Any, Callable

import httpx
import pytest

import re

import clients.fbi as fbi_client
import mcp_server.responses.fbi as fbi_responses
from clients import FbiAPIError, FbiClient
from clients.fbi import ARREST_CODES_FOR, ARREST_OFFENSES, OFFENSES, arrest_offense
from clients.models.fbi import FbiArrestResponse, FbiObservation, FbiSeries
from mcp_server import server
from mcp_server.responses.fbi import FbiArrestSeries, from_arrest_response

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


# --- Sample payloads (copied from live arrest responses) ---------------------


def _properties() -> dict[str, Any]:
    return {"max_data_date": {"UCR": "09/2026"}, "last_refresh_date": {"UCR": "09/15/2026"}}


def _headers() -> dict[str, str]:
    """``tooltips`` carries a chart-axis map beside the coverage block.

    It is ``{str: str}`` where every other block is ``{str: {str: value}}``, so
    a pivot that assumes nesting trips over it.
    """
    return {"yAxisHeaderRates": "Arrests per 100,000 people",
            "yAxisHeaderActual": "Arrests"}


def _national_payload() -> dict[str, Any]:
    """``arrest/national/all`` for 01-2023..03-2023, as the API returned it."""
    return {
        "rates": {"United States Arrests": {
            "01-2023": 179.65, "02-2023": 166.85, "03-2023": 188.2}},
        "actuals": {"United States Arrests": {
            "01-2023": 580792, "02-2023": 536320, "03-2023": 610587}},
        "tooltips": {
            "leftYAxisHeaders": _headers(),
            "Percent of Population Coverage": {"United States": {
                "01-2023": 95.55, "02-2023": 95.0, "03-2023": 95.89}},
        },
        "populations": {
            "population": {"United States": {
                "01-2023": 338357687, "02-2023": 338357687, "03-2023": 338357687}},
            "participated_population": {"United States": {
                "01-2023": 323289818, "02-2023": 321444080, "03-2023": 324439456}},
        },
        "cde_properties": _properties(),
    }


def _state_payload() -> dict[str, Any]:
    """``arrest/state/TX/all`` -- the state and the nation, state first."""
    return {
        "rates": {
            "Texas Arrests": {"01-2023": 157.64, "02-2023": 147.66, "03-2023": 166.44},
            "United States Arrests": {
                "01-2023": 179.65, "02-2023": 166.85, "03-2023": 188.2},
        },
        "actuals": {"Texas Arrests": {
            "01-2023": 48322, "02-2023": 45264, "03-2023": 51020}},
        "tooltips": {
            "leftYAxisHeaders": _headers(),
            "Percent of Population Coverage": {
                "Texas": {"01-2023": 98.72, "02-2023": 98.7, "03-2023": 98.75},
                "United States": {"01-2023": 95.55, "02-2023": 95.0, "03-2023": 95.89},
            },
        },
        "populations": {
            "population": {
                "Texas": {"01-2023": 30503301, "02-2023": 30503301, "03-2023": 30503301},
                "United States": {
                    "01-2023": 338357687, "02-2023": 338357687, "03-2023": 338357687},
            },
        },
        "cde_properties": _properties(),
    }


def _agency_payload() -> dict[str, Any]:
    """``arrest/agency/NY0303000/all`` -- three geographies, the agency LAST.

    ``rates`` is keyed New York, United States, New York City Police
    Department, in that order, and ``actuals`` holds the agency alone. The
    agency's coverage is ``null``: it publishes none of its own.

    The state's 148.48 and the agency's 157.49 are both plausible arrest rates,
    so reading the wrong one is a substitution nothing downstream can detect.
    """
    return {
        "rates": {
            "New York Arrests": {
                "01-2023": 148.48, "02-2023": 140.52, "03-2023": 163.84},
            "United States Arrests": {
                "01-2023": 179.65, "02-2023": 166.85, "03-2023": 188.2},
            "New York City Police Department Arrests": {
                "01-2023": 157.49, "02-2023": 153.57, "03-2023": 179.74},
        },
        "actuals": {"New York City Police Department Arrests": {
            "01-2023": 12889, "02-2023": 12568, "03-2023": 14710}},
        "tooltips": {
            "leftYAxisHeaders": _headers(),
            "Percent of Population Coverage": {
                "New York": {"01-2023": 99.66, "02-2023": 99.64, "03-2023": 99.66},
                "United States": {"01-2023": 95.55, "02-2023": 95.0, "03-2023": 95.89},
                "New York City Police Department": None,
            },
        },
        "populations": {
            "population": {
                "New York": {
                    "01-2023": 19571216, "02-2023": 19571216, "03-2023": 19571216},
                "United States": {
                    "01-2023": 338357687, "02-2023": 338357687, "03-2023": 338357687},
                "New York City Police Department": {
                    "01-2023": 8184044, "02-2023": 8184044, "03-2023": 8184044},
            },
        },
        "cde_properties": _properties(),
    }


def _month_major_payload() -> dict[str, Any]:
    """``arrest/state/TX/all`` over 2018-2020, in the key order the API used.

    Every January, then every February: the periods are grouped by month and
    not by date, which is what ``_chronological`` exists to undo.
    """
    return {
        "rates": {},
        "actuals": {"Texas Arrests": {
            "01-2018": 84593, "01-2019": 78606, "01-2020": 62934,
            "02-2018": 82523, "02-2019": 72772, "02-2020": 61825,
            "03-2018": 95650, "03-2019": 78381, "03-2020": 52404,
        }},
        "tooltips": {"leftYAxisHeaders": _headers(),
                     "Percent of Population Coverage": {}},
        "populations": {"population": {}},
        "cde_properties": _properties(),
    }


def _arrests(response: FbiArrestResponse) -> list[str]:
    """The labels of the arrest series, in payload order."""
    return [s.label for s in response.series if s.measure == "arrests"]


# --- The route and its vocabulary --------------------------------------------


async def test_the_default_path_is_the_all_offence_route_with_type_counts(make_fbi_client):
    """With no offence the segment is ``all``, exactly as before the argument existed.

    ``type`` is required -- omitting it is a 400 ``Invalid 'type'.`` -- and
    ``counts`` is the monthly payload, which carries the rates as well.
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_state_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests(state="TX", start="01-2023", end="03-2023")

    assert seen["path"].endswith("/arrest/state/TX/all")
    assert response.offense == "all"
    assert seen["params"]["type"] == "counts"
    assert seen["params"]["API_KEY"] == "test-key"
    assert "api_key" not in seen["params"]
    assert seen["params"]["from"] == "01-2023" and seen["params"]["to"] == "03-2023"


async def test_one_request_carries_the_count_and_the_rate(make_fbi_client):
    """``type=counts`` does not mean counts only; the rates come regardless."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_state_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests(state="TX")

    units = {s.unit for s in response.series if s.measure == "arrests"}
    assert units == {"count", "rate per 100,000"}


async def test_the_scope_fragments_are_the_ones_summarized_uses(make_fbi_client):
    """national, state/{ST} and agency/{ORI}, unchanged from ``route()``."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=_national_payload())

    async with make_fbi_client(handler) as client:
        await client.get_arrests()
        await client.get_arrests(scope="tx")
        await client.get_arrests(scope="NY0303000")

    assert [p.rsplit("/cde/", 1)[-1] for p in paths] == [
        "arrest/national/all", "arrest/state/TX/all", "arrest/agency/NY0303000/all"]


async def test_a_bare_year_is_refused_without_a_request(make_fbi_client):
    """``from=2023`` is a 400, not a January. Employment takes years; this does not."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=_state_payload())

    with pytest.raises(FbiAPIError) as exc_info:
        async with make_fbi_client(handler) as client:
            await client.get_arrests(state="TX", start="2023", end="12-2023")

    assert "MM-YYYY" in str(exc_info.value)
    assert calls == []


@pytest.mark.parametrize("period", ["13-2023", "1-2023", "01-23", "2023-01", "January"])
async def test_a_malformed_month_is_refused_without_a_request(make_fbi_client, period):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=_state_payload())

    with pytest.raises(FbiAPIError):
        async with make_fbi_client(handler) as client:
            await client.get_arrests(state="TX", start=period)

    assert calls == []


async def test_two_geographies_at_once_are_refused_without_a_request(make_fbi_client):
    """``state`` and ``ori`` together would silently pick one and drop the other."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=_agency_payload())

    with pytest.raises(FbiAPIError) as exc_info:
        async with make_fbi_client(handler) as client:
            await client.get_arrests(state="NY", ori="NY0303000")

    assert "one of scope, state or ori" in str(exc_info.value)
    assert calls == []


# --- Per-offence arrests -----------------------------------------------------
#
# The payloads below are ``arrest/{scope}/11`` -- murder and nonnegligent
# homicide -- for 01-2023..03-2023, copied from live responses. They are the
# ``all`` shape exactly, down to the labels: nothing in them says murder.


def _murder_national_payload() -> dict[str, Any]:
    """``arrest/national/11``: 1,017, 905 and 1,027 murder arrests a month."""
    return {
        "rates": {"United States Arrests": {
            "01-2023": 0.31, "02-2023": 0.28, "03-2023": 0.32}},
        "actuals": {"United States Arrests": {
            "01-2023": 1017, "02-2023": 905, "03-2023": 1027}},
        "tooltips": {
            "leftYAxisHeaders": _headers(),
            "Percent of Population Coverage": {"United States": {
                "01-2023": 95.55, "02-2023": 95.0, "03-2023": 95.89}},
        },
        "populations": {"population": {"United States": {
            "01-2023": 338357687, "02-2023": 338357687, "03-2023": 338357687}}},
        "cde_properties": _properties(),
    }


def _murder_state_payload() -> dict[str, Any]:
    """``arrest/state/NY/11`` -- the requested state listed FIRST in ``rates``."""
    return {
        "rates": {
            "New York Arrests": {"01-2023": 0.25, "02-2023": 0.19, "03-2023": 0.23},
            "United States Arrests": {
                "01-2023": 0.31, "02-2023": 0.28, "03-2023": 0.32},
        },
        "actuals": {"New York Arrests": {
            "01-2023": 49, "02-2023": 37, "03-2023": 44}},
        "tooltips": {
            "leftYAxisHeaders": _headers(),
            "Percent of Population Coverage": {
                "New York": {"01-2023": 99.66, "02-2023": 99.64, "03-2023": 99.66},
                "United States": {"01-2023": 95.55, "02-2023": 95.0, "03-2023": 95.89},
            },
        },
        "populations": {"population": {
            "New York": {"01-2023": 19571216, "02-2023": 19571216, "03-2023": 19571216},
            "United States": {
                "01-2023": 338357687, "02-2023": 338357687, "03-2023": 338357687},
        }},
        "cde_properties": _properties(),
    }


def _murder_agency_payload() -> dict[str, Any]:
    """``arrest/agency/NY0303000/11`` -- the requested agency listed LAST.

    The state's murder-arrest rate (0.25) and the NYPD's (0.15) are both
    plausible, so reading the wrong one would pass unnoticed.
    """
    return {
        "rates": {
            "New York Arrests": {"01-2023": 0.25, "02-2023": 0.19, "03-2023": 0.23},
            "United States Arrests": {
                "01-2023": 0.31, "02-2023": 0.28, "03-2023": 0.32},
            "New York City Police Department Arrests": {
                "01-2023": 0.15, "02-2023": 0.2, "03-2023": 0.22},
        },
        "actuals": {"New York City Police Department Arrests": {
            "01-2023": 12, "02-2023": 16, "03-2023": 18}},
        "tooltips": {
            "leftYAxisHeaders": _headers(),
            "Percent of Population Coverage": {
                "New York": {"01-2023": 99.66, "02-2023": 99.64, "03-2023": 99.66},
                "United States": {"01-2023": 95.55, "02-2023": 95.0, "03-2023": 95.89},
                "New York City Police Department": None,
            },
        },
        "populations": {"population": {
            "New York": {"01-2023": 19571216, "02-2023": 19571216, "03-2023": 19571216},
            "United States": {
                "01-2023": 338357687, "02-2023": 338357687, "03-2023": 338357687},
            "New York City Police Department": {
                "01-2023": 8184044, "02-2023": 8184044, "03-2023": 8184044},
        }},
        "cde_properties": _properties(),
    }


async def test_the_offence_code_reaches_the_path_at_every_grain(make_fbi_client):
    """The code is the path's last segment, after the unchanged scope fragment."""
    paths: list[str] = []
    params: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        params.append(dict(request.url.params))
        return httpx.Response(200, json=_murder_national_payload())

    async with make_fbi_client(handler) as client:
        await client.get_arrests("11")
        await client.get_arrests("11", scope="NY")
        await client.get_arrests("11", ori="NY0303000")
        await client.get_arrests(offense="260", state="TX")

    assert [p.rsplit("/cde/", 1)[-1] for p in paths] == [
        "arrest/national/11", "arrest/state/NY/11", "arrest/agency/NY0303000/11",
        "arrest/state/TX/260"]
    # The offence travels in the path, never as a query parameter, and the
    # query is what it always was.
    assert all(set(p) == {"from", "to", "type", "API_KEY"} for p in params)
    assert all(p["type"] == "counts" for p in params)


async def test_the_default_offence_is_all(make_fbi_client):
    """Every call written before the argument existed still asks for ``all``."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=_national_payload())

    async with make_fbi_client(handler) as client:
        default = await client.get_arrests()
        explicit = await client.get_arrests("all")

    assert paths[0] == paths[1] and paths[0].endswith("/arrest/national/all")
    assert default.offense == explicit.offense == "all"


@pytest.mark.parametrize("given, code", [
    ("11", "11"),
    (11, "11"),
    ("ALL", "all"),
    ("Murder and Nonnegligent Homicide", "11"),
    ("  driving under the   influence ", "260"),
    ("Drug Abuse Violations (Unspecified)", "150"),
])
async def test_a_name_or_a_code_maps_to_the_code_the_api_takes(make_fbi_client, given, code):
    """The API's codes are kept; the FBI's own names are mapped onto them."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=_national_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests(given)

    assert paths[0].endswith(f"/arrest/national/{code}")
    assert response.offense == code


@pytest.mark.parametrize("offense", [
    "violent-crime", "homicide", "999", "", "counts", "offense", "age",
    # The spec's shorter name for 150. It reads as every drug arrest, and 150
    # is only the ones given no sub-code, so it is not accepted as a name.
    "Drug Abuse Violations",
])
async def test_an_unknown_offence_is_refused_without_a_request(make_fbi_client, offense):
    """The gateway locks a key out after enough failures, so none is spent on a guess."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=_national_payload())

    with pytest.raises(FbiAPIError) as exc_info:
        async with make_fbi_client(handler) as client:
            await client.get_arrests(offense, state="TX")

    assert "unknown arrest offence" in str(exc_info.value)
    assert calls == []


@pytest.mark.parametrize("slug", OFFENSES)
def test_a_summarized_slug_is_refused_with_the_codes_that_make_it_up(slug):
    """The most likely mistake, answered in the refusal rather than by a 400."""
    with pytest.raises(FbiAPIError) as exc_info:
        arrest_offense(slug)

    message = str(exc_info.value)
    assert "summarized slug" in message
    for code in ARREST_CODES_FOR[slug]:
        assert f"{code} ({ARREST_OFFENSES[code]})" in message


def test_the_code_table_is_the_documented_one():
    """48 values: ``all`` and 47 numeric UCR arrest codes, none of them a slug."""
    assert len(ARREST_OFFENSES) == 48
    assert next(iter(ARREST_OFFENSES)) == "all"
    assert all(code.isdigit() for code in ARREST_OFFENSES if code != "all")
    assert not set(OFFENSES) & set(ARREST_OFFENSES)
    assert ARREST_OFFENSES["11"] == "Murder and Nonnegligent Homicide"
    assert ARREST_OFFENSES["50"] == "Assault - Not Specified"
    assert ARREST_OFFENSES["260"] == "Driving Under the Influence"
    # Every slug's codes exist, and arson stays outside property crime.
    assert set(ARREST_CODES_FOR) == set(OFFENSES)
    assert all(code in ARREST_OFFENSES
               for codes in ARREST_CODES_FOR.values() for code in codes)
    assert "110" not in ARREST_CODES_FOR["property-crime"]
    assert ARREST_CODES_FOR["violent-crime"] == ("11", "20", "23", "30", "50")


async def test_the_offence_is_carried_on_the_response_because_the_label_never_names_it(
        make_fbi_client):
    """Murder comes back as "New York Arrests", the same label as every other code."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_murder_state_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests("11", state="NY")

    assert response.offense == "11"
    assert _arrests(response) == ["New York Arrests", "New York Arrests"]


async def test_a_per_offence_state_request_keeps_the_state_listed_first(make_fbi_client):
    """The state leads ``rates`` here, so a take-the-last reader gets the nation."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_murder_state_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests("11", state="NY")

    rate = next(s for s in response.series
                if s.measure == "arrests" and s.unit == "rate per 100,000")
    count = next(s for s in response.series
                 if s.measure == "arrests" and s.unit == "count")
    assert [o.value for o in rate.observations] == [0.25, 0.19, 0.23]
    assert [o.value for o in count.observations] == [49, 37, 44]
    assert not [s for s in response.series if s.label.startswith("United States")]


async def test_a_per_offence_agency_request_keeps_the_agency_listed_last(make_fbi_client):
    """The agency trails ``rates``; the ``actuals`` labels find it wherever it is."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_murder_agency_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests("11", ori="NY0303000")

    rate = next(s for s in response.series
                if s.measure == "arrests" and s.unit == "rate per 100,000")
    count = next(s for s in response.series
                 if s.measure == "arrests" and s.unit == "count")
    assert rate.label == "New York City Police Department Arrests"
    assert [o.value for o in rate.observations] == [0.15, 0.2, 0.22]
    assert [o.value for o in count.observations] == [12, 16, 18]


# --- The blocks are not nested -----------------------------------------------


async def test_the_numbers_are_read_from_the_top_level_not_from_a_wrapper(make_fbi_client):
    """``summarized`` nests under ``offenses``; ``arrest`` does not.

    The payload here carries both, with different magnitudes, so a reader
    copied from ``get_offenses`` would come back with the decoy rather than
    with nothing -- which is the failure that survives review.
    """
    payload = _state_payload()
    payload["offenses"] = {
        "actuals": {"Texas Arrests": {"01-2023": 1.0, "02-2023": 2.0, "03-2023": 3.0}},
        "rates": {"Texas Arrests": {"01-2023": 0.1}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests(state="TX")

    counts = next(s for s in response.series
                  if s.measure == "arrests" and s.unit == "count")
    assert [o.value for o in counts.observations] == [48322, 45264, 51020]


# --- The comparison series ---------------------------------------------------


async def test_a_state_request_drops_the_national_comparison(make_fbi_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_state_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests(state="TX")

    assert isinstance(response, FbiArrestResponse)
    assert response.scope == "TX"
    assert not [s for s in response.series if s.label.startswith("United States")]
    # Four series survive: arrests as a count and as a rate, plus the
    # denominator and the coverage percentage, all for Texas.
    assert len(response.series) == 4
    assert {s.unit for s in response.series} == {
        "count", "rate per 100,000", "people", "percent"}


async def test_an_agency_request_returns_the_agency_and_not_its_state(make_fbi_client):
    """The trap, and it is worse here: the agency is listed LAST in ``rates``.

    ``summarized`` puts the state first and the agency last; this route puts
    the state first, the nation second and the agency last. Taking either end
    of the block gives a comparison geography at a plausible magnitude.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_agency_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests(ori="NY0303000")

    assert _arrests(response) == [
        "New York City Police Department Arrests",
        "New York City Police Department Arrests",
    ]
    rate = next(s for s in response.series
                if s.measure == "arrests" and s.unit == "rate per 100,000")
    assert [o.value for o in rate.observations] == [157.49, 153.57, 179.74]
    assert 148.48 not in [o.value for o in rate.observations]   # the state's


async def test_the_agency_is_matched_by_the_actuals_labels_not_by_position(make_fbi_client):
    """``actuals`` carries the requested scope alone, at every grain.

    Reordering ``rates`` must not change the answer -- if it does, the filter
    is reading position rather than labels.
    """
    payload = _agency_payload()
    payload["rates"] = dict(reversed(list(payload["rates"].items())))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests(ori="NY0303000")

    rate = next(s for s in response.series
                if s.measure == "arrests" and s.unit == "rate per 100,000")
    assert rate.label == "New York City Police Department Arrests"
    assert [o.value for o in rate.observations] == [157.49, 153.57, 179.74]


async def test_an_agency_keeps_its_own_population_and_its_states_coverage(make_fbi_client):
    """The agency's coverage is ``null``, so the state's has to stand in.

    Dropping it with the national comparison would take away the only thing
    that says how much of the population the figure rests on. The label is what
    makes the substitution visible.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_agency_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests(ori="NY0303000")

    coverage = [s for s in response.series if s.unit == "percent"]
    population = [s for s in response.series if s.unit == "people"]
    assert [s.label for s in coverage] == ["New York"]
    assert [s.label for s in population] == [
        "New York", "New York City Police Department"]


async def test_include_comparisons_keeps_the_state_and_the_nation(make_fbi_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_agency_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests(ori="NY0303000", include_comparisons=True)

    assert _arrests(response) == [
        "New York City Police Department Arrests",
        "New York Arrests",
        "United States Arrests",
        "New York City Police Department Arrests",
    ]


async def test_a_national_request_keeps_its_own_united_states_series(make_fbi_client):
    """At national scope "United States" is the answer, not the comparison."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_national_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests()

    assert response.scope == "national"
    # Count, rate, population, participated population, coverage.
    assert len(response.series) == 5
    assert _arrests(response) == ["United States Arrests", "United States Arrests"]


# --- The pivot ---------------------------------------------------------------


async def test_the_label_names_the_measure_as_arrests(make_fbi_client):
    """"Texas Arrests" is a measure the label parser has to know.

    Unrecognised, it falls through to 'value', and every selection downstream
    is made on the measure.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_state_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests(state="TX")

    assert {s.measure for s in response.series} == {"arrests", "value"}
    assert "value" not in {s.measure for s in response.series if s.unit == "count"}


async def test_a_multi_year_series_comes_back_in_date_order(make_fbi_client):
    """The API keys the periods month-major: every January, then every February.

    Sorted as text, '01-2019' precedes '02-2018', so the series arrives out of
    sequence and its span reads as 01-2018 to 03-2020 whatever it contains.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_month_major_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests(
            state="TX", start="01-2018", end="03-2020")

    counts = next(s for s in response.series if s.unit == "count")
    assert [o.period for o in counts.observations] == [
        "01-2018", "02-2018", "03-2018",
        "01-2019", "02-2019", "03-2019",
        "01-2020", "02-2020", "03-2020",
    ]
    assert [o.value for o in counts.observations][:3] == [84593, 82523, 95650]
    assert counts.span == ("01-2018", "03-2020")


async def test_unreported_months_survive_the_pivot_as_none(make_fbi_client):
    """A month nobody reported is None, not zero and not absent."""
    payload = _state_payload()
    payload["actuals"]["Texas Arrests"] = {
        "01-2023": None, "02-2023": 45264, "03-2023": 51020}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests(state="TX")

    counts = next(s for s in response.series
                  if s.measure == "arrests" and s.unit == "count")
    assert [(o.period, o.value) for o in counts.observations] == [
        ("01-2023", None), ("02-2023", 45264), ("03-2023", 51020)]
    assert counts.span == ("02-2023", "03-2023")


async def test_the_axis_header_block_is_not_pivoted_as_a_series(make_fbi_client):
    """``tooltips.leftYAxisHeaders`` is ``{str: str}`` and must be skipped."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_national_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests()

    assert not [s for s in response.series if "yAxisHeader" in s.label]


async def test_the_vintage_comes_off_the_ucr_property(make_fbi_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_state_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests(state="TX")

    assert response.max_data_date == "09/2026"
    assert response.last_refresh_date == "09/15/2026"


async def test_a_payload_missing_its_blocks_yields_no_series(make_fbi_client):
    """A scope with nothing to report answers 200 with empty blocks, not 404."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"actuals": None, "rates": None,
                                         "tooltips": None, "populations": None,
                                         "cde_properties": None})

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests(state="WY")

    assert response.series == []
    assert response.max_data_date is None


# --- Errors ------------------------------------------------------------------


async def test_an_invalid_offence_segment_is_wrapped(make_fbi_client):
    """A 400 for the offence segment still arrives as an ``FbiAPIError``.

    An unknown code never gets this far now -- it is refused before the
    request -- but the FBI can retire a code the table still lists, and that
    answer has to be readable rather than a bare ``HTTPStatusError``.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="An invalid offense was requested.")

    with pytest.raises(FbiAPIError) as exc_info:
        async with make_fbi_client(handler) as client:
            await client.get_arrests(state="TX")

    assert "400" in str(exc_info.value)
    assert "invalid offense" in str(exc_info.value)


async def test_the_plain_text_invalid_type_answer_is_not_parsed_as_data(make_fbi_client):
    """``Invalid 'type'.`` comes back as text with a non-JSON content type."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Invalid 'type'.")

    with pytest.raises(FbiAPIError) as exc_info:
        async with make_fbi_client(handler) as client:
            await client.get_arrests(state="TX")

    assert "expected JSON" in str(exc_info.value)


# --- The mapper --------------------------------------------------------------


async def _mapped(handler: HttpHandler, factory, **kwargs) -> FbiArrestSeries:
    scope = kwargs.pop("scope", "TX")
    unit = kwargs.pop("unit", "count")
    async with factory(handler) as client:
        response = await client.get_arrests(scope=scope, **kwargs)
    return from_arrest_response(response, scope=scope, unit=unit)


async def test_the_mapper_selects_the_count(make_fbi_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_state_payload())

    series = await _mapped(handler, make_fbi_client)

    assert series.scope == "TX" and series.geography == "Texas"
    assert series.measure == "arrests" and series.unit == "count"
    assert series.frequency == "Monthly"
    assert [o.value for o in series.observations] == [48322, 45264, 51020]
    assert (series.observation_start, series.observation_end) == ("01-2023", "03-2023")
    assert series.coverage.label == "Texas"
    assert series.coverage_mean_percent == 98.72
    assert series.population.observations[0].value == 30503301
    assert series.max_data_date == "09/2026"


async def test_the_mapper_selects_the_rate_from_the_same_payload(make_fbi_client):
    """Unit is a selection made after the call; it never reaches the FBI."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_state_payload())

    series = await _mapped(handler, make_fbi_client, unit="rate")

    assert series.unit == "rate per 100,000"
    assert [o.value for o in series.observations] == [157.64, 147.66, 166.44]


async def test_every_response_says_which_offence_and_that_it_is_not_a_clearance(
        make_fbi_client):
    """Both facts are always true, so both are always stated.

    The labels never name the offence, and differencing arrests against
    clearances is wrong in a way no value in the payload reveals.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_state_payload())

    series = await _mapped(handler, make_fbi_client)

    assert "ALL offences together" in series.notices[0]
    assert "An arrest is NOT a clearance" in series.notices[0]
    assert "cannot be differenced against fbi_offenses' clearances" in series.notices[0]


async def test_a_stood_in_coverage_label_is_flagged(make_fbi_client):
    """The agency's coverage is its state's, and the notice says whose."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_agency_payload())

    series = await _mapped(handler, make_fbi_client, scope="NY0303000")

    assert series.geography == "New York City Police Department"
    assert series.coverage.label == "New York"
    assert series.population.label == "New York City Police Department"
    assert any("labelled New York rather than New York City Police Department"
               in notice for notice in series.notices)


def test_an_empty_payload_maps_to_a_notice_rather_than_raising():
    """The mappers are total: nothing selected is a record with a notice."""
    series = from_arrest_response(
        FbiArrestResponse(scope="WY", series=[]), scope="WY")

    assert series.observations == []
    assert series.offense == "all"
    assert "ALL offences together" in series.notices[0]
    assert "No arrest series as count" in series.notices[1]
    assert "01-2018" in series.notices[1]


def test_a_none_payload_maps_to_a_notice_rather_than_raising():
    series = from_arrest_response(None, scope="national")

    assert series.scope == "national" and series.observations == []
    assert len(series.notices) == 2


async def test_a_series_spanning_2021_is_called_spliced(make_fbi_client):
    """The SRS-to-NIBRS break applies to arrests as much as to offences."""
    payload = _state_payload()
    payload["actuals"]["Texas Arrests"] = {"01-2020": 62934, "01-2022": 55000}
    payload["rates"] = {}
    payload["tooltips"]["Percent of Population Coverage"] = {
        "Texas": {"01-2020": 98.86, "01-2022": 97.4}}
    payload["populations"]["population"] = {
        "Texas": {"01-2020": 29000000, "01-2022": 30000000}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    series = await _mapped(handler, make_fbi_client, start="01-2020", end="01-2022")

    assert any("spliced, not continuous" in notice for notice in series.notices)


# --- A zero is not always a zero ---------------------------------------------
#
# The defect these pin: at agency scope the arrest route pads every month the
# department did not file with 0 rather than with null, the mapper's own
# "filled" test was ``is not None``, and the only hole detector was the
# coverage floor -- which at agency scope reads the STATE's coverage and so
# cannot see one agency going dark. Washington's Metropolitan Police therefore
# advertised 01-1985 to 09-2026, 501 of 501 months filled, across twenty-five
# years in which it filed nothing at all.


def _months(first: str, count: int) -> list[str]:
    """``count`` consecutive ``MM-YYYY`` periods starting at *first*."""
    month, year = (int(part) for part in first.split("-"))
    periods: list[str] = []
    for _ in range(count):
        periods.append(f"{month:02d}-{year}")
        month, year = (month % 12 + 1, year + (month == 12))
    return periods


def _arrest_response(values: list[float | None], *, first: str = "01-1985",
                     scope: str = "DCMPD0000",
                     geography: str = "Washington Police Department",
                     state: str = "District of Columbia",
                     coverage: float = 100.0) -> FbiArrestResponse:
    """One hand-built arrest payload: the series, its state's coverage, a population.

    Coverage is the state's and is flat by default, which is the situation the
    detector has to work in: at agency scope the percentage published belongs
    to a geography that was reporting perfectly well.
    """
    periods = _months(first, len(values))

    def points(source):
        return [FbiObservation(period=period, value=value)
                for period, value in zip(periods, source)]

    return FbiArrestResponse(scope=scope, max_data_date="09/2026", series=[
        FbiSeries(label=f"{geography} Arrests", scope=scope, measure="arrests",
                  unit="count", observations=points(values)),
        FbiSeries(label=state, scope=scope, measure="value", unit="percent",
                  observations=points([coverage] * len(values))),
        FbiSeries(label=geography, scope=scope, measure="value", unit="people",
                  observations=points([680_000.0] * len(values))),
    ])


def _washington() -> list[float]:
    """DCMPD0000's arrest counts, 01-1985..09-2026, in the shape the CDE serves.

    501 months, of which 150 carry a filing. Four years of annual filing where
    a December holds the whole year, then twenty-five and a half years of
    nothing, then NIBRS from August 2021, then a vintage month that has barely
    started to arrive.
    """
    values = [5500.0 + 100 * (i % 12) for i in range(12 * 7)]     # 1985-1991
    for _ in range(4):                                            # 1992-1995
        values += [0.0] * 11 + [62_000.0]
    values += [0.0] * (12 * 25 + 7)                               # 01-1996..07-2021
    values += [1000.0 + 20.0 * i for i in range(61)]              # 08-2021..08-2026
    return values + [5.0]                                         # 09-2026


def test_twenty_five_years_of_zeros_are_not_twenty_five_years_of_data():
    """The whole defect, at the size it occurred.

    Every one of these months passed ``is not None``, so the response claimed
    501 of 501 filled and a span reaching back to 1985 -- and a caller summing
    the series got a department that arrested nobody for a quarter of a century
    rather than a department that stopped filing.
    """
    series = from_arrest_response(
        _arrest_response(_washington()), scope="DCMPD0000")

    assert len(series.observations) == 501
    # 150 filings, plus the 44 blank months that belong to the four annual
    # returns of 1992-1995: a run of eleven blanks closed by a December carrying
    # the whole year is a filing schedule, not a department that stopped, and
    # nulling those eleven would leave the December standing alone as a month.
    assert sum(1 for o in series.observations if o.value is not None) == 194
    kept_zeros = [o.period for o in series.observations if o.value == 0]
    assert len(kept_zeros) == 44
    assert {period.split("-")[1] for period in kept_zeros} == {"1992", "1993", "1994", "1995"}
    # Nulled, not left as zero, for the twenty-five year hole: the point of the
    # choice. A consumer that sums without reading notices now drops those
    # months or raises, instead of averaging a thousand arrests a month down to
    # three hundred. And a consumer summing 1992 gets the year the CDE filed.
    assert not [o for o in series.observations
                if o.value == 0 and not o.period.endswith(("1992", "1993", "1994", "1995"))]
    year = [o.value for o in series.observations if o.period.endswith("-1992")]
    assert sum(value for value in year if value is not None) == 62_000
    hole = {o.period: o.value for o in series.observations}
    assert hole["01-1996"] is None and hole["07-2021"] is None
    assert hole["12-1995"] == 62_000.0 and hole["08-2021"] == 1000.0


def test_the_span_names_the_filings_and_not_the_requested_window():
    """01-1985 to 09-2026 was the window asked for, not the data returned."""
    series = from_arrest_response(
        _arrest_response(_washington()), scope="DCMPD0000")

    assert series.observation_start == "01-1985"
    assert series.observation_end == "09-2026"
    # And where the padding sits at the edges, the span moves off it: an agency
    # the CDE has nothing for before 2018 gets zeros back for 1985 onwards.
    padded = from_arrest_response(
        _arrest_response([0.0] * 36 + [1200.0 + 10 * i for i in range(24)] + [0.0, 0.0],
                         first="01-2015"),
        scope="DCMPD0000")
    assert (padded.observation_start, padded.observation_end) == ("01-2018", "12-2019")
    assert padded.observations[0].value is None
    assert padded.observations[-1].value is None


def test_the_unfiled_spans_are_named_and_counted():
    """A notice in the voice of the others, naming the stretches and the count."""
    series = from_arrest_response(
        _arrest_response(_washington()), scope="DCMPD0000")

    notice = next(n for n in series.notices if "record no filing" in n)
    # 307, not 351: the 44 blanks of 1992-1995 are a filing schedule and get
    # their own sentence rather than being counted as months nobody filed.
    assert "307 of the 501 months" in notice
    assert "01-1996..07-2021" in notice
    assert "01-1992..11-1992" not in notice
    assert "spells a missing return as 0 rather than as null" in notice

    schedule = next(n for n in series.notices if "annual returns" in n)
    assert "4 annual returns" in schedule
    assert "01-1992..11-1992 closed by 12-1992" in schedule
    assert "62,000 arrests against 62,000 for 12 months" in schedule


def test_the_state_coverage_cannot_see_the_hole_and_says_nothing():
    """Why the run test had to exist: coverage is structurally blind here.

    The District of Columbia reported 100% of its population in every one of
    these months, because the District was reporting. The agency was not.
    """
    series = from_arrest_response(
        _arrest_response(_washington()), scope="DCMPD0000")

    assert series.coverage.label == "District of Columbia"
    assert series.coverage_min_percent == 100.0
    assert not [n for n in series.notices if "Coverage bottoms out" in n]
    assert [n for n in series.notices if "record no filing" in n]


def test_a_small_agency_with_two_quiet_months_keeps_them():
    """The floor's whole purpose, and the reason length alone will not do.

    A village department making three arrests a month has ordinary zeros and
    ordinary quiet quarters. Two of them swallow six arrests, which is not
    evidence of anything, so the months stay as they came.
    """
    quiet = [3.0, 2.0, 4.0, 0.0, 0.0, 3.0, 5.0, 2.0, 4.0, 3.0, 1.0, 2.0] * 3
    series = from_arrest_response(
        _arrest_response(quiet, first="01-2018", geography="Sleepy Hollow Police Department",
                         state="New York"),
        scope="NY0000000")

    assert not [n for n in series.notices if "record no filing" in n]
    assert [o.value for o in series.observations] == quiet
    assert (series.observation_start, series.observation_end) == ("01-2018", "12-2020")


def test_the_same_two_month_run_is_a_hole_at_a_department_that_files_thousands():
    """The rule is the mass, not the length: identical runs, opposite readings."""
    busy = [2000.0, 2100.0, 1900.0, 0.0, 0.0, 2050.0] * 6
    series = from_arrest_response(
        _arrest_response(busy, first="01-2018"), scope="DCMPD0000")

    assert [n for n in series.notices if "record no filing" in n]
    assert [o.value for o in series.observations][3:5] == [None, None]


def test_a_single_blank_month_at_volume_is_a_missing_return():
    """One blank month is enough, where a month normally holds thousands.

    There was a minimum run length of two, on the ground that one blank month is
    a month, and it made the mass floor unreachable for a run of one however
    large the level -- which is how a single skipped year passed at a department
    of three thousand officers while two consecutive ones were caught. The floor
    carries the case on its own: a department filing two thousand arrests a month
    does not arrest nobody in November.
    """
    values = [2000.0 + 10 * i for i in range(24)]
    values[10] = 0.0
    series = from_arrest_response(
        _arrest_response(values, first="01-2018"), scope="DCMPD0000")

    assert series.observations[10].value is None
    assert "11-2018" in next(n for n in series.notices if "record no filing" in n)


def test_a_single_blank_month_in_a_small_series_is_still_a_month():
    """And the floor is what keeps it: the price of dropping the run length.

    San Francisco clears two or three homicides a month, so a zero there is an
    ordinary month. One blank against a level of three swallows three filings,
    nowhere near the floor of twenty-five, so it keeps its value -- the same
    arithmetic that nulls the month above.
    """
    values = [3.0, 2.0, 4.0, 3.0, 2.0, 3.0] * 4
    values[10] = 0.0
    series = from_arrest_response(
        _arrest_response(values, first="01-2018"), scope="CA0380100",
        )

    assert series.observations[10].value == 0.0
    assert not [n for n in series.notices if "record no filing" in n]


def test_the_tail_still_filling_is_detectable_without_coverage():
    """09-2026 gives five arrests against 2,288 the month before.

    Coverage reports this at national scope, where the last month's percentage
    collapses. At agency scope the percentage is the state's and holds at 100,
    so the level of the surrounding filings is the only evidence there is.
    """
    series = from_arrest_response(
        _arrest_response(_washington()), scope="DCMPD0000")

    notice = next(n for n in series.notices if "still filling" in n)
    assert "09-2026 carries 5" in notice
    assert "drop it before comparing" in notice
    # A partial filing is still a filing: it keeps its value and its place in
    # the span, and is flagged rather than nulled. Nothing in the payload says
    # the five arrests did not happen.
    assert series.observations[-1].value == 5.0
    assert series.observation_end == "09-2026"


def test_a_flat_series_of_genuine_zeros_is_left_alone():
    """No filing anywhere means no level, and no level means no verdict.

    An agency that reports zero every month may be reporting zero every month.
    The rule says so rather than guessing, which is the same small-count limit
    the notebooks state.
    """
    series = from_arrest_response(
        _arrest_response([0.0] * 60, first="01-2018"), scope="DCMPD0000")

    assert [o.value for o in series.observations] == [0.0] * 60
    assert not [n for n in series.notices if "record no filing" in n]


def test_the_offence_notice_still_leads_a_series_with_holes():
    """The unconditional notice keeps its place; the new ones follow it."""
    series = from_arrest_response(
        _arrest_response(_washington()), scope="DCMPD0000")

    assert "ALL offences together" in series.notices[0]
    assert len([n for n in series.notices if "record no filing" in n]) == 1


# --- The offence on the mapped series ---------------------------------------


async def test_the_offence_shows_up_on_the_mapped_series(make_fbi_client):
    """Code and name both, and the notice names it too -- the labels do not."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_murder_state_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests("11", state="NY")
    series = from_arrest_response(response, scope="NY")

    assert series.offense == "11"
    assert series.offense_name == "Murder and Nonnegligent Homicide"
    assert series.geography == "New York"
    assert [o.value for o in series.observations] == [49, 37, 44]
    assert "Murder and Nonnegligent Homicide only (UCR arrest code 11)" in series.notices[0]
    assert "An arrest is NOT a clearance" in series.notices[0]


def test_the_mapper_takes_the_offence_from_the_payload_unless_told():
    """The client records the code; the tool also passes it, and that wins."""
    payload = FbiArrestResponse(offense="260", scope="TX", series=[])

    assert from_arrest_response(payload, scope="TX").offense == "260"
    assert from_arrest_response(payload, scope="TX").offense_name == (
        "Driving Under the Influence")
    assert from_arrest_response(payload, scope="TX", offense="11").offense == "11"
    assert from_arrest_response(None, scope="TX", offense="290").offense == "290"
    assert "code 260 at TX" in from_arrest_response(payload, scope="TX").notices[-1]


@pytest.mark.parametrize("code, says", [
    ("50", "AGGRAVATED assault"),
    ("20", "LEGACY rape definition"),
    ("23", "NO rape arrests nationally in 2023"),
    ("140", "Add 140-143"),
    ("150", "55,325 of the 918,020"),
    ("170", "Add 170-173"),
])
def test_a_code_whose_name_misleads_says_so(code, says):
    """The trap travels with the numbers, second only to what an arrest is."""
    response = _arrest_response([10.0, 12.0, 11.0], first="01-2023",
                                scope="TX", geography="Texas", state="Texas")
    series = from_arrest_response(response, scope="TX", offense=code)

    assert series.offense == code
    assert f"code {code})" in series.notices[0]
    assert says in series.notices[1]


@pytest.mark.parametrize("code", ["all", "11", "260", "310"])
def test_an_ordinary_code_carries_no_trap_notice(code):
    response = _arrest_response([10.0, 12.0, 11.0], first="01-2023",
                                scope="TX", geography="Texas", state="Texas")
    series = from_arrest_response(response, scope="TX", offense=code)

    assert not [n for n in series.notices if n.startswith("Code ")]


# --- The tool ----------------------------------------------------------------


def _patch_fbi(monkeypatch, handler: HttpHandler) -> None:
    """Serve ``fbi_arrests``' client from ``handler``: no key, no network."""
    async def fake_call_fbi(run):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     base_url=FBI_BASE_URL) as http:
            return await run(FbiClient(api_key="test-key", base_url=FBI_BASE_URL,
                                       client=http))

    monkeypatch.setattr(server, "_call_fbi", fake_call_fbi)


async def _arrest_tool():
    return next(t for t in await server.server.list_tools() if t.name == "fbi_arrests")


async def test_the_tool_passes_the_offence_to_the_path_and_the_response(monkeypatch):
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=_murder_agency_payload())

    _patch_fbi(monkeypatch, handler)
    series = await server.fbi_arrests(
        scope="NY0303000", offense="11", start="01-2023", end="03-2023")

    assert paths[0].endswith("/arrest/agency/NY0303000/11")
    assert (series.offense, series.offense_name) == (
        "11", "Murder and Nonnegligent Homicide")
    assert [o.value for o in series.observations] == [12, 16, 18]


async def test_the_tool_defaults_to_all(monkeypatch):
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=_state_payload())

    _patch_fbi(monkeypatch, handler)
    series = await server.fbi_arrests(scope="TX", start="01-2023", end="03-2023")

    assert paths[0].endswith("/arrest/state/TX/all")
    assert series.offense == "all"


async def test_the_tool_schema_enumerates_the_codes_and_names_them():
    """A model reads the codes as an enum and their names in the description."""
    offense = (await _arrest_tool()).input_schema["properties"]["offense"]

    assert offense["enum"] == list(ARREST_OFFENSES)
    assert offense["default"] == "all"
    for code, name in ARREST_OFFENSES.items():
        if code != "all":
            assert f"{code} {name}" in offense["description"]


async def test_the_tool_refuses_an_unlisted_code_before_any_request(monkeypatch):
    """The enum is checked at the tool boundary, so no request is spent on it."""
    from mcp.server.mcpserver.exceptions import ToolError

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=_national_payload())

    _patch_fbi(monkeypatch, handler)
    with pytest.raises(ToolError):
        await server.server.call_tool("fbi_arrests", {"offense": "homicide"})

    assert calls == []


# --- What the documentation claims -------------------------------------------
#
# Every docstring and description on the arrest path once said that clearances
# minus arrests bounds the share of clearances made by exceptional means. It
# does not: an arrest counts a person taken in on one occasion and a clearance
# an offence closed, one arrest can clear several offences and several arrests
# one, and most arrests are for offences with no clearance series, so total
# arrests are several times total clearances and the difference is not a floor
# or a ceiling on anything. These pin the correction.

_WRONG_CLAIMS = (
    r"minus arrests",
    r"arrests minus",
    r"\bbounds?\b.{0,60}exceptional",
    r"exceptional.{0,60}\bbound",
    r"clearances above arrests",
    r"clearances without one",
    r"clearing by exception",
    r"in aggregate only",
)


async def _arrest_texts() -> dict[str, str]:
    tool = await _arrest_tool()
    schema = FbiArrestSeries.model_json_schema()
    return {
        "clients.fbi module": fbi_client.__doc__,
        "FbiClient.get_arrests": FbiClient.get_arrests.__doc__,
        "FbiArrestResponse": FbiArrestResponse.__doc__,
        "FbiArrestResponse.offense": FbiArrestResponse.model_fields["offense"].description,
        "responses module": fbi_responses.__doc__,
        "FbiArrestSeries": FbiArrestSeries.__doc__,
        "FbiArrestSeries fields": " ".join(
            p.get("description", "") for p in schema["properties"].values()),
        "from_arrest_response": from_arrest_response.__doc__,
        "notice, all": " ".join(fbi_responses._arrest_notices("all")),
        "notice, 11": " ".join(fbi_responses._arrest_notices("11")),
        "code notes": " ".join(fbi_responses._ARREST_CODE_NOTES.values()),
        "tool description": tool.description,
        "tool arguments": " ".join(
            p.get("description", "") for p in tool.input_schema["properties"].values()),
    }


async def test_nothing_on_the_arrest_path_claims_arrests_bound_clearances():
    texts = await _arrest_texts()

    for where, text in texts.items():
        flat = " ".join((text or "").split()).casefold()
        for pattern in _WRONG_CLAIMS:
            assert not re.search(pattern, flat), f"{where} matches {pattern!r}"


async def test_the_correction_is_stated_where_a_caller_reads_it():
    """Not merely the old claim removed: the opposite said, in each place."""
    texts = {where: " ".join((text or "").split())
             for where, text in (await _arrest_texts()).items()}

    assert "NOT a clearance and CANNOT be differenced" in texts["tool description"]
    assert "An arrest is NOT a clearance" in texts["notice, all"]
    assert "not in total and not for the same offence" in texts["notice, 11"]
    assert "cannot be differenced against each other" in texts["clients.fbi module"]
    assert "not a clearance" in texts["FbiArrestResponse"]
    assert "cannot be differenced" in texts["FbiClient.get_arrests"]
    assert "different units" in texts["FbiArrestSeries"]


def test_the_module_records_where_the_codes_came_from_and_the_sum_check():
    doc = " ".join(fbi_client.__doc__.split())

    assert "https://cde.ucr.cjis.gov/LATEST/webapp/#/pages/docApi" in doc
    assert "lookup/offenses?type=arrest" in doc
    assert "7,184,021" in doc and "905" in doc


# --- A single offence's nulls ------------------------------------------------
#
# For one offence the CDE has no row for a month without an arrest and spells
# it null. National gambling-numbers arrests (code 172) came back null in 21 of
# the 24 months of 2023-2024; the other three hold 3, 1 and 1, which is the 5
# the FBI's own 2023 totals give that code. Read as missing returns, those
# nulls cost the series its span and produced a notice that the UCR data stops
# at 12-2023, under a max_data_date of 09/2026.

_PERIODS_2023_2024 = _months("01-2023", 24)


def _gambling_numbers_payload() -> dict[str, Any]:
    """``arrest/national/172`` for 01-2023..12-2024, as the API returned it.

    Keys in the API's month-major order are irrelevant here, so they are in
    date order; the values, nulls included, are the live ones.
    """
    counts = dict.fromkeys(_PERIODS_2023_2024, None) | {
        "05-2023": 3, "10-2023": 1, "12-2023": 1}
    rates = dict.fromkeys(_PERIODS_2023_2024, None) | {
        "05-2023": 0, "10-2023": 0, "12-2023": 0}
    coverage = [95.55, 95, 95.89, 95.94, 95.83, 95.95, 96, 96.25, 96.29, 96.24,
                96.23, 96.19, 96.71, 96.58, 96.08, 96.49, 96.4, 96.5, 96.53,
                96.48, 96.06, 96.47, 96.36, 96.39]
    population = [338357687] * 12 + [343551384] * 12
    participated = [
        323289818, 321444080, 324439456, 324614663, 324255129, 324648689,
        324828294, 325656835, 325802697, 325647783, 325592421, 325455692,
        332244501, 331795480, 330071739, 331487745, 331170260, 331519599,
        331619936, 331442375, 330019722, 331422525, 331062561, 331158128]
    return {
        "rates": {"United States Arrests": rates},
        "actuals": {"United States Arrests": counts},
        "tooltips": {
            "leftYAxisHeaders": _headers(),
            "Percent of Population Coverage": {
                "United States": dict(zip(_PERIODS_2023_2024, coverage))},
        },
        "populations": {
            "population": {"United States": dict(zip(_PERIODS_2023_2024, population))},
            "participated_population": {
                "United States": dict(zip(_PERIODS_2023_2024, participated))},
        },
        "cde_properties": _properties(),
    }


async def _gambling_numbers(make_fbi_client, unit: str = "count") -> FbiArrestSeries:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_gambling_numbers_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests("172", start="01-2023", end="12-2024")
    return from_arrest_response(response, scope="national", unit=unit)


async def test_a_single_offences_nulls_are_months_with_no_arrest(make_fbi_client):
    """The months sum to the FBI's own total, and the span is the window."""
    series = await _gambling_numbers(make_fbi_client)

    values = [o.value for o in series.observations]
    assert None not in values
    assert sum(values[:12]) == 5            # the 2023 total in the CDE's breakdown
    assert sum(values[12:]) == 0
    assert (series.observation_start, series.observation_end) == ("01-2023", "12-2024")


async def test_a_single_offence_gets_no_false_data_stops_notice(make_fbi_client):
    """max_data_date is 09/2026; nothing about 2024 is past it."""
    series = await _gambling_numbers(make_fbi_client)

    assert not [n for n in series.notices if "past the last filing" in n]
    assert not [n for n in series.notices if "record no filing" in n]
    notice = next(n for n in series.notices if "spells a month with no arrest" in n)
    assert "21 of the 24 months" in notice
    assert "participated population is above zero" in notice


async def test_a_single_offences_null_rate_is_a_zero_rate_too(make_fbi_client):
    series = await _gambling_numbers(make_fbi_client, unit="rate")

    assert [o.value for o in series.observations] == [0.0] * 24


def _one_code(values: list[float | None], participated: list[float | None], *,
              first: str, max_data_date: str = "09/2026", scope: str = "CA0194200",
              geography: str = "Los Angeles Police Department",
              offense: str = "11") -> FbiArrestResponse:
    """A single code's arrests with the agency's own participated population.

    Coverage is the state's, flat and complete, as at agency scope: it cannot
    say whether the agency reported. The participated population can.
    """
    periods = _months(first, len(values))

    def points(source):
        return [FbiObservation(period=p, value=v) for p, v in zip(periods, source)]

    return FbiArrestResponse(offense=offense, scope=scope, max_data_date=max_data_date,
                             series=[
        FbiSeries(label=f"{geography} Arrests", scope=scope, measure="arrests",
                  unit="count", observations=points(values)),
        FbiSeries(label="California", scope=scope, measure="value", unit="percent",
                  observations=points([99.9] * len(values))),
        FbiSeries(label=geography, scope=scope, measure="value", unit="people",
                  observations=points([3_800_000.0] * len(values))),
        FbiSeries(label=geography, scope=scope, measure="value",
                  unit=fbi_client.PARTICIPATED, observations=points(participated)),
    ])


def test_a_month_with_no_participated_population_stays_null():
    """Los Angeles' twelve null months of 'all' are the twelve with none.

    A month the scope published no participated population for is a month
    nobody reported, so its null is not a zero-arrest month.
    """
    values = [2.0, None, 1.0, None, None, 3.0]
    participated = [3.8e6, 3.8e6, 3.8e6, None, None, 3.8e6]
    series = from_arrest_response(
        _one_code(values, participated, first="01-2021"), scope="CA0194200")

    assert [o.value for o in series.observations] == [2.0, 0.0, 1.0, None, None, 3.0]
    notice = next(n for n in series.notices if "no participated population" in n)
    assert ("2 months have no participated population for Los Angeles Police "
            "Department (04-2021..05-2021)") in notice
    assert "1 of the 6 months" in next(
        n for n in series.notices if "spells a month with no arrest" in n)


def test_months_past_max_data_date_stay_null_and_say_why():
    values = [950.0, 900.0, 40.0, None, None, None]
    series = from_arrest_response(
        _one_code(values, [3.8e6] * 6, first="07-2026"), scope="CA0194200")

    assert [o.value for o in series.observations] == [950.0, 900.0, 40.0, None, None, None]
    assert series.observation_end == "09-2026"
    notice = next(n for n in series.notices if "past max_data_date" in n)
    assert "3 months past max_data_date (09/2026)" in notice
    assert "10-2026..12-2026" in notice
    # The vintage month itself is still filling, and says so.
    assert [n for n in series.notices if "09-2026 carries 40" in n]


def test_the_total_keeps_its_nulls():
    """'all' is left as it was: its nulls are missing returns, not zeros."""
    values = [2000.0, None, 2100.0, 2050.0]
    series = from_arrest_response(
        _one_code(values, [3.8e6] * 4, first="01-2023", offense="all"),
        scope="CA0194200")

    assert series.observations[1].value is None
    assert not [n for n in series.notices if "spells a month with no arrest" in n]


# --- A single offence's quiet final months -----------------------------------


@pytest.mark.parametrize("blank", [0.0, None])
def test_a_rare_codes_quiet_final_months_are_kept(blank):
    """Involuntary servitude in Texas: five quiet months at the end are five
    ordinary months, not a window running past the data.

    The trailing run used to be taken at any length and without the mass test,
    which was safe for 'all' -- never genuinely 0 -- and nulled these.
    """
    values = [blank, 1.0, blank, 2.0, blank, blank, 1.0, blank, blank, blank, blank, blank]
    response = _arrest_response(values, first="01-2023", scope="TX",
                                geography="Texas", state="Texas", coverage=98.7)
    series = from_arrest_response(response, scope="TX", offense="102")

    assert [o.value for o in series.observations] == [
        v if v is not None else 0.0 for v in values]
    assert series.observation_end == "12-2023"
    assert not [n for n in series.notices if "past the last filing" in n]


@pytest.mark.parametrize("blank, spelled", [
    # The CDE sent zeros: its padding for a missing return, and the notice
    # says so -- not that nulls were read as zero, which none were.
    (0.0, "The CDE spells a missing return as 0 rather than as null"),
    (None, "They came back null"),
])
def test_a_single_code_that_stops_at_volume_is_still_caught(blank, spelled):
    """The mass test still applies to the trailing run: six blank months at a
    thousand murders' worth of arrests a month is a missing return."""
    values = [1000.0 + 10 * i for i in range(18)] + [blank] * 6
    response = _arrest_response(values, first="01-2023", scope="TX",
                                geography="Texas", state="Texas", coverage=98.7)
    series = from_arrest_response(response, scope="TX", offense="11")

    assert [o.value for o in series.observations][-6:] == [None] * 6
    assert series.observation_end == "06-2024"
    notice = next(n for n in series.notices if "record no filing" in n)
    assert "07-2024..12-2024" in notice
    assert spelled in notice
    other = ("They came back null" if blank == 0.0
             else "The CDE spells a missing return as 0")
    assert other not in notice
    assert not [n for n in series.notices if "past the last filing" in n]
    # Nulled by the rule, so not also reported as zero arrests.
    assert not [n for n in series.notices if "returned as 0 arrests" in n]


def test_the_documentation_describes_what_the_rule_does_for_one_offence():
    """It used to say the rule 'keeps more of their zeros' -- there were no
    zeros to keep, and the trailing rule nulled at any level."""
    module = " ".join(fbi_client.__doc__.split())
    method = " ".join(FbiClient.get_arrests.__doc__.split())
    field = FbiArrestSeries.model_fields["observations"].description

    assert "keeps more of their zeros" not in module
    assert "a month with no arrest is null, not 0" in module
    assert "the one window checked" in method
    assert "the one window checked" in fbi_responses._arrest_notices("11")[0]
    assert "spells a month with no arrest for it as null" in field


# --- The rates' denominator ---------------------------------------------------
#
# The CDE's rates divide by the participated population -- the people living
# where agencies reported -- and not by the resident population. Nationally in
# January 2023, 580,792 arrests over 323,289,818 is the API's 179.65; over
# 338,357,687 residents it would be 171.65.


async def test_the_participated_population_is_carried_as_its_own_series(make_fbi_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_national_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests()

    participated = [s for s in response.series if s.unit == fbi_client.PARTICIPATED]
    assert [s.label for s in participated] == ["United States"]
    assert [o.value for o in participated[0].observations] == [
        323289818, 321444080, 324439456]


async def test_the_rate_recomputes_from_the_participated_population(make_fbi_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_national_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests()
    counts = from_arrest_response(response, scope="national")
    rates = from_arrest_response(response, scope="national", unit="rate")

    denominator = rates.participated_population
    assert denominator is not None and denominator.unit == fbi_client.PARTICIPATED
    for count, rate, participants, residents in zip(
            counts.observations, rates.observations, denominator.observations,
            rates.population.observations):
        assert round(1e5 * count.value / participants.value, 2) == rate.value
        assert round(1e5 * count.value / residents.value, 2) != rate.value
    # Coverage is the one over the other.
    assert round(100 * denominator.observations[0].value
                 / rates.population.observations[0].value, 2) == 95.55


def _homicide_national_payload() -> dict[str, Any]:
    """``summarized/national/homicide``, 01-2023..03-2023, as the API returned it."""
    periods = ["01-2023", "02-2023", "03-2023"]

    def block(values):
        return dict(zip(periods, values))

    return {
        "offenses": {
            "actuals": {"United States Offenses": block([1660, 1369, 1557]),
                        "United States Clearances": block([1007, 873, 1001])},
            "rates": {"United States Offenses": block([0.51, 0.43, 0.48]),
                      "United States Clearances": block([0.31, 0.27, 0.31])},
        },
        "tooltips": {"Percent of Population Coverage": {
            "United States": block([95.55, 95, 95.89])}},
        "populations": {
            "population": {"United States": block([338357687] * 3)},
            "participated_population": {
                "United States": block([323289818, 321444080, 324439456])},
        },
        "cde_properties": _properties(),
    }


async def test_the_offence_rate_divides_by_the_participated_population_too(
        make_fbi_client):
    """Same payload family, same denominator: 1,660 homicides over 323,289,818
    participants is the API's 0.51; over the residents it would be 0.49."""
    from mcp_server.responses.fbi import from_offense_response

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_homicide_national_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_offenses("homicide", start="01-2023", end="03-2023")
    counts = from_offense_response(response, offense="homicide", scope="national")
    rates = from_offense_response(response, offense="homicide", scope="national",
                                  unit="rate")

    denominator = rates.participated_population
    assert denominator is not None
    assert [o.value for o in denominator.observations] == [
        323289818, 321444080, 324439456]
    for count, rate, participants in zip(counts.observations, rates.observations,
                                         denominator.observations):
        assert round(1e5 * count.value / participants.value, 2) == rate.value
    assert round(1e5 * 1660 / 338357687, 2) != 0.51
    assert "NOT what the rate divides by" in (
        type(rates).model_fields["population"].description)


async def test_no_tool_calls_a_rate_per_resident():
    tools = {t.name: t for t in await server.server.list_tools()}

    for name in ("fbi_offenses", "fbi_arrests"):
        unit = tools[name].input_schema["properties"]["unit"]["description"]
        assert "residents of the scope" not in unit
        assert "people living where agencies reported" in unit
        assert "PARTICIPATED population" in tools[name].description


# --- Calling the tool positionally --------------------------------------------


async def test_a_positional_call_from_before_offences_still_binds(monkeypatch):
    """(scope, unit, start, end) was the signature; 'offense' goes after it."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=_state_payload())

    _patch_fbi(monkeypatch, handler)
    series = await server.fbi_arrests("TX", "rate", "01-2023", "03-2023")

    assert paths[0].endswith("/arrest/state/TX/all")
    assert series.unit == "rate per 100,000"
    assert [o.value for o in series.observations] == [157.64, 147.66, 166.44]


# --- Corrections to the single-offence reading --------------------------------
#
# The single-offence reading above was verified against live payloads and
# found to overreach in five ways, each pinned here: it held an agency's
# trailing run to the mass test, though an agency's participated population
# carries on after it stops filing; it judged a rate in its own units, so one
# request's count and rate disagreed; it asked a wider geography whether an
# agency reported, and nulled a zero the agency filed; it passed the CDE's -1
# through as a rate; and its notices described nulls read as zero where the
# CDE had sent zeros, and zeros the rule then nulled.


def _san_francisco_murder_payload() -> dict[str, Any]:
    """``arrest/agency/CA0380100/11`` for 01-2022..12-2024, as the API returned it.

    The national comparison and California's populations are left out; the
    client drops the one and the mapper does not read the other. San
    Francisco filed no arrest of any kind in 2024 -- its ``all`` series is 0
    in all twelve months -- yet its participated population is published for
    every one of them, and max_data_date is 09/2026.
    """
    periods = _months("01-2022", 36)
    counts = [6, 1, 2, 0, 6, 6, 2, 6, 9, 9, 13, 12,
              6, 10, 0, 6, 4, 2, 2, 3, 2, 3, 8, 4] + [0] * 12
    rates = [0.78, 0.13, 0.26, 0, 0.78, 0.78, 0.26, 0.78, 1.18, 1.18, 1.7, 1.57,
             0.77, 1.28, 0, 0.77, 0.51, 0.26, 0.26, 0.38, 0.26, 0.38, 1.02, 0.51] + [0] * 12
    people = [764693] * 12 + [782846] * 12 + [802856] * 12
    california = [99.01, 98.68, 98.68, 98.68, 98.93, 97.85, 98.69, 98.97, 98.97, 99.13,
                  98.66, 98.98, 99.49, 96.39, 96.3, 96.37, 96.96, 96.53, 96.96, 99.42,
                  99.5, 99.42, 99.81, 99.88, 99.88, 99.56, 99.56, 99.83, 99.56, 99.63,
                  99.46, 99.63, 99.9, 99.63, 99.9, 99.9]
    agency = "San Francisco Police Department"

    def block(values):
        return dict(zip(periods, values))

    return {
        "rates": {"California Arrests": block([0.3] * 36),
                  f"{agency} Arrests": block(rates)},
        "actuals": {f"{agency} Arrests": block(counts)},
        "tooltips": {"leftYAxisHeaders": _headers(),
                     "Percent of Population Coverage": {
                         "California": block(california), agency: None}},
        "populations": {"population": {agency: block(people)},
                        "participated_population": {agency: block(people)}},
        "cde_properties": _properties(),
    }


async def _san_francisco(make_fbi_client, unit: str) -> FbiArrestSeries:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_san_francisco_murder_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests("11", ori="CA0380100",
                                            start="01-2022", end="12-2024")
    return from_arrest_response(response, scope="CA0380100", unit=unit, offense="11")


@pytest.mark.parametrize("unit", ["count", "rate"])
async def test_an_agency_that_stops_filing_ends_at_its_last_filing(make_fbi_client, unit):
    """San Francisco's 2024 is a missing return in the count and in the rate.

    With the trailing run held to the mass test the count only just caught it
    (twelve months at a level of about three is 36 against a floor of 25),
    and the rate, judged in its own units at about 0.4, came back as twelve
    0.0 rates ending 12-2024.
    """
    series = await _san_francisco(make_fbi_client, unit)

    values = [o.value for o in series.observations]
    assert values[24:] == [None] * 12
    assert None not in values[:24]
    assert series.observation_end == "12-2023"
    # The sentence says what the run is and what it is not. The window ends in
    # December 2024 and the programme's data runs to September 2026, so these
    # months are not the CDE padding a window it could not fill -- and at agency
    # scope nothing in the payload can say whether the department stopped filing
    # or the window ended on a quiet stretch, because the coverage carried is
    # the state's.
    notice = next(n for n in series.notices if "record no filing" in n)
    assert "The last 12 months of this window (01-2024..12-2024) record no filing" in notice
    assert "not the CDE padding a window it could not fill" in notice
    assert "AT AGENCY SCOPE" in notice
    assert not [n for n in series.notices if "past the last filing" in n]


def _counted(counts: list[float | None], *, first: str,
             participated: float | list[float | None] = 330_000_000.0,
             scope: str = "national", geography: str = "United States",
             state: str | None = None, offense: str = "11",
             max_data_date: str = "09/2026",
             rates: list[float | None] | None = None) -> FbiArrestResponse:
    """A single code's counts AND rates, the rate recomputed as the CDE does.

    The participated population is the scope's own unless *state* is given,
    in which case it is published for the state only, as a payload whose
    agency block was missing would carry it.

    *rates* overrides the recomputation, for the rates the CDE is not known to
    publish: -1 where the participated population is not 0, or a negative rate
    that is not -1 at all.
    """
    periods = _months(first, len(counts))
    shares = (participated if isinstance(participated, list)
              else [participated] * len(counts))
    if rates is None:
        rates = [None if c is None else (round(1e5 * c / p, 2) if p else -1.0)
                 for c, p in zip(counts, shares)]

    def points(source):
        return [FbiObservation(period=p, value=v) for p, v in zip(periods, source)]

    return FbiArrestResponse(offense=offense, scope=scope, max_data_date=max_data_date,
                             series=[
        FbiSeries(label=f"{geography} Arrests", scope=scope, measure="arrests",
                  unit="count", observations=points(counts)),
        FbiSeries(label=f"{geography} Arrests", scope=scope, measure="arrests",
                  unit="rate per 100,000", observations=points(rates)),
        FbiSeries(label=state or geography, scope=scope, measure="value",
                  unit=fbi_client.PARTICIPATED, observations=points(shares)),
    ])


def test_a_quiet_code_at_an_agency_that_stops_filing_is_still_caught():
    """About one arrest a month, then a year of nothing: twelve months swallow
    about twelve arrests, under the floor, so only the open tail catches it --
    and the agency's participated population, published throughout, cannot."""
    counts = [1.0, 0.0, 2.0, 1.0, 1.0, 0.0, 1.0, 2.0, 1.0, 0.0, 1.0, 1.0] * 2 + [0.0] * 12
    series = from_arrest_response(
        _counted(counts, first="01-2022", participated=250_000.0, scope="CA0000000",
                 geography="Smallville Police Department"),
        scope="CA0000000", offense="11")

    assert [o.value for o in series.observations][24:] == [None] * 12
    assert series.observation_end == "12-2023"
    assert [n for n in series.notices if "record no filing" in n]


def test_nationally_the_rate_is_nulled_where_the_count_is():
    """Six dark months at a thousand arrests a month: the count's run clears
    the floor, and the same months in the rate -- 0.3 per 100,000 each, far
    under it in its own units -- are nulled with it, not returned as 0.0."""
    counts = [1000.0 + 10 * i for i in range(18)] + [0.0] * 6
    response = _counted(counts, first="01-2023")
    count = from_arrest_response(response, scope="national", offense="11")
    rate = from_arrest_response(response, scope="national", unit="rate", offense="11")

    assert [o.value for o in rate.observations][-6:] == [None] * 6
    assert [o.value is None for o in rate.observations] == [
        o.value is None for o in count.observations]
    assert rate.observation_end == count.observation_end == "06-2024"
    assert [n for n in rate.notices if "record no filing" in n]


def test_a_rare_code_nationally_keeps_its_quiet_final_months_in_the_rate_too():
    """What the closed tail is for, unchanged: code 172's 2024 is zero arrests."""
    counts = [None] * 4 + [3.0] + [None] * 4 + [1.0, None, 1.0] + [None] * 12
    rate = from_arrest_response(_counted(counts, first="01-2023"), scope="national",
                                unit="rate", offense="172")

    assert [o.value for o in rate.observations] == [0.0] * 24
    assert rate.observation_end == "12-2024"


def test_a_states_participation_cannot_vouch_for_one_of_its_agencies():
    """An agency's own participated population missing, its state's present:
    the state reported, which says nothing about the agency, so the agency's
    nulls stay null rather than becoming zero arrests."""
    response = _counted([2.0, None, 1.0, 3.0], first="01-2023", participated=3.9e7,
                        scope="CA0194200", geography="Los Angeles Police Department",
                        state="California")
    series = from_arrest_response(response, scope="CA0194200", offense="11")

    assert [o.value for o in series.observations] == [2.0, None, 1.0, 3.0]
    notice = next(n for n in series.notices if "nothing to say whether" in n)
    assert "Los Angeles Police Department reported (02-2023)" in notice
    assert not [n for n in series.notices if "returned as 0 arrests" in n]


def _metro_transit_payload() -> dict[str, Any]:
    """``arrest/agency/DCMTP0000/30`` for 01-2021..12-2021, as the API returned it.

    The Metro Transit Police has no resident population: its population and
    participated population are 0 in every month, its rate is -1 in every
    month, and it files robbery arrests all the same -- including a 0 in April.
    The national comparison is left out; the client drops it.
    """
    periods = _months("01-2021", 12)
    agency = "Metro Transit Police"

    def block(values):
        return dict(zip(periods, values))

    return {
        "rates": {"District of Columbia Arrests": block([2.5] * 12),
                  f"{agency} Arrests": block([-1] * 12)},
        "actuals": {f"{agency} Arrests": block(
            [4, 8, 13, 0, 10, 12, 9, 12, 7, 15, 7, 10])},
        "tooltips": {"leftYAxisHeaders": _headers(),
                     "Percent of Population Coverage": {
                         "District of Columbia": block([100] * 12), agency: None}},
        "populations": {
            "population": {"District of Columbia": block([670050] * 12),
                           agency: block([0] * 12)},
            "participated_population": {"District of Columbia": block([670050] * 12),
                                        agency: block([0] * 12)},
        },
        "cde_properties": _properties(),
    }


async def _metro_transit(make_fbi_client, unit: str) -> FbiArrestSeries:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_metro_transit_payload())

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests("30", ori="DCMTP0000",
                                            start="01-2021", end="12-2021")
    return from_arrest_response(response, scope="DCMTP0000", unit=unit, offense="30")


async def test_a_zero_the_agency_filed_is_kept_whatever_its_population(make_fbi_client):
    """April 2021's 0 is the transit police's own filing, among 4 to 15 a
    month. It was nulled and blamed on nobody reporting, because the agency's
    participated population is 0 -- as it is in every month it files."""
    series = await _metro_transit(make_fbi_client, "count")

    assert [o.value for o in series.observations] == [
        4, 8, 13, 0, 10, 12, 9, 12, 7, 15, 7, 10]
    assert not [n for n in series.notices if "nobody reported" in n]
    assert not [n for n in series.notices if "nothing to say whether" in n]


async def test_a_rate_over_nobody_is_null_not_minus_one(make_fbi_client):
    """-1 is what the CDE publishes over a participated population of 0; left
    in place, twelve months of it sum to -12."""
    series = await _metro_transit(make_fbi_client, "rate")

    assert [o.value for o in series.observations] == [None] * 12
    assert series.observation_start is None
    notice = next(n for n in series.notices if "negative rate" in n)
    assert "12 months carry a negative rate (01-2021..12-2021)" in notice
    assert "participated population is 0" in notice
    # The count is untouched.
    count = await _metro_transit(make_fbi_client, "count")
    assert sum(o.value for o in count.observations) == 107


def test_the_total_rate_over_nobody_is_null_too():
    """'all' takes the same guard: the -1 is the denominator's, not the code's."""
    response = _counted([40.0, 38.0, 45.0], first="01-2021", participated=0.0,
                        scope="DCMTP0000", geography="Metro Transit Police",
                        offense="all")
    series = from_arrest_response(response, scope="DCMTP0000", unit="rate")

    assert [o.value for o in series.observations] == [None] * 3
    assert [n for n in series.notices if "negative rate" in n]


def test_the_offence_route_nulls_a_negative_rate_as_well():
    """The offence mapper shares the participated-population description, so it
    shares the guard: a negative rate is impossible on either route."""
    from clients.models.fbi import FbiOffenseResponse
    from mcp_server.responses.fbi import from_offense_response

    periods = _months("01-2021", 3)
    response = FbiOffenseResponse(offense="robbery", scope="DCMTP0000", series=[
        FbiSeries(label="Metro Transit Police Offenses", scope="DCMTP0000",
                  measure="offenses", unit="rate per 100,000",
                  observations=[FbiObservation(period=p, value=-1.0) for p in periods]),
    ])
    series = from_offense_response(response, offense="robbery", scope="DCMTP0000",
                                   unit="rate")

    assert [o.value for o in series.observations] == [None] * 3
    assert [n for n in series.notices if "negative rate" in n]


def test_nulls_the_rule_then_nulls_are_not_also_called_zero_arrests():
    """Code 20 nationally with 2018-2019 null: the nulls are read as zero
    arrests, the rule then nulls them as a missing return at 1,500 a month,
    and only the second notice may speak -- the first used to say the same 24
    months were returned as 0 arrests."""
    counts = [None] * 24 + [1500.0 + 5 * i for i in range(60)]
    series = from_arrest_response(_counted(counts, first="01-2018"), scope="national",
                                  offense="20")

    assert [o.value for o in series.observations][:24] == [None] * 24
    assert series.observation_start == "01-2020"
    assert not [n for n in series.notices if "returned as 0 arrests" in n]
    notice = next(n for n in series.notices if "record no filing" in n)
    assert "24 of the 84 months" in notice
    assert "They came back null" in notice


def test_the_zero_arrest_notice_counts_only_the_months_returned_as_zero():
    """Mixed, and what separates the two is the level, not the spelling.

    Nationally the CDE spells a month with no arrests as null, so for a code
    filing a handful a year a null is exactly that. This series is busy for a
    year and rare afterwards: the twelve-month run sits where a month normally
    holds thirty and swallows far more than any quiet stretch could, so it is a
    missing return; the two lone nulls sit where a month holds less than one and
    swallow nothing, so they come back as the zero-arrest months they are. Both
    sentences are on the response, and each counts only its own months.

    At volume the reading goes the other way, and the test above is the pair to
    this one: two thousand arrests a month makes a lone blank a missing return.
    """
    counts = ([30.0] * 12 + [None] * 12 + [0.4] * 8 + [None] + [0.4] * 7
              + [None] + [0.4] * 8)
    series = from_arrest_response(_counted(counts, first="01-2018"), scope="national",
                                  offense="172")

    zeroed = next(n for n in series.notices if "returned as 0 arrests" in n)
    assert "2 of the 49 months" in zeroed
    unfiled = next(n for n in series.notices if "record no filing" in n)
    assert "12 of the 49 months" in unfiled and "01-2019..12-2019" in unfiled

    values = [o.value for o in series.observations]
    assert values.count(0.0) == 2 and values.count(None) == 12
    assert [o.period for o in series.observations if o.value == 0.0] == ["09-2020", "05-2021"]


def test_an_upper_case_all_takes_the_totals_path():
    """The mapper normalises the code as the client does: a direct call with
    'ALL' is the total, whose nulls are missing returns, not zero arrests."""
    response = _counted([2000.0, None, 2100.0, 2050.0], first="01-2023",
                        scope="CA0194200", geography="Los Angeles Police Department",
                        participated=3.8e6, offense="all")
    series = from_arrest_response(response, scope="CA0194200", offense="ALL")

    assert series.offense == "all"
    assert series.observations[1].value is None
    assert "ALL offences together" in series.notices[0]
    assert from_arrest_response(response, scope="CA0194200", offense=11).offense == "11"


async def test_every_claim_of_the_null_spelling_is_qualified_as_national():
    """At agency scope the CDE sends 0 for a month with no arrest for one
    offence (San Francisco murder, 42 months; the NYPD's, 8); the null spelling
    is shown nationally only. Every place that states it says so."""
    texts = await _arrest_texts()
    texts["get_arrests"] = FbiClient.get_arrests.__doc__
    texts["_one_offence"] = fbi_responses._one_offence.__doc__
    claim = re.compile(r"spells a month with no arrest|a month with no arrest is null")
    seen = 0
    for where, text in texts.items():
        flat = " ".join((text or "").split())
        for match in claim.finditer(flat.casefold()):
            seen += 1
            before = flat.casefold()[max(0, match.start() - 80):match.start()]
            assert "nationally" in before, f"{where}: {flat[match.start() - 80:match.end()]!r}"
    assert seen >= 5


def test_the_documentation_states_only_what_the_payloads_show():
    """Three claims the saved payloads did not support, and their replacements."""
    client = " ".join(fbi_client.__doc__.split())
    responses = " ".join(fbi_responses.__doc__.split())
    unfiled = " ".join(fbi_responses._unfiled.__doc__.split())

    # Population lands on the published rate at small counts, where the two
    # decimals hide the gap: New York murder 10 of 12, California homicide 51
    # of 84. It misses only the high-count series.
    for doc in (client, responses):
        assert "population`` misses most national and state months" not in doc
        assert "misses most national and state months" not in doc
    assert "10 of 12 months of 2023" in client and "51 of 84" in client
    # No saved New York single-code payload covers 2018-2024: New York state
    # murder is 2023 only, and the NYPD's own is agency scope, where the two
    # populations are the same number.
    assert "single codes nationally and in New York over 2018-2024" not in client
    assert "code 20 nationally over 2018-2024 (84 of 84)" in client
    # Nothing supports "until 2010"; the SRS manual says 2009, and that the
    # data may still be stored.
    assert "until 2010" not in client
    assert "is no longer a required Part II offense" in client
    # An agency's trailing run is not cut at the data's end: max_data_date is
    # the national vintage, not the agency's last filing.
    assert "no longer in the series" not in unfiled
    assert "national or state scope only" in unfiled


async def test_the_tools_say_what_a_rate_over_nobody_comes_back_as():
    tools = {t.name: t for t in await server.server.list_tools()}

    for name in ("fbi_offenses", "fbi_arrests"):
        unit = tools[name].input_schema["properties"]["unit"]["description"]
        assert "-1" in unit and "null" in unit
    field = FbiArrestSeries.model_fields["participated_population"].description
    assert "-1" in field


async def test_a_null_at_an_agency_with_no_residents_is_not_blamed_on_nobody_reporting(
        make_fbi_client):
    """Its participated population is 0 in every month it files, so 0 cannot
    say it did not report. The null stays null, as the CDE sent it, and the
    notice says the payload cannot tell -- not that nobody reported."""
    payload = _metro_transit_payload()
    payload["actuals"]["Metro Transit Police Arrests"]["06-2021"] = None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with make_fbi_client(handler) as client:
        response = await client.get_arrests("30", ori="DCMTP0000",
                                            start="01-2021", end="12-2021")
    series = from_arrest_response(response, scope="DCMTP0000", offense="30")

    assert series.observations[5].value is None
    assert series.observations[3].value == 0
    assert not [n for n in series.notices if "nobody reported" in n]
    notice = next(n for n in series.notices if "nothing to say whether" in n)
    assert "Metro Transit Police reported (06-2021)" in notice
    assert "participated population is 0" in notice


# --- What a notice may claim, and what only the payload can say --------------
#
# The -1 the CDE publishes over a participated population of 0 is the only
# negative rate this source is known to send, and it has only ever been seen on
# the arrest route at agency scope. The notice explaining a negative rate
# asserted that account unconditionally: any negative value, at any scope, on
# either route, was told it was -1, that the participated population was 0, and
# that this was a transit or campus force -- three claims a national rate of
# -2.5 over 330 million participants contradicts.
#
# And a month nulled for that reason reaches the non-reporting rule as a null,
# which it cannot tell from the CDE's own blank, so an interior run of them was
# reported a second time as a return nobody sent -- with a spelling the CDE had
# not used, for months that carry a filing, and a span the response itself
# contradicts. The rule is now told which blanks are already accounted for.


def test_an_upper_case_all_on_the_payload_takes_the_totals_path_too():
    """``_arrest_code`` normalised the argument and not the payload's own field.

    The client writes it normalised, so nothing it returns needs this -- but a
    hand-built response does not have to, and with the argument omitted that
    field is the code the mapper works under. An 'ALL' there took the
    single-offence path and had the total's null read as 0 arrests, which is
    the one failure the function exists to prevent.
    """
    response = _counted([2000.0, None, 2100.0, 2050.0], first="01-2023",
                        scope="CA0194200", geography="Los Angeles Police Department",
                        participated=3.8e6, offense="ALL")
    series = from_arrest_response(response, scope="CA0194200")

    assert series.offense == "all"
    assert series.offense_name == ARREST_OFFENSES["all"]
    assert series.observations[1].value is None
    assert "ALL offences together" in series.notices[0]
    assert not [n for n in series.notices if "returned as 0 arrests" in n]


def test_a_negative_rate_that_is_not_minus_one_is_not_blamed_on_a_transit_force():
    """-2.5 nationally over 330 million participants: not -1, not a population
    of 0, and not an agency without residents. The notice said all three."""
    series = from_arrest_response(
        _counted([330_000.0] * 6, first="01-2023",
                 rates=[100.0, 100.0, -2.5, 100.0, 100.0, 100.0]),
        scope="national", unit="rate")

    assert series.observations[2].value is None
    notice = next(n for n in series.notices if "negative rate" in n)
    assert "transit or campus force" not in notice
    assert "participated population is 0, as it is in every month" not in notice
    assert "the participated population for United States that month is 330,000,000" \
        in notice


def test_a_minus_one_over_a_real_population_says_the_account_is_unestablished():
    """The value is the CDE's marker, the denominator is 330 million: the
    notice may explain what -1 means and may not assert it happened here."""
    series = from_arrest_response(
        _counted([330_000.0] * 6, first="01-2023", offense="all",
                 rates=[100.0, 100.0, -1.0, 100.0, 100.0, 100.0]),
        scope="national", unit="rate")

    notice = next(n for n in series.notices if "negative rate" in n)
    assert "that is not established here" in notice
    assert "330,000,000" in notice
    assert "participated population is 0, as it is in every month" not in notice


def test_the_offence_routes_negative_rate_notice_is_not_about_a_transit_force():
    """clients/fbi.py records that the offence route was never checked for the
    -1 at all, so a national homicide rate below zero cannot be one."""
    from clients.models.fbi import FbiOffenseResponse
    from mcp_server.responses.fbi import from_offense_response

    periods = _months("01-2023", 6)

    def points(values):
        return [FbiObservation(period=p, value=v) for p, v in zip(periods, values)]

    response = FbiOffenseResponse(offense="homicide", scope="national", series=[
        FbiSeries(label="United States Offenses", scope="national", measure="offenses",
                  unit="rate per 100,000",
                  observations=points([0.5, 0.6, -0.4, 0.5, 0.5, 0.6])),
        FbiSeries(label="United States", scope="national", measure="value",
                  unit=fbi_client.PARTICIPATED, observations=points([3.2e8] * 6)),
    ])
    series = from_offense_response(response, offense="homicide", scope="national",
                                  unit="rate")

    notice = next(n for n in series.notices if "negative rate" in n)
    assert "transit or campus force" not in notice
    assert "the participated population for United States that month is 320,000,000" \
        in notice


def test_an_interior_negative_rate_run_is_not_also_called_a_missing_return():
    """Four months whose participated population is 0 among filings of 300.

    The CDE sends -1 for those months and 300 arrests beside it, so they are
    not a return nobody sent: _defined nulls the rate, and the non-reporting
    rule used to null it again and say the CDE had spelled the run 0, that the
    months recorded no filing, and that the span named the filings rather than
    the window -- while observation_start and observation_end still spanned it.
    """
    participated = [670_050.0] * 3 + [0.0] * 4 + [670_050.0] * 5
    response = _counted([300.0] * 12, first="01-2023", participated=participated,
                        scope="DCMTP0000", geography="Metro Transit Police",
                        offense="all")
    series = from_arrest_response(response, scope="DCMTP0000", unit="rate")

    assert [o.value is None for o in series.observations] == (
        [False] * 3 + [True] * 4 + [False] * 5)
    assert (series.observation_start, series.observation_end) == ("01-2023", "12-2023")
    assert not [n for n in series.notices if "record no filing" in n]
    notice = next(n for n in series.notices if "negative rate" in n)
    assert "participated population is 0" in notice
    # The count is the evidence that those months were filed, and is untouched.
    count = from_arrest_response(response, scope="DCMTP0000", unit="count")
    assert [o.value for o in count.observations] == [300.0] * 12
    assert not [n for n in count.notices if "record no filing" in n]


def test_the_offence_route_does_not_call_a_negative_rate_run_a_missing_return():
    """The same interaction on the offence route, which shares both halves."""
    from clients.models.fbi import FbiOffenseResponse
    from mcp_server.responses.fbi import from_offense_response

    periods = _months("01-2023", 12)

    def points(values):
        return [FbiObservation(period=p, value=v) for p, v in zip(periods, values)]

    # A level the run has to clear the mass floor against: four blank months
    # at 10 per 100,000 swallow 40 against a floor of 25, so the rule would
    # have read them as a gap.
    rates = [10.0] * 3 + [-1.0] * 4 + [10.0] * 5
    response = FbiOffenseResponse(offense="robbery", scope="DCMTP0000", series=[
        FbiSeries(label="Metro Transit Police Offenses", scope="DCMTP0000",
                  measure="offenses", unit="rate per 100,000", observations=points(rates)),
        FbiSeries(label="Metro Transit Police", scope="DCMTP0000", measure="value",
                  unit=fbi_client.PARTICIPATED,
                  observations=points([670_050.0] * 3 + [0.0] * 4 + [670_050.0] * 5)),
    ])
    series = from_offense_response(response, offense="robbery", scope="DCMTP0000",
                                   unit="rate")

    assert [o.value is None for o in series.observations] == (
        [False] * 3 + [True] * 4 + [False] * 5)
    assert (series.observation_start, series.observation_end) == ("01-2023", "12-2023")
    assert not [n for n in series.notices if "record no filing" in n]
    assert [n for n in series.notices if "negative rate" in n]


async def test_an_mcp_caller_can_learn_that_an_agencys_trailing_run_is_nulled():
    """The behaviour that changed most, stated where a tool caller reads it.

    At agency scope a run reaching the end of the window is nulled whatever its
    length and however quiet the series, so observation_end can fall a single
    month short of the request. It was in the module and function docstrings
    alone, which an MCP caller never sees.
    """
    description = " ".join((await _arrest_tool()).description.split())
    field = " ".join(
        FbiArrestSeries.model_fields["observations"].description.split())

    for where, text in (("tool description", description), ("observations", field)):
        assert "agency scope" in text.casefold(), where
        assert "whatever its length" in text, where
        assert "observation_end" in text, where
