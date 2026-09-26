"""The filing rule for CDE monthly series, and the two readers it works on.

**What the rule is for.** The FBI Crime Data Explorer reports a month nobody
filed as a number: ``0`` on most routes, ``null`` on some, and nothing in the
payload distinguishes either from a month in which nothing happened. Summing
those zeros turns five filed months into a year. Washington filed nothing from
January to July 2021 while it converted to NIBRS, and its homicide count for
that year reads 116 against the 198 of the year before -- a fall that never
happened. The MCP tools detect the worst of it and return those months as null
(``mcp_server/responses/fbi.py``), and their notices name the spans; this
module is the notebook side of the same problem, applied to the values that
arrive however they are spelled.

**The rule, in three tests.** Each reads an absence, and an absence is only
evidence where something was expected, so each carries a floor:

* *a run of blanks* -- :data:`UNFILED_MIN_RUN` or more zeros or NaNs in a row,
  where the filings the run swallowed (its length times the local level) reach
  ``run_floor``. Unfloored, the length test alone takes ten ordinary months
  from San Francisco, which clears two or three homicides a month;
* *a part-filing* -- a month under ``share`` of the median filing around it,
  where that median is at least ``floor``. New York's aggravated assault for
  2021 reads 1, 2, 4, 1, 6, 3, 4, 0, 3, 4, 2, 4 against a normal month of
  about 2,900, and no test on zeros catches that;
* *a catch-up* -- the filing straight after a gap, where it exceeds
  ``catch_up`` times the local median. Washington's December 1997 holds the
  whole year at 301 against a normal month of 22.

:func:`unreadable` is those three. :func:`arrest_unreadable` is the same three
with the three changes an all-offence arrest series needs and a homicide
series does not -- a token read as a blank, a part-filing line at a third
rather than a tenth, and a lump measured anywhere rather than only after a gap.

**Where it is explained.** ``walkthrough.ipynb`` section 2 sets out the three
tests and their floors on homicide; ``enforcement.ipynb`` section 3 sets out
the three arrest changes, prints the margin between each threshold and the
data, and lists every month each test takes. Both notebooks call this module
rather than restating it, so a threshold moved here moves in both; the tests
are ``tests/test_fbi_notebook_filing.py``.

**The older pair in** ``utils/mcp.py``. ``unfiled()`` and ``rolling_12()``
there are the first, simpler version of this rule, and they stay because
``mcp.ipynb`` uses them: that notebook walks the tools as a model sees them,
over ``{period: value}`` dictionaries, and one test is all it needs to show the
problem exists. They are superseded for analysis, and by three things
precisely. They carry the run test alone -- no part-filing, no catch-up, no
lump -- so New York's 2021 assault series passes them whole. They weigh a run
against one median for the entire series instead of the local level, so a run
in a stretch where the department filed nothing has nothing to be weighed
against. And they have no notion of a month that cannot be read for a reason
other than being blank, so a window containing a catch-up is summed as twelve
months. Nothing in this module reads a dictionary, and nothing there reads an
array; neither calls the other.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy
from matplotlib import pyplot
from matplotlib.figure import Figure
from numpy.typing import NDArray

Payload = dict[str, Any]           # one tool response, as structured content

#: Defaults of :func:`unreadable`, named so that a notebook can print the rule
#: it ran with rather than restate it.
UNFILED_MIN_RUN = 2
PARTIAL_SHARE = 0.1
PARTIAL_FLOOR = 25.0
UNFILED_RUN_FLOOR = 25.0
CATCH_UP = 2.0

#: Defaults of :func:`arrest_unreadable`, the three changes arrests need.
TOKEN_SHARE = 0.01
ARREST_PARTIAL_SHARE = 1 / 3
LUMP = 3.0


# --- Reading a response ------------------------------------------------------


def monthly(payload: Payload) -> tuple[NDArray[numpy.object_], NDArray[numpy.float64]]:
    """A CDE monthly series as (dates, values), in date order.

    'MM-YYYY' sorts as text into all the Januaries, then all the Februaries,
    which is the order the observations arrive in; sorting on the parsed date
    is what makes a window mean twelve consecutive months.
    """
    points: list[tuple[datetime, float]] = []
    for observation in payload["observations"]:
        month, year = observation["period"].split("-")
        value = observation["value"]
        points.append((datetime(int(year), int(month), 1),
                       numpy.nan if value is None else float(value)))
    points.sort()
    return (numpy.array([date for date, _ in points]),
            numpy.array([value for _, value in points]))


def context(payload: Payload, field: str,
            dates: NDArray[numpy.object_]) -> NDArray[numpy.float64]:
    """Population or coverage, on the series' own months, NaN where absent."""
    carried = (payload.get(field) or {}).get("observations", [])
    values = {observation["period"]: observation["value"] for observation in carried}
    months = [f"{date.month:02d}-{date.year}" for date in dates]
    return numpy.array([numpy.nan if values.get(month) is None else float(values[month])
                        for month in months])


# --- The level a month is judged against -------------------------------------


def local_median(values: NDArray[numpy.float64], span: int = 25) -> NDArray[numpy.float64]:
    """The median filing of the two years around each month, ignoring blanks.

    A centred window rather than a trailing one: the question is what a month
    in this stretch of the series normally looks like, and the months after are
    as much evidence of that as the months before.
    """
    out = numpy.zeros(values.shape)
    for i in range(len(values)):
        window = values[max(0, i - span // 2):i + span // 2 + 1]
        filed = window[numpy.isfinite(window) & (window > 0)]
        if len(filed):
            out[i] = float(numpy.median(filed))
    return out


def surrounding(values: NDArray[numpy.float64], typical: float, *, span: int = 25,
                min_filings: int = 6) -> NDArray[numpy.float64]:
    """The median filing of the two years around each month, not counting it.

    :func:`local_median` counts the month itself, which is right for a
    part-filing and wrong for a lump: where a window holds little but lumps --
    Washington's 1992-1995, eleven blanks and a December four years running --
    the median *is* a lump and no lump exceeds it. Leaving the month out, and
    falling back on the series' own *typical* filing where fewer than
    *min_filings* others remain, is what lets a lump be measured at all.
    """
    out = numpy.full(values.shape, typical)
    for i in range(len(values)):
        window = numpy.concatenate([values[max(0, i - span // 2):i],
                                    values[i + 1:i + span // 2 + 1]])
        filed = window[numpy.isfinite(window) & (window > 0)]
        if len(filed) >= min_filings:
            out[i] = float(numpy.median(filed))
    return out


# --- The rule ----------------------------------------------------------------


def unreadable(values: NDArray[numpy.float64], *, min_run: int = UNFILED_MIN_RUN,
               share: float = PARTIAL_SHARE, floor: float = PARTIAL_FLOOR,
               run_floor: float = UNFILED_RUN_FLOOR,
               catch_up: float = CATCH_UP) -> NDArray[numpy.bool_]:
    """Months that cannot be read as months: gaps, part-filings and catch-ups.

    Both of the first two tests read an absence, and an absence is only
    evidence where something was expected, so both carry a floor. A month under
    *share* of the local median is a part-filing, but only where that median is
    at least *floor*. *min_run* blanks in a row is a filing gap, but only where
    the filings the run swallowed -- its length times the local level -- reach
    *run_floor*. The filing after a gap is a catch-up when it exceeds *catch_up*
    times the local median.
    """
    median = local_median(values)
    blank = numpy.isnan(values) | (values == 0)
    flagged = numpy.zeros(values.shape, dtype=bool)

    # The level a run is weighed against. Where a whole neighbourhood is blank
    # the local median is 0 and offers none -- New York filed no clearance at
    # all from 2002 to 2012 -- so the series' own median filing stands in.
    filed = values[numpy.isfinite(values) & (values > 0)]
    level = numpy.where(median > 0, median,
                        float(numpy.median(filed)) if len(filed) else 0.0)

    # San Francisco is why the run test needs a floor of its own. It clears two
    # or three homicides a month, so a zero is an ordinary month there and two
    # in a row an ordinary quarter. Unfloored, the length test alone flags ten
    # such months before 2021 -- 1996-04/05, 2000-02/03, 2007-12..2008-03,
    # 2011-10/11 -- and each voids the twelve windows it sits in, among them
    # the year to December 2000, where every filing is present: 28 clearances
    # against 59 homicides, 47.5%. Washington's real gaps clear the floor
    # comfortably; the thinnest, two blank months at a median of 19 clearances,
    # swallows 38. The floor's price is the mirror image, and it is real: a
    # short genuine gap in a small series now passes as a quiet stretch.
    def close_run(start: int, stop: int) -> None:
        if (stop - start >= min_run
                and (stop - start) * numpy.median(level[start:stop]) >= run_floor):
            flagged[start:stop] = True

    start: int | None = None
    for i, is_blank in enumerate(blank):
        if is_blank and start is None:
            start = i
        elif not is_blank and start is not None:
            close_run(start, i)
            start = None
    if start is not None:
        close_run(start, len(blank))

    flagged |= (values < share * median) & (median >= floor)

    i = 0
    while i < len(values):
        if flagged[i]:
            end = i
            while end < len(values) and flagged[end]:
                end += 1
            if end < len(values) and values[end] > catch_up * median[end]:
                flagged[end] = True
            i = end + 1
        else:
            i += 1
    return flagged


def arrest_unreadable(values: NDArray[numpy.float64], *, token: float = TOKEN_SHARE,
                      share: float = ARREST_PARTIAL_SHARE,
                      lump: float = LUMP) -> NDArray[numpy.bool_]:
    """Months of an arrest series that cannot be read as months.

    :func:`unreadable`'s three tests, run as they stand, with three changes the
    arrest series need and the homicide series do not.

    *A token is a blank.* A filing under *token* of the series' median filing
    -- one arrest in a month, from a department that files fifteen thousand --
    is read as the gap it sits in, so the run test sees one run, not two.

    *A part-filing is under a third.* The homicide tests use a tenth because a
    city clearing three homicides a month has ordinary months far below its
    median. Arrests are counted in hundreds and thousands a month;
    Washington's 1989, eleven short months under a lump of a December, is what
    a third is for.

    *A lump is a lump anywhere.* :func:`unreadable`'s catch-up test looks only
    at the filing after a gap. A filing more than *lump* times the level around
    it (:func:`surrounding`) carries more than one month whether or not a gap
    precedes it, and cannot be read as a month.
    """
    filed = values[numpy.isfinite(values) & (values > 0)]
    typical = float(numpy.median(filed)) if len(filed) else 0.0
    blanked = numpy.where(numpy.isfinite(values) & (values < token * typical), 0.0, values)
    flagged = unreadable(blanked, share=share)
    level = surrounding(blanked, typical)
    flagged |= numpy.isfinite(blanked) & (level > 0) & (blanked > lump * level)
    return flagged


# --- What a readable window is -----------------------------------------------


def trailing_sum(values: NDArray[numpy.float64], window: int = 12) -> NDArray[numpy.float64]:
    """Twelve-month trailing sum, NaN until the window is full and clean.

    A window holding an unreadable month stays NaN rather than summing eleven
    months as though they were twelve.
    """
    out = numpy.full(values.shape, numpy.nan)
    for end in range(window - 1, len(values)):
        span = values[end - window + 1:end + 1]
        if not numpy.isnan(span).any():
            out[end] = span.sum()
    return out


# --- Figures -----------------------------------------------------------------
# Not part of the rule, and here for one reason: both notebooks stamp every
# figure with the requests it was drawn from, and a second module for six lines
# would be worse than this heading.


def stamp_source(*names: str, figure: Figure | None = None) -> None:
    """Name the requests a figure was drawn from, along its bottom edge."""
    figure = figure or pyplot.gcf()
    figure.subplots_adjust(bottom=max(0.12, 0.09 + 0.030 * len(names)))
    figure.text(0.995, 0.005, "\n".join(names), ha="right", va="bottom",
                fontsize=7, family="monospace", alpha=0.65)
