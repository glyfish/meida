"""Tests for the FRED response models (``mcp_server/responses/fred.py``).

Pure and offline: navi models are hand-built, so nothing here touches the FRED
API or a client. What is being checked is the translation itself — the
``seriess`` rename, the dropped HTTP envelope, ISO date rendering, the '.'
missing-value sentinel, and that the mappers survive None/empty input.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from clients.models.fred import (
    Category,
    CategoryResponse,
    Observation,
    ObservationsResponse,
    Release,
    ReleasesResponse,
    Series,
    SeriesResponse,
)
from mcp_server.responses import fred


# --- navi fixtures ------------------------------------------------------------


REALTIME = {"realtime_start": date(2024, 5, 1), "realtime_end": date(2024, 5, 1)}


def _series(series_id: str = "GDP", **overrides: Any) -> Series:
    payload: dict[str, Any] = {
        "id": series_id,
        "title": "Gross Domestic Product",
        "observation_start": date(1947, 1, 1),
        "observation_end": date(2024, 1, 1),
        "frequency": "Quarterly",
        "frequency_short": "Q",
        "units": "Billions of Dollars",
        "units_short": "Bil. of $",
        "seasonal_adjustment": "Seasonally Adjusted Annual Rate",
        "seasonal_adjustment_short": "SAAR",
        "last_updated": datetime(2024, 4, 25, 7, 55, 1, tzinfo=timezone(timedelta(hours=-5))),
        "popularity": 92,
        "notes": "BEA Account Code: A191RC",
    }
    payload.update(overrides)
    return Series(**payload)


def _series_response(*series: Series, count: int | None = None) -> SeriesResponse:
    return SeriesResponse(
        **REALTIME,
        order_by="series_id",
        sort_order="asc",
        count=count,
        offset=0,
        limit=1000,
        seriess=list(series),
    )


def _observations_response(
    pairs: list[tuple[date, str]], count: int | None = None
) -> ObservationsResponse:
    return ObservationsResponse(
        **REALTIME,
        order_by="observation_date",
        sort_order="asc",
        count=count,
        offset=0,
        limit=100,
        observations=[
            Observation(**REALTIME, date=observed_on, value=value) for observed_on, value in pairs
        ],
    )


# --- Field renaming -----------------------------------------------------------


def test_seriess_is_renamed_to_series():
    result = fred.from_series_response(_series_response(_series()))

    assert [item.id for item in result.series] == ["GDP"]
    assert not hasattr(result, "seriess")
    assert "seriess" not in result.model_dump()


def test_series_fields_carry_through():
    result = fred.from_series_response(_series_response(_series()))
    series = result.series[0]

    assert series.title == "Gross Domestic Product"
    assert series.frequency == "Quarterly"
    assert series.frequency_short == "Q"
    assert series.units_short == "Bil. of $"
    assert series.seasonal_adjustment_short == "SAAR"
    assert series.popularity == 92
    assert series.notes == "BEA Account Code: A191RC"


def test_series_list_preserves_order_and_every_member():
    response = _series_response(_series("GDP"), _series("UNRATE"), _series("CPIAUCSL"))

    result = fred.from_series_response(response)

    assert [item.id for item in result.series] == ["GDP", "UNRATE", "CPIAUCSL"]


# --- Envelope removal ---------------------------------------------------------


ENVELOPE_FIELDS = {
    "status",
    "response_time",
    "responseTime",
    "message",
    "realtime_start",
    "realtime_end",
    "order_by",
    "sort_order",
    "offset",
    "limit",
}


@pytest.mark.parametrize(
    "model",
    [
        fred.FredCategory,
        fred.FredCategoryList,
        fred.FredSeries,
        fred.FredSeriesList,
        fred.FredObservation,
        fred.FredObservationList,
        fred.FredRelease,
        fred.FredReleaseList,
    ],
)
def test_no_envelope_fields_on_any_model(model):
    assert ENVELOPE_FIELDS.isdisjoint(model.model_fields)


def test_envelope_is_dropped_from_mapped_payloads():
    dumped = fred.from_series_response(_series_response(_series())).model_dump()

    assert ENVELOPE_FIELDS.isdisjoint(dumped)
    assert ENVELOPE_FIELDS.isdisjoint(dumped["series"][0])


def test_observation_realtime_bounds_are_dropped():
    result = fred.from_observations_response(_observations_response([(date(2024, 1, 1), "1.0")]))

    assert result.observations[0].model_dump() == {"date": "2024-01-01", "value": "1.0"}


def test_count_is_kept_so_truncation_is_visible():
    response = _series_response(_series(), count=4213)

    result = fred.from_series_response(response)

    assert result.count == 4213
    assert len(result.series) == 1  # count > len(...) means truncated


def test_count_absent_stays_none():
    assert fred.from_series_response(_series_response(_series())).count is None


# --- Date derivation ----------------------------------------------------------


def test_observation_dates_are_iso_strings():
    response = _observations_response([(date(2024, 1, 1), "1.0"), (date(2024, 4, 1), "2.0")])

    result = fred.from_observations_response(response)

    assert [obs.date for obs in result.observations] == ["2024-01-01", "2024-04-01"]
    assert all(isinstance(obs.date, str) for obs in result.observations)


def test_series_coverage_dates_are_iso_strings():
    result = fred.from_series_response(_series_response(_series()))
    series = result.series[0]

    assert series.observation_start == "1947-01-01"
    assert series.observation_end == "2024-01-01"


def test_last_updated_is_iso_8601_with_offset():
    result = fred.from_series_response(_series_response(_series()))

    assert result.series[0].last_updated == "2024-04-25T07:55:01-05:00"


def test_mapped_payload_is_json_primitives_only():
    """The server dumps in python mode, so no date objects may survive."""
    dumped = fred.from_series_response(_series_response(_series())).model_dump()
    observations = fred.from_observations_response(
        _observations_response([(date(2024, 1, 1), "1.0")])
    ).model_dump()

    for value in dumped["series"][0].values():
        assert not isinstance(value, (date, datetime))
    for value in observations["observations"][0].values():
        assert not isinstance(value, (date, datetime))


# --- Missing-value sentinel ---------------------------------------------------


def test_missing_value_sentinel_becomes_none():
    response = _observations_response([(date(2020, 4, 1), ".")])

    result = fred.from_observations_response(response)

    assert result.observations[0].value is None


def test_no_observation_is_dropped_for_a_missing_value():
    response = _observations_response(
        [
            (date(2024, 1, 1), "1.0"),
            (date(2024, 2, 1), "."),
            (date(2024, 3, 1), "."),
            (date(2024, 4, 1), "2.0"),
        ]
    )

    result = fred.from_observations_response(response)

    assert len(result.observations) == 4
    assert [obs.date for obs in result.observations] == [
        "2024-01-01",
        "2024-02-01",
        "2024-03-01",
        "2024-04-01",
    ]
    assert [obs.value for obs in result.observations] == ["1.0", None, None, "2.0"]


def test_values_stay_strings():
    result = fred.from_observations_response(_observations_response([(date(2024, 1, 1), "27956.9")]))

    assert result.observations[0].value == "27956.9"
    assert isinstance(result.observations[0].value, str)


def test_series_id_is_echoed_when_supplied():
    response = _observations_response([(date(2024, 1, 1), "1.0")])

    assert fred.from_observations_response(response, series_id="GDP").series_id == "GDP"
    assert fred.from_observations_response(response).series_id is None


# --- Categories and releases --------------------------------------------------


def test_category_response_maps_tree_nodes():
    response = CategoryResponse(
        **REALTIME,
        count=2,
        categories=[
            Category(id=32992, name="Money, Banking, & Finance", parent_id=0),
            Category(id=10, name="Population, Employment, & Labor Markets", parent_id=0),
        ],
    )

    result = fred.from_category_response(response)

    assert [(c.id, c.name, c.parent_id) for c in result.categories] == [
        (32992, "Money, Banking, & Finance", 0),
        (10, "Population, Employment, & Labor Markets", 0),
    ]
    assert result.count == 2


def test_category_without_parent_is_none():
    response = CategoryResponse(**REALTIME, categories=[Category(id=0, name="Categories")])

    result = fred.from_category_response(response)

    assert result.categories[0].parent_id is None


def test_releases_response_maps_and_drops_realtime():
    response = ReleasesResponse(
        **REALTIME,
        count=1,
        releases=[
            Release(
                id=53,
                name="Gross Domestic Product",
                press_release=True,
                link="https://www.bea.gov/data/gdp",
                **REALTIME,
            )
        ],
    )

    result = fred.from_releases_response(response)

    assert result.releases[0].model_dump() == {
        "id": 53,
        "name": "Gross Domestic Product",
        "press_release": True,
        "link": "https://www.bea.gov/data/gdp",
    }
    assert result.count == 1


def test_release_without_link_is_none():
    response = ReleasesResponse(
        **REALTIME,
        releases=[Release(id=9, name="No Link Release", press_release=False, **REALTIME)],
    )

    assert fred.from_releases_response(response).releases[0].link is None


# --- Empty / None inputs ------------------------------------------------------


@pytest.mark.parametrize(
    ("mapper", "field"),
    [
        (fred.from_category_response, "categories"),
        (fred.from_series_response, "series"),
        (fred.from_observations_response, "observations"),
        (fred.from_releases_response, "releases"),
    ],
)
def test_mappers_accept_none(mapper, field):
    result = mapper(None)

    assert getattr(result, field) == []
    assert result.count is None


def test_mappers_accept_empty_payloads():
    assert fred.from_series_response(_series_response()).series == []
    assert fred.from_observations_response(_observations_response([])).observations == []
    assert fred.from_category_response(CategoryResponse(**REALTIME)).categories == []
    assert fred.from_releases_response(ReleasesResponse(**REALTIME)).releases == []


def test_mappers_tolerate_missing_attributes():
    """Total, not merely defensive: a payload missing the list still maps."""

    class _Bare:
        pass

    assert fred.from_series_response(_Bare()).series == []
    assert fred.from_observations_response(_Bare()).observations == []


def test_optional_series_fields_missing_stay_none():
    series = _series(
        frequency_short=None,
        units_short=None,
        seasonal_adjustment=None,
        seasonal_adjustment_short=None,
        popularity=None,
        notes=None,
    )

    mapped = fred.from_series_response(_series_response(series)).series[0]

    assert mapped.frequency_short is None
    assert mapped.units_short is None
    assert mapped.seasonal_adjustment is None
    assert mapped.popularity is None
    assert mapped.notes is None


# --- Published JSON Schema ----------------------------------------------------


ALL_MODELS = [
    fred.FredCategory,
    fred.FredCategoryList,
    fred.FredSeries,
    fred.FredSeriesList,
    fred.FredObservation,
    fred.FredObservationList,
    fred.FredRelease,
    fred.FredReleaseList,
]


def _property_names(schema: dict) -> list[str]:
    names = list(schema.get("properties", {}))
    for definition in schema.get("$defs", {}).values():
        names.extend(definition.get("properties", {}))
    return names


@pytest.mark.parametrize("model", ALL_MODELS)
def test_schema_property_names_are_snake_case(model):
    for name in _property_names(model.model_json_schema()):
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name), f"{model.__name__}.{name} is not snake_case"


@pytest.mark.parametrize("model", ALL_MODELS)
def test_schema_declares_no_aliases(model):
    for field in model.model_fields.values():
        assert field.alias is None
        assert field.validation_alias is None
        assert field.serialization_alias is None


@pytest.mark.parametrize("model", ALL_MODELS)
def test_every_field_is_described(model):
    for name, field in model.model_fields.items():
        assert field.description, f"{model.__name__}.{name} has no description"


@pytest.mark.parametrize("model", ALL_MODELS)
def test_every_model_has_a_docstring(model):
    assert (model.__doc__ or "").strip()


def test_schema_descriptions_reach_the_json_schema():
    schema = fred.FredObservationList.model_json_schema()

    value = schema["$defs"]["FredObservation"]["properties"]["value"]["description"]
    assert "'.'" in value  # the sentinel is explained to the consumer, not just handled
    assert schema["properties"]["observations"]["description"]
    assert "realtime" in schema["description"].lower()  # the drop is documented
