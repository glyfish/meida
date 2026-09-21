"""Tests for the FBI arrest route (``FbiClient.get_arrests`` and its mapper).

Uses ``httpx.MockTransport`` with payloads copied from live CDE responses, so
the suite never spends against the shared api.data.gov allowance.

The arrest route is the same payload family as ``summarized`` and differs in
exactly the two places that are easy to get wrong, so those are what is pinned
here:

* ``actuals`` and ``rates`` sit at the **top level**, with no ``offenses``
  wrapper. A reader copied from ``get_offenses`` finds nothing and returns an
  empty series rather than failing.
* The requested scope is listed **last** in ``rates``, where ``summarized``
  lists it after the comparisons that come first. Neither position is reliable,
  so the labels in ``actuals`` decide.

Alongside those: the vocabulary this route accepts (``all`` as the offence
segment, ``type=counts``, ``MM-YYYY`` dates), the month-major key order that
makes a multi-year series come back out of sequence, and the all-offence limit
that the mapper states on every response -- an arrest total cannot be
differenced against one offence's clearances.

The client factory is local rather than in ``conftest.py`` so that the key is
injected here: nothing in this module can read a real ``DATA_GOV_KEY`` or reach
the network.
"""
from __future__ import annotations

from typing import Any, Callable

import httpx
import pytest

from clients import FbiAPIError, FbiClient
from clients.models.fbi import (
    FbiArrestResponse, FbiObservation, FbiOffenseResponse, FbiSeries,
)
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


async def test_the_arrest_path_is_the_all_offence_route_with_type_counts(make_fbi_client):
    """``all`` is the only offence segment that answers, ``counts`` the only type.

    ``type`` is required -- omitting it is a 400 ``Invalid 'type'.`` -- and
    vestigial, since the payload carries the rates either way.
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_state_payload())

    async with make_fbi_client(handler) as client:
        await client.get_arrests(state="TX", start="01-2023", end="03-2023")

    assert seen["path"].endswith("/arrest/state/TX/all")
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
    assert len(response.series) == 4
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
    """The offence slugs of ``summarized`` do not transfer to this route."""
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


async def test_every_response_says_the_total_is_all_offences(make_fbi_client):
    """The limit is always true, so it is always stated.

    Differencing an all-offence arrest total against one offence's clearances
    is wrong in a way no value in the payload reveals.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_state_payload())

    series = await _mapped(handler, make_fbi_client)

    assert "all-offence arrest total" in series.notices[0]
    assert "single offence's clearances" in series.notices[0]


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
    assert "all-offence arrest total" in series.notices[0]
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


# --- What the pairing buys ---------------------------------------------------


def test_clearances_above_arrests_are_clearances_without_one():
    """The reason this route was added, as arithmetic.

    ``summarized`` reports one combined clearance series and never splits it. A
    clearance by exceptional means -- offender dead, victim uncooperative,
    extradition refused -- is a clearance with no arrest behind it, and a
    department under pressure can move it without moving the other. Arrests
    beside clearances bound that share from outside: whatever part of the
    clearances exceeds the arrests cannot have been cleared by arrest.
    """
    def _points(pairs):
        return [FbiObservation(period=p, value=v) for p, v in pairs]

    clearances = FbiOffenseResponse(offense="violent-crime", scope="TX", series=[
        FbiSeries(label="Texas Clearances", scope="TX", measure="clearances",
                  unit="count", observations=_points(
                      [("01-2023", 9000.0), ("02-2023", 12000.0)]))])
    arrests = FbiArrestResponse(scope="TX", series=[
        FbiSeries(label="Texas Arrests", scope="TX", measure="arrests",
                  unit="count", observations=_points(
                      [("01-2023", 9500.0), ("02-2023", 9400.0)]))])

    cleared = {o.period: o.value for s in clearances.series for o in s.observations}
    arrested = {o.period: o.value for s in arrests.series for o in s.observations}
    floor = {period: max(0.0, value - arrested[period])
             for period, value in cleared.items()}

    # January's clearances all fit inside its arrests, so nothing is forced to
    # be exceptional. February's do not: at least 2,600 were cleared with no
    # arrest anywhere in the month, which the clearance series alone hides.
    assert floor == {"01-2023": 0.0, "02-2023": 2600.0}
