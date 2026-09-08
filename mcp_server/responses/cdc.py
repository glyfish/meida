"""MCP response models for the CDC Socrata catalog tools.

Like BIS, navi's CDC models are already snake_case with no aliases and no HTTP
envelope, so ``CdcDataset`` is served directly. Only the list-returning tools
need anything: a bare list yields no ``structuredContent``, so each gets an
object wrapper naming what it contains.

The time-series tool is not here -- ``cdc_series_data`` has its own response in
``server.py``, since it reshapes Socrata rows into the house
``{date/year, value}`` observation form rather than returning a catalog object.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from clients.models.cdc import CdcCatalogEntry, CdcCategory, CdcTag


class CdcDatasetList(BaseModel):
    """Datasets matching a catalog search."""

    datasets: list[CdcCatalogEntry] = Field(
        description="Each entry's 'id' is the dataset_id the other CDC tools take."
    )


class CdcCategoryList(BaseModel):
    """The catalog's categories with dataset counts -- the topic map."""

    categories: list[CdcCategory]


class CdcTagList(BaseModel):
    """The catalog's tags with dataset counts -- finer-grained than categories."""

    tags: list[CdcTag]
