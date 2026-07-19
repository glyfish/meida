"""Tests for navi's BIS pydantic models (``lib/clients/models/bis.py``)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from lib.clients.models.bis import (
    BisCodelist,
    BisDataResponse,
    BisDataStructure,
    BisDataflow,
    BisDimension,
    BisObservation,
    BisSeries,
)


def test_dataflow_optional_fields():
    flow = BisDataflow(id="WS_TC")
    assert flow.name is None and flow.agency is None


def test_observation_allows_missing_value():
    """Empty cells are common in SDMX output and must not fail validation."""
    obs = BisObservation(time_period="2025-01", value=None)
    assert obs.value is None and obs.status is None


def test_series_defaults_to_no_observations():
    series = BisSeries(key="M.US.368")
    assert series.observations == []
    assert series.dimensions == {}


def test_data_response_series_count():
    response = BisDataResponse(
        flow="WS_CBPOL",
        series=[BisSeries(key="M.US.368"), BisSeries(key="M.GB.368")],
    )
    assert response.series_count == 2


def test_datastructure_decode_uses_codelist():
    dsd = BisDataStructure(
        id="BIS_TOTAL_CREDIT",
        dimensions=[BisDimension(id="BORROWERS_CTY", codelist_id="CL_AREA")],
        codelists={"CL_AREA": BisCodelist(id="CL_AREA", codes={"US": "United States"})},
    )
    assert dsd.decode("BORROWERS_CTY", "US") == "United States"
    assert dsd.decode("BORROWERS_CTY", "XX") == "XX"       # unknown code
    assert dsd.decode("OTHER", "US") == "US"               # unknown dimension


def test_datastructure_decode_without_codelist():
    """A dimension with no enumeration returns codes untouched."""
    dsd = BisDataStructure(id="D", dimensions=[BisDimension(id="FREQ")])
    assert dsd.decode("FREQ", "M") == "M"


def test_models_are_frozen():
    obs = BisObservation(time_period="2025-01", value=1.0)
    with pytest.raises(ValidationError):
        obs.value = 2.0
