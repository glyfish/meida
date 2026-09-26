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
for one series and gets one, with the numbers that say how much of the
population it rests on. This is what makes 2021 readable -- coverage sits at
96-98% and falls to about 74% that year, as agencies that had not converted
from SRS to NIBRS stopped reporting. **Two populations travel**, because the
CDE's rates divide by the participated one -- the people living where
agencies reported -- and not by the resident one: coverage is exactly the
first over the second. A rate recomputed from ``population`` misses every
month of national and New York ``all`` arrests in the saved payloads, and at
small counts it can still land on the published figure, because the two
decimals hide the gap: New York murder arrests 10 of 12 months of 2023,
California homicide offences 51 of 84 over 2018-2024. Where the participated
population is 0 -- in every month at an agency with no resident population of
its own, such as the Metro Transit Police (DCMTP0000) -- the arrest route
publishes a rate of -1, and a negative rate comes back null here on either
route. The notice that says so asserts that account only where the payload
bears it out -- the value is exactly -1 *and* the scope's own participated
population is 0 in those months -- and otherwise reports the value and the
denominator it actually found: a rate of -2.5 over 330 million participants is
not a transit force, and the offence route, where no -1 has been seen at all,
is not one either. A month nulled that way is **not** a blank: the scope filed
it and the CDE simply could not publish a rate for it, so the missing-return
rule below is told to leave those months alone rather than report the same run
a second time as a return nobody sent.

**Whose coverage, though.** An agency request returns three geographies. The
client drops the national comparison but not the agency's state, so a payload
for an ORI can still carry the state's coverage and population where the agency
publishes none of its own. The context therefore carries its own ``label``:
where it does not match the series' geography it says so, rather than passing a
state's figure off as an agency's.

**A zero is not always a zero, and that is the one trap the coverage series
cannot catch.** The CDE reports a month nobody filed as ``0`` rather than as
``null``. The two spellings are the same fact and which one a scope gets is
arbitrary -- Washington and New York report zeros for the months of 2021 they
did not file, Los Angeles and San Francisco report nulls -- so a test on
``value is not None`` counts a missing return as an observation, and a sum
across it invents data. Coverage cannot show this at agency scope, because an
agency publishes none of its own and the percentage carried is its *state's*:
Washington's Metropolitan Police filed no arrest at all between January 1996
and July 2021, 307 consecutive zeros, under a District of Columbia coverage of
100.0% in every one of those months.

The rule applied here is the notebooks' (``notebooks/fbi/utils/mcp.py``'s
``unfiled``, developed in ``notebooks/fbi/walkthrough.ipynb`` §2): **a run of
blanks is a missing return when the filings it swallowed -- its length times
the local level -- amount to something.** Length alone will not do, because a
department clearing three homicides a month has ordinary zeros and ordinary
quiet quarters; the mass floor is what keeps those. The price is the mirror
image and is stated rather than hidden: a short genuine gap in a small series
now passes as a quiet stretch, and nothing in the payload can tell the two
apart. Detected months come back as **null**, not as zero, and the span names
the filings rather than the request window.

**Arrests are selected the same way and carry one notice unconditionally.**
``fbi_arrests`` returns one offence's arrests, or all offences' together, as a
count or a rate. The offence is a UCR arrest code (``11``, ``260``), which the
payload's labels never name, so the series carries it as ``offense`` along
with its FBI name. The obvious misuse is to read arrests as the arrest half of
``fbi_offenses``' clearances and difference the two. That is wrong: an arrest
counts a person taken in on one occasion and a clearance an offence closed,
one arrest can clear several offences and several arrests one, and most
arrests are for offences with no clearance series at all. No value in the
payload shows the difference, so ``notices`` says so on every arrest response,
and adds a sentence for the codes whose names mislead -- 50 is aggravated
assault, 23 held no rape arrests in 2023, and 140, 150 and 170 are only their
groups' unspecified remainders.

**Nationally, for one offence the CDE spells a month with no arrest as
null**, not 0: code 172 for 2023-2024 comes back null in 21 of 24 months, and
its other three months sum to the FBI's 2023 total for it. At agency scope it
has not been seen to: San Francisco's and the NYPD's murder arrests are 0, not
null, in months the department filed other arrests, and the only nulls in the
saved agency payloads -- San Francisco's and Los Angeles' twelve months of
2021 -- are months with no participated population at all. So a single
code's nulls are read before the rule above sees them -- 0 where the scope's
*own* participated population is above zero for the month and the month is
not past ``max_data_date``, null otherwise -- and a value the CDE sent, zero
included, goes to the rule as it came.

The rule then treats a single code's trailing run by scope. Nationally and
for a state the participated population is the sum over the agencies that
reported, so a quiet final stretch under one is quiet, and the trailing run is
held to the same mass test as any other run -- a rare code's final months are
often empty. An agency's participated population carries on after it stops
filing (San Francisco filed no arrest in 2024 under one in every month), so
there the trailing run is nulled at any level, as for ``all``. Either way a
single code is judged on its **counts**, whichever unit is returned: the mass
floor is in arrests, and a rate of 0.3 per 100,000 would pass as a quiet
stretch where the count behind it is a missing return.

The mappers are pure and total, as in the other modules here: no I/O, and a
``None`` payload maps to an empty record with a notice rather than raising at
the tool boundary.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Literal, NamedTuple, Optional, Sequence

from pydantic import BaseModel, Field

from clients.fbi import (
    ARREST_OFFENSES, ARREST_VERIFIED_FROM, OFFENSES, PARTICIPATED, FbiAPIError, FbiClient,
    arrest_offense,
)
from clients.models.fbi import FbiObservation, FbiSeries


__all__ = [
    "ArrestOffense",
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
#: The UCR arrest codes, published as the ``enum`` on ``fbi_arrests`` in the
#: same way, so an unknown code is refused at the tool boundary before it can
#: become a failed request against the shared key. Codes rather than names,
#: because the codes are what the API takes; the tool lists the names.
ArrestOffense = Literal[tuple(ARREST_OFFENSES)]
Measure = Literal["offenses", "clearances"]
Unit = Literal["count", "rate"]
EmploymentMeasure = Literal["officers", "civilians"]

#: The tool's ``unit`` against the client's own unit strings. A catalog entry
#: writes ``count``; ``rate`` is the other half of the same payload.
UNITS: dict[str, str] = {"count": "count", "rate": "rate per 100,000"}

#: Below this, a month's figure is not comparable to a normal one and the
#: response says so. Coverage runs 96-98% outside the NIBRS transition.
COVERAGE_FLOOR = 90.0

#: The run-and-mass rule for a missing return, carried over from
#: ``notebooks/fbi/utils/mcp.py`` and ``notebooks/fbi/walkthrough.ipynb`` §2 so
#: the tools and the notebooks call the same months unfiled.
#:
#: ``UNFILED_RUN_FLOOR``
#:     The filings a run has to swallow before it is read as a gap: its length
#:     times the local level. Washington's thinnest real gap in the notebooks,
#:     two blank months at a median of 19 clearances, swallows 38 and clears
#:     this comfortably; San Francisco's ordinary zero quarters, at two or
#:     three clearances a month, do not.
#: ``LEVEL_SPAN``
#:     Periods in the centred window whose median says what a period in this
#:     stretch of the series normally looks like. Centred rather than trailing:
#:     the months after a run are as much evidence of its level as the months
#:     before -- except at the end of the window, where there is nothing to the
#:     right and the window truncates to the left of its own accord.
#:
#: **There is no minimum run length.** There was one -- two blanks, on the
#: ground that one blank month is a month -- and it made the floor unreachable
#: for a run of one however large the level, which is how a single skipped year
#: passed at a department of three thousand officers where two consecutive ones
#: were caught. The mass floor already carries that case: a run of *k* blanks
#: where a period normally holds *L* has probability :math:`e^{-kL}` if the
#: filings arrive independently, so ``k * L >= 25`` puts the run below
#: :math:`10^{-10}` at *k* = 1 exactly as it does at *k* = 2, and a lone blank
#: in a small series -- San Francisco's zero clearance months, at a level of two
#: to four -- is kept by the floor rather than by its length. **This is where
#: the tool and** ``notebooks/fbi/utils/filing.py`` **differ**: that module's
#: ``unreadable`` still takes ``min_run=2``, so a lone blank at a level above 25
#: is null here and a readable zero there. The two agree on every longer run.
UNFILED_RUN_FLOOR = 25.0
LEVEL_SPAN = 25

#: A periodic return: a blank run closed by a filing that carries the whole
#: period, which the CDE serves as a blank run and one large month with nothing
#: to say the two belong together.
#:
#: ``PERIOD_LENGTHS``
#:     The schedules seen in the payloads: quarterly, semiannual and annual. A
#:     run of ``k - 1`` blanks closed by a filing is a candidate for period
#:     ``k``. Nothing else is: a seven-month run (Washington's 2021 conversion)
#:     and a twelve-month one (San Francisco's 2021) are gaps, and a run of four
#:     or eight matches no filing schedule the CDE has been seen to carry.
#: ``PERIOD_SHARE``
#:     The share of the period's expected filings the closing month must carry
#:     before the run is read as a schedule rather than as a gap that happened
#:     to be ``k - 1`` months long. Half: New York's quarterly homicide months
#:     of 2005 carry 119 against a quarter's 129 at the level either side of the
#:     stretch, Washington's four annual arrest Decembers 55,607-67,941 against
#:     a year's 62,000, and its 1996 semiannual pair 198 and 199 against 198 --
#:     while a two-month gap in a series running at the floor closes with an
#:     ordinary month and clears nothing.
#: ``PERIOD_CEILING``
#:     And the share it must not exceed, because a filing far above the period's
#:     expected mass carries more than the period and calling it a schedule
#:     would misdescribe it. Every schedule measured in the saved payloads lands
#:     near one: New York's quarterly homicide Septembers at 1.01 of a quarter,
#:     Washington's annual arrest Decembers at 0.87 to 1.06 of a year, its 1997
#:     homicides at 1.17, its 1996 half-years at 0.88 and 1.00. New York's
#:     12-1993 arrests, 667,414 after eight blank months, one filing and two
#:     more blanks, are 2.6 times a quarter and cover most of a year: the two
#:     blanks before them are missing returns and the December is a lump, which
#:     is what this ceiling makes of them.
#: ``ORDINARY_MIN``
#:     Filings that are not themselves a period's closing month, in the centred
#:     window, before the window is allowed to say what a month normally holds.
#:     Fewer than this and there is nothing uncontaminated to measure against --
#:     New York filed quarterly for ten years, so every window inside that
#:     stretch is lumps and blanks -- and the level falls back to the median of
#:     the candidates' own per-month figures.
#: ``LUMP_SHARE``
#:     A filing this many times the level around it carries more than one month
#:     whether or not a blank run precedes it, which is the shape of
#:     Washington's 12-1989 arrests: 62,900 after eleven months of 579-902. It
#:     is deliberately above every routine December in the national series,
#:     where annual reconciliation puts December 2.1 to 2.4 times a normal month
#:     in every year of 1985-2026 (12-2020, the largest, is 3,601 against
#:     1,555).
#: ``LUMP_FLOOR``
#:     The level a month has to be measured against before three times it means
#:     anything, and the share alone is not enough. At a level of two to six a
#:     month at three times it is an ordinary bad month: San Francisco's
#:     homicide offences and clearances, at six and three a month, hold thirteen
#:     such months over 1985-2007 (11-2005 is 20 offences against a normal 6,
#:     11-1997 is 18 clearances against a normal 2) and not one of them carries a
#:     second month's filings. At a level of 25 the same multiple is out of
#:     reach: 75 filings where 25 are expected is beyond any month-to-month
#:     variation these series show, and what is left is Washington's 62,900
#:     against 751 and its 06-1996 homicides, 198 against 34.
PERIOD_LENGTHS = (3, 6, 12)
PERIOD_SHARE = 0.5
PERIOD_CEILING = 2.0
ORDINARY_MIN = 6
LUMP_SHARE = 3.0
LUMP_FLOOR = 25.0

#: A last month under this share of the local level is still filling rather
#: than low -- but only where the level is worth measuring against, which is
#: what ``PARTIAL_FLOOR`` is for. Washington's September 2026 reports 5 arrests
#: against 2,288 the month before; a village reporting one arrest against a
#: normal two is not evidence of anything.
PARTIAL_SHARE = 0.1
PARTIAL_FLOOR = 25.0

_NIBRS_NOTICE = (
    "This series spans 2021, when the FBI retired the Summary Reporting System "
    "for NIBRS. Two things changed at once: agencies that had not converted "
    "stopped reporting (the coverage dip), and NIBRS counts every offence in an "
    "incident where SRS counted only the most serious one. Treat the series as "
    "spliced, not continuous."
)

#: What an arrest is not, stated on every arrest response rather than
#: conditionally, because it is always true and it is the fact that makes the
#: obvious next step wrong: differencing arrests against clearances, as if the
#: gap were the clearances made by exceptional means.
_ARREST_NOT_A_CLEARANCE = (
    "An arrest is NOT a clearance: an arrest counts one person arrested, cited or "
    "summoned on one occasion, a clearance counts one offence closed, and one arrest "
    "can clear several offences while several arrests can clear one. The two routes "
    "also carry their own coverage. So this cannot be differenced against "
    "fbi_offenses' clearances — not in total and not for the same offence — and the "
    "pair does not show how many clearances were made by exceptional means."
)

#: The codes whose FBI names mislead, each with the sentence that says how.
#: Figures are national 2023, from the live ``totals`` breakdown.
_ARREST_CODE_NOTES: dict[str, str] = {
    "20": ("Code 20 is the LEGACY rape definition, yet it holds every rape arrest "
           "nationally in 2023 (18,769) and code 23 none: take the two together for "
           "rape arrests."),
    "23": ("Code 23 held NO rape arrests nationally in 2023 — that year's 18,769 are "
           "all under code 20, the legacy definition. Take the two together for rape "
           "arrests."),
    "50": ("Code 50, 'Assault - Not Specified', is AGGRAVATED assault: the FBI's own "
           "totals file its 330,173 national 2023 arrests as 'Aggravated Assault'. "
           "Simple assault is code 55."),
    "140": ("Code 140 is only the prostitution arrests given no sub-code, not all of "
            "them: codes 141-143 hold the rest. Add 140-143 for the total."),
    "150": ("Code 150 is only the drug arrests given no sub-code, not all of them: "
            "nationally in 2023 it holds 55,325 of the 918,020 drug arrests in codes "
            "150-160. Add 150-160 for the total."),
    "170": ("Code 170 is only the gambling arrests given no sub-code, not all of "
            "them: codes 171-173 hold the rest. Add 170-173 for the total."),
}


def _arrest_notices(offense: str) -> List[str]:
    """What every arrest response leads with: which offence, and what it is not.

    The offence is named in prose as well as in the ``offense`` field because
    the CDE's labels never name it -- murder comes back as "Texas Arrests" -- and
    a caller holding only the numbers has no other way to tell.
    """
    if offense == "all":
        what = ("Arrests for ALL offences together (code 'all'). Most are for offences "
                "fbi_offenses has no series for: nationally in 2023 only 17.5% of "
                "arrests were for its eight offences, the rest for drug possession, "
                "DUI, simple assault, disorderly conduct and the like. ")
    else:
        what = (f"Arrests for {ARREST_OFFENSES.get(offense, offense)} only (UCR arrest "
                f"code {offense}). Each arrest is filed under one code; nationally in "
                f"2023, the one window checked, the codes add up to 'all' bar 905 "
                f"arrests filed under 'Suspicion', which has no code. ")
    notices = [what + _ARREST_NOT_A_CLEARANCE]
    if offense in _ARREST_CODE_NOTES:
        notices.append(_ARREST_CODE_NOTES[offense])
    return notices


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
    unit: str = Field(
        description="'people' for population, 'participated people' for the "
                    "population the rates divide by, 'percent' for coverage.")
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
        default=None, description="First period carrying a FILING, 'MM-YYYY'. The "
                                  "request window is usually wider than the data, "
                                  "and the CDE pads the difference with 0 rather "
                                  "than with null -- this names the filings."
    )
    observation_end: Optional[str] = None
    observations: List[FbiObservation] = Field(
        default_factory=list,
        description="Monthly, ascending. A value of null is a month with no return "
                    "behind it, which includes months the CDE reported as 0: see "
                    "'notices', which names them. Do not read a null as a zero.")
    population: Optional[FbiContextSeries] = Field(
        default=None, description="Resident population, monthly. NOT what the "
                                  "rate divides by: see participated_population."
    )
    participated_population: Optional[FbiContextSeries] = Field(
        default=None,
        description="The people living where agencies reported, monthly: the "
                    "rate's denominator, so rate = 100,000 x count / this, and "
                    "coverage = 100 x this / population. Below the resident "
                    "population wherever coverage is below 100%. Where it is 0 "
                    "the rate is undefined, and a negative rate -- the arrest "
                    "route publishes -1 there -- is returned as null.",
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
                    "coverage collapse, months nobody filed, a rate over a "
                    "participated population of 0, a last month still filling, "
                    "or nothing selected. Empty when none apply.",
    )


class FbiArrestSeries(FbiResponseModel):
    """Arrests for one offence, or all, in one geography, monthly, with context.

    ``offense`` is the UCR arrest code and ``offense_name`` the FBI's name for
    it. Not a counterpart to ``FbiOffenseSeries``' clearances: an arrest counts
    a person taken in on one occasion and a clearance an offence closed, so the
    two are in different units and are never differenced.
    """

    offense: str = Field(
        default="all",
        description="The UCR arrest code: 'all', or a code such as '11'. The CDE's "
                    "labels never name it, so this is the only record of which "
                    "offence the series counts.",
    )
    offense_name: str = Field(
        default=ARREST_OFFENSES["all"],
        description="The FBI's name for the code, e.g. 'Murder and Nonnegligent "
                    "Homicide'. Some mislead -- code 50, 'Assault - Not Specified', "
                    "is aggravated assault -- and 'notices' says which.",
    )
    scope: str = Field(description="As requested: 'national', a state, or an ORI.")
    geography: str = Field(
        default="", description="What the CDE calls the scope, e.g. 'Texas'."
    )
    measure: str = Field(
        default="arrests",
        description="Always 'arrests'; 'offense' says for what.",
    )
    unit: str = Field(description="'count' or 'rate per 100,000'.")
    frequency: str = "Monthly"
    observation_start: Optional[str] = Field(
        default=None,
        description=f"First period carrying a FILING, 'MM-YYYY'. History is verified "
                    f"back to {ARREST_VERIFIED_FROM}; earlier months are a request "
                    f"for whatever the API has, and the CDE pads what it has none of "
                    f"with 0 rather than with null.",
    )
    observation_end: Optional[str] = None
    observations: List[FbiObservation] = Field(
        default_factory=list,
        description="Monthly, ascending. A value of null is a month with no return "
                    "behind it, which includes months the CDE reported as 0: see "
                    "'notices', which names them. Do not read a null as a zero. "
                    "Nationally, for a single offence (any code but 'all') the CDE "
                    "spells a month with no arrest for it as null (at agency scope "
                    "it has sent 0); where the scope's own participated population "
                    "is above zero that month this returns the null as 0, so a sum "
                    "counts what the FBI's own totals count. AT AGENCY SCOPE a run "
                    "of blanks that reaches the end of the window is returned as "
                    "null whatever its length and however quiet the series -- an "
                    "agency's participated population carries on after it stops "
                    "filing, so nothing else can say the run is a gap -- so "
                    "observation_end can fall short of the requested end by as "
                    "little as one month, and a genuinely quiet final month is "
                    "nulled with the rest.")
    population: Optional[FbiContextSeries] = Field(
        default=None, description="Resident population, monthly. NOT what the "
                                  "rate divides by: see participated_population."
    )
    participated_population: Optional[FbiContextSeries] = Field(
        default=None,
        description="The people living where agencies reported, monthly: the "
                    "rate's denominator, so rate = 100,000 x count / this, and "
                    "coverage = 100 x this / population. At agency scope it "
                    "equals the agency's population. Where it is 0 -- in every "
                    "month at an agency with no resident population of its own, "
                    "such as a transit or campus force -- the CDE's rate is -1, "
                    "and that is returned as null.",
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
        description="Advisories about this series. Always names the offence and "
                    "states that an arrest is not a clearance; adds a misleading "
                    "code name, a 2021 splice, a coverage collapse, a stood-in "
                    "geography, a single offence's nulls read as zero arrests, "
                    "the months nobody filed, months past max_data_date, a rate "
                    "over a participated population of 0, or a last month still "
                    "filling where they apply.",
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
        default=None, description="First year carrying a RETURN, 'YYYY'."
    )
    observation_end: Optional[str] = None
    observations: List[FbiObservation] = Field(
        default_factory=list,
        description="Male plus female, one point per year. A value of null is a year "
                    "with no return behind it, including one the CDE reported as 0."
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
        description="Advisories -- years the agency filed no return (including the "
                    "ones the CDE spells as 0), a window running past the last "
                    "return, or nothing selected. Employment reporting is voluntary "
                    "and gappy.",
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


def _median(values: Iterable[float]) -> float:
    """Median of what is there, 0.0 for nothing. Never raises."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    return (ordered[middle] if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) / 2.0)


def _levels(values: Sequence[Optional[float]], span: int = LEVEL_SPAN) -> List[float]:
    """What a filed period in this stretch of the series normally carries.

    The median of the filings in a centred window, per period. Where a whole
    window is blank the window offers no level at all -- Washington filed no
    arrest for twenty-five years, so every window inside that stretch is empty
    -- and the series' own median filing stands in, which is the only evidence
    left about what those months would have held.
    """
    filed = [v for v in values if v]
    overall = _median(filed)
    half = span // 2
    return [_median([v for v in values[max(0, i - half):i + half + 1] if v]) or overall
            for i in range(len(values))]


def _runs(values: Sequence[Optional[float]],
          spared: Iterable[int] = ()) -> List[tuple[int, int]]:
    """``(start, stop)`` of every maximal blank run, ``stop`` exclusive.

    A null and a zero are one fact here: which spelling a scope gets is
    arbitrary, and a run can mix them. *spared* is positions that are not to
    count as blank -- they neither join a run nor split one.
    """
    kept = set(spared)
    out: List[tuple[int, int]] = []
    start: Optional[int] = None
    for i, value in enumerate([*values, 1.0]):
        blank = i < len(values) and (value is None or value == 0) and i not in kept
        if blank and start is None:
            start = i
        elif not blank and start is not None:
            out.append((start, i))
            start = None
    return out


def _level_around(values: Sequence[Optional[float]], index: int,
                  skip: Iterable[int] = (), span: int = LEVEL_SPAN) -> Optional[float]:
    """What an ordinary period near *index* carries, or None if nothing says.

    The median of the filings in a centred window with *index* itself and every
    position in *skip* left out. :func:`_levels` counts the period itself, which
    is right for judging a run and wrong for judging a large filing: where a
    window holds little but the closing months of periodic returns, the median
    *is* one of them and no lump exceeds it. ``None`` where fewer than
    :data:`ORDINARY_MIN` filings are left, which is the honest answer for New
    York's decade of quarterly homicide filings -- there is no ordinary month in
    that neighbourhood to measure a quarter against.
    """
    excluded = {*skip, index}
    half = span // 2
    window = [v for i, v in enumerate(values)
              if max(0, index - half) <= i <= index + half and i not in excluded and v]
    return _median(window) if len(window) >= ORDINARY_MIN else None


class _Period(NamedTuple):
    """One periodic return: the blank months and the filing that closes them.

    ``start`` / ``closer``
        The first blank and the filing that carries the period, inclusive.
    ``months``
        The period in months -- 3, 6 or 12 -- which is the blanks plus the
        closing month.
    ``level``
        What an ordinary month nearby carries, or, where the neighbourhood has
        none, the candidates' own per-month figure. The notice quotes it.
    ``measured``
        True where *level* came from ordinary months rather than from the
        candidates themselves, so a notice can say which.
    """

    start: int
    closer: int
    months: int
    level: float
    measured: bool

    @property
    def blanks(self) -> range:
        """The blank months, without the filing that closes them."""
        return range(self.start, self.closer)


def _periodic(values: Sequence[Optional[float]], levels: Sequence[float],
              spared: Iterable[int] = ()) -> List[_Period]:
    """The runs that are a filing schedule rather than a missing return.

    An agency that files quarterly or annually sends the CDE the blanks *and* a
    month carrying the whole period, and the payload says nothing about the
    pair: Washington filed its 1993 homicides in four Marches, Junes,
    Septembers and Decembers of 113, 113, 113 and 115 against a normal 36 a
    month, its 1992-1995 arrests in four Decembers of 55,607-67,941, and New
    York filed homicides quarterly for the ten years to December 2012.

    Three tests, in this order.

    *Shape.* A maximal blank run of ``k - 1`` periods closed by a filing, where
    ``k`` is one of :data:`PERIOD_LENGTHS`. A trailing run has no closing filing
    and is therefore never periodic, however long: the period it would belong to
    has not been filed yet.

    *The run would otherwise be read as a missing return.* Its length times its
    local level reaches :data:`UNFILED_RUN_FLOOR`, which is :func:`_unfiled`'s
    own test. A run this rule would keep anyway needs no schedule to explain it,
    and claiming one would be a false claim about a quiet stretch: national
    arrests for gambling-numbers (code 172) run at three a year, so two blank
    months closed by a filing of 1 match the shape of a quarter and mean
    nothing. New York's quarterly homicide blanks swallow about 63 a month and
    Washington's annual arrest blanks about 5,000.

    *Mass.* The closing filing carries between :data:`PERIOD_SHARE` and
    :data:`PERIOD_CEILING` of the ``k`` periods' expected filings, measured by
    :func:`_level_around` with every candidate's closing month left out. Below
    the floor it is an ordinary month after an ordinary quiet stretch; above the
    ceiling it carries more than the period it would be named for, and is left
    to :func:`_lumps` with its blanks left to the missing-return rule. Where
    the neighbourhood holds fewer than :data:`ORDINARY_MIN` ordinary filings
    the candidates' own per-month figures stand in, which makes the shape
    decide -- and the ceiling then rarely bites, since that level is the
    candidates' own. That is the
    honest position for a series that is periodic throughout a stretch, since
    there is no monthly filing anywhere near it to compare against.

    What this cannot do is tell a quarterly filer from a department that
    happened to file in March, June, September and December: the payload carries
    the same twelve numbers either way. The notice says so rather than the
    docstring alone.
    """
    runs = [(start, stop) for start, stop in _runs(values, spared)
            if stop < len(values) and (stop - start) + 1 in PERIOD_LENGTHS
            and (stop - start) * _median(levels[start:stop]) >= UNFILED_RUN_FLOOR]
    closers = {stop for _, stop in runs}
    implied = _median([(values[stop] or 0.0) / ((stop - start) + 1)
                       for start, stop in runs])
    out: List[_Period] = []
    for start, stop in runs:
        months = (stop - start) + 1
        measured = _level_around(values, stop, closers)
        level = measured if measured is not None else implied
        expected = months * level
        filing = values[stop] or 0.0
        if level and PERIOD_SHARE * expected <= filing <= PERIOD_CEILING * expected:
            out.append(_Period(start=start, closer=stop, months=months,
                               level=level, measured=measured is not None))
    return out


def _lumps(values: Sequence[Optional[float]], periodic: Sequence[_Period]) -> List[int]:
    """Filings too large to be one period, with no blank run to explain them.

    Washington's arrests for 1989 are eleven months of 579 to 902 and a December
    of 62,900, against four to seven thousand a month either side of the year:
    the December carries the year and the other eleven are part-filings, and no
    blank run marks any of it. There is nothing here to null and no schedule to
    name, so this only reports -- naming the month is the whole of what the
    payload supports.

    A month is reported where it carries :data:`LUMP_SHARE` times what an
    ordinary month nearby carries, that level is at least :data:`LUMP_FLOOR` --
    below it a month at three times the level is an ordinary bad month and
    nothing else, which is San Francisco's three-clearances-a-month series over
    and over -- it is not a periodic return's closing month, and the
    neighbourhood has enough ordinary months to say what normal is.
    """
    closers = {period.closer for period in periodic}
    return [i for i, value in enumerate(values)
            if value and i not in closers
            and (level := _level_around(values, i, closers)) is not None
            and level >= LUMP_FLOOR and value >= LUMP_SHARE * level]


def _unfiled(values: Sequence[Optional[float]], levels: Sequence[float], *,
             open_tail: bool = True, filed: Iterable[int] = ()) -> List[int]:
    """Indexes of the periods that are blank because nobody filed.

    A null and a zero are the same fact here and are treated as one: which
    spelling a scope gets is arbitrary, and a run can mix them.

    *filed* is the positions whose blank is already accounted for, and those are
    not blanks at all here: they neither qualify nor join or split a run. Two
    kinds reach it. A rate the payload published as -1, which :func:`_defined`
    nulled -- the scope filed that period and the value was removed because it
    could not be published, not because nothing arrived; left in, such a run
    would be reported a second time as a missing return, and described with the
    spelling the CDE did not use. And the blank months of a periodic return
    (:func:`_periodic`), which are the schedule the scope files on rather than
    returns it skipped.

    Two ways a run qualifies.

    *By mass.* The run's length times its local level reaches
    :data:`UNFILED_RUN_FLOOR`. There is no minimum length: the floor is what
    keeps a small series' quiet months, and it keeps a lone one as surely as a
    pair. This is the whole of the test for a run with filings on both sides of
    it, and for a run at the start of the window -- a request routinely reaches
    back further than an agency does, and the CDE pads what it has no data for
    with zeros exactly as it pads a skipped return.

    *By sitting at the end of the window.* A trailing run is taken at any
    length and without the mass test, because the evidence that decides the
    others is missing: there are no filings after it to weigh it against, and
    the tool's window runs to the current month, whose return has not arrived.
    A genuinely quiet final month is nulled by this, which costs a consumer one
    month; leaving it costs them an ``observation_end`` that names a month with
    nothing in it. A series that is blank throughout is exempt -- with no
    filing anywhere there is no level, and nothing to say the scope is not
    simply reporting zeros.

    *open_tail* False holds the trailing run to the mass test like any other,
    with the level taken from the filings to its left, which are the only ones
    there are. Two callers ask for it. A single offence's arrests at national or
    state scope only, where a quiet final stretch is common and real -- a code
    with five arrests a year nationally has trailing zeros as often as not --
    and where the evidence the open tail stands in for is in the payload: the
    arrest mapper has cut the months past ``max_data_date``, and has read a null
    as a month with no arrest only where the participated population, summed
    over the agencies that reported that month, is above zero. An agency's
    participated population is no such evidence -- San Francisco's carries on
    through 2024, a year it filed no arrest -- so an agency's trailing run stays
    open. And the offence route, wherever the window ends before
    ``max_data_date`` and the CDE cannot have been padding: see
    :func:`_read_filings`.

    So the three routes do not answer this the same way, and the difference is
    worth having in one place because a caller comparing one agency's arrests
    with its offences over the same window meets both answers:

    ======================  ==============================================
    series                  a trailing blank run at the end of the window
    ======================  ==============================================
    offences, clearances    the vintage decides: padding at or past
                            ``max_data_date``, otherwise held to the mass
                            test like any interior run. San Francisco's
                            forty-five zero clearance months are why
    arrests, ``all``        nulled at any length, at every scope: a
                            department that files anything files arrests,
                            so a blank run is never a quiet stretch
    arrests, one code       nulled at any length at agency scope, held to
                            the mass test nationally and by state, where a
                            rare code's quiet tail is ordinary and real
    employment              nulled at any length -- the annual response
                            has its own sentence for a year with no return
    ======================  ==============================================

    Each of those was settled against live payloads rather than chosen, and
    each is pinned by a test. What none of them can do is tell an agency that
    stopped filing from one with a genuinely quiet stretch, because the coverage
    an agency payload carries is its state's; the notices say so rather than
    implying otherwise.
    """
    kept = set(filed)
    out: List[int] = []
    for start, stop in _runs(values, kept):
        length = stop - start
        trailing = open_tail and stop == len(values) and start > 0
        if trailing or length * _median(levels[start:stop]) >= UNFILED_RUN_FLOOR:
            out.extend(range(start, stop))
    return out


def _spans(observations: Sequence[FbiObservation], indexes: Iterable[int]) -> List[str]:
    """Consecutive indexes as ``'MM-YYYY'`` or ``'MM-YYYY..MM-YYYY'``."""
    spans: List[str] = []
    run: List[int] = []
    for index in sorted(indexes):
        if run and index != run[-1] + 1:
            spans.append(_label(observations, run))
            run = []
        run.append(index)
    if run:
        spans.append(_label(observations, run))
    return spans


def _label(observations: Sequence[FbiObservation], run: Sequence[int]) -> str:
    first, last = observations[run[0]].period, observations[run[-1]].period
    return first if first == last else f"{first}..{last}"


class _Filings(NamedTuple):
    """One series read as filings rather than as values.

    ``observations``
        The series with every detected non-reporting period nulled.
    ``interior`` / ``trailing``
        The spans that were nulled, split by where they sit: a gap inside or
        before the filings, against a window that runs to or past the last
        return. They read differently and are worth separate sentences.
    ``inside`` / ``after``
        The periods behind those spans, so a notice can count them.
    ``beyond``
        The periods in ``after`` that are past ``max_data_date``, where the CDE
        genuinely is padding a window past the data it holds.
    ``kept_tail``
        A trailing blank run the mass test left alone, with the level it was
        judged against: the run is too small to be a missing return and the
        periods keep the value the CDE sent.
    ``closed_early``
        True where *vintage* decided the trailing run rather than *open_tail*:
        the window's own last period is before ``max_data_date``, so the data
        carries on past the window and the CDE cannot have been padding. That is
        the one case in which a kept trailing run is worth a sentence, and it is
        why ``kept_tail`` is carried at all.
    ``periodic``
        The runs read as a filing schedule rather than as missing returns. Their
        blanks keep the value the CDE sent.
    ``lumps``
        Filings too large to be one period, with no blank run to explain them.
        Reported, never altered.
    ``partial``
        The last period, where it carries a filing too small to be a whole one,
        with the level it was judged against.
    """

    observations: List[FbiObservation]
    start: Optional[str]
    end: Optional[str]
    interior: List[str]
    trailing: List[str]
    inside: List[str]
    after: List[str]
    partial: Optional[tuple[FbiObservation, float]]
    beyond: List[str]
    kept_tail: Optional[tuple[str, float, int]]
    periodic: List[tuple[_Period, str, FbiObservation]]
    lumps: List[tuple[FbiObservation, float]]
    closed_early: bool = False

    @property
    def periods(self) -> List[str]:
        """Every period that was nulled, in order."""
        return [*self.inside, *self.after]

    @property
    def anything(self) -> bool:
        """True where the reading has something to say about the series."""
        return bool(self.interior or self.trailing or self.periodic or self.lumps
                    or (self.closed_early and self.kept_tail))


def _read_filings(observations: Iterable[FbiObservation], *,
                  open_tail: bool = True,
                  filed: Iterable[int] = (),
                  vintage: Optional[str] = None,
                  periodic: bool = False) -> _Filings:
    """Separate a series' filings from the periods it was merely padded with.

    **Nulled, not flagged.** A detected non-reporting period comes back with
    ``value=None``. The alternative -- leave the zero and mention it in
    ``notices`` -- is the failure this exists to stop: a caller that sums or
    averages without reading prose gets a plausible, wrong, silent answer, and
    that is exactly how Washington's arrests came to advertise 501 of 501
    months filled across twenty-five years in which the department filed
    nothing. Nulling makes the same caller either drop the period or raise on
    it, and it is the spelling the model already documents for this fact
    (``FbiObservation.value``: "None where the agency or scope did not
    report"), which is what the CDE itself uses for half the scopes.

    A period that survives keeps its value, zero included: a genuine zero is a
    filing and belongs in the span.

    *periodic* turns on :func:`_periodic`, and with it the one case where
    nulling makes a caller's arithmetic worse rather than better. An agency
    filing quarterly or annually sends the blanks *and* a month carrying the
    whole period; nulling the blanks and keeping the lump as one month's value
    makes a monthly mean three or twelve times too high, where before the rule a
    sum or a mean over whole periods was right. So a recognised schedule's blanks
    are handed to :func:`_unfiled` as accounted for and come back exactly as the
    CDE sent them -- 0 in every span seen -- and the notice names the span and
    says what a month inside it does not mean. Nothing is spread across the
    blanks: the CDE does not publish the split, and inventing one would be worse
    than either. Monthly only: a quarter is not a thing an annual series has, so
    ``pe`` leaves this off.

    *vintage* is ``max_data_date``, and it splits the trailing blank run into
    the three different things it can be. Periods **past** the vintage are the
    CDE padding a window past the data it holds, and are nulled whatever their
    length. A run that **reaches** the vintage is the same case seen from
    inside: the returns for the month the data stops in are still arriving, so a
    blank there cannot be told from a period with nothing in it, and it is nulled
    too. A run that ends **before** the vintage is none of that -- the data
    continues past the window, the CDE padded nothing, and the window simply
    ended there -- so it is judged by its mass like any run inside the series,
    with the level taken from the filings to its left. That last case is why
    ``vintage`` exists: San Francisco's homicide clearances for 12-2007, at the
    end of a window ending 12-2007 under a vintage of 09/2026, are a filed zero
    at a department clearing three a month, and were being deleted with a notice
    saying the CDE had padded past its data. Without *vintage* the trailing run
    is taken as *open_tail* says, which is what the arrest route wants.

    *filed* is :func:`_unfiled`'s: the positions whose blank is a value already
    accounted for -- a rate the CDE published as -1 -- rather than a period
    nobody filed. They come back null, as they arrived here, but no notice
    claims them.
    """
    observations = list(observations)
    values = [o.value for o in observations]
    levels = _levels(values)
    spared = set(filed)
    schedule = _periodic(values, levels, spared) if periodic else []
    lumped = _lumps(values, schedule) if periodic else []
    spared.update(index for period in schedule for index in period.blanks)

    cutoff = _month_key(vintage or "")
    tail = next((run for run in _runs(values, spared) if run[1] == len(values)), None)
    closed_early = False
    if cutoff is not None and tail is not None and tail[0] > 0:
        # The window's own last period decides: at or past the vintage the data
        # stops inside the run, before it the data carries on past the window.
        last_key = _month_key(observations[-1].period)
        open_tail = last_key is None or last_key >= cutoff
        closed_early = not open_tail

    holes = _unfiled(values, levels, open_tail=open_tail, filed=spared)
    hidden = set(holes)
    cleaned = [FbiObservation(period=o.period, value=None) if i in hidden else o
               for i, o in enumerate(observations)]

    last = len(cleaned) - 1
    partial: Optional[tuple[FbiObservation, float]] = None
    if cleaned and last not in hidden and cleaned[last].value is not None:
        level = levels[last]
        if level >= PARTIAL_FLOOR and cleaned[last].value < PARTIAL_SHARE * level:
            partial = (cleaned[last], level)

    # The run that reaches the end of the window, if there is one, told apart
    # from the gaps inside the series: "the data stops here" and "the agency
    # skipped these" are different sentences.
    after: List[int] = []
    while last - len(after) in hidden and last - len(after) >= 0:
        after.append(last - len(after))
    after.reverse()

    # And the trailing run the mass test kept, which is a third sentence again:
    # the periods are filed zeros as far as the surrounding filings can say.
    kept_tail: Optional[tuple[str, float, int]] = None
    if tail is not None and not hidden & set(range(*tail)):
        kept_tail = (_label(observations, range(*tail)),
                     _median(levels[tail[0]:tail[1]]), tail[1] - tail[0])

    inside = [i for i in holes if i not in set(after)]
    start, end = _span(cleaned)
    beyond = [i for i in after
              if cutoff is not None and (key := _month_key(observations[i].period))
              is not None and key > cutoff]
    return _Filings(
        observations=cleaned, start=start, end=end,
        interior=_spans(observations, inside),
        trailing=_spans(observations, after),
        inside=[observations[i].period for i in inside],
        after=[observations[i].period for i in after],
        beyond=[observations[i].period for i in beyond],
        kept_tail=kept_tail,
        periodic=[(period, _label(observations, period.blanks),
                   observations[period.closer]) for period in schedule],
        lumps=[(observations[i], _level_around(values, i, {p.closer for p in schedule})
                or 0.0) for i in lumped],
        partial=partial,
        closed_early=closed_early,
    )


def _crosses_nibrs(observations: Iterable[FbiObservation]) -> bool:
    """True when the series has values on both sides of the 2021 changeover."""
    years = {y for o in _filled(observations) if (y := _year(o.period)) is not None}
    return any(y < 2021 for y in years) and any(y >= 2021 for y in years)


def _context(series: Iterable[FbiSeries], unit: str, geography: str, *,
             exact: bool = False) -> Optional[FbiContextSeries]:
    """The context series for this geography, or the narrowest one on offer.

    An exact label match is preferred; failing that the first candidate is
    returned with its own label attached, so a state's coverage standing in for
    an agency's is visible rather than silent.

    *exact* refuses the stand-in. That is for evidence rather than display:
    a state's participation says nothing about whether one of its agencies
    reported, so a test of the agency must not be answered by it.
    """
    candidates = [s for s in series if s.unit == unit]
    matched = next((s for s in candidates if s.label == geography), None)
    chosen = matched if matched is not None or exact else next(iter(candidates), None)
    if chosen is None:
        return None
    return FbiContextSeries(
        label=chosen.label, unit=chosen.unit or unit,
        observations=list(chosen.observations),
    )


def _listed(spans: Sequence[str], limit: int = 8) -> str:
    """Spans as prose, capped like the employment gap notice's year list."""
    return ", ".join(spans[:limit]) + (", ..." if len(spans) > limit else "")


def _spelling(periods: Sequence[str], from_null: Iterable[str]) -> str:
    """How the CDE spelled a run the rule nulled, for the sentence that says why.

    A single offence's nulls reach the rule as zeros only because the mapper
    read them as zero-arrest months first; a zero the CDE sent is its padding
    for a missing return. The sentence says which of the two the run was, so
    a run of zeros the CDE sent is not explained as nulls read as zero.
    """
    nulls = len(set(periods) & set(from_null))
    if not nulls:
        return ("The CDE spells a missing return as 0 rather than as null, so a run "
                "of them sums and averages as real months")
    if nulls == len(periods):
        return ("They came back null, which for a single offence is read as a month "
                "with no arrest where the scope's participated population is above "
                "zero, so a missing return spelled that way would sum and average as "
                "real months")
    return (f"{nulls} of them came back null, read as a month with no arrest for a "
            f"single offence where the scope's participated population is above "
            f"zero, and the rest as 0, the CDE's padding for a missing return; "
            f"either way a run of them sums and averages as real months")


#: What a periodic return's length is called, for the notice that names it.
#: Only the lengths :data:`PERIOD_LENGTHS` admits; nothing else is recognised.
SCHEDULES: dict[int, tuple[str, str]] = {
    3: ("quarterly", "quarter"), 6: ("semiannual", "half-year"), 12: ("annual", "year"),
}


def _periodic_notices(filings: _Filings, counted: str) -> List[str]:
    """One sentence per schedule: what the span is, and what a month in it is not.

    Monthly routes only, and only for the spans :func:`_periodic` recognised.
    The blanks keep the value the CDE sent, so the arithmetic a caller does
    without reading this is right over whole periods and wrong over anything
    else, and that is what the sentence has to say. The caveat is stated
    because the payload cannot settle it: a quarterly filer and a scope that
    only ever filed in March, June, September and December arrive identical.
    """
    notices: List[str] = []
    for months, (adverb, name) in SCHEDULES.items():
        spans = [(period, label, closer) for period, label, closer in filings.periodic
                 if period.months == months]
        if not spans:
            continue
        count = len(spans)
        examples = [f"{label} closed by {closer.period} "
                    f"({closer.value or 0:,.0f}{counted} against "
                    f"{period.months * period.level:,.0f} for {period.months} months)"
                    for period, label, closer in spans]
        article = "an" if adverb[0] in "aeiou" else "a"
        guessed = [period for period, _, _ in spans if not period.measured]
        measured = (
            f"The level {len(guessed)} of them {'was' if len(guessed) == 1 else 'were'} "
            f"measured against is the span's own figure spread over its months, because "
            f"the {LEVEL_SPAN} months around it hold fewer than {ORDINARY_MIN} ordinary "
            f"filings to compare with -- a series that is {adverb} throughout a stretch "
            f"has no monthly filing anywhere near it -- so there the shape is what "
            f"decides. " if guessed else "")
        notices.append(
            f"{count} {adverb} return{'' if count == 1 else 's'} in this window: a run "
            f"of {months - 1} blank month{'' if months == 2 else 's'} closed by a filing "
            f"carrying the whole {name} ({_listed(examples, limit=4)}). {measured}"
            f"This is a filing schedule rather than a missing return, so the blanks are "
            f"returned as the CDE sent them -- 0 in every span seen -- and the closing "
            f"month keeps the whole {name}: a sum or a mean over WHOLE {name}s is right "
            f"as it stands, where nulling the blanks would leave a monthly mean about "
            f"{months} times too high. A single month inside a span is NOT a monthly "
            f"figure: a 0 there says no return arrived for that month by itself, not "
            f"that nothing happened in it, and the closing month is the {name}'s total "
            f"and not that month's. Nothing is spread across the blanks -- the CDE does "
            f"not publish the split, and inventing one would be worse than either "
            f"spelling. What this cannot tell apart: {article} {adverb} filer from a scope "
            f"that "
            f"only ever filed in those closing months. The payload carries the same "
            f"months either way."
        )
    return notices


def _lump_notice(filings: _Filings, counted: str) -> List[str]:
    """Filings too large to be one month, with no blank run to explain them.

    Reported and never altered: the payload does not say which months the
    figure covers, so there is nothing to null and nothing to spread. Monthly
    routes only, and only where the neighbourhood holds enough ordinary filings
    to say what a month normally carries.
    """
    if not filings.lumps:
        return []
    count = len(filings.lumps)
    examples = [f"{observation.period} holds {observation.value or 0:,.0f}{counted} "
                f"against a normal {level:,.0f} nearby"
                for observation, level in filings.lumps]
    return [
        f"{count} month{'' if count == 1 else 's'} here carr{'ies' if count == 1 else 'y'} "
        f"{LUMP_SHARE:,.0f} times or more what a month nearby carries, with no blank run "
        f"in front of {'it' if count == 1 else 'them'} to explain "
        f"{'it' if count == 1 else 'them'} ({_listed(examples, limit=4)}). A filing that "
        f"size carries more than one month -- a reconciliation, or a whole period filed "
        f"at once while the other months were part-filed -- but the payload does not say "
        f"which months it covers, so it is returned exactly as the CDE sent it: nothing "
        f"is nulled, nothing is spread, and the months around it are not necessarily the "
        f"quiet months they look like. A mean over a window holding one of these counts "
        f"a period as a month."
    ]


def _kept_tail_notice(filings: _Filings, vintage: Optional[str], counted: str, *,
                      agency: bool) -> List[str]:
    """A trailing blank run the mass test kept, where the vintage said it could.

    Only for a window that ends before ``max_data_date``: the data carries on
    past the window, so the CDE padded nothing and the run is judged like any
    run inside the series. Three things are different and the sentence keeps
    them apart -- padding past the vintage, a run reaching the vintage, and a
    window that simply ended on a quiet stretch. What cannot be told apart is
    said rather than solved.
    """
    if not (filings.closed_early and filings.kept_tail):
        return []
    label, level, count = filings.kept_tail
    ambiguity = (
        "AT AGENCY SCOPE this cannot be told apart from a department that stopped "
        "filing at the end of the window: the coverage the payload carries is its "
        "STATE's, an agency's participated population carries on after it stops "
        "filing, and max_data_date is the national vintage rather than the agency's "
        "last return. Widen the window past these months to see which it is."
        if agency else
        "At national and state scope the participated population is summed over the "
        "agencies that reported, so a quiet run under one is quiet."
    )
    return [
        f"The last {count} month{'' if count == 1 else 's'} of this window ({label}) "
        f"{'is' if count == 1 else 'are'} blank and {'is' if count == 1 else 'are'} "
        f"returned as the CDE sent {'it' if count == 1 else 'them'}: the window ends "
        f"before max_data_date ({vintage}), where the UCR data stops, so the data "
        f"carries on past the window and the CDE padded nothing. Judged like any run "
        f"inside the series -- against a normal {level:,.0f}{counted} for this stretch, "
        f"from the filings to its left -- the run is too small to be a missing return, "
        f"so {'it is a filed zero' if count == 1 else 'they are filed zeros'} as far as "
        f"the surrounding filings can say. {ambiguity}"
    ]


def _judged_on_counts_notice(unit: str, counted: str) -> List[str]:
    """Why a rate's nulls are the count's nulls, on the routes that do that.

    Stated only where the reading had something to report, and only for a rate:
    a clean series needs no sentence, and a payload carrying no count series for
    the label -- which no live payload has been seen to do -- is judged on what
    it has and says nothing it cannot support.

    The floor the rule turns on is in filings, so a rate judged in its own units
    disagrees with its own count: one saved payload's offence counts and offence
    rates came back as two different answers to which months exist, 96 months
    apart, from a single request.
    """
    if unit != UNITS["rate"]:
        return []
    return [
        f"This is the rate series, and whether a month records a filing is decided on "
        f"the COUNT of{counted} for the same geography, measure and month, then applied "
        f"here: a month is filed or not, which is a fact about the return rather than "
        f"about the unit it is read in. The floor that separates a missing return from a "
        f"quiet month is in{counted} ({UNFILED_RUN_FLOOR:,.0f} of them), so judged in "
        f"its own units a rate of 0.3 per 100,000 passes as a quiet stretch where the "
        f"count behind it is a missing return, and one request would answer two ways. "
        f"The months named above are named from the counts; the count and the rate come "
        f"back null in exactly the same months."
    ]


def _filing_notices(filings: _Filings, total: int, *,
                    tail_already_flagged: bool = False,
                    from_null: Iterable[str] = (),
                    counted: str = "",
                    unit: str = "",
                    judged_on_counts: bool = False,
                    vintage: Optional[str] = None,
                    agency: bool = False) -> List[str]:
    """What the filing analysis has to say about a monthly series.

    Separate facts get separate sentences rather than one compound one: months
    nobody filed, a window that outruns the data, a trailing blank run the
    vintage says is not padding, a filing schedule, a filing too large to be one
    month, and a last month that arrived incomplete. Employment phrases its own,
    because the annual response already has a notice for a year with no return
    and the zeros belong in it rather than beside it.

    *from_null* is the periods a single offence's reading turned from null
    into 0, so a run the rule nulled is described as the CDE actually spelled
    it. *counted* names in prose what the figures quoted here are counts of, and
    *unit* is the unit being returned; with *judged_on_counts* -- the series was
    read on its own counts and the verdict applied to the unit asked for -- they
    decide whether the response has to say that the count and the rate were read
    as one series. *agency* is scope, for the one sentence whose answer depends
    on it: an agency's trailing blank run cannot be told from an agency that
    stopped filing, and a national one can.
    """
    from_null = set(from_null)
    notices: List[str] = []
    if filings.interior:
        notices.append(
            f"{len(filings.inside)} of the {total} month"
            f"{'' if total == 1 else 's'} in this window record no filing: "
            f"{_listed(filings.interior)}. {_spelling(filings.inside, from_null)} — "
            f"and the run here swallows more than the surrounding filings say any "
            f"quiet stretch could. They are returned as null instead, and "
            f"observation_start/observation_end name the filings rather than the "
            f"requested window."
        )
    if filings.trailing:
        count = len(filings.after)
        nulls = len(set(filings.after) & from_null)
        padding = ("with 0 rather than with null" if not nulls else
                   "with null, which a single offence's reading took for a month "
                   "with no arrest" if nulls == count else
                   "with 0 and with null, a null read as a month with no arrest for "
                   "a single offence")
        # Whether the run is the CDE padding a window it could not fill is a
        # question about the vintage, not about the run: padding starts after
        # max_data_date. Asked here rather than in _read_filings because the
        # routes pass their own open_tail and only some of them pass a vintage,
        # and the answer must not change which months are nulled.
        cutoff = _month_key(vintage or "")
        opens = _month_key(filings.after[0]) if filings.after else None
        padding_run = cutoff is None or opens is None or opens > cutoff
        if not padding_run:
            # The window ends before the data does, so nothing here is padding:
            # the CDE has months behind the window it was not asked for. Saying
            # "max_data_date is where the UCR data actually stops" of a run like
            # this was the defect -- a window ending on San Francisco's zero
            # clearance months blamed the programme's vintage for a run that sits
            # in the middle of the series.
            notices.append(
                f"The last {count} month{'' if count == 1 else 's'} of this window "
                f"({_listed(filings.trailing)}) record no filing. "
                f"{_spelling(filings.after, from_null)} — and the run is larger than "
                f"the filings to its left say a quiet stretch could be, so "
                f"{'it is' if count == 1 else 'they are'} returned as null and "
                f"observation_end is the last month with a return behind it. This is "
                f"not the CDE padding a window it could not fill: the window ends "
                f"before max_data_date ({vintage}), where the UCR data stops, so the "
                f"series carries on past the end you asked for. Widen the window to "
                f"see whether the filings resume."
                + (" AT AGENCY SCOPE nothing here can say whether the department "
                   "stopped filing or the window merely ended on a quiet stretch: the "
                   "coverage the payload carries is its STATE's, and max_data_date is "
                   "the national vintage rather than this agency's last return."
                   if agency else "")
            )
        else:
            notices.append(
                f"The window runs {count} month{'' if count == 1 else 's'} past the "
                f"last filing ({_listed(filings.trailing)}): the CDE pads to the "
                f"requested end {padding}, and max_data_date is where "
                f"the UCR data actually stops. Those months are returned as null, so "
                f"observation_end is the last month with a return behind it."
            )
    notices.extend(_kept_tail_notice(filings, vintage, counted, agency=agency))
    notices.extend(_periodic_notices(filings, counted))
    notices.extend(_lump_notice(filings, counted))
    if filings.partial and not tail_already_flagged:
        observation, level = filings.partial
        notices.append(
            f"{observation.period} carries {observation.value:,.0f}{counted} against a "
            f"normal {level:,.0f} for this stretch: the last month of the window is still "
            f"filling, so it undercounts — drop it before comparing. Coverage will "
            f"not show this at agency scope, where the percentage published is the "
            f"state's and not the agency's."
        )
    if filings.anything and judged_on_counts:
        notices.extend(_judged_on_counts_notice(unit, counted))
    return notices


class _Qualified(NamedTuple):
    """The population, the coverage and the advisories a series comes with."""

    geography: str
    population: Optional[FbiContextSeries]
    participated: Optional[FbiContextSeries]
    coverage: Optional[FbiContextSeries]
    mean_percent: Optional[float]
    min_percent: Optional[float]
    min_period: Optional[str]
    notices: List[str]
    tail_flagged: bool


def _qualify(series: Iterable[FbiSeries], chosen: FbiSeries,
             observations: Optional[Sequence[FbiObservation]] = None) -> _Qualified:
    """Attach the coverage and population that make one series readable.

    Shared by offences and arrests: both come out of the same payload family,
    and the three things that make a figure misleading -- the 2021 splice, a
    coverage collapse, a wider geography's context standing in for the
    requested one -- are the same in both.

    *observations* is the series read as filings, where that has already been
    done: the 2021 test asks whether there are values on both sides of the
    break, and a scope that filed nothing after it has none, however many zeros
    the payload padded the years with.
    """
    series = list(series)
    geography = _geography(chosen.label)
    coverage = _context(series, "percent", geography)
    population = _context(series, "people", geography)
    participated = _context(series, PARTICIPATED, geography)
    covered = _filled(coverage.observations) if coverage else []
    worst = min(covered, key=lambda o: o.value) if covered else None
    tail_flagged = False

    notices: List[str] = []
    if _crosses_nibrs(chosen.observations if observations is None else observations):
        notices.append(_NIBRS_NOTICE)
    if worst is not None and worst.value < COVERAGE_FLOOR:
        # The worst month is either 2021 or the end of the window, and they
        # mean different things: one is a reporting break, the other a month
        # that has not finished arriving.
        tail = worst.period == covered[-1].period
        tail_flagged = tail
        notices.append(
            f"Coverage bottoms out at {worst.value}% in {worst.period}: "
            + ("the last month of the window is still filling, so it undercounts "
               "-- drop it before comparing."
               if tail else
               "that month's figure counts what was reported, not what happened.")
        )
    stood_in = sorted({c.label for c in (coverage, population, participated)
                       if c is not None and c.label != geography})
    if stood_in:
        notices.append(
            f"Coverage or population is labelled {', '.join(stood_in)} rather than "
            f"{geography}: the payload carries none for the requested geography "
            f"itself, so the context is the wider one it does carry."
        )
    return _Qualified(
        geography=geography, population=population, participated=participated,
        coverage=coverage,
        mean_percent=(round(sum(o.value for o in covered) / len(covered), 2)
                      if covered else None),
        min_percent=worst.value if worst else None,
        min_period=worst.period if worst else None,
        notices=notices, tail_flagged=tail_flagged,
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


def _denominator(participated: Optional[FbiContextSeries],
                 periods: Sequence[str]) -> str:
    """What the scope's own participated population is in these periods.

    The clause that keeps :func:`_defined`'s notice to what the response
    carries. A payload with no participated population of the scope's own says
    so rather than guessing, since a wider geography's denominator is not this
    series' denominator.
    """
    if participated is None:
        return ("the payload carries no participated population for this geography "
                "itself, so the denominator behind the value cannot be checked here")
    reach = {o.period: o.value for o in participated.observations}
    values = [reach.get(period) for period in periods]
    if len(values) == 1:
        if values[0] is None:
            return (f"the payload carries no participated population for "
                    f"{participated.label} for that month, so the denominator behind "
                    f"the value cannot be checked")
        return (f"the participated population for {participated.label} that "
                f"month is {values[0]:,.0f}")
    peopled = sum(1 for v in values if v is not None and v > 0)
    missing = sum(1 for v in values if v is None)
    counted = [(what, many) for what, many in (("above zero", peopled),
                                              ("0", len(values) - peopled - missing),
                                              ("missing", missing)) if many]
    stands = (f"{counted[0][0]} in all {len(values)} months" if len(counted) == 1 else
              f"{', '.join(f'{what} in {many}' for what, many in counted)} of the "
              f"{len(values)} months")
    return f"the participated population for {participated.label} is {stands}"


def _defined(chosen: FbiSeries, participated: Optional[FbiContextSeries] = None,
             ) -> tuple[FbiSeries, List[str], List[int]]:
    """The series with its impossible rates nulled, and the notice saying so.

    Where the participated population is 0 the CDE publishes a rate of -1 --
    the Metro Transit Police (DCMTP0000), which has no resident population of
    its own, carries -1 in all 48 months of 2021-2024 beside up to 35 robbery
    arrests a month. A rate over nobody is undefined, and a -1 left in place
    sums to -48 and averages below zero, so it is nulled like any other value
    with nothing behind it. Counts are never touched: only a rate can be
    negative, and only a rate has the denominator that makes it so.

    **The notice says only what this response shows.** The -1-over-nobody
    account is asserted where the payload bears it out -- every negative value
    is exactly -1, and *participated*, the scope's own participated population,
    is 0 in every one of those months. Where it does not, the notice reports
    the value and the denominator it actually found and leaves -1 as the one
    cause this source is known to have: a rate of -2.5 over 330 million
    participants is not a transit force, and was told it was, on the offence
    route as well, where no -1 has been seen at all.

    The positions nulled come back with the series. They are blanks the payload
    accounts for, so :func:`_read_filings` is told to leave them alone rather
    than report them a second time as months nobody filed -- which it cannot
    tell them apart from, since both arrive as null.
    """
    if chosen.unit != UNITS["rate"]:
        return chosen, [], []
    negative = [i for i, o in enumerate(chosen.observations)
                if o.value is not None and o.value < 0]
    if not negative:
        return chosen, [], []
    hidden = set(negative)
    cleaned = chosen.model_copy(update={"observations": [
        FbiObservation(period=o.period, value=None) if i in hidden else o
        for i, o in enumerate(chosen.observations)]})
    months = [chosen.observations[i] for i in negative]
    count = len(months)
    periods = [o.period for o in months]
    marker = all(o.value == -1 for o in months)
    reach = ({o.period: o.value for o in participated.observations}
             if participated is not None else {})
    empty = participated is not None and all(reach.get(p) == 0 for p in periods)
    established = marker and empty
    if established:
        why = (f"the CDE publishes -1 where the participated population is 0, and "
               f"the participated population carried for {participated.label} is 0 in "
               f"{'that month' if count == 1 else 'every one of those months'} — as it "
               f"is in every month at an agency with no resident population of its "
               f"own, such as a transit or campus force")
    else:
        why = (("-1 is what the CDE publishes where the participated population is 0 — "
                "as it is in every month at an agency with no resident population of "
                "its own, such as a transit or campus force — but that is not "
                "established here: "
                if marker else
                f"the only negative rate this source is known to publish is the -1 it "
                f"puts where the participated population is 0, and "
                f"{'this is' if count == 1 else 'these are'} not -1: ")
               + _denominator(participated, periods))
    return cleaned, [
        f"{count} month{'' if count == 1 else 's'} carr{'ies' if count == 1 else 'y'} "
        f"a negative rate ({_listed(_spans(chosen.observations, negative))}): {why}. "
        f"{'A rate over nobody is undefined' if established else 'A rate below zero '
           'is impossible either way'}, so "
        f"{'it is' if count == 1 else 'they are'} returned as null; the counts are "
        f"unaffected."
    ], negative


#: What the figures a notice quotes are counts of, in prose, per measure. The
#: rule is applied to counts on both measures, so a notice built for a rate
#: series quotes a number in a different unit from the one returned and has to
#: say which.
COUNTED: dict[str, str] = {"offenses": " offences", "clearances": " clearances"}


def from_offense_response(
    payload: Any, *, offense: str, scope: str, measure: str = "offenses",
    unit: str = "count",
) -> FbiOffenseSeries:
    """Select one series out of the four a CDE offence payload carries.

    *unit* is the tool's word ('count' or 'rate'), mapped to the client's own
    unit strings by :data:`UNITS`.

    **The verdict is the count's, on both measures.** A month is filed or not,
    which is a fact about the return and not about the unit it is read in, so the
    non-reporting rule runs on the count series for the same label and measure
    and what it nulls is nulled in the rate as well. Judged in its own units a
    rate meets a floor of 25 that means filings: on one saved payload New York's
    homicide offence counts came back with 101 months nulled and the rates for
    the same months with 5, one request answering twice, and at a scope whose
    monthly rate runs above 25 the error is the other way -- genuine filed zero
    months deleted from the rate that the count keeps. Offences and clearances
    are still judged separately, on their own counts: a department can file its
    offences and not its clearances, as New York did from 2002 to 2012.

    **The trailing blank run is judged against the vintage** (see
    :func:`_read_filings`): past ``max_data_date`` or reaching it, the CDE is
    padding a window past the data it holds and the months are nulled; ending
    before it, the data carries on past the window, the CDE padded nothing, and
    the run is held to the mass test like any run inside the series. San
    Francisco's homicide clearances for 12-2007, at the end of a window ending
    there, are a filed zero at a department clearing three a month.

    **Periodic returns are recognised and left alone** (:func:`_periodic`): an
    agency filing quarterly or annually sends the blanks *and* a month carrying
    the whole period, so nulling the blanks would leave a monthly mean three or
    twelve times too high. Their months come back as the CDE sent them and the
    notice says what a month inside one does not mean.
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

    vintage = getattr(payload, "max_data_date", None)
    chosen, undefined, published = _defined(
        chosen, _context(series, PARTICIPATED, _geography(chosen.label), exact=True))
    # Judged on the counts for this label and measure, which the same payload
    # always carries; a payload without one is judged on what it has.
    counts = next((s for s in series
                   if s.measure == chosen.measure and s.unit == UNITS["count"]
                   and s.label == chosen.label), chosen)
    # The months whose rate the CDE published as -1: the scope filed them, so
    # the rule is told not to report them a second time as returns nobody sent.
    negative = {chosen.observations[i].period for i in published}
    filings = _read_filings(
        counts.observations, vintage=vintage, periodic=True,
        filed=[i for i, o in enumerate(counts.observations) if o.period in negative])
    if counts is chosen:
        observations = filings.observations
    else:
        dropped = set(filings.periods)
        observations = [FbiObservation(period=o.period, value=None)
                        if o.period in dropped else o for o in chosen.observations]
    start, end = _span(observations)
    context = _qualify(series, chosen, observations)
    return FbiOffenseSeries(
        offense=offense, scope=scope, geography=context.geography,
        measure=chosen.measure, unit=resolved,
        observation_start=start, observation_end=end,
        observations=observations,
        population=context.population,
        participated_population=context.participated,
        coverage=context.coverage,
        coverage_mean_percent=context.mean_percent,
        coverage_min_percent=context.min_percent,
        coverage_min_period=context.min_period,
        max_data_date=vintage,
        last_refresh_date=getattr(payload, "last_refresh_date", None),
        notices=[*context.notices, *undefined,
                 *_filing_notices(filings, len(observations),
                                  tail_already_flagged=context.tail_flagged,
                                  counted=COUNTED.get(chosen.measure, ""),
                                  unit=resolved, judged_on_counts=counts is not chosen,
                                  vintage=vintage, agency=_is_agency(scope))],
    )


def _month_key(period: str) -> Optional[tuple[int, int]]:
    """``(year, month)`` for ``'MM-YYYY'`` or the vintage's ``'MM/YYYY'``."""
    month, _, year = period.replace("/", "-").partition("-")
    if month.isdigit() and year.isdigit() and len(year) == 4:
        return int(year), int(month)
    return None


def _is_agency(scope: str) -> bool:
    """An ORI rather than 'national' or a state, by the client's own routing."""
    return FbiClient.route(scope)[0].startswith("agency/")


def _arrest_code(offense: Any, payload: Any) -> str:
    """The UCR code the mapper works under, normalised as the client does it.

    The tool's ``enum`` only admits codes, but a direct call can pass ``'ALL'``
    or a name, and a raw ``'ALL'`` would take the single-offence path and have
    the total's nulls read as zero arrests. A value the client would refuse is
    kept as given rather than raised on, because the mapper is total.

    **The payload's own ``offense`` is normalised the same way**, not just the
    argument. The client writes that field normalised, so nothing it returns
    needs it -- but a hand-built response does not have to, and where the
    argument is omitted the field is the code the mapper works under. Normalised
    on one path only, an ``'ALL'`` on the response took the single-offence path
    and had the total's nulls read as zero arrests, which is the failure this
    function exists to prevent.
    """
    if offense is None:
        offense = getattr(payload, "offense", None)
        if not offense:
            return "all"
    try:
        return arrest_offense(offense)
    except FbiAPIError:
        return str(offense)


class _OneOffence(NamedTuple):
    """A single offence's arrests with their nulls read.

    ``observations``
        The months left for the non-reporting rule, in order, a null read as 0.
    ``kept``
        Where each of those sits in the requested window.
    ``unreported`` / ``undecided`` / ``beyond``
        The positions that stay null before the rule runs: nulls in months the
        scope has no participated population for; nulls with nothing in the
        payload that can say whether the scope reported; and blanks past
        ``max_data_date``.
    ``zeroed``
        The periods whose null was read as 0. The rule can still null them.
    ``gate``
        The scope's own context series that said whether it reported, if any.
    """

    observations: List[FbiObservation]
    kept: List[int]
    unreported: List[int]
    undecided: List[int]
    beyond: List[int]
    zeroed: List[str]
    gate: Optional[FbiContextSeries]

    @property
    def dropped(self) -> List[int]:
        """Every position that stays null whatever the rule says."""
        return sorted([*self.unreported, *self.undecided, *self.beyond])


def _one_offence(observations: Sequence[FbiObservation], series: Sequence[FbiSeries],
                 geography: str, max_data_date: Optional[str], *,
                 agency: bool = False) -> _OneOffence:
    """Read a single offence's nulls as the zero-arrest months they are nationally.

    Nationally the CDE has no row for a month without an arrest for one
    offence, and spells it null: gambling-numbers arrests (code 172) come back
    null in 21 of the 24 months of 2023-2024, and 3 + 1 + 1 in the other three
    is exactly the 5 the FBI's 2023 totals give that code. Read as missing
    returns, those months cost the series its span and invent a "data stops"
    notice two years before the data does. At agency scope the spelling has
    not been seen: a month with no murder arrest at a department that filed
    comes back 0, and the only nulls are months with no participated
    population at all.

    A null is read as 0 only where the payload says the scope reported: the
    month is not past ``max_data_date``, and the scope's *own* participated
    population -- its coverage where the payload has none -- is above zero
    that month. Only the scope's own: a state's participation says nothing
    about one of its agencies, so a wider geography's series is never asked.
    A null with no participated population behind it stays null (Los Angeles'
    and San Francisco's twelve null months of ``all`` are exactly the twelve
    with none), and so does one the payload cannot decide -- no series of the
    scope's own, or, at an *agency*, a participated population of 0, which a
    transit or campus force with no residents of its own has in every month it
    files.

    A value the CDE sent is kept as it came, zero included -- including a zero
    in a month whose participated population is 0: the Metro Transit Police
    filed 0 robbery arrests in 04-2021 among 4 to 35 a month, and that zero is
    theirs. Zeros are the rule's to judge, as for ``all``. So is an agency that
    stopped filing while its participated population carried on --
    Washington's twenty-five years of zeros for ``all`` sit under a population
    in every month.
    """
    gate = (_context(series, PARTICIPATED, geography, exact=True)
            or _context(series, "percent", geography, exact=True))
    reach = {o.period: o.value for o in gate.observations} if gate else {}
    cutoff = _month_key(max_data_date or "")
    kept: List[int] = []
    unreported: List[int] = []
    undecided: List[int] = []
    beyond: List[int] = []
    zeroed: List[str] = []
    out: List[FbiObservation] = []
    for index, observation in enumerate(observations):
        month = _month_key(observation.period)
        if (not observation.value and cutoff is not None and month is not None
                and month > cutoff):                # blank, and past the data
            beyond.append(index)
            continue
        if observation.value is not None:           # as the CDE sent it, zero included
            kept.append(index)
            out.append(observation)
            continue
        participated = reach.get(observation.period)
        if participated is not None and participated > 0:
            kept.append(index)
            zeroed.append(observation.period)
            out.append(FbiObservation(period=observation.period, value=0.0))
        elif gate is not None and (participated is None or not agency):
            unreported.append(index)
        else:
            undecided.append(index)
    return _OneOffence(observations=out, kept=kept, unreported=unreported,
                       undecided=undecided, beyond=beyond, zeroed=zeroed, gate=gate)


def _one_offence_notices(one: _OneOffence, observations: Sequence[FbiObservation],
                         geography: str, max_data_date: Optional[str], *,
                         zeroed: Sequence[str]) -> List[str]:
    """What reading a single offence's nulls did, in a sentence per kind.

    *zeroed* is the nulls that are returned as 0: the ones read as zero
    arrests that the non-reporting rule then left alone. A null the rule went
    on to null is its notice's business, not this one's.
    """
    total = len(observations)
    notices: List[str] = []
    what = ("participated population" if one.gate is not None
            and one.gate.unit == PARTICIPATED else "coverage")
    label = one.gate.label if one.gate is not None else geography
    if zeroed:
        notices.append(
            f"Nationally the CDE spells a month with no arrest for a single offence "
            f"as null, not 0 (at agency scope it has sent 0): {len(zeroed)} of the "
            f"{total} month{'' if total == 1 else 's'} here came back null in months "
            f"{label} reported (its {what} is above zero in each), and are returned "
            f"as 0 arrests — which is how the FBI's own annual totals count them "
            f"(checked nationally for 2023)."
        )
    if one.unreported:
        count = len(one.unreported)
        notices.append(
            f"{count} month{' has' if count == 1 else 's have'} no {what} for "
            f"{label} ({_listed(_spans(observations, one.unreported))}): nobody "
            f"reported, so {'it is' if count == 1 else 'they are'} returned as null "
            f"rather than as zero arrests."
        )
    if one.undecided:
        count = len(one.undecided)
        why = (f"{label}'s {what} is 0, as it is in every month at an agency with no "
               f"resident population of its own, such as a transit or campus force"
               if one.gate is not None else
               f"the payload carries no participated population or coverage for "
               f"{geography} itself, and a wider geography's cannot say whether "
               f"this one reported")
        notices.append(
            f"{count} month{'' if count == 1 else 's'} came back null with nothing to "
            f"say whether {geography} reported "
            f"({_listed(_spans(observations, one.undecided))}): {why}. So "
            f"{'it is' if count == 1 else 'they are'} returned as null, as the CDE "
            f"sent {'it' if count == 1 else 'them'}, rather than as zero arrests."
        )
    if one.beyond:
        count = len(one.beyond)
        notices.append(
            f"The window runs {count} month{'' if count == 1 else 's'} past "
            f"max_data_date ({max_data_date}), where the UCR data stops "
            f"({_listed(_spans(observations, one.beyond))}): "
            f"{'that month is' if count == 1 else 'those months are'} returned as null."
        )
    return notices


def from_arrest_response(
    payload: Any, *, scope: str, unit: str = "count",
    offense: Optional[str] = None,
) -> FbiArrestSeries:
    """Select the count or the rate out of an arrest payload.

    One request carries both, as for offences, so *unit* is a selection made
    here and never reaches the FBI. There is no *measure* argument: the route
    serves arrests and nothing else.

    *offense* is the UCR arrest code, normalised as the client normalises it
    (``'ALL'`` is ``'all'``). The payload carries it too (the client records
    it from the request, since the labels do not), and that is used when
    *offense* is not given; a ``None`` payload falls back to ``'all'``.

    :func:`_arrest_notices` leads the notices on every response, including an
    empty one: which offence this is, since nothing in the labels says, and
    that an arrest is not a clearance, since differencing the two is the misuse
    no value in the payload reveals.

    A single offence (any code but ``'all'``) is read differently from the
    total before the non-reporting rule sees it, because nationally the CDE
    spells a month with no arrest for it as null: :func:`_one_offence` reads
    those as 0 where the scope's own participated population says it
    reported. Nationally and for a state the trailing run is then held to the
    same mass test as any other (``open_tail=False``): a rare code's quiet
    final months are ordinary, and the months past ``max_data_date`` have been
    set aside. At agency scope it stays open, because ``max_data_date`` is the
    national vintage and not the agency's last filing, and an agency's
    participated population carries on after it stops filing.

    **Both paths are judged on the counts**, whichever unit was asked for, and
    what the rule nulls in the count is nulled in the rate too. The mass floor
    is in arrests: judged in its own units a rate of 0.3 per 100,000 passes as
    a quiet stretch where the count behind it is a missing return, and one
    request's count and rate then disagree about which months exist -- New
    York's ``all`` arrests differed by one month (06-2022) on the saved payload,
    the offence route by up to 96.

    **Periodic returns are recognised on both paths** (:func:`_periodic`).
    Washington filed its 1992-1995 arrests in four Decembers of 55,607 to
    67,941 under eleven blank months each; nulling those blanks and keeping the
    December as one month's value left the monthly mean over the full history
    53% high, where the zeros the CDE sent average correctly over whole years.
    Those months come back as the CDE sent them, with a notice.

    A rate below zero is nulled on either path, with a notice: see
    :func:`_defined`.
    """
    resolved = UNITS.get(unit, unit)
    code = _arrest_code(offense, payload)
    name = ARREST_OFFENSES.get(code, code)
    series: List[FbiSeries] = list(getattr(payload, "series", None) or [])
    chosen = _select(series, measure="arrests", unit=resolved, scope=scope)
    if chosen is None:
        return FbiArrestSeries(
            offense=code, offense_name=name, scope=scope, unit=resolved,
            notices=[*_arrest_notices(code),
                     f"No arrest series as {resolved} in the payload for code {code} "
                     f"at {scope}. Arrests are verified back to "
                     f"{ARREST_VERIFIED_FROM}; a window entirely before that may "
                     f"simply have nothing in it."],
        )

    vintage = getattr(payload, "max_data_date", None)
    geography = _geography(chosen.label)
    chosen, undefined, published = _defined(
        chosen, _context(series, PARTICIPATED, geography, exact=True))
    read: List[str] = []
    from_null: List[str] = []
    counted = " arrests"
    # Judged on the counts: the same label's count series, which the same
    # payload always carries. Only a payload without one judges the rate.
    counts = next((s for s in series if s.measure == "arrests"
                   and s.unit == UNITS["count"] and s.label == chosen.label), chosen)
    if code == "all":
        # ``published`` is the months whose rate the CDE sent as -1. They are
        # null now, but the scope filed them, so the rule is told not to read
        # them as a return nobody sent -- it cannot tell the two spellings
        # apart, and used to say both things about the same months.
        negative = {chosen.observations[i].period for i in published}
        filings = _read_filings(
            counts.observations, periodic=True,
            filed=[i for i, o in enumerate(counts.observations)
                   if o.period in negative])
        if counts is chosen:
            observations = filings.observations
        else:
            dropped = set(filings.periods)
            observations = [FbiObservation(period=o.period, value=None)
                            if o.period in dropped else o for o in chosen.observations]
    else:
        agency = _is_agency(scope)
        one = _one_offence(counts.observations, series, geography, vintage,
                           agency=agency)
        filings = _read_filings(one.observations, open_tail=agency, periodic=True)
        dropped = {*filings.periods, *(counts.observations[i].period for i in one.dropped)}
        from_null = one.zeroed
        zeroed = [p for p in one.zeroed if p not in dropped]
        as_zero = set(zeroed)
        observations = [
            FbiObservation(period=o.period, value=None) if o.period in dropped
            else FbiObservation(period=o.period, value=0.0)
            if o.value is None and o.period in as_zero
            else o
            for o in chosen.observations]
        read = _one_offence_notices(one, counts.observations, geography, vintage,
                                    zeroed=zeroed)
    start, end = _span(observations)
    context = _qualify(series, chosen, observations)
    return FbiArrestSeries(
        offense=code, offense_name=name,
        scope=scope, geography=context.geography, unit=resolved,
        observation_start=start, observation_end=end,
        observations=observations,
        population=context.population,
        participated_population=context.participated,
        coverage=context.coverage,
        coverage_mean_percent=context.mean_percent,
        coverage_min_percent=context.min_percent,
        coverage_min_period=context.min_period,
        max_data_date=vintage,
        last_refresh_date=getattr(payload, "last_refresh_date", None),
        notices=[*_arrest_notices(code), *context.notices, *undefined, *read,
                 *_filing_notices(filings, len(observations),
                                  tail_already_flagged=context.tail_flagged,
                                  from_null=from_null, counted=counted,
                                  unit=resolved, judged_on_counts=counts is not chosen,
                                  vintage=vintage, agency=_is_agency(scope))],
    )


def from_employment_response(
    payload: Any, *, ori: str, measure: str = "officers",
) -> FbiEmploymentSeries:
    """Sum the sexes into the one annual series the catalog names.

    ``pe`` reports 'Male Officers' and 'Female Officers' separately; neither is
    the series anybody asks for. A year present in one and absent in the other
    contributes what it has rather than dropping out.

    The zero here is the same zero as in the monthly routes and needs the same
    reading. A year whose two halves both arrive as 0 sums to 0, and a 0 is a
    year *present* to any test on ``is not None`` -- so it suppresses the gap
    notice below, which is the one thing on this response that says a return is
    missing, and pads the span at either end. The run-and-mass rule settles it:
    a run of zero years at a department of four thousand officers is a return
    nobody sent, while an agency that genuinely employs no civilians has a
    level of zero, clears no floor and keeps its zeros. Years the rule takes
    are nulled and fold into the gap notice, which names how many of its gaps
    were spelled as 0 rather than as an absence; a year padded past the last
    return -- the current one, whose return has not arrived -- gets a sentence
    of its own, since the gap notice looks only between the first filing and
    the last.
    """
    series: List[FbiSeries] = list(getattr(payload, "series", None) or [])
    parts = [s for s in series if s.measure == measure and s.unit == "count"]
    totals: dict[str, float] = {}
    for part in parts:
        for observation in part.observations:
            if observation.value is not None:
                totals[observation.period] = totals.get(observation.period, 0.0) + observation.value
    filings = _read_filings(
        FbiObservation(period=period, value=value)
        for period, value in sorted(totals.items(), key=lambda kv: _year(kv[0]) or 0)
    )
    observations = filings.observations
    padded = set(filings.periods)

    notices: List[str] = []
    if not _filled(observations):
        notices.append(
            f"No {measure} reported for {ori} in this window. Employment is served "
            f"per agency only -- pe/national and pe/state answer with nulls -- and "
            f"filing is voluntary."
        )
    else:
        years = {_year(o.period) for o in _filled(observations)}
        first, last = min(y for y in years if y), max(y for y in years if y)
        gaps = [y for y in range(first, last + 1) if y not in years]
        zeroed = [y for y in gaps if str(y) in padded]
        if gaps:
            notices.append(
                f"{len(gaps)} year{'' if len(gaps) == 1 else 's'} between {first} "
                f"and {last} with no return "
                f"({', '.join(str(y) for y in gaps[:8])}"
                f"{', ...' if len(gaps) > 8 else ''}): the agency did not file, "
                f"which is not the same as employing nobody."
                + (f" {len(zeroed)} of them arrived as 0 rather than as an absence "
                   f"and are returned as null, so a sum does not read a skipped "
                   f"return as a department of nobody."
                   if zeroed else "")
            )
    if filings.trailing:
        count = len(filings.after)
        notices.append(
            f"The window runs {count} year{'' if count == 1 else 's'} past the last "
            f"return ({_listed(filings.trailing)}): the CDE pads to the requested "
            f"end with 0 rather than with null, so observation_end names the last "
            f"year the agency actually filed."
        )
    return FbiEmploymentSeries(
        ori=ori, measure=measure,
        observation_start=filings.start, observation_end=filings.end,
        observations=observations,
        population=_context(series, "people", ori),
        max_data_date=getattr(payload, "max_data_date", None),
        last_refresh_date=getattr(payload, "last_refresh_date", None),
        notices=notices,
    )
