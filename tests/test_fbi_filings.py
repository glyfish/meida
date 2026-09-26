"""The filing rule, on the two FBI routes besides arrests.

``tests/test_fbi_arrests.py`` pins the defect at the size it was found: an
agency whose arrest series advertised 501 of 501 months filled across
twenty-five years in which it filed nothing, because the CDE writes a missing
return as ``0`` and the mapper's "filled" test was ``is not None``. The same
zero is in the other two payloads, so the same rule is applied there and pinned
here.

``summarized`` is the worse of the two, because the hole is real and dated:
Washington's homicide series reports zero for every month of 1997 and for
January to July 2021 while the department was converting to NIBRS, and its
state's coverage -- the only coverage an agency payload carries -- sits at 100%
throughout. ``pe`` is the milder one, and the exposure is structural rather
than observed: male and female are summed, two zeros sum to a zero, and a zero
is a year *present* to the gap notice that is the only thing on that response
saying a return is missing.

Everything here is hand-built. Nothing in this module reaches the network or
reads a real ``DATA_GOV_KEY``.
"""
from __future__ import annotations

import sys

from clients.models.fbi import (
    FbiEmploymentResponse, FbiObservation, FbiOffenseResponse, FbiSeries,
)
from mcp_server.responses.fbi import (
    PARTIAL_FLOOR, UNFILED_RUN_FLOOR,
    from_employment_response, from_offense_response,
)
from notebook_modules import load

filing = load("fbi/utils", "filing")


# --- Fixtures ----------------------------------------------------------------


def _months(first: str, count: int) -> list[str]:
    """``count`` consecutive ``MM-YYYY`` periods starting at *first*."""
    month, year = (int(part) for part in first.split("-"))
    periods: list[str] = []
    for _ in range(count):
        periods.append(f"{month:02d}-{year}")
        month, year = (month % 12 + 1, year + (month == 12))
    return periods


def _offense_response(offenses: list[float | None], clearances: list[float | None] | None = None,
                      *, first: str = "01-2018", scope: str = "DCMPD0000",
                      geography: str = "Washington Police Department",
                      state: str = "District of Columbia",
                      coverage: float = 100.0,
                      vintage: str = "09/2026") -> FbiOffenseResponse:
    """One hand-built ``summarized`` payload for an agency.

    The coverage series is the *state's*, which is all an agency payload
    carries, and it is flat: the situation in which the coverage floor can say
    nothing at all about the agency that was asked for.
    """
    periods = _months(first, len(offenses))
    clearances = offenses if clearances is None else clearances

    def points(source):
        return [FbiObservation(period=period, value=value)
                for period, value in zip(periods, source)]

    return FbiOffenseResponse(
        offense="homicide", scope=scope, max_data_date=vintage, series=[
            FbiSeries(label=f"{geography} Offenses", scope=scope, measure="offenses",
                      unit="count", observations=points(offenses)),
            FbiSeries(label=f"{geography} Clearances", scope=scope, measure="clearances",
                      unit="count", observations=points(clearances)),
            FbiSeries(label=state, scope=scope, measure="value", unit="percent",
                      observations=points([coverage] * len(offenses))),
            FbiSeries(label=geography, scope=scope, measure="value", unit="people",
                      observations=points([680_000.0] * len(offenses))),
        ])


def _employment_response(male: list[float | None], female: list[float | None],
                         *, first: int = 1985, measure: str = "officers",
                         ori: str = "DCMPD0000") -> FbiEmploymentResponse:
    """``pe/agency`` as it arrives: the two sexes apart, annual, plus a denominator."""
    years = [str(first + i) for i in range(len(male))]

    def points(source):
        return [FbiObservation(period=year, value=value)
                for year, value in zip(years, source)]

    label = measure.capitalize()
    return FbiEmploymentResponse(ori=ori, max_data_date="09/2026", series=[
        FbiSeries(label=f"Male {label}", scope=ori, measure=measure, unit="count",
                  observations=points(male)),
        FbiSeries(label=f"Female {label}", scope=ori, measure=measure, unit="count",
                  observations=points(female)),
        FbiSeries(label="Participated Population", scope=ori, measure="value",
                  unit="people", observations=points([680_000.0] * len(male))),
    ])


def _values(series) -> list[float | None]:
    return [o.value for o in series.observations]


def _notice(series, fragment: str) -> str:
    return next(n for n in series.notices if fragment in n)


def _has(series, fragment: str) -> bool:
    return any(fragment in n for n in series.notices)


# --- The rule's two halves ---------------------------------------------------


def test_the_constants_are_the_notebooks():
    """The tools and ``notebooks/fbi`` must call the same months unfiled.

    If these drift, a notebook's chart and the tool's notices disagree about
    which months exist, which is worse than either rule on its own. The floor
    and the level window are the rule, and they must agree exactly.

    The one deliberate difference is the minimum run length, and it is pinned
    here rather than left to drift: ``utils/filing.py`` keeps ``min_run=2``
    because a lone blank month in a chart is a month, while the tool dropped it
    so that a single skipped period at a large agency -- a 3,000-officer
    department filing no employment return for one year -- meets the mass floor
    on its own. The two agree on every run of two or more.
    """
    assert (UNFILED_RUN_FLOOR, PARTIAL_FLOOR) == (filing.UNFILED_RUN_FLOOR,
                                                  filing.PARTIAL_FLOOR) == (25.0, 25.0)
    assert not hasattr(sys.modules["mcp_server.responses.fbi"], "UNFILED_MIN_RUN")
    assert filing.UNFILED_MIN_RUN == 2


# --- summarized: offences and clearances -------------------------------------


def test_the_2021_conversion_gap_is_read_as_a_gap_not_as_a_peaceful_year():
    """Washington filed no homicide from January to July 2021.

    Those seven months come back as 0, and a twelve-month sum over 2021 that
    reads them as months makes five filed months look like a year -- the
    arithmetic the notebooks call out, and the reason this rule exists.
    """
    monthly = [14.0, 11.0, 16.0, 13.0, 15.0, 18.0, 17.0, 16.0, 14.0, 13.0, 15.0, 12.0]
    offenses = monthly * 3 + [0.0] * 7 + monthly[7:] + monthly * 2
    series = from_offense_response(
        _offense_response(offenses), offense="homicide", scope="DCMPD0000")

    assert _values(series)[36:43] == [None] * 7
    notice = _notice(series, "record no filing")
    assert "7 of the 72 months" in notice
    assert "01-2021..07-2021" in notice
    # Everything either side keeps its value, zero included where it is one.
    assert _values(series)[35] == 12.0 and _values(series)[43] == 16.0


def test_the_agency_payload_carries_only_its_states_coverage_and_it_is_perfect():
    """Why ``summarized`` needed the same fix as the arrest route.

    The coverage floor is the response's only other hole detector, and at
    agency scope the percentage belongs to the state. The District reported
    100% of its population through every month the department skipped.
    """
    offenses = [15.0] * 24 + [0.0] * 12 + [15.0] * 24
    series = from_offense_response(
        _offense_response(offenses), offense="homicide", scope="DCMPD0000")

    assert series.coverage.label == "District of Columbia"
    assert series.coverage_min_percent == 100.0
    assert not _has(series, "Coverage bottoms out")
    assert _has(series, "record no filing")


def test_clearances_are_read_as_their_own_series():
    """Both measures come out of one payload and each is judged on its own.

    A department can file its offences and not its clearances -- New York filed
    no clearance at all from 2002 to 2012 while its offence counts ran normally
    -- so the selection has to carry its own verdict.
    """
    offenses = [15.0] * 60
    clearances = [8.0] * 24 + [0.0] * 12 + [8.0] * 24
    payload = _offense_response(offenses, clearances)

    filed = from_offense_response(payload, offense="homicide", scope="DCMPD0000",
                                  measure="offenses")
    missing = from_offense_response(payload, offense="homicide", scope="DCMPD0000",
                                    measure="clearances")

    assert not _has(filed, "record no filing")
    assert _values(filed) == offenses
    assert _has(missing, "record no filing")
    assert _values(missing)[24:36] == [None] * 12


def test_a_small_department_keeps_its_quiet_months():
    """Three homicides a month, and two zeros in a row is an ordinary quarter.

    The mass floor is the whole difference between this and the case above,
    and the cost is stated rather than hidden: a genuine two-month gap in a
    series this small now reads as a quiet stretch, and nothing in the payload
    can tell them apart.
    """
    offenses = [3.0, 2.0, 4.0, 0.0, 0.0, 3.0, 5.0, 2.0, 4.0, 1.0, 3.0, 2.0] * 3
    series = from_offense_response(
        _offense_response(offenses, geography="Sleepy Hollow Police Department",
                          state="New York"),
        offense="homicide", scope="NY0000000")

    assert not _has(series, "record no filing")
    assert _values(series) == offenses
    assert (series.observation_start, series.observation_end) == ("01-2018", "12-2020")


def test_the_vintage_month_drops_out_of_the_span():
    """A window runs to the current month; the current month has not arrived.

    The CDE pads it with 0 rather than leaving it out, so ``observation_end``
    named a month with nothing in it. What makes the month padding is that the
    programme's own data stops before it -- ``max_data_date`` -- and not the
    zero, which is why the vintage here is November and the window ends in
    December.
    """
    offenses = [15.0] * 35 + [0.0]
    series = from_offense_response(
        _offense_response(offenses, vintage="11/2020"),
        offense="homicide", scope="DCMPD0000")

    assert series.observation_end == "11-2020"
    assert _values(series)[-1] is None
    notice = _notice(series, "past the last filing")
    assert "1 month past the last filing (12-2020)" in notice


def test_a_lone_trailing_zero_inside_the_data_is_kept_as_a_filing():
    """The same shape, with the data running on: not padding, and not a gap.

    A window that ends on a zero while the programme has months behind it is not
    being padded -- the department filed that month, or the window simply stopped
    there. One blank month does not reach the mass floor at this level, so it
    keeps its value and nothing claims the data stops. Deleting it was the
    defect: San Francisco has thirty-nine genuine zero runs in its homicide
    clearances, and a window ending on any of them lost the run.
    """
    offenses = [15.0] * 35 + [0.0]
    series = from_offense_response(
        _offense_response(offenses, vintage="09/2026"),
        offense="homicide", scope="DCMPD0000")

    assert _values(series)[-1] == 0.0
    assert series.observation_end == "12-2020"
    assert not _has(series, "past the last filing")


def test_a_partial_last_month_keeps_its_value_and_gets_a_notice():
    """Flagged, not nulled: a small filing is still a filing.

    The choice is deliberate and it is the opposite of the one made for an
    unfiled month. There is evidence a return was sent here -- a number came
    back -- so the response keeps it and says it is incomplete, rather than
    deleting a figure that may be right.
    """
    offenses = [150.0] * 35 + [4.0]
    series = from_offense_response(
        _offense_response(offenses), offense="homicide", scope="DCMPD0000")

    assert series.observations[-1].value == 4.0
    assert series.observation_end == "12-2020"
    notice = _notice(series, "still filling")
    assert "12-2020 carries 4 offences against a normal 150" in notice
    assert "drop it before comparing" in notice


def test_a_flat_low_series_gets_no_tail_verdict():
    """``PARTIAL_FLOOR``: a village reporting one against a normal two proves nothing."""
    offenses = [2.0, 3.0, 1.0, 2.0, 4.0, 2.0] * 6 + [0.0, 1.0]
    series = from_offense_response(
        _offense_response(offenses, geography="Sleepy Hollow Police Department",
                          state="New York"),
        offense="homicide", scope="NY0000000")

    assert not _has(series, "still filling")
    assert _values(series)[-2:] == [0.0, 1.0]


# --- pe: employment ----------------------------------------------------------


def test_a_run_of_zero_years_is_a_department_that_did_not_file():
    """Male 0 plus female 0 is a total of 0, and a 0 is a year present.

    That is enough to suppress the gap notice, which is the only thing on this
    response that says a return is missing, and to stretch the span across the
    years it covers.
    """
    male = [2000.0] * 12 + [0.0] * 3 + [2100.0] * 25
    female = [900.0] * 12 + [0.0] * 3 + [950.0] * 25
    series = from_employment_response(
        _employment_response(male, female), ori="DCMPD0000")

    assert dict(zip([o.period for o in series.observations], _values(series)))["1997"] is None
    assert _values(series)[12:15] == [None] * 3
    notice = _notice(series, "with no return")
    assert "3 years between 1985 and 2024 with no return (1997, 1998, 1999)" in notice
    assert "3 of them arrived as 0 rather than as an absence" in notice


def test_an_agency_that_employs_no_civilians_keeps_its_zeros():
    """No filing anywhere means no level, and no level means no verdict.

    A department of sworn officers and no civilian staff reports zero civilians
    every year, truthfully. The mass test cannot clear a floor against a level
    of zero, so the years stand.
    """
    series = from_employment_response(
        _employment_response([0.0] * 40, [0.0] * 40, measure="civilians"),
        ori="DCMPD0000", measure="civilians")

    assert _values(series) == [0.0] * 40
    assert (series.observation_start, series.observation_end) == ("1985", "2024")
    assert series.notices == []


def test_a_year_padded_past_the_last_return_leaves_the_span():
    """The current year's return has not been filed, and arrives as 0."""
    male = [2000.0] * 40 + [0.0]
    female = [900.0] * 40 + [0.0]
    series = from_employment_response(
        _employment_response(male, female), ori="DCMPD0000")

    assert series.observation_end == "2024"
    assert _values(series)[-1] is None
    assert "1 year past the last return (2025)" in _notice(series, "past the last return")


def test_an_absent_year_still_reads_as_an_absent_year():
    """The gap notice that was already here keeps working unchanged.

    A year missing from the payload altogether is the honest spelling of the
    same fact, and it must not start being described as a zero.
    """
    male = [2000.0] * 12 + [None] * 3 + [2100.0] * 25
    female = [900.0] * 12 + [None] * 3 + [950.0] * 25
    series = from_employment_response(
        _employment_response(male, female), ori="DCMPD0000")

    notice = _notice(series, "with no return")
    assert "3 years between 1985 and 2024 with no return (1997, 1998, 1999)" in notice
    assert "arrived as 0" not in notice


def test_an_agency_with_nothing_at_all_still_maps_to_a_notice():
    """The mappers stay total: no filings is a record with an explanation."""
    series = from_employment_response(
        _employment_response([None] * 5, [None] * 5), ori="WY0000000")

    assert series.observations == []
    assert "No officers reported for WY0000000" in series.notices[0]
