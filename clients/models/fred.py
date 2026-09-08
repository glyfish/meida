"""Typed models describing common FRED API payloads."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional
import re

from pydantic import BaseModel, Field, field_validator


class FredBaseModel(BaseModel):
    """Base config for immutable FRED models."""

    model_config = {"frozen": True}


class FredResponse(FredBaseModel):
    realtime_start: date
    realtime_end: date


class PaginatedResponse(FredResponse):
    order_by: Optional[str] = None
    sort_order: Optional[str] = None
    count: Optional[int] = None
    offset: Optional[int] = None
    limit: Optional[int] = None


class Category(FredBaseModel):
    id: int = Field(alias="id")
    name: str
    parent_id: int | None = Field(default=None, alias="parent_id")


class CategoryResponse(PaginatedResponse):
    # FRED's category endpoints (/category, /category/children) return ONLY
    # {"categories": [...]} -- no realtime window, unlike /series and /releases.
    # Inheriting them as required made get_category_children raise
    # ValidationError on every real response, so these are optional here and
    # stay required on the responses that genuinely carry them.
    realtime_start: Optional[date] = None
    realtime_end: Optional[date] = None
    categories: List[Category] = Field(default_factory=list)


class Series(FredBaseModel):
    id: str
    title: str
    observation_start: date
    observation_end: date
    frequency: str
    frequency_short: Optional[str] = None
    units: str
    units_short: Optional[str] = None
    seasonal_adjustment: Optional[str] = None
    seasonal_adjustment_short: Optional[str] = None
    last_updated: datetime
    popularity: Optional[int] = None
    notes: Optional[str] = None

    @field_validator("last_updated", mode="before")
    @classmethod
    def _parse_last_updated(cls, value: str | datetime) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            normalized = value
            if re.search(r"[+-]\d{2}$", value):
                normalized = value + "00"
            try:
                return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S%z")
            except ValueError:
                try:
                    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                except ValueError as exc:
                    raise ValueError(f"Invalid last_updated format: {value}") from exc
        raise ValueError("last_updated must be datetime or string")


class SeriesResponse(PaginatedResponse):
    seriess: List[Series] = Field(default_factory=list)


class Observation(FredBaseModel):
    realtime_start: date
    realtime_end: date
    date: date
    value: str


class ObservationsResponse(PaginatedResponse):
    observations: List[Observation] = Field(default_factory=list)


class Release(FredBaseModel):
    id: int
    name: str
    press_release: bool = Field(alias="press_release")
    link: Optional[str] = None
    realtime_start: date
    realtime_end: date


class ReleasesResponse(PaginatedResponse):
    releases: List[Release] = Field(default_factory=list)
