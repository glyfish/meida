"""Tests for navi's BLS pydantic models (``lib/clients/models/bls.py``).

Validate against the real response fixtures captured from the live API: object
``Results``, string values, empty footnotes, catalog extras, and the survey
models.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from lib.clients.models.bls import (
    BlsSeriesResponse,
    BlsSurveysResponse,
    Footnote,
    Observation,
)


def test_series_data_parses_full_fixture(load_bls_fixture):
    response = BlsSeriesResponse.model_validate(load_bls_fixture("series_data_full"))
    assert response.status == "REQUEST_SUCCEEDED"
    assert isinstance(response.response_time, int)
    series = response.results.series[0]
    assert series.series_id == "LNS14000000"
    obs = series.data[0]
    assert obs.year == "2023" and obs.period == "M12"
    assert obs.period_name == "December"
    assert obs.value == "3.8"  # value stays a string
    assert obs.calculations.net_changes["1"] == "0.1"
    assert obs.calculations.pct_changes["12"] == "8.6"


def test_catalog_keeps_survey_specific_extras(load_bls_fixture):
    series = BlsSeriesResponse.model_validate(load_bls_fixture("series_data_full")).results.series[0]
    assert series.catalog.survey_abbreviation == "LN"
    assert series.catalog.series_title == "(Seas) Unemployment Rate"
    # Fields not declared on the model are retained via extra="allow".
    assert series.catalog.model_dump()["demographic_age"] == "16 years and over"


def test_empty_footnote_object_parses():
    footnote = Footnote.model_validate({})
    assert footnote.code is None and footnote.text is None


def test_latest_flag_present(load_bls_fixture):
    response = BlsSeriesResponse.model_validate(load_bls_fixture("latest_single"))
    assert response.results.series[0].data[0].latest == "true"


def test_popular_series_ids(load_bls_fixture):
    response = BlsSeriesResponse.model_validate(load_bls_fixture("popular"))
    assert len(response.results.series) == 25
    assert response.results.series[0].series_id == "CUUR0000SA0"
    assert response.results.series[0].data == []  # popular returns IDs only


def test_all_surveys_basic_fields(load_bls_fixture):
    response = BlsSurveysResponse.model_validate(load_bls_fixture("all_surveys"))
    survey = response.results.survey[0]
    assert survey.survey_abbreviation == "AP"
    assert survey.survey_name.startswith("Consumer Price Index")
    assert survey.allows_net_change is None  # only on single-survey endpoint


def test_single_survey_detail_fields(load_bls_fixture):
    response = BlsSurveysResponse.model_validate(load_bls_fixture("single_survey"))
    survey = response.results.survey[0]
    assert survey.survey_abbreviation == "TU"
    assert survey.allows_net_change == "false"
    assert survey.has_annual_averages == "false"


def test_error_payload_parses_with_empty_results(load_bls_fixture):
    response = BlsSurveysResponse.model_validate(load_bls_fixture("error_not_processed"))
    assert response.status == "REQUEST_NOT_PROCESSED"
    assert "invalid" in response.message[0].lower()
    assert response.results.survey == []


def test_observation_is_frozen():
    obs = Observation.model_validate(
        {"year": "2023", "period": "M12", "periodName": "December", "value": "3.8"}
    )
    with pytest.raises(ValidationError):
        obs.value = "9.9"
