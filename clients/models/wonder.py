"""Typed models for the CDC WONDER mortality API.

CDC WONDER (``wonder.cdc.gov``) answers mortality queries via an XML POST web
service. Unlike the Socrata portal, results come back as an XML ``<data-table>``
of grouped rows. This client targets the common shape we need for the
immiseration build: a measure (deaths / rates) **grouped by year**, nationally.

One ``WonderRow`` is a single grouped row (one year). Values that WONDER
suppresses or marks unreliable ("Suppressed", "Unreliable", "Not Applicable")
come through as ``None`` rather than a sentinel number.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class WonderBaseModel(BaseModel):
    """Base config for immutable WONDER models."""

    model_config = {"frozen": True, "populate_by_name": True}


class WonderRow(WonderBaseModel):
    """One grouped row of a WONDER data-table (grouped By Year)."""

    year: int
    deaths: Optional[int] = None
    population: Optional[int] = None
    crude_rate: Optional[float] = None          # per O_rate_per (100,000)
    age_adjusted_rate: Optional[float] = None   # 2000 US std pop, per O_rate_per


class WonderResponse(WonderBaseModel):
    """Parsed rows for one WONDER query, plus any caveat messages WONDER returns."""

    database: str                                # e.g. "D76"
    rows: List[WonderRow] = Field(default_factory=list)
    messages: List[str] = Field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)
