"""MCP response models for the FBI Crime Data Explorer tools.

Like BIS and CDC, navi's FBI models are already snake_case, carry no aliases
and have no HTTP envelope, so ``FbiObservation`` is published as it stands.
What this module adds is **selection**, which is the whole difference between
the API and the three tools.

One CDE request returns four series -- offences and clearances, each as a count
and as a rate -- because the request is parameterised by scope, offence and
date range and by nothing else. A catalog entry, though, identifies *one*
series, and its ``retrieval`` block therefore names a measure and a unit. Those
two arguments are selections made here, over a payload already in hand, and
they never reach the FBI. Anything caching in front of the client should key on
the request rather than on the tool's arguments: keyed on the payload four
series cost one call, keyed on measure and unit they cost four, against an
allowance of a thousand an hour.

**Coverage and population travel with the series, not beside it.** All three
arrive in the same payload, so returning one series and dropping the other two
would make a second call necessary to learn whether the first is usable. They
are published as context fields rather than as extra series: the caller asked
for one series and gets one, with the two numbers that say how much of the
population it rests on. This is what makes 2021 readable -- coverage sits at
96-98% and falls to about 74% that year, as agencies that had not converted
from SRS to NIBRS stopped reporting.

**Whose coverage, though.** An agency request returns three geographies. The
client drops the national comparison but not the agency's state, so a payload
for an ORI can still carry the state's coverage and population where the agency
publishes none of its own. The context therefore carries its own ``label``:
where it does not match the series' geography it says so, rather than passing a
state's figure off as an agency's.

**Arrests are selected the same way and carry one notice unconditionally.**
``fbi_arrests`` returns a single all-offence total, because that is all the
route serves. Its reason for existing is that a CDE clearance is either an
arrest or an exceptional-means clearance and the API reports only their sum, so
arrests beside clearances bound the exceptional share. That bound is an
aggregate one, and the obvious misuse -- differencing all-offence arrests
against one offence's clearances -- is wrong in a way no value in the payload
reveals. So the limit is stated in ``notices`` on every arrest response rather
than only where it happens to bite.

The mappers are pure and total, as in the other modules here: no I/O, and a
``None`` payload maps to an empty record with a notice rather than raising at
the tool boundary.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Literal, NamedTuple, Optional

from pydantic import BaseModel, Field

from clients.fbi import ARREST_VERIFIED_FROM, OFFENSES
from clients.models.fbi import FbiObservation, FbiSeries


__all__ = [
    "EmploymentMeasure",
    "Measure",
    "Offense",
    "Unit",
    "FbiContextSeries",
    "FbiArrestSeries",
    "FbiOffenseSeries",
    "FbiEmploymentSeries",
    "from_arrest_response",
    "from_offense_response",
    "from_employment_response",
]


#: Published as JSON Schema ``enum`` on ``fbi_offenses``, so a caller sees the
#: accepted vocabulary without reading prose. Sourced from the client rather
#: than restated, since the API has no working lookup for it.
Offense = Literal[OFFENSES]
Measure = Literal["offenses", "clearances"]
Unit = Literal["count", "rate"]
EmploymentMeasure = Literal["officers", "civilians"]

#: The tool's ``unit`` against the client's own unit strings. A catalog entry
#: writes ``count``; ``rate`` is the other half of the same payload.
UNITS: dict[str, str] = {"count": "count", "rate": "rate per 100,000"}

#: Below this, a month's figure is not comparable to a normal one and the
#: response says so. Coverage runs 96-98% outside the NIBRS transition.
COVERAGE_FLOOR = 90.0

_NIBRS_NOTICE = (
    "This series spans 2021, when the FBI retired the Summary Reporting System "
    "for NIBRS. Two things changed at once: agencies that had not converted "
    "stopped reporting (the coverage dip), and NIBRS counts every offence in an "
    "incident where SRS counted only the most serious one. Treat the series as "
    "spliced, not continuous."
)

#: Stated on every arrest response rather than conditionally, because it is
#: always true and it is the fact that makes the obvious next step wrong:
#: differencing this against a single-offence clearance series compares an
#: all-offence total with one offence's clearances.
_ARREST_SCOPE_NOTICE = (
    "This is ONE all-offence arrest total: the FBI's arrest route serves no "
    "per-offence, age, sex, race or ethnicity split. It bounds the "
    "exceptional-means share of clearances in aggregate — clearances above "
    "arrests are clearances without one — but it cannot be differenced against "
    "a single offence's clearances from fbi_offenses, which counts a different "
    "population of events."
)


class FbiResponseModel(BaseModel):
    """Base config: immutable, snake_case, no vendor aliases."""

    model_config = {"frozen": True}


class FbiContextSeries(FbiResponseModel):
    """Population or reporting coverage, carried with the series it qualifies."""

    label: str = Field(
        description="The geography this describes, as the CDE labels it ('Texas'). "
                    "An agency payload may carry only its state's, so this is not "
                    "always the series' own geography -- compare it before using."
    )
    unit: str = Field(description="'people' for population, 'percent' for coverage.")
    observations: List[FbiObservation] = Field(
        default_factory=list, description="Same periods as the series, ascending."
    )


class FbiOffenseSeries(FbiResponseModel):
    """One offence or clearance series, monthly, with the context to read it."""

    offense: str
    scope: str = Field(description="As requested: 'national', a state, or an ORI.")
    geography: str = Field(
        default="", description="What the CDE calls the scope, e.g. 'Texas'."
    )
    measure: str = Field(description="'offenses' or 'clearances'.")
    unit: str = Field(description="'count' or 'rate per 100,000'.")
    frequency: str = "Monthly"
    observation_start: Optional[str] = Field(
        default=None, description="First period carrying a value, 'MM-YYYY'. The "
                                  "request window is usually wider than the data."
    )
    observation_end: Optional[str] = None
    observations: List[FbiObservation] = Field(default_factory=list)
    population: Optional[FbiContextSeries] = Field(
        default=None, description="The denominator, monthly -- so a rate is "
                                  "recomputable rather than trusted."
    )
    coverage: Optional[FbiContextSeries] = Field(
        default=None, description="Percent of the population living where agencies "
                                  "reported, monthly."
    )
    coverage_mean_percent: Optional[float] = Field(
        default=None, description="Mean coverage over the returned window. The "
                                  "catalog entry carries the same figure for the "
                                  "full history, so the two compare directly."
    )
    coverage_min_percent: Optional[float] = None
    coverage_min_period: Optional[str] = Field(
        default=None, description="When coverage was worst -- usually a 2021 month."
    )
    max_data_date: Optional[str] = Field(
        default=None, description="Vintage of the underlying UCR data, 'MM/YYYY'."
    )
    last_refresh_date: Optional[str] = None
    notices: List[str] = Field(
        default_factory=list,
        description="Advisories about this particular series -- a 2021 splice, a "
                    "coverage collapse, or nothing selected. Empty when none apply.",
    )


class FbiArrestSeries(FbiResponseModel):
    """Persons arrested in one geography, monthly, with the context to read it.

    The counterpart to ``FbiOffenseSeries``' clearances and the reason the two
    belong together: a clearance is either an arrest or an exceptional-means
    clearance, and the CDE reports only their sum. Arrests beside clearances
    bound the second from outside.

    There is no ``offense`` field because there is no offence to name -- the
    route serves one all-offence total per geography.
    """

    scope: str = Field(description="As requested: 'national', a state, or an ORI.")
    geography: str = Field(
        default="", description="What the CDE calls the scope, e.g. 'Texas'."
    )
    measure: str = Field(
        default="arrests",
        description="Always 'arrests': persons arrested, all offences together.",
    )
    unit: str = Field(description="'count' or 'rate per 100,000'.")
    frequency: str = "Monthly"
    observation_start: Optional[str] = Field(
        default=None,
        description=f"First period carrying a value, 'MM-YYYY'. History is verified "
                    f"back to {ARREST_VERIFIED_FROM}; earlier months are a request "
                    f"for whatever the API has.",
    )
    observation_end: Optional[str] = None
    observations: List[FbiObservation] = Field(default_factory=list)
    population: Optional[FbiContextSeries] = Field(
        default=None, description="The denominator, monthly."
    )
    coverage: Optional[FbiContextSeries] = Field(
        default=None, description="Percent of the population living where agencies "
                                  "reported, monthly. An agency publishes none of "
                                  "its own, so this is usually its state's."
    )
    coverage_mean_percent: Optional[float] = None
    coverage_min_percent: Optional[float] = None
    coverage_min_period: Optional[str] = None
    max_data_date: Optional[str] = Field(
        default=None, description="Vintage of the underlying UCR data, 'MM/YYYY'."
    )
    last_refresh_date: Optional[str] = None
    notices: List[str] = Field(
        default_factory=list,
        description="Advisories about this series. Always states that the total is "
                    "all offences together; adds a 2021 splice, a coverage collapse "
                    "or a stood-in geography where they apply.",
    )


class FbiEmploymentSeries(FbiResponseModel):
    """One agency's sworn officers or civilian employees, annual.

    Male and female are reported separately and summed here, because that is
    the series the catalog names. Counts only: the API's own per-1,000 rates
    divide by a participated population that is sometimes zero.
    """

    ori: str
    measure: str = Field(description="'officers' or 'civilians'.")
    unit: str = "count"
    frequency: str = "Annual"
    observation_start: Optional[str] = Field(
        default=None, description="First year carrying a value, 'YYYY'."
    )
    observation_end: Optional[str] = None
    observations: List[FbiObservation] = Field(
        default_factory=list, description="Male plus female, one point per year."
    )
    population: Optional[FbiContextSeries] = Field(
        default=None,
        description="The 'participated population' the API's own rates divide by. "
                    "Published for provenance, not as a denominator: it is "
                    "sometimes zero and gives impossible per-1,000 figures.",
    )
    max_data_date: Optional[str] = None
    last_refresh_date: Optional[str] = None
    notices: List[str] = Field(
        default_factory=list,
        description="Advisories -- years the agency filed no return, or nothing "
                    "selected. Employment reporting is voluntary and gappy.",
    )


def _geography(label: str) -> str:
    """'Texas Clearances' -> 'Texas'; the CDE labels a geography and a measure at once."""
    return label.rsplit(" ", 1)[0]


def _year(period: str) -> Optional[int]:
    """The year in 'MM-YYYY' or 'YYYY'; None if the period is not one of those."""
    tail = period.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() and len(tail) == 4 else None


def _filled(observations: Iterable[FbiObservation]) -> List[FbiObservation]:
    return [o for o in observations if o.value is not None]


def _span(observations: Iterable[FbiObservation]) -> tuple[Optional[str], Optional[str]]:
    filled = _filled(observations)
    return (filled[0].period, filled[-1].period) if filled else (None, None)


def _crosses_nibrs(observations: Iterable[FbiObservation]) -> bool:
    """True when the series has values on both sides of the 2021 changeover."""
    years = {y for o in _filled(observations) if (y := _year(o.period)) is not None}
    return any(y < 2021 for y in years) and any(y >= 2021 for y in years)


def _context(series: Iterable[FbiSeries], unit: str, geography: str) -> Optional[FbiContextSeries]:
    """The context series for this geography, or the narrowest one on offer.

    An exact label match is preferred; failing that the first candidate is
    returned with its own label attached, so a state's coverage standing in for
    an agency's is visible rather than silent.
    """
    candidates = [s for s in series if s.unit == unit]
    if not candidates:
        return None
    chosen = next((s for s in candidates if s.label == geography), candidates[0])
    return FbiContextSeries(
        label=chosen.label, unit=chosen.unit or unit,
        observations=list(chosen.observations),
    )


class _Qualified(NamedTuple):
    """The population, the coverage and the advisories a series comes with."""

    geography: str
    population: Optional[FbiContextSeries]
    coverage: Optional[FbiContextSeries]
    mean_percent: Optional[float]
    min_percent: Optional[float]
    min_period: Optional[str]
    notices: List[str]


def _qualify(series: Iterable[FbiSeries], chosen: FbiSeries) -> _Qualified:
    """Attach the coverage and population that make one series readable.

    Shared by offences and arrests: both come out of the same payload family,
    and the three things that make a figure misleading -- the 2021 splice, a
    coverage collapse, a wider geography's context standing in for the
    requested one -- are the same in both.
    """
    series = list(series)
    geography = _geography(chosen.label)
    coverage = _context(series, "percent", geography)
    population = _context(series, "people", geography)
    covered = _filled(coverage.observations) if coverage else []
    worst = min(covered, key=lambda o: o.value) if covered else None

    notices: List[str] = []
    if _crosses_nibrs(chosen.observations):
        notices.append(_NIBRS_NOTICE)
    if worst is not None and worst.value < COVERAGE_FLOOR:
        # The worst month is either 2021 or the end of the window, and they
        # mean different things: one is a reporting break, the other a month
        # that has not finished arriving.
        tail = worst.period == covered[-1].period
        notices.append(
            f"Coverage bottoms out at {worst.value}% in {worst.period}: "
            + ("the last month of the window is still filling, so it undercounts "
               "-- drop it before comparing."
               if tail else
               "that month's figure counts what was reported, not what happened.")
        )
    stood_in = sorted({c.label for c in (coverage, population)
                       if c is not None and c.label != geography})
    if stood_in:
        notices.append(
            f"Coverage or population is labelled {', '.join(stood_in)} rather than "
            f"{geography}: the payload carries none for the requested geography "
            f"itself, so the context is the wider one it does carry."
        )
    return _Qualified(
        geography=geography, population=population, coverage=coverage,
        mean_percent=(round(sum(o.value for o in covered) / len(covered), 2)
                      if covered else None),
        min_percent=worst.value if worst else None,
        min_period=worst.period if worst else None,
        notices=notices,
    )


def _select(series: List[FbiSeries], *, measure: str, unit: str,
            scope: str) -> Optional[FbiSeries]:
    """The one series a tool asked for, with the national comparison excluded.

    Belt and braces: the client already drops the national comparison unless it
    was asked for, and at a non-national scope a "United States" series here
    would be one.
    """
    candidates = [s for s in series if s.measure == measure and s.unit == unit]
    if scope != "national":
        candidates = [s for s in candidates
                      if not s.label.startswith("United States")] or candidates
    return candidates[0] if candidates else None


def from_offense_response(
    payload: Any, *, offense: str, scope: str, measure: str = "offenses",
    unit: str = "count",
) -> FbiOffenseSeries:
    """Select one series out of the four a CDE offence payload carries.

    *unit* is the tool's word ('count' or 'rate'), mapped to the client's own
    unit strings by :data:`UNITS`.
    """
    resolved = UNITS.get(unit, unit)
    series: List[FbiSeries] = list(getattr(payload, "series", None) or [])
    chosen = _select(series, measure=measure, unit=resolved, scope=scope)
    if chosen is None:
        return FbiOffenseSeries(
            offense=offense, scope=scope, measure=measure, unit=resolved,
            notices=[f"No {measure} series as {resolved} in the payload for "
                     f"{offense} at {scope}."],
        )

    context = _qualify(series, chosen)
    start, end = _span(chosen.observations)
    return FbiOffenseSeries(
        offense=offense, scope=scope, geography=context.geography,
        measure=chosen.measure, unit=resolved,
        observation_start=start, observation_end=end,
        observations=list(chosen.observations),
        population=context.population,
        coverage=context.coverage,
        coverage_mean_percent=context.mean_percent,
        coverage_min_percent=context.min_percent,
        coverage_min_period=context.min_period,
        max_data_date=getattr(payload, "max_data_date", None),
        last_refresh_date=getattr(payload, "last_refresh_date", None),
        notices=context.notices,
    )


def from_arrest_response(
    payload: Any, *, scope: str, unit: str = "count",
) -> FbiArrestSeries:
    """Select the count or the rate out of an arrest payload.

    One request carries both, as for offences, so *unit* is a selection made
    here and never reaches the FBI. There is no *measure* argument: the route
    serves one all-offence arrest total and nothing else.

    :data:`_ARREST_SCOPE_NOTICE` leads the notices on every response, including
    an empty one. What this series is for -- bounding the exceptional-means
    share of clearances -- is exactly what goes wrong when it is read as an
    offence-level figure, so the limit travels with the numbers.
    """
    resolved = UNITS.get(unit, unit)
    series: List[FbiSeries] = list(getattr(payload, "series", None) or [])
    chosen = _select(series, measure="arrests", unit=resolved, scope=scope)
    if chosen is None:
        return FbiArrestSeries(
            scope=scope, unit=resolved,
            notices=[_ARREST_SCOPE_NOTICE,
                     f"No arrest series as {resolved} in the payload for {scope}. "
                     f"Arrests are verified back to {ARREST_VERIFIED_FROM}; a window "
                     f"entirely before that may simply have nothing in it."],
        )

    context = _qualify(series, chosen)
    start, end = _span(chosen.observations)
    return FbiArrestSeries(
        scope=scope, geography=context.geography, unit=resolved,
        observation_start=start, observation_end=end,
        observations=list(chosen.observations),
        population=context.population,
        coverage=context.coverage,
        coverage_mean_percent=context.mean_percent,
        coverage_min_percent=context.min_percent,
        coverage_min_period=context.min_period,
        max_data_date=getattr(payload, "max_data_date", None),
        last_refresh_date=getattr(payload, "last_refresh_date", None),
        notices=[_ARREST_SCOPE_NOTICE, *context.notices],
    )


def from_employment_response(
    payload: Any, *, ori: str, measure: str = "officers",
) -> FbiEmploymentSeries:
    """Sum the sexes into the one annual series the catalog names.

    ``pe`` reports 'Male Officers' and 'Female Officers' separately; neither is
    the series anybody asks for. A year present in one and absent in the other
    contributes what it has rather than dropping out.
    """
    series: List[FbiSeries] = list(getattr(payload, "series", None) or [])
    parts = [s for s in series if s.measure == measure and s.unit == "count"]
    totals: dict[str, float] = {}
    for part in parts:
        for observation in part.observations:
            if observation.value is not None:
                totals[observation.period] = totals.get(observation.period, 0.0) + observation.value
    observations = [FbiObservation(period=period, value=value)
                    for period, value in sorted(totals.items())]

    notices: List[str] = []
    if not observations:
        notices.append(
            f"No {measure} reported for {ori} in this window. Employment is served "
            f"per agency only -- pe/national and pe/state answer with nulls -- and "
            f"filing is voluntary."
        )
    else:
        years = {_year(o.period) for o in observations}
        first, last = min(y for y in years if y), max(y for y in years if y)
        gaps = [y for y in range(first, last + 1) if y not in years]
        if gaps:
            notices.append(
                f"{len(gaps)} year{'' if len(gaps) == 1 else 's'} between {first} "
                f"and {last} with no return "
                f"({', '.join(str(y) for y in gaps[:8])}"
                f"{', ...' if len(gaps) > 8 else ''}): the agency did not file, "
                f"which is not the same as employing nobody."
            )
    start, end = _span(observations)
    return FbiEmploymentSeries(
        ori=ori, measure=measure,
        observation_start=start, observation_end=end,
        observations=observations,
        population=_context(series, "people", ori),
        max_data_date=getattr(payload, "max_data_date", None),
        last_refresh_date=getattr(payload, "last_refresh_date", None),
        notices=notices,
    )
