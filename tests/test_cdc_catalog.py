"""Tests for the CDC series-catalog registry + build logic (``notebooks/cdc/catalog.py``).

Pure-function tests: ``build`` and the special handlers take group-by rows as
input, so no network is needed. They assert value-normalization, reserved-word
quoting, the reality-driven pruning of non-curated / suppressed combos, the
location dimension, and the three special-case handlers.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "notebooks" / "cdc"))

import catalog as C  # noqa: E402

AA_W26F = "Deaths per 100,000 resident population, age adjusted"
AA_9J2V = "Deaths per 100,000 resident population, age-adjusted"
CRUDE_9J2V = "Deaths per 100,000 resident population, crude"


def _spec(concept, dataset_id=None):
    return next(s for s in C.REGISTRY if s.concept == concept
                and (dataset_id is None or s.dataset_id == dataset_id))


def test_cross_normalizes_values_and_builds_recipe():
    spec = _spec("life_expectancy", "w9j2-ggv5")
    rows = [{"race": "White", "sex": "Male"}, {"race": "All Races", "sex": "Both Sexes"}]
    entries = C.build(spec, rows)
    assert len(entries) == 2
    e = entries[0]
    assert e["dataset_id"] == "w9j2-ggv5"
    assert e["where"] == "race='White' AND sex='Male'"
    assert e["select"] == "year AS year, average_life_expectancy AS value"
    assert e["facets"] == {"race": "white", "sex": "male"}
    assert e["series_id"] == "cdc/life_expectancy/w9j2-ggv5/race=white/sex=male"


def test_cross_dynamic_facet_is_identity():
    spec = _spec("drug_overdose", "xkb8-kh2a")
    rows = [{"state": "PA", "indicator": "Heroin (T40.1)"}]
    e = C.build(spec, rows)[0]
    assert e["where"] == "state='PA' AND indicator='Heroin (T40.1)'"
    assert e["facets"] == {"state": "PA", "drug": "heroin"}


def test_cross_skips_noncurated_value():
    spec = _spec("life_expectancy", "w9j2-ggv5")
    assert C.build(spec, [{"race": "Martian", "sex": "Male"}]) == []


def test_stratified_reserved_word_quoted_and_rate():
    spec = _spec("suicide", "w26f-tf3h")
    rows = [{"group": "Sex", "subgroup": "Male", "estimate_type": AA_W26F}]
    e = C.build(spec, rows)[0]
    assert "`group`='Sex'" in e["where"]
    assert "subgroup='Male'" in e["where"]
    assert e["facets"] == {"sex": "male", "rate_type": "age_adjusted"}


def test_stratified_carries_location():
    spec = _spec("chronic_liver_mortality", "hksd-2xuw")
    rows = [{"locationabbr": "CA", "stratificationcategory1": "Race/Ethnicity",
             "stratification1": "White, non-Hispanic", "datavaluetype": "Age-adjusted Rate"}]
    e = C.build(spec, rows)[0]
    assert "locationabbr='CA'" in e["where"]
    assert e["facets"]["state"] == "CA"
    assert e["facets"]["race"] == "white"
    assert e["facets"]["rate_type"] == "age_adjusted"


def test_stratified_skips_grade_and_overlapping_age():
    spec = _spec("alcohol_binge", "hksd-2xuw")
    rows = [
        {"locationabbr": "US", "stratificationcategory1": "Grade",
         "stratification1": "Grade 9", "datavaluetype": "Crude Prevalence"},   # non-curated category
    ]
    assert C.build(spec, rows) == []


def test_suicide_history_stub_parser():
    rows = [
        {"stub_name": "Total", "stub_label": "All persons", "unit": AA_9J2V},
        {"stub_name": "Sex and age", "stub_label": "Female: 45-54 years", "unit": CRUDE_9J2V},
        {"stub_name": "Sex and race", "stub_label": "Male: White", "unit": AA_9J2V},
        {"stub_name": "Sex and age", "stub_label": "Female: 45-64 years", "unit": CRUDE_9J2V},  # overlap
    ]
    entries = C.build_suicide_history(rows)
    ids = {e["series_id"] for e in entries}
    assert "cdc/suicide/9j2v-jamp/age_adjusted" in ids                       # Total
    assert "cdc/suicide/9j2v-jamp/sex=female/age=45-54/crude" in ids         # sex x age
    assert "cdc/suicide/9j2v-jamp/sex=male/race=white/age_adjusted" in ids   # sex x race
    assert len(entries) == 3                                                 # overlap 45-64 dropped


def test_vsrr_column_melt():
    entries = C.build_vsrr()
    assert len(entries) == 18                                    # 3 causes x 2 rates x 3 geo
    e = next(x for x in entries
             if x["concept"] == "suicide" and x["facets"].get("sex") == "male"
             and x["facets"]["rate_type"] == "age_adjusted")
    assert e["select"] == "year_and_quarter AS year, rate_sex_male AS value"
    assert "cause_of_death='Suicide'" in e["where"]
    assert e["provisional"] is True


def test_group_soql_backticks_reserved_and_adds_location():
    sel, where = C.group_soql(_spec("suicide", "w26f-tf3h"))
    assert "`group`" in sel
    sel2, _ = C.group_soql(_spec("chronic_liver_mortality", "hksd-2xuw"))
    assert sel2.startswith("locationabbr")               # location prepended for stratified+location


def test_le_snapshot_union_recipe():
    members = {("Montana", "Total"): {
        "2018": ("a5a8-jsrq", "state", "leb", "Montana"),
        "2020": ("ss2j-8ajj", "state", "le", "Montana"),
        "2021": ("it4f-frdc", "area", "leb", "Montana"),
    }}
    e = C.build_le_snapshots(members)[0]
    assert e["facets"] == {"area": "Montana", "sex": "total"}
    assert e["observation_start"] == "2018" and e["observation_end"] == "2021"
    assert [s["select"] for s in e["sources"]] == [
        "'2018' AS year, leb AS value",
        "'2020' AS year, le AS value",     # 2020 uses the `le` column, not `leb`
        "'2021' AS year, leb AS value",
    ]
    assert e["sources"][2]["where"] == "area='Montana' AND sex='Total'"   # 2021 uses `area`
