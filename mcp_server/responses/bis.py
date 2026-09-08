"""MCP response models for the BIS tools.

BIS is the one source whose navi models need almost nothing: they are already
snake_case, carry no aliases, and have no HTTP envelope -- ``BisDataResponse``
is ``{flow, series}`` and observations are ``{time_period, value, status}``.
So these are passed through directly rather than restated here.

Only two things are meida's own:

* :class:`BisDataflowList` -- a bare list produces no ``structuredContent`` at
  all, so list-returning tools need an object wrapper.
* :class:`BisDataStructureView` -- ``bis_datastructure`` does not return its
  navi model unchanged. It blanks each codelist's ``codes`` unless the caller
  asks for them (some codelists exceed 1000 entries) and reports ``code_count``
  instead, so the response genuinely differs from ``BisDataStructure`` and needs
  its own model to be described honestly.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from clients.models.bis import BisDataflow, BisDataStructure, BisDimension


class BisDataflowList(BaseModel):
    """The BIS dataflows (datasets) available."""

    dataflows: list[BisDataflow] = Field(
        description="Each entry's 'id' is what the other BIS tools take as 'flow'."
    )


class BisCodelistView(BaseModel):
    """One codelist, with its codes omitted unless explicitly requested."""

    id: str
    name: str | None = None
    code_count: int = Field(
        description="How many code/label pairs exist, whether or not they are included."
    )
    codes: dict[str, str] = Field(
        default_factory=dict,
        description="Code -> label. Empty unless the tool was called with include_codes=true.",
    )


class BisDataStructureView(BaseModel):
    """A dataflow's dimensions and the codelists that decode them.

    The dimensions are ordered: a series key is their values joined by '.', which
    is what ``bis_series_data`` takes as 'key'.
    """

    id: str
    name: str | None = None
    dimensions: list[BisDimension] = Field(default_factory=list)
    codelists: dict[str, BisCodelistView] = Field(default_factory=dict)


def from_datastructure(
    structure: BisDataStructure, *, include_codes: bool = False
) -> BisDataStructureView:
    """Build the view, keeping code counts even when the codes are dropped."""
    return BisDataStructureView(
        id=structure.id,
        name=structure.name,
        dimensions=list(structure.dimensions),
        codelists={
            key: BisCodelistView(
                id=codelist.id,
                name=codelist.name,
                code_count=len(codelist.codes),
                codes=dict(codelist.codes) if include_codes else {},
            )
            for key, codelist in structure.codelists.items()
        },
    )
