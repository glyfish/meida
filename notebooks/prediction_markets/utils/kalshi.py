"""Kalshi read-only reader: series, events, markets, candlesticks, settlement.

Kalshi is the CFTC-regulated venue (KalshiEX LLC, a designated contract market).
Everything here is unauthenticated GET traffic against the public market-data
surface. Nothing in this module can sign, order, hold a key or touch a wallet;
the venue is being measured, not traded.

THE ONE THING TO KNOW
---------------------
Kalshi partitions market data into a *live* tier and a *historical* tier, split
by the ``market_settled_ts`` cutoff from ``GET /historical/cutoff`` (observed
2026-07-28 on 2026-09-26, i.e. a trailing window of about two months). A market
settled before the cutoff **404s on every live route** -- ``/markets/{t}``,
``/events/{e}?with_nested_markets=true`` and
``/series/{s}/markets/{t}/candlesticks`` all deny it exists -- and is served
instead by ``/historical/markets`` and
``/historical/markets/{ticker}/candlesticks``.

Probe only the live tier and you conclude Kalshi deletes its past. It does not:
the historical tier goes back to 2021-07 with full one-minute candlesticks.
``Reader`` routes every call to the right tier for you.

The two tiers also **rename every numeric field**. Live says
``price.close_dollars``, ``volume_fp``, ``open_interest_fp``; historical says
``price.close``, ``volume``, ``open_interest``, for the identical object. Code
written against one tier silently reads zeros and empty prices from the other.
``normalise_candle`` collapses both onto one shape.

LADDERS
-------
Kalshi's native unit is not the single market -- it is the *event*, a set of
markets over one underlying at different strikes or dates. A ``greater`` strike
ladder (``KXCPIYOY-26AUG`` at T2.5, T2.6 ... T5.0) is a discrete **survival
function** over the CPI print; differencing adjacent rungs gives the density,
exactly as an option strike ladder does over price. ``Ladder`` makes that a
first-class object and scores its internal coherence -- monotonicity, negative
implied mass, arbitrage violations -- which is a quality test no single market
can support.
"""

from __future__ import annotations

import json
import re
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

import httpx

BASE = "https://api.elections.kalshi.com/trade-api/v2"
USER_AGENT = "meida-research/0.1 (read-only market-structure survey)"

# Kalshi accepts exactly these candlestick widths, in minutes. 5, 15, 30, 240,
# 720 and 10080 are all HTTP 400.
PERIODS = (1, 60, 1440)
MAX_CANDLES = 5000  # per request; asking for more is a 400 naming the ceiling
MAX_BATCH_TICKERS = 100  # GET /markets/candlesticks?market_tickers=

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

TARGET_CATEGORIES = ("Economics", "Financials", "Politics", "Elections")


class KalshiAPIError(RuntimeError):
    """A Kalshi response that was not a 200 and not a handled 429."""


# --------------------------------------------------------------------------
# field normalisation
# --------------------------------------------------------------------------
#
# Live tier suffixes money with _dollars and quantities with _fp. Historical
# tier uses the bare name. Same object, same meaning, two spellings.


def _num(d: dict | None, *names: str) -> float | None:
    """First present key among ``names``, as a float. None if absent or null."""
    if not d:
        return None
    for n in names:
        if n in d and d[n] is not None:
            try:
                return float(d[n])
            except (TypeError, ValueError):
                return None
    return None


def _ohlc(d: dict | None) -> dict[str, float | None]:
    """Normalise an OHLC sub-object across both tiers."""
    return {
        "open": _num(d, "open", "open_dollars"),
        "high": _num(d, "high", "high_dollars"),
        "low": _num(d, "low", "low_dollars"),
        "close": _num(d, "close", "close_dollars"),
    }


def normalise_candle(c: dict) -> dict:
    """One shape for a candlestick from either tier.

    ``price`` is the *traded* price and is absent in a period with no trades --
    live tier returns ``{}`` or only ``previous_dollars``. ``yes_bid`` and
    ``yes_ask`` are the quote and are present whether or not anything traded,
    which is what makes a historical spread series possible at all.

    ``mean`` is Kalshi's volume-weighted mean traded price for the period. It is
    the honest point estimate for the period; ``close`` is the last print and is
    noisier on thin markets.
    """
    px = c.get("price") or {}
    bid = _ohlc(c.get("yes_bid"))
    ask = _ohlc(c.get("yes_ask"))
    mid = None
    if bid["close"] is not None and ask["close"] is not None:
        mid = (bid["close"] + ask["close"]) / 2.0
    spread = None
    if bid["close"] is not None and ask["close"] is not None:
        spread = ask["close"] - bid["close"]
    ts = c.get("end_period_ts")
    return {
        "ts": ts,
        "date": datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d") if ts else None,
        "open": _num(px, "open", "open_dollars"),
        "high": _num(px, "high", "high_dollars"),
        "low": _num(px, "low", "low_dollars"),
        "close": _num(px, "close", "close_dollars"),
        "mean": _num(px, "mean", "mean_dollars"),
        "previous": _num(px, "previous", "previous_dollars"),
        "yes_bid": bid["close"],
        "yes_ask": ask["close"],
        "mid": mid,
        "spread": spread,
        "volume": _num(c, "volume", "volume_fp") or 0.0,
        "open_interest": _num(c, "open_interest", "open_interest_fp") or 0.0,
        "traded": px.get("close") is not None or px.get("close_dollars") is not None,
    }


def normalise_market(m: dict) -> dict:
    """One shape for a market from either tier, with the settlement record.

    ``result`` is the settled outcome: ``yes``, ``no``, ``""`` while open, and
    on rare occasions ``void``/``all_no``. ``expiration_value`` is the realised
    value of the underlying as a human string ("Above 3.3%") -- Kalshi tells you
    not only which side won but what the world actually did, which Polymarket
    never does.
    """
    return {
        "ticker": m.get("ticker"),
        "event_ticker": m.get("event_ticker"),
        "series_ticker": (m.get("ticker") or "").split("-")[0],
        "title": m.get("title"),
        "subtitle": m.get("subtitle"),
        "yes_sub_title": m.get("yes_sub_title"),
        "market_type": m.get("market_type"),
        "strike_type": m.get("strike_type"),
        "floor_strike": m.get("floor_strike"),
        "cap_strike": m.get("cap_strike"),
        "custom_strike": m.get("custom_strike"),
        "rules_primary": m.get("rules_primary"),
        "rules_secondary": m.get("rules_secondary"),
        "open_time": m.get("open_time"),
        "close_time": m.get("close_time"),
        "expected_expiration_time": m.get("expected_expiration_time"),
        "expiration_time": m.get("expiration_time"),
        "latest_expiration_time": m.get("latest_expiration_time"),
        "settlement_ts": m.get("settlement_ts"),
        "status": m.get("status"),
        "result": m.get("result"),
        "expiration_value": m.get("expiration_value"),
        "settlement_value": _num(m, "settlement_value_dollars", "settlement_value"),
        "last_price": _num(m, "last_price_dollars", "last_price"),
        "yes_bid": _num(m, "yes_bid_dollars", "yes_bid"),
        "yes_ask": _num(m, "yes_ask_dollars", "yes_ask"),
        "yes_bid_size": _num(m, "yes_bid_size_fp", "yes_bid_size"),
        "yes_ask_size": _num(m, "yes_ask_size_fp", "yes_ask_size"),
        "liquidity": _num(m, "liquidity_dollars", "liquidity"),
        "volume": _num(m, "volume_fp", "volume") or 0.0,
        "volume_24h": _num(m, "volume_24h_fp", "volume_24h") or 0.0,
        "open_interest": _num(m, "open_interest_fp", "open_interest") or 0.0,
        "notional_value": _num(m, "notional_value_dollars", "notional_value"),
        "can_close_early": m.get("can_close_early"),
    }


def outcome(m: dict) -> float | None:
    """The settled label as a number in [0, 1], or None if it is not a label.

    ``result`` is ``yes``, ``no``, ``""`` (still open) -- or ``scalar``, and
    that last one is a trap that will silently flatter any calibration you
    compute.

    A ``scalar`` market did **not** settle against the world. Kalshi halted it
    and paid out at a price, either because the underlying stopped being
    reportable or because a rule let it settle at the last trade. The observed
    values are fractional and are plainly the market's own quote rather than an
    outcome: a Netherlands election paid ``0.5`` to two different parties, a
    conviction market paid ``0.8``, and six Disney-subscriber rungs paid 0.94,
    0.68, 0.64, 0.44, 0.32 and 0.28 in exact strike order. Scored as truth,
    such a row makes the forecast look perfect because the "outcome" *is* the
    forecast. This is Kalshi's analogue of a UMA 50-50 vote on Polymarket.

    So ``scalar`` returns None: it is excluded from the labelled corpus by
    construction, and ``settlement_value`` is kept on the row so the exclusion
    stays auditable.
    """
    if m.get("result") not in ("yes", "no"):
        return None
    sv = m.get("settlement_value")
    if sv is not None:
        return float(sv)
    return 1.0 if m["result"] == "yes" else 0.0


def parse_ts(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


# --------------------------------------------------------------------------
# the client
# --------------------------------------------------------------------------


class Reader:
    """Paced, unauthenticated reader that routes across the live/historical split.

    No credential is ever constructed or sent: the only header is a User-Agent.
    """

    def __init__(
        self,
        pace: float = 0.12,
        timeout: float = 90.0,
        client: httpx.Client | None = None,
        log: Any = None,
    ) -> None:
        self.pace = pace
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=timeout
        )
        self._last = 0.0
        self._cutoff: dict[str, int] | None = None
        self.n_requests = 0
        self.n_429 = 0
        self.log = log or (lambda *a: None)

    # -- plumbing ---------------------------------------------------------

    def _sleep(self) -> None:
        wait = self.pace - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def get(self, path: str, allow_404: bool = False, **params: Any) -> dict | None:
        """One GET, paced, with 429 backoff. Returns None on an allowed 404."""
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in range(6):
            self._sleep()
            r = self._client.get(BASE + path, params=params)
            self.n_requests += 1
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                self.n_429 += 1
                delay = float(r.headers.get("Retry-After") or (2 ** attempt))
                self.log(f"429 on {path}; sleeping {delay}s (total 429s {self.n_429})")
                time.sleep(delay)
                continue
            if r.status_code == 404 and allow_404:
                return None
            raise KalshiAPIError(f"{r.status_code} GET {path} {params} :: {r.text[:300]}")
        raise KalshiAPIError(f"gave up after repeated 429 on {path}")

    def paginate(self, path: str, key: str, limit: int | None = None,
                 cap: int | None = None, **params: Any) -> Iterator[dict]:
        """Cursor-walk a list endpoint.

        The per-page ceiling is **not uniform and not documented in the error**:
        ``/markets`` and ``/historical/markets`` take 1000 and reject 1001 with a
        message naming the field, while ``/events`` takes 200 and rejects 201
        with a bare ``{"code":"bad_request"}`` carrying no ``details`` at all --
        so a walk that assumes one ceiling fails opaquely on the other route.
        ``/series`` ignores ``limit`` entirely and returns the whole catalogue.
        The cursor is opaque; an empty page or an absent cursor ends the walk.
        """
        if limit is None:
            limit = 200 if path.rstrip("/").endswith("/events") else 1000
        cursor = None
        seen = 0
        while True:
            page = self.get(path, limit=limit, cursor=cursor, **params)
            rows = (page or {}).get(key) or []
            for row in rows:
                yield row
                seen += 1
                if cap and seen >= cap:
                    return
            cursor = (page or {}).get("cursor")
            if not rows or not cursor:
                return

    # -- the live/historical split ---------------------------------------

    def cutoff(self, refresh: bool = False) -> dict[str, int]:
        """``GET /historical/cutoff`` as unix seconds.

        ``market_settled_ts`` is the one that governs markets and candlesticks.
        Kalshi advances these forward over time, so a job that caches the value
        across days will start missing markets that have since crossed over.
        Re-read it every run.
        """
        if self._cutoff is None or refresh:
            raw = self.get("/historical/cutoff") or {}
            self._cutoff = {k: parse_ts(v) for k, v in raw.items()}
            self._cutoff["_raw"] = raw
        return self._cutoff

    def is_historical(self, market: dict) -> bool:
        """Does this market live in the historical tier?

        Keyed on ``settlement_ts`` where present, falling back to ``close_time``.
        Getting this wrong costs a 404, not a wrong answer, so the fallback is safe.
        """
        cut = self.cutoff().get("market_settled_ts")
        if not cut:
            return False
        t = parse_ts(market.get("settlement_ts")) or parse_ts(market.get("close_time"))
        return bool(t and t < cut)

    # -- catalogue --------------------------------------------------------

    def series_list(self, category: str | None = None) -> list[dict]:
        """Every series, or one category's.

        Unpaginated: the whole 14,392-series catalogue arrives in one ~17 MB
        response. ``settlement_sources`` on a series is the named authority the
        contract settles against -- the field that makes a Kalshi contract
        joinable to an upstream statistic.
        """
        j = self.get("/series", category=category) or {}
        return j.get("series") or []

    def series(self, ticker: str) -> dict | None:
        j = self.get(f"/series/{ticker}", allow_404=True)
        return (j or {}).get("series")

    def events(self, cap: int | None = None, **params: Any) -> Iterator[dict]:
        """Events. Always available on the live route regardless of age.

        This is the **discovery spine**, and it beats ``/markets`` for the job on
        two counts. It excludes multivariate events, so it is not swamped by
        auto-generated sports parlays -- a 20,000-market walk of
        ``/markets?status=open`` returned *zero* rows in Economics, Financials,
        Politics or Elections because ``KXMVECROSSCATEGORY`` and friends fill the
        first 20 pages. And each event carries ``category``, ``series_ticker``,
        ``settlement_sources`` and ``mutually_exclusive``, which is everything
        needed to classify a ladder.

        With ``with_nested_markets="true"`` one walk returns the whole open
        universe with quotes attached: **14,444 open events in 89 requests**,
        5,296 of them in the four target categories.

        **But do not pass ``with_nested_markets`` with ``status="settled"``.** On
        a settled page, 61 of 100 events came back with an empty ``markets``
        list -- every one of them a pre-cutoff event whose markets live in the
        historical tier, all recoverable via
        ``/historical/markets?event_ticker=``. The empty list is indistinguishable
        from an event that never had markets, so a closed-corpus build that
        trusts it loses most of the history.
        """
        yield from self.paginate("/events", "events", cap=cap, **params)

    def event(self, ticker: str, nested: bool = False) -> dict | None:
        """One event.

        Events never expire from the live tier, but ``with_nested_markets`` only
        returns markets that are *themselves* still live. A 2025 event therefore
        returns 200 with zero nested markets -- which reads exactly like an event
        that never had any. Use ``markets(event_ticker=...)`` instead.
        """
        j = self.get(f"/events/{ticker}", allow_404=True,
                     with_nested_markets="true" if nested else None)
        if j is None:
            return None
        ev = j.get("event") or {}
        if nested and "markets" in j and "markets" not in ev:
            ev["markets"] = j["markets"]
        return ev

    def markets(self, cap: int | None = None, both_tiers: bool = True,
                **params: Any) -> Iterator[dict]:
        """Settled and open markets across both tiers, normalised.

        ``/markets`` serves the live tier and ``/historical/markets`` the rest;
        neither knows about the other. A filter such as
        ``series_ticker=PRES`` returns **zero rows with HTTP 200** on the live
        route, because every PRES market settled in 2025 -- the emptiness is the
        tier boundary, not an empty series. Walking both is the only honest read.

        **De-duplicate on ticker.** The docs say a market settled before the
        cutoff is "only available" on the historical route, and that is not
        quite true: the two tiers overlap in a band just below the cutoff. On
        KXNASDAQ100, 180 markets came back from *both* walks with identical
        ``settlement_ts`` (2026-07-21/22, against a cutoff of 2026-07-28). So
        the cutoff is a floor on where you *must* look, not a partition, and a
        corpus built by concatenating the two walks double-counts that band.
        """
        emitted = 0
        for path, key in (("/markets", "markets"), ("/historical/markets", "markets")):
            if path.startswith("/historical") and not both_tiers:
                continue
            p = dict(params)
            if path == "/markets" and "status" not in p:
                p["status"] = "settled"
            if path.startswith("/historical"):
                p.pop("status", None)  # everything historical is settled
            for m in self.paginate(path, key, **p):
                row = normalise_market(m)
                row["tier"] = "historical" if path.startswith("/historical") else "live"
                # Keep the series we ASKED for alongside the one the ticker
                # spells, because on the historical route they differ. Kalshi
                # re-prefixed its series with "KX" at some point and the
                # historical filter follows the lineage: a query for
                # series_ticker=KXCPIYOY returns 603 markets of which **356
                # carry the legacy `CPIYOY-` prefix** and only 247 the modern
                # one, reaching back to 2022-12 rather than 2024-11.
                #
                # Two consequences. (1) Deriving the series from the ticker
                # prefix, as ``normalise_market`` must when nothing better is
                # available, splits one contract's history in two -- and since
                # `/series` lists CPIYOY and KXCPIYOY as separate series, a walk
                # over all series then harvests the legacy rows twice.
                # (2) More usefully, this is the vendor solving the re-issue
                # splice for you: one query returns a continuous four-year
                # history across a rename, which is the join Polymarket leaves
                # to a hand-maintained concept map.
                row["queried_series"] = params.get("series_ticker")
                yield row
                emitted += 1
                if cap and emitted >= cap:
                    return

    def market(self, ticker: str) -> dict | None:
        """One market, tried live then historical.

        Note which filter name the *list* route honours: on
        ``/historical/markets`` it is ``tickers`` (plural). Passing ``ticker``
        or ``market_tickers`` is **not an error** -- the filter is silently
        dropped and you are handed the unfiltered first page, which looks like
        a successful lookup returning the wrong market. Any filter used against
        these routes has to be confirmed by inspecting what came back.
        """
        j = self.get(f"/markets/{ticker}", allow_404=True)
        if j and j.get("market"):
            row = normalise_market(j["market"])
            row["tier"] = "live"
            return row
        j = self.get(f"/historical/markets/{ticker}", allow_404=True)
        if j and j.get("market"):
            row = normalise_market(j["market"])
            row["tier"] = "historical"
            return row
        return None

    # -- price paths ------------------------------------------------------

    def candles(self, market: dict | str, period: int = 1440,
                start_ts: int | None = None, end_ts: int | None = None,
                series_ticker: str | None = None) -> list[dict]:
        """The full normalised price path of one market, chunked past the 5000 cap.

        ``period`` is minutes and must be one of 1, 60 or 1440. Defaults span the
        market's own life, so a settled market yields its complete history.

        The two tiers take **different paths**: live is
        ``/series/{series}/markets/{ticker}/candlesticks`` and needs the series
        segment; historical is ``/historical/markets/{ticker}/candlesticks`` and
        has no series segment at all. Ask the wrong one and you get a 404 that
        looks like a market that never existed.
        """
        if period not in PERIODS:
            raise ValueError(f"period must be one of {PERIODS}, got {period}")
        if isinstance(market, str):
            m = self.market(market)
            if m is None:
                return []
            market = m
        ticker = market["ticker"]
        ser = series_ticker or market.get("series_ticker") or ticker.split("-")[0]
        hist = market.get("tier") == "historical" or (
            market.get("tier") is None and self.is_historical(market)
        )
        path = (f"/historical/markets/{ticker}/candlesticks" if hist
                else f"/series/{ser}/markets/{ticker}/candlesticks")

        s = start_ts or parse_ts(market.get("open_time"))
        e = end_ts or parse_ts(market.get("close_time")) or int(time.time())
        if not s:
            return []
        out: list[dict] = []
        span = period * 60 * (MAX_CANDLES - 1)
        cur = s
        while cur < e:
            stop = min(e, cur + span)
            j = self.get(path, allow_404=True, start_ts=cur, end_ts=stop,
                         period_interval=period)
            if j is None:
                break
            out += [normalise_candle(c) for c in (j.get("candlesticks") or [])]
            cur = stop
        return out

    def batch_candles(self, tickers: Sequence[str], period: int = 1440,
                      start_ts: int | None = None,
                      end_ts: int | None = None) -> dict[str, list[dict]]:
        """Up to 100 LIVE-tier markets in one call. Historical is not batchable.

        ``GET /markets/candlesticks?market_tickers=a,b,c``. The parameter is
        ``market_tickers``; ``tickers`` yields a 400 that names the right one.

        The trap: a pre-cutoff ticker is not an error here. The route returns
        **HTTP 200 with ``{"markets": []}``**, so a backfill that batches
        blindly reports success and writes nothing. Check the keys you got back
        against the keys you asked for.
        """
        out: dict[str, list[dict]] = {}
        for i in range(0, len(tickers), MAX_BATCH_TICKERS):
            chunk = list(tickers[i:i + MAX_BATCH_TICKERS])
            j = self.get("/markets/candlesticks", market_tickers=",".join(chunk),
                         start_ts=start_ts, end_ts=end_ts, period_interval=period)
            for row in (j or {}).get("markets") or []:
                t = row.get("ticker") or row.get("market_ticker")
                out[t] = [normalise_candle(c) for c in (row.get("candlesticks") or [])]
        return out

    def event_candles(self, series_ticker: str, event_ticker: str, period: int = 1440,
                      start_ts: int | None = None,
                      end_ts: int | None = None) -> list[list[dict]] | None:
        """Every rung of a live event's ladder in a single call.

        ``GET /series/{s}/events/{e}/candlesticks`` returns ``market_candlesticks``
        as a list-of-lists, one per market in event order. Live tier only.
        """
        j = self.get(f"/series/{series_ticker}/events/{event_ticker}/candlesticks",
                     allow_404=True, start_ts=start_ts, end_ts=end_ts,
                     period_interval=period)
        if not j:
            return None
        return [[normalise_candle(c) for c in row]
                for row in (j.get("market_candlesticks") or [])]

    def trades(self, ticker: str, cap: int = 1000,
               historical: bool | None = None) -> list[dict]:
        """The public trade tape, print by print, routed across the tier split.

        ``trades_created_ts`` governs this one (same value as the market cutoff
        when observed). Fills older than it come from ``/historical/trades``,
        which **is** public and unauthenticated -- it returned PRES-2024-DJT's
        tape from January 2025 -- despite the docs describing the historical
        trade route in terms of member fills.

        Each print carries ``taker_side``, ``taker_book_side``, ``count_fp`` and
        ``is_block_trade``, so signed order flow, print-size concentration and
        negotiated-block share are all computable. That is the thing Polymarket
        structurally cannot offer, where ``volumeClob`` equals ``volumeNum`` at
        every percentile and wash volume cannot be apportioned from the API.

        **The filter parameter name flips between the two routes.**
        ``/historical/markets`` honours ``tickers`` and silently ignores
        ``ticker``; ``/historical/trades`` honours ``ticker`` and silently
        ignores ``tickers`` -- passing the plural there returned trades for an
        unrelated market (``KXHIGHTLV-26JUL27-B109.5``) with HTTP 200. Neither
        route errors on the wrong name, so both have to be checked against the
        rows that come back.
        """
        if historical is None:
            cut = self.cutoff().get("trades_created_ts")
            m = self.market(ticker)
            t = parse_ts((m or {}).get("settlement_ts")) or \
                parse_ts((m or {}).get("close_time"))
            historical = bool(cut and t and t < cut)
        path = "/historical/trades" if historical else "/markets/trades"
        return list(self.paginate(path, "trades", limit=min(cap, 1000),
                                  cap=cap, ticker=ticker))

    def orderbook(self, ticker: str) -> dict | None:
        """Resting depth as two bid stacks. Empty on a settled market.

        ``{"yes_dollars": [[price, size], ...], "no_dollars": [[price, size], ...]}``
        -- both lists are **bids**, one per outcome, ascending in price. There is
        no ask list: an ask on YES is a bid on NO at the complement, so
        ``yes_ask = 1 - max(no_dollars price)``. Verified against a trade print
        that reported ``yes_price 0.3900`` and ``no_price 0.6100`` on the same
        fill.
        """
        j = self.get(f"/markets/{ticker}/orderbook", allow_404=True)
        return (j or {}).get("orderbook_fp") or (j or {}).get("orderbook")


def book_depth(orderbook: dict | None, within: float = 0.01) -> dict:
    """Executable notional near the touch, computed from the book itself.

    Never use the market row's ``liquidity_dollars`` for this. On
    KXCPIYOY-26SEP-T3.6 -- a 17-level two-sided book with $46,062 of open
    interest and a one-cent spread -- ``liquidity_dollars`` reports
    **0.0000**. It is not a depth measure that needs interpreting, as
    Polymarket's ``liquidityNum`` is; it is simply absent while looking like a
    number, so a quality filter keyed on it silently rejects the best markets
    on the venue.

    ``bid_depth`` is what you could sell into, ``ask_depth`` what you could buy
    from, both in dollars of notional within ``within`` of the touch on that
    side.
    """
    ob = orderbook or {}
    yes = [(float(p), float(s)) for p, s in (ob.get("yes_dollars") or [])]
    no = [(float(p), float(s)) for p, s in (ob.get("no_dollars") or [])]
    out = {"yes_bid": None, "yes_ask": None, "spread": None,
           "bid_depth": 0.0, "ask_depth": 0.0,
           "bid_levels": len(yes), "ask_levels": len(no),
           "imbalance": None}
    if yes:
        out["yes_bid"] = max(p for p, _ in yes)
        out["bid_depth"] = sum(p * s for p, s in yes
                               if out["yes_bid"] - p <= within)
    if no:
        best_no = max(p for p, _ in no)
        out["yes_ask"] = round(1.0 - best_no, 4)
        # An ask on YES costs (1 - no_price) per contract.
        out["ask_depth"] = sum((1.0 - p) * s for p, s in no
                               if best_no - p <= within)
    if out["yes_bid"] is not None and out["yes_ask"] is not None:
        out["spread"] = round(out["yes_ask"] - out["yes_bid"], 4)
        tot = out["bid_depth"] + out["ask_depth"]
        if tot:
            out["imbalance"] = round(
                (out["bid_depth"] - out["ask_depth"]) / tot, 4)
    return out


# --------------------------------------------------------------------------
# quality metrics over one market
# --------------------------------------------------------------------------


def market_quality(market: dict, candles: Sequence[dict] | None = None) -> dict:
    """Metrics that say whether a price is worth reading as a probability.

    Neither of the two fields a filter would reach for first survives contact:
    ``liquidity`` reads 0.0000 on real books (see ``book_depth``), and volume
    counts turnover rather than interest.

    **``open_interest`` on the market row is zero once the market settles.** It
    is a live position count, not a historical record, so the median across
    every settled market in the corpus is 0 in all four categories --
    PRES-2024-DJT reports ``open_interest`` 0.0 on the row while its own candle
    path peaks at $81.5M. So the interest a settled market actually attracted is
    recoverable **only** from the candles, which is what
    ``peak_open_interest`` below does. A quality screen that reads OI off the
    market row silently scores every settled market as having had no interest.

    The candle-derived fields need a price path; without one they are None and
    the row is still usable for a census.
    """
    q: dict[str, Any] = {
        "ticker": market.get("ticker"),
        "volume": market.get("volume"),
        "open_interest": market.get("open_interest"),
        "turnover": None,
        "settled": outcome(market),
        "result": market.get("result"),
    }
    oi, vol = market.get("open_interest") or 0.0, market.get("volume") or 0.0
    if oi:
        q["turnover"] = vol / oi

    o, c = parse_ts(market.get("open_time")), parse_ts(market.get("close_time"))
    q["life_days"] = round((c - o) / 86400.0, 2) if o and c else None

    if not candles:
        return q

    traded = [x for x in candles if x["traded"]]
    quoted = [x for x in candles if x["mid"] is not None]
    two_sided = [x for x in quoted
                 if x["yes_bid"] is not None and x["yes_ask"] is not None
                 and x["yes_bid"] > 0 and x["yes_ask"] < 1]

    q["n_periods"] = len(candles)
    q["n_traded"] = len(traded)
    # Share of the market's life on which anything at all changed hands. The
    # single most discriminating quality number available: a ladder rung that
    # trades on 4% of its days is an interpolation, not an opinion.
    q["traded_frac"] = round(len(traded) / len(candles), 4) if candles else None
    q["n_two_sided"] = len(two_sided)
    q["two_sided_frac"] = round(len(two_sided) / len(candles), 4) if candles else None

    spreads = [x["spread"] for x in two_sided if x["spread"] is not None]
    if spreads:
        spreads = sorted(spreads)
        q["median_spread"] = spreads[len(spreads) // 2]
        rel = [s / x["mid"] for s, x in zip(spreads, two_sided) if x["mid"]]
        rel = sorted(r for r in rel if r is not None)
        q["median_rel_spread"] = round(rel[len(rel) // 2], 4) if rel else None

    prices = [x["mean"] if x["mean"] is not None else x["close"] for x in traded]
    prices = [p for p in prices if p is not None]
    if prices:
        q["n_distinct_prices"] = len(set(prices))
        q["first_price"], q["last_price_path"] = prices[0], prices[-1]
        moves = [abs(b - a) for a, b in zip(prices, prices[1:])]
        if moves:
            ms = sorted(moves)
            q["median_abs_move"] = ms[len(ms) // 2]
            q["max_abs_move"] = ms[-1]
            # A path that never moves is a quote, not a belief being updated.
            q["frac_periods_unchanged"] = round(
                sum(1 for m in moves if m == 0) / len(moves), 4)

    q["peak_open_interest"] = max((x["open_interest"] for x in candles), default=None)
    q["total_candle_volume"] = sum(x["volume"] for x in candles)
    return q


# Every quality metric Kalshi's read surface can support, where it comes from,
# and whether it survives contact. "trust" is the judgement, not the vendor's.
#
#   name                      where it comes from                          trust
QUALITY_METRICS: tuple[tuple[str, str, str, str], ...] = (
    # --- from the market row, free, one call per 1000 markets ---
    ("volume", "market.volume_fp", "no",
     "turnover, not interest; a rung can churn without anyone holding a view"),
    ("open_interest", "market.open_interest_fp", "live only",
     "the honest interest measure WHILE OPEN; zeroed the moment it settles"),
    ("liquidity", "market.liquidity_dollars", "never",
     "reads 0.0000 on a 17-level book with $46k OI; not a depth measure"),
    ("quoted_spread", "market.yes_ask - market.yes_bid", "yes",
     "absolute spread; compare relative to mid, not in cents"),
    ("size_at_touch", "market.yes_bid_size_fp / yes_ask_size_fp", "yes",
     "top-of-book size per side, free on the row; 571 vs 5,618 is a real signal"),
    ("settlement_source", "series.settlement_sources[].name/url", "yes",
     "the named authority; present on 100% of target series"),
    ("contract_terms", "series.contract_terms_url", "yes",
     "a filed PDF on 5,973/5,973 target series, plus a CFTC product cert on 5,961"),
    ("insider_prohibitions", "series.additional_prohibitions", "yes",
     "e.g. source-agency employees barred from CPI; Senate staff from legislation"),
    ("fee_family", "series.fee_type / fee_multiplier", "partial",
     "'quadratic' on 99.6%; the coefficient is NOT exposed, so the wedge needs the docs"),

    # --- computed from the order book, one call per market ---
    ("book_depth_at_touch", "book_depth(orderbook()) -> bid_depth/ask_depth", "yes",
     "the only honest depth; $217 bid on the deepest CPI rung"),
    ("book_imbalance", "book_depth(...)['imbalance']", "yes",
     "-0.82 on that rung: makers offering, nobody bidding"),
    ("book_levels", "book_depth(...)['bid_levels'/'ask_levels']", "yes",
     "a one-level book quoting a penny spread is not a market"),

    # --- computed from the candle path, one call per market, FULL LIFE ---
    ("traded_frac", "market_quality(...)['traded_frac']", "yes",
     "share of the market's LIFE on which anything traded; the single best "
     "discriminator (92% robotaxi vs 18% Senate primary vs 27% Apple)"),
    ("two_sided_frac", "market_quality(...)['two_sided_frac']", "yes",
     "share of days with a genuine two-sided quote"),
    ("median_rel_spread", "market_quality(...)['median_rel_spread']", "yes",
     "spread/mid over the whole life: 4% vs 26% vs 56% separates the same three"),
    ("frac_periods_unchanged", "market_quality(...)['frac_periods_unchanged']", "yes",
     "a path that never ticks is a quote being carried, not a belief"),
    ("n_distinct_prices", "market_quality(...)['n_distinct_prices']", "yes",
     "a step function with 15 distinct prices is not a probability path"),
    ("peak_open_interest", "market_quality(...)['peak_open_interest']", "yes",
     "recovers, from the candles, the interest the row has already thrown away"),
    ("vwap_vs_close", "candle['mean'] vs candle['close']", "yes",
     "Kalshi gives a per-period VWAP; prefer it to the last print on thin books"),

    # --- computed across an event's markets ---
    ("ladder_coherence", "Ladder.coherence()", "yes",
     "monotonicity and arbitrage violations; needs a SYNCHRONOUS mid snapshot"),
    ("implied_mass", "Ladder.coherence()['implied_mass']", "yes",
     "how much of the distribution the listed rungs actually span"),
    ("implied_quantile", "Ladder.implied_quantile(q)", "yes",
     "the number a ladder exists to produce and no single market can give"),

    # --- from the trade tape, live tier only ---
    ("signed_order_flow", "trades()[].taker_side / taker_book_side", "yes",
     "who lifted whom; Polymarket's volume cannot be apportioned this way"),
    ("block_trade_share", "trades()[].is_block_trade", "yes",
     "negotiated size, flagged; a concentration signal for free"),

    # --- labels, for scoring ---
    ("settled_outcome", "outcome(market)", "yes",
     "result yes/no + settlement_value; EXCLUDES result=='scalar'"),
    ("realised_underlying", "market.expiration_value", "yes",
     "what the world actually did, parseable as a bare number on 93% of the "
     "rows that carry it; this is what makes the FRED/BLS join checkable"),
)


def brier(prob: float, settled: float) -> float:
    return (prob - settled) ** 2


def log_score(prob: float, settled: float, eps: float = 1e-6) -> float:
    p = min(max(prob, eps), 1 - eps)
    return -(settled * math.log(p) + (1 - settled) * math.log(1 - p))


# --------------------------------------------------------------------------
# ladders: the CDF object
# --------------------------------------------------------------------------


@dataclass
class Ladder:
    """A set of markets over one underlying, ordered by strike or by date.

    A ``greater`` strike ladder is a survival function S(k) = P(X > k), so it
    must be **weakly decreasing** in k, and -dS is the probability mass in each
    interval. A "by date T" ladder is a CDF F(T) = P(event by T), so it must be
    weakly **increasing** in T, and the forward difference is the mass in each
    window. Either way, adjacent rungs difference into a density -- and either
    way a violation is free evidence that the quote is not a probability.
    """

    event_ticker: str
    kind: str  # "strike" | "date" | "categorical"
    rungs: list[dict] = field(default_factory=list)  # ordered; each has x, p, ticker

    @property
    def xs(self) -> list[float]:
        return [r["x"] for r in self.rungs]

    @property
    def ps(self) -> list[float]:
        return [r["p"] for r in self.rungs]

    def differences(self) -> list[dict]:
        """Probability mass implied in each interval between adjacent rungs.

        Sign convention: mass is always reported as a non-negative quantity
        where the ladder is coherent, so a *negative* entry is precisely an
        arbitrage violation.
        """
        out = []
        for (a, b) in zip(self.rungs, self.rungs[1:]):
            d = a["p"] - b["p"] if self.kind == "strike" else b["p"] - a["p"]
            out.append({"lo": a["x"], "hi": b["x"], "mass": d,
                        "lo_ticker": a["ticker"], "hi_ticker": b["ticker"]})
        return out

    def coherence(self) -> dict:
        """How much this ladder contradicts itself.

        ``max_violation`` in cents is the size of the free lunch: on a coherent
        ladder it is zero, and anything above the tick is either a stale quote or
        a rung nobody is pricing.
        """
        diffs = self.differences()
        bad = [d for d in diffs if d["mass"] < 0]
        ps = self.ps
        return {
            "event_ticker": self.event_ticker,
            "kind": self.kind,
            "n_rungs": len(self.rungs),
            "n_intervals": len(diffs),
            "monotone": not bad,
            "n_violations": len(bad),
            "max_violation": round(max((-d["mass"] for d in bad), default=0.0), 4),
            "total_violation": round(sum(-d["mass"] for d in bad), 4),
            "implied_mass": round(sum(d["mass"] for d in diffs), 4),
            "p_range": (min(ps), max(ps)) if ps else None,
            "endpoints_bracket": (bool(ps) and max(ps) <= 1.0 and min(ps) >= 0.0),
        }

    def implied_quantile(self, q: float = 0.5) -> float | None:
        """Interpolate the x at which the ladder crosses probability ``q``.

        For a strike ladder this is the market-implied quantile of the
        underlying; for a date ladder it is the market-implied resolution date
        (as a unix timestamp) by which the event is ``q``-likely to have
        happened. This is the number the ladder exists to produce and no single
        market can give.
        """
        pts = sorted(zip(self.xs, self.ps), key=lambda t: t[0])
        for (x0, p0), (x1, p1) in zip(pts, pts[1:]):
            lo, hi = (p0, p1) if p0 <= p1 else (p1, p0)
            if lo <= q <= hi and p1 != p0:
                return x0 + (x1 - x0) * (q - p0) / (p1 - p0)
        return None


_BEFORE = ("before ", "by ", "on or before ")


def ladder_shape(event: dict, markets: Sequence[dict]) -> str:
    """Which of the three shapes an event's markets form.

    Kalshi states this rather than leaving it to be inferred, which Polymarket
    does not:

    ``partition``   ``mutually_exclusive: True`` -- the rungs are already the
                    density and their prices should sum to about 1 (less the
                    discount). Differencing them is meaningless.
    ``cdf``         ``mutually_exclusive: False`` with rungs labelled
                    "Before <date>" -- each rung is P(event by T), so the set is
                    a cumulative distribution over the resolution date and the
                    forward difference is the mass in each window. This is the
                    shape an option strike ladder has, and the one worth
                    reading as a term structure.
    ``survival``    a ``greater``/``less`` strike ladder over a numeric
                    underlying -- P(X > k), the complement of a CDF over value
                    rather than over date.
    ``single``      fewer than two rungs, or no recoverable ordering.
    """
    if len(markets) < 2:
        return "single"
    kinds = {m.get("strike_type") for m in markets if m.get("strike_type")}
    # ``between`` decides it, even alongside strike rungs. Kalshi's usual
    # numeric event is a *partition*: a run of ``between`` buckets with a
    # ``less`` rung on the low wing and a ``greater`` rung on the high wing
    # (NASDAQ100-24OCT25 has exactly that shape). Reading the two wings as a
    # two-rung survival ladder would difference two non-adjacent tails and call
    # the result a density.
    if "between" in kinds:
        return "partition"
    if kinds & {"greater", "greater_or_equal", "less", "less_or_equal"}:
        return "survival"
    if event.get("mutually_exclusive"):
        return "partition"
    # A cdf has to *say* it is cumulative. Distinct close times alone are not
    # enough evidence: a 14-rung set of "will senator X vote for Y" markets
    # closes on 14 different days and is a partition over people, not a
    # distribution over dates. Require the "Before <date>" / "By <date>" label
    # Kalshi puts in ``yes_sub_title`` on a genuine cumulative rung, on a
    # majority of the rungs.
    subs = [(m.get("yes_sub_title") or "").lower() for m in markets]
    n_before = sum(any(s.startswith(p) for p in _BEFORE) for s in subs)
    if n_before >= 2 and n_before >= len(markets) / 2:
        return "cdf"
    return "partition"


def build_ladder(event_ticker: str, markets: Sequence[dict],
                 price_key: str = "last_price") -> Ladder | None:
    """Assemble a ladder from an event's markets, if they form one.

    Kalshi marks the shape itself: ``strike_type`` is ``greater`` /
    ``less`` / ``between`` on a strike ladder, and ``floor_strike`` /
    ``cap_strike`` carry the numbers. A ``between`` set is a *partition*, not a
    ladder -- the rungs are already the density -- so it is reported as
    ``categorical`` and left alone.
    """
    usable = [m for m in markets if m.get(price_key) is not None]
    if len(usable) < 2:
        return None
    kinds = {m.get("strike_type") for m in usable}

    if kinds <= {"greater", "greater_or_equal"} and all(
            m.get("floor_strike") is not None for m in usable):
        rungs = [{"x": float(m["floor_strike"]), "p": float(m[price_key]),
                  "ticker": m["ticker"]} for m in usable]
        rungs.sort(key=lambda r: r["x"])
        return Ladder(event_ticker, "strike", rungs)

    if kinds <= {"less", "less_or_equal"} and all(
            m.get("cap_strike") is not None for m in usable):
        # P(X < k) is a CDF: increasing in k, so it differences like a date ladder.
        rungs = [{"x": float(m["cap_strike"]), "p": float(m[price_key]),
                  "ticker": m["ticker"]} for m in usable]
        rungs.sort(key=lambda r: r["x"])
        return Ladder(event_ticker, "date", rungs)

    if kinds & {"between"}:
        rungs = [{"x": float(m.get("floor_strike") or 0.0), "p": float(m[price_key]),
                  "ticker": m["ticker"]} for m in usable]
        rungs.sort(key=lambda r: r["x"])
        return Ladder(event_ticker, "categorical", rungs)

    # A date ladder. The x axis is the date in the rung's own LABEL, not its
    # ``close_time``: when the event resolves, every rung that has not yet
    # elapsed is closed early at the resolution instant, so their close_times
    # all collapse to the same value. On KXTRUMPCHINA-26 five different rungs
    # ("Before May 13", "Before May 14", "Before May 15", "Before Jun 1",
    # "Before Jul 1") share ``close_time`` 2026-05-13, which would stack five
    # distinct points of the distribution onto one x and difference them into
    # nonsense. ``label_date`` reads the intended date instead and only falls
    # back to close_time when there is no label.
    rungs = []
    for m in usable:
        x = label_date(m.get("yes_sub_title")) or parse_ts(m.get("close_time"))
        if x is None:
            return None
        rungs.append({"x": float(x), "p": float(m[price_key]),
                      "ticker": m["ticker"]})
    if len({r["x"] for r in rungs}) < 2:
        return None
    rungs.sort(key=lambda r: r["x"])
    return Ladder(event_ticker, "date", rungs)


_LABEL_RE = re.compile(
    r"(?:before|by|on or before)\s+"
    r"(?:(?P<mon>[A-Za-z]{3,9})\s+(?P<day>\d{1,2})?,?\s*(?P<year1>\d{4})"
    r"|(?P<mon2>[A-Za-z]{3,9})\s+(?P<year2>\d{4})"
    r"|(?P<year3>\d{4}))",
    re.I)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def label_date(sub_title: str | None) -> int | None:
    """Unix seconds for the date named in a cumulative rung's label.

    Handles the three forms Kalshi actually uses on "by date" rungs:
    ``Before May 14, 2026``, ``Before Jul 2025`` and ``Before 2029``.
    """
    if not sub_title:
        return None
    m = _LABEL_RE.search(sub_title)
    if not m:
        return None
    g = m.groupdict()
    try:
        if g["year1"]:
            mon = _MONTHS.get((g["mon"] or "")[:3].lower())
            if not mon:
                return None
            return int(datetime(int(g["year1"]), mon,
                                int(g["day"] or 1), tzinfo=UTC).timestamp())
        if g["year2"]:
            mon = _MONTHS.get((g["mon2"] or "")[:3].lower())
            if not mon:
                return None
            return int(datetime(int(g["year2"]), mon, 1, tzinfo=UTC).timestamp())
        if g["year3"]:
            return int(datetime(int(g["year3"]), 1, 1, tzinfo=UTC).timestamp())
    except ValueError:
        return None
    return None


def snapshot(paths: dict[str, Sequence[dict]], at_date: str,
             field: str = "mid") -> dict[str, float]:
    """The last value of ``field`` at or before ``at_date``, per ticker.

    A ladder can only be scored for coherence on a **synchronous** set of
    prices. ``last_price`` is not synchronous: on a settled event every rung
    reports the price of its own final trade, which may be months apart and,
    after settlement, is pinned to 0 or 1. Scoring coherence on ``last_price``
    therefore manufactures violations that never existed in the book -- the
    KXCPIYOY-26AUG ladder scores three violations and a 18-cent free lunch on
    last prices, none of which was tradable.

    Use a mid-quote snapshot instead, and prefer ``mid`` over ``close``: the
    quote exists on days with no trade, so it is defined for every rung on
    every day, which is exactly what a synchronous read needs.
    """
    out = {}
    for ticker, cs in paths.items():
        best = None
        for c in cs:
            if c.get("date") and c["date"] <= at_date and c.get(field) is not None:
                best = c[field]
        if best is not None:
            out[ticker] = best
    return out


def ladder_at(event_ticker: str, markets: Sequence[dict],
              paths: dict[str, Sequence[dict]], at_date: str,
              field: str = "mid") -> Ladder | None:
    """Build a ladder from a synchronous mid-quote snapshot on ``at_date``."""
    snap = snapshot(paths, at_date, field=field)
    if len(snap) < 2:
        return None
    priced = [dict(m, _snap=snap[m["ticker"]]) for m in markets
              if m.get("ticker") in snap]
    return build_ladder(event_ticker, priced, price_key="_snap")


# --------------------------------------------------------------------------
# settlement provenance
# --------------------------------------------------------------------------

# Which named authority a contract settles against, mapped onto the upstream
# meida already ingests. Resolution against one of these is arithmetic: the
# print lands, the strike is above or below it, the market pays. Compare
# Polymarket, whose standard is "a consensus of credible reporting" adjudicated
# by an oracle vote.
SETTLEMENT_UPSTREAM = {
    "bls": ("BLS", ("bureau of labor statistics", "bls.gov")),
    "fred": ("FRED", ("federal reserve economic data", "fred.stlouisfed.org")),
    "fed": ("FRED", ("federal reserve", "federalreserve.gov", "newyorkfed.org")),
    "bea": ("FRED", ("bureau of economic analysis", "bea.gov")),
    "census": ("FRED", ("census bureau", "census.gov")),
    "treasury": ("FRED", ("department of the treasury", "home.treasury.gov")),
    "eia": ("EIA", ("energy information", "eia.gov")),
}


def classify_settlement(sources: Sequence[dict] | None) -> dict:
    """Tag a series' settlement sources against meida's existing upstreams.

    Returns the matched agency keys, the house source they would join to, and
    any literal FRED series ids found in the URLs -- the cleanest join in the
    stack, because Kalshi sometimes names the exact FRED id it settles on.
    """
    sources = sources or []
    blob = " ".join(
        f"{s.get('name', '')} {s.get('url', '')}".lower() for s in sources)
    matched, upstream = [], set()
    for key, (house, needles) in SETTLEMENT_UPSTREAM.items():
        if any(n in blob for n in needles):
            matched.append(key)
            upstream.add(house)
    fred_ids = []
    for s in sources:
        u = s.get("url") or ""
        if "fred.stlouisfed.org/series/" in u:
            tail = u.split("/series/")[1]
            fred_ids.append(tail.split("#")[0].split("?")[0].strip("/"))
    return {
        "agencies": sorted(matched),
        "house_upstream": sorted(upstream),
        "fred_series_ids": sorted(set(fred_ids)),
        "is_statistical": bool(matched),
        "source_names": [s.get("name") for s in sources],
        "source_urls": [s.get("url") for s in sources],
    }


# --------------------------------------------------------------------------
# corpus io
# --------------------------------------------------------------------------


def write_jsonl(rows: Sequence[dict], name: str, data_dir: Path = DATA_DIR) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / name
    with p.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str) + "\n")
    return p


def read_jsonl(name: str, data_dir: Path = DATA_DIR) -> list[dict]:
    p = data_dir / name
    if not p.exists():
        return []
    with p.open() as fh:
        return [json.loads(line) for line in fh if line.strip()]
