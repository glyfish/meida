"""Tests for the FBI pydantic models (``clients/models/fbi.py``).

The models carry two derived properties that decide what a caller reads:
``FbiSeries.span``, which the catalog turns into ``observation_start`` and
``observation_end``, and ``FbiEmploymentResponse.officers``, which is the only
route to a staffing number that does not go through the API's unusable rates.
Both have to be right about missing years, since 1985-2024 at agency grain is
mostly missing years.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from clients.models.fbi import (
    FbiAgency,
    FbiEmploymentResponse,
    FbiObservation,
    FbiOffenseResponse,
    FbiSeries,
)


def _series(measure: str, points: list[tuple[str, float | None]], **kwargs) -> FbiSeries:
    return FbiSeries(
        label=kwargs.pop("label", f"Washington Police Department {measure.title()}"),
        scope=kwargs.pop("scope", "DCMPD0000"),
        measure=measure,
        observations=[FbiObservation(period=period, value=value) for period, value in points],
        **kwargs,
    )


def test_span_is_the_first_and_last_period_carrying_a_value():
    series = _series("offenses", [("01-2019", 12.0), ("02-2019", 9.0), ("03-2019", 11.0)])
    assert series.span == ("01-2019", "03-2019")


def test_span_ignores_the_months_nobody_reported():
    """An unreported month is not the start of the series, and not the end."""
    series = _series("offenses", [("01-2019", None), ("02-2019", 9.0),
                                  ("03-2019", 11.0), ("04-2019", None)])
    assert series.span == ("02-2019", "03-2019")


def test_span_is_none_when_every_value_is_missing():
    """``pe/state`` answers 200 with the full shape and nothing in it."""
    series = _series("officers", [("1985", None), ("1986", None)])
    assert series.span is None


def test_span_is_none_without_observations():
    assert FbiSeries(label="Texas Offenses", scope="TX", measure="offenses").span is None


def test_an_observation_may_have_no_value():
    """None is the reporting gap; zero would be a claim about crime."""
    observation = FbiObservation(period="06-2021")
    assert observation.value is None


def test_officers_sum_the_male_and_female_counts():
    """The API reports the two sexes separately and never their total."""
    response = FbiEmploymentResponse(ori="DCMPD0000", series=[
        _series("officers", [("1985", 3400.0), ("1990", 4200.0)], label="Male Officers"),
        _series("officers", [("1985", 437.0), ("1990", 540.0)], label="Female Officers"),
    ])
    assert response.officers == {1985: 3837, 1990: 4740}


def test_officers_leave_out_a_year_with_no_report():
    """A year both series report as null is absent, rather than zero."""
    response = FbiEmploymentResponse(ori="DCMPD0000", series=[
        _series("officers", [("1985", 3400.0), ("1986", None)], label="Male Officers"),
        _series("officers", [("1985", 437.0), ("1986", None)], label="Female Officers"),
    ])
    assert response.officers == {1985: 3837}


def test_officers_ignore_the_civilian_and_population_series():
    """One payload carries four staffing series and a denominator."""
    response = FbiEmploymentResponse(ori="DCMPD0000", series=[
        _series("officers", [("1985", 3400.0)], label="Male Officers"),
        _series("officers", [("1985", 437.0)], label="Female Officers"),
        _series("civilians", [("1985", 500.0)], label="Male Civilians"),
        _series("civilians", [("1985", 320.0)], label="Female Civilians"),
        _series("value", [("1985", 626000.0)], label="Population", unit="people"),
    ])
    assert response.officers == {1985: 3837}


def test_officers_come_back_in_year_order():
    """The catalog reads the first and last key as the span."""
    response = FbiEmploymentResponse(ori="DCMPD0000", series=[
        _series("officers", [("2010", 3945.0), ("1985", 3837.0), ("2024", 3276.0)],
                label="Male Officers"),
    ])
    assert list(response.officers) == [1985, 2010, 2024]


def test_officers_are_empty_without_an_employment_series():
    """``pe/national`` returns the shape with every value null."""
    response = FbiEmploymentResponse(ori="DCMPD0000", series=[
        _series("officers", [("1985", None)], label="Male Officers"),
    ])
    assert response.officers == {}


def test_an_offense_response_defaults_to_no_series():
    response = FbiOffenseResponse(offense="homicide", scope="DC")
    assert response.series == []
    assert response.max_data_date is None and response.last_refresh_date is None


def test_an_agency_needs_only_its_ori():
    """The registry omits fields per agency; only the ORI is dependable."""
    agency = FbiAgency(ori="DC0011300")
    assert agency.agency_name is None and agency.nibrs_start_date is None


def test_models_are_frozen():
    observation = FbiObservation(period="01-2019", value=12.0)
    with pytest.raises(ValidationError):
        observation.value = 9.0
