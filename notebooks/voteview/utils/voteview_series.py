"""Reduce the DW-NOMINATE panel to stored time series.

``HSall_members.csv`` is a **panel** -- one row per member per Congress, 51,064
of them -- and a series needs one number per Congress. That reduction is the
whole job, and which reduction you pick decides what the series means.

Four measures, each answering something the others cannot:

**party_predicts_position** -- the distance between the two largest parties'
medians over the average spread *within* them. Above 1, party tells you more
about a member than their own party's internal variation does. It works in
every era because it never names a party, which matters: Democrats and
Republicans do not both exist before the 34th Congress.

**effective_parties** -- Laakso-Taagepera, ``1 / sum(share^2)``. Two even
parties give 2.0, one party holding four fifths gives about 1.4. Carried
because the ratio above cannot be read without it: 1807 had the same 82%
supermajority as 1821 with a ratio of 3.74 against 0.65. Dominance and
separation are independent, and a dominant party is not an agreeable one.

**median_gap** and **moderate_bloc** -- the conventional Democrat-versus-
Republican pair. The gap is what published work reports; the bloc counts
members inside the opposing party's range, and the two are not redundant. The
bloc hit zero in the House in 2007 and stayed there while the gap kept climbing
from 0.805 to 0.925.

**The representation gate.** ``party_predicts_position`` is confounded with how
evenly the chamber is split -- mean 3.24 where the second party holds under 25%
against 5.01 where it holds over 40%. Comparing a 163-member party's median to
a 35-member remnant is not the same measurement; the remnant is a biased
survivor, not a small sample. It is not noise: bootstrapping a 73-member
median gives an sd of 0.015. The confound is worth 7.5% of variance, so the
gate excludes genuine one-party Congresses rather than ordinary majorities --
25%, which drops nine and keeps 110.

**What this is not.** ``dim1`` is a common scale, not a common subject. What
members divided over changes completely -- the Bank and tariffs in the 1830s,
silver and trusts in the 1890s, something else now. These measure how sharply
the chamber was sorted, never what it was sorting over.
"""
from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

from .fetch import CHAMBERS, DATA_DIR, DEMOCRAT, REPUBLICAN, party_code

SOURCE = "voteview"

#: A month. Not because the data moves that fast -- the resolution is biennial
#: and only the sitting Congress is re-estimated, so a year of drift would
#: change little. It is that *looking* is cheap: one conditional request
#: answers "has it changed?" in 0.18s and zero bytes, and the whole file is
#: 6 MB. So the horizon is set to how often it is worth a glance, not to how
#: long the data stays valid. Anything that actually matters at this
#: resolution -- a chamber flipping, a realignment -- arrives via the news
#: first and prompts a manual refresh.
TTL_DAYS = 30

#: A Congress convenes in January of an odd year and sits two years.
def congress_year(congress: int) -> int:
    return 1789 + (congress - 1) * 2


#: Below this share for the second party, the ratio is not a like-for-like
#: comparison. See the module docstring.
BALANCED = 0.25

#: The two-party measures need both major parties; they do not exist earlier.
TWO_PARTY_FROM = 34


class VoteviewSeriesError(RuntimeError):
    """Raised when the panel cannot support the reduction."""


def load_panel(data_dir: Path = DATA_DIR) -> dict[tuple[int, str, int], list[float]]:
    """``(congress, chamber, party) -> [dim1, ...]``, presidents excluded."""
    path = Path(data_dir) / "HSall_members.csv"
    if not path.exists():
        raise VoteviewSeriesError(f"no member file at {path} -- run utils.fetch.fetch()")
    scores: dict[tuple[int, str, int], list[float]] = defaultdict(list)
    for row in csv.DictReader(path.open()):
        if row["chamber"] not in CHAMBERS or not row["nominate_dim1"]:
            continue
        scores[(int(row["congress"]), row["chamber"], party_code(row))].append(
            float(row["nominate_dim1"]))
    if not scores:
        raise VoteviewSeriesError(f"{path} produced no usable rows")
    return scores


# --- the four measures --------------------------------------------------------

def _two_largest(scores, congress, chamber):
    groups = sorted(((p, v) for (c, ch, p), v in scores.items()
                     if c == congress and ch == chamber), key=lambda kv: -len(kv[1]))
    return groups[:2] if len(groups) >= 2 else None


def effective_parties(scores, congress, chamber) -> float | None:
    sizes = [len(v) for (c, ch, _), v in scores.items() if c == congress and ch == chamber]
    total = sum(sizes)
    return 1 / sum((n / total) ** 2 for n in sizes) if total else None


def party_predicts_position(scores, congress, chamber) -> float | None:
    """Between-party separation over within-party spread. Gated -- see the docstring."""
    pair = _two_largest(scores, congress, chamber)
    if not pair:
        return None
    a, b = pair[0][1], pair[1][1]
    total = sum(len(v) for (c, ch, _), v in scores.items() if c == congress and ch == chamber)
    if len(b) / total < BALANCED:
        return None
    within = (statistics.pstdev(a) * len(a) + statistics.pstdev(b) * len(b)) / (len(a) + len(b))
    return abs(statistics.median(a) - statistics.median(b)) / within if within else None


def _dr(scores, congress, chamber):
    if congress < TWO_PARTY_FROM:
        return None
    d = scores.get((congress, chamber, DEMOCRAT), [])
    r = scores.get((congress, chamber, REPUBLICAN), [])
    return (d, r) if len(d) >= 20 and len(r) >= 20 else None


def median_gap(scores, congress, chamber) -> float | None:
    pair = _dr(scores, congress, chamber)
    return statistics.median(pair[1]) - statistics.median(pair[0]) if pair else None


def moderate_bloc(scores, congress, chamber) -> float | None:
    """Members whose score falls inside the opposing party's range."""
    pair = _dr(scores, congress, chamber)
    if not pair:
        return None
    d, r = pair
    return float(sum(1 for x in d if x >= min(r)) + sum(1 for x in r if x <= max(d)))


MEASURES: dict[str, dict[str, Any]] = {
    "party_predicts_position": {
        "fn": party_predicts_position, "units": "ratio",
        "title": "How much party membership predicts ideology",
        "definition": "Distance between the two largest parties' medians on DW-NOMINATE "
                      "dim1, over the membership-weighted mean within-party spread. "
                      f"Only reported where the second party holds >= {BALANCED:.0%} "
                      "of the chamber.",
    },
    "effective_parties": {
        "fn": effective_parties, "units": "parties",
        "title": "Effective number of parties",
        "definition": "Laakso-Taagepera index, 1 / sum(seat share squared).",
    },
    "median_gap": {
        "fn": median_gap, "units": "dim1",
        "title": "Distance between the party medians",
        "definition": "Republican median minus Democratic median on DW-NOMINATE dim1. "
                      "Requires >= 20 members of each, so it begins at the 35th Congress.",
    },
    "moderate_bloc": {
        "fn": moderate_bloc, "units": "members",
        "title": "Members inside the opposing party's range",
        "definition": "Count of Democrats at or right of the most liberal Republican, plus "
                      "Republicans at or left of the most conservative Democrat.",
    },
}


def build_series(measure: str, chamber: str, scores=None,
                 data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """One stored-series record for a measure and chamber."""
    if measure not in MEASURES:
        raise VoteviewSeriesError(
            f"unknown measure {measure!r}; known: {', '.join(sorted(MEASURES))}")
    if chamber not in CHAMBERS:
        raise VoteviewSeriesError(f"unknown chamber {chamber!r}")
    scores = load_panel(data_dir) if scores is None else scores
    spec = MEASURES[measure]

    congresses = sorted({c for c, ch, _ in scores if ch == chamber})
    observations = []
    for congress in congresses:
        value = spec["fn"](scores, congress, chamber)
        if value is None:
            continue
        observations.append({"date": f"{congress_year(congress):04d}-01-01",
                             "value": f"{value:.6g}", "congress": congress})
    if not observations:
        raise VoteviewSeriesError(f"{measure}/{chamber} produced no observations")

    start, end = observations[0]["date"], observations[-1]["date"]
    return {
        "source": SOURCE,
        "native_id": f"voteview/{measure}/{chamber.lower()}",
        "title": f"{spec['title']} — US {chamber}",
        "frequency": "Biennial",
        "units": spec["units"],
        "observation_start": start,
        "observation_end": end,
        "observation_count": len(observations),
        "ttl_days": TTL_DAYS,
        "metadata": {
            "observation_count": len(observations),
            "units": spec["units"],
            SOURCE: {
                "concept": ["congressional_polarization"],
                "measure": [measure],
                "chamber": [chamber.lower()],
                "definition": [spec["definition"]],
                "scale": ["DW-NOMINATE dim1, economic left/right"],
                "observation_start_int": [int(start[:4] + "0101")],
                "observation_end_int": [int(end[:4] + "0101")],
            },
        },
        "observations": observations,
    }


def build_all(data_dir: Path = DATA_DIR) -> list[dict[str, Any]]:
    """All four measures across both chambers -- eight series."""
    scores = load_panel(data_dir)
    return [build_series(m, ch, scores=scores, data_dir=data_dir)
            for m in MEASURES for ch in CHAMBERS]
