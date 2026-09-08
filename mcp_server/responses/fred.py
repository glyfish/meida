"""Consumer-facing response models for the FRED tools.

These sit between navi's wire-format models (``clients.models.fred``) and the
MCP tool boundary. navi's models exist to *parse* FRED's JSON, so they carry the
vendor's spelling and its HTTP envelope; these models exist to be *published* as
a JSON Schema an API consumer reads, so they carry neither.

What changes on the way through:

* **``seriess`` becomes ``series``.** FRED's own payload misspells it; navi
  reproduces the misspelling faithfully so parsing works. Nothing downstream
  should have to.
* **The envelope goes.** ``realtime_start``/``realtime_end``, ``order_by``,
  ``sort_order``, ``offset`` and ``limit`` describe an HTTP call, not data.
  ``count`` stays: it is the vendor's total, and comparing it against the
  returned list is how a caller learns the result was truncated.
* **Dates are ISO strings, not ``date`` objects.** navi parses them to
  ``datetime.date``/``datetime``; here they are re-emitted as ``YYYY-MM-DD``
  (and ISO-8601 for ``last_updated``). Every field is then a JSON primitive, so
  a plain ``model_dump()`` — which is what the server does — is already
  serializable, and the published schema says ``string`` rather than a format a
  consumer has to guess at.
* **Observations follow the house shape** set by
  ``mcp_server/timeseries_source_models.py`` and ``cdc_series_data``:
  ``{"date": "YYYY-MM-DD", "value": "<number as string>"}``, ascending as FRED
  returned them. Values stay strings — vendors return strings and callers cast.

Mapping functions are pure and total: no I/O, and ``None``/missing/empty inputs
produce an empty model rather than raising.
"""

from __future__ import annotations

from datetime import date as _date, datetime as _datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Iterable, List, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - typing only
    from clients.models.fred import (
        CategoryResponse,
        ObservationsResponse,
        ReleasesResponse,
        SeriesResponse,
    )


__all__ = [
    "FredCategory",
    "FredCategoryList",
    "FredSeries",
    "FredSeriesList",
    "FredObservation",
    "FredObservationList",
    "FredRelease",
    "FredReleaseList",
    "from_category_response",
    "from_series_response",
    "from_observations_response",
    "from_releases_response",
]


#: FRED writes a missing observation as a single period. Anything in this set is
#: reported as ``null`` rather than passed through as a magic string.
_MISSING_VALUES = {".", "", "NA", "N/A"}


class FredResponseModel(BaseModel):
    """Base config: immutable, snake_case, no vendor aliases."""

    model_config = {"frozen": True}


# --- Categories ---------------------------------------------------------------


class FredCategory(FredResponseModel):
    """One node in FRED's category tree."""

    id: int = Field(description="FRED category id; pass it back to browse this category.")
    name: str = Field(description="Display name of the category, e.g. 'Employment Situation'.")
    parent_id: Optional[int] = Field(
        default=None,
        description="Id of the containing category. The root category (0) is its own parent.",
    )


class FredCategoryList(FredResponseModel):
    """Categories returned by a category lookup."""

    categories: List[FredCategory] = Field(
        default_factory=list,
        description="The categories, in the order FRED returned them.",
    )
    count: Optional[int] = Field(
        default=None,
        description=(
            "Total categories FRED has for this query. Greater than the length of "
            "'categories' means the result was truncated."
        ),
    )


# --- Series metadata ----------------------------------------------------------


class FredSeries(FredResponseModel):
    """Metadata for one FRED series — what it measures and what it covers.

    Carries no observations; fetch those with ``fred_series_observations`` using
    ``id``.
    """

    id: str = Field(description="FRED series id, e.g. 'GDP' or 'UNRATE'.")
    title: str = Field(description="Human-readable series title.")
    observation_start: Optional[str] = Field(
        default=None, description="Date of the earliest observation, ISO 'YYYY-MM-DD'."
    )
    observation_end: Optional[str] = Field(
        default=None, description="Date of the latest observation, ISO 'YYYY-MM-DD'."
    )
    frequency: Optional[str] = Field(
        default=None, description="Observation frequency in long form, e.g. 'Quarterly'."
    )
    frequency_short: Optional[str] = Field(
        default=None, description="Frequency abbreviation, e.g. 'Q'."
    )
    units: Optional[str] = Field(
        default=None,
        description="Units in long form, e.g. 'Billions of Chained 2017 Dollars'.",
    )
    units_short: Optional[str] = Field(
        default=None, description="Units abbreviation, e.g. 'Bil. of Chn. 2017 $'."
    )
    seasonal_adjustment: Optional[str] = Field(
        default=None,
        description="Seasonal adjustment in long form, e.g. 'Seasonally Adjusted Annual Rate'.",
    )
    seasonal_adjustment_short: Optional[str] = Field(
        default=None, description="Seasonal adjustment abbreviation, e.g. 'SAAR'."
    )
    last_updated: Optional[str] = Field(
        default=None,
        description=(
            "When FRED last revised the series, ISO-8601 with the offset FRED "
            "reports (US Central), e.g. '2024-03-28T07:52:03-05:00'."
        ),
    )
    popularity: Optional[int] = Field(
        default=None,
        description="FRED's 0-100 popularity score; useful for ranking search results.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Free-text source notes and methodology. Often long, sometimes absent.",
    )


class FredSeriesList(FredResponseModel):
    """Series metadata returned by a series lookup, listing, or update feed.

    Always a list, even for a single-series lookup: FRED returns one shape for
    all of them, and a caller that handles the list handles every tool.
    """

    series: List[FredSeries] = Field(
        default_factory=list,
        description=(
            "The series, in the order FRED returned them. Named 'series' — FRED's "
            "own payload spells this key 'seriess'."
        ),
    )
    count: Optional[int] = Field(
        default=None,
        description=(
            "Total series FRED has for this query. Greater than the length of "
            "'series' means the result was truncated."
        ),
    )


# --- Observations -------------------------------------------------------------


class FredObservation(FredResponseModel):
    """One observation: a date and its value."""

    date: str = Field(description="Observation date, ISO 'YYYY-MM-DD'.")
    value: Optional[str] = Field(
        default=None,
        description=(
            "The observed value as a string — cast it as needed. Null where FRED "
            "has no value for the date (it writes '.' on the wire); the row is "
            "kept so the series' calendar stays intact."
        ),
    )


class FredObservationList(FredResponseModel):
    """A FRED series' observations, ascending by date.

    Two vendor details are resolved here rather than pushed onto the caller:

    * **The '.' sentinel.** FRED marks a missing value with a single period.
      That becomes ``null``, matching the house observation contract; the row
      itself is never dropped, so gaps stay visible as dates with no value.
    * **Per-observation ``realtime_start``/``realtime_end``.** These are
      ALFRED vintage bounds. Under the default (non-vintage) request every
      observation repeats the same pair, echoing the request rather than
      describing the data, so they are dropped. A caller who needs revision
      history wants ALFRED's vintage endpoints, not this field.
    """

    series_id: Optional[str] = Field(
        default=None,
        description=(
            "The series these observations belong to. FRED omits it from the "
            "observations payload, so it is filled in from the request when known."
        ),
    )
    observations: List[FredObservation] = Field(
        default_factory=list,
        description="The observations, ascending by date as FRED returned them.",
    )
    count: Optional[int] = Field(
        default=None,
        description=(
            "Total observations FRED has for this query. Greater than the length "
            "of 'observations' means the result was truncated — page with the "
            "tool's offset/limit."
        ),
    )


# --- Releases -----------------------------------------------------------------


class FredRelease(FredResponseModel):
    """A FRED release — the publication a set of series is issued under."""

    id: int = Field(description="FRED release id; pass it to fred_release_series.")
    name: str = Field(description="Release name, e.g. 'Employment Situation'.")
    press_release: bool = Field(
        default=False,
        description="True when the release is accompanied by a press release.",
    )
    link: Optional[str] = Field(
        default=None, description="URL of the releasing agency's page, when FRED has one."
    )


class FredReleaseList(FredResponseModel):
    """Releases returned by a release listing."""

    releases: List[FredRelease] = Field(
        default_factory=list,
        description="The releases, in the order FRED returned them.",
    )
    count: Optional[int] = Field(
        default=None,
        description=(
            "Total releases FRED has for this query. Greater than the length of "
            "'releases' means the result was truncated."
        ),
    )


# --- Helpers ------------------------------------------------------------------


def _iso(value: Any) -> Optional[str]:
    """Render a date/datetime (or an already-ISO string) as an ISO string."""
    if value is None:
        return None
    if isinstance(value, _datetime):
        return value.isoformat()
    if isinstance(value, _date):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _text(value: Any) -> Optional[str]:
    """Normalize an optional string field: strip, and treat empty as absent."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _value(value: Any) -> Optional[str]:
    """Normalize an observation value, mapping FRED's '.' sentinel to None."""
    if value is None:
        return None
    text = str(value).strip()
    return None if text in _MISSING_VALUES else text


def _items(payload: Any, field: str) -> Iterable[Any]:
    """Read a list field off a payload, tolerating None payloads and None fields.

    Mappings are read by key as well as by attribute. Without that a dict --
    a ``model_dump()`` round-trip, or a cached payload -- would miss every
    ``getattr`` and map to an empty result with no error raised, which is the
    one failure mode a data mapper must not have.
    """
    if payload is None:
        return ()
    if isinstance(payload, Mapping):
        return payload.get(field) or ()
    return getattr(payload, field, None) or ()


def _count(payload: Any) -> Optional[int]:
    """Read the vendor's total, if it reported one."""
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        count = payload.get("count")
    else:
        count = getattr(payload, "count", None)
    return count if isinstance(count, int) else None


# --- Mappers ------------------------------------------------------------------


def from_category_response(payload: "CategoryResponse | None") -> FredCategoryList:
    """Map navi's ``CategoryResponse`` to :class:`FredCategoryList`."""
    return FredCategoryList(
        categories=[
            FredCategory(
                id=category.id,
                name=category.name,
                parent_id=getattr(category, "parent_id", None),
            )
            for category in _items(payload, "categories")
        ],
        count=_count(payload),
    )


def from_series_response(payload: "SeriesResponse | None") -> FredSeriesList:
    """Map navi's ``SeriesResponse`` to :class:`FredSeriesList`.

    This is where ``seriess`` becomes ``series``.
    """
    return FredSeriesList(
        series=[
            FredSeries(
                id=series.id,
                title=series.title,
                observation_start=_iso(getattr(series, "observation_start", None)),
                observation_end=_iso(getattr(series, "observation_end", None)),
                frequency=_text(getattr(series, "frequency", None)),
                frequency_short=_text(getattr(series, "frequency_short", None)),
                units=_text(getattr(series, "units", None)),
                units_short=_text(getattr(series, "units_short", None)),
                seasonal_adjustment=_text(getattr(series, "seasonal_adjustment", None)),
                seasonal_adjustment_short=_text(
                    getattr(series, "seasonal_adjustment_short", None)
                ),
                last_updated=_iso(getattr(series, "last_updated", None)),
                popularity=getattr(series, "popularity", None),
                notes=_text(getattr(series, "notes", None)),
            )
            for series in _items(payload, "seriess")
        ],
        count=_count(payload),
    )


def from_observations_response(
    payload: "ObservationsResponse | None",
    *,
    series_id: Optional[str] = None,
) -> FredObservationList:
    """Map navi's ``ObservationsResponse`` to :class:`FredObservationList`.

    ``series_id`` is optional because FRED's observations payload does not carry
    it; pass the id from the request so the result identifies itself. Every
    observation is preserved — a missing value becomes ``null``, never a dropped
    row.
    """
    return FredObservationList(
        series_id=_text(series_id),
        observations=[
            FredObservation(
                date=_iso(getattr(observation, "date", None)) or "",
                value=_value(getattr(observation, "value", None)),
            )
            for observation in _items(payload, "observations")
        ],
        count=_count(payload),
    )


def from_releases_response(payload: "ReleasesResponse | None") -> FredReleaseList:
    """Map navi's ``ReleasesResponse`` to :class:`FredReleaseList`."""
    return FredReleaseList(
        releases=[
            FredRelease(
                id=release.id,
                name=release.name,
                press_release=bool(getattr(release, "press_release", False)),
                link=_text(getattr(release, "link", None)),
            )
            for release in _items(payload, "releases")
        ],
        count=_count(payload),
    )
