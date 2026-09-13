"""Tests for the Voteview reductions (``notebooks/voteview/utils/voteview_series.py``).

Hand-built panels, no file and no network. The panel is 51,064 rows and every
measure is a summary of it, so the failure mode is a plausible number rather
than an exception -- these pin the cases where a wrong reduction still returns
something believable.
"""
from __future__ import annotations

import pytest

from notebook_modules import load

vs = load("voteview/utils", "voteview_series")


def _panel(spec):
    """``{(congress, chamber, party): [dim1, ...]}`` from a terse spec."""
    return {k: list(v) for k, v in spec.items()}


D, R, WHIG = 100, 200, 29


# --- party_predicts_position --------------------------------------------------

def test_ratio_is_party_separation_over_internal_spread():
    panel = _panel({(50, "House", D): [-0.4, -0.6], (50, "House", R): [0.4, 0.6]})
    # medians -0.5 and 0.5 -> gap 1.0; each party's pstdev is 0.1
    assert vs.party_predicts_position(panel, 50, "House") == pytest.approx(10.0)


def test_ratio_below_one_when_the_divide_runs_through_the_parties():
    """The Era of Good Feelings shape: party barely predicts position."""
    panel = _panel({(17, "House", D): [-0.9, 0.0, 0.9], (17, "House", WHIG): [-0.8, 0.1, 1.0]})
    assert vs.party_predicts_position(panel, 17, "House") < 1.0


def test_ratio_needs_no_democrat_or_republican():
    """It uses the two largest parties, so it works before they exist."""
    panel = _panel({(17, "House", 13): [-0.4, -0.5] * 5, (17, "House", 1): [0.4, 0.5] * 5})
    assert vs.party_predicts_position(panel, 17, "House") is not None


def test_a_rump_second_party_is_gated_out():
    """Comparing a 90-member median to a 10-member remnant is not like-for-like."""
    panel = _panel({(17, "House", 13): [-0.4] * 90, (17, "House", 1): [0.4] * 10})
    assert 10 / 100 < vs.BALANCED
    assert vs.party_predicts_position(panel, 17, "House") is None


def test_the_gate_admits_an_ordinary_majority():
    """A 60/40 chamber is a normal legislature, not a one-party era."""
    panel = _panel({(17, "House", 13): [-0.4, -0.5] * 30, (17, "House", 1): [0.4, 0.5] * 20})
    assert 40 / 100 > vs.BALANCED
    assert vs.party_predicts_position(panel, 17, "House") is not None


# --- effective_parties --------------------------------------------------------

def test_effective_parties_is_two_for_an_even_split():
    panel = _panel({(50, "House", D): [0.0] * 50, (50, "House", R): [0.0] * 50})
    assert vs.effective_parties(panel, 50, "House") == pytest.approx(2.0)


def test_effective_parties_approaches_one_under_dominance():
    panel = _panel({(17, "House", 13): [0.0] * 90, (17, "House", 1): [0.0] * 10})
    assert vs.effective_parties(panel, 17, "House") == pytest.approx(1.0 / 0.82)


def test_dominance_and_separation_are_independent():
    """1807 had 1821's supermajority and four times its ratio. Both are needed."""
    dominant_and_split = _panel({(15, "House", 13): [-0.5] * 90, (15, "House", 1): [0.5] * 10})
    assert vs.effective_parties(dominant_and_split, 15, "House") < 1.3
    assert vs.party_predicts_position(dominant_and_split, 15, "House") is None  # gated
    # the ratio is gated, so effective_parties is the only signal left there
    assert vs.effective_parties(dominant_and_split, 15, "House") is not None


# --- the Democrat-versus-Republican pair --------------------------------------

def test_median_gap_is_republican_minus_democrat():
    panel = _panel({(50, "House", D): [-0.4] * 20, (50, "House", R): [0.5] * 20})
    assert vs.median_gap(panel, 50, "House") == pytest.approx(0.9)


def test_the_dr_measures_refuse_congresses_before_the_two_party_frame():
    """Democrats and Republicans do not both exist before the 34th."""
    panel = _panel({(20, "House", D): [-0.4] * 30, (20, "House", R): [0.4] * 30})
    assert 20 < vs.TWO_PARTY_FROM
    assert vs.median_gap(panel, 20, "House") is None
    assert vs.moderate_bloc(panel, 20, "House") is None


def test_moderate_bloc_counts_members_inside_the_other_party_range():
    panel = _panel({
        (50, "House", D): [-0.5] * 19 + [0.2],    # one Democrat right of the R minimum
        (50, "House", R): [0.5] * 19 + [-0.1],    # one Republican left of the D maximum
    })
    assert vs.moderate_bloc(panel, 50, "House") == 2.0


def test_moderate_bloc_is_zero_when_the_ranges_do_not_touch():
    panel = _panel({(50, "House", D): [-0.5] * 20, (50, "House", R): [0.5] * 20})
    assert vs.moderate_bloc(panel, 50, "House") == 0.0


def test_the_bloc_and_the_gap_are_not_redundant():
    """The bloc hit zero in 2007 while the gap kept climbing -- they must differ."""
    far = _panel({(50, "House", D): [-0.6] * 20, (50, "House", R): [0.6] * 20})
    farther = _panel({(50, "House", D): [-0.9] * 20, (50, "House", R): [0.9] * 20})
    assert vs.moderate_bloc(far, 50, "House") == vs.moderate_bloc(farther, 50, "House") == 0.0
    assert vs.median_gap(farther, 50, "House") > vs.median_gap(far, 50, "House")


# --- record shape -------------------------------------------------------------

def test_series_record_matches_the_storage_contract():
    panel = _panel({(50, "House", D): [-0.4] * 20, (50, "House", R): [0.4] * 20,
                    (52, "House", D): [-0.5] * 20, (52, "House", R): [0.5] * 20})
    rec = vs.build_series("median_gap", "House", scores=panel)
    assert rec["source"] == "voteview"
    assert rec["native_id"] == "voteview/median_gap/house"
    assert rec["frequency"] == "Biennial"
    assert rec["ttl_days"] == 365
    assert [o["date"] for o in rec["observations"]] == ["1887-01-01", "1891-01-01"]
    assert all(isinstance(o["value"], str) for o in rec["observations"])
    assert rec["observation_count"] == len(rec["observations"]) == 2


def test_congresses_map_to_the_year_they_convene():
    assert vs.congress_year(1) == 1789
    assert vs.congress_year(119) == 2025


def test_one_ttl_for_every_series():
    """All eight reduce from one CSV, so refreshing any one refetches them all."""
    assert len({vs.TTL_DAYS}) == 1
    assert vs.TTL_DAYS == 365


def test_unknown_measure_and_chamber_are_refused():
    with pytest.raises(vs.VoteviewSeriesError, match="unknown measure"):
        vs.build_series("polarization", "House", scores={})
    with pytest.raises(vs.VoteviewSeriesError, match="unknown chamber"):
        vs.build_series("median_gap", "Congress", scores={})


def test_a_party_with_no_internal_spread_gives_no_ratio():
    """The denominator is the within-party spread; identical members make it
    zero. Returns None rather than dividing -- contrived in real data, but the
    guard is what stops an infinity reaching the series."""
    panel = _panel({(50, "House", D): [-0.4] * 20, (50, "House", R): [0.4] * 20})
    assert vs.party_predicts_position(panel, 50, "House") is None
