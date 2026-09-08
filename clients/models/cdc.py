"""Typed models for the CDC Socrata (SODA) API.

CDC publishes datasets on a Socrata portal (``data.cdc.gov``). Each dataset is a
"resource" addressed by a 4x4 id (e.g. ``w9j2-ggv5``). Rows are **heterogeneous**
-- the schema differs across datasets -- so data rows are returned as plain
``{field: value}`` dicts (Socrata returns values as strings), and the *structure*
of a dataset is described by ``CdcColumn`` / ``CdcDataset``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CdcBaseModel(BaseModel):
    """Base config for immutable CDC models."""

    model_config = {"frozen": True, "populate_by_name": True}


class CdcColumn(CdcBaseModel):
    """One column of a dataset (from ``/api/views/{id}.json``)."""

    field_name: str                      # SoQL/API field name, e.g. "average_life_expectancy"
    name: Optional[str] = None           # human label, e.g. "Average Life Expectancy"
    data_type: Optional[str] = None      # Socrata dataTypeName, e.g. "number", "text"
    description: Optional[str] = None

    # Value hints from Socrata's ``cachedContents``. Free -- they arrive with the
    # column metadata -- and they carry the exact literals a SoQL ``where``
    # needs, which are otherwise unguessable ("All Races", "Both Sexes").
    #
    # ``cached_top`` is the MOST COMMON values, **capped by Socrata at 20**, not
    # the complete set. Do not treat it as exhaustive: ``cached_cardinality`` is
    # unreliable for deciding (on ``xkb8-kh2a`` every column reports the row
    # count), so a column sitting at the cap needs a ``$group=`` query for a
    # definitive list.
    cached_top: List[Dict[str, Any]] = Field(default_factory=list)
    cached_smallest: Optional[str] = None
    cached_largest: Optional[str] = None
    cached_non_null: Optional[int] = None
    cached_null: Optional[int] = None


class CdcDataset(CdcBaseModel):
    """A dataset's metadata: id, name, and its columns."""

    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    columns: List[CdcColumn] = Field(default_factory=list)


class CdcCatalogEntry(CdcBaseModel):
    """One dataset hit from the Socrata discovery catalog."""

    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    domain: Optional[str] = None


class CdcCategory(CdcBaseModel):
    """A domain category with its dataset count (a catalog facet)."""

    category: str
    count: int = 0


class CdcTag(CdcBaseModel):
    """A domain tag with its dataset count (a catalog facet)."""

    tag: str
    count: int = 0


class CdcDataResponse(CdcBaseModel):
    """Rows returned for one query. Rows are heterogeneous (schema varies by
    dataset), so each is a plain ``{field: value}`` dict; values are strings."""

    dataset_id: str
    rows: List[Dict[str, Any]] = Field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)
