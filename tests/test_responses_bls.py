"""Tests for the published BLS response models (``mcp_server/responses/bls.py``).

Pure and offline: navi models are hand-built, mapped, and inspected. What these
pin down is the contract meida publishes -- envelope removal, snake_case names
with no vendor aliases, the derived ISO date, and that nothing (observation,
footnote content, catalog extra, calculation) is lost on the way through.
"""
from __future__ import annotations

import re

import pytest

from clients.models.bls import (
    Aspect,
    BlsSeriesResponse,
    BlsSurveysResponse,
    Calculations,
    Catalog,
    Footnote,
    Observation,
    Series,
    SeriesResults,
    Survey,
    SurveyResults,
)

from mcp_server.responses import bls


# --- builders ----------------------------------------------------------------


def _observation(year: str = "2024", period: str = "M03", **kwargs) -> Observation:
    fields = {
        "year": year,
        "period": period,
        "period_name": "March",
        "value": "3.8",
    }
    fields.update(kwargs)
    return Observation(**fields)


def _series_response(*series: Series) -> BlsSeriesResponse:
    return BlsSeriesResponse(
        status="REQUEST_SUCCEEDED",
        response_time=87,
        message=[],
        results=SeriesResults(series=list(series)),
    )


def _surveys_response(*surveys: Survey) -> BlsSurveysResponse:
    return BlsSurveysResponse(
        status="REQUEST_SUCCEEDED",
        response_time=12,
        message=["advisory"],
        results=SurveyResults(survey=list(surveys)),
    )


# --- envelope removal --------------------------------------------------------


def test_series_response_drops_transport_envelope():
    dumped = bls.from_bls_series_response(
        _series_response(Series(series_id="LNS14000000", data=[_observation()]))
    ).model_dump()

    # message survives as `notices` -- it carries truncation warnings on a
    # SUCCESSFUL response, so it is data, not transport.
    assert set(dumped) == {"series", "notices"}
    for gone in ("status", "responseTime", "response_time", "message", "Results", "results"):
        assert gone not in dumped


def test_surveys_response_drops_transport_envelope():
    dumped = bls.from_bls_surveys_response(
        _surveys_response(Survey(survey_abbreviation="AP", survey_name="Average Price Data"))
    ).model_dump()

    assert set(dumped) == {"surveys", "notices"}


def test_results_nesting_is_flattened_but_series_list_survives():
    payload = _series_response(
        Series(series_id="A", data=[_observation()]),
        Series(series_id="B", data=[_observation(period="M04")]),
    )

    mapped = bls.from_bls_series_response(payload)

    # Results.series[].data[] -> series[].observations[]: one level of envelope
    # removed, the real list-of-series structure kept.
    assert [s.series_id for s in mapped.series] == ["A", "B"]
    assert [len(s.observations) for s in mapped.series] == [1, 1]


# --- field renaming ----------------------------------------------------------


def test_series_id_is_snake_case_and_data_becomes_observations():
    dumped = bls.from_bls_series_response(
        _series_response(Series(series_id="LNS14000000", data=[_observation()]))
    ).model_dump()

    series = dumped["series"][0]
    assert series["series_id"] == "LNS14000000"
    assert "seriesID" not in series
    assert "data" not in series
    assert len(series["observations"]) == 1


def test_observation_keeps_period_name_without_vendor_spelling():
    observation = bls.from_observation(_observation())
    dumped = observation.model_dump()

    assert dumped["period_name"] == "March"
    assert "periodName" not in dumped
    # The vendor's own fields stay beside the derived date.
    assert dumped["year"] == "2024"
    assert dumped["period"] == "M03"


def test_survey_flags_are_renamed_and_parsed_to_booleans():
    payload = _surveys_response(
        Survey(
            survey_abbreviation="TU",
            survey_name="American Time Use",
            allows_net_change="false",
            allows_percent_change="true",
            has_annual_averages="false",
        )
    )

    dumped = bls.from_bls_survey_response(payload).model_dump()["survey"]

    assert dumped["allows_net_change"] is False
    assert dumped["allows_percent_change"] is True
    assert dumped["has_annual_averages"] is False
    for gone in ("allowsNetChange", "allowsPercentChange", "hasAnnualAverages"):
        assert gone not in dumped


def test_unreported_survey_flags_are_none_not_false():
    survey = bls.from_survey(Survey(survey_abbreviation="AP", survey_name="Average Price"))

    assert survey.allows_net_change is None
    assert survey.allows_percent_change is None
    assert survey.has_annual_averages is None


@pytest.mark.parametrize(
    "raw, expected",
    [("true", True), ("TRUE", True), ("false", False), (" False ", False), (True, True), (None, None), ("maybe", None)],
)
def test_to_bool_parses_vendor_strings(raw, expected):
    assert bls._to_bool(raw) is expected


# --- date derivation ---------------------------------------------------------


@pytest.mark.parametrize(
    "period, expected_date, expected_type",
    [
        ("M01", "2024-01-01", "monthly"),
        ("M03", "2024-03-01", "monthly"),
        ("M12", "2024-12-01", "monthly"),
        ("M13", "2024-01-01", "annual_average"),
        ("Q01", "2024-01-01", "quarterly"),
        ("Q02", "2024-04-01", "quarterly"),
        ("Q03", "2024-07-01", "quarterly"),
        ("Q04", "2024-10-01", "quarterly"),
        ("Q05", "2024-01-01", "annual_average"),
        ("S01", "2024-01-01", "semiannual"),
        ("S02", "2024-07-01", "semiannual"),
        ("S03", "2024-01-01", "annual_average"),
        ("A01", "2024-01-01", "annual"),
        ("m06", "2024-06-01", "monthly"),
        (" Q03 ", "2024-07-01", "quarterly"),
    ],
)
def test_every_bls_period_prefix_maps_to_a_date(period, expected_date, expected_type):
    assert bls.derive_observation_date("2024", period) == expected_date
    assert bls.derive_period_type(period) == expected_type


@pytest.mark.parametrize("period", ["M14", "Q06", "S04", "X01", "", "M1", None, 3])
def test_unrecognised_period_yields_none_not_a_guess(period):
    assert bls.derive_observation_date("2024", period) is None
    assert bls.derive_period_type(period) == "unknown"


@pytest.mark.parametrize("year", ["", "24", "20244", "two thousand", None, 2024])
def test_unusable_year_yields_none_not_a_guess(year):
    assert bls.derive_observation_date(year, "M03") is None


def test_unrecognised_period_still_publishes_the_observation():
    observation = bls.from_observation(_observation(period="X99", period_name="Whatever"))

    assert observation.date is None
    assert observation.period_type == "unknown"
    # Nothing is dropped: the raw fields and the value are still there.
    assert observation.period == "X99"
    assert observation.year == "2024"
    assert observation.value == "3.8"


def test_annual_average_row_shares_a_date_with_the_first_period():
    monthly = bls.from_observation(_observation(period="M01"))
    average = bls.from_observation(_observation(period="M13"))

    assert monthly.date == average.date == "2024-01-01"
    assert (monthly.period_type, average.period_type) == ("monthly", "annual_average")


# --- house shape -------------------------------------------------------------


def test_observation_uses_the_house_date_value_shape():
    observation = bls.from_observation(_observation(value="3.8"))

    assert observation.date == "2024-03-01"
    assert observation.value == "3.8"
    assert isinstance(observation.value, str)


def test_latest_flag_becomes_a_boolean():
    assert bls.from_observation(_observation(latest="true")).latest is True
    assert bls.from_observation(_observation()).latest is False


# --- optional nested payloads survive ----------------------------------------


def test_catalog_survives_including_survey_specific_extras():
    catalog = Catalog(
        series_title="(Seas) Unemployment Rate",
        series_id="LNS14000000",
        seasonality="Seasonally Adjusted",
        survey_name="Labor Force Statistics from the Current Population Survey",
        survey_abbreviation="LN",
        measure_data_type="Percent or rate",
        demographic_age="16 years and over",
        commerce_industry="All Industries",
    )

    mapped = bls.from_catalog(catalog)

    assert mapped.series_title == "(Seas) Unemployment Rate"
    assert mapped.survey_abbreviation == "LN"
    assert mapped.additional_fields == {
        "demographic_age": "16 years and over",
        "commerce_industry": "All Industries",
    }


def test_calculations_survive():
    observation = _observation(
        calculations=Calculations(
            net_changes={"1": "0.1", "12": "0.3"},
            pct_changes={"1": "2.7", "12": "8.6"},
        )
    )

    mapped = bls.from_observation(observation)

    assert mapped.calculations.net_changes == {"1": "0.1", "12": "0.3"}
    assert mapped.calculations.pct_changes == {"1": "2.7", "12": "8.6"}


def test_calculations_absent_when_not_requested():
    assert bls.from_observation(_observation()).calculations is None


def test_aspects_survive_with_their_footnotes():
    observation = _observation(
        aspects=[
            Aspect(
                name="Standard error",
                value="0.2",
                footnotes=[Footnote(code="E", text="Estimated.")],
            )
        ]
    )

    mapped = bls.from_observation(observation)

    assert [a.name for a in mapped.aspects] == ["Standard error"]
    assert mapped.aspects[0].value == "0.2"
    assert mapped.aspects[0].footnotes[0].code == "E"


def test_footnotes_keep_content_and_drop_the_empty_padding():
    observation = _observation(
        footnotes=[Footnote(), Footnote(code="P", text="Preliminary."), Footnote()]
    )

    mapped = bls.from_observation(observation)

    assert [(f.code, f.text) for f in mapped.footnotes] == [("P", "Preliminary.")]


def test_annual_average_rows_are_kept_when_requested():
    payload = _series_response(
        Series(
            series_id="LNS14000000",
            data=[_observation(period="M13", period_name="Annual"), _observation(period="M12")],
        )
    )

    mapped = bls.from_bls_series_response(payload)

    assert [o.period for o in mapped.series[0].observations] == ["M13", "M12"]


# --- nothing is dropped ------------------------------------------------------


def test_every_observation_is_carried_over_in_order():
    months = [f"M{m:02d}" for m in range(12, 0, -1)]
    payload = _series_response(
        Series(
            series_id="LNS14000000",
            data=[_observation(year="2024", period=period) for period in months],
        )
    )

    observations = bls.from_bls_series_response(payload).series[0].observations

    assert len(observations) == len(months)
    assert [o.period for o in observations] == months
    assert [o.date for o in observations] == [f"2024-{m:02d}-01" for m in range(12, 0, -1)]


def test_multiple_series_all_survive():
    payload = _series_response(
        *[Series(series_id=f"S{i}", data=[_observation()]) for i in range(50)]
    )

    assert len(bls.from_bls_series_response(payload).series) == 50


def test_all_surveys_are_carried_over():
    payload = _surveys_response(
        *[Survey(survey_abbreviation=f"S{i}", survey_name=f"Survey {i}") for i in range(23)]
    )

    surveys = bls.from_bls_surveys_response(payload).surveys

    assert len(surveys) == 23
    assert surveys[0].survey_abbreviation == "S0"


# --- list vs single survey ---------------------------------------------------


def test_survey_list_and_survey_info_are_distinct_shapes():
    payload = _surveys_response(
        Survey(survey_abbreviation="TU", survey_name="American Time Use", allows_net_change="false")
    )

    listed = bls.from_bls_surveys_response(payload).model_dump()
    single = bls.from_bls_survey_response(payload).model_dump()

    assert list(listed) == ["surveys", "notices"] and isinstance(listed["surveys"], list)
    assert list(single) == ["survey", "notices"] and isinstance(single["survey"], dict)
    assert single["survey"]["survey_abbreviation"] == "TU"


def test_survey_info_takes_the_first_when_bls_returns_several():
    payload = _surveys_response(
        Survey(survey_abbreviation="TU", survey_name="American Time Use"),
        Survey(survey_abbreviation="AP", survey_name="Average Price"),
    )

    assert bls.from_bls_survey_response(payload).survey.survey_abbreviation == "TU"


# --- empty / None inputs -----------------------------------------------------


def test_mappers_accept_none():
    assert bls.from_bls_series_response(None).series == []
    assert bls.from_bls_surveys_response(None).surveys == []
    assert bls.from_bls_survey_response(None).survey is None
    assert bls.from_catalog(None) is None
    assert bls.from_calculations(None) is None
    assert bls.from_footnote(None) is None
    assert bls.from_footnotes(None) == []


def test_mappers_accept_empty_results():
    assert bls.from_bls_series_response(_series_response()).series == []
    assert bls.from_bls_surveys_response(_surveys_response()).surveys == []
    assert bls.from_bls_survey_response(_surveys_response()).survey is None


def test_series_without_observations_maps_to_an_empty_list():
    # What bls_popular_series returns: ids only, no data key.
    payload = _series_response(Series(series_id="CUUR0000SA0"))

    mapped = bls.from_bls_series_response(payload)

    assert mapped.series[0].series_id == "CUUR0000SA0"
    assert mapped.series[0].observations == []
    assert mapped.series[0].catalog is None


def test_empty_footnote_only_list_maps_to_empty():
    assert bls.from_observation(_observation(footnotes=[Footnote()])).footnotes == []


# --- published schema --------------------------------------------------------


_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")

_MODELS = [
    bls.BlsSeriesData,
    bls.BlsSeries,
    bls.BlsObservation,
    bls.BlsCatalog,
    bls.BlsCalculations,
    bls.BlsAspect,
    bls.BlsFootnote,
    bls.BlsSurvey,
    bls.BlsSurveyList,
    bls.BlsSurveyInfo,
]


def _property_names(schema: dict) -> list[str]:
    names: list[str] = []
    for definition in list(schema.get("$defs", {}).values()) + [schema]:
        names.extend(definition.get("properties", {}))
    return names


@pytest.mark.parametrize("model", _MODELS, ids=lambda m: m.__name__)
def test_schema_property_names_are_snake_case(model):
    names = _property_names(model.model_json_schema())

    assert names
    assert [name for name in names if not _SNAKE_CASE.match(name)] == []


@pytest.mark.parametrize("model", _MODELS, ids=lambda m: m.__name__)
def test_schema_carries_no_vendor_spellings(model):
    names = _property_names(model.model_json_schema())

    for vendor in (
        "Results",
        "responseTime",
        "seriesID",
        "periodName",
        "allowsNetChange",
        "allowsPercentChange",
        "hasAnnualAverages",
        "status",
        "message",
    ):
        assert vendor not in names


@pytest.mark.parametrize("model", _MODELS, ids=lambda m: m.__name__)
def test_every_model_and_field_is_documented(model):
    schema = model.model_json_schema()

    for definition in list(schema.get("$defs", {}).values()) + [schema]:
        if "properties" not in definition:
            continue
        assert definition.get("description"), definition.get("title")
        for name, prop in definition["properties"].items():
            assert prop.get("description"), f"{definition.get('title')}.{name}"


# --- Captured vendor payloads ------------------------------------------------
#
# Every test above maps a hand-built navi model. These run the real captured BLS
# responses in tests/fixtures/bls/ through the mappers instead, which is what
# pins behaviour against what BLS actually sends -- and what catches a regression
# in the advisory handling that hand-built inputs never exercise.

import json
from pathlib import Path

_FIXTURES = Path(__file__).parent / "fixtures" / "bls"


def _fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


def test_full_series_fixture_preserves_every_observation():
    payload = BlsSeriesResponse.model_validate(_fixture("series_data_full.json"))
    mapped = bls.from_bls_series_response(payload)

    for navi_series, out_series in zip(payload.results.series, mapped.series):
        assert len(out_series.observations) == len(navi_series.data)
        assert out_series.series_id == navi_series.series_id
    assert mapped.series and all(o.date for s in mapped.series for o in s.observations)


def test_truncation_advisory_survives_on_a_successful_response():
    """The regression this guards: BLS reports truncation via message[], with
    status=REQUEST_SUCCEEDED. Dropping it as transport makes the tool lossy."""
    raw = _fixture("error_span.json")
    assert raw["status"] == "REQUEST_SUCCEEDED"

    mapped = bls.from_bls_series_response(BlsSeriesResponse.model_validate(raw))

    assert any("reduced" in notice for notice in mapped.notices)
    assert mapped.series, "the truncated data is still returned, not discarded"


def test_survey_fixtures_map_and_serialize():
    listed = bls.from_bls_surveys_response(
        BlsSurveysResponse.model_validate(_fixture("all_surveys.json")))
    single = bls.from_bls_survey_response(
        BlsSurveysResponse.model_validate(_fixture("single_survey.json")))

    assert len(listed.surveys) > 1
    assert single.survey is not None and single.survey.survey_abbreviation
    for model in (listed, single):
        json.dumps(model.model_dump())          # must be JSON-primitive throughout


def test_popular_and_latest_fixtures_map():
    popular = bls.from_bls_series_response(
        BlsSeriesResponse.model_validate(_fixture("popular.json")))
    latest = bls.from_bls_series_response(
        BlsSeriesResponse.model_validate(_fixture("latest_single.json")))

    assert popular.series and all(s.series_id for s in popular.series)
    assert latest.series and len(latest.series[0].observations) == 1
