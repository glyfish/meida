"""Typed models for the FBI Crime Data Explorer (CDE) API.

The CDE returns wide, chart-shaped payloads rather than series: a nested map of
``{block: {label: {period: value}}}`` where the period is ``MM-YYYY`` for
offences and arrests and ``YYYY`` for employment, and the labels name a
geography and a measure at once ("District of Columbia Offenses", "United
States Clearances", "Texas Arrests").
These models pivot that into observations, so a caller gets series rather than
a chart.

Three blocks are carried through rather than discarded, because all are needed
to use the numbers honestly:

``population``
    The resident population of each geography, monthly -- a denominator the
    caller can choose, but not the one the CDE's own offence and arrest rates
    use.

``participated_population``
    The people living where agencies reported, monthly, under the unit
    ``"participated people"``. This is what the offence and arrest rates
    divide by, so they are recomputable instead of trusted. Coverage is
    exactly this over ``population``, so nationally it is 95.5% of the
    residents in January 2023 and 74.1% in February 2021; at agency scope it
    equals ``population`` in every month the agency has one. Where it is 0 --
    in every month at an agency with no resident population of its own, such
    as the Metro Transit Police (``DCMTP0000``) -- the arrest route publishes
    a rate of -1, which the MCP mappers return as null. The employment
    endpoint's rates divide by one too, and there it is sometimes zero.

``coverage``
    The share of the population living where agencies reported, monthly. It
    runs 96-98% and falls to **74.7% in 2021** as agencies moved to NIBRS. A
    2021 figure is not comparable to a 2019 one, and this is the number that
    says so.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class FbiBaseModel(BaseModel):
    """Base config for immutable FBI models."""

    model_config = {"frozen": True, "populate_by_name": True}


class FbiObservation(FbiBaseModel):
    """One period of one series."""

    period: str = Field(
        description="'MM-YYYY' for offences and arrests, 'YYYY' for employment.")
    value: Optional[float] = Field(
        default=None, description="None where the agency or scope did not report.")


class FbiSeries(FbiBaseModel):
    """One measure for one geography over time."""

    label: str = Field(description="The CDE's own label, e.g. 'Texas Offenses'.")
    scope: str = Field(description="'national', a two-letter state, or an ORI.")
    measure: str = Field(
        description="'offenses', 'clearances', 'arrests', 'officers', "
                    "'civilians', 'population' or 'coverage'.")
    unit: Optional[str] = Field(
        default=None,
        description="'count', 'rate per 100,000', 'percent', 'people' (population) or "
                    "'participated people' (the population the rates divide by).")
    observations: List[FbiObservation] = Field(default_factory=list)

    @property
    def span(self) -> tuple[str, str] | None:
        """First and last period carrying a value, or None if empty."""
        filled = [o.period for o in self.observations if o.value is not None]
        return (filled[0], filled[-1]) if filled else None


class FbiOffenseResponse(FbiBaseModel):
    """What ``summarized`` returns for one offence and one scope.

    Both counts and rates arrive, for the scope *and* for the nation as a
    comparison, along with clearances. ``coverage`` and ``population`` come
    from the same payload.
    """

    offense: str
    scope: str
    series: List[FbiSeries] = Field(default_factory=list)
    max_data_date: Optional[str] = None
    last_refresh_date: Optional[str] = None


class FbiArrestResponse(FbiBaseModel):
    """What ``arrest/{scope}/{offense}`` returns: arrests, monthly.

    One series per geography for the one offence asked for, counts and rates
    together as for offences. The label names the geography only -- "Texas
    Arrests" whether the code was murder or DUI -- so ``offense`` is the only
    record of which offence this is.

    An arrest is not a clearance and does not pair with one. An arrest counts
    one person arrested, cited or summoned on one occasion; a clearance counts
    an offence closed. One arrest can clear several offences and several arrests
    one, and most arrests are for offences with no clearance series at all, so
    this cannot be differenced against an :class:`FbiOffenseResponse`'s
    clearances, in total or for the same offence.
    """

    offense: str = Field(
        default="all",
        description="The UCR arrest code requested: 'all' or a code such as '11'. "
                    "Never in the payload's labels, so carried from the request.")
    scope: str
    series: List[FbiSeries] = Field(default_factory=list)
    max_data_date: Optional[str] = None
    last_refresh_date: Optional[str] = None


class FbiAgency(FbiBaseModel):
    """One law-enforcement agency in the CDE registry."""

    ori: str = Field(description="Originating Agency Identifier, e.g. 'DCMPD0000'.")
    agency_name: Optional[str] = None
    agency_type_name: Optional[str] = Field(
        default=None, description="'City', 'County', 'State Police', 'University or College', "
                                  "'Tribal', 'Other State Agency', 'Other'.")
    state_abbr: Optional[str] = None
    counties: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_nibrs: Optional[bool] = None
    nibrs_start_date: Optional[str] = Field(
        default=None, description="When this agency moved to NIBRS -- the per-agency half of "
                                  "the reporting break that shows up nationally in 2021.")


class FbiEmploymentResponse(FbiBaseModel):
    """What ``pe/agency`` returns: officers and civilians by sex, annual.

    Only the agency scope carries data. ``pe/national`` and ``pe/state/{ST}``
    answer 200 with the full shape and every value null.
    """

    ori: str
    series: List[FbiSeries] = Field(default_factory=list)
    max_data_date: Optional[str] = None
    last_refresh_date: Optional[str] = None

    @property
    def officers(self) -> Dict[int, int]:
        """Sworn officers per year: male plus female, from the counts.

        Built from ``actuals`` and never from the API's ``rates``, whose
        denominator is unreliable -- one Texas agency reports 35 employees per
        1,000 in 1985 and 274 in 2018.
        """
        contributing = [s for s in self.series if s.measure == "officers"]
        reported: Dict[int, list[Optional[float]]] = {}
        for series in contributing:
            for observation in series.observations:
                reported.setdefault(int(observation.period), []).append(observation.value)
        # A year counts only when every contributing series reported it. Summing
        # what happens to be present turns a year where only the male count came
        # back into a plausible-looking total that is roughly half the force.
        return {year: int(sum(v for v in values if v is not None))
                for year, values in sorted(reported.items())
                if len(values) == len(contributing) and all(v is not None for v in values)}
