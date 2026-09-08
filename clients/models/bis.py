"""Typed models describing BIS SDMX payloads.

BIS exposes an SDMX 2.1 service. Two shapes matter here:

* **Structure** (SDMX-JSON) -- dataflows, data structure definitions, and
  codelists. A dataflow is the rough equivalent of a BLS survey; its DSD
  declares dimensions, each of which is decoded by a codelist.
* **Data** (CSV) -- one row per observation, with the series' dimension and
  attribute values repeated on every row. Requesting CSV avoids parsing
  SDMX-XML for the data path entirely.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class BisBaseModel(BaseModel):
    """Base config for immutable BIS models."""

    model_config = {"frozen": True, "populate_by_name": True}


class BisDataflow(BisBaseModel):
    """A published dataset, e.g. WS_TC 'Total credit'."""

    id: str
    name: Optional[str] = None
    agency: Optional[str] = None
    version: Optional[str] = None
    structure: Optional[str] = None


class BisDimension(BisBaseModel):
    """One dimension of a series key, decoded by ``codelist_id``."""

    id: str
    position: Optional[int] = None
    codelist_id: Optional[str] = None


class BisCodelist(BisBaseModel):
    """Code -> label mapping for a dimension (the BLS lookup-file analogue)."""

    id: str
    name: Optional[str] = None
    codes: Dict[str, str] = Field(default_factory=dict)


class BisDataStructure(BisBaseModel):
    """A DSD: the ordered dimensions of a dataflow plus their codelists."""

    id: str
    name: Optional[str] = None
    dimensions: List[BisDimension] = Field(default_factory=list)
    codelists: Dict[str, BisCodelist] = Field(default_factory=dict)

    def decode(self, dimension_id: str, code: str) -> str:
        """Return the label for a dimension's code, or the code if unknown."""
        for dimension in self.dimensions:
            if dimension.id == dimension_id and dimension.codelist_id:
                codelist = self.codelists.get(dimension.codelist_id)
                if codelist:
                    return codelist.codes.get(code, code)
        return code


class BisObservation(BisBaseModel):
    """A single datapoint. ``value`` is None when the cell is empty."""

    time_period: str
    value: Optional[float] = None
    status: Optional[str] = None


class BisSeries(BisBaseModel):
    """One series: its dimension/attribute values plus its observations."""

    key: str
    dimensions: Dict[str, str] = Field(default_factory=dict)
    title: Optional[str] = None
    unit_measure: Optional[str] = None
    observations: List[BisObservation] = Field(default_factory=list)


class BisDataResponse(BisBaseModel):
    """All series returned for one data query."""

    flow: str
    series: List[BisSeries] = Field(default_factory=list)

    @property
    def series_count(self) -> int:
        return len(self.series)
