"""One shape for three venues, and the calibration measured over it.

The three collectors each wrote their venue's own vocabulary to disk.  This
module puts Polymarket, Kalshi and the Iowa Electronic Markets into a single
panel of ``(market, day, price, horizon, outcome)`` rows so that a reliability
curve can be cut by venue, and then measures four things over it: calibration
by horizon, favourite-longshot bias, ladder coherence, and which quality
metrics actually separate a calibrated market from a miscalibrated one.

**What one shape costs.**  ``FORCED`` is the register of every place the three
venues disagree about what a row means, and what this module did about it.  It
is printed by the notebook rather than summarised, because two of the entries
are load-bearing:

*The price is not the same object on the two large venues.*  Polymarket serves
one forward-filled **last trade** per day and no quote at all; Kalshi serves a
daily candle whose ``close`` is null on the 55% of days with no trade but whose
**mid** is always present.  So Polymarket's price on a quiet day is a stale
print and Kalshi's is a live quote.  ``price_basis`` records which was used and
:func:`kalshi_price_basis_sensitivity` measures how much the choice moves the
answer, because a forcing that changes the result is a finding and not a
footnote.

*The two large samples were built differently.*  Polymarket's paths cover 75.8%
of its settled markets -- near-population.  Kalshi's cover 4,393 markets
selected for volume >= $500 and non-intraday life -- a liquidity-stratified
sample.  A raw venue-versus-venue calibration comparison is therefore
confounded by sample construction, not just by venue, and
:func:`matched_stratum` is the only comparison here that is not.

Read-only throughout: every input is a file one of the three collectors already
wrote under ``data/``.  Nothing in this module calls a venue.
"""

from __future__ import annotations

import gzip
import json
import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy
from numpy.typing import NDArray

__all__ = [
    "DATA",
    "FORCED",
    "HORIZON_EDGES",
    "HORIZON_LABELS",
    "PRICE_BANDS",
    "Market",
    "Panel",
    "bootstrap_ci",
    "brier",
    "calibration_slope",
    "cut",
    "horizon_bucket",
    "kalshi_price_basis_sensitivity",
    "ladder_price_coherence",
    "load_iem",
    "load_kalshi",
    "load_panel",
    "load_polymarket",
    "longshot_table",
    "market_bucket_rows",
    "matched_stratum",
    "metric_discrimination",
    "polymarket_quality",
    "reliability",
    "threshold_sweep",
]

DATA = Path(__file__).resolve().parent.parent / "data"

# ==========================================================================
# 0.  The register of forcings
# ==========================================================================

#: ``name -> (what the venues do, what this module forced, and what it costs)``.
#:
#: Printed by the notebook in full.  An entry belongs here when the three
#: venues do not agree on what a field *means*, as distinct from what it is
#: called; pure renames are handled silently in the loaders.
FORCED: dict[str, tuple[str, str, str]] = {
    "price": (
        "Polymarket serves one forward-filled last trade per day at "
        "fidelity=1440 and no quote on the path at all. Kalshi's daily candle "
        "carries yes_bid, yes_ask, mid, close and mean, and `close` is null on "
        "the 55% of market-days with no trade. IEM publishes low/high/last and "
        "no book at all except in its single 1988 file.",
        "Kalshi uses `mid` where present and falls back to `close`; Polymarket "
        "and IEM use the last trade, which is all they have.",
        "The two large venues' prices are different objects: a quiet Polymarket "
        "day is a stale print, a quiet Kalshi day is a live quote. A stale "
        "print is the older belief and therefore the *worse* forecast of the "
        "two at the same horizon, which flatters Kalshi. "
        "kalshi_price_basis_sensitivity() measures the size of it.",
    ),
    "resolution date": (
        "Polymarket carries end_date (the eligibility date, wrong by up to "
        "three weeks and past-dated on 15 of 440 open geopolitics events), "
        "closed_time, and a resolution_ts from /v2/resolutions. Kalshi carries "
        "close_time, settlement_ts and expiration_time. IEM carries only the "
        "last date on which a contract printed.",
        "Horizon is measured to closed_time on Polymarket, close_time on "
        "Kalshi, and the terminal print date on IEM.",
        "IEM's horizon is the only one that is not the venue's own statement of "
        "when the question closed -- it is inferred from the data, so a market "
        "that stopped trading early reads as a shorter horizon than it had.",
    ),
    "outcome": (
        "Polymarket's authoritative /v2/resolutions returns YES, NO or a UMA "
        "FIFTY_FIFTY vote that pays $0.50 on both tokens. Kalshi returns yes, "
        "no, an empty string, or `scalar` -- 162 markets Kalshi halted and paid "
        "out at a price rather than settling against the world. IEM has no "
        "outcome field: a winner-take-all market is read off its terminal "
        "prices and a vote-share market has no binary outcome at all.",
        "Binary 1/0 from YES/NO and yes/no. Polymarket FIFTY_FIFTY (30) and "
        "Kalshi scalar (162) are excluded rather than scored, because in both "
        "cases the 'outcome' is the forecast and scoring it makes the venue "
        "look perfect. IEM contributes only winner-take-all markets whose "
        "terminal top-two separation exceeds 0.5, one binary row per contract.",
        "IEM's inclusion gate is a judgement, and it is why IEM contributes 34 "
        "markets out of 89. Vote-share markets are dropped entirely: pooling "
        "them with winner-take-all gives a reliability curve that is wrong in a "
        "way no diagnostic catches, because both look like prices in [0,1].",
    ),
    "price scale": (
        "Polymarket and Kalshi quote in probability on [0,1]. IEM sold unit "
        "portfolios at $2.50 in 1988 and at $2.00 in the 1990 Senate markets, "
        "liquidating at face value times vote share -- the 1990 prospectus says "
        "'prices should be interpreted as twice the vote share'.",
        "The IEM loader divides by the per-market scale the collector recorded "
        "in iem.PRICE_SCALES.",
        "None, once applied. Read raw, those prices are wrong by 2-2.5x and "
        "still look plausible.",
    ),
    "category": (
        "Kalshi labels every series Politics, Elections, Economics or "
        "Financials. Polymarket has no category: it has >=4,000 dirty tag slugs "
        "and a two-valued `domains` field. IEM is all political.",
        "A two-level cut: `domain` in {political, macro} from Kalshi's category "
        "and from Polymarket's harvest tags, plus Polymarket's `geopolitics` "
        "tag kept as its own sub-cut because it is the one the user asked "
        "about and it behaves differently from the rest of politics.",
        "The domains are not the same populations. Kalshi's Financials is "
        "mostly dead index-strike ladder rungs; Polymarket's financial tags are "
        "oil, the Fed and trade-war headlines. 'macro' is a label for two "
        "different things and no cross-venue macro comparison here is clean.",
    ),
    "independence": (
        "A market contributes one price per day for its whole life, so a "
        "365-day market contributes 365 rows that are ~the same forecast.",
        "Every headline number is computed on one observation per market per "
        "horizon bucket -- the price nearest the middle of the bucket. Raw "
        "market-day counts are reported alongside so the inflation is visible.",
        "It cuts the usable n by roughly 30x and is the single largest "
        "difference between the numbers here and any that count market-days. "
        "Prices are still autocorrelated across buckets within one market, so "
        "no p-value or confidence interval here is exact; the bootstrap "
        "resamples markets, not rows, which handles the within-market part.",
    ),
}

# ==========================================================================
# 1.  The common shape
# ==========================================================================

#: Horizon-bucket edges in days to resolution.  The published literature stops
#: at "1 month+"; the last three edges are the point of the exercise.
HORIZON_EDGES: tuple[float, ...] = (0.0, 1.0, 7.0, 30.0, 90.0, 180.0, 365.0, 730.0, math.inf)
HORIZON_LABELS: tuple[str, ...] = (
    "<1d", "1-7d", "7-30d", "30-90d", "90-180d", "180-365d", "1-2y", ">2y")

#: Price bands for the favourite-longshot table.  The two lowest bands are
#: split at 5c because Polymarket's sub-2c neg-risk legs are a different
#: population from a genuine 7c forecast and pooling them hides that.
PRICE_BANDS: tuple[tuple[float, float, str], ...] = (
    (0.00, 0.02, "<2c"),
    (0.02, 0.05, "2-5c"),
    (0.05, 0.10, "5-10c"),
    (0.10, 0.25, "10-25c"),
    (0.25, 0.50, "25-50c"),
    (0.50, 0.75, "50-75c"),
    (0.75, 0.90, "75-90c"),
    (0.90, 1.01, ">90c"),
)


@dataclass(frozen=True, slots=True)
class Market:
    """One resolved binary question, in whichever venue's words it came from.

    ``outcome`` is 1.0 or 0.0 and never 0.5: a market whose settlement was a
    negotiated price rather than a fact about the world is excluded by the
    loader, not carried with a fractional label.
    """

    venue: str
    market_id: str
    title: str
    venue_category: str          # the venue's own label, verbatim
    domain: str                  # political | macro
    geo: bool                    # Polymarket's geopolitics tag; False elsewhere
    outcome: float               # 1.0 | 0.0
    resolved_at: datetime
    first_seen: datetime
    life_days: float
    n_points: int
    volume: float | None
    peak_open_interest: float | None
    multi_outcome: bool          # neg-risk / mutually-exclusive leg
    price_basis: str             # "last_trade" | "mid_else_close"
    quality: dict[str, float | None] = field(default_factory=dict)


@dataclass(slots=True)
class Panel:
    """Markets, and one row per market-day.

    The observation arrays are parallel and index into ``markets`` through
    ``m_index``; nothing here is a per-row object, because the Polymarket half
    alone is 1.6M rows.
    """

    markets: list[Market]
    m_index: NDArray[numpy.int32]
    price: NDArray[numpy.float32]
    horizon: NDArray[numpy.float32]
    ts: NDArray[numpy.int64]

    # -- per-market views, built once ------------------------------------
    def market_array(self, attr: str) -> NDArray[Any]:
        """One value per market, as an array aligned with ``m_index``."""
        return numpy.array([getattr(m, attr) for m in self.markets])

    def per_obs(self, attr: str) -> NDArray[Any]:
        """A market attribute broadcast to one value per observation."""
        return self.market_array(attr)[self.m_index]

    @property
    def outcome(self) -> NDArray[numpy.float64]:
        return self.market_array("outcome").astype(numpy.float64)

    def __len__(self) -> int:
        return int(self.price.size)

    def describe(self) -> dict[str, Any]:
        venues = self.market_array("venue")
        return {
            "markets": len(self.markets),
            "observations": len(self),
            "by_venue": {v: int((venues == v).sum()) for v in sorted(set(venues))},
            "obs_by_venue": {
                v: int((venues[self.m_index] == v).sum()) for v in sorted(set(venues))},
            "max_horizon_days": float(self.horizon.max()) if len(self) else 0.0,
        }


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    opener: Callable[..., Any] = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as handle:                       # type: ignore[operator]
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def _parse_ts(value: Any) -> datetime | None:
    """A venue timestamp in any of the four spellings the corpus contains."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ==========================================================================
# 2.  The three loaders
# ==========================================================================

#: Polymarket harvest tags that make a market macro rather than political.
#: Taken from the collector's own curated registry, split by hand: the
#: alternative is Polymarket's `domains` field, which calls oil "financial" and
#: a government shutdown "political" and has no third value.
_PM_MACRO_TAGS = frozenset({
    "economy", "fed", "inflation", "fed-rates", "macro-indicators", "gdp",
    "global-rates", "taxes", "treasuries", "consumer", "housing", "labor",
    "recession", "trade-war", "oil", "business",
})

_KALSHI_DOMAIN = {
    "Politics": "political", "Elections": "political",
    "Economics": "macro", "Financials": "macro",
}


def load_polymarket(
    *,
    markets_path: Path | None = None,
    paths_path: Path | None = None,
    min_points: int = 3,
) -> tuple[list[Market], list[tuple[int, list[list[float]]]]]:
    """Polymarket's settled markets that have a stored daily path.

    Three joins and one exclusion.  The join is ``market_id`` across the
    markets file and the price-paths file; the outcome comes from
    ``settled_outcome`` (which the collector took from ``/v2/resolutions``) and
    **never** from the last price on the path -- 26.9% of paths disagree with
    the settled value, because the resolving move lands inside one day.

    ``min_points`` drops markets whose whole life is one or two daily prints.
    They carry no horizon structure and would otherwise land entirely in the
    ``<1d`` bucket and dominate it.
    """
    markets_path = markets_path or DATA / "polymarket_markets.jsonl.gz"
    paths_path = paths_path or DATA / "polymarket_price_paths.jsonl.gz"

    paths: dict[str, list[list[float]]] = {}
    for row in _iter_jsonl(paths_path):
        points = row.get("points") or []
        if len(points) >= min_points:
            paths[str(row["market_id"])] = points

    out: list[Market] = []
    linked: list[tuple[int, list[list[float]]]] = []
    for row in _iter_jsonl(markets_path):
        key = str(row["market_id"])
        points = paths.get(key)
        if points is None:
            continue
        outcome = {"YES": 1.0, "NO": 0.0}.get(row.get("settled_outcome") or "")
        if outcome is None:                      # FIFTY_FIFTY and unresolved
            continue
        resolved = _parse_ts(row.get("closed_time")) or _parse_ts(row.get("resolution_ts"))
        if resolved is None:
            continue
        tags = set(row.get("harvest_tags") or []) | set(row.get("tag_slugs") or [])
        first = _parse_ts(row.get("start_date")) or _parse_ts(row.get("created_at"))
        if first is None:
            first = datetime.fromtimestamp(float(points[0][0]), tz=timezone.utc)
        prices = [float(p[1]) for p in points]
        out.append(Market(
            venue="polymarket",
            market_id=key,
            title=str(row.get("question") or row.get("slug") or key),
            venue_category=",".join(sorted(tags & (_PM_MACRO_TAGS | {
                "politics", "elections", "geopolitics", "world"}))) or "other",
            domain="macro" if (tags & _PM_MACRO_TAGS) else "political",
            geo="geopolitics" in tags,
            outcome=outcome,
            resolved_at=resolved,
            first_seen=first,
            life_days=(resolved - first).total_seconds() / 86400.0,
            n_points=len(points),
            volume=_as_float(row.get("volume_num")),
            peak_open_interest=_as_float(row.get("event_open_interest")),
            multi_outcome=bool(row.get("neg_risk") or row.get("event_neg_risk")),
            price_basis="last_trade",
            quality=_polymarket_quality_row(row, prices, points),
        ))
        linked.append((len(out) - 1, points))
    return out, linked


def _as_float(value: Any) -> float | None:
    try:
        out = float(value)          # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) else out


def _polymarket_quality_row(
    row: Mapping[str, Any], prices: Sequence[float], points: Sequence[Sequence[float]],
) -> dict[str, float | None]:
    """Every quality measure Polymarket supports, vendor-reported and computed.

    The point of keeping both is section 5: ``liquidity_num``, ``spread`` and
    ``competitive`` are the vendor's own quality signals and the computed
    columns beside them are the honest versions of the same idea.  Whether
    either separates a calibrated market from a miscalibrated one is the
    question, not an assumption.
    """
    unique = len(set(round(p, 4) for p in prices))
    moves = [abs(prices[i + 1] - prices[i]) for i in range(len(prices) - 1)]
    stamps = [float(p[0]) for p in points]
    gaps = [(stamps[i + 1] - stamps[i]) / 86400.0 for i in range(len(stamps) - 1)]
    unchanged = sum(1 for m in moves if m < 1e-9)
    text = row.get("description") or ""
    return {
        # vendor-reported
        "liquidity_num": _as_float(row.get("liquidity_num")),
        "volume_num": _as_float(row.get("volume_num")),
        "competitive": _as_float(row.get("competitive")),
        "vendor_spread": _as_float(row.get("spread")),
        "best_bid": _as_float(row.get("best_bid")),
        "best_ask": _as_float(row.get("best_ask")),
        "uma_bond": _as_float(row.get("uma_bond")),
        "event_open_interest": _as_float(row.get("event_open_interest")),
        # computed from the stored path
        "n_points": float(len(prices)),
        "distinct_levels": float(unique),
        "levels_per_point": unique / len(prices),
        "frac_unchanged": (unchanged / len(moves)) if moves else None,
        "median_abs_move": float(numpy.median(moves)) if moves else None,
        "max_abs_move": float(max(moves)) if moves else None,
        "largest_gap_days": float(max(gaps)) if gaps else None,
        "information_rate": float(numpy.mean(moves)) if moves else None,
        # specification
        "resolution_chars": float(len(text)),
        "names_source": float(bool(row.get("resolution_source"))),
        "was_disputed": float(bool(row.get("was_disputed"))),
        "neg_risk": float(bool(row.get("neg_risk") or row.get("event_neg_risk"))),
        "holding_rewards": float(bool(row.get("holding_rewards_enabled"))),
        "fee_bearing": float(bool(row.get("fee_type"))),
    }


def load_kalshi(
    *,
    candles_path: Path | None = None,
    quality_path: Path | None = None,
    basis: Literal["mid_else_close", "close_only"] = "mid_else_close",
    min_points: int = 3,
) -> tuple[list[Market], list[tuple[int, list[tuple[int, float]]]]]:
    """Kalshi's settled markets with a stored daily candle path.

    ``basis`` is the forcing named in ``FORCED["price"]``.  ``mid_else_close``
    keeps every day and reads a quote on the 55% with no trade;
    ``close_only`` keeps trades and throws those days away.  Both are offered
    so the notebook can measure the difference instead of asserting it does not
    matter.

    ``result == "scalar"`` is excluded: Kalshi halted those 162 markets and paid
    out at a price, so their "outcome" is their own forecast and scoring it
    would read as perfect skill.
    """
    candles_path = candles_path or DATA / "kalshi_candles.jsonl"
    quality_path = quality_path or DATA / "kalshi_quality.jsonl"

    quality: dict[str, dict[str, float | None]] = {}
    for row in _iter_jsonl(quality_path):
        quality[str(row["ticker"])] = {
            k: _as_float(row.get(k)) for k in (
                "volume", "life_days", "n_periods", "n_traded", "traded_frac",
                "n_two_sided", "two_sided_frac", "median_spread",
                "median_rel_spread", "n_distinct_prices", "median_abs_move",
                "max_abs_move", "frac_periods_unchanged", "peak_open_interest",
                "total_candle_volume")}

    out: list[Market] = []
    linked: list[tuple[int, list[tuple[int, float]]]] = []
    for row in _iter_jsonl(candles_path):
        outcome = {"yes": 1.0, "no": 0.0}.get(str(row.get("result") or "").lower())
        if outcome is None:
            continue
        resolved = _parse_ts(row.get("close_time"))
        if resolved is None:
            continue
        series: list[tuple[int, float]] = []
        for candle in row.get("candles") or []:
            price = candle.get("mid") if basis == "mid_else_close" else None
            if price is None:
                price = candle.get("close")
            if price is None:
                continue
            series.append((int(candle["ts"]), float(price)))
        if len(series) < min_points:
            continue
        ticker = str(row["ticker"])
        cat = str(row.get("category") or "")
        q = quality.get(ticker, {})
        first = datetime.fromtimestamp(series[0][0], tz=timezone.utc)
        out.append(Market(
            venue="kalshi",
            market_id=ticker,
            title=ticker,
            venue_category=cat or "other",
            domain=_KALSHI_DOMAIN.get(cat, "macro"),
            geo=False,
            outcome=outcome,
            resolved_at=resolved,
            first_seen=first,
            life_days=(resolved - first).total_seconds() / 86400.0,
            n_points=len(series),
            volume=q.get("volume"),
            peak_open_interest=q.get("peak_open_interest"),
            multi_outcome=False,
            price_basis=basis,
            quality=q,
        ))
        linked.append((len(out) - 1, series))
    return out, linked


def load_iem(
    *,
    corpus_path: Path | None = None,
    history_path: Path | None = None,
    legacy_dir: Path | None = None,
    min_separation: float = 0.5,
) -> tuple[list[Market], list[tuple[int, list[tuple[int, float]]]]]:
    """IEM's winner-take-all markets, one binary row per contract.

    IEM has no outcome field.  The label comes from the terminal print: the
    contract with the highest last price won.  ``min_separation`` is the
    inclusion gate the IEM collector chose -- the gap between the top two
    terminal prices must exceed it, so an ambiguous market is excluded rather
    than silently mislabelled.  Vote-share markets are dropped entirely.

    Prices are divided by the market's portfolio scale (2.5 in 1988, 2.0 in the
    1990 Senate markets, 1.0 thereafter) before anything reads them as a
    probability.
    """
    corpus_path = corpus_path or DATA / "iem_labelled_corpus.json"
    history_path = history_path or DATA / "iem_price_history" / "all_markets.json"
    legacy_dir = legacy_dir or DATA / "iem_1988_1996"

    records = json.loads(corpus_path.read_text())
    modern: dict[str, list[dict[str, Any]]] = (
        json.loads(history_path.read_text()) if history_path.exists() else {})

    out: list[Market] = []
    linked: list[tuple[int, list[tuple[int, float]]]] = []
    for record in records:
        if record.get("settlement") != "winner_take_all" or not record.get("resolved"):
            continue
        label = record.get("label") or {}
        if (label.get("separation") or 0.0) <= min_separation:
            continue
        labels = label.get("labels") or {}
        winner = label.get("winner")
        if not labels or winner is None:
            continue
        scale = float(record.get("price_scale") or 1.0)
        rows = modern.get(record["market"]) or _legacy_rows(legacy_dir, record["market"])
        if not rows:
            continue
        terminal = _parse_ts(label.get("terminal_date"))
        if terminal is None:
            continue
        by_contract: dict[str, list[tuple[int, float]]] = {}
        for row in rows:
            price = row.get("last")
            stamp = _parse_ts(row.get("date"))
            if price is None or stamp is None:
                continue
            by_contract.setdefault(str(row["contract"]), []).append(
                (int(stamp.timestamp()), float(price) / scale))
        for contract, series in by_contract.items():
            if contract not in labels or len(series) < 3:
                continue
            series.sort()
            out.append(Market(
                venue="iem",
                market_id=f"{record['market']}/{contract}",
                title=f"{record['market']} {contract}",
                venue_category=record.get("archive") or "iem",
                domain="political",
                geo=False,
                outcome=1.0 if contract == winner else 0.0,
                resolved_at=terminal,
                first_seen=datetime.fromtimestamp(series[0][0], tz=timezone.utc),
                life_days=(terminal - datetime.fromtimestamp(
                    series[0][0], tz=timezone.utc)).total_seconds() / 86400.0,
                n_points=len(series),
                volume=float(sum(float(r.get("dollar_volume") or 0.0) for r in rows
                                 if str(r.get("contract")) == contract)),
                peak_open_interest=None,
                multi_outcome=True,          # every WTA market is a partition
                price_basis="last_trade",
                quality={"n_points": float(len(series))},
            ))
            linked.append((len(out) - 1, series))
    return out, linked


def _legacy_rows(directory: Path, market: str) -> list[dict[str, Any]]:
    """The 1988-1996 archive, already parsed to rows by the IEM collector."""
    for name in (f"{market}.json", f"{market}_pricedata.json"):
        candidate = directory / name
        if candidate.exists():
            payload = json.loads(candidate.read_text())
            return payload if isinstance(payload, list) else payload.get("rows") or []
    return []


def load_panel(
    *,
    venues: Sequence[str] = ("polymarket", "kalshi", "iem"),
    kalshi_basis: Literal["mid_else_close", "close_only"] = "mid_else_close",
    progress: Callable[[str], None] | None = None,
) -> Panel:
    """All three venues in one panel, horizons measured to each one's close."""
    markets: list[Market] = []
    m_index: list[int] = []
    prices: list[float] = []
    horizons: list[float] = []
    stamps: list[int] = []

    def add(loaded: list[Market], linked: Sequence[tuple[int, Sequence[Any]]]) -> None:
        base = len(markets)
        markets.extend(loaded)
        for local, series in linked:
            market = loaded[local]
            close = market.resolved_at.timestamp()
            for point in series:
                ts, price = (int(point[0]), float(point[1]))
                if not 0.0 <= price <= 1.0:
                    continue                          # off-scale IEM leftovers
                horizon = (close - ts) / 86400.0
                if horizon < 0:
                    continue                          # a print after the close
                m_index.append(base + local)
                prices.append(price)
                horizons.append(horizon)
                stamps.append(ts)

    for venue in venues:
        if progress:
            progress(f"loading {venue}")
        if venue == "polymarket":
            add(*load_polymarket())
        elif venue == "kalshi":
            add(*load_kalshi(basis=kalshi_basis))
        elif venue == "iem":
            add(*load_iem())
        else:
            raise ValueError(f"unknown venue {venue!r}")

    return Panel(
        markets=markets,
        m_index=numpy.asarray(m_index, dtype=numpy.int32),
        price=numpy.asarray(prices, dtype=numpy.float32),
        horizon=numpy.asarray(horizons, dtype=numpy.float32),
        ts=numpy.asarray(stamps, dtype=numpy.int64),
    )


# ==========================================================================
# 3.  Calibration
# ==========================================================================

def horizon_bucket(horizon: NDArray[Any],
                   edges: Sequence[float] = HORIZON_EDGES) -> NDArray[numpy.int64]:
    """Bucket index per observation; -1 for anything outside the edges."""
    index = numpy.digitize(numpy.asarray(horizon, dtype=numpy.float64),
                           numpy.asarray(edges[1:-1], dtype=numpy.float64),
                           right=False)
    return index.astype(numpy.int64)


def market_bucket_rows(panel: Panel, edges: Sequence[float] = HORIZON_EDGES
                       ) -> dict[str, NDArray[Any]]:
    """One observation per market per horizon bucket.

    The reduction that makes the n honest.  Consecutive days of one market are
    ~the same forecast, so a market-day count overstates the information by
    roughly the length of the market.  Within a bucket the row kept is the one
    whose horizon is nearest the bucket's geometric centre, which is a less
    arbitrary choice than "first" (biased to the long end of the bucket) or
    "last" (biased to the short end, and to the resolving move).
    """
    bucket = horizon_bucket(panel.horizon, edges)
    lo = numpy.asarray(edges[:-1], dtype=numpy.float64)
    hi = numpy.asarray(edges[1:], dtype=numpy.float64)
    # Geometric centre, with the open top bucket anchored at twice its floor.
    hi_capped = numpy.where(numpy.isfinite(hi), hi, lo * 2.0 + 1.0)
    centre = numpy.sqrt(numpy.maximum(lo, 1e-6) * hi_capped)

    key = panel.m_index.astype(numpy.int64) * len(edges) + bucket
    distance = numpy.abs(panel.horizon.astype(numpy.float64) - centre[bucket])

    order = numpy.lexsort((distance, key))
    keep = order[numpy.concatenate(([True], numpy.diff(key[order]) != 0))]
    keep.sort()

    outcome = panel.outcome
    return {
        "m_index": panel.m_index[keep],
        "price": panel.price[keep].astype(numpy.float64),
        "horizon": panel.horizon[keep].astype(numpy.float64),
        "bucket": bucket[keep],
        "outcome": outcome[panel.m_index[keep]],
        "ts": panel.ts[keep],
    }


def brier(price: NDArray[Any], outcome: NDArray[Any],
          baseline: float | None = None) -> dict[str, float | int]:
    """Brier score, and the skill over a constant climatological forecast.

    The baseline is the *sample's own* base rate unless one is passed.  That is
    the honest comparison and also the harsh one: a set of markets that all
    settle NO is very easy to beat in absolute Brier and very hard to beat in
    skill, which is exactly why the skill column is here.
    """
    price = numpy.asarray(price, dtype=numpy.float64)
    outcome = numpy.asarray(outcome, dtype=numpy.float64)
    if price.size == 0:
        return {"n": 0, "brier": float("nan"), "base_rate": float("nan"),
                "climatological": float("nan"), "skill": float("nan")}
    base = float(outcome.mean()) if baseline is None else float(baseline)
    score = float(numpy.mean((price - outcome) ** 2))
    clim = float(numpy.mean((base - outcome) ** 2))
    return {
        "n": int(price.size),
        "brier": score,
        "base_rate": float(outcome.mean()),
        "climatological": clim,
        "skill": (1.0 - score / clim) if clim > 0 else float("nan"),
    }


def calibration_slope(price: NDArray[Any], outcome: NDArray[Any],
                      clip: float = 0.01) -> dict[str, float]:
    """Two slopes of realised on predicted, because they answer different things.

    ``slope_linear`` is the OLS slope of outcome on price: 1.0 is calibrated,
    below 1.0 means the price moves more than the truth (overconfident), above
    1.0 means it moves less (underconfident, the "compression toward 50%" the
    published work reports).

    ``slope_logit`` is the same regression in log-odds, which is the form the
    published calibration-slope figures use, and it is *not* comparable to the
    linear one.  Prices are clipped to ``[clip, 1-clip]`` first, so its value
    depends on the clip -- reported for comparability with the literature, and
    not used for any claim here.
    """
    price = numpy.asarray(price, dtype=numpy.float64)
    outcome = numpy.asarray(outcome, dtype=numpy.float64)
    # No "n" key: this dict is merged into brier()'s, whose n is an int count,
    # and a float here would silently change its type in every printed table.
    out = {"slope_linear": float("nan"),
           "intercept": float("nan"), "slope_logit": float("nan")}
    if price.size < 10 or numpy.ptp(price) < 1e-9:
        return out
    slope, intercept = numpy.polyfit(price, outcome, 1)
    out["slope_linear"], out["intercept"] = float(slope), float(intercept)

    clipped = numpy.clip(price, clip, 1.0 - clip)
    logit = numpy.log(clipped / (1.0 - clipped))
    if numpy.ptp(logit) > 1e-9:
        # One Newton-free pass: a least-squares fit of the empirical log-odds
        # inside coarse bins, rather than a full logistic regression, so that
        # this module needs nothing beyond numpy. Bins with 0% or 100% realised
        # rate carry no finite log-odds and are dropped, which is a known
        # upward bias on the slope at small n -- hence "not used for any claim".
        edges = numpy.quantile(logit, numpy.linspace(0, 1, 11))
        edges = numpy.unique(edges)
        if edges.size >= 4:
            idx = numpy.clip(numpy.digitize(logit, edges[1:-1]), 0, edges.size - 2)
            xs, ys = [], []
            for b in range(edges.size - 1):
                mask = idx == b
                if mask.sum() < 5:
                    continue
                rate = float(outcome[mask].mean())
                if 0.0 < rate < 1.0:
                    xs.append(float(logit[mask].mean()))
                    ys.append(math.log(rate / (1.0 - rate)))
            if len(xs) >= 3:
                out["slope_logit"] = float(numpy.polyfit(xs, ys, 1)[0])
    return out


def reliability(price: NDArray[Any], outcome: NDArray[Any],
                bands: Sequence[tuple[float, float, str]] = PRICE_BANDS,
                ) -> list[dict[str, Any]]:
    """The reliability curve: mean price against realised rate, per band."""
    price = numpy.asarray(price, dtype=numpy.float64)
    outcome = numpy.asarray(outcome, dtype=numpy.float64)
    rows = []
    for lo, hi, label in bands:
        mask = (price >= lo) & (price < hi)
        n = int(mask.sum())
        rows.append({
            "band": label, "lo": lo, "hi": hi, "n": n,
            "mean_price": float(price[mask].mean()) if n else float("nan"),
            "realised": float(outcome[mask].mean()) if n else float("nan"),
            "gap": (float(price[mask].mean() - outcome[mask].mean())
                    if n else float("nan")),
        })
    return rows


def cut(rows: Mapping[str, NDArray[Any]], panel: Panel, attr: str | None = None,
        mask: NDArray[Any] | None = None) -> dict[str, dict[str, Any]]:
    """Calibration statistics grouped by a market attribute.

    Every returned row carries its own ``n`` in markets as well as rows,
    because the whole point of ``market_bucket_rows`` is that the two differ.
    """
    keep = numpy.ones(rows["price"].size, dtype=bool) if mask is None else numpy.asarray(mask)
    labels = (numpy.array(["all"] * int(keep.sum())) if attr is None
              else panel.market_array(attr)[rows["m_index"][keep]])
    price, outcome = rows["price"][keep], rows["outcome"][keep]
    m_index = rows["m_index"][keep]

    out: dict[str, dict[str, Any]] = {}
    for label in sorted(set(labels.tolist()), key=str):
        sel = labels == label
        stats = brier(price[sel], outcome[sel])
        stats.update(calibration_slope(price[sel], outcome[sel]))
        stats["n_markets"] = int(numpy.unique(m_index[sel]).size)
        stats["mean_price"] = float(price[sel].mean()) if sel.any() else float("nan")
        stats["bias"] = stats["mean_price"] - stats["base_rate"]
        out[str(label)] = stats
    return out


def bootstrap_ci(price: NDArray[Any], outcome: NDArray[Any], m_index: NDArray[Any],
                 statistic: Callable[[NDArray[Any], NDArray[Any]], float],
                 draws: int = 400, seed: int = 20260926,
                 ) -> tuple[float, float]:
    """A percentile interval that resamples **markets**, not rows.

    Rows from one market are not independent, so resampling rows would give an
    interval several times too narrow.  This is still not exact -- one market's
    rows across horizon buckets are correlated with each other -- but it puts
    the clustering in the right place.
    """
    price = numpy.asarray(price, dtype=numpy.float64)
    outcome = numpy.asarray(outcome, dtype=numpy.float64)
    m_index = numpy.asarray(m_index)
    ids = numpy.unique(m_index)
    if ids.size < 10:
        return (float("nan"), float("nan"))
    lookup = {int(i): numpy.flatnonzero(m_index == i) for i in ids}
    rng = numpy.random.default_rng(seed)
    values = []
    for _ in range(draws):
        picked = rng.choice(ids, size=ids.size, replace=True)
        rows = numpy.concatenate([lookup[int(p)] for p in picked])
        values.append(statistic(price[rows], outcome[rows]))
    finite = numpy.asarray([v for v in values if numpy.isfinite(v)])
    if finite.size < 20:
        return (float("nan"), float("nan"))
    return (float(numpy.percentile(finite, 2.5)), float(numpy.percentile(finite, 97.5)))


def kalshi_price_basis_sensitivity(edges: Sequence[float] = HORIZON_EDGES
                                   ) -> dict[str, dict[str, Any]]:
    """The cost of the price forcing, measured rather than asserted.

    Loads Kalshi twice -- once reading the mid on every day, once reading only
    days that traded -- and reports the same calibration statistics both ways.
    If the two agree the forcing is a footnote; if they do not, every
    cross-venue number in the notebook inherits the difference.
    """
    out: dict[str, dict[str, Any]] = {}
    for basis in ("mid_else_close", "close_only"):
        markets, linked = load_kalshi(basis=basis)   # type: ignore[arg-type]
        panel = Panel(markets=markets,
                      m_index=numpy.empty(0, dtype=numpy.int32),
                      price=numpy.empty(0, dtype=numpy.float32),
                      horizon=numpy.empty(0, dtype=numpy.float32),
                      ts=numpy.empty(0, dtype=numpy.int64))
        m_index, prices, horizons, stamps = [], [], [], []
        for local, series in linked:
            close = markets[local].resolved_at.timestamp()
            for ts, price in series:
                horizon = (close - ts) / 86400.0
                if horizon < 0 or not 0.0 <= price <= 1.0:
                    continue
                m_index.append(local)
                prices.append(price)
                horizons.append(horizon)
                stamps.append(ts)
        panel.m_index = numpy.asarray(m_index, dtype=numpy.int32)
        panel.price = numpy.asarray(prices, dtype=numpy.float32)
        panel.horizon = numpy.asarray(horizons, dtype=numpy.float32)
        panel.ts = numpy.asarray(stamps, dtype=numpy.int64)
        rows = market_bucket_rows(panel, edges)
        stats = cut(rows, panel)["all"]
        stats["market_days"] = len(panel)
        stats["by_bucket"] = {
            HORIZON_LABELS[b]: brier(rows["price"][rows["bucket"] == b],
                                     rows["outcome"][rows["bucket"] == b])
            for b in range(len(HORIZON_LABELS))}
        out[basis] = stats
    return out


def matched_stratum(panel: Panel, rows: Mapping[str, NDArray[Any]],
                    min_volume: float = 500.0, min_life_days: float = 1.0,
                    ) -> NDArray[numpy.bool_]:
    """The only honest cross-venue mask: Kalshi's own sampling rule, applied to all.

    The Kalshi paths were selected for volume >= $500 and a non-intraday life.
    Polymarket's were not -- they are 75.8% of its whole settled corpus.  So a
    raw venue comparison compares a liquid sample with a population.  This
    applies Kalshi's rule to every venue, which does not make the samples the
    same (nothing here can) but removes the part of the difference that is
    known to be construction.
    """
    volume = panel.market_array("volume")[rows["m_index"]]
    life = panel.market_array("life_days")[rows["m_index"]].astype(numpy.float64)
    volume = numpy.array([numpy.nan if v is None else float(v) for v in volume])
    return (volume >= min_volume) & (life >= min_life_days)


# ==========================================================================
# 4.  Favourite-longshot bias
# ==========================================================================

def longshot_table(price: NDArray[Any], outcome: NDArray[Any],
                   bands: Sequence[tuple[float, float, str]] = PRICE_BANDS,
                   ) -> list[dict[str, Any]]:
    """Bias per price band, in both of the two units that get quoted.

    ``gap_cents`` is the absolute miscalibration: mean price minus realised
    rate, in cents.  It is the one to apply as a correction.

    ``per_dollar`` is the return on a dollar staked at the band's mean price,
    ``(realised - price) / price``, which is the unit the Polymarket literature
    quotes ("longshots lose 19.3c per dollar below 10c").  At low prices it is
    a ratio of two small numbers and is extremely sensitive to the band edge,
    so the two columns can tell different stories and the absolute gap is the
    robust one.  Both are printed for exactly that reason.
    """
    price = numpy.asarray(price, dtype=numpy.float64)
    outcome = numpy.asarray(outcome, dtype=numpy.float64)
    rows = []
    for lo, hi, label in bands:
        mask = (price >= lo) & (price < hi)
        n = int(mask.sum())
        if not n:
            rows.append({"band": label, "n": 0, "mean_price": float("nan"),
                         "realised": float("nan"), "gap_cents": float("nan"),
                         "per_dollar": float("nan"), "n_markets": 0})
            continue
        mean_price = float(price[mask].mean())
        realised = float(outcome[mask].mean())
        rows.append({
            "band": label, "n": n,
            "mean_price": mean_price, "realised": realised,
            "gap_cents": 100.0 * (mean_price - realised),
            "per_dollar": (100.0 * (realised - mean_price) / mean_price
                           if mean_price > 1e-9 else float("nan")),
        })
    return rows


# ==========================================================================
# 5.  Ladders
# ==========================================================================

def ladder_price_coherence(
    *,
    ladders_path: Path | None = None,
    paths_path: Path | None = None,
    markets_path: Path | None = None,
    kinds: Sequence[str] = ("cumulative",),
    min_rungs: int = 3,
    snapshots: int = 12,
) -> list[dict[str, Any]]:
    """Ladder coherence in **price**, over each ladder's whole life.

    The Polymarket collector scored ladders on their settled *outcomes* --
    whether the NO/YES pattern along the deadline axis is monotone.  That is a
    fact about the world, not about the prices.  This scores the prices: on
    each of up to ``snapshots`` dates spread over the ladder's life, it reads
    every rung's stored daily price on that date and asks whether the CDF is
    monotone in the deadline, what mass each adjacent difference implies, and
    whether any of that mass is negative.

    A negative interval mass is a stated arbitrage: the market says the event
    is *less* likely to have happened by a later date than by an earlier one.
    Whether it is tradeable is a different question -- these are last trades,
    not quotes, and a stale print on one rung manufactures a violation that was
    never executable.  ``max_gap_days`` on each snapshot is how stale the
    freshest reading in it could be.
    """
    ladders_path = ladders_path or DATA / "polymarket_ladders.json"
    paths_path = paths_path or DATA / "polymarket_price_paths.jsonl.gz"
    markets_path = markets_path or DATA / "polymarket_markets.jsonl.gz"

    payload = json.loads(ladders_path.read_text())
    ladders = [lad for lad in payload["ladders"]
               if lad.get("kind") in kinds and lad.get("n_rungs", 0) >= min_rungs]

    wanted: set[str] = set()
    for lad in ladders:
        for rung in lad["rungs"]:
            wanted.add(str(rung["market_id"]))

    # Only the rungs' own paths are held: the whole file is 55k paths and the
    # ladders reach a small fraction of them.
    series: dict[str, tuple[NDArray[numpy.int64], NDArray[numpy.float64]]] = {}
    for row in _iter_jsonl(paths_path):
        key = str(row["market_id"])
        if key not in wanted:
            continue
        points = row.get("points") or []
        if len(points) < 2:
            continue
        stamps = numpy.asarray([int(p[0]) for p in points], dtype=numpy.int64)
        values = numpy.asarray([float(p[1]) for p in points], dtype=numpy.float64)
        order = numpy.argsort(stamps)
        series[key] = (stamps[order], values[order])

    volume: dict[str, float] = {}
    for row in _iter_jsonl(markets_path):
        key = str(row["market_id"])
        if key in wanted:
            volume[key] = float(row.get("volume_num") or 0.0)

    out: list[dict[str, Any]] = []
    for lad in ladders:
        rungs = [r for r in lad["rungs"]
                 if str(r["market_id"]) in series and r.get("stated_deadline")]
        if len(rungs) < min_rungs:
            continue
        rungs.sort(key=lambda r: str(r["stated_deadline"]))
        deadlines = [datetime.fromisoformat(str(r["stated_deadline"])).replace(
            tzinfo=timezone.utc) for r in rungs]
        keys = [str(r["market_id"]) for r in rungs]

        closes = [_parse_ts(r.get("closed_time")) for r in rungs]
        # **A ladder is only a CDF where its rungs are quoted at the same
        # moment**, and for a ladder assembled across re-issued events they
        # very often are not: a rung that settled in February and one created
        # in December never coexist. Requiring every rung to be live at once
        # therefore throws most cross-event ladders away, so each snapshot
        # instead reads whichever rungs were *live* on that date -- had a print
        # at or before it and had not yet closed. `all_rungs_ever` against
        # `max_live_rungs` is how much of the ladder was ever simultaneous, and
        # it is the measurement that decides whether the ladder framing applies
        # to that ladder at all.
        union_lo = min(int(series[k][0][0]) for k in keys)
        union_hi = max(int(series[k][0][-1]) for k in keys)
        if union_hi <= union_lo:
            continue

        grid = numpy.linspace(union_lo, union_hi, max(2, snapshots)).astype(numpy.int64)
        lad_rows = []
        for when in grid:
            live: list[tuple[datetime, float, float]] = []
            for k, deadline, close in zip(keys, deadlines, closes):
                if close is not None and close.timestamp() <= float(when):
                    continue                       # already settled: a stale print
                stamps, values = series[k]
                pos = int(numpy.searchsorted(stamps, when, side="right")) - 1
                if pos < 0:
                    continue                       # not created yet
                live.append((deadline, float(values[pos]),
                             (int(when) - int(stamps[pos])) / 86400.0))
            if len(live) < min_rungs:
                continue
            live.sort(key=lambda row: row[0])
            arr = numpy.asarray([row[1] for row in live])
            staleness = [row[2] for row in live]
            diffs = numpy.diff(arr)
            days = numpy.asarray([(live[i + 1][0] - live[i][0]).days
                                  for i in range(len(live) - 1)], dtype=numpy.float64)
            days = numpy.where(days <= 0, numpy.nan, days)
            # Hazard two ways: the linear rate per day, and the continuous
            # force of resolution. They disagree by tens of percent on a wide
            # rung, so a flat linear profile can hide a rising hazard.
            survive = numpy.maximum(1.0 - arr[:-1], 1e-9)
            conditional = numpy.clip(diffs / survive, -1.0, 1.0)
            with numpy.errstate(divide="ignore", invalid="ignore"):
                force = -numpy.log(numpy.maximum(1.0 - conditional, 1e-12)) / days
                linear = conditional / days
            lad_rows.append({
                "at": datetime.fromtimestamp(int(when), tz=timezone.utc).date().isoformat(),
                "n_live": len(live),
                "deadlines": [row[0].date().isoformat() for row in live],
                "prices": [round(p, 4) for p in arr.tolist()],
                "interval_mass": [round(d, 4) for d in diffs.tolist()],
                "monotone": bool(numpy.all(diffs >= -1e-9)),
                "n_negative": int((diffs < -1e-9).sum()),
                "worst_negative": float(diffs.min()) if diffs.size else 0.0,
                "terminal_mass": float(arr[-1]),
                "max_gap_days": float(max(staleness)),
                "median_hazard_linear": _nanmedian(linear),
                "median_hazard_force": _nanmedian(force),
            })
        if not lad_rows:
            continue
        vols = [volume.get(k, 0.0) for k in keys]
        live_counts = [r["n_live"] for r in lad_rows]
        out.append({
            "ladder_id": lad["ladder_id"],
            "subject": lad.get("subject"),
            "kind": lad.get("kind"),
            "confidence": lad.get("confidence"),
            "all_rungs_ever": len(keys),
            "max_live_rungs": int(max(live_counts)),
            "median_live_rungs": float(numpy.median(live_counts)),
            "simultaneous_frac": max(live_counts) / len(keys),
            "n_events": len(set(lad.get("event_ids") or [])),
            "outcome_monotone": lad.get("outcome_monotone"),
            "tag_slugs": lad.get("tag_slugs") or [],
            "min_deadline": deadlines[0].date().isoformat(),
            "max_deadline": deadlines[-1].date().isoformat(),
            "total_volume": float(sum(vols)),
            "median_rung_volume": float(numpy.median(vols)),
            "n_snapshots": len(lad_rows),
            "frac_monotone": float(numpy.mean([r["monotone"] for r in lad_rows])),
            "mean_negative_intervals": float(numpy.mean([r["n_negative"] for r in lad_rows])),
            "worst_negative": float(min(r["worst_negative"] for r in lad_rows)),
            "median_terminal_mass": float(numpy.median([r["terminal_mass"] for r in lad_rows])),
            "median_max_gap_days": float(numpy.median([r["max_gap_days"] for r in lad_rows])),
            "snapshots": lad_rows,
        })
    return out


def _nanmedian(values: NDArray[Any]) -> float:
    """numpy.nanmedian without the all-NaN warning, which is an expected case.

    Two rungs can share a deadline -- Polymarket re-lists the same date across
    events -- and the interval between them is then zero days and carries no
    hazard at all.
    """
    finite = numpy.asarray(values, dtype=numpy.float64)
    finite = finite[numpy.isfinite(finite)]
    return float(numpy.median(finite)) if finite.size else float("nan")


# ==========================================================================
# 6.  Which metrics matter
# ==========================================================================

def _stat_pack(price: NDArray[Any], outcome: NDArray[Any]) -> dict[str, float]:
    stats = brier(price, outcome)
    stats.update(calibration_slope(price, outcome))
    stats["mean_price"] = float(numpy.mean(price)) if price.size else float("nan")
    stats["bias"] = stats["mean_price"] - stats["base_rate"]
    stats["abs_bias"] = abs(stats["bias"])
    return {k: float(v) for k, v in stats.items()}


#: Coarse price strata for the standardisation in :func:`metric_discrimination`.
#: Deliberately coarser than ``PRICE_BANDS``: five strata keep enough rows in
#: every (metric bin x stratum) cell to mean anything at n ~ 2,000.
STANDARDISE_BANDS: tuple[tuple[float, float, str], ...] = (
    (0.00, 0.05, "<5c"),
    (0.05, 0.20, "5-20c"),
    (0.20, 0.50, "20-50c"),
    (0.50, 0.80, "50-80c"),
    (0.80, 1.01, ">80c"),
)


def _standardised(price: NDArray[Any], outcome: NDArray[Any],
                  band: NDArray[Any], weights: Mapping[int, float],
                  min_cell: int = 15) -> dict[str, float]:
    """Bias and Brier for one metric bin, re-weighted to the whole sample's price mix.

    Post-stratification, and it is the load-bearing step of section 5.  Nearly
    every quality metric on either venue is partly a proxy for the price level
    -- relative spread is ``spread / mid``, so a 2c contract has a huge one by
    arithmetic alone, and a market that never moves is a market priced at 2c.
    Comparing raw bias across bins of such a metric therefore measures the
    price mix and calls it quality.  Here each bin is re-weighted so that its
    price distribution matches the whole masked sample's, and any cell thinner
    than ``min_cell`` is dropped with the weights renormalised over what is
    left, so ``weight_covered`` says how much of the sample the number rests on.
    """
    total = 0.0
    bias = 0.0
    brier_std = 0.0
    covered = 0.0
    for key, weight in weights.items():
        cell = band == key
        n = int(cell.sum())
        if n < min_cell:
            continue
        bias += weight * float(price[cell].mean() - outcome[cell].mean())
        brier_std += weight * float(numpy.mean((price[cell] - outcome[cell]) ** 2))
        total += weight
        covered += weight
    if total <= 0:
        return {"bias_std": float("nan"), "brier_std": float("nan"),
                "weight_covered": 0.0}
    return {"bias_std": bias / total, "brier_std": brier_std / total,
            "weight_covered": covered}


def metric_discrimination(
    panel: Panel,
    rows: Mapping[str, NDArray[Any]],
    metrics: Sequence[str],
    *,
    mask: NDArray[Any] | None = None,
    n_bins: int = 5,
    min_per_bin: int = 60,
    bands: Sequence[tuple[float, float, str]] = STANDARDISE_BANDS,
) -> list[dict[str, Any]]:
    """Does a quality metric separate calibrated markets from miscalibrated ones?

    For each metric, markets are split into ``n_bins`` quantile bins of that
    metric and calibration is measured inside each bin **twice**: raw, and
    standardised to the whole sample's price mix by :func:`_standardised`.

    Read the standardised column.  The raw one is kept beside it because the
    difference between the two is itself the finding -- a metric whose raw
    ``d_abs_bias`` is large and whose standardised one is near zero is not
    measuring market quality, it is measuring how cheap the contract is, and
    several of the metrics both the vendor docs and the prior analysis
    recommend are exactly that.

    **Horizon must be held fixed by the caller**, because horizon is the
    strongest single predictor of miscalibration and almost every liquidity
    measure correlates with it; an unstratified sweep ranks metrics by how well
    they proxy for time to resolution.  Pass ``mask`` restricted to one or two
    adjacent horizon buckets.

    ``rho_*`` are rank correlations over the bin means, so they say whether the
    metric orders the bins, not whether it orders markets.
    """
    out: list[dict[str, Any]] = []
    keep = (numpy.ones(rows["price"].size, dtype=bool) if mask is None
            else numpy.asarray(mask, dtype=bool))
    m_index = rows["m_index"][keep]
    price = rows["price"][keep]
    outcome = rows["outcome"][keep]

    # The price mix the whole masked sample has, which every bin is weighted to.
    band_of = numpy.full(price.size, -1, dtype=numpy.int64)
    for k, (lo, hi, _) in enumerate(bands):
        band_of[(price >= lo) & (price < hi)] = k
    weights = {k: float((band_of == k).mean()) for k in range(len(bands))
               if (band_of == k).any()}

    for name in metrics:
        values = numpy.array([
            (m.quality.get(name) if m.quality.get(name) is not None else numpy.nan)
            for m in panel.markets], dtype=numpy.float64)[m_index]
        finite = numpy.isfinite(values)
        if finite.sum() < n_bins * min_per_bin:
            out.append({"metric": name, "usable": False,
                        "n": int(finite.sum()), "reason": "too few finite values"})
            continue
        v = values[finite]
        p_f, o_f, b_f, m_f = (price[finite], outcome[finite],
                              band_of[finite], m_index[finite])
        edges = numpy.unique(numpy.quantile(v, numpy.linspace(0, 1, n_bins + 1)))
        if edges.size < 3:
            out.append({"metric": name, "usable": False, "n": int(finite.sum()),
                        "reason": f"only {edges.size - 1} distinct quantile bin(s)"})
            continue
        idx = numpy.clip(numpy.digitize(v, edges[1:-1]), 0, edges.size - 2)
        bins = []
        for b in range(edges.size - 1):
            sel = idx == b
            if sel.sum() < min_per_bin:
                continue
            pack = _stat_pack(p_f[sel], o_f[sel])
            pack.update(_standardised(p_f[sel], o_f[sel], b_f[sel], weights))
            pack.update({
                "bin": b, "lo": float(edges[b]), "hi": float(edges[b + 1]),
                "n": int(sel.sum()),
                "n_markets": int(numpy.unique(m_f[sel]).size),
                "median_value": float(numpy.median(v[sel])),
                "abs_bias_std": abs(pack["bias_std"]),
            })
            bins.append(pack)
        if len(bins) < 2:
            out.append({"metric": name, "usable": False, "n": int(finite.sum()),
                        "reason": "bins too thin after the floor"})
            continue
        lo_bin, hi_bin = bins[0], bins[-1]
        ranks = numpy.arange(len(bins), dtype=numpy.float64)
        out.append({
            "metric": name, "usable": True,
            "n": int(finite.sum()),
            "n_markets": int(numpy.unique(m_f).size),
            "n_bins": len(bins),
            # raw -- confounded by the price mix, kept for the comparison
            "abs_bias_lo": lo_bin["abs_bias"], "abs_bias_hi": hi_bin["abs_bias"],
            "d_abs_bias": hi_bin["abs_bias"] - lo_bin["abs_bias"],
            "skill_lo": lo_bin["skill"], "skill_hi": hi_bin["skill"],
            "d_skill": hi_bin["skill"] - lo_bin["skill"],
            # standardised -- the column to read
            "bias_std_lo": lo_bin["bias_std"], "bias_std_hi": hi_bin["bias_std"],
            "abs_bias_std_lo": lo_bin["abs_bias_std"],
            "abs_bias_std_hi": hi_bin["abs_bias_std"],
            "d_abs_bias_std": hi_bin["abs_bias_std"] - lo_bin["abs_bias_std"],
            "brier_std_lo": lo_bin["brier_std"], "brier_std_hi": hi_bin["brier_std"],
            "d_brier_std": hi_bin["brier_std"] - lo_bin["brier_std"],
            "weight_covered_lo": lo_bin["weight_covered"],
            "weight_covered_hi": hi_bin["weight_covered"],
            "rho_abs_bias_std": _spearman(
                ranks, numpy.asarray([b["abs_bias_std"] for b in bins])),
            "rho_abs_bias": _spearman(
                ranks, numpy.asarray([b["abs_bias"] for b in bins])),
            "base_rate_lo": lo_bin["base_rate"], "base_rate_hi": hi_bin["base_rate"],
            "bins": bins,
        })
    return out


def _spearman(a: NDArray[Any], b: NDArray[Any]) -> float:
    """Rank correlation, on so few points that it is a shape test not a test."""
    a, b = numpy.asarray(a, dtype=numpy.float64), numpy.asarray(b, dtype=numpy.float64)
    ok = numpy.isfinite(a) & numpy.isfinite(b)
    if ok.sum() < 3:
        return float("nan")
    ra = numpy.argsort(numpy.argsort(a[ok])).astype(numpy.float64)
    rb = numpy.argsort(numpy.argsort(b[ok])).astype(numpy.float64)
    if numpy.std(ra) < 1e-12 or numpy.std(rb) < 1e-12:
        return float("nan")
    return float(numpy.corrcoef(ra, rb)[0, 1])


def threshold_sweep(
    panel: Panel,
    rows: Mapping[str, NDArray[Any]],
    metric: str,
    thresholds: Sequence[float],
    *,
    mask: NDArray[Any] | None = None,
    direction: Literal["above", "below"] = "above",
    bands: Sequence[tuple[float, float, str]] = STANDARDISE_BANDS,
) -> list[dict[str, Any]]:
    """What a hard cut at each threshold keeps, and what it buys.

    The output a person can act on: for each candidate threshold, the share of
    markets that survive it and the calibration of what survives.  A threshold
    that improves calibration while keeping nothing is not a usable filter, so
    ``kept_frac`` is printed beside every row.
    """
    keep = (numpy.ones(rows["price"].size, dtype=bool) if mask is None
            else numpy.asarray(mask, dtype=bool))
    m_index, price, outcome = rows["m_index"][keep], rows["price"][keep], rows["outcome"][keep]
    values = numpy.array([
        (m.quality.get(metric) if m.quality.get(metric) is not None else numpy.nan)
        for m in panel.markets], dtype=numpy.float64)[m_index]

    band_of = numpy.full(price.size, -1, dtype=numpy.int64)
    for k, (lo, hi, _) in enumerate(bands):
        band_of[(price >= lo) & (price < hi)] = k
    weights = {k: float((band_of == k).mean()) for k in range(len(bands))
               if (band_of == k).any()}

    base = _stat_pack(price, outcome)
    base.update(_standardised(price, outcome, band_of, weights))
    out = []
    for threshold in thresholds:
        sel = (values >= threshold) if direction == "above" else (values <= threshold)
        sel &= numpy.isfinite(values)
        if sel.sum() < 30:
            out.append({"threshold": float(threshold), "n": int(sel.sum()),
                        "kept_frac": float(sel.mean()), "usable": False})
            continue
        pack = _stat_pack(price[sel], outcome[sel])
        pack.update(_standardised(price[sel], outcome[sel], band_of[sel], weights))
        pack.update({
            "threshold": float(threshold), "usable": True,
            "n": int(sel.sum()), "kept_frac": float(sel.mean()),
            "n_markets": int(numpy.unique(m_index[sel]).size),
            "abs_bias_std": abs(pack["bias_std"]),
            "d_abs_bias": pack["abs_bias"] - base["abs_bias"],
            "d_abs_bias_std": abs(pack["bias_std"]) - abs(base["bias_std"]),
            "d_brier_std": pack["brier_std"] - base["brier_std"],
            "d_skill": pack["skill"] - base["skill"],
        })
        out.append(pack)
    return out


def polymarket_quality(panel: Panel) -> list[str]:
    """The Polymarket quality columns present on enough markets to test."""
    counts: dict[str, int] = {}
    for market in panel.markets:
        if market.venue != "polymarket":
            continue
        for name, value in market.quality.items():
            if value is not None and numpy.isfinite(float(value)):
                counts[name] = counts.get(name, 0) + 1
    return sorted(counts, key=lambda k: -counts[k])
