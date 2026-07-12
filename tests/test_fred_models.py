"""Tests for navi's FRED pydantic models (``lib/clients/models/fred.py``).

The interesting logic here is ``Series._parse_last_updated`` (FRED's short
timezone suffix normalization) plus field aliases and default factories.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from lib.clients.models.fred import (
    Category,
    CategoryResponse,
    Release,
    Series,
    SeriesResponse,
)

_BASE_SERIES = {
    "id": "GDP",
    "title": "Gross Domestic Product",
    "observation_start": "1947-01-01",
    "observation_end": "2024-01-01",
    "frequency": "Quarterly",
    "units": "Billions of Dollars",
    "last_updated": "2024-03-28 07:56:01-05",
}


def _series(**overrides) -> Series:
    return Series.model_validate({**_BASE_SERIES, **overrides})


def test_last_updated_normalizes_short_timezone():
    series = _series(last_updated="2024-03-28 07:56:01-05")
    assert series.last_updated.utcoffset() == timedelta(hours=-5)


def test_last_updated_without_timezone_is_naive():
    series = _series(last_updated="2024-03-28 07:56:01")
    assert series.last_updated.tzinfo is None
    assert series.last_updated == datetime(2024, 3, 28, 7, 56, 1)


def test_last_updated_accepts_datetime_passthrough():
    moment = datetime(2024, 3, 28, 7, 56, 1, tzinfo=timezone.utc)
    series = _series(last_updated=moment)
    assert series.last_updated is moment


def test_last_updated_rejects_garbage():
    with pytest.raises(ValidationError):
        _series(last_updated="not-a-timestamp")


def test_series_optional_fields_default_none():
    series = _series()
    assert series.popularity is None
    assert series.notes is None
    assert series.frequency_short is None


def test_category_alias_and_optional_parent():
    category = Category.model_validate({"id": 10, "name": "Population"})
    assert category.parent_id is None
    nested = Category.model_validate({"id": 11, "name": "Child", "parent_id": 10})
    assert nested.parent_id == 10


def test_release_press_release_alias():
    release = Release.model_validate(
        {
            "id": 53,
            "name": "GDP",
            "press_release": False,
            "realtime_start": "2024-01-01",
            "realtime_end": "2024-01-01",
        }
    )
    assert release.press_release is False


def test_series_response_defaults_to_empty_list():
    response = SeriesResponse.model_validate(
        {"realtime_start": "2024-01-01", "realtime_end": "2024-01-01"}
    )
    assert response.seriess == []
    assert response.count is None


def test_category_response_parses_nested_categories():
    response = CategoryResponse.model_validate(
        {
            "realtime_start": "2024-01-01",
            "realtime_end": "2024-01-01",
            "categories": [{"id": 1, "name": "A"}, {"id": 2, "name": "B", "parent_id": 1}],
        }
    )
    assert [c.id for c in response.categories] == [1, 2]


def test_models_are_frozen():
    series = _series()
    with pytest.raises(ValidationError):
        series.title = "mutated"
