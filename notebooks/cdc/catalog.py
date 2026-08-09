"""CDC series-catalog generation.

Hand-written **registry** of curated CDC datasets (the CDC stand-in for BIS's
SDMX structure) + ``export_cdc_catalog()`` which walks each spec's facet
cross-product and emits the **series catalog** -- one atomic entry per
permutation, each carrying its exact ``cdc_series_data`` call arguments
(``dataset_id`` + ``where`` + ``select``) plus descriptive metadata. Output goes
to ``notebooks/cdc/data/`` (gitignored, regenerable), consumed by yada's
document store. ``server.py`` is unchanged -- the recipes are replayed through
the existing raw-SoQL ``cdc_series_data`` tool.

Two pivot modes, because CDC datasets split into two shapes:
  * CROSS      -- facets are independent columns; true Cartesian product
                  (w9j2-ggv5 race x sex, xkb8-kh2a state x drug).
  * STRATIFIED -- one active stratification per row; series = Overall + each
                  value of each chosen category (w26f-tf3h, hksd-2xuw).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

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
         time_field="year", value_field="data_value", mode="cross",
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


def _select(spec: Spec) -> str:
    return f"{spec.time_field} AS year, {spec.value_field} AS value"


def _entry(spec: Spec, facets: dict[str, str], where: list[str], rate: str | None) -> dict[str, Any]:
    parts = [spec.concept, spec.dataset_id] + [f"{k}={v}" for k, v in facets.items()]
    if rate:
        parts.append(rate)
    sid = "cdc/" + "/".join(_slug(p) for p in parts)
    title_bits = ", ".join(f"{k}={v}" for k, v in facets.items()) or "overall"
    title = f"{spec.concept.replace('_', ' ')} ({title_bits}" + (f", {rate}" if rate else "") + ")"
    return {
        "series_id": sid,
        "dataset_id": spec.dataset_id,
        "where": " AND ".join(where),
        "select": _select(spec),
        "title": title,
        "concept": spec.concept,
        "unit": spec.unit,
        "frequency": spec.frequency,
        "cadence": spec.cadence,
        "provisional": spec.provisional,
        "live": spec.live,
        "facets": {**facets, **({"rate_type": rate} if rate else {})},
    }


def _reverse(d: dict[str, str]) -> dict[str, str]:
    return {v: k for k, v in d.items()}


def group_query(spec: Spec) -> tuple[list[str], list[str]]:
    """Return (group-by columns, where) that enumerate combos which HAVE data.

    Grouping over the facet/strat columns (+ rate column) with ``value NOT NULL``
    yields exactly the combinations that exist -- so suppressed cells never
    become catalog entries.
    """
    where = list(spec.base_where) + [f"{spec.value_field} IS NOT NULL"]
    if spec.mode == "cross":
        cols = [f.column for f in spec.facets.values()]
    else:
        cols = [spec.strat_category_col, spec.strat_value_col]
        if spec.location_col:
            cols = [spec.location_col] + cols
    if spec.rate_type:
        cols.append(spec.rate_type.column)
    return cols, where


def group_soql(spec: Spec) -> tuple[str, str]:
    """Ready-to-send ($select/$group string, $where string) for the group-by,
    with reserved-word columns back-ticked. Returned row keys stay unquoted."""
    cols, where = group_query(spec)
    return ", ".join(_col(c) for c in cols), " AND ".join(where)


def _apply_rate(spec: Spec, row: dict[str, Any], rt_rev: dict[str, str],
                where: list[str]) -> str | None | bool:
    """Append the rate condition; return canonical rate, None, or False to skip."""
    if spec.rate_type is None:
        return None
    literal = row.get(spec.rate_type.column)
    canonical = rt_rev.get(literal)
    if canonical is None:                    # rate variant we don't curate
        return False
    where.append(_eq(spec.rate_type.column, literal))
    return canonical


def build(spec: Spec, group_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Emit catalog entries for the existing combos in ``group_rows``.

    Literals are normalized to canonical tokens via the registry maps; any literal
    not in the curated set is skipped (drops non-curated strata like 'Grade',
    overlapping age aggregates, and meta drug indicators).
    """
    out: list[dict[str, Any]] = []
    rt_rev = _reverse(spec.rate_type.values) if spec.rate_type else {}

    if spec.mode == "cross":
        facet_rev = {name: (None if f.dynamic else _reverse(f.values))
                     for name, f in spec.facets.items()}
        for row in group_rows:
            facets, where, skip = {}, list(spec.base_where), False
            for name, f in spec.facets.items():
                literal = row.get(f.column)
                if literal in (None, ""):
                    skip = True; break
                canonical = literal if f.dynamic else facet_rev[name].get(literal)
                if canonical is None:        # literal not in curated set
                    skip = True; break
                facets[name] = canonical
                where.append(_eq(f.column, literal))
            if skip:
                continue
            rate = _apply_rate(spec, row, rt_rev, where)
            if rate is False:
                continue
            out.append(_entry(spec, facets, where, rate))
    else:
        cat_to_name = {spec.overall[0]: "__overall__"}
        for name, bd in spec.breakdowns.items():
            cat_to_name[bd.category] = name
        for row in group_rows:
            cat, val = row.get(spec.strat_category_col), row.get(spec.strat_value_col)
            name = cat_to_name.get(cat)
            if name is None:                 # non-curated stratification
                continue
            where = list(spec.base_where) + [_eq(spec.strat_category_col, cat),
                                             _eq(spec.strat_value_col, val)]
            if name == "__overall__":
                if val != spec.overall[1]:
                    continue
                facets = {}
            else:
                canonical = _reverse(spec.breakdowns[name].values).get(val)
                if canonical is None:        # e.g. overlapping age aggregate
                    continue
                facets = {name: canonical}
            if spec.location_col:            # scope each stratification series to one state
                loc = row.get(spec.location_col)
                if loc in (None, ""):
                    continue
                where.append(_eq(spec.location_col, loc))
                facets = {"state": loc, **facets}
            rate = _apply_rate(spec, row, rt_rev, where)
            if rate is False:
                continue
            out.append(_entry(spec, facets, where, rate))
    return out


# =========================================================================== #
# SPECIAL CASES -- three datasets that don't fit the generic pivot
# =========================================================================== #

# --- 1. 9j2v-jamp suicide history: NCHS "stub" schema (colon-delimited label) ---
SUICIDE_HISTORY = Spec(
    dataset_id="9j2v-jamp", concept="suicide", unit="per 100,000",
    frequency="annual", cadence="irregular", live=False,
    time_field="year", value_field="estimate", mode="stub")

_9J2V_SEX = {"Male": "male", "Female": "female"}
_9J2V_RACE = {"White": "white", "Black or African American": "black",
              "American Indian or Alaska Native": "aian",
              "Asian or Pacific Islander": "asian_pi"}
_9J2V_AGE = {"10-14 years": "10-14", "15-19 years": "15-19", "20-24 years": "20-24",
             "25-34 years": "25-34", "35-44 years": "35-44", "45-54 years": "45-54",
             "55-64 years": "55-64", "65-74 years": "65-74", "75-84 years": "75-84",
             "85 years and over": "85+"}   # drop overlapping aggregates (15-24, 25-44, ...)
_9J2V_RATE = {"Deaths per 100,000 resident population, age-adjusted": "age_adjusted",
              "Deaths per 100,000 resident population, crude": "crude"}
SUICIDE_HISTORY_SCHEMES = ("Total", "Sex", "Sex and age", "Sex and race")


def suicide_history_group() -> tuple[str, str]:
    schemes = ",".join(f"'{s}'" for s in SUICIDE_HISTORY_SCHEMES)
    return ("stub_name, stub_label, unit",
            f"stub_name in({schemes}) AND estimate IS NOT NULL")


def build_suicide_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        scheme, label, unit = r.get("stub_name"), r.get("stub_label"), r.get("unit")
        rate = _9J2V_RATE.get(unit)
        if rate is None:
            continue
        if scheme == "Total":
            facets = {} if label == "All persons" else None
        elif scheme == "Sex":
            s = _9J2V_SEX.get(label)
            facets = {"sex": s} if s else None
        elif scheme == "Sex and age":
            parts = (label or "").split(": ", 1)
            s = _9J2V_SEX.get(parts[0]) if len(parts) == 2 else None
            a = _9J2V_AGE.get(parts[1]) if len(parts) == 2 else None
            facets = {"sex": s, "age": a} if s and a else None      # skips age aggregates
        elif scheme == "Sex and race":
            parts = (label or "").split(": ", 1)
            s = _9J2V_SEX.get(parts[0]) if len(parts) == 2 else None
            rc = _9J2V_RACE.get(parts[1]) if len(parts) == 2 else None
            facets = {"sex": s, "race": rc} if s and rc else None
        else:
            facets = None
        if facets is None:
            continue
        where = [f"stub_name='{scheme}'", _eq("stub_label", label), _eq("unit", unit)]
        out.append(_entry(SUICIDE_HISTORY, facets, where, rate))
    return out


# --- 2. LE state snapshots: union 4 single-year datasets into per-(area,sex) series ---
LE_SNAPSHOTS = [   # (year, dataset_id, geo_column, value_column)
    ("2018", "a5a8-jsrq", "state", "leb"), ("2019", "ncvk-7amm", "state", "leb"),
    ("2020", "ss2j-8ajj", "state", "le"),  ("2021", "it4f-frdc", "area", "leb"),
]
_LE_SEX = {"Total": "total", "Male": "male", "Female": "female"}


def build_le_snapshots(members: dict[tuple[str, str], dict[str, tuple]]) -> list[dict[str, Any]]:
    """``members``: (area, sex) -> {year: (dataset_id, geo_col, value_col, geo_value)}.
    Emits one series per (area, sex) with a multi-source union recipe (one
    cdc_series_data call per year, merged downstream)."""
    out = []
    for (area, sex), yrs in members.items():
        canon = _LE_SEX.get(sex)
        if canon is None:
            continue
        sources = [{"dataset_id": ds, "where": f"{_eq(geo_col, gv)} AND {_eq('sex', sex)}",
                    "select": f"'{yr}' AS year, {val_col} AS value"}
                   for yr, (ds, geo_col, val_col, gv) in sorted(yrs.items())]
        out.append({
            "series_id": f"cdc/life_expectancy/state_snapshots/{_slug(area)}/sex={canon}",
            "concept": "life_expectancy", "unit": "years", "frequency": "annual",
            "cadence": "irregular", "provisional": False, "live": False,
            "title": f"life expectancy at birth ({area}, {canon})",
            "facets": {"area": area, "sex": canon},
            "observation_start": min(yrs), "observation_end": max(yrs),
            "sources": sources,   # multi-part union recipe
        })
    return out


# --- 3. VSRR 489q-934x: state/sex live in wide columns -> pick the value column ---
_VSRR_CAUSES = {"Suicide": "suicide", "Drug overdose": "drug_overdose",
                "Chronic liver disease and cirrhosis": "chronic_liver_mortality"}
_VSRR_RATE = {"Age-adjusted": "age_adjusted", "Crude": "crude"}
_VSRR_GEO = {"overall": "rate_overall", "male": "rate_sex_male", "female": "rate_sex_female"}
_VSRR_PERIOD = "12 months ending with quarter"


def build_vsrr() -> list[dict[str, Any]]:
    """National + sex despair triad, 12-month-ending. Sex is a value-column choice
    (rate_overall / rate_sex_male / rate_sex_female), not a row filter."""
    out = []
    for cause_lit, concept in _VSRR_CAUSES.items():
        for rate_lit, rate in _VSRR_RATE.items():
            for geo, col in _VSRR_GEO.items():
                where = [_eq("cause_of_death", cause_lit), _eq("rate_type", rate_lit),
                         _eq("time_period", _VSRR_PERIOD)]
                facets = {} if geo == "overall" else {"sex": geo}
                bits = [concept, "489q-934x", "quarterly"] + \
                       ([f"sex={geo}"] if geo != "overall" else []) + [rate]
                out.append({
                    "series_id": "cdc/" + "/".join(_slug(b) for b in bits),
                    "dataset_id": "489q-934x", "concept": concept, "unit": "per 100,000",
                    "frequency": "quarterly", "cadence": "R/P3M",
                    "provisional": True, "live": True,
                    "title": f"{concept.replace('_', ' ')} (VSRR quarterly, {geo}, {rate})",
                    "where": " AND ".join(where),
                    "select": f"year_and_quarter AS year, {col} AS value",
                    "facets": {**facets, "rate_type": rate, "period": "12mo_ending"},
                })
    return out


# =========================================================================== #
# EXPORT -- generate the full series catalog (metadata YAML) via CdcClient
# =========================================================================== #

async def _span(client, dataset_id: str, time_field: str,
                base_where: tuple[str, ...]) -> tuple[str | None, str | None]:
    where = " AND ".join(base_where) if base_where else None
    resp = await client.query(dataset_id, select=f"min({time_field}) as a, max({time_field}) as b",
                              where=where, limit=1)
    row = resp.rows[0] if resp.rows else {}
    return row.get("a"), row.get("b")


def _write_yaml(payload: dict[str, Any], path: Path) -> None:
    with path.open("w") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)


async def export_cdc_catalog(client, output_dir: str | Path) -> dict[str, Any]:
    """Generate the CDC series catalog into ``output_dir`` (one file per source
    group + a ``dataset.yaml`` index). Returns a summary. Metadata only --
    observations are fetched on demand via ``cdc_series_data`` replaying each
    entry's recipe."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[dict[str, Any]]] = {}

    async def stamp(entries, dataset_id, time_field, base_where):
        a, b = await _span(client, dataset_id, time_field, base_where)
        for e in entries:
            e.setdefault("observation_start", a)
            e.setdefault("observation_end", b)

    # clean datasets (generic build)
    for spec in REGISTRY:
        sel, where = group_soql(spec)
        rows = (await client.query(spec.dataset_id, select=sel, group=sel,
                                   where=where, limit=50_000)).rows
        entries = build(spec, rows)
        await stamp(entries, spec.dataset_id, spec.time_field, spec.base_where)
        groups.setdefault(spec.dataset_id, []).extend(entries)

    # special: suicide history (stub)
    sel, where = suicide_history_group()
    rows = (await client.query("9j2v-jamp", select=sel, group=sel, where=where, limit=50_000)).rows
    sh = build_suicide_history(rows)
    await stamp(sh, "9j2v-jamp", "year", ())
    groups.setdefault("9j2v-jamp", []).extend(sh)

    # special: VSRR (column melt)
    vsrr = build_vsrr()
    causes = ",".join(f"'{c}'" for c in _VSRR_CAUSES)
    await stamp(vsrr, "489q-934x", "year_and_quarter", (f"cause_of_death in({causes})",))
    groups.setdefault("489q-934x", []).extend(vsrr)

    # special: LE snapshots (union) -- entries already carry their span
    members: dict[tuple[str, str], dict[str, tuple]] = {}
    for yr, ds, geo_col, val_col in LE_SNAPSHOTS:
        rows = (await client.query(ds, select=f"{geo_col},sex", group=f"{geo_col},sex", limit=500)).rows
        for r in rows:
            gv, sx = r.get(geo_col), r.get("sex")
            if gv and sx:
                members.setdefault((gv, sx), {})[yr] = (ds, geo_col, val_col, gv)
    groups["le_snapshots"] = build_le_snapshots(members)

    # write per-group files + index
    index = []
    for key, entries in groups.items():
        fname = f"cdc_series_{key}.yaml"
        _write_yaml({"group": key, "series_count": len(entries), "series": entries}, out / fname)
        index.append({"group": key, "series_file": fname, "series_count": len(entries),
                      "concepts": sorted({e["concept"] for e in entries})})
    total = sum(len(v) for v in groups.values())
    _write_yaml({"source": "cdc", "total_series": total, "groups": index}, out / "dataset.yaml")
    return {"total": total, "by_group": {k: len(v) for k, v in groups.items()}}
