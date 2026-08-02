"""Tests for the CDC pydantic models (``lib/clients/models/cdc.py``)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from lib.clients.models.cdc import (
    CdcCatalogEntry,
    CdcColumn,
    CdcDataResponse,
    CdcDataset,
)


def test_dataset_holds_columns():
    dataset = CdcDataset(
        id="w9j2-ggv5",
        name="Life expectancy",
        columns=[CdcColumn(field_name="year", name="Year", data_type="text")],
    )
    assert dataset.id == "w9j2-ggv5"
    assert dataset.columns[0].field_name == "year"
    assert dataset.columns[0].data_type == "text"


def test_data_response_row_count():
    resp = CdcDataResponse(dataset_id="x", rows=[{"a": "1"}, {"a": "2"}])
    assert resp.row_count == 2
    assert resp.rows[1]["a"] == "2"


def test_catalog_entry_optional_fields_default_none():
    entry = CdcCatalogEntry(id="abcd-1234")
    assert entry.name is None and entry.description is None and entry.domain is None


def test_models_are_frozen():
    entry = CdcCatalogEntry(id="abcd-1234")
    with pytest.raises(ValidationError):
        entry.id = "zzzz-9999"  # frozen models reject mutation
