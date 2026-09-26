"""The metric catalogue: everything about market quality that public data can measure.

This module exists to answer one question exhaustively -- *what can actually be
measured about a prediction market from data anyone can fetch without an
account?*  It is written to be complete rather than convenient.  Where a
measure that a trader would want **cannot** be computed from public data, it is
named in `NOT_COMPUTABLE` with the reason, instead of being quietly left out.
The value of the catalogue is that its silences are deliberate.

HOW TO READ A METRIC
--------------------
Every function's docstring carries three things, in this order:

* **measures** -- what the number is, in one line.
* **blind to** -- what it cannot see.  Every metric here has a blind spot and
  the blind spot is usually the interesting part.
* **good / bad** -- the range that means a tradeable market and the range that
  means an artefact.  These are calibrated against the live measurements in
  ``sefer/planning/polymarket-event-probabilities.md`` (2026-09-26), not
  invented.

THE THREE FAMILIES
------------------
1.  **Can the price be traded?**  Depth, spread, sweep cost, tick.  A quote
    nobody will fill is not a price.  This is where the published `liquidity`
    fields fail: Polymarket's ``liquidityNum`` is resting *bid* notional summed
    across **both** outcome books, so a contract with zero bids on the side you
    want can report millions.  Compute depth; never read it.
2.  **Does the price mean anything?**  Interest, turnover, holder
    concentration, staleness, information rate.  Volume is not interest: one
    Polymarket event showed **$1.29bn volume against $10.1m open interest**,
    128x turnover, with 88% of it in outcomes priced under two cents.
3.  **Is the price a probability?**  Fee wedges, capital-lock-up discount,
    favourite-longshot bias, outcome-sum coherence, and -- the part that only
    exists for a family of markets -- **ladder coherence**.

LADDERS ARE FIRST-CLASS OBJECTS
-------------------------------
A row of *"X happens by date T"* markets is a **cumulative distribution
function over the resolution date**.  Adjacent rungs difference into the
probability mass falling in each interval, exactly as an option strike ladder
differences into a density over price.  That makes a ladder testable in ways a
single market never is:

* the CDF must be **non-decreasing** in T, and a violation is an outright
  arbitrage if it survives the bid-ask spread;
* the **interval masses** must be non-negative and sum to at most one;
* the implied **hazard** -- the chance of resolving in an interval given it has
  not resolved yet -- must be a plausible shape, and a ladder priced by one
  market maker interpolating between the front rung and 1.0 produces a
  suspiciously smooth, near-constant hazard;
* the **terminal mass** left beyond the last rung says how much of the question
  the ladder actually prices.

One correction is mandatory before any of this: the rungs are **discounted
prices at different horizons**, so differencing them raw mixes the discount
gradient into the interval mass and can manufacture negative mass out of a
perfectly coherent ladder.  `discount_adjust_ladder` must run first.  See
`ladder_report`.

VENUES
------
`VENUE_COVERAGE` states, metric by metric, which of the four venues can support
it.  The short version:

* **Polymarket** -- the only venue serving a real order book, open interest,
  holders and trades.  Nearly every metric here is computable.
* **Kalshi** -- book and open interest, CFTC-regulated, settles against BLS and
  FRED prints.  No holder data.
* **PredictIt** -- four touch prices and nothing else.  No book beyond the
  touch, no open interest, no holders, no trade tape, no resolution text, and
  history only seven days deep.  Roughly a third of this catalogue is
  uncomputable there, and `predictit.py` explains why.
* **IEM** -- no live API at all, but a per-day, per-contract record of share
  volume, dollar volume, low, high and last going back to 1988.  Useless for
  monitoring, unmatched for method development.

.. note::

   Nothing here fetches.  The functions take already-fetched structures so the
   catalogue can be unit-tested without a network, and so the same code scores
   a live book and a 1992 IEM file.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Literal, Mapping, Sequence

__all__ = [
    "VENUE_COVERAGE",
    "NOT_COMPUTABLE",
    "BookLevel",
    "OrderBook",
    "Rung",
    "best_bid",
    "best_ask",
    "midpoint",
    "absolute_spread",
    "relative_spread",
    "depth_within",
    "depth_profile",
    "sweep_cost",
    "book_imbalance",
    "mid_last_divergence",
    "tick_size_relative",
    "volume_to_open_interest",
    "holder_concentration",
    "tail_volume_share",
    "time_since_last_trade",
    "quote_age",
    "path_staleness",
    "distinct_trading_days",
    "distinct_price_levels",
    "largest_gap_days",
    "information_rate",
    "time_to_resolution",
    "market_age",
    "outcome_price_sum",
    "sum_to_one_deviation",
    "resolution_text_length",
    "names_machine_checkable_source",
    "resolution_quality",
    "dispute_flags",
    "discount_factor",
    "discount_adjust",
    "longshot_adjust",
    "no_arbitrage_band",
    "parse_deadline",
    "rungs_from_markets",
    "discount_adjust_ladder",
    "ladder_monotonicity",
    "ladder_interval_mass",
    "ladder_hazard",
    "ladder_arbitrage_violations",
    "ladder_terminal_mass",
    "ladder_implied_quantile",
    "ladder_report",
    "quality_report",
]

Side = Literal["bid", "ask"]

# ==========================================================================
# 0.  The coverage registry -- what each venue can and cannot support
# ==========================================================================

#: ``metric -> {venue: (status, note)}``.  Status is one of:
#:
#: ``"yes"``      computable from a public, unauthenticated endpoint
#: ``"partial"``  computable but degraded -- read the note before using it
#: ``"no"``       the venue does not serve the inputs; the metric is unavailable
#:
#: This table is the answer to "what metrics are available at all".  It is
#: deliberately verbose: a blank cell would read as "not checked".
VENUE_COVERAGE: dict[str, dict[str, tuple[str, str]]] = {
    "depth_within_1c / depth_within_5c": {
        "polymarket": ("yes", "CLOB /book gives full ladder both sides."),
        "kalshi": ("yes", "/markets/{ticker}/orderbook, unauthenticated."),
        "predictit": (
            "no",
            "Only four touch prices (bestBuy/bestSell x Yes/No). No size at "
            "the touch and no levels behind it. Depth is unmeasurable; the "
            "$3,500 per-trader-per-market cap bounds it structurally instead.",
        ),
        "iem": ("no", "No book is published, live or historical."),
    },
    "absolute_spread / relative_spread": {
        "polymarket": ("yes", "From the book. Gamma's own `spread` field lies -- it reports 0.001 on books with no bid."),
        "kalshi": ("yes", "yes_bid / yes_ask on the market record."),
        "predictit": ("yes", "bestBuyYesCost - bestSellYesCost is a true touch spread."),
        "iem": ("partial", "Daily low/high only; the intraday spread is not recoverable."),
    },
    "midpoint_vs_last_trade_divergence": {
        "polymarket": ("yes", "/midpoint against lastTradePrice -- but lastTradePrice is actively wrong on resolved markets."),
        "kalshi": ("yes", "last_price against the bid/ask mid."),
        "predictit": ("yes", "lastTradePrice against the bestBuy/bestSell mid."),
        "iem": ("partial", "Daily last against the day's low/high midpoint only."),
    },
    "open_interest": {
        "polymarket": ("yes", "data-api /v2/oi?condition= -- the honest interest proxy."),
        "kalshi": ("yes", "open_interest on the market record."),
        "predictit": ("no", "Not served on any endpoint. No proxy exists."),
        "iem": ("no", "Not published."),
    },
    "volume_to_open_interest_turnover": {
        "polymarket": ("yes", "But volume itself is uncheckable -- volumeClob == volumeNum exactly at every percentile."),
        "kalshi": ("yes", "volume and open_interest both served."),
        "predictit": ("no", "No open interest; and volume exists only as 7 days of share counts."),
        "iem": ("no", "Volume yes, open interest no."),
    },
    "holder_count / holder_concentration": {
        "polymarket": ("yes", "data-api /v2/holders. Rate-limits hard; back off on 429."),
        "kalshi": ("no", "Not served."),
        "predictit": ("no", "Not served."),
        "iem": ("no", "Not served."),
    },
    "time_since_last_trade": {
        "polymarket": ("yes", "data-api /v2/trades timestamps."),
        "kalshi": ("partial", "last_price exists; its timestamp is not always served."),
        "predictit": (
            "no",
            "lastTradePrice carries no timestamp anywhere. The nearest proxy "
            "is a zero tradeVolume day in the 7-day chart, which is a 24-hour "
            "resolution answer to a question that needs minutes.",
        ),
        "iem": ("partial", "Zero-volume days are visible, so 'no trade today' is knowable; time-of-day is not."),
    },
    "quote_age": {
        "polymarket": ("no", "Book levels carry no timestamp. Only repeated polling can age a quote."),
        "kalshi": ("no", "Same."),
        "predictit": ("no", "Same."),
        "iem": ("no", "No book."),
    },
    "price_path_staleness / distinct_trading_days": {
        "polymarket": ("yes", "12-hour buckets are permanent; needs fidelity>=720 on the legacy CLOB route."),
        "kalshi": ("yes", "/series/{s}/markets/{t}/candlesticks."),
        "predictit": (
            "partial",
            "Seven days only, and only the first six contracts of a market. "
            "Beyond that, staleness is computable only over snapshots the "
            "recorder has accumulated since it started.",
        ),
        "iem": ("yes", "Daily rows from market open to close, for the market's whole life."),
    },
    "time_to_resolution / market_age": {
        "polymarket": ("partial", "endDate is the eligibility date, not the resolution date -- 15 of 440 open geopolitics events are past-dated, min -668 days."),
        "kalshi": ("yes", "close_time and expiration_time both served."),
        "predictit": ("partial", "dateEnd is 'NA' on 488 of 613 contracts (80%)."),
        "iem": ("yes", "Open Date and Close Date on every market info page."),
    },
    "tick_size": {
        "polymarket": ("yes", "orderPriceMinTickSize, 0.01 or 0.001."),
        "kalshi": ("yes", "One cent."),
        "predictit": ("yes", "One cent, fixed."),
        "iem": ("yes", "One tenth of a cent in the published files (4 dp)."),
    },
    "negative_risk_membership": {
        "polymarket": ("yes", "negRisk flag; exclude groupItemTitle matching 'Person [A-Z]' placeholders."),
        "kalshi": ("yes", "Mutually-exclusive series are structurally marked."),
        "predictit": (
            "partial",
            "No flag exists, but exclusivity is inferrable: across 131 "
            "multi-contract markets the median sum of last-trade prices is "
            "exactly 1.000, so most are exclusive. Min 0.0, max 2.16 -- the "
            "outliers are linked, not exclusive, markets.",
        ),
        "iem": ("yes", "Stated in the prospectus; WTA markets are exclusive by construction."),
    },
    "outcome_price_sum": {
        "polymarket": ("yes", "But only meaningful where negRisk is true and the set is exhaustive."),
        "kalshi": ("yes", ""),
        "predictit": ("yes", "Directly from the snapshot."),
        "iem": ("yes", "From the daily file."),
    },
    "resolution_text_length / named_source": {
        "polymarket": ("yes", "description present on 100/100 events and 848/848 markets; median 1,155 chars."),
        "kalshi": ("yes", "Better than prose: settlement_sources names BLS/FRED/Fed series, plus contract_terms_url PDFs."),
        "predictit": (
            "no",
            "No endpoint serves rules text. It exists only as client-rendered "
            "HTML on the market page. Every resolution-quality metric is "
            "unavailable for this venue from the API.",
        ),
        "iem": ("partial", "Prospectus is a static .txt per market, so length and source-naming are computable -- but by scraping, not an API."),
    },
    "dispute_history": {
        "polymarket": ("yes", "/v2/resolutions gives was_disputed and extended_review with a transaction hash behind them."),
        "kalshi": ("no", "Not served; CFTC-regulated settlement is not a dispute process in this sense."),
        "predictit": ("no", "Not served."),
        "iem": ("no", "Not served."),
    },
    "ladder_coherence": {
        "polymarket": ("yes", "The 15-rung Russia-Ukraine ceasefire ladder is the reference case: monotone 0.065 -> 0.705."),
        "kalshi": ("yes", "Strike ladders on macro series are the cleanest ladders anywhere -- they settle on a published statistic."),
        "predictit": (
            "partial",
            "Snapshot ladders are computable; historical ladders are NOT, "
            "because the chart endpoint silently returns only the first six "
            "contracts. Market 7589's 11 House-seat rungs chart as 6.",
        ),
        "iem": ("yes", "Vote-share bucket markets are ladders and the full history is published."),
    },
    "fee_wedge": {
        "polymarket": ("yes", "feeType/feeSchedule per market; geopolitics is genuinely fee-free."),
        "kalshi": ("yes", "Published fee schedule on notional."),
        "predictit": ("yes", "10% of gross profit per position -- the widest wedge of any venue here. See predictit.FEES."),
        "iem": ("yes", "No trading fee; a flat account fee only."),
    },
}

#: Measures a trader would want that **no** public data supports, anywhere in
#: this study.  Named rather than omitted, because a catalogue that silently
#: drops the unmeasurable overstates what is known.
NOT_COMPUTABLE: dict[str, str] = {
    "quote_age": (
        "No venue timestamps an order-book level. The age of the quote you are "
        "about to hit is unknowable from a single read; only your own repeated "
        "polling can establish it, and then only to your polling interval."
    ),
    "order_flow_toxicity": (
        "Requires signed trade direction (buyer- or seller-initiated). Public "
        "trade tapes give price and size, not aggressor side, so VPIN and "
        "friends cannot be computed."
    ),
    "true_unique_traders": (
        "Polymarket /holders counts wallets, and one person may hold many: the "
        "2024 'French whale' traded >$85m through four accounts that Polymarket "
        "itself later confirmed were one trader. Wallet count is an upper bound "
        "on people, not a count of them."
    ),
    "wash_trade_share": (
        "volumeClob equals volumeNum exactly at every percentile across 3,005 "
        "political markets, so there is no cross-check inside the API. "
        "Separating real from circular volume needs on-chain Polygon trade data."
    ),
    "market_maker_identity": (
        "Whether a smooth ladder is 44 independent traders or one maker "
        "interpolating cannot be settled from public data. The hazard-smoothness "
        "test in `ladder_hazard` is a hint, not an answer."
    ),
    "resolution_source_field": (
        "Polymarket's structured `resolutionSource` carries nothing usable and "
        "`resolvedBy` is an Ethereum address, not a source. The actual contract "
        "lives in free prose and can only be parsed, never queried."
    ),
    "criteria_drift": (
        "`description` is editable and nothing upstream keeps the old text. "
        "Once it changes, what the market promised while it traded at 0.40 is "
        "gone. This is recoverable only by snapshotting the catalogue daily "
        "from now on -- it cannot be backfilled."
    ),
    "predictit_depth": (
        "PredictIt publishes no size at the touch and no levels behind it, so "
        "its executable depth is unmeasurable. The binding constraint is "
        "regulatory instead, and it is a ceiling rather than a measurement: "
        "CFTC Letter 25-20 caps investment per participant PER CONTRACT at the "
        "FECA individual contribution limit ($3,500 at issue, FEC-indexed), and "
        "eliminated the former 5,000-trader-per-contract limit. See "
        "predictit.LIMITS -- and note that the cap is per contract, so an "
        "11-rung ladder permits 11x that exposure to one question."
    ),
    "predictit_pre_2025_price_quality": (
        "Not recoverable. The CFTC's own July 2025 amendment records that the "
        "5,000-trader-per-contract cap it was removing 'can create distortions "
        "in the data generated by the Market, as new traders are not allowed to "
        "enter some popular contracts, which then become illiquid and are not "
        "able to trade at market prices'. So PredictIt's most popular pre-2025 "
        "contracts were the ones most likely to be distorted, and how much "
        "cannot be measured after the fact -- the binding of the cap was never "
        "published. See predictit.STRUCTURAL_BREAKS."
    ),
}


# ==========================================================================
# 1.  Shapes
# ==========================================================================


@dataclass(frozen=True)
class BookLevel:
    """One price level: ``price`` in dollars per share, ``size`` in shares."""

    price: float
    size: float

    @property
    def notional(self) -> float:
        """Dollars resting at this level."""
        return self.price * self.size


@dataclass
class OrderBook:
    """A two-sided book for one outcome token.

    ``bids`` are sorted best (highest) first, ``asks`` best (lowest) first.
    `normalise` will sort for you if the venue does not.
    """

    bids: list[BookLevel] = field(default_factory=list)
    asks: list[BookLevel] = field(default_factory=list)

    def normalise(self) -> "OrderBook":
        self.bids = sorted(self.bids, key=lambda lv: -lv.price)
        self.asks = sorted(self.asks, key=lambda lv: lv.price)
        return self

    @classmethod
    def from_clob(cls, payload: Mapping[str, Any]) -> "OrderBook":
        """Build from a Polymarket CLOB ``/book`` payload."""

        def lv(rows: Any) -> list[BookLevel]:
            return [BookLevel(float(r["price"]), float(r["size"])) for r in (rows or [])]

        return cls(lv(payload.get("bids")), lv(payload.get("asks"))).normalise()

    @property
    def two_sided(self) -> bool:
        """True only if both sides have at least one level.

        A single-sided book is the most common disqualifier there is: requiring
        a genuine two-sided quote removes **50% of Polymarket markets 181-365
        days out** and 91 of the 121 outcomes in one leadership event.
        """
        return bool(self.bids) and bool(self.asks)


@dataclass(frozen=True)
class Rung:
    """One rung of a *"X happens by date T"* ladder.

    ``horizon`` is the rung's deadline; ``price`` is the Yes price.  ``bid`` and
    ``ask`` are optional and only needed for the arbitrage test, which has to
    know whether a monotonicity violation survives the spread.
    """

    label: str
    horizon: date
    price: float
    bid: float | None = None
    ask: float | None = None


# ==========================================================================
# 2.  Can the price be traded?
# ==========================================================================


def best_bid(book: OrderBook) -> float | None:
    """measures: the highest resting buy price.

    blind to: whether that bid is one share or ten thousand. A touch price with
    no size behind it is the single most misleading number a venue serves.

    good/bad: presence is the test. ``None`` means the market cannot be sold
    into at any price and every downstream metric on that side is void.
    """
    return book.bids[0].price if book.bids else None


def best_ask(book: OrderBook) -> float | None:
    """measures: the lowest resting sell price.

    blind to: size, same as `best_bid`.

    good/bad: ``None`` means you cannot buy. On Polymarket, 7 of the 40
    highest-liquidity long-dated geopolitics markets had no two-sided book at
    all -- every one a Nobel Peace Prize candidate leg.
    """
    return book.asks[0].price if book.asks else None


def midpoint(book: OrderBook) -> float | None:
    """measures: ``(best_bid + best_ask) / 2``, the conventional fair value.

    blind to: asymmetric depth. A mid between a $50,000 bid and a $12 ask is
    arithmetically halfway and economically nowhere near it -- use
    `book_imbalance` or the size-weighted microprice alongside it.

    good/bad: not a quality metric in itself; it is the input to most others.
    """
    bid, ask = best_bid(book), best_ask(book)
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2.0


def absolute_spread(book: OrderBook) -> float | None:
    """measures: ``ask - bid`` in dollars.

    blind to: price level, which makes it nearly useless on its own here. The
    *median* absolute spread across long-dated Polymarket political markets is
    **0.1c** -- which sounds superb until you notice the median *relative*
    spread on the same set is 17-22%, because the prices are pennies.

    good/bad: do not filter on this. Use `relative_spread`.
    """
    bid, ask = best_bid(book), best_ask(book)
    if bid is None or ask is None:
        return None
    return ask - bid


def relative_spread(book: OrderBook) -> float | None:
    """measures: ``(ask - bid) / mid`` -- the round-trip cost as a fraction.

    blind to: depth. A one-lot quote can show a 1% relative spread.

    good/bad: **<= 0.10 is the working filter.** The flagship Taiwan-2027
    market sits at 0.087. Median on long-dated political markets is 0.17-0.22,
    which is why most of them fail. Above ~0.30 the market is decorative.
    """
    bid, ask = best_bid(book), best_ask(book)
    if bid is None or ask is None:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return (ask - bid) / mid


def depth_within(book: OrderBook, side: Side, cents: float = 0.01) -> float:
    """measures: **executable notional in dollars** within ``cents`` of the touch.

    This is the metric that replaces every published `liquidity` field. For the
    bid side it sums ``price * size`` over levels at or above
    ``best_bid - cents``; for the ask, at or below ``best_ask + cents``.

    blind to: hidden or iceberg size (none of these venues offer it, so the
    blind spot is small), and to what happens when you actually trade -- resting
    size is not a promise.

    good/bad: the natural filter is **>= $10,000 on the side you would take**,
    and it is worth knowing in advance that on Polymarket this filter
    *annihilates the long-dated universe*: across the 40 highest-liquidity open
    geopolitics markets beyond 180 days, median bid depth within 1c is **$199**
    and median ask depth **$495**, with **2 of 33** clearing $10k on the bid and
    **0 of 33** on the ask. $1,000 is a realistic floor for research; $10,000 is
    a floor for trading and almost nothing passes it at range.
    """
    levels = book.bids if side == "bid" else book.asks
    if not levels:
        return 0.0
    touch = levels[0].price
    if side == "bid":
        keep = [lv for lv in levels if lv.price >= touch - cents - 1e-12]
    else:
        keep = [lv for lv in levels if lv.price <= touch + cents + 1e-12]
    return sum(lv.notional for lv in keep)


def depth_profile(book: OrderBook) -> dict[str, float | None]:
    """measures: depth at 1c and 5c on both sides, plus the touch and spread.

    The standard one-call summary of "can this be traded". Use the 5c numbers
    to see whether depth is *at* the touch or merely *near* it: a book whose 1c
    depth is $200 and 5c depth is $40,000 is a market maker standing off, which
    is a different problem from an empty market.

    blind to: everything time-varying. A book is one instant.

    good/bad: want ``ask_1c`` and ``bid_1c`` both >= $10,000 and
    ``relative_spread`` <= 0.10. Treat a 5c/1c ratio above ~20 as a warning
    that the touch is ornamental.
    """
    return {
        "best_bid": best_bid(book),
        "best_ask": best_ask(book),
        "midpoint": midpoint(book),
        "absolute_spread": absolute_spread(book),
        "relative_spread": relative_spread(book),
        "bid_1c": depth_within(book, "bid", 0.01),
        "ask_1c": depth_within(book, "ask", 0.01),
        "bid_5c": depth_within(book, "bid", 0.05),
        "ask_5c": depth_within(book, "ask", 0.05),
        "two_sided": book.two_sided,
        "n_bid_levels": len(book.bids),
        "n_ask_levels": len(book.asks),
    }


def sweep_cost(book: OrderBook, side: Side, notional: float) -> dict[str, float | None]:
    """measures: what spending ``notional`` dollars actually costs you.

    Walks the book and returns the volume-weighted average price achieved, the
    slippage against the midpoint in dollars and in relative terms, and how
    much of the order could not be filled at all. ``side="ask"`` means you are
    buying (lifting offers); ``side="bid"`` means you are selling into bids.

    This is the honest version of "is there $10,000 here" -- depth within a
    cent answers whether the size exists, sweep cost answers what it costs to
    take it.

    blind to: market impact beyond the visible book, and the fact that a
    resting order can be pulled between your read and your trade.

    good/bad: slippage under ~1% of mid for the size you care about is a real
    market. ``unfilled > 0`` means the book cannot absorb your size at any
    price, which on long-dated conflict markets is the normal answer.
    """
    levels = book.asks if side == "ask" else book.bids
    mid = midpoint(book)
    remaining = notional
    spent = 0.0
    shares = 0.0
    for lv in levels:
        if remaining <= 0:
            break
        take = min(lv.notional, remaining)
        spent += take
        shares += take / lv.price if lv.price > 0 else 0.0
        remaining -= take
    vwap = (spent / shares) if shares > 0 else None
    slippage = None
    rel = None
    if vwap is not None and mid is not None:
        slippage = (vwap - mid) if side == "ask" else (mid - vwap)
        rel = slippage / mid if mid > 0 else None
    return {
        "vwap": vwap,
        "shares": shares,
        "filled": spent,
        "unfilled": max(0.0, remaining),
        "slippage": slippage,
        "relative_slippage": rel,
        "midpoint": mid,
    }


def book_imbalance(book: OrderBook, cents: float = 0.01) -> float | None:
    """measures: ``(bid_depth - ask_depth) / (bid_depth + ask_depth)`` near the touch.

    Ranges -1 (all offers, no bids) to +1 (all bids, no offers).

    blind to: intent. Imbalance is a pressure reading, not a forecast, and on
    a thin book it is mostly noise.

    good/bad: |imbalance| below ~0.5 is a balanced book. Values pinned at
    exactly +1 or -1 are the signature of a one-sided quote and should be read
    together with `OrderBook.two_sided`, not as a directional signal. This is
    the metric that catches the Polymarket pathology where a cheap outcome's
    *No* book is bid near $1 and dominates the reported liquidity.
    """
    b = depth_within(book, "bid", cents)
    a = depth_within(book, "ask", cents)
    if b + a <= 0:
        return None
    return (b - a) / (b + a)


def mid_last_divergence(
    book: OrderBook, last_trade: float | None
) -> dict[str, float | None]:
    """measures: how far the last printed trade sits from the current midpoint.

    blind to: *when* the last trade happened -- see `quote_age` in
    `NOT_COMPUTABLE`. A large divergence on a market that traded a minute ago
    means the book moved; on one that traded in March it means nothing.

    good/bad: under 2c absolute, or under 10% relative, on a market with a real
    book. A large divergence is a reliable detector of stale served fields:
    Polymarket's ``lastTradePrice`` reads **1 on a losing Yes token** after
    resolution and elsewhere contradicts its own ``outcomePrices``. Treat any
    divergence over ~0.2 as evidence the served field is broken rather than as
    information about price.
    """
    mid = midpoint(book)
    if mid is None or last_trade is None:
        return {"midpoint": mid, "last_trade": last_trade, "absolute": None, "relative": None}
    diff = last_trade - mid
    return {
        "midpoint": mid,
        "last_trade": last_trade,
        "absolute": diff,
        "relative": (diff / mid) if mid > 0 else None,
    }


def tick_size_relative(tick: float, price: float) -> float | None:
    """measures: the tick as a fraction of the price -- the quantization floor.

    blind to: whether anyone trades at adjacent ticks.

    good/bad: below ~0.02 the grid is fine enough to express a belief. At a 1c
    tick and a 3c price the relative tick is **0.33**, meaning the market
    cannot distinguish a 3% from a 4% probability -- a third of the quantity
    being measured. Polymarket's 0.001 tick exists precisely for these; Kalshi
    and PredictIt are stuck at a cent, which makes both unusable for longshots.
    """
    if price <= 0:
        return None
    return tick / price


# ==========================================================================
# 3.  Does the price mean anything?
# ==========================================================================


def volume_to_open_interest(volume: float, open_interest: float) -> float | None:
    """measures: turnover -- how many times the outstanding position churned.

    blind to: whether the churn is real. This is the metric that exposed the
    problem rather than solving it.

    good/bad: for a months-to-years horizon question, turnover in the low
    single digits is normal and healthy. **128x is not**: the 2028 Democratic
    nominee market reported $1,285,481,603 of volume against $10,075,637 of
    open interest on a two-year-horizon question. Read anything above ~20x as
    reward-farming, wash trading, or both, and fall back on open interest
    alone.
    """
    if open_interest <= 0:
        return None
    return volume / open_interest


def holder_concentration(
    holdings: Sequence[float], top_k: int = 5
) -> dict[str, float | int | None]:
    """measures: how few wallets hold the position -- HHI, top-1 and top-k share.

    blind to: **people**. Wallets are not traders; see ``true_unique_traders``
    in `NOT_COMPUTABLE`. It is also blind to off-venue hedges.

    good/bad: HHI below ~0.05 with a top-1 share under ~0.10 is a dispersed
    market. Concentration matters most at settlement, because the same holders
    vote the oracle: the US-Iran peace-deal market that resolved Yes on a
    disputed reading had a reported largest holder at 16.7%, top five at 41.7%
    and top seven at 50.3% -- a majority of the vote in seven hands.
    """
    total = float(sum(h for h in holdings if h and h > 0))
    if total <= 0:
        return {"n_holders": 0, "hhi": None, "top1_share": None, f"top{top_k}_share": None}
    shares = sorted((h / total for h in holdings if h and h > 0), reverse=True)
    return {
        "n_holders": len(shares),
        "hhi": sum(s * s for s in shares),
        "top1_share": shares[0],
        f"top{top_k}_share": sum(shares[:top_k]),
    }


def tail_volume_share(
    volumes: Sequence[float], prices: Sequence[float], threshold: float = 0.02
) -> float | None:
    """measures: the share of an event's volume sitting in outcomes priced below ``threshold``.

    blind to: motive. It cannot tell farming from genuine lottery-ticket demand.

    good/bad: under ~0.20 is unremarkable. **Above ~0.50 the event's headline
    volume describes something other than interest in the question.** Measured
    on Polymarket's 2028 Democratic nominee event: 88.5% of volume under 2c and
    84% under 1c, with Oprah Winfrey at $54.4m of volume and a price of 0.0005,
    twice the front-runner's. Compute this before quoting any event-level
    volume figure.
    """
    if not volumes or len(volumes) != len(prices):
        return None
    total = float(sum(volumes))
    if total <= 0:
        return None
    return sum(v for v, p in zip(volumes, prices) if p is not None and p < threshold) / total


def time_since_last_trade(
    last_trade_ts: datetime | str | None, now: datetime | None = None
) -> float | None:
    """measures: hours since the most recent print.

    blind to: size of that trade. One share at 3am resets the clock.

    good/bad: for a months-horizon market, under ~48 hours means somebody is
    watching. Beyond ~2 weeks the quote is a standing order, not a price.
    Unavailable on PredictIt and IEM at anything finer than a day -- see
    `VENUE_COVERAGE`.
    """
    if last_trade_ts is None:
        return None
    if isinstance(last_trade_ts, str):
        last_trade_ts = datetime.fromisoformat(last_trade_ts.replace("Z", "+00:00"))
    if last_trade_ts.tzinfo is None:
        last_trade_ts = last_trade_ts.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - last_trade_ts).total_seconds() / 3600.0


def quote_age(*_: Any, **__: Any) -> None:
    """measures: nothing. **Not computable on any venue in this study.**

    Order-book levels carry no timestamp on Polymarket, Kalshi or PredictIt,
    and IEM publishes no book at all. The age of the quote you are about to
    hit is unknowable from a single read. It becomes knowable only through
    your own repeated polling, and then only to the resolution of your polling
    interval -- which is a property of your collector, not of the venue.

    Kept as a function so the catalogue's silence is explicit rather than an
    omission. Always returns ``None``.
    """
    return None


def path_staleness(prices: Sequence[float]) -> dict[str, float | int | None]:
    """measures: the share of observations with no price change -- a step function detector.

    Returns ``no_move_share`` (fraction of consecutive pairs that are equal),
    ``longest_flat_run`` in observations, and ``n_moves``.

    blind to: moves smaller than the tick, and to moves that happened and
    reversed within one bucket.

    good/bad: below ~0.5 on a daily series is a live market. **Above ~0.9 the
    series is a step function and not a probability path**: the $455k
    ``will-china-invade-taiwan-by-june-30-2027`` market showed **15 distinct
    prices across 175 days**. Independently, 35% of Polymarket markets beyond a
    year did not move a single tick in a month.
    """
    clean = [p for p in prices if p is not None]
    if len(clean) < 2:
        return {"n": len(clean), "no_move_share": None, "longest_flat_run": None, "n_moves": None}
    flat = 0
    moves = 0
    run = 1
    longest = 1
    for a, b in zip(clean, clean[1:]):
        if a == b:
            flat += 1
            run += 1
            longest = max(longest, run)
        else:
            moves += 1
            run = 1
    pairs = len(clean) - 1
    return {
        "n": len(clean),
        "no_move_share": flat / pairs,
        "longest_flat_run": longest,
        "n_moves": moves,
    }


def distinct_trading_days(
    dates: Sequence[Any], volumes: Sequence[float] | None = None
) -> int:
    """measures: how many distinct days the market actually traded.

    With ``volumes``, counts days with non-zero volume -- the honest reading.
    Without, counts distinct dates present, which on a forward-filled price
    path counts days the *collector* ran, not days the market traded.

    blind to: intraday concentration. Ten trades in one minute is one day.

    good/bad: divide by `market_age` in days to get a participation rate.
    Above ~0.5 is an active market. Polymarket's four Russia-Ukraine rungs
    beyond a year had lifetime volumes of $818, $976, $1,643 and $3,018 -- at
    that level, most "days" in the path are forward fill.
    """
    if volumes is not None and len(volumes) == len(dates):
        return len({d for d, v in zip(dates, volumes) if v and v > 0})
    return len(set(dates))


def distinct_price_levels(prices: Sequence[float]) -> int:
    """measures: how many different prices the market has ever printed.

    blind to: the order they came in.

    good/bad: read against the number of observations. **15 distinct prices
    over 175 days and 161 observations** is the Taiwan-June-2027 market, and it
    is a step function. A ratio of distinct levels to observations above ~0.3
    is a genuinely moving price; below ~0.1 it is a quote being nudged.
    """
    return len({p for p in prices if p is not None})


def largest_gap_days(dates: Sequence[date | str]) -> int | None:
    """measures: the biggest hole in the observed path, in days.

    blind to: whether the hole is missing data or a genuinely silent market --
    those look identical from outside.

    good/bad: on a daily series, 1 is perfect. Polymarket's flagship
    Taiwan-2027 market gives 409 daily points over 429 days (95% coverage) with
    a largest gap of 10 days, and that is the *good* case.
    """
    parsed = sorted(
        date.fromisoformat(str(d)[:10]) if not isinstance(d, date) else d for d in dates
    )
    if len(parsed) < 2:
        return None
    return max((b - a).days for a, b in zip(parsed, parsed[1:]))


def information_rate(prices: Sequence[float], lag: int = 1) -> float | None:
    """measures: the median absolute price move over ``lag`` observations, in dollars.

    The cleanest single answer to "is this market learning anything?".

    blind to: direction and to whether the move was informed.

    good/bad: it decays hard with horizon, and the decay is the finding.
    Measured on Polymarket political markets with a real book and >$50k volume,
    the median 1-day move falls from **1.00c at <=30 days to 0.10c beyond 365
    days**, and the median 1-week move from 2.50c to 0.45c. Below ~0.1c a day
    the market is not incorporating news; it is being carried.
    """
    clean = [p for p in prices if p is not None]
    if len(clean) <= lag:
        return None
    moves = [abs(b - a) for a, b in zip(clean, clean[lag:])]
    return statistics.median(moves) if moves else None


def time_to_resolution(
    end: date | datetime | str | None, now: date | datetime | None = None
) -> int | None:
    """measures: days from now until the stated end date.

    blind to: **whether the stated end date is true**, and on Polymarket it
    frequently is not. ``endDate`` is the *eligibility* date, not the
    resolution date: one Russia-Ukraine market carried ``endDate=2026-05-31``
    and closed on 2026-05-09, three weeks early. Worse, **15 of 440 open
    geopolitics events are past-dated, the worst by -668 days**, so a negative
    value here is a data-quality flag rather than an error in your code.

    good/bad: negative means the catalogue is wrong about the market, not that
    the market is over. Cross-check against ``closedTime`` and
    ``acceptingOrders`` before trusting it. Also note that event-level and
    market-level end dates differ, and the event view hides the long rungs --
    always compute this on the market.
    """
    if end is None:
        return None
    if isinstance(end, str):
        end = date.fromisoformat(end[:10])
    if isinstance(end, datetime):
        end = end.date()
    now = now or date.today()
    if isinstance(now, datetime):
        now = now.date()
    return (end - now).days


def market_age(
    created: date | datetime | str | None, now: date | datetime | None = None
) -> int | None:
    """measures: days since the market was created.

    blind to: when it became *liquid*, which is usually much later.

    good/bad: discard the **first ~24 hours** of any price path as launch
    noise. Taiwan-2027's first 12-hour bucket reads 0.435, the second 0.235,
    and it then settles at 0.225 for weeks -- the opening print is not a prior.
    A market under a week old has no usable history at all.
    """
    if created is None:
        return None
    if isinstance(created, str):
        created = date.fromisoformat(created[:10])
    if isinstance(created, datetime):
        created = created.date()
    now = now or date.today()
    if isinstance(now, datetime):
        now = now.date()
    return (now - created).days


def outcome_price_sum(prices: Sequence[float | None]) -> float | None:
    """measures: the sum of prices across a mutually exclusive outcome set.

    blind to: whether the set is exhaustive, which is the usual reason the sum
    is wrong. *Nobel Peace Prize Winner 2026* sums to **0.606** -- not
    mispricing, just that the winner is usually not on the list.

    good/bad: see `sum_to_one_deviation`. **Never apply this to a
    date-ladder**: "X by date T" rungs are cumulative, not exclusive, and the
    Russia-Ukraine ceasefire ladder legitimately sums to **6.77**. Check
    ``negRisk`` first.
    """
    clean = [p for p in prices if p is not None]
    return sum(clean) if clean else None


def sum_to_one_deviation(
    prices: Sequence[float | None], years_to_resolution: float = 0.0, rate: float = 0.0
) -> dict[str, float | None]:
    """measures: how far an exclusive set's prices sit from their no-arbitrage total.

    The target is not 1.0 but ``exp(-rate * years)``, because every outcome
    settles at the same future date and the whole set is discounted together.
    Returns the raw sum, the target, and the deviation.

    blind to: unpriced residual mass and to ask-only placeholder quotes, which
    confound the reading badly. On Polymarket's two deepest long-dated
    exclusive sets the mids sum to 0.9005 and 0.8795 -- but 88 of those 128
    outcomes are placeholders at the 0.001 minimum tick with no bid. Valuing
    them at zero implies a 4.95% annualized discount; valuing them at their ask
    implies 0.55%. The honest statement is that the measurement cannot narrow
    it.

    good/bad: **this is the strongest single quality test for an exclusive
    set** -- it catches non-exhaustive candidate fields, stale mids and broken
    books in one shot. Want deviation within +/-0.02. On 255 exclusive
    political events the median sum is 0.994 at 31-180 days but only **45% are
    within +/-2%**, and beyond 365 days **61% are more than 5% away**.
    """
    total = outcome_price_sum(prices)
    if total is None:
        return {"sum": None, "target": None, "deviation": None, "relative": None}
    target = math.exp(-rate * years_to_resolution)
    return {
        "sum": total,
        "target": target,
        "deviation": total - target,
        "relative": (total - target) / target if target else None,
    }


# ==========================================================================
# 4.  Is the contract well specified?
# ==========================================================================

_SOURCE_PATTERN = re.compile(
    r"\b(Associated Press|AP\b|Reuters|Bloomberg|"
    r"Bureau of Labor Statistics|BLS\b|FRED\b|Federal Reserve|FOMC|"
    r"Census Bureau|EIA\b|World Bank|IMF\b|"
    r"Congressional Record|Federal Register|Secretary of State|"
    r"official (?:results|tally|count|statement)|"
    r"https?://)",
    re.IGNORECASE,
)

_CONSENSUS_PATTERN = re.compile(
    r"consensus of (?:a )?credible (?:sources|reporting)|credible reporting",
    re.IGNORECASE,
)

_DURATION_PATTERN = re.compile(
    r"\b(\d+)[- ](?:calendar[- ])?(?:consecutive[- ])?(day|hour|week|month)s?\b",
    re.IGNORECASE,
)


def resolution_text_length(text: str | None) -> int:
    """measures: characters of resolution prose.

    blind to: whether the prose is any good. Length is a proxy for specificity
    and nothing more.

    good/bad: Polymarket's median is **1,155 characters** and its maximum
    5,456; ``description`` is present on 848/848 markets sampled. Under ~200
    characters the contract is almost certainly under-specified. Zero means
    the venue serves no criteria at all, which is the PredictIt case.
    """
    return len(text or "")


def names_machine_checkable_source(text: str | None) -> bool:
    """measures: whether the criteria name a specific, checkable authority.

    blind to: whether the named source will actually publish the number, and to
    the difference between a source that *reports* and a source that
    *determines*.

    good/bad: True is what you want and is rare in geopolitics. Kalshi wins
    here structurally rather than textually -- its ``settlement_sources`` field
    names the BLS, FRED and Fed series a contract settles against, so
    resolution is arithmetic. Polymarket's standard is "a consensus of credible
    sources", with the text explicitly providing that where government
    statements conflict with field reporting, **"the reporting will take
    precedence"** -- precise criteria, discretionary judge.
    """
    if not text:
        return False
    return bool(_SOURCE_PATTERN.search(text))


def resolution_quality(text: str | None) -> dict[str, Any]:
    """measures: a structured read of the resolution contract.

    Reports length, whether a checkable source is named, whether the
    "consensus of credible reporting" standard is invoked, and whether a
    **duration test** appears -- the feature that separates a rigorous
    geopolitical contract from a vague one. The Russia-Ukraine ceasefire market
    specifies a **10-calendar-day continuity test** with four worked qualifying
    and non-qualifying precedents; the NATO-Russia market defines a "military
    encounter" with an inclusion list, an exclusion list and named historical
    precedents used as calibration.

    blind to: everything that matters most -- whether the judge will apply the
    text as written. Three documented Polymarket failures all sit in exactly
    the categories this study cares about, including a **$237m** market that
    resolved No against 40+ outlets' reporting.

    good/bad: want ``names_source`` True or ``has_duration_test`` True, with
    length over ~500. ``consensus_standard`` True without a duration test is
    the weakest combination and should be flagged, not excluded -- it is the
    modal Polymarket geopolitics contract.
    """
    text = text or ""
    durations = _DURATION_PATTERN.findall(text)
    return {
        "length": len(text),
        "names_source": names_machine_checkable_source(text),
        "consensus_standard": bool(_CONSENSUS_PATTERN.search(text)),
        "has_duration_test": bool(durations),
        "durations": ["".join(d) for d in durations][:5],
        "served": bool(text),
    }


def dispute_flags(resolution: Mapping[str, Any] | None) -> dict[str, Any]:
    """measures: whether settlement was contested, from Polymarket ``/v2/resolutions``.

    blind to: disputes that never reached the oracle, and to concentration in
    the vote itself, which is reported off-platform if at all.

    good/bad: ``was_disputed`` True is a quality flag worth storing forever, not
    a disqualifier. Two structural facts belong with it: **resolution is not
    strictly 0/1** -- a UMA "Unknown / 50-50" vote settles each token at $0.50,
    so the outcome column is not boolean -- and ``price`` is **1e18-scaled**,
    with ``"69"`` as the sentinel for unresolved. An open dispute means the
    market has no usable price at all.
    """
    if not resolution:
        return {"served": False}
    raw = resolution.get("price")
    settled = None
    if raw is not None and str(raw) != "69":
        try:
            settled = float(raw) / 1e18
        except (TypeError, ValueError):
            settled = None
    return {
        "served": True,
        "status": resolution.get("status"),
        "settled_value": settled,
        "is_fifty_fifty": settled is not None and abs(settled - 0.5) < 1e-9,
        "was_disputed": bool(resolution.get("was_disputed")),
        "extended_review": bool(resolution.get("extended_review")),
        "unresolved_sentinel": str(raw) == "69",
    }


# ==========================================================================
# 5.  Turning a price into a probability
# ==========================================================================


def discount_factor(years: float, rate: float = 0.0481) -> float:
    """measures: ``exp(-rate * years)`` -- what a dollar at resolution is worth now.

    The default is the 2-year Treasury par yield on 2026-09-25 (**4.81%**);
    the curve that day was 3m 4.24%, 1y 4.50%, 2y 4.81%, 3y 4.94%. Use the
    point matching the horizon.

    blind to: holding rewards, which offset it. Polymarket pays an annualized
    rate on positions in a curated set -- **555 markets carry
    ``holdingRewardsEnabled: true``** and they are disproportionately the
    markets this study cares about. Apply the discount correction **only where
    that flag is false.**

    good/bad: the correction is small at months and material at years. Anchor
    on the Treasury curve; a widely cited settlement-wedge range from the
    literature is labelled UNSUPPORTED in the source doc and should not be
    substituted for it.
    """
    return math.exp(-rate * years)


def discount_adjust(price: float, years: float, rate: float = 0.0481) -> float:
    """measures: the price grossed back up to an undiscounted probability.

    ``price / exp(-rate * years)``. A non-yielding claim settling in ``years``
    should trade below its probability, so this raises it.

    blind to: holding rewards (see `discount_factor`) and to the possibility
    that the discount is not the whole story. What is confirmed from the
    literature is that a discount adjustment removes **48-88% of the apparent
    long-horizon miscalibration gradient**, leaving a residual statistically
    indistinguishable from zero -- so roughly half to nearly all of the
    "miscalibration" at range is arithmetic rather than error.

    good/bad: at 2 years and 4.81% the factor is 1.101, a 10% uplift. If that
    changes your conclusion, your conclusion was not robust.
    """
    return price / discount_factor(years, rate)


def longshot_adjust(price: float, cutoff: float = 0.10, factor: float = 0.80) -> float:
    """measures: the favourite-longshot haircut applied below ``cutoff``.

    blind to: the grouping the published estimate was computed under, which
    changes its sign. Equal-weighted, longshots lose **6.3c per dollar**;
    grouped by parent event they *gain* **4.1c per dollar**. The headline
    figure used here is that purchases **below 10c lose 19.3c per dollar**
    while those at or above 90c earn 0.83c, so a 5c quote corresponds to
    roughly a 4% true probability.

    good/bad: the bias is documented in Crypto and Politics and **absent in
    Sports**, so do not apply it venue-wide. Note it points the *opposite* way
    to the lock-up discount at the low end: a 5c conflict quote is
    simultaneously ~20% too high in relative terms and a few percent too low.
    They largely cancel, and that is not a reason to ignore either -- apply
    both, per market, conditional on the fee and rewards flags.
    """
    return price * factor if price < cutoff else price


def no_arbitrage_band(price: float, taker_rate: float = 0.04) -> float:
    """measures: the width of the band a notional taker fee opens around a price.

    ``2 * rate * p * (1 - p)`` -- Polymarket's shape, where
    ``fee = shares * rate * p * (1 - p)``.

    blind to: the profit-fee structure used by PredictIt, which is a different
    functional form entirely and much wider. Use
    ``predictit.fee_band_width`` for that: **0.0526 at p = 0.50** against
    **0.0200** here.

    good/bad: 2 points at p=0.5 for Polymarket politics; **zero for
    geopolitics**, which is genuinely fee-free (``feeType: null``, verified
    live). Re-read the fee fields on every catalogue refresh -- politics fees
    were introduced after this project's backlog was written and the exemption
    is not guaranteed to persist.
    """
    return 2.0 * taker_rate * price * (1.0 - price)


# ==========================================================================
# 6.  Ladders -- a row of "by date T" markets is a CDF
# ==========================================================================


def _sorted_rungs(rungs: Sequence[Rung]) -> list[Rung]:
    return sorted(rungs, key=lambda r: r.horizon)


#: Deadline phrasings seen in real ladder titles.  Ordered most specific first,
#: because "before 2027" and "by December 31, 2026" can appear in one title and
#: the explicit date is the one that matters.
_DEADLINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"by\s+(?P<m>[A-Z][a-z]+)\s+(?P<d>\d{1,2}),?\s+(?P<y>\d{4})", re.I),
    re.compile(r"by\s+(?:the\s+)?end\s+of\s+(?P<m>[A-Z][a-z]+)\s+(?P<y>\d{4})", re.I),
    re.compile(r"by\s+(?P<m>[A-Z][a-z]+)\s+(?P<y>\d{4})", re.I),
    re.compile(r"by\s+(?:the\s+)?end\s+of\s+(?P<y>\d{4})", re.I),
    re.compile(r"before\s+(?P<y>\d{4})", re.I),
    re.compile(r"in\s+(?P<y>\d{4})\s*\?*$", re.I),
)

_MONTHS = {
    m: i
    for i, m in enumerate(
        ("january february march april may june july august september "
         "october november december").split(),
        1,
    )
}


def parse_deadline(title: str) -> date | None:
    """measures: the deadline a ladder rung's title encodes, as a date.

    Handles the phrasings that actually occur: "by October 31, 2026", "by end of
    2026", "before 2027", "by December 2027".

    blind to: **the difference between the title and the contract.** Titles are
    editorial and they disagree with their own slugs -- the Taiwan event's title
    says "by end of 2026" while its slug says ``before-2027``. Those happen to
    mean the same instant; nothing guarantees the next pair will. Where a
    market-level ``endDate`` exists, prefer it and use this only to *order*
    rungs whose dates are missing or past-dated.

    good/bad: ``None`` means the title carries no parseable deadline, which is
    the signal that the market is not a date-ladder rung at all. "before YYYY"
    is normalised to 1 January of that year and "by end of YYYY" to 31 December,
    so the two differ by a day rather than silently colliding.
    """
    for pat in _DEADLINE_PATTERNS:
        m = pat.search(title or "")
        if not m:
            continue
        groups = m.groupdict()
        year = int(groups["y"])
        month_name = (groups.get("m") or "").lower()
        if month_name and month_name in _MONTHS:
            month = _MONTHS[month_name]
            if groups.get("d"):
                return date(year, month, int(groups["d"]))
            # "by end of <month> <year>" -> last day of that month
            if month == 12:
                return date(year, 12, 31)
            return date(year, month + 1, 1) - __import__("datetime").timedelta(days=1)
        if "end" in m.group(0).lower():
            return date(year, 12, 31)
        if m.group(0).lower().startswith("before"):
            return date(year, 1, 1)
        return date(year, 12, 31)
    return None


def rungs_from_markets(
    markets: Iterable[Mapping[str, Any]],
    title_key: str = "question",
    price_key: str = "price",
    bid_key: str = "bestBid",
    ask_key: str = "bestAsk",
    end_key: str = "endDate",
) -> list[Rung]:
    """measures: nothing directly -- it assembles a ladder from venue records so
    everything else in this section can measure it.

    Takes the deadline from ``end_key`` where it is present **and in the
    future-or-past-but-plausible range**, otherwise falls back to
    `parse_deadline` on the title. That order matters: Polymarket's ``endDate``
    is authoritative when sane but **15 of 440 open geopolitics events are
    past-dated, the worst by −668 days**, and a past-dated rung sorts to the
    front and corrupts every difference downstream.

    blind to: whether the markets really belong to one question. It will happily
    build a "ladder" out of unrelated markets that happen to name dates, and the
    coherence tests will then report violations that mean nothing. Group by
    series or by a curated concept mapping first -- Polymarket's ``series_id``
    covers only about a third of open geopolitics events, so the rest needs a
    hand-maintained mapping.

    good/bad: check ``len(rungs)`` against the number of markets passed. A large
    drop means the titles are not date-phrased and the set is probably an
    *exclusive* outcome group, which must be summed rather than differenced.
    """
    out: list[Rung] = []
    for m in markets:
        title = str(m.get(title_key) or "")
        horizon: date | None = None
        raw_end = m.get(end_key)
        if raw_end:
            try:
                horizon = date.fromisoformat(str(raw_end)[:10])
            except ValueError:
                horizon = None
        if horizon is None or not (date(2000, 1, 1) <= horizon <= date(2100, 1, 1)):
            horizon = parse_deadline(title)
        if horizon is None:
            continue
        price = m.get(price_key)
        if price is None:
            bid, ask = m.get(bid_key), m.get(ask_key)
            if bid is not None and ask is not None:
                price = (float(bid) + float(ask)) / 2.0
        if price is None:
            continue
        out.append(
            Rung(
                label=title or str(m.get("slug") or horizon),
                horizon=horizon,
                price=float(price),
                bid=float(m[bid_key]) if m.get(bid_key) is not None else None,
                ask=float(m[ask_key]) if m.get(ask_key) is not None else None,
            )
        )
    return _sorted_rungs(out)


def discount_adjust_ladder(
    rungs: Sequence[Rung], asof: date, rate: float = 0.0481
) -> list[Rung]:
    """measures: the ladder with each rung grossed up to an undiscounted probability.

    **Run this before any other ladder function.** Each rung settles at a
    different date, so each carries a different discount. Differencing raw
    prices therefore mixes the discount gradient into the interval mass, and
    because the far rungs are discounted hardest it biases every interval mass
    downward -- and can manufacture a *negative* mass, and so a spurious
    monotonicity violation, out of a perfectly coherent ladder.

    blind to: holding rewards, which offset the discount on the ~555 flagged
    Polymarket markets. Where ``holdingRewardsEnabled`` is true, skip this.

    good/bad: at a 4.81% rate the correction is under 0.5% inside three months
    and about 10% at two years. It matters for the 2027 rungs and is noise for
    the front ones.
    """
    out = []
    for r in _sorted_rungs(rungs):
        years = max(0.0, (r.horizon - asof).days / 365.25)
        f = discount_factor(years, rate)
        out.append(
            Rung(
                label=r.label,
                horizon=r.horizon,
                price=r.price / f,
                bid=(r.bid / f) if r.bid is not None else None,
                ask=(r.ask / f) if r.ask is not None else None,
            )
        )
    return out


def ladder_monotonicity(rungs: Sequence[Rung]) -> dict[str, Any]:
    """measures: whether the implied CDF is non-decreasing in the deadline.

    "X by June" cannot be more likely than "X by December": the June event is a
    subset of the December one. Any decrease is incoherent.

    blind to: whether the violation is tradeable -- that needs the spread, so
    use `ladder_arbitrage_violations`. A one-tick decrease on a market with a
    2c spread is noise, not an arbitrage.

    good/bad: ``n_violations == 0`` is the pass. The reference case passes:
    Polymarket's 15 open Russia-Ukraine ceasefire rungs run monotone from
    **0.065 to 0.705** between Oct 2026 and Dec 2027, with relative spreads
    narrowing 15.4% to 1.4%. A ladder with violations larger than the tick is
    either stale on some rungs or not actually a ladder.
    """
    ordered = _sorted_rungs(rungs)
    violations = []
    for a, b in zip(ordered, ordered[1:]):
        if b.price < a.price - 1e-12:
            violations.append(
                {
                    "from": a.label,
                    "to": b.label,
                    "from_price": a.price,
                    "to_price": b.price,
                    "drop": a.price - b.price,
                }
            )
    return {
        "n_rungs": len(ordered),
        "monotone": not violations,
        "n_violations": len(violations),
        "worst_drop": max((v["drop"] for v in violations), default=0.0),
        "violations": violations,
    }


def ladder_interval_mass(
    rungs: Sequence[Rung], asof: date | None = None
) -> list[dict[str, Any]]:
    """measures: the probability mass falling in each interval between rungs.

    This is the whole point of treating a ladder as a CDF. The first rung's
    mass is its own price (mass from now to its deadline); each later rung's is
    the difference from its predecessor. It is the direct analogue of
    differencing an option strike ladder into a density over price.

    Pass ``asof`` -- normally today -- so the **first** interval has a length
    too. Without it the first rung's ``interval_days`` is ``None`` and its
    ``mass_per_day`` is undefined, which quietly drops the first and often
    largest interval out of any density comparison.

    blind to: anything happening between the rungs -- the resolution is the
    rung spacing and nothing finer. Also blind to the discount unless
    `discount_adjust_ladder` ran first.

    good/bad: every mass should be **non-negative**. Negative mass means either
    a monotonicity violation or an unadjusted discount gradient; check which
    before concluding the market is broken. A mass distribution concentrated in
    one interval is informative; one spread near-uniformly across intervals
    with tiny values is a maker interpolating.
    """
    ordered = _sorted_rungs(rungs)
    out = []
    prev_price = 0.0
    prev_date: date | None = asof
    for r in ordered:
        mass = r.price - prev_price
        days = (r.horizon - prev_date).days if prev_date else None
        out.append(
            {
                "label": r.label,
                "horizon": r.horizon,
                "cumulative": r.price,
                "mass": mass,
                "interval_days": days,
                "mass_per_day": (mass / days) if days and days > 0 else None,
                "negative": mass < -1e-12,
            }
        )
        prev_price = r.price
        prev_date = r.horizon
    return out


def ladder_hazard(
    rungs: Sequence[Rung], asof: date | None = None
) -> list[dict[str, Any]]:
    """measures: the conditional probability of resolving in each interval, given it has not yet.

    ``h_i = mass_i / (1 - F_{i-1})``. The hazard is the shape that tells you
    what the market actually believes about *timing*, as opposed to
    eventuality, and it is the ladder's most informative derived quantity.

    Two normalisations are returned because rungs are rarely evenly spaced.
    ``hazard_per_day`` is the linear ``h / days`` -- adequate for ranking.
    ``hazard_rate_per_day`` is ``-ln(1 - h) / days``, the continuous force of
    resolution, and it is the one to use when comparing a six-month rung with a
    one-month rung: the linear version understates long intervals, so a flat
    linear profile across widening rungs can hide a genuinely rising hazard.

    blind to: whether the shape is a belief or an interpolation. That
    distinction is in `NOT_COMPUTABLE` as ``market_maker_identity``.

    good/bad: a **rising** hazard says the market expects resolution to become
    more likely as time passes (peace talks maturing); a **falling** hazard
    says the window is closing. A **flat** hazard across many rungs, with the
    per-day rate near-constant to two figures, is the signature of a smooth
    interpolation between the front rung and 1.0 rather than independent
    pricing -- especially when lifetime volume on those rungs is four figures.
    On the reference ladder the four rungs beyond a year carry lifetime volumes
    of **$818, $976, $1,643 and $3,018** with 1c depth of **$88 to $1,215**,
    so a smooth hazard there should be read as one maker, not as 44 traders.
    """
    out = []
    survival = 1.0
    for row in ladder_interval_mass(rungs, asof):
        mass = row["mass"]
        hazard = (mass / survival) if survival > 1e-12 else None
        days = row["interval_days"]
        out.append(
            {
                "label": row["label"],
                "horizon": row["horizon"],
                "mass": mass,
                "survival_before": survival,
                "hazard": hazard,
                "interval_days": days,
                # Linear normalisation: simple, and fine for ranking rungs.
                "hazard_per_day": (hazard / days) if hazard is not None and days else None,
                # The correct continuous force of resolution, which is what to
                # compare across unequal rung spacings: a 6-month rung and a
                # 1-month rung are only commensurable through -ln(1-h)/days.
                # The linear version understates long intervals.
                "hazard_rate_per_day": (
                    -math.log(1.0 - hazard) / days
                    if hazard is not None and days and 0.0 <= hazard < 1.0
                    else None
                ),
                # A conditional probability outside [0, 1] is not a hazard. It
                # means the cumulative curve left [0, 1] -- stale quotes, or a
                # set of *exclusive* markets being read as a cumulative ladder
                # (the ceasefire date ladder legitimately sums to 6.77, and
                # cumulating it would produce exactly this). Flagged rather
                # than clipped, because clipping hides the input error.
                "implausible": hazard is not None and not (-1e-9 <= hazard <= 1 + 1e-9),
            }
        )
        survival -= mass
    return out


def ladder_arbitrage_violations(rungs: Sequence[Rung]) -> list[dict[str, Any]]:
    """measures: monotonicity violations that survive the bid-ask spread.

    A violation is only money if you can **buy the later rung at its ask and
    sell the earlier rung at its bid** for a credit: the later contract
    dominates the earlier one (it pays whenever the earlier does, and
    sometimes more), so ``ask_later < bid_earlier`` is a riskless credit
    before fees.

    blind to: fees, capital lock-up over the holding period, and execution --
    it reports the gross edge. Net it against `no_arbitrage_band` or
    ``predictit.fee_band_width`` before believing it.

    good/bad: an empty list is the expected result and the healthy one. A
    non-empty list on a venue with real depth is a genuine finding; on a
    four-figure-volume rung it is more likely a stale quote than an
    opportunity. Note the one peer-reviewed cross-venue study found identical
    contracts diverging across exchanges with **arbitrage opportunities
    peaking in the final two weeks** -- so these are real, and they cluster
    exactly where horizons are shortest.
    """
    ordered = _sorted_rungs(rungs)
    out = []
    for i, earlier in enumerate(ordered):
        for later in ordered[i + 1 :]:
            if earlier.bid is None or later.ask is None:
                continue
            if later.ask < earlier.bid - 1e-12:
                out.append(
                    {
                        "sell": earlier.label,
                        "sell_bid": earlier.bid,
                        "buy": later.label,
                        "buy_ask": later.ask,
                        "gross_credit": earlier.bid - later.ask,
                    }
                )
    return out


def ladder_terminal_mass(rungs: Sequence[Rung]) -> dict[str, float | None]:
    """measures: the probability left beyond the last rung -- ``1 - F(T_max)``.

    blind to: nothing much; it is arithmetic. But it is the number people skip.

    good/bad: it says how much of the question the ladder prices at all. A
    terminal mass of 0.295 on the reference ceasefire ladder means the market
    puts ~30% on the war *not* ending by December 2027, and the ladder is
    silent about when that 30% resolves. **A terminal mass above ~0.5 means the
    ladder is mostly about the tail it does not cover**, and any implied median
    date is extrapolation rather than measurement.
    """
    ordered = _sorted_rungs(rungs)
    if not ordered:
        return {"last_cumulative": None, "terminal_mass": None, "last_horizon": None}
    last = ordered[-1]
    return {
        "last_cumulative": last.price,
        "terminal_mass": 1.0 - last.price,
        "last_horizon": last.horizon,
    }


def ladder_implied_quantile(rungs: Sequence[Rung], q: float = 0.5) -> date | None:
    """measures: the date by which the market implies the event resolves with probability ``q``.

    Linear interpolation between the bracketing rungs. ``q=0.5`` gives the
    implied median resolution date -- the single most communicable number a
    ladder produces, and the thing the user's framing is *for*: a row of "by
    date" contracts answers "when", not just "whether".

    blind to: the shape between rungs, and to everything beyond the last rung.

    good/bad: returns ``None`` when the ladder never reaches ``q``, which is
    the correct answer and not a failure -- check `ladder_terminal_mass` and
    say the market does not price that quantile, rather than extrapolating.
    """
    ordered = _sorted_rungs(rungs)
    if not ordered or ordered[-1].price < q:
        return None
    prev_p = 0.0
    prev_d: date | None = None
    for r in ordered:
        if r.price >= q:
            if prev_d is None or r.price == prev_p:
                return r.horizon
            frac = (q - prev_p) / (r.price - prev_p)
            span = (r.horizon - prev_d).days
            return prev_d.fromordinal(prev_d.toordinal() + int(round(frac * span)))
        prev_p, prev_d = r.price, r.horizon
    return None


def ladder_report(
    rungs: Sequence[Rung],
    asof: date | None = None,
    rate: float = 0.0481,
    apply_discount: bool = True,
) -> dict[str, Any]:
    """measures: the whole ladder, coherently, in one call.

    Runs `discount_adjust_ladder` first (unless the rungs are reward-eligible,
    in which case pass ``apply_discount=False``), then monotonicity, interval
    masses, hazards, arbitrage, terminal mass and the implied quartiles.

    blind to: everything in `NOT_COMPUTABLE`, and in particular to whether one
    maker priced the whole curve.

    good/bad: a usable ladder is ``monotone``, has no negative masses, an empty
    ``arbitrage`` list, a terminal mass under ~0.5, and a hazard that varies
    across rungs. The reference Russia-Ukraine ladder passes every structural
    test and still fails on depth -- which is the lesson: **coherence and
    tradeability are independent, and a ladder can be perfectly coherent
    because one participant made it so.**
    """
    asof = asof or date.today()
    working = list(discount_adjust_ladder(rungs, asof, rate)) if apply_discount else _sorted_rungs(rungs)
    masses = ladder_interval_mass(working, asof)
    return {
        "asof": asof,
        "discount_applied": apply_discount,
        "rate": rate if apply_discount else None,
        "n_rungs": len(working),
        "monotonicity": ladder_monotonicity(working),
        "interval_mass": masses,
        "n_negative_mass": sum(1 for m in masses if m["negative"]),
        "hazard": (hz := ladder_hazard(working, asof)),
        "n_implausible_hazard": sum(1 for h in hz if h["implausible"]),
        "arbitrage": ladder_arbitrage_violations(working),
        "terminal": ladder_terminal_mass(working),
        "implied_q25": ladder_implied_quantile(working, 0.25),
        "implied_median": ladder_implied_quantile(working, 0.50),
        "implied_q75": ladder_implied_quantile(working, 0.75),
    }


# ==========================================================================
# 7.  Composite
# ==========================================================================


def quality_report(
    book: OrderBook | None = None,
    *,
    last_trade: float | None = None,
    volume: float | None = None,
    open_interest: float | None = None,
    holdings: Sequence[float] | None = None,
    prices: Sequence[float] | None = None,
    dates: Sequence[Any] | None = None,
    volumes: Sequence[float] | None = None,
    end_date: Any = None,
    created: Any = None,
    tick: float | None = None,
    neg_risk: bool | None = None,
    outcome_prices: Sequence[float | None] | None = None,
    resolution_text: str | None = None,
    resolution: Mapping[str, Any] | None = None,
    years: float = 0.0,
    rate: float = 0.0481,
) -> dict[str, Any]:
    """measures: every metric in this module that the supplied inputs support.

    Missing inputs produce ``None`` rather than an exception, so the same call
    scores a Polymarket market with a full book and a PredictIt contract with
    four touch prices -- and the ``None``s are then the honest map of what that
    venue does not serve. Read them together with `VENUE_COVERAGE`.

    blind to: everything in `NOT_COMPUTABLE`.

    good/bad: there is deliberately **no single composite score**. The
    measurements do not commensurate -- a market can have a tight spread and no
    depth, or deep books and 128x turnover -- and collapsing them to one number
    is how ``liquidityNum`` came to rank a zero-bid contract as its event's
    most liquid. Filter on the individual gates instead.
    """
    out: dict[str, Any] = {}
    if book is not None:
        out["book"] = depth_profile(book)
        out["imbalance"] = book_imbalance(book)
        out["sweep_10k_ask"] = sweep_cost(book, "ask", 10_000)
        out["mid_vs_last"] = mid_last_divergence(book, last_trade)
        mid = midpoint(book)
        if tick is not None and mid:
            out["relative_tick"] = tick_size_relative(tick, mid)
    if volume is not None and open_interest is not None:
        out["turnover"] = volume_to_open_interest(volume, open_interest)
    out["open_interest"] = open_interest
    if holdings:
        out["holders"] = holder_concentration(holdings)
    if prices:
        out["staleness"] = path_staleness(prices)
        out["distinct_prices"] = distinct_price_levels(prices)
        out["info_rate_1d"] = information_rate(prices, 1)
        out["info_rate_7d"] = information_rate(prices, 7)
    if dates:
        out["trading_days"] = distinct_trading_days(dates, volumes)
        out["largest_gap_days"] = largest_gap_days(dates)
    out["days_to_resolution"] = time_to_resolution(end_date)
    out["market_age_days"] = market_age(created)
    out["neg_risk"] = neg_risk
    if outcome_prices:
        out["outcome_sum"] = sum_to_one_deviation(outcome_prices, years, rate)
    out["resolution_text"] = resolution_quality(resolution_text)
    out["resolution"] = dispute_flags(resolution)
    out["quote_age"] = quote_age()
    return out
