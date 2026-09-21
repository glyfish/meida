"""MCP response models for the FBI Crime Data Explorer tools.

Like BIS and CDC, navi's FBI models are already snake_case, carry no aliases
and have no HTTP envelope, so ``FbiObservation`` is published as it stands.
What this module adds is **selection**, which is the whole difference between
the API and the two tools.

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

The mappers are pure and total, as in the other modules here: no I/O, and a
``None`` payload maps to an empty record with a notice rather than raising at
the tool boundary.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Literal, Optional

from pydantic import BaseModel, Field

from clients.fbi import OFFENSES
from clients.models.fbi import FbiObservation, FbiSeries


__all__ = [
    "EmploymentMeasure",
    "Measure",
    "Offense",
    "Unit",
    "FbiContextSeries",
    "FbiOffenseSeries",
    "FbiEmploymentSeries",
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
    candidates = [s for s in series if s.measure == measure and s.unit == resolved]
    if scope != "national":
        # Belt and braces: the client already drops the national comparison
        # unless it was asked for, and a national series here would be one.
        candidates = [s for s in candidates
                      if not s.label.startswith("United States")] or candidates
    chosen = candidates[0] if candidates else None
    if chosen is None:
        return FbiOffenseSeries(
            offense=offense, scope=scope, measure=measure, unit=resolved,
            notices=[f"No {measure} series as {resolved} in the payload for "
                     f"{offense} at {scope}."],
        )

    geography = _geography(chosen.label)
    coverage = _context(series, "percent", geography)
    population = _context(series, "people", geography)
    covered = _filled(coverage.observations) if coverage else []
    worst = min(covered, key=lambda o: o.value) if covered else None
    start, end = _span(chosen.observations)

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

    return FbiOffenseSeries(
        offense=offense, scope=scope, geography=geography,
        measure=chosen.measure, unit=resolved,
        observation_start=start, observation_end=end,
        observations=list(chosen.observations),
        population=population,
        coverage=coverage,
        coverage_mean_percent=(round(sum(o.value for o in covered) / len(covered), 2)
                               if covered else None),
        coverage_min_percent=worst.value if worst else None,
        coverage_min_period=worst.period if worst else None,
        max_data_date=getattr(payload, "max_data_date", None),
        last_refresh_date=getattr(payload, "last_refresh_date", None),
        notices=notices,
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
