"""Typed models describing Bureau of Labor Statistics (BLS) API payloads.

Shapes were confirmed against live v2 responses: ``Results`` is an object (not
the array shown in the docs), ``value``/``year`` are strings, ``footnotes`` can
contain empty objects, and ``catalog`` fields vary by survey (so it allows
extras).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class BlsBaseModel(BaseModel):
    """Base config for immutable BLS models."""

    model_config = {"frozen": True, "populate_by_name": True}


class Footnote(BlsBaseModel):
    # Often an empty object (`{}`) in responses, so both fields are optional.
    code: Optional[str] = None
    text: Optional[str] = None


class Calculations(BlsBaseModel):
    net_changes: Dict[str, str] = Field(default_factory=dict)
    pct_changes: Dict[str, str] = Field(default_factory=dict)


class Aspect(BlsBaseModel):
    name: Optional[str] = None
    value: Optional[str] = None
    footnotes: List[Footnote] = Field(default_factory=list)


class Catalog(BaseModel):
    """Series metadata (v2, ``catalog=true``). Fields vary by survey."""

    # Frozen but tolerant of the many survey-specific keys.
    model_config = {"frozen": True, "extra": "allow"}

    series_title: Optional[str] = None
    series_id: Optional[str] = None
    seasonality: Optional[str] = None
    survey_name: Optional[str] = None
    survey_abbreviation: Optional[str] = None
    measure_data_type: Optional[str] = None


class Observation(BlsBaseModel):
    year: str
    period: str
    period_name: str = Field(alias="periodName")
    value: str
    latest: Optional[str] = None
    footnotes: List[Footnote] = Field(default_factory=list)
    calculations: Optional[Calculations] = None
    aspects: List[Aspect] = Field(default_factory=list)


class Series(BlsBaseModel):
    series_id: str = Field(alias="seriesID")
    catalog: Optional[Catalog] = None
    data: List[Observation] = Field(default_factory=list)


class Survey(BlsBaseModel):
    survey_abbreviation: str
    survey_name: str
    # Only present on the single-survey endpoint.
    allows_net_change: Optional[str] = Field(default=None, alias="allowsNetChange")
    allows_percent_change: Optional[str] = Field(default=None, alias="allowsPercentChange")
    has_annual_averages: Optional[str] = Field(default=None, alias="hasAnnualAverages")


class SeriesResults(BlsBaseModel):
    series: List[Series] = Field(default_factory=list)


class SurveyResults(BlsBaseModel):
    survey: List[Survey] = Field(default_factory=list)


class BlsBaseResponse(BlsBaseModel):
    status: str
    response_time: Optional[int] = Field(default=None, alias="responseTime")
    message: List[str] = Field(default_factory=list)


class BlsSeriesResponse(BlsBaseResponse):
    """Response for time-series data, latest, and popular endpoints."""

    results: SeriesResults = Field(default_factory=SeriesResults, alias="Results")


class BlsSurveysResponse(BlsBaseResponse):
    """Response for the all-surveys and single-survey endpoints."""

    results: SurveyResults = Field(default_factory=SurveyResults, alias="Results")
