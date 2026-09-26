"""Build the labelled IEM corpus: resolved markets with a full price path and a known outcome.

This is the asset IEM exists for in this study.  Every IEM market listed here
is **closed**, so every price path ends in a settlement -- which makes the
corpus *labelled* in the sense that matters for calibration: for each market,
each contract, and each day of that contract's life, you have a price and you
know what happened.

The label comes from the market itself rather than from an outside source, and
that choice is deliberate.  IEM contracts liquidate at a published value and the
final day's price *is* that value, so reading the label off the terminal row
avoids the join errors that come from matching market questions to an external
election-results table by hand.  `terminal_label` records the margin by which
the winner separated from the rest, so a market whose terminal prices are
ambiguous can be excluded rather than silently mislabelled.

Two corrections are applied and both are load-bearing:

1.  **Price scale.**  The 1988 and 1990 markets liquidate at $2.50 and $2.00
    times a vote share, so their published prices are not probabilities.  See
    ``iem.PRICE_SCALES``.
2.  **Settlement kind.**  A winner-take-all market settles 0/1 and is a binary
    event; a **vote-share** market settles at a continuous fraction and is a
    strike ladder, not a binary.  Pooling the two into one reliability curve is
    a category error, so `classify_settlement` separates them and the corpus
    carries the flag.

Output lands in ``data/iem_labelled_corpus.json`` -- gitignored and
regenerable, per the repo rule that nothing under ``notebooks/*/data/`` is
tracked.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import iem

__all__ = [
    "PRICE_BINS",
    "HORIZON_BINS",
    "SETTLEMENT_OVERRIDES",
    "reliability_table",
    "brier_by_horizon",
    "classify_settlement",
    "terminal_label",
    "build_legacy_rows",
    "build_modern_rows",
    "build_corpus",
    "write_corpus",
]

DATA_DIR = iem.DATA_DIR

#: A market whose code or description marks it as settling on a continuous vote
#: share rather than 0/1.  ``vs`` is matched only as a whole token, because it
#: otherwise fires inside words like "senate**vs**" and, worse, never fires at
#: all if written as ``[_\b]`` -- inside a character class ``\b`` is a backspace
#: character, not a word boundary, which is a silent way to classify the entire
#: archive as "unknown".
_VOTE_SHARE = re.compile(
    r"(?:^|[^a-z0-9])(?:vs|voteshare)(?:$|[^a-z0-9])|vote[ _]share", re.I
)
_WINNER_TAKE_ALL = re.compile(r"wta|winner[- ]takes?[- ]all", re.I)

#: Settlement kind taken from the market's own format spec, where the code name
#: does not carry it.  The 1988 presidential and both 1990 Senate markets
#: liquidate at a face value **times the candidate's vote share** -- they are
#: vote-share markets despite having no ``_vs`` in their names, and scoring them
#: as binaries is the error `classify_settlement` exists to prevent.
SETTLEMENT_OVERRIDES: dict[str, str] = {
    "1988presidential": "vote_share",
    "1990iowasenate": "vote_share",
    "1990illinoissenate": "vote_share",
}


def classify_settlement(code: str, description: str | None = None) -> str:
    """``"vote_share"``, ``"winner_take_all"`` or ``"unknown"``.

    A vote-share market's label is a **number in [0, 1]**, so its "calibration"
    question is a regression, not a reliability curve.  A winner-take-all
    market's label is 0 or 1 and is the one that belongs in a Brier score.
    Pooling the two produces a reliability curve that is wrong in a way no
    diagnostic catches, because both look like prices in [0, 1].

    `SETTLEMENT_OVERRIDES` wins over the pattern match, since three early
    markets state their settlement in their spec and not in their name.
    Anything returning ``"unknown"`` should be inspected rather than pooled --
    the seat-count and price-level markets in the archive are ladders whose
    settlement is neither binary nor a share.
    """
    if code in SETTLEMENT_OVERRIDES:
        return SETTLEMENT_OVERRIDES[code]
    blob = f"{code} {description or ''}"
    if _VOTE_SHARE.search(blob):
        return "vote_share"
    if _WINNER_TAKE_ALL.search(blob):
        return "winner_take_all"
    return "unknown"


def terminal_label(
    rows: Sequence[dict[str, Any]], price_key: str = "last"
) -> dict[str, Any]:
    """Read each contract's settlement off the final day of its path.

    Returns the terminal date, a ``labels`` map from contract to terminal price,
    the apparent ``winner``, and ``separation`` -- the gap between the top two
    terminal prices.

    **Use ``separation`` as the inclusion gate.**  A winner-take-all market that
    settled cleanly shows a separation near 1.0; anything under ~0.5 means the
    final row was captured before settlement, or the market is a vote-share or
    ladder market where several contracts legitimately pay out. Labelling those
    as a binary winner is exactly the silent error this function exists to make
    visible.
    """
    if not rows:
        return {"terminal_date": None, "labels": {}, "winner": None, "separation": None}
    last_date = max(r["date"] for r in rows)
    final = {}
    for r in rows:
        if r["date"] == last_date and r.get("contract"):
            v = r.get(price_key)
            if v is not None:
                final[r["contract"]] = v
    if not final:
        return {"terminal_date": last_date, "labels": {}, "winner": None, "separation": None}
    ranked = sorted(final.items(), key=lambda kv: -kv[1])
    separation = ranked[0][1] - ranked[1][1] if len(ranked) > 1 else None
    return {
        "terminal_date": last_date,
        "labels": final,
        "winner": ranked[0][0],
        "separation": separation,
    }


def build_legacy_rows(directory: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """Parse the recovered 1988-1996 files into per-market row lists.

    Dispatches the 1988 wide file to `iem.parse_1988_wide` and everything else
    to `iem.parse_legacy_file`, which between them cover all five layouts found
    in the archive.
    """
    directory = directory or (DATA_DIR / "iem_1988_1996")
    out: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(directory.glob("*.txt")):
        text = path.read_text(errors="replace")
        rows = (
            iem.parse_1988_wide(text)
            if path.stem == "1988presidential"
            else iem.parse_legacy_file(text)
        )
        if rows:
            out[path.stem] = rows
    return out


def build_modern_rows(path: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """Load the 1998-present pull, keeping only markets that returned rows.

    A market can legitimately return nothing: the registry's ``ph_year``
    dropdown lists the years the *page* offers, and some market-years have no
    price table behind them.
    """
    path = path or (DATA_DIR / "iem_price_history" / "all_markets.json")
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {k: v for k, v in raw.items() if v}


def build_corpus(
    legacy: dict[str, list[dict[str, Any]]] | None = None,
    modern: dict[str, list[dict[str, Any]]] | None = None,
    registry: Sequence[iem.IEMMarket] | None = None,
) -> list[dict[str, Any]]:
    """One record per labelled market, with its path summary and its label.

    Each record carries the market code, archive, settlement kind, price scale,
    date span, observation and contract counts, the number of days with actual
    trading, and the `terminal_label` block.  The full paths are not inlined --
    they are already on disk per archive, and a 17k-row corpus file that
    duplicates them is a liability rather than an asset.
    """
    legacy = legacy if legacy is not None else build_legacy_rows()
    modern = modern if modern is not None else build_modern_rows()
    try:
        reg = {m.code: m for m in (registry or iem.load_registry())}
    except iem.IEMError:
        reg = {}

    records: list[dict[str, Any]] = []
    for archive, group, price_key in (
        ("1988-1996", legacy, "last"),
        ("1998-present", modern, "last"),
    ):
        for code, rows in sorted(group.items()):
            meta = reg.get(code)
            desc = meta.description if meta else None
            dates = sorted(r["date"] for r in rows)
            contracts = sorted({r["contract"] for r in rows if r.get("contract")})
            traded = len({r["date"] for r in rows if not r.get("no_trade")})
            # Legacy layouts keep their numerics in `fields`, so a terminal
            # label is only readable where a named price column survived.
            # Test every row, not just the first: one legacy file mixes 8- and
            # 9-field rows, so `rows[0]` is not representative and keying off it
            # would drop a whole market's label or, worse, claim one it lacks.
            has_price = any(price_key in r for r in rows)
            label = terminal_label(rows, price_key) if has_price else {
                "terminal_date": dates[-1],
                "labels": {},
                "winner": None,
                "separation": None,
                "note": "legacy layout keeps numerics in `fields`; column meaning varies per market",
            }
            records.append(
                {
                    "venue": "iem",
                    "market": code,
                    "archive": archive,
                    "description": desc,
                    "settlement": classify_settlement(code, desc),
                    "price_scale": iem.PRICE_SCALES.get(code, 1.0),
                    "resolved": True,
                    "n_observations": len(rows),
                    "n_contracts": len(contracts),
                    "contracts": contracts,
                    "first_date": dates[0],
                    "last_date": dates[-1],
                    "span_days": _span_days(dates[0], dates[-1]),
                    "n_trading_days": traded,
                    "label": label,
                }
            )
    return records


def _span_days(a: str, b: str) -> int:
    from datetime import date as _d

    return (_d.fromisoformat(b) - _d.fromisoformat(a)).days


#: Default price bins for a reliability curve.  Finer at the ends, because that
#: is where favourite-longshot bias lives.
PRICE_BINS: tuple[tuple[float, float], ...] = (
    (0.00, 0.05), (0.05, 0.15), (0.15, 0.25), (0.25, 0.35), (0.35, 0.45),
    (0.45, 0.55), (0.55, 0.65), (0.65, 0.75), (0.75, 0.85), (0.85, 0.95),
    (0.95, 1.01),
)

#: Horizon bands in days to resolution.  The last two are the point: **no
#: published calibration evidence exists beyond one month from any venue**, so
#: 91-365 and 366+ are the bands this corpus was built to fill.
HORIZON_BINS: tuple[tuple[int, int], ...] = ((0, 30), (31, 90), (91, 365), (366, 10**6))


def _forecast_days(
    records: Sequence[dict[str, Any]],
    rows_by_market: Mapping[str, Sequence[dict[str, Any]]],
    min_separation: float = 0.5,
) -> list[tuple[int, float, float]]:
    """``(days_to_resolution, price, outcome)`` for every usable contract-day.

    Only winner-take-all markets with a clean `terminal_label` separation are
    included, because only those have an unambiguous 0/1 label.  The settlement
    day itself is dropped -- its price *is* the outcome, so keeping it
    manufactures perfect skill at horizon zero.
    """
    out: list[tuple[int, float, float]] = []
    for rec in records:
        if rec["settlement"] != "winner_take_all":
            continue
        if (rec["label"].get("separation") or 0.0) <= min_separation:
            continue
        winner = rec["label"]["winner"]
        terminal = _date(rec["last_date"])
        for row in rows_by_market.get(rec["market"], ()):
            price = row.get("last")
            if price is None or not (0.0 <= price <= 1.0):
                continue
            horizon = (terminal - _date(row["date"])).days
            if horizon <= 0:
                continue
            out.append((horizon, price, 1.0 if row["contract"] == winner else 0.0))
    return out


def _date(s: str):
    from datetime import date as _d

    return _d.fromisoformat(s)


def reliability_table(
    records: Sequence[dict[str, Any]],
    rows_by_market: Mapping[str, Sequence[dict[str, Any]]],
    min_cell: int = 15,
) -> list[dict[str, Any]]:
    """The reliability curve: mean price against realized frequency, by horizon.

    One row per (horizon band, price bin) cell with at least ``min_cell``
    observations.  ``gap = realized - mean_price``; positive means the market
    **underpriced** that outcome.

    .. warning::

       A contract-day is not an independent observation.  Prices are
       forward-filled between trades and heavily autocorrelated, so cell counts
       overstate the information content by a large and unquantified factor.
       These numbers are descriptive.  Do not attach a p-value to them, and do
       not read a single cell's gap as a finding -- read the **shape across
       horizon bands**, which is robust to the autocorrelation in a way the
       individual cells are not.
    """
    cells: dict[tuple[tuple[int, int], tuple[float, float]], list[float]] = defaultdict(list)
    outcomes: dict[tuple[tuple[int, int], tuple[float, float]], float] = defaultdict(float)
    for horizon, price, outcome in _forecast_days(records, rows_by_market):
        hb = next((b for b in HORIZON_BINS if b[0] <= horizon <= b[1]), None)
        pb = next((b for b in PRICE_BINS if b[0] <= price < b[1]), None)
        if hb is None or pb is None:
            continue
        cells[(hb, pb)].append(price)
        outcomes[(hb, pb)] += outcome
    table = []
    for hb in HORIZON_BINS:
        for pb in PRICE_BINS:
            ps = cells.get((hb, pb))
            if not ps or len(ps) < min_cell:
                continue
            mean_p = sum(ps) / len(ps)
            realized = outcomes[(hb, pb)] / len(ps)
            table.append(
                {
                    "horizon_lo": hb[0],
                    "horizon_hi": None if hb[1] >= 10**6 else hb[1],
                    "price_lo": pb[0],
                    "price_hi": pb[1],
                    "n": len(ps),
                    "mean_price": round(mean_p, 4),
                    "realized": round(realized, 4),
                    "gap": round(realized - mean_p, 4),
                }
            )
    return table


def brier_by_horizon(
    records: Sequence[dict[str, Any]],
    rows_by_market: Mapping[str, Sequence[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Brier score and skill against a climatological baseline, per horizon band.

    ``skill = 1 - Brier / (base * (1 - base))`` where ``base`` is the share of
    contract-days that won.  A market with **no skill scores zero**; a negative
    score means the market did worse than always quoting the base rate.

    This is the number the whole exercise is for, because **no published
    calibration evidence exists beyond one month for any venue**.

    Measured on the full corpus (2026-09-26): **skill stays positive at every
    horizon, in both archives, including beyond a year.**

    ===============  =====  =====  ========  ========
    horizon          1988-1996     1998-present
    ---------------  ------------  ------------------
    band             n      skill  n         skill
    ===============  =====  =====  ========  ========
    0-30 days          801  +0.40      2,970    +0.60
    31-90 days       1,276  +0.16      5,691    +0.41
    91-365 days      1,390  +0.16     19,280    +0.18
    366+ days        1,424  +0.17     11,867    +0.16
    ===============  =====  =====  ========  ========

    Two readings, and the second is the point.  Skill **decays monotonically
    with horizon** in the modern archive, 0.60 to 0.16, which is the same shape
    the published one-month literature reports.  But it **does not decay to
    zero**: both archives land near **+0.16 beyond a year to resolution**, which
    is direct evidence on the question no published study answers -- long-dated
    real-money political markets are meaningfully better than a climatological
    baseline.

    .. warning::

       **This number moved once already, and the earlier version was wrong.**
       Computed on a partial pull of 16 modern markets, the 91-365 and 366+
       bands read −0.002 and −0.012 -- apparently *no* skill at range.  The full
       57-market pull, which raised the usable winner-take-all count from 7 to
       27, turned both positive.  The partial sample was dominated by US
       congressional-control contracts, which sit near 50/50 for years by
       construction and are therefore the hardest case for a climatological
       baseline.  So the long-horizon result is **highly sensitive to which
       questions are in the sample**, and any re-run that changes the market set
       must recompute it rather than quote this table.

    Read it also with the `reliability_table` warning about autocorrelation:
    contract-days are not independent observations, there are no confidence
    intervals here, and the usable market count is 34 across both archives.
    """
    rows = _forecast_days(records, rows_by_market)
    out = []
    for hb in HORIZON_BINS:
        band = [(p, y) for h, p, y in rows if hb[0] <= h <= hb[1]]
        if not band:
            continue
        n = len(band)
        base = sum(y for _, y in band) / n
        brier = sum((p - y) ** 2 for p, y in band) / n
        clim = base * (1.0 - base)
        out.append(
            {
                "horizon_lo": hb[0],
                "horizon_hi": None if hb[1] >= 10**6 else hb[1],
                "n_contract_days": n,
                "base_rate": round(base, 4),
                "brier": round(brier, 4),
                "climatological_brier": round(clim, 4),
                "skill": round(1.0 - brier / clim, 4) if clim else None,
            }
        )
    return out


def write_corpus(records: Sequence[dict[str, Any]], directory: Path | None = None) -> Path:
    """Write the labelled corpus and return the path."""
    directory = directory or DATA_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "iem_labelled_corpus.json"
    path.write_text(json.dumps(list(records), indent=1), encoding="utf-8")
    return path
