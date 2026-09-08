"""Typed models for meida's time-series source database.

meida owns a PostgreSQL table (``time_series_source``) holding observations for
sources that **cannot be fetched per request** -- CDC WONDER (throttled ~1 query
per 2 minutes behind a bot filter) and CDC NVSR (annual Excel downloads with no
programmatic URL discovery). The table stands in for a provider API: consumers
read it through the same client -> MCP tool -> caching path as FRED or Tiingo.

The observation payload matches yada's ``time_series_cache`` contract, so moving
a series from here into that cache is a straight copy: ascending by date, and
``value`` is a **string** -- readers cast it and skip the sentinels the upstream
providers use for missing data.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TimeSeriesSourceBaseModel(BaseModel):
    """Base config for immutable time-series-source models."""

    model_config = {"frozen": True, "populate_by_name": True}


class Observation(TimeSeriesSourceBaseModel):
    """One point in a series.

    ``value`` is a string to match the shared cache contract (FRED and Tiingo
    both store it that way). Sources may carry extra keys beside it -- WONDER
    adds ``deaths``, ``population`` and ``crude_rate`` next to the age-adjusted
    rate -- so ``extra="allow"`` keeps them rather than dropping them.
    """

    model_config = {"frozen": True, "populate_by_name": True, "extra": "allow"}

    date: str                            # ISO ``YYYY-MM-DD``; annual data snaps to ``YYYY-01-01``
    value: Optional[str] = None          # stringified number, or None when withheld


class TimeSeriesRef(TimeSeriesSourceBaseModel):
    """Identity and coverage of a series, without its observations.

    What ``list_series`` returns -- enough to decide whether to fetch the
    payload, cheaply, since the observations column dominates row size.
    """

    source: str                          # ``cdc_wonder`` | ``cdc_nvsr``
    native_id: str
    title: str
    frequency: str                       # long form, e.g. ``Annual``
    units: Optional[str] = None
    observation_start: Optional[date] = None
    observation_end: Optional[date] = None
    observation_count: Optional[int] = None
    expires_at: Optional[datetime] = None
    stale: bool = False                  # past ``expires_at`` -- due for a refresh, still served


class TimeSeriesRecord(TimeSeriesRef):
    """A full series: identity, coverage, catalog metadata, and observations."""

    metadata: Dict[str, Any] = Field(default_factory=dict)
    observations: List[Observation] = Field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.observations)


class TimeSeriesRefList(TimeSeriesSourceBaseModel):
    """A listing of stored series.

    An object rather than a bare list: FastMCP derives a tool's output schema
    from its return annotation, and a bare list yields no ``structuredContent``
    at all, so the caller would get an undescribed payload.
    """

    series: List[TimeSeriesRef] = Field(default_factory=list)
