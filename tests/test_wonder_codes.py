"""Tests for the reconstructed WONDER code sets (``notebooks/cdc/wonder_codes.py``).

These sets were lost -- the original pull ran from a script that is gone, and
the cached JSON holds results rather than queries. What remained was a code
*count* per concept in ``_download_summary.json``, so the count check below is
the offline half of the reconstruction; :func:`verify_against_cache` is the
other half and needs a throttled query, so it is not exercised here.

The count check is weak on its own -- two different 125-code sets both pass --
but it is what catches an edit that quietly changes a definition, which is the
failure these guard against day to day.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "notebooks" / "cdc"))

import wonder_codes as wc  # noqa: E402


def test_every_set_matches_the_original_pulls_count():
    """The recorded counts are the only surviving evidence of the lost sets."""
    bad = {c: (mine, rec) for c, (mine, rec) in wc.check_counts().items() if mine != rec}
    assert not bad, f"rebuilt sets disagree with _download_summary.json: {bad}"


def test_no_duplicates_within_a_set():
    """A duplicate inflates the count and would mask a missing code."""
    for concept, codes in wc.CODE_SETS.items():
        assert len(codes) == len(set(codes)), concept


def test_drug_overdose_is_a_subset_of_drug_induced():
    """NVSR 70-08 defines overdose as a subcategory, not a sibling."""
    assert set(wc.DRUG_OVERDOSE) <= set(wc.DRUG_INDUCED)


def test_despair_is_a_union_not_a_sum():
    """The components overlap, so adding their rates double-counts."""
    parts = set(wc.ALCOHOL_INDUCED) | set(wc.DRUG_INDUCED) | set(wc.SUICIDE)
    assert set(wc.DESPAIR_COMPOSITE) == parts
    total = len(wc.ALCOHOL_INDUCED) + len(wc.DRUG_INDUCED) + len(wc.SUICIDE)
    assert len(wc.DESPAIR_COMPOSITE) < total, "no overlap means the union is pointless"


def test_the_overlaps_that_make_the_union_necessary():
    """Name them, so a future edit that removes one is visible."""
    assert set(wc.DRUG_INDUCED) & set(wc.SUICIDE) == {"X60", "X61", "X62", "X63", "X64"}
    assert set(wc.ALCOHOL_INDUCED) & set(wc.SUICIDE) == {"X65"}


def test_the_f_blocks_exclude_acute_intoxication_and_amnesic_syndrome():
    """.0 and .6 are not drug-induced deaths; dropping .0 is what gives 125."""
    for block in wc._DRUG_F_BLOCKS:
        assert f"{block}.0" not in wc.DRUG_INDUCED
        assert f"{block}.6" not in wc.DRUG_INDUCED
        assert f"{block}.1" in wc.DRUG_INDUCED
        assert f"{block}.9" in wc.DRUG_INDUCED


def test_compare_to_cache_flags_a_changed_death_count(tmp_path):
    (tmp_path / "chronic_liver_D76.json").write_text(
        '[{"year": 1999, "deaths": 100}, {"year": 2000, "deaths": 200}]')
    same = wc.compare_to_cache("chronic_liver",
                               [{"year": 1999, "deaths": 100}, {"year": 2000, "deaths": 200}],
                               data_dir=tmp_path)
    assert same["match"] and same["years_compared"] == 2

    off = wc.compare_to_cache("chronic_liver",
                              [{"year": 1999, "deaths": 100}, {"year": 2000, "deaths": 999}],
                              data_dir=tmp_path)
    assert not off["match"] and off["mismatches"] == {2000: (200, 999)}


def test_compare_to_cache_flags_a_missing_year(tmp_path):
    (tmp_path / "chronic_liver_D76.json").write_text(
        '[{"year": 1999, "deaths": 100}, {"year": 2000, "deaths": 200}]')
    out = wc.compare_to_cache("chronic_liver", [{"year": 1999, "deaths": 100}],
                              data_dir=tmp_path)
    assert not out["match"] and out["years_only_cached"] == [2000]


def test_a_missing_cache_file_is_an_error_not_a_pass(tmp_path):
    with pytest.raises(wc.WonderCodesError, match="no cached pull"):
        wc.cached_series("chronic_liver", data_dir=tmp_path)


def test_rejected_codes_parses_wonders_500_body():
    """The retry depends on reading which codes WONDER named."""
    msg = ("WONDER D76 HTTP 500: WONDER returned no <data-table>: Invalid "
           "'ICD-10 Codes' codes were found: 'I03, I04, I23'. Check the Finder Tool")
    assert wc.rejected_codes(msg) == ["I03", "I04", "I23"]


def test_rejected_codes_ignores_other_failures():
    """A timeout must not be mistaken for a code rejection and retried blind."""
    assert wc.rejected_codes("WONDER D76 HTTP 504: gateway timeout") == []


def test_the_sets_that_wonder_refuses_are_documented():
    """Verified live: the finder rejects every NCHS pseudo-code.

    They stay in the sets because they are part of the published definitions;
    the fetcher drops them per-request and records the deviation. Removing
    them here would make the counts disagree with the original pull and hide
    that the series omit terrorism-reclassified deaths.
    """
    assert "*U03" in wc.SUICIDE
    assert {"*U01", "*U02"} <= set(wc.HOMICIDE)
    assert "*U01.4" in wc.FIREARM


def test_every_concept_has_a_citation():
    assert set(wc.CITATIONS) == set(wc.CODE_SETS)
    assert all(wc.CITATIONS.values())
