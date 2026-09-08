"""Response models for the series-catalog tools."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CatalogEntry(BaseModel):
    """One series meida can serve: what it is, and what fetches it."""

    model_config = {"frozen": True}

    source: str = Field(description="Catalog namespace, e.g. 'cdc'.")
    series_id: str = Field(
        description="Stable identifier, e.g. "
                    "'cdc/alcohol_binge/hksd-2xuw/state=ak/race=aian/age_adjusted'."
    )
    dataset_id: Optional[str] = Field(
        default=None, description="Provider dataset this series comes from, when it has one."
    )
    concept: Optional[str] = Field(
        default=None, description="What is measured, e.g. 'alcohol_binge'."
    )
    title: str
    description: Optional[str] = Field(
        default=None,
        description=(
            "Prose summary. Generated per bucket of series that differ only by facet "
            "value, so many series share one description -- use 'facets' to tell them "
            "apart, not this."
        ),
    )
    units: Optional[str] = None
    frequency: Optional[str] = None
    provisional: bool = Field(
        default=False,
        description="Provisional data, revised in later releases (VSRR counts).",
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Still being updated, judged against the newest series of the "
                    "same vintage -- provisional and final are compared separately.",
    )
    facets: Dict[str, Any] = Field(
        default_factory=dict,
        description="The values that pick this series out of its dataset. These are "
                    "the argument names cdc_series_data takes, so they can be passed "
                    "straight back in.",
    )
    retrieval: Dict[str, Any] = Field(
        default_factory=dict,
        description="Which tool fetches this series and with what arguments: "
                    "'cdc_series_data' for the live Socrata route, "
                    "'timeseries_source_data' for the stored one. A null 'tool' means "
                    "no single-call route exists yet.",
    )
    observation_start: Optional[date] = None
    observation_end: Optional[date] = None


class CatalogSearchResult(BaseModel):
    """Matching entries, plus how many matched in total."""

    total: int = Field(
        description="Series matching the filters, before 'limit'. Compare against "
                    "len(entries) to tell a complete result from a truncated one."
    )
    returned: int
    entries: List[CatalogEntry] = Field(default_factory=list)


class CatalogConcept(BaseModel):
    """A concept and the dataset that publishes it, with its series count."""

    concept: str
    dataset_id: Optional[str] = None
    series_count: int


class CatalogConceptList(BaseModel):
    """The coarse map of what the catalog holds."""

    concepts: List[CatalogConcept] = Field(default_factory=list)
