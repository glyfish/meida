"""Response models for the BLS MCP tools.

The BLS Public Data API wraps every payload in an HTTP-shaped envelope --
``{"status", "responseTime", "message", "Results"}`` -- and buries the actual
observations three levels down at ``Results.series[].data[]``. It also spells a
handful of keys in camelCase (``seriesID``, ``periodName``, ``allowsNetChange``
...). navi's models mirror that wire format because they have to parse it; these
models are what meida *publishes*, so they drop the envelope, keep only data,
and use snake_case names with no aliases at all.

What changes, concretely:

- ``status`` / ``responseTime`` / ``message`` are dropped -- they describe the
  HTTP call, not the data.
- ``Results`` disappears: a series response is ``{"series": [...]}`` and a
  survey response is ``{"surveys": [...]}`` / ``{"survey": {...}}``.
- ``seriesID`` -> ``series_id``, ``periodName`` -> ``period_name``,
  ``allowsNetChange`` -> ``allows_net_change``, ``allowsPercentChange`` ->
  ``allows_percent_change``, ``hasAnnualAverages`` -> ``has_annual_averages``.
- ``Series.data`` -> ``Series.observations``, and each observation gains a
  derived ISO ``date`` (see :func:`derive_observation_date`) beside the raw
  ``year``/``period`` it was derived from.
- The optional nested payloads ``bls_series_data`` can request -- ``catalog``,
  ``calculations``, ``annualaverage`` rows and ``aspects`` -- are modelled and
  carried through, including the survey-specific catalog keys BLS invents per
  survey (kept under ``catalog.additional_fields``).

The mapping functions are pure: no I/O, no network, and every one accepts
``None`` or an empty payload and returns an empty model rather than raising.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from clients.models.bls import (
    Aspect as NaviAspect,
    BlsSeriesResponse as NaviBlsSeriesResponse,
    BlsSurveysResponse as NaviBlsSurveysResponse,
    Calculations as NaviCalculations,
    Catalog as NaviCatalog,
    Footnote as NaviFootnote,
    Observation as NaviObservation,
    Series as NaviSeries,
    Survey as NaviSurvey,
)

# --- period codes -------------------------------------------------------------

PeriodType = Literal[
    "monthly",
    "quarterly",
    "semiannual",
    "annual",
    "annual_average",
    "unknown",
]

# Every ``period`` code BLS publishes, mapped to the month its period starts in.
_MONTHLY_PERIODS: Dict[str, int] = {f"M{month:02d}": month for month in range(1, 13)}
_QUARTERLY_PERIODS: Dict[str, int] = {"Q01": 1, "Q02": 4, "Q03": 7, "Q04": 10}
_SEMIANNUAL_PERIODS: Dict[str, int] = {"S01": 1, "S02": 7}
_ANNUAL_PERIODS: Dict[str, int] = {"A01": 1}
# Aggregates BLS returns alongside the periodic rows when ``annualaverage=true``.
_ANNUAL_AVERAGE_PERIODS: Dict[str, int] = {"M13": 1, "Q05": 1, "S03": 1}

_PERIOD_START_MONTH: Dict[str, int] = {
    **_MONTHLY_PERIODS,
    **_QUARTERLY_PERIODS,
    **_SEMIANNUAL_PERIODS,
    **_ANNUAL_PERIODS,
    **_ANNUAL_AVERAGE_PERIODS,
}

_PERIOD_TYPES: Dict[str, PeriodType] = {
    **{code: "monthly" for code in _MONTHLY_PERIODS},
    **{code: "quarterly" for code in _QUARTERLY_PERIODS},
    **{code: "semiannual" for code in _SEMIANNUAL_PERIODS},
    **{code: "annual" for code in _ANNUAL_PERIODS},
    **{code: "annual_average" for code in _ANNUAL_AVERAGE_PERIODS},
}


def normalize_period(period: Any) -> str:
    """Upper-case and strip a raw ``period`` code; non-strings become ``""``."""
    if not isinstance(period, str):
        return ""
    return period.strip().upper()


def derive_observation_date(year: Any, period: Any) -> Optional[str]:
    """Derive an ISO ``YYYY-MM-DD`` date from BLS's ``year`` + ``period`` pair.

    BLS dates an observation with a 4-digit year string and a coded period
    (``year="2024"``, ``period="M03"``). Every code BLS publishes is mapped to
    the **first day of the period it names**:

    - ``M01``..``M12`` -- calendar month -> ``YYYY-MM-01``
    - ``M13`` -- annual average of the 12 months -> ``YYYY-01-01``
    - ``Q01``..``Q04`` -- calendar quarter -> ``YYYY-01/04/07/10-01``
    - ``Q05`` -- annual average of the 4 quarters -> ``YYYY-01-01``
    - ``S01``/``S02`` -- first/second half -> ``YYYY-01-01`` / ``YYYY-07-01``
    - ``S03`` -- annual average of the 2 halves -> ``YYYY-01-01``
    - ``A01`` -- annual observation -> ``YYYY-01-01``

    Anything else -- an unrecognised code, or a year that is not four digits --
    returns ``None`` rather than a guess or an exception. The observation is
    still published with its raw ``year`` and ``period`` intact and its
    ``period_type`` set to ``"unknown"``, so nothing is lost and no wrong date
    is invented; callers needing a date should filter on ``date is not None``.

    The annual-average codes deliberately share a date with the first period of
    their year (``M13`` with ``M01``, ``Q05`` with ``Q01``, ``S03`` with
    ``S01``), so a series fetched with ``annualaverage=true`` holds two rows
    dated ``YYYY-01-01``. ``period_type`` is what tells them apart.
    """
    month = _PERIOD_START_MONTH.get(normalize_period(period))
    if month is None:
        return None
    if not isinstance(year, str):
        return None
    digits = year.strip()
    if len(digits) != 4 or not digits.isdigit():
        return None
    return f"{digits}-{month:02d}-01"


def derive_period_type(period: Any) -> PeriodType:
    """Classify a BLS ``period`` code; unrecognised codes give ``"unknown"``."""
    return _PERIOD_TYPES.get(normalize_period(period), "unknown")


# --- models -------------------------------------------------------------------


class BlsResponseModel(BaseModel):
    """Base config for the immutable, alias-free BLS response models."""

    model_config = {"frozen": True}


class BlsFootnote(BlsResponseModel):
    """A qualifier BLS attaches to an observation (e.g. ``P`` / "Preliminary")."""

    code: Optional[str] = Field(
        default=None, description="Short footnote code, e.g. 'P' or 'R'."
    )
    text: Optional[str] = Field(
        default=None, description="Human-readable footnote text."
    )


class BlsCalculations(BlsResponseModel):
    """Changes over trailing spans, returned only when ``calculations=true``.

    Both maps are keyed by the span in periods -- ``"1"``, ``"3"``, ``"6"``,
    ``"12"`` -- and their values are stringified numbers, like ``value``.
    """

    net_changes: Dict[str, str] = Field(
        default_factory=dict,
        description="Absolute change over N periods, keyed by N (e.g. {'12': '0.3'}).",
    )
    pct_changes: Dict[str, str] = Field(
        default_factory=dict,
        description="Percent change over N periods, keyed by N (e.g. {'12': '8.6'}).",
    )


class BlsAspect(BlsResponseModel):
    """A secondary measure published beside the value (``aspects=true``).

    Surveys use aspects for things a single number cannot carry -- a standard
    error, an alternate base, a companion count.
    """

    name: Optional[str] = Field(default=None, description="What the aspect measures.")
    value: Optional[str] = Field(
        default=None, description="The aspect's value, stringified like ``value``."
    )
    footnotes: List[BlsFootnote] = Field(
        default_factory=list, description="Footnotes qualifying this aspect."
    )


class BlsCatalog(BlsResponseModel):
    """Series metadata, returned only when ``catalog=true``.

    BLS returns a different set of descriptive keys per survey (a CPI series is
    described by item and area, a CPS series by demographics). The keys common
    to every survey are declared here; the survey-specific remainder is kept
    verbatim in ``additional_fields`` rather than dropped.
    """

    series_title: Optional[str] = Field(
        default=None, description="Human-readable series title."
    )
    series_id: Optional[str] = Field(
        default=None, description="The series' BLS id, as reported by the catalog."
    )
    seasonality: Optional[str] = Field(
        default=None,
        description="'Seasonally Adjusted' or 'Not Seasonally Adjusted'.",
    )
    survey_name: Optional[str] = Field(
        default=None, description="Full name of the survey publishing the series."
    )
    survey_abbreviation: Optional[str] = Field(
        default=None, description="Two-character survey code, e.g. 'LN' or 'CU'."
    )
    measure_data_type: Optional[str] = Field(
        default=None, description="What the value measures, e.g. 'Percent or rate'."
    )
    additional_fields: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Survey-specific catalog keys BLS returned beyond the common ones, "
            "e.g. 'demographic_age', 'area', 'item'. Kept verbatim; the key set "
            "varies by survey."
        ),
    )


class BlsObservation(BlsResponseModel):
    """One datapoint of a series.

    ``date`` is derived from the vendor's ``year``/``period`` pair, which are
    both kept beside it. ``value`` stays a string because BLS sends it as one
    (and uses non-numeric placeholders for withheld data) -- callers cast it.
    """

    date: Optional[str] = Field(
        default=None,
        description=(
            "ISO 'YYYY-MM-DD' start of the period this observation covers, "
            "derived from year + period. None when the period code is one this "
            "API does not recognise -- never a guessed date."
        ),
    )
    value: str = Field(
        default="",
        description=(
            "The observed value as a string; cast it on read. Empty only when "
            "BLS omitted the field entirely."
        ),
    )
    year: str = Field(default="", description="Vendor's 4-digit calendar year, e.g. '2024'.")
    period: str = Field(
        default="",
        description="Vendor's period code: M01-M13, Q01-Q05, S01-S03 or A01.",
    )
    period_name: Optional[str] = Field(
        default=None,
        description="BLS's label for the period, e.g. 'March' or '1st Quarter'.",
    )
    period_type: PeriodType = Field(
        default="unknown",
        description=(
            "Frequency the period code denotes. 'annual_average' marks the "
            "aggregate rows (M13/Q05/S03) that share a date with the year's "
            "first period, so filter on this to keep them out of a monthly or "
            "quarterly series. 'unknown' means the code was unrecognised and "
            "'date' is None."
        ),
    )
    latest: bool = Field(
        default=False,
        description="True on the observation BLS flagged as the series' most recent.",
    )
    footnotes: List[BlsFootnote] = Field(
        default_factory=list,
        description=(
            "Footnotes qualifying this value. BLS pads the list with empty "
            "objects; those carry no code or text and are not republished."
        ),
    )
    calculations: Optional[BlsCalculations] = Field(
        default=None,
        description="Net/percent changes; present only when calculations were requested.",
    )
    aspects: List[BlsAspect] = Field(
        default_factory=list,
        description="Secondary measures; present only when aspects were requested.",
    )


class BlsSeries(BlsResponseModel):
    """One BLS series: its id, optional catalog metadata, and its observations."""

    series_id: str = Field(
        default="", description="BLS series id, e.g. 'LNS14000000'."
    )
    catalog: Optional[BlsCatalog] = Field(
        default=None,
        description="Series metadata; present only when catalog metadata was requested.",
    )
    observations: List[BlsObservation] = Field(
        default_factory=list,
        description=(
            "The series' datapoints, in the order BLS returned them (most recent "
            "first). Empty for endpoints that report ids only, such as the "
            "popular-series list."
        ),
    )


class BlsSeriesData(BlsResponseModel):
    """The series payload shared by the three BLS observation tools.

    ``bls_series_data`` fills in observations (plus catalog, calculations and
    aspects when asked for), ``bls_series_latest`` returns exactly one
    observation per series, and ``bls_popular_series`` returns series ids with
    no observations at all -- it is a discovery list, not data.
    """

    series: List[BlsSeries] = Field(
        default_factory=list,
        description="One entry per requested series, in the order BLS returned them.",
    )
    notices: List[str] = Field(
        default_factory=list,
        description=(
            "Advisories BLS returned alongside a SUCCESSFUL response -- e.g. "
            "'Year range has been reduced to the system-allowed limit of 20 years.' "
            "or a series id that does not exist. This is the only signal that the "
            "data was truncated or partially unfulfilled, so it is published as "
            "data rather than dropped as transport. Empty when BLS reported none."
        ),
    )



class BlsSurvey(BlsResponseModel):
    """A BLS survey -- the program that publishes a family of series."""

    survey_abbreviation: str = Field(
        default="",
        description="Two-character survey code used by the other BLS tools, e.g. 'TU'.",
    )
    survey_name: str = Field(default="", description="Full name of the survey.")
    allows_net_change: Optional[bool] = Field(
        default=None,
        description=(
            "Whether the survey supports net-change calculations. None when BLS "
            "did not report it -- the survey list omits these flags, only the "
            "single-survey lookup carries them."
        ),
    )
    allows_percent_change: Optional[bool] = Field(
        default=None,
        description="Whether the survey supports percent-change calculations; None when unreported.",
    )
    has_annual_averages: Optional[bool] = Field(
        default=None,
        description="Whether the survey publishes annual-average rows; None when unreported.",
    )


class BlsSurveyList(BlsResponseModel):
    """Every BLS survey, as returned by ``bls_all_surveys``.

    A catalog of programs to look up by abbreviation; the per-survey capability
    flags are not populated here (BLS reports them only for a single survey).
    """

    surveys: List[BlsSurvey] = Field(
        default_factory=list, description="All surveys BLS publishes."
    )
    notices: List[str] = Field(
        default_factory=list,
        description=(
            "Advisories BLS returned alongside a SUCCESSFUL response -- e.g. "
            "'Year range has been reduced to the system-allowed limit of 20 years.' "
            "or a series id that does not exist. This is the only signal that the "
            "data was truncated or partially unfulfilled, so it is published as "
            "data rather than dropped as transport. Empty when BLS reported none."
        ),
    )



class BlsSurveyInfo(BlsResponseModel):
    """One survey's metadata, as returned by ``bls_survey_info``.

    Distinct from ``BlsSurveyList`` on purpose: the vendor returns both through
    the same envelope, but this endpoint answers "tell me about survey X" and
    populates the capability flags. ``survey`` is None when the abbreviation
    matched nothing.
    """

    survey: Optional[BlsSurvey] = Field(
        default=None,
        description="The requested survey, or None when the abbreviation matched nothing.",
    )
    notices: List[str] = Field(
        default_factory=list,
        description=(
            "Advisories BLS returned alongside a SUCCESSFUL response -- e.g. "
            "'Year range has been reduced to the system-allowed limit of 20 years.' "
            "or a series id that does not exist. This is the only signal that the "
            "data was truncated or partially unfulfilled, so it is published as "
            "data rather than dropped as transport. Empty when BLS reported none."
        ),
    )



# --- mapping ------------------------------------------------------------------


def _attr(payload: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` off a model/namespace, folding missing and None together.

    Mappings are read by key first. A dict payload -- typically a
    ``model_dump()`` round-trip -- would otherwise miss every ``getattr`` and
    produce an empty result silently, which reads as "BLS returned nothing".
    Keys are navi's field names (``results``), not BLS's wire aliases
    (``Results``); raw vendor JSON is navi's to parse, not ours.
    """
    if isinstance(payload, Mapping):
        value = payload.get(name, default)
    else:
        value = getattr(payload, name, default)
    return default if value is None else value


def _notices(payload: Any) -> List[str]:
    """BLS's ``message[]`` advisories, kept as data.

    On a REQUEST_SUCCEEDED response these are the only indication that the
    result was truncated (a reduced year range) or partially unfulfilled (an
    unknown series id), so discarding them would make the tool silently lossy.
    """
    raw = _attr(payload, "message", [])
    if isinstance(raw, str):
        raw = [raw]
    return [str(item) for item in raw if item]


def _to_bool(raw: Any) -> Optional[bool]:
    """Parse BLS's stringified booleans ('true'/'false'); None when unrecognised."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in {"true", "t", "yes", "y", "1"}:
            return True
        if text in {"false", "f", "no", "n", "0"}:
            return False
    return None


def from_footnote(payload: Optional[NaviFootnote]) -> Optional[BlsFootnote]:
    """Map one footnote; returns None for the empty ``{}`` objects BLS pads with."""
    if payload is None:
        return None
    code = _attr(payload, "code")
    text = _attr(payload, "text")
    if code is None and text is None:
        return None
    return BlsFootnote(code=code, text=text)


def from_footnotes(payload: Any) -> List[BlsFootnote]:
    """Map a footnote list, dropping the content-free entries; None means empty."""
    mapped = (from_footnote(item) for item in payload or [])
    return [footnote for footnote in mapped if footnote is not None]


def from_calculations(payload: Optional[NaviCalculations]) -> Optional[BlsCalculations]:
    """Map the net/percent-change block; None when it was not requested."""
    if payload is None:
        return None
    return BlsCalculations(
        net_changes=dict(_attr(payload, "net_changes", {})),
        pct_changes=dict(_attr(payload, "pct_changes", {})),
    )


def from_aspect(payload: Optional[NaviAspect]) -> BlsAspect:
    """Map one aspect entry."""
    return BlsAspect(
        name=_attr(payload, "name"),
        value=_attr(payload, "value"),
        footnotes=from_footnotes(_attr(payload, "footnotes", [])),
    )


def from_catalog(payload: Optional[NaviCatalog]) -> Optional[BlsCatalog]:
    """Map series catalog metadata, preserving the survey-specific extra keys.

    navi parses the catalog with ``extra="allow"`` because the key set differs
    per survey; those extras land in ``additional_fields`` here.
    """
    if payload is None:
        return None
    extras = _attr(payload, "model_extra", {})
    return BlsCatalog(
        series_title=_attr(payload, "series_title"),
        series_id=_attr(payload, "series_id"),
        seasonality=_attr(payload, "seasonality"),
        survey_name=_attr(payload, "survey_name"),
        survey_abbreviation=_attr(payload, "survey_abbreviation"),
        measure_data_type=_attr(payload, "measure_data_type"),
        additional_fields=dict(extras),
    )


def from_observation(payload: Optional[NaviObservation]) -> BlsObservation:
    """Map one observation, deriving its ISO ``date`` from year + period."""
    year = _attr(payload, "year", "")
    period = _attr(payload, "period", "")
    return BlsObservation(
        date=derive_observation_date(year, period),
        value=_attr(payload, "value", ""),
        year=year,
        period=period,
        period_name=_attr(payload, "period_name"),
        period_type=derive_period_type(period),
        latest=_to_bool(_attr(payload, "latest")) is True,
        footnotes=from_footnotes(_attr(payload, "footnotes", [])),
        calculations=from_calculations(_attr(payload, "calculations")),
        aspects=[from_aspect(aspect) for aspect in _attr(payload, "aspects", [])],
    )


def from_series(payload: Optional[NaviSeries]) -> BlsSeries:
    """Map one series, renaming the vendor's ``data`` list to ``observations``."""
    return BlsSeries(
        series_id=_attr(payload, "series_id", ""),
        catalog=from_catalog(_attr(payload, "catalog")),
        observations=[from_observation(obs) for obs in _attr(payload, "data", [])],
    )


def from_bls_series_response(
    payload: Optional[NaviBlsSeriesResponse],
) -> BlsSeriesData:
    """Map navi's ``BlsSeriesResponse`` (data / latest / popular) to ``BlsSeriesData``.

    Drops the ``status``/``responseTime`` envelope and lifts ``Results.series``
    to the top level, but republishes ``message`` as ``notices`` -- see
    :func:`_notices`. A None or empty payload maps to an empty series list.
    """
    if payload is None:
        return BlsSeriesData()
    results = _attr(payload, "results")
    return BlsSeriesData(
        series=[from_series(series) for series in _attr(results, "series", [])],
        notices=_notices(payload),
    )


def from_survey(payload: Optional[NaviSurvey]) -> BlsSurvey:
    """Map one survey, renaming the camelCase capability flags and parsing them to bools."""
    return BlsSurvey(
        survey_abbreviation=_attr(payload, "survey_abbreviation", ""),
        survey_name=_attr(payload, "survey_name", ""),
        allows_net_change=_to_bool(_attr(payload, "allows_net_change")),
        allows_percent_change=_to_bool(_attr(payload, "allows_percent_change")),
        has_annual_averages=_to_bool(_attr(payload, "has_annual_averages")),
    )


def from_bls_surveys_response(
    payload: Optional[NaviBlsSurveysResponse],
) -> BlsSurveyList:
    """Map navi's ``BlsSurveysResponse`` to the survey *list* (``bls_all_surveys``).

    A None or empty payload maps to an empty list.
    """
    if payload is None:
        return BlsSurveyList()
    results = _attr(payload, "results")
    return BlsSurveyList(
        surveys=[from_survey(survey) for survey in _attr(results, "survey", [])],
        notices=_notices(payload),
    )


def from_bls_survey_response(
    payload: Optional[NaviBlsSurveysResponse],
) -> BlsSurveyInfo:
    """Map navi's ``BlsSurveysResponse`` to a *single* survey (``bls_survey_info``).

    The vendor returns one survey inside the same one-element list it uses for
    the full catalog; this unwraps it. A None, empty, or unmatched payload maps
    to ``survey=None`` rather than raising. If BLS were ever to return more
    than one, the first is taken -- the endpoint is a lookup by abbreviation.
    """
    listing = from_bls_surveys_response(payload)
    return BlsSurveyInfo(
        survey=listing.surveys[0] if listing.surveys else None,
        notices=listing.notices,
    )
