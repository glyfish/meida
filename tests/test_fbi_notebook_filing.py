"""Tests for the notebook filing rule (``notebooks/fbi/utils/filing.py``).

No network and no MCP server: every case is a hand-built array standing for a
shape measured in the real series, named in the test.

What is pinned is the decisions, because each of them changes a published
figure without raising anything:

* a run of blanks is a gap only where the filings it swallowed reach the floor
  -- San Francisco's two quiet clearance months are not a gap, Washington's two
  at a median of 19 are;
* a part-filing is a month under a share of the level around it, and only where
  that level clears a floor;
* the filing after a gap may be carrying the gap;
* where a whole neighbourhood is blank the level falls back on the series'
  own median filing, or nothing could be weighed at all;
* a null and a zero are the same fact, because the CDE spells a missing return
  both ways on different routes;
* a window holding an unreadable month is dropped, not summed as eleven;
* and for arrests, a token is a blank, the part-filing line is a third rather
  than a tenth, and a lump is a lump whether or not a gap precedes it.

The last test is the reconciliation with ``utils/mcp.py``'s older
``unfiled()``, which ``mcp.ipynb`` still uses: it shows the shape that pair
passes and this rule takes.
"""
from __future__ import annotations

import numpy
import pytest

from notebook_modules import load

filing = load("fbi/utils", "filing")
mcp = load("fbi/utils", "mcp")


# --- Fixtures ----------------------------------------------------------------


def _payload(values: dict[str, float | None], **blocks: dict[str, float | None]) -> dict:
    """A tool response carrying *values*, and a context block per keyword."""
    return {
        "observations": [{"period": period, "value": value} for period, value in values.items()],
        **{name: {"label": "x", "unit": "y",
                  "observations": [{"period": period, "value": value}
                                   for period, value in block.items()]}
           for name, block in blocks.items()},
    }


def _series(*runs: tuple[float | None, int]) -> numpy.ndarray:
    """``(value, repeats)`` pairs as one array; ``None`` becomes NaN."""
    out: list[float] = []
    for value, repeats in runs:
        out.extend([numpy.nan if value is None else float(value)] * repeats)
    return numpy.array(out)


# --- Reading a response ------------------------------------------------------


def test_monthly_sorts_on_the_parsed_date_and_nans_a_null() -> None:
    """'MM-YYYY' sorts as text into all the Januaries; a window needs date order."""
    dates, values = filing.monthly(_payload({"12-1999": 3.0, "01-2000": None, "02-2000": 5.0}))
    assert [f"{date:%Y-%m}" for date in dates] == ["1999-12", "2000-01", "2000-02"]
    assert values[0] == 3.0 and numpy.isnan(values[1]) and values[2] == 5.0


def test_context_lands_on_the_series_own_months_and_nans_the_rest() -> None:
    """A context block is aligned by period, not by position, and may be short."""
    payload = _payload({"01-2000": 1.0, "02-2000": 2.0, "03-2000": 3.0},
                       population={"03-2000": 900.0, "01-2000": 800.0, "02-2000": None})
    dates, _ = filing.monthly(payload)
    population = filing.context(payload, "population", dates)
    assert population[0] == 800.0 and numpy.isnan(population[1]) and population[2] == 900.0


def test_context_is_nan_throughout_where_the_response_carries_no_block() -> None:
    """An agency payload carries no coverage of its own, and None is not a dict."""
    payload = _payload({"01-2000": 1.0})
    payload["coverage"] = None
    dates, _ = filing.monthly(payload)
    assert numpy.isnan(filing.context(payload, "coverage", dates)).all()


# --- The level ---------------------------------------------------------------


def test_local_median_is_centred_and_ignores_blanks() -> None:
    """The months after a date are as much evidence of its level as the ones before."""
    values = _series((0.0, 12), (100.0, 13))
    median = filing.local_median(values)
    assert median[0] == 100.0                      # blanks pass no vote
    assert (median > 0).all()


def test_local_median_is_zero_where_the_whole_neighbourhood_is_blank() -> None:
    """New York filed no clearance from 2002 to 2012: the window offers no level."""
    values = _series((100.0, 6), (0.0, 40), (100.0, 6))
    assert filing.local_median(values)[23] == 0.0


def test_surrounding_leaves_the_month_out_and_falls_back_on_the_typical_filing() -> None:
    """Washington's 1992-1995: eleven blanks and a December, four years running.

    ``local_median`` counts the month itself, so in that stretch the median is
    a December and no December exceeds it. ``surrounding`` leaves it out, and
    where fewer than six other filings remain it takes the series' own typical
    filing instead -- which is the only reason those Decembers can be measured.
    """
    values = _series((5_000.0, 24), (0.0, 11), (60_000.0, 1), (0.0, 11), (60_000.0, 1))
    level = filing.surrounding(values, typical=5_000.0)
    assert level[35] == 5_000.0                    # the December, judged by the series
    assert filing.local_median(values)[35] == 60_000.0      # itself, as a lump would be
    assert level[12] == 5_000.0                    # an ordinary month keeps its own level


# --- The three tests ---------------------------------------------------------


def test_a_run_of_blanks_is_a_gap_where_it_swallowed_enough() -> None:
    """Washington's thinnest real gap: two blank months at a median of 19."""
    values = _series((19.0, 12), (0.0, 2), (19.0, 12))
    flagged = filing.unreadable(values)
    assert list(numpy.flatnonzero(flagged)) == [12, 13]


def test_two_quiet_months_in_a_small_series_are_not_a_gap() -> None:
    """San Francisco clears two or three homicides a month; two zeros is a quarter.

    Unfloored, the length test alone voids the twenty-four windows those two
    months sit in, among them a year every month of which was filed.
    """
    values = _series((3.0, 12), (0.0, 2), (3.0, 12))
    assert not filing.unreadable(values).any()
    assert filing.unreadable(values, run_floor=0.0)[12:14].all()


def test_a_part_filing_is_taken_where_the_level_clears_the_floor() -> None:
    """New York's 2021 assault series: single figures against a normal 2,900."""
    values = _series((2_900.0, 12), (4.0, 1), (2_900.0, 12))
    assert filing.unreadable(values)[12]


def test_a_low_month_in_a_small_series_is_kept() -> None:
    """The same shape under the floor is an ordinary month, not a part-filing."""
    values = _series((20.0, 12), (1.0, 1), (20.0, 12))
    assert not filing.unreadable(values).any()


def test_the_filing_after_a_gap_is_taken_when_it_carries_the_gap() -> None:
    """Washington's December 1997 holds the whole year at 301 against a normal 22."""
    values = _series((22.0, 12), (0.0, 11), (301.0, 1), (22.0, 12))
    flagged = filing.unreadable(values)
    assert flagged[23]                                     # the December
    assert flagged[12:23].all()                            # and the year it holds
    assert not flagged[24:].any()


def test_an_ordinary_filing_after_a_gap_is_kept() -> None:
    """January 2022 is ordinary in the three cities that lost 2021, and that is
    the month the whole 2021 question turns on."""
    values = _series((22.0, 12), (0.0, 7), (22.0, 12))
    assert not filing.unreadable(values)[19]


def test_a_run_where_nothing_was_filed_is_weighed_against_the_series_median() -> None:
    """A twenty-year hole has no local level, so the series' own filing stands in."""
    values = _series((15_000.0, 12), (0.0, 240), (15_000.0, 12))
    assert filing.unreadable(values)[12:252].all()


def test_a_trailing_run_is_closed_at_the_end_of_the_series() -> None:
    """San Francisco's arrests stop in December 2023 and the window runs on."""
    values = _series((1_500.0, 24), (0.0, 12))
    assert filing.unreadable(values)[24:].all()


def test_a_null_and_a_zero_are_the_same_blank() -> None:
    """New York and Washington report 0 for 2021, Los Angeles and San Francisco null."""
    zeros = _series((200.0, 12), (0.0, 7), (200.0, 12))
    nulls = _series((200.0, 12), (None, 7), (200.0, 12))
    assert (filing.unreadable(zeros) == filing.unreadable(nulls)).all()


def test_the_defaults_are_the_constants_the_notebooks_print() -> None:
    """Both notebooks print the rule they ran with, from these names."""
    values = _series((2_900.0, 12), (0.0, 2), (2_900.0, 12))
    assert (filing.unreadable(values) == filing.unreadable(
        values, min_run=filing.UNFILED_MIN_RUN, share=filing.PARTIAL_SHARE,
        floor=filing.PARTIAL_FLOOR, run_floor=filing.UNFILED_RUN_FLOOR,
        catch_up=filing.CATCH_UP)).all()


# --- Windows -----------------------------------------------------------------


def test_trailing_sum_waits_for_a_full_window() -> None:
    values = _series((1.0, 13))
    out = filing.trailing_sum(values)
    assert numpy.isnan(out[:11]).all() and out[11] == 12.0 and out[12] == 12.0


def test_a_window_holding_an_unreadable_month_is_dropped_not_summed() -> None:
    """Eleven months summed as though they were twelve is the error the rule is for."""
    values = _series((10.0, 6), (None, 1), (10.0, 17))
    out = filing.trailing_sum(values)
    assert numpy.isnan(out[11:18]).all()
    assert out[18] == 120.0


# --- The arrest additions ----------------------------------------------------


def test_a_token_filing_is_read_as_the_gap_it_sits_in() -> None:
    """New York files one arrest in September 2017, inside a twenty-year hole.

    Left as a filing it cuts the run in two and ends the first half there; read
    as the blank it is, the run is one run.
    """
    values = _series((15_000.0, 12), (0.0, 100), (1.0, 1), (0.0, 100), (15_000.0, 12))
    taken = filing.arrest_unreadable(values)
    assert taken[112]                                      # the single arrest
    assert taken[12:212].all()                             # and one run around it


def test_an_arrest_part_filing_is_taken_at_a_third_where_a_tenth_keeps_it() -> None:
    """Washington's 1989: eleven months of 579-902 under local medians of 4,301."""
    values = _series((4_500.0, 12), (700.0, 11), (62_900.0, 1), (4_500.0, 12))
    assert filing.arrest_unreadable(values)[12:23].all()
    assert not filing.unreadable(values)[12:23].any()      # a tenth keeps them all


def test_a_lump_is_taken_with_no_gap_before_it() -> None:
    """Washington's 1989 December sits on filings, not on blanks, so no catch-up
    test can reach it."""
    values = _series((4_500.0, 24), (62_900.0, 1), (4_500.0, 24))
    assert filing.arrest_unreadable(values)[24]
    assert not filing.unreadable(values)[24]


def test_an_ordinary_heavy_month_is_kept() -> None:
    """A December at twice the level around it is in every trailing year anyway."""
    values = _series((4_500.0, 24), (9_000.0, 1), (4_500.0, 24))
    assert not filing.arrest_unreadable(values)[24]


def test_the_arrest_rule_reads_a_null_and_a_zero_alike_too() -> None:
    zeros = _series((15_000.0, 12), (0.0, 12), (15_000.0, 12))
    nulls = _series((15_000.0, 12), (None, 12), (15_000.0, 12))
    assert (filing.arrest_unreadable(zeros) == filing.arrest_unreadable(nulls)).all()


# --- The older pair in utils/mcp.py ------------------------------------------


def test_the_older_unfiled_passes_the_part_filing_this_rule_takes() -> None:
    """``utils/mcp.py``'s pair carries the run test alone, and ``mcp.ipynb`` uses it.

    New York's 2021 aggravated assault series reads single figures against a
    normal month of about 2,900. No test on zeros catches that, so the older
    pair sums it as a year. This rule takes the months whose surroundings still
    offer a level to measure them against -- the first of the thin ones, before
    the window fills with thin months -- and one taken month is enough to drop
    every window that holds it.
    """
    filed = {f"{month:02d}-2020": 2_900.0 for month in range(1, 13)}
    thin = {f"{month:02d}-2021": value
            for month, value in enumerate([1, 2, 4, 1, 6, 3, 4, 0, 3, 4, 2, 4], start=1)}
    points = {**filed, **thin}

    assert mcp.unfiled(points) == set()                    # nothing but one zero month
    assert "12-2021" in mcp.rolling_12(points)             # so the thin year is summed

    values = numpy.array([points[period] for period in
                          [f"{m:02d}-{y}" for y in (2020, 2021) for m in range(1, 13)]])
    taken = filing.unreadable(values)
    assert taken[12:14].all()
    assert numpy.isnan(filing.trailing_sum(numpy.where(taken, numpy.nan, values))[-1])


@pytest.mark.parametrize("shape", [
    _series((0.0, 24)),                                    # nothing filed at all
    _series((None, 24)),
    _series((5.0, 1)),                                     # one month
])
def test_the_rule_survives_a_series_with_nothing_to_measure(shape: numpy.ndarray) -> None:
    """A scope that filed nothing must not raise; it has no readable window."""
    assert filing.unreadable(shape).shape == shape.shape
    assert filing.arrest_unreadable(shape).shape == shape.shape
