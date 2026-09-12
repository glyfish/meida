"""Tests for the WONDER and NVSR series builders.

Pure-function tests over hand-built inputs, following ``test_cdc_catalog.py``:
no network, no database, no dependency on the downloaded data being present.

The two behaviours most worth pinning are the ones that fail *silently*:
the D76/D158 splice (a wrong boundary yields a plausible series) and the NVSR
Table -> (race, sex) mapping (a wrong row or table mislabels one population as
another, with nothing to flag it).
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import sys

_CDC = Path(__file__).resolve().parents[1] / "notebooks" / "cdc"
sys.path.insert(0, str(_CDC))

import nvsr_series as ns          # noqa: E402
import wonder_series as ws        # noqa: E402


# --- WONDER: stitching -------------------------------------------------------


def _rows(pairs):
    return [{"year": y, "deaths": 100, "population": 1000,
             "crude_rate": r, "age_adjusted_rate": r} for y, r in pairs]


def test_stitch_prefers_d76_through_the_splice_year():
    """D76 owns <= 2020, D158 owns after -- the overlap comes from D76."""
    d76 = _rows([(2019, 10.4), (2020, 13.1)])
    d158 = _rows([(2019, 99.9), (2020, 99.9), (2021, 14.4)])   # overlap deliberately wrong
    got = ws.stitch(d76, d158)
    assert [(r["year"], r["age_adjusted_rate"]) for r in got] == [
        (2019, 10.4), (2020, 13.1), (2021, 14.4)
    ]


def test_stitch_output_is_ascending_and_unique():
    got = ws.stitch(_rows([(2000, 1.0), (1999, 2.0)]), _rows([(2021, 3.0)]))
    years = [r["year"] for r in got]
    assert years == sorted(years) == [1999, 2000, 2021]


def test_check_overlap_flags_disagreement():
    """The splice assumes the databases agree on shared years."""
    assert ws.check_overlap(_rows([(2019, 10.4)]), _rows([(2019, 10.4)])) == []
    assert ws.check_overlap(_rows([(2019, 10.4)]), _rows([(2019, 11.0)])) == [2019]


def test_build_series_rejects_disagreeing_overlap(tmp_path):
    (tmp_path / "alcohol_D76.json").write_text(json.dumps(_rows([(2019, 10.4), (2020, 13.1)])))
    (tmp_path / "alcohol_D158.json").write_text(json.dumps(_rows([(2020, 99.9), (2021, 14.4)])))
    with pytest.raises(ws.WonderSeriesError, match="disagree"):
        ws.build_series("alcohol", data_dir=tmp_path)


def test_build_series_shape_and_string_values(tmp_path):
    (tmp_path / "alcohol_D76.json").write_text(json.dumps(_rows([(1999, 7.1), (2020, 13.1)])))
    (tmp_path / "alcohol_D158.json").write_text(json.dumps(_rows([(2020, 13.1), (2021, 14.4)])))
    rec = ws.build_series("alcohol", data_dir=tmp_path)

    assert rec["source"] == "cdc_wonder"
    assert rec["native_id"] == "cdc/alcohol_induced/wonder/national/age_adjusted"
    assert rec["frequency"] == "Annual"
    assert rec["ttl_days"] == 365
    assert rec["observation_start"] == "1999-01-01"      # annual snaps to Jan 1
    assert rec["observation_end"] == "2021-01-01"
    assert rec["observation_count"] == len(rec["observations"]) == 3
    first = rec["observations"][0]
    assert first["value"] == "7.1" and isinstance(first["value"], str)
    assert first["deaths"] == 100 and first["population"] == 1000   # extras preserved


def test_build_series_records_excluded_codes(tmp_path):
    """WONDER rejects *U03; the deviation must travel with the data."""
    (tmp_path / "suicide_D76.json").write_text(json.dumps(_rows([(2020, 13.5)])))
    (tmp_path / "suicide_D158.json").write_text(json.dumps(_rows([(2021, 14.1)])))
    (tmp_path / "_download_summary.json").write_text(json.dumps({
        "suicide": {"databases": {"D76": {"dropped_codes": ["*U03"]},
                                  "D158": {"dropped_codes": ["*U03"]}}}
    }))
    meta = ws.build_series("suicide", data_dir=tmp_path)["metadata"]["cdc_wonder"]
    assert meta["excluded_codes"] == ["*U03"]
    assert "terrorism" in meta["exclusion_note"][0]


def test_unknown_concept_raises():
    with pytest.raises(ws.WonderSeriesError, match="unknown concept"):
        ws.build_series("not_a_concept")


# --- NVSR: position-based parsing and the table mapping ----------------------


def _xlsx(tmp_path: Path, name: str, cells: dict[str, float]) -> Path:
    """Minimal .xlsx carrying the given cell references."""
    body = "".join(f'<c r="{ref}"><v>{val}</v></c>' for ref, val in cells.items())
    sheet = (
        '<?xml version="1.0"?><worksheet xmlns='
        '"http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData><row>{body}</row></sheetData></worksheet>"
    )
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return path


def test_reads_e0_from_fixed_position_not_a_label(tmp_path):
    """G4 is the value; a label-based read would find the decoy at G25."""
    p = _xlsx(tmp_path, "Table01.xlsx", {"G4": 76.3702, "G25": 56.1943})
    assert ns.life_expectancy_at_birth(p) == pytest.approx(76.3702)


def test_missing_cell_returns_none(tmp_path):
    assert ns.life_expectancy_at_birth(_xlsx(tmp_path, "Table01.xlsx", {"A1": 1.0})) is None


def test_unreadable_file_raises(tmp_path):
    bad = tmp_path / "Table01.xlsx"
    bad.write_text("not a zip")
    with pytest.raises(ns.NvsrSeriesError, match="cannot read"):
        ns.life_expectancy_at_birth(bad)


def test_national_table_map_covers_six_groups_by_three_sexes():
    assert len(ns.NATIONAL_TABLES) == 18
    assert len({r for r, _ in ns.NATIONAL_TABLES.values()}) == 6
    # spot-check the captions this mapping came from
    assert ns.NATIONAL_TABLES[1] == ("all", "both")
    assert ns.NATIONAL_TABLES[13] == ("black_nh", "both")
    assert ns.NATIONAL_TABLES[18] == ("white_nh", "female")


def test_state_table_map_excludes_the_standard_error_table():
    """{ST}4 is standard errors, so a state yields three series, not four."""
    assert set(ns.STATE_TABLES) == {1, 2, 3}
    assert 4 not in ns.STATE_TABLES


def test_verify_national_raises_when_the_parse_drifts(tmp_path):
    """The guard against reading the wrong row."""
    (tmp_path / "us" / "2021").mkdir(parents=True)
    _xlsx(tmp_path / "us" / "2021", "Table01.xlsx", {"G4": 56.1943})   # the decoy value
    with pytest.raises(ns.NvsrSeriesError, match="published 76.4"):
        ns.verify_national(tmp_path)


def test_verify_national_accepts_the_published_value(tmp_path):
    (tmp_path / "us" / "2021").mkdir(parents=True)
    _xlsx(tmp_path / "us" / "2021", "Table01.xlsx", {"G4": 76.3702})
    assert ns.verify_national(tmp_path) == {2021: pytest.approx(76.3702)}


def test_build_national_groups_years_into_one_series(tmp_path):
    for year, value in [(2021, 76.3702), (2022, 77.4569)]:
        d = tmp_path / "us" / str(year)
        d.mkdir(parents=True)
        _xlsx(d, "Table01.xlsx", {"G4": value})
    recs = ns.build_national(tmp_path)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["native_id"] == "cdc/life_expectancy/nvsr/race=all/sex=both"
    assert [o["date"] for o in rec["observations"]] == ["2021-01-01", "2022-01-01"]
    assert rec["observations"][0]["value"] == "76.3702"      # full precision, as a string


def _state_year(tmp_path, year, values):
    """Write one state-year: ``values`` is ``{postal: (both, male, female)}``."""
    d = tmp_path / "state" / str(year)
    d.mkdir(parents=True, exist_ok=True)
    for state, (both, male, female) in values.items():
        for n, val in [(1, both), (2, male), (3, female), (4, 0.05)]:
            _xlsx(d, f"{state}{n}.xlsx", {"G4": val})
    return d


def test_verify_state_accepts_a_well_formed_year(tmp_path):
    _state_year(tmp_path, 2022, {"HI": (79.9, 77.4, 82.2), "MS": (70.9, 67.6, 74.4)})
    assert ns.verify_state(tmp_path) == {2022: 2}


def test_verify_state_catches_a_shuffled_sex_mapping(tmp_path):
    """{ST}1/2/3 carry no labels, so a swap is silent -- except in the ordering."""
    _state_year(tmp_path, 2022, {"HI": (79.9, 82.2, 77.4)})    # male and female swapped
    with pytest.raises(ns.NvsrSeriesError, match="female > both > male"):
        ns.verify_state(tmp_path)


def test_verify_state_catches_a_misread_cell(tmp_path):
    _state_year(tmp_path, 2022, {"HI": (79.9, 77.4, 82.2)})
    _xlsx(tmp_path / "state" / "2022", "HI1.xlsx", {"G4": 0.24})    # the SE table's value
    with pytest.raises(ns.NvsrSeriesError, match="outside 60-95"):
        ns.verify_state(tmp_path)


def test_verify_state_requires_all_three_life_tables(tmp_path):
    d = tmp_path / "state" / "2022"
    d.mkdir(parents=True)
    _xlsx(d, "HI1.xlsx", {"G4": 79.9})
    with pytest.raises(ns.NvsrSeriesError, match="missing female, male"):
        ns.verify_state(tmp_path)


def test_verify_state_brackets_the_national_value(tmp_path):
    """A systematic offset keeps the ordering but moves the states off the nation."""
    _state_year(tmp_path, 2021, {"HI": (79.9, 77.4, 82.2), "MS": (77.9, 75.6, 80.4)})
    (tmp_path / "us" / "2021").mkdir(parents=True)
    _xlsx(tmp_path / "us" / "2021", "Table01.xlsx", {"G4": 76.3702})
    with pytest.raises(ns.NvsrSeriesError, match="outside the state range"):
        ns.verify_state(tmp_path)


def test_build_state_skips_the_standard_error_table(tmp_path):
    d = tmp_path / "state" / "2022"
    d.mkdir(parents=True)
    for n, val in [(1, 75.8), (2, 73.6), (3, 78.2), (4, 0.05)]:   # AK4 = standard errors
        _xlsx(d, f"AK{n}.xlsx", {"G4": val})
    recs = ns.build_state(tmp_path)
    assert len(recs) == 3
    assert {r["metadata"]["cdc_nvsr"]["sex"][0] for r in recs} == {"both", "male", "female"}
    assert all("0.05" not in json.dumps(r["observations"]) for r in recs)


# --- catalog entries and description bucketing -------------------------------

import catalog_timeseries as ct    # noqa: E402
import descriptions as desc        # noqa: E402


def test_bucket_key_ignores_facet_values(): 
    """Series differing only in facet VALUES share a bucket; names matter."""
    a = {"concept": "suicide", "unit": "per 100,000", "facets": {"sex": "male", "age": "15-19"}}
    b = {"concept": "suicide", "unit": "per 100,000", "facets": {"sex": "female", "age": "25-34"}}
    c = {"concept": "suicide", "unit": "per 100,000", "facets": {"sex": "male"}}
    assert desc.bucket_key("g", a) == desc.bucket_key("g", b)
    assert desc.bucket_key("g", a) != desc.bucket_key("g", c)   # different facet shape
    assert desc.bucket_key("g", a) != desc.bucket_key("other", a)


def test_buckets_collects_examples_and_widest_coverage():
    catalog = {"g": [
        {"concept": "suicide", "unit": "u", "facets": {"sex": "male"},
         "title": "t1", "observation_start": "2000", "observation_end": "2010"},
        {"concept": "suicide", "unit": "u", "facets": {"sex": "female"},
         "title": "t2", "observation_start": "1999", "observation_end": "2024"},
    ]}
    (ctx,) = desc.buckets(catalog).values()
    assert ctx["series_count"] == 2
    assert sorted(ctx["facet_examples"]["sex"]) == ["female", "male"]
    assert (ctx["observation_start"], ctx["observation_end"]) == ("1999", "2024")


def test_wonder_catalog_entry_carries_provenance_and_retrieval(tmp_path):
    wdir = tmp_path / "wonder"
    wdir.mkdir()
    (wdir / "alcohol_D76.json").write_text(json.dumps(_rows([(1999, 7.1), (2020, 13.1)])))
    (wdir / "alcohol_D158.json").write_text(json.dumps(_rows([(2020, 13.1), (2021, 14.4)])))

    (entry,) = [e for e in ct.wonder_entries(data_dir=tmp_path)
                if e["concept"] == "alcohol_induced"]
    # provenance: which database supplied which stretch, and the file to regenerate from
    assert [s["kind"] for s in entry["sources"]] == ["wonder", "wonder"]
    assert entry["sources"][0]["years"] == {"from": 1999, "to": 2020}
    assert entry["sources"][1]["years"]["from"] == 2021
    # retrieval: which tool serves it
    assert entry["retrieval"]["tool"] == "timeseries_source_data"
    assert entry["retrieval"]["source"] == "cdc_wonder"
    assert entry["retrieval"]["native_id"] == entry["series_id"]
    # catalog bounds are bare years, matching the Socrata entries
    assert entry["observation_start"] == "1999" and entry["observation_end"] == "2021"
