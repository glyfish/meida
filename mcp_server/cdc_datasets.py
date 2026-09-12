"""The CDC query contract: which columns and literals back each named facet.

This is the single source of truth for how a *canonical token* the MCP client
sends (``race="black"``) becomes a SoQL predicate against a specific dataset
(``race='Black'`` on w9j2-ggv5, but ``group='Race and Hispanic origin' AND
subgroup='Black only, non-Hispanic'`` on w26f-tf3h). The same concept is spelled
differently in every dataset, so the mapping has to be explicit.

It lives in ``mcp_server`` rather than ``notebooks/cdc`` because the server is
its primary consumer -- ``cdc_query.build`` turns tool arguments into SoQL, so
no SoQL crosses the wire. ``notebooks/cdc/catalog.py`` imports from here to
generate the series catalog, which keeps the tool's accepted vocabulary and the
catalog's ``facets`` metadata keys identical by construction.

Two pivot modes, because CDC datasets split into two shapes:
  * CROSS      -- facets are independent columns; true Cartesian product
                  (w9j2-ggv5 race x sex, xkb8-kh2a state x drug).
  * STRATIFIED -- one active stratification per row; series = Overall + each
                  value of each chosen category (w26f-tf3h, hksd-2xuw).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# value-normalization maps: canonical token -> the dataset's exact literal
# (the same real-world concept is spelled differently per dataset -- e.g. White)
# --------------------------------------------------------------------------- #
W9J2_RACE = {"all": "All Races", "white": "White", "black": "Black"}
W9J2_SEX = {"both": "Both Sexes", "male": "Male", "female": "Female"}

W26F_RACE = {
    "white": "White only, non-Hispanic", "black": "Black only, non-Hispanic",
    "hispanic": "All races, Hispanic", "asian": "Asian only, non-Hispanic",
    "aian": "American Indian and Alaska Native only, non-Hispanic",
    "nhpi": "Native Hawaiian or Other Pacific Islander only, non-Hispanic",
}
W26F_SEX = {"male": "Male", "female": "Female"}
# NCHS age bands carry overlapping aggregates (15-24 alongside 15-19+20-24); we
# keep the clean 10-year partition and drop the aggregates.
W26F_AGE = {
    "10-14": "10-14 years", "15-19": "15-19 years", "20-24": "20-24 years",
    "25-34": "25-34 years", "35-44": "35-44 years", "45-54": "45-54 years",
    "55-64": "55-64 years", "65-74": "65-74 years", "75-84": "75-84 years",
    "85+": "85 years and older",
}
W26F_RATE = {
    "age_adjusted": "Deaths per 100,000 resident population, age adjusted",
    "crude": "Deaths per 100,000 resident population, crude",
}

HKSD_RACE = {
    "white": "White, non-Hispanic", "black": "Black, non-Hispanic",
    "hispanic": "Hispanic", "asian": "Asian, non-Hispanic",
    "aian": "American Indian or Alaska Native, non-Hispanic",
    "nhpi": "Native Hawaiian or Other Pacific Islander, non-Hispanic",
    "multiracial": "Multiracial, non-Hispanic",
}
HKSD_SEX = {"male": "Male", "female": "Female"}
HKSD_AGE = {"18-44": "Age 18-44", "45-64": "Age 45-64", "65+": "Age >=65"}

# curated overdose drug categories (drop the meta indicators)
XKB8_DRUG = {
    "all": "Number of Drug Overdose Deaths",
    "opioids": "Opioids (T40.0-T40.4,T40.6)",
    "heroin": "Heroin (T40.1)",
    "synthetic_opioids": "Synthetic opioids, excl. methadone (T40.4)",
    "natural_semisynthetic": "Natural & semi-synthetic opioids (T40.2)",
    "methadone": "Methadone (T40.3)",
    "cocaine": "Cocaine (T40.5)",
    "psychostimulants": "Psychostimulants with abuse potential (T43.6)",
}


@dataclass(frozen=True)
class Facet:
    """A CROSS-mode facet: an independent column with a normalized value map."""
    column: str
    values: dict[str, str]          # canonical -> literal
    dynamic: bool = False           # if True, values are queried live (identity map)


@dataclass(frozen=True)
class Breakdown:
    """A STRATIFIED-mode breakdown: a category literal + its value map."""
    category: str                   # e.g. "Sex" (value of the stratification-category column)
    values: dict[str, str]          # canonical -> value literal
    crude_only: bool = False        # age-specific -> no age-adjusted rate


@dataclass(frozen=True)
class RateType:
    column: str
    values: dict[str, str]          # canonical -> literal
    default: str


@dataclass(frozen=True)
class Spec:
    dataset_id: str
    concept: str
    unit: str
    frequency: str
    cadence: str
    time_field: str
    value_field: str
    mode: str                       # "cross" | "stratified"
    provisional: bool = False
    live: bool = True
    base_where: tuple[str, ...] = ()          # always-applied conditions
    facets: dict[str, Facet] = field(default_factory=dict)          # cross mode
    strat_category_col: str | None = None                          # stratified mode
    strat_value_col: str | None = None
    location_col: str | None = None          # stratified datasets that also vary by state
    # Set when the period needs two columns. xkb8-kh2a is monthly but splits the
    # period across `year` and `month`, so selecting time_field alone returns
    # twelve rows sharing one label. Socrata cannot concatenate them -- there is
    # no concat() and || silently yields nothing -- so both are selected and the
    # label is composed after the fetch.
    month_field: str | None = None
    overall: tuple[str, str] | None = None    # (category literal, value literal)
    breakdowns: dict[str, Breakdown] = field(default_factory=dict)  # stratified mode
    rate_type: RateType | None = None


# --------------------------------------------------------------------------- #
# THE REGISTRY  (clean datasets; special-case ones added by their handlers)
# --------------------------------------------------------------------------- #
REGISTRY: list[Spec] = [
    Spec(dataset_id="w9j2-ggv5", concept="life_expectancy", unit="years",
         frequency="annual", cadence="irregular", live=False,
         time_field="year", value_field="average_life_expectancy", mode="cross",
         facets={"race": Facet("race", W9J2_RACE), "sex": Facet("sex", W9J2_SEX)}),
    Spec(dataset_id="w9j2-ggv5", concept="mortality", unit="deaths per 100,000",
         frequency="annual", cadence="irregular", live=False,
         time_field="year", value_field="mortality", mode="cross",
         facets={"race": Facet("race", W9J2_RACE), "sex": Facet("sex", W9J2_SEX)}),

    Spec(dataset_id="xkb8-kh2a", concept="drug_overdose", unit="deaths (12-mo-ending count)",
         frequency="monthly", cadence="R/P1M", provisional=True,
         time_field="year", month_field="month", value_field="data_value", mode="cross",
         facets={"state": Facet("state", {}, dynamic=True),
                 "drug": Facet("indicator", XKB8_DRUG)}),

    Spec(dataset_id="w26f-tf3h", concept="suicide", unit="per 100,000",
         frequency="annual", cadence="R/P1Y",
         time_field="time_period", value_field="estimate", mode="stratified",
         strat_category_col="group", strat_value_col="subgroup",
         overall=("Total", "All ages"),
         breakdowns={"sex": Breakdown("Sex", W26F_SEX),
                     "race": Breakdown("Race and Hispanic origin", W26F_RACE),
                     "age": Breakdown("Age group", W26F_AGE, crude_only=True)},
         rate_type=RateType("estimate_type", W26F_RATE, "age_adjusted")),

    Spec(dataset_id="hksd-2xuw", concept="alcohol_consumption", unit="gallons per capita",
         frequency="annual", cadence="R/P1Y",
         time_field="yearstart", value_field="datavalue", mode="stratified",
         base_where=("topic='Alcohol'", "questionid='ALC08'"),
         strat_category_col="stratificationcategory1", strat_value_col="stratification1",
         location_col="locationabbr",
         overall=("Overall", "Overall"), breakdowns={}),

    Spec(dataset_id="hksd-2xuw", concept="alcohol_binge", unit="percent",
         frequency="annual", cadence="R/P1Y",
         time_field="yearstart", value_field="datavalue", mode="stratified",
         base_where=("topic='Alcohol'", "questionid='ALC06'"),
         strat_category_col="stratificationcategory1", strat_value_col="stratification1",
         location_col="locationabbr",
         overall=("Overall", "Overall"),
         breakdowns={"sex": Breakdown("Sex", HKSD_SEX),
                     "race": Breakdown("Race/Ethnicity", HKSD_RACE),
                     "age": Breakdown("Age", HKSD_AGE)},
         rate_type=RateType("datavaluetype",
                            {"age_adjusted": "Age-adjusted Prevalence", "crude": "Crude Prevalence"},
                            "age_adjusted")),

    Spec(dataset_id="hksd-2xuw", concept="chronic_liver_mortality", unit="per 100,000",
         frequency="annual", cadence="R/P1Y",
         time_field="yearstart", value_field="datavalue", mode="stratified",
         base_where=("topic='Alcohol'", "questionid='ALC09'"),
         strat_category_col="stratificationcategory1", strat_value_col="stratification1",
         location_col="locationabbr",
         overall=("Overall", "Overall"),
         breakdowns={"sex": Breakdown("Sex", HKSD_SEX),
                     "race": Breakdown("Race/Ethnicity", HKSD_RACE),
                     "age": Breakdown("Age", HKSD_AGE, crude_only=True)},
         rate_type=RateType("datavaluetype",
                            {"age_adjusted": "Age-adjusted Rate", "count": "Number"},
                            "age_adjusted")),
]

_RESERVED = {"group"}


def _col(name: str) -> str:
    return f"`{name}`" if name in _RESERVED else name


def _eq(col: str, literal: str) -> str:
    return f"{_col(col)}='{literal.replace(chr(39), chr(39) * 2)}'"


def _slug(text: str) -> str:
    return str(text).lower().replace(" ", "_").replace(",", "").replace(">=", "ge")


#: xkb8-kh2a writes month names, not numbers, so they neither sort nor parse.
MONTH_NUMBER: dict[str, str] = {
    "January": "01", "February": "02", "March": "03", "April": "04",
    "May": "05", "June": "06", "July": "07", "August": "08",
    "September": "09", "October": "10", "November": "11", "December": "12",
}


def _select(spec: Spec) -> str:
    """The two-column contract: one time label, one value.

    A dataset whose period spans two columns selects both -- the label is
    composed after the fetch, since Socrata has no string concatenation.
    """
    if spec.month_field:
        return (f"{spec.time_field}, {spec.month_field}, "
                f"{spec.value_field} AS value")
    return f"{spec.time_field} AS year, {spec.value_field} AS value"


# --------------------------------------------------------------------------- #
# the two datasets whose shape the two modes above do not cover
# --------------------------------------------------------------------------- #
#: 9j2v-jamp is NCHS "stub" long format: the demographic breakdown is a scheme
#: name plus a composed label ("Sex and age" / "Female: 10-14 years"), and the
#: rate type lives in ``unit`` rather than a rate column.
_9J2V_SEX_LIT = {"male": "Male", "female": "Female"}
_9J2V_RACE_LIT = {"white": "White", "black": "Black or African American",
                  "aian": "American Indian or Alaska Native",
                  "asian_pi": "Asian or Pacific Islander"}
_9J2V_AGE_LIT = {"10-14": "10-14 years", "15-19": "15-19 years", "20-24": "20-24 years",
                 "25-34": "25-34 years", "35-44": "35-44 years", "45-54": "45-54 years",
                 "55-64": "55-64 years", "65-74": "65-74 years", "75-84": "75-84 years",
                 "85+": "85 years and over"}
_9J2V_UNIT_LIT = {
    "age_adjusted": "Deaths per 100,000 resident population, age-adjusted",
    "crude": "Deaths per 100,000 resident population, crude",
}

#: 489q-934x (VSRR) puts sex in *wide value columns*, so ``sex`` selects which
#: column to read rather than filtering rows.
_VSRR_CAUSE_LIT = {"suicide": "Suicide", "drug_overdose": "Drug overdose",
                   "chronic_liver_mortality": "Chronic liver disease and cirrhosis"}
_VSRR_RATE_LIT = {"age_adjusted": "Age-adjusted", "crude": "Crude"}
_VSRR_SEX_COL = {"both": "rate_overall", "male": "rate_sex_male",
                 "female": "rate_sex_female"}


@dataclass(frozen=True)
class StubSpec:
    """9j2v-jamp: facet set -> (scheme literal, ordered label parts)."""
    dataset_id: str = "9j2v-jamp"
    concept: str = "suicide"
    unit: str = "per 100,000"
    frequency: str = "annual"
    time_field: str = "year"
    value_field: str = "estimate"
    category_col: str = "stub_name"
    label_col: str = "stub_label"
    rate_col: str = "unit"
    schemes: dict[frozenset, str] = field(default_factory=lambda: {
        frozenset(): "Total",
        frozenset({"sex"}): "Sex",
        frozenset({"sex", "age"}): "Sex and age",
        frozenset({"sex", "race"}): "Sex and race",
    })
    total_label: str = "All persons"
    label_order: tuple[str, ...] = ("sex", "age", "race")
    values: dict[str, dict[str, str]] = field(default_factory=lambda: {
        "sex": _9J2V_SEX_LIT, "race": _9J2V_RACE_LIT,
        "age": _9J2V_AGE_LIT, "rate_type": _9J2V_UNIT_LIT,
    })


@dataclass(frozen=True)
class VsrrSpec:
    """489q-934x: concept -> cause_of_death row filter; sex -> value column."""
    dataset_id: str = "489q-934x"
    unit: str = "per 100,000"
    frequency: str = "quarterly"
    time_field: str = "year_and_quarter"
    cause_col: str = "cause_of_death"
    rate_col: str = "rate_type"
    period_col: str = "time_period"
    period_literal: str = "12 months ending with quarter"
    causes: dict[str, str] = field(default_factory=lambda: dict(_VSRR_CAUSE_LIT))
    rates: dict[str, str] = field(default_factory=lambda: dict(_VSRR_RATE_LIT))
    sex_columns: dict[str, str] = field(default_factory=lambda: dict(_VSRR_SEX_COL))


STUB = StubSpec()
VSRR = VsrrSpec()

#: The nation as a facet value. ``state`` holds postal codes and there is no
#: postal code for the country, so national series carry ``geography`` instead.
NATIONAL = "national"

#: Full jurisdiction name -> postal code. Socrata's single-year life-expectancy
#: datasets spell states out ("New Mexico") where every other CDC dataset uses
#: the code, so a catalog built straight from them files those series under a
#: vocabulary nothing else searches. Normalising here keeps one key, one
#: spelling: see :func:`postal_code`.
POSTAL_BY_NAME: dict[str, str] = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME",
    "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE",
    "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}


def postal_code(area: str) -> str | None:
    """Postal code for a jurisdiction, or None where it is not one.

    Returns None for "United States", which these datasets list beside the
    states -- the caller files that under :data:`NATIONAL` instead of
    inventing a code for it.
    """
    return POSTAL_BY_NAME.get(area.strip())



#: Postal codes appearing across CDC's state-level datasets. Wider than the 50
#: states: DC, the territories (GU, PR, VI), the national rollup ``US``, and
#: ``YC`` (New York City, which BRFSS reports separately from NY).
STATES: tuple[str, ...] = (
    "AK", "AL", "AR", "AZ", "CA", "CO", "CT", "DC", "DE", "FL", "GA", "GU",
    "HI", "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME", "MI",
    "MN", "MO", "MS", "MT", "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY",
    "OH", "OK", "OR", "PA", "PR", "RI", "SC", "SD", "TN", "TX", "US", "UT",
    "VA", "VI", "VT", "WA", "WI", "WV", "WY", "YC",
)
