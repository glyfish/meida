"""PredictIt: the snapshot venue, plus the snapshot recorder that turns it into history.

PredictIt is small, entirely political, and the only venue in this study whose
prices are distorted by a *fee on gross profits* rather than a fee on notional.
That single design choice moves its prices further from probability than
anything on Polymarket, and it is the reason `fees` below is not an afterthought.

WHAT IS PUBLIC, verified live 2026-09-26
----------------------------------------
Three unauthenticated endpoints on ``https://www.predictit.org``, no key, no
account, no cookie:

===================================================  ====================================
``/api/marketdata/all/``                             197 markets / 613 contracts, 418 KB
``/api/marketdata/markets/{market_id}``              one market, identical record shape
``/api/Public/GetMarketChartData/{market_id}``       daily OHLC + share volume
===================================================  ====================================

Confirmed absent (all 404, tested 2026-09-26):
``/api/marketdata/contracts/{id}``, ``/api/Public/GetMarketHistory/{id}``,
``/api/Public/GetMarketChartData/{market}/{contract}``.  Passing a *contract*
id to ``GetMarketChartData`` returns 400, not 404 -- it wants a market id.

THE HISTORY QUESTION, ANSWERED
------------------------------
The task was to establish whether *any* history is obtainable without an
account.  The answer is a qualified yes, and the qualification is severe.

``GetMarketChartData`` is real history: one row per contract per day with
``openSharePrice``, ``highSharePrice``, ``lowSharePrice``, ``closeSharePrice``
and ``tradeVolume`` (shares).  It is strictly better than the snapshot, which
carries no volume at all.  But:

1.  **It returns exactly seven days.**  Ten ``timespan`` values were tested --
    ``24h 7d 30d 90d 1y all ALL max 5y`` plus the parameter omitted entirely,
    plus ``days=365`` and ``showHidden=true`` -- and all twelve responses were
    byte-comparable: 42 rows, 7 distinct dates, 6 contracts.  The parameter is
    accepted and ignored.  There is no reachable argument that widens it.
2.  **It returns only the first six contracts as served**, silently.  Market
    8171 has 13 contracts and charts 6; market 7589 -- the 11-rung "How many
    House seats will Republicans win" ladder -- charts rungs 1-6 and omits
    rungs 7-11 with no error and no marker.  *PredictIt's own seat-count
    ladders cannot be reconstructed from the chart endpoint at all*, which
    matters precisely because a ladder is the object worth studying.
3.  It is daily close.  Intraday is not offered on any route.

So the seven-day window is a **backfill cushion, not an archive**: a recorder
that misses up to a week loses nothing, but nothing before the recorder started
is recoverable from PredictIt.  Hence `record_snapshot`.

On the academic research download: PredictIt was created in 2014 by Victoria
University of Wellington explicitly as an academic data-gathering instrument
under CFTC no-action relief, and supplying data to researchers was its stated
purpose -- it is now run by the Prediction Market Research Consortium, a US
not-for-profit whose contract list is chosen by a board of academics.

**No self-service bulk download exists.**  Probed and 404: ``GetMarketChartDataCsv``,
``ExportMarketChartData``, ``DownloadMarketChartData``.  ``?format=csv`` on the
chart route is *accepted and ignored* -- it returns the same 14,075-byte JSON,
byte for byte.  Third-party reviews mention "a CSV download from the website";
*inferred, not verified* -- the served Content-Security-Policy whitelists
``https://*.highcharts.com``, and the Highcharts export button serialises
whatever the browser already holds, so that CSV is almost certainly the same
seven days rather than a second data source.  What **is** verified is that no
server-side CSV route responds, so nothing a script can reach goes deeper.

Historical practice for a real archive is to request an extract under an
academic agreement, naming the markets wanted.  So a deeper PredictIt history
is *obtainable by asking a human*, not by code.  Do not design around it, and
do not assume the seven-day window is a bug that a parameter will fix.

RATE LIMIT -- the one hard constraint
-------------------------------------
PredictIt publishes its limit in response headers, and it is the tightest in
this study by two orders of magnitude::

    x-rate-limit-limit-minute: 5
    x-rate-limit-remaining-minute: 3
    x-rate-limit-reset-minute: 60

**Five requests per minute per IP.**  Polymarket Gamma tolerated 81 req/s.
This is 0.083 req/s.  A full chart sweep of all 197 markets is therefore
197 / 5 = **40 minutes of wall clock**, and must be run as a background job.
`RateLimiter` below enforces it client-side with a margin; do not bypass it.

FEES -- why PredictIt prices are not probabilities
--------------------------------------------------
See `FEES` and `breakeven_band`.  The headline: **10% of gross profit on every
profitable position, not netted against losing ones.**  A trader who wins one
leg and loses another of equal size pays a fee on the winner and gets no relief
on the loser, so a market-neutral book bleeds.  The resulting no-trade band is
**5.3 percentage points wide at p = 0.50** -- against roughly 2 points for
Polymarket's 4% notional taker fee at the same price.

**The withdrawal fee was removed on 2026-09-23, three days before this was
written.**  PredictIt had charged 5% on every withdrawal since launch; it now
charges none, and ACH deposits are free.  The 10% profit fee is unchanged.  Any
PredictIt calibration study covering data before 2026-09-23 is measuring a
market with a materially different cost structure, and the break must be
modelled -- `FEES` carries both regimes and `fee_regime_on` selects by date.

Whether the 10% is charged per *position* or netted across a market is the one
fee question this pass could **not** settle from a primary source: PredictIt's
help centre now sits behind a login.  Long-standing trader accounts and
third-party reviews describe it as per-position with no offset for losers, which
is the assumption `net_payoff_per_share` encodes and the conservative one.
Treat the non-netting specifically as *unverified* while treating the 10% rate
as verified.

LIMITS, AND THE BREAK THEY PUT IN THE HISTORY
---------------------------------------------
See `LIMITS` and `STRUCTURAL_BREAKS`, both read verbatim out of **CFTC Letter
No. 25-20 (2025-07-14)**.  Two things there matter more than they look:

* The investment cap is **per participant per CONTRACT**, and it is **indexed to
  the FECA individual contribution limit** rather than fixed -- $3,500 at issue.
  Widely repeated third-party reviews report it as a flat per-*market* cap,
  which understates permitted exposure on a multi-rung ladder by the number of
  rungs.
* The CFTC removed the old 5,000-trader-per-contract limit **because the
  academic community told it the cap was distorting the data**: capped contracts
  "become illiquid and are not able to trade at market prices."  That makes
  2025-07-14 a structural break, and it falls on the wrong side of the
  much-cited 2024-election accuracy results, which are drawn from the capped
  regime.

.. warning::

   Read-only and unauthenticated.  Nothing here places an order, holds a key
   or touches a wallet.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import httpx

__all__ = [
    "PredictItError",
    "RateLimiter",
    "PredictItClient",
    "FEES",
    "FeeRegime",
    "fee_regime_on",
    "net_payoff_per_share",
    "breakeven_band",
    "fee_band_width",
    "fee_adjusted_probability",
    "DATA_DIR",
    "record_snapshot",
    "snapshot_paths",
    "load_snapshot",
    "iter_snapshot_rows",
    "build_history",
    "chart_rows",
    "chart_coverage",
    "LIMITS",
    "STRUCTURAL_BREAKS",
    "RESOLUTION_TEXT_AVAILABLE",
]

BASE = "https://www.predictit.org"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SNAPSHOT_DIR = DATA_DIR / "predictit_snapshots"

#: Browser-ish UA.  PredictIt serves the API to a bare UA, but Cloudflare sits
#: in front of it and a blank UA is the one thing worth not risking.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)

#: Documented by the venue in its own response headers, not inferred.
RATE_LIMIT_PER_MINUTE = 5


class PredictItError(RuntimeError):
    """Any non-200, malformed payload, or rate-limit refusal from PredictIt."""


# --------------------------------------------------------------------------
# rate limiting
# --------------------------------------------------------------------------


class RateLimiter:
    """A thread-safe sliding-window limiter, sized for PredictIt's 5/minute.

    What it measures: nothing -- it is a governor, not a metric.  It blocks the
    caller until a request may be issued without exceeding `per_window`
    requests in any `window` seconds.

    Why a sliding window and not a sleep: the venue's counter is per clock
    minute (``x-rate-limit-reset-minute: 60``), so a naive ``sleep(12)`` between
    calls still bursts across a minute boundary.  The window here is deliberately
    *longer* than 60 s and the count *lower* than 5, leaving headroom for the
    fact that the server's minute and ours are not aligned.
    """

    def __init__(self, per_window: int = 4, window: float = 62.0) -> None:
        self.per_window = per_window
        self.window = window
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Block until a request is permitted.  Returns the seconds waited."""
        waited = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                while self._times and now - self._times[0] >= self.window:
                    self._times.popleft()
                if len(self._times) < self.per_window:
                    self._times.append(now)
                    return waited
                sleep_for = self.window - (now - self._times[0]) + 0.25
            time.sleep(sleep_for)
            waited += sleep_for


# --------------------------------------------------------------------------
# client
# --------------------------------------------------------------------------


class PredictItClient:
    """Read-only PredictIt client.  No key, no account, no order path.

    Every call goes through `RateLimiter`, so a loop over all 197 markets is
    safe but slow by construction (~40 min for a full chart sweep).  Run those
    in the background and poll the log.

    The `client=` seam exists so tests can inject a transport and assert that
    no credential header is ever sent, as meida's BIS client test does.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        limiter: RateLimiter | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._client = client or httpx.Client(
            base_url=BASE,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
        self.limiter = limiter or RateLimiter()
        #: Populated from response headers on every call; useful evidence that
        #: the client is inside the venue's own budget.
        self.last_rate_headers: dict[str, str] = {}

    # -- plumbing ---------------------------------------------------------

    def _get(self, path: str) -> Any:
        self.limiter.acquire()
        try:
            resp = self._client.get(path)
        except httpx.HTTPError as exc:  # pragma: no cover - network
            raise PredictItError(f"GET {path} failed: {exc}") from exc
        self.last_rate_headers = {
            k: v for k, v in resp.headers.items() if k.lower().startswith("x-rate-limit")
        }
        if resp.status_code == 429:
            raise PredictItError(
                f"GET {path} -> 429; limiter is mis-sized. "
                f"headers={self.last_rate_headers}"
            )
        if resp.status_code != 200:
            raise PredictItError(f"GET {path} -> HTTP {resp.status_code}")
        if not resp.content:
            raise PredictItError(f"GET {path} -> 200 with empty body")
        try:
            return resp.json()
        except ValueError as exc:
            raise PredictItError(f"GET {path} -> 200 but not JSON") from exc

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PredictItClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- endpoints --------------------------------------------------------

    def all_markets(self) -> list[dict[str, Any]]:
        """The whole venue in one request: every open market and contract.

        Returns the ``markets`` list.  Measured 2026-09-26: **197 markets, 613
        contracts, 418 KB, every contract ``status == "Open"``**.  66 markets
        are single-contract (binary); the largest carries 18.

        What it cannot see: no volume, no open interest, no order-book depth,
        no trade timestamps, no resolution text, no settlement date for 488 of
        613 contracts (``dateEnd == "NA"``).  This payload supports far fewer
        quality metrics than Polymarket's -- see ``metrics.VENUE_COVERAGE``.
        """
        payload = self._get("/api/marketdata/all/")
        if not isinstance(payload, dict) or "markets" not in payload:
            raise PredictItError("unexpected /marketdata/all/ shape")
        return payload["markets"]

    def market(self, market_id: int) -> dict[str, Any]:
        """One market by id, in the same record shape as `all_markets`.

        Pointless for a sweep -- `all_markets` returns everything for one
        request against a 5/minute budget -- but correct for a single refresh.
        """
        return self._get(f"/api/marketdata/markets/{int(market_id)}")

    def chart(self, market_id: int) -> list[dict[str, Any]]:
        """Daily OHLC + share volume for a market's **first six contracts only**.

        Returns ~42 rows: 7 days x 6 contracts.  Row keys: ``marketId``,
        ``contractId``, ``contractName``, ``date``, ``dateString``,
        ``openSharePrice``, ``highSharePrice``, ``lowSharePrice``,
        ``closeSharePrice``, ``tradeVolume``, ``lineColor``.

        What it cannot see, and this is the whole caveat:

        * **Nothing older than seven days.**  No parameter widens it; twelve
          variants were tested and returned identical payloads.
        * **Contracts seven and beyond.**  Truncation is silent.  Call
          `chart_coverage` against the snapshot to find out what was dropped
          before trusting a ladder built from this.
        * Volume is in *shares*, and a share is at most $1, so share volume is
          an upper bound on dollar volume -- not the same number.
        """
        rows = self._get(f"/api/Public/GetMarketChartData/{int(market_id)}")
        if not isinstance(rows, list):
            raise PredictItError(f"unexpected chart shape for market {market_id}")
        return rows


# --------------------------------------------------------------------------
# fees -- the wedge between a PredictIt price and a probability
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FeeRegime:
    """One PredictIt fee regime, with the date it took effect.

    ``profit_fee`` is charged on **gross profit per closed position**, never
    netted against losing positions in the same market.  That non-netting is
    the expensive part and is not captured by any single percentage.
    """

    name: str
    effective_from: date
    profit_fee: float
    withdrawal_fee: float
    note: str


#: Both regimes, because the change is three days old and every historical
#: series spans the break.
FEES: tuple[FeeRegime, ...] = (
    FeeRegime(
        name="legacy",
        effective_from=date(2014, 1, 1),
        profit_fee=0.10,
        withdrawal_fee=0.05,
        note=(
            "10% of gross profit per position plus 5% of every withdrawal. "
            "In force from launch until 2026-09-22 inclusive."
        ),
    ),
    FeeRegime(
        name="simplified-2026",
        effective_from=date(2026, 9, 23),
        profit_fee=0.10,
        withdrawal_fee=0.0,
        note=(
            "Withdrawal fee removed 2026-09-23; ACH deposits free; one "
            "fee-free card deposit up to $1,000. Profit fee unchanged at 10%."
        ),
    ),
)


def fee_regime_on(when: date | datetime | str) -> FeeRegime:
    """The regime in force on a given date.

    Always resolve fees by observation date rather than by 'today'.  A
    calibration corpus that spans 2026-09-23 contains two different markets.
    """
    if isinstance(when, str):
        when = date.fromisoformat(when[:10])
    if isinstance(when, datetime):
        when = when.date()
    chosen = FEES[0]
    for regime in FEES:
        if regime.effective_from <= when:
            chosen = regime
    return chosen


def net_payoff_per_share(price: float, regime: FeeRegime | None = None) -> float:
    """What one winning share actually pays after the profit fee.

    A share bought at ``price`` settles at $1.  Gross profit is ``1 - price``;
    the venue keeps ``profit_fee`` of it.  Net receipt is therefore
    ``1 - f*(1 - price)``, which is **below $1 at every price** and falls
    fastest on cheap contracts.

    Good/bad: at price 0.95 a winner nets 0.995 (the fee costs 0.5%); at price
    0.05 a winner nets 0.905, so the fee eats **9.5% of the payoff** on exactly
    the longshots where the favourite-longshot bias already sits.  The fee and
    the bias push the same way on the same contracts.
    """
    regime = regime or FEES[-1]
    return 1.0 - regime.profit_fee * (1.0 - price)


def breakeven_band(price: float, regime: FeeRegime | None = None) -> tuple[float, float]:
    """The no-trade band around a quoted price: ``(lower, upper)`` probabilities.

    A risk-neutral trader buys **Yes** only if their belief ``q`` exceeds
    ``upper = price / (1 - f + f*price)``, and buys **No** only if ``q`` falls
    below ``lower = 1 - (1 - price) / (1 - f*price)``.  Between the two nobody
    with a correct belief trades, so the quoted price is consistent with any
    probability in the band.

    **This is the number to quote when someone calls a PredictIt price a
    probability.**  At price 0.50 under the 10% profit fee the band is
    [0.4737, 0.5263] -- the price pins the probability only to within 5.3
    percentage points.

    What it cannot see: the *withdrawal* fee (which compounds on top in the
    legacy regime), the opportunity cost of locked capital, and the
    non-netting penalty on a multi-leg position, all of which widen the real
    band further.  Treat this as a floor on the uncertainty, not the total.
    """
    regime = regime or FEES[-1]
    f = regime.profit_fee
    upper = price / (1.0 - f + f * price)
    lower = 1.0 - (1.0 - price) / (1.0 - f * price)
    return lower, upper


def fee_band_width(price: float, regime: FeeRegime | None = None) -> float:
    """Width of `breakeven_band` in probability points.

    Good: below ~0.01 (a cent of ambiguity).  Bad: above ~0.04.  PredictIt is
    bad everywhere in the middle -- the width peaks at **0.0526 at p = 0.50**
    and falls to ~0.019 at p = 0.10 and p = 0.90.  Compare Polymarket's
    ``2*rate*p*(1-p)`` = 0.02 at p = 0.50 for its 4% notional taker fee.
    """
    lower, upper = breakeven_band(price, regime)
    return upper - lower


def fee_adjusted_probability(
    price: float, side: str = "yes", regime: FeeRegime | None = None
) -> float:
    """The belief a trader must hold to justify paying ``price`` on ``side``.

    ``side="yes"`` returns the upper edge of `breakeven_band`, ``"no"`` the
    lower.  Use it to turn a *touch* price into the implied belief of whoever
    would lift it, which is the honest reading of an order book under a profit
    fee.  A midpoint is not that number and should not be substituted for it.
    """
    lower, upper = breakeven_band(price, regime)
    if side.lower() in {"yes", "y", "buy"}:
        return upper
    if side.lower() in {"no", "n", "sell"}:
        return lower
    raise ValueError(f"side must be 'yes' or 'no', got {side!r}")


# --------------------------------------------------------------------------
# the snapshot recorder -- history accumulates from today
# --------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def record_snapshot(
    markets: Sequence[dict[str, Any]],
    charts: dict[int, list[dict[str, Any]]] | None = None,
    when: datetime | None = None,
    directory: Path | None = None,
) -> Path:
    """Write one dated snapshot file.  This is how PredictIt gets a history.

    The public API serves only the present, so the archive is something we
    create: one file per run, never overwritten, accumulating into a series
    from the day the recorder starts.  The seven-day chart window makes the
    recorder forgiving -- a week's outage backfills -- but nothing before the
    first run is ever recoverable.

    ``charts`` is optional because a full chart sweep costs 40 minutes against
    the 5/minute limit.  A sensible cadence is the snapshot daily and the chart
    sweep weekly, since the chart's own window is seven days.

    Files land under ``data/predictit_snapshots/predictit-YYYY-MM-DD-HHMM.json``,
    gitignored per the repo rule that nothing under ``notebooks/*/data/`` is
    tracked.
    """
    when = when or _utcnow()
    directory = directory or SNAPSHOT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"predictit-{when:%Y-%m-%d-%H%M}.json"
    payload = {
        "captured_at": when.isoformat(),
        "venue": "predictit",
        "source": f"{BASE}/api/marketdata/all/",
        "fee_regime": fee_regime_on(when).name,
        "n_markets": len(markets),
        "n_contracts": sum(len(m.get("contracts") or []) for m in markets),
        "markets": list(markets),
        "charts": {str(k): v for k, v in (charts or {}).items()},
    }
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return path


def snapshot_paths(directory: Path | None = None) -> list[Path]:
    """Every recorded snapshot, oldest first."""
    directory = directory or SNAPSHOT_DIR
    if not directory.exists():
        return []
    return sorted(directory.glob("predictit-*.json"))


def load_snapshot(path: Path) -> dict[str, Any]:
    """Read one snapshot file back."""
    return json.loads(path.read_text(encoding="utf-8"))


def iter_snapshot_rows(path: Path) -> Iterator[dict[str, Any]]:
    """Flatten one snapshot into one row per contract.

    Row keys are venue-neutral so `metrics` can consume them alongside
    Polymarket and Kalshi rows.
    """
    snap = load_snapshot(path)
    captured = snap["captured_at"]
    for market in snap["markets"]:
        for contract in market.get("contracts") or []:
            yield {
                "venue": "predictit",
                "captured_at": captured,
                "market_id": market["id"],
                "market_name": market.get("name"),
                "contract_id": contract["id"],
                "contract_name": contract.get("name"),
                "status": contract.get("status"),
                "date_end": None if contract.get("dateEnd") == "NA" else contract.get("dateEnd"),
                # PredictIt's four quotes: what you pay to open, what you get to close.
                "best_buy_yes": contract.get("bestBuyYesCost"),
                "best_buy_no": contract.get("bestBuyNoCost"),
                "best_sell_yes": contract.get("bestSellYesCost"),
                "best_sell_no": contract.get("bestSellNoCost"),
                "last_trade": contract.get("lastTradePrice"),
                "last_close": contract.get("lastClosePrice"),
            }


def build_history(directory: Path | None = None) -> list[dict[str, Any]]:
    """Assemble every recorded snapshot into one long table, oldest first.

    This is the accumulated series.  Until the recorder has run for a while it
    is short; that is the honest state of PredictIt history and no amount of
    API cleverness changes it.
    """
    rows: list[dict[str, Any]] = []
    for path in snapshot_paths(directory):
        rows.extend(iter_snapshot_rows(path))
    return rows


def chart_rows(chart: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise `PredictItClient.chart` output to the neutral row shape."""
    out = []
    for r in chart:
        out.append(
            {
                "venue": "predictit",
                "market_id": r.get("marketId"),
                "contract_id": r.get("contractId"),
                "contract_name": r.get("contractName"),
                "date": (r.get("dateString") or "")[:10],
                "open": r.get("openSharePrice"),
                "high": r.get("highSharePrice"),
                "low": r.get("lowSharePrice"),
                "close": r.get("closeSharePrice"),
                "share_volume": r.get("tradeVolume"),
            }
        )
    return out


def chart_coverage(
    market: dict[str, Any], chart: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    """Which of a market's contracts the chart endpoint silently dropped.

    Always run this before treating charted contracts as a ladder.  On market
    7589 (11 House-seat rungs) it reports 5 missing rungs, all at the top of
    the distribution -- so any hazard or interval-mass computation over that
    ladder would be reading a truncated CDF as a complete one.
    """
    listed = {c["id"]: c.get("name") for c in market.get("contracts") or []}
    charted = {r.get("contractId") for r in chart}
    missing = {cid: name for cid, name in listed.items() if cid not in charted}
    return {
        "market_id": market.get("id"),
        "n_contracts": len(listed),
        "n_charted": len(charted),
        "n_missing": len(missing),
        "complete": not missing,
        "missing": missing,
    }


# --------------------------------------------------------------------------
# resolution text -- PredictIt does not serve any
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# structural limits, and the break they put in the price history
# --------------------------------------------------------------------------

#: Verified verbatim from **CFTC Letter No. 25-20** (14 July 2025), which amends
#: Letter 14-130.  These are not depth measurements -- PredictIt publishes no
#: size -- they are the regulatory ceiling that stands in for depth on this
#: venue, and they changed recently enough to break the price history.
#:
#: **Investment cap: per participant, per CONTRACT, indexed to FECA.**  The
#: letter says the limit "will be the limit for individual contributions to
#: campaigns per election, per candidate, under the Federal Election Campaign
#: Act (FECA), as that limit is adjusted going forward", and its footnote 1
#: gives the current FECA figure as **$3,500**, adjusted for inflation by the
#: FEC every two years.  Two consequences that are easy to get wrong:
#:
#: * It is **per contract, not per market.**  An 11-rung seat-count ladder
#:   therefore permits $38,500 of exposure to one question, not $3,500.
#: * It is **not a fixed number.**  Any code or analysis that hard-codes $3,500
#:   will silently drift as the FEC re-indexes.  Widely repeated third-party
#:   reviews also misread this figure as a flat per-market cap; the letter's own
#:   text is the authority.
#:
#: **The 5,000-trader-per-contract limit was eliminated**, and the stated reason
#: is a finding about data quality from the regulator itself: the academic
#: community reported that the cap "can create distortions in the data generated
#: by the Market, as new traders are not allowed to enter some popular
#: contracts, which then become illiquid and are not able to trade at market
#: prices."
#:
#: .. warning::
#:
#:    **That is a structural break in PredictIt's price series, dated
#:    2025-07-14.**  Before it, the platform's *most popular* contracts -- the
#:    ones a calibration study would weight most heavily -- were the ones most
#:    likely to be capped, illiquid, and by the CFTC's own account not trading
#:    at market prices.  Any study pooling PredictIt data across that date is
#:    mixing two different market microstructures, and the distortion is
#:    concentrated in exactly the contracts that matter most.  The much-cited
#:    finding that PredictIt beat Polymarket and Kalshi on 2024 election
#:    accuracy is drawn from the *capped* regime.
LIMITS: dict[str, Any] = {
    "source": "CFTC Letter No. 25-20, 2025-07-14, amending CFTC Letter No. 14-130",
    "investment_cap_basis": "FECA individual contribution limit per election per candidate",
    "investment_cap_scope": "per participant, per contract",
    "investment_cap_usd_at_issue": 3500,
    "investment_cap_is_indexed": True,
    "traders_per_contract_limit": None,
    "traders_per_contract_limit_before": 5000,
    "trader_cap_removed_on": date(2025, 7, 14),
    "operator": "Prediction Market Research Consortium, Inc. (PMRC), a US not-for-profit",
    "operator_before": "Victoria University of Wellington",
    "contract_selection": "a board of academics from US universities, staggered two-year terms",
}

#: The two dates that break PredictIt's price history.  Any corpus spanning
#: either is not one market.
STRUCTURAL_BREAKS: tuple[tuple[date, str], ...] = (
    (date(2025, 7, 14), "5,000-trader-per-contract cap removed; investment cap re-indexed to FECA; operator changed to PMRC"),
    (date(2026, 9, 23), "5% withdrawal fee removed; ACH deposits free; profit fee unchanged at 10%"),
)

#: PredictIt serves no resolution criteria on any public endpoint.  The rules
#: exist, but only as prose on the market's HTML page under a "Rules" tab
#: rendered client-side.  So the resolution-quality metrics in `metrics` --
#: text length, named source, dispute history -- are **not computable** for
#: this venue from the API, and `metrics.VENUE_COVERAGE` records that rather
#: than quietly returning None.
RESOLUTION_TEXT_AVAILABLE = False

#: Resolution-quality metrics for this venue are unavailable, so the
#: source-naming test lives only in `metrics.names_machine_checkable_source`.
#: It is deliberately not duplicated here: two copies of the same pattern in
#: two modules drift, and the catalogue is the one that should own it.
