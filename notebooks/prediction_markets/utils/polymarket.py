"""Read-only Polymarket reader and closed-universe harvester.

Scope and rules
---------------
Unauthenticated GET/POST against three public hosts.  No wallet, no keys, no
order placement, nothing that can sign a transaction is imported here.  The
module talks to:

* ``gamma-api.polymarket.com``  -- metadata: events, markets, tags, series.
  Keyset pagination only (``/events`` is deprecated with a sunset date already
  past, and ``offset`` hard-stops at 20000 with HTTP 422).
* ``clob.polymarket.com``       -- price paths.  ``POST /batch-prices-history``
  takes 20 token ids per call and is the workhorse.  ``fidelity`` **must** be
  >= 720 or a resolved market returns ``{"history": []}`` with HTTP 200; we pin
  1440 (daily).
* ``data-api.polymarket.com/v2`` -- ``/resolutions`` is the authoritative
  settled outcome (``price`` is 1e18-scaled, ``69`` is the unresolved
  sentinel) and carries ``was_disputed``.  It accepts ``condition=`` or
  ``event_id=``, comma separated, at most 20 distinct values.  This host rate
  limits where the other two do not, so it gets a slower pace and 429 backoff.

Everything is cached under ``data/_cache/polymarket/`` so a harvest is resumable
and re-runnable without re-fetching.  Closed markets are immutable, so the cache
never expires for them.

Measured in this harvest, not inherited
---------------------------------------
* ``POST /batch-prices-history`` takes ``{"markets": [...ids], "interval",
  "fidelity"}`` -- *not* ``requests``, and not per-id objects.  **20 is a hard
  cap**: 50 returns ``400 'markets' exceeds maximum of 20``.
* At ``fidelity=1440`` the delivered series is genuinely **one print per day in
  the 00:00 UTC hour**, verified across 2,000 paths / ~107k intervals: 24h
  spacing dominates, every print lands in hour 0, and the rest are whole-day
  multiples (missing days).  So the midday-print problem that motivates a
  daily-reduction rule belongs to ``fidelity=720``, not to this corpus.
* ``/v2/resolutions`` accepts ``event_id`` as well as ``condition``, 20
  comma-separated values either way.  ``event_id`` is far cheaper: one slot
  covers all of an event's markets rather than one per market.
* **Events carry no series reference.** Neither ``/events/keyset`` nor
  ``/events/{id}`` returns a ``series`` key, and ``include_series=true`` is
  ignored.  ``/series?slug=`` works, so the only way to ask the venue whether it
  links a ladder is to reconstruct the series slug from the event slugs.
* ``cumulativeMarkets`` is set on **1 of 10,465** closed political/financial
  events, and ``negRisk`` is frequently omitted rather than false.  Neither can
  carry ladder detection on its own.
* ``order=id&ascending=true`` keeps the keyset cursor chain stable over an
  already-closed corpus, which is what makes the page cache reusable; ordering
  by volume or closedTime reshuffles it on every run.

Usage
-----
    python utils/polymarket.py harvest            # full closed pol/fin universe
    python utils/polymarket.py harvest --limit-events 500   # smoke test
    python utils/polymarket.py ladders            # re-derive ladders from cache
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import httpx

# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
NOTEBOOK_DIR = HERE.parent
DATA_DIR = NOTEBOOK_DIR / "data"
# Namespaced: sibling venue readers (kalshi, predictit, iem) write into the
# same gitignored data directory.
CACHE_DIR = DATA_DIR / "_cache" / "polymarket"

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA_V2 = "https://data-api.polymarket.com/v2"

USER_AGENT = "gly.fish-research/0.1 (read-only market-data study; contact troy.stribling@gmail.com)"

# Pace per host, seconds between requests, enforced globally across worker
# threads.  Gamma and CLOB tolerated far more than this in the reference run
# (81-155 req/s sustained, zero 429); we are deliberately slow.  data-api v2 is
# the one host with a documented 429 + Retry-After, so it is slowest and is
# never called concurrently.
PACE = {GAMMA: 0.35, CLOB: 0.12, DATA_V2: 0.60}

# Concurrency for the price backfill only.  A batch round trip is ~1.7s, so
# sequential fetching is round-trip bound rather than pace bound; six workers
# against a 0.12s global gate is ~8 req/s, about 5% of the measured tolerance.
PRICE_WORKERS = 6

DAILY_FIDELITY = 1440  # minutes.  Below 720 a resolved market returns nothing.
BATCH_TOKENS = 20      # POST /batch-prices-history cap
BATCH_CONDITIONS = 20  # /v2/resolutions cap

UNRESOLVED_PRICE_SENTINEL = "69"
PRICE_SCALE = 10**18

# --------------------------------------------------------------------------
# The tag registry.
#
# Tag slugs are dirty and there are >=4000 of them; `multi-strikes` alone means
# "multiple strike prices" and silently drags ~1000 Bitcoin threshold markets
# into anything that trusts it.  So the universe is defined by a hand-curated
# registry, seeded from the task brief and extended with each seed tag's
# `/tags/slug/{slug}/related-tags/tags` neighbours, keeping only the political
# and financial/macro ones.  Sports and crypto-price tags are excluded by
# construction: they are out of scope, and crypto dailies would swamp the
# corpus.
# --------------------------------------------------------------------------

POLITICAL_TAGS: tuple[str, ...] = (
    # seeds
    "politics", "elections", "geopolitics", "world",
    # politics neighbours
    "trump", "midterms", "senate-midterms", "house-elections",
    "governor-midterms", "mayoral-elections", "global-elections", "primaries",
    "congress", "gov-shutdown", "us-presidential-election", "israel-election",
    "french-election", "epstein",
    # geopolitics / world neighbours (theatre axis)
    "iran", "lebanon", "ukraine", "ukraine-map", "cuba", "venezuela",
    "middle-east", "gaza", "israel", "syria", "yemen", "turkey", "sudan",
    "china", "thailand-cambodia", "india-pakistan", "russia", "brazil",
    "canada", "south-korea", "nepal-election", "romania",
    # legacy
    "war", "foreign-policy",
)

FINANCIAL_TAGS: tuple[str, ...] = (
    # seeds
    "economy", "fed", "inflation",
    # economy neighbours
    "fed-rates", "macro-indicators", "gdp", "global-rates", "taxes",
    "treasuries", "consumer", "housing", "labor", "recession", "trade-war",
    "oil", "business",
)

TAG_DOMAIN: dict[str, str] = {
    **{t: "political" for t in POLITICAL_TAGS},
    **{t: "financial" for t in FINANCIAL_TAGS},
}

ALL_TAGS: tuple[str, ...] = POLITICAL_TAGS + FINANCIAL_TAGS


class PolymarketError(RuntimeError):
    """Any non-recoverable failure talking to a Polymarket host."""


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------


def _host_of(url: str) -> str:
    for host in (GAMMA, CLOB, DATA_V2):
        if url.startswith(host):
            return host
    return url


class _Pacer:
    """One monotonic gate per host."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        pace = PACE.get(host, 0.5)
        with self._lock:
            last = self._last.get(host, 0.0)
            gap = time.monotonic() - last
            if gap < pace:
                time.sleep(pace - gap)
            self._last[host] = time.monotonic()


def _blob_path(root: Path, key: str) -> Path:
    digest = hashlib.sha1(key.encode()).hexdigest()
    return root / digest[:2] / f"{digest}.json.gz"


def _read_blob(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, EOFError, json.JSONDecodeError):
        return None


def _write_blob(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, path)


@dataclass
class Stats:
    requests: int = 0
    cache_hits: int = 0
    bytes_down: int = 0
    retries: int = 0
    rate_limited: int = 0
    errors: int = 0
    by_host: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    # The price backfill runs on several threads, and `+=` on an int attribute
    # is a read-modify-write that can interleave, so counts would silently drift
    # low -- and the request count is a reported figure.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def bump(self, **deltas: int) -> None:
        with self._lock:
            for name, delta in deltas.items():
                setattr(self, name, getattr(self, name) + delta)

    def bump_host(self, host: str) -> None:
        with self._lock:
            self.by_host[host] += 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "cache_hits": self.cache_hits,
            "bytes_downloaded": self.bytes_down,
            "retries": self.retries,
            "http_429": self.rate_limited,
            "errors": self.errors,
            "requests_by_host": dict(self.by_host),
        }


class PolymarketReader:
    """Unauthenticated, cached, politely paced reader."""

    def __init__(
        self,
        cache_dir: Path | str = CACHE_DIR,
        *,
        client: httpx.Client | None = None,
        log: Any = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.http_cache = self.cache_dir / "http"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._owns_client = client is None
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=httpx.Timeout(60.0, connect=20.0),
            follow_redirects=True,
        )
        self.pacer = _Pacer()
        self.stats = Stats()
        self._log = log or (lambda msg: print(msg, flush=True))

    # -- plumbing ---------------------------------------------------------

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "PolymarketReader":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _cache_key(self, method: str, url: str, params: dict | None, body: Any) -> str:
        return "\n".join([
            method,
            url,
            json.dumps(params or {}, sort_keys=True),
            json.dumps(body, sort_keys=True) if body is not None else "",
        ])

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json_body: Any = None,
        use_cache: bool = True,
        max_attempts: int = 5,
    ) -> Any:
        """One cached, paced, backing-off request.  Returns decoded JSON."""
        key = self._cache_key(method, url, params, json_body)
        path = _blob_path(self.http_cache, key)
        if use_cache:
            hit = _read_blob(path)
            if hit is not None:
                self.stats.bump(cache_hits=1)
                return hit

        host = _host_of(url)
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            self.pacer.wait(host)
            try:
                resp = self.client.request(method, url, params=params, json=json_body)
            except httpx.HTTPError as exc:  # transport level
                last_exc = exc
                self.stats.bump(retries=1)
                time.sleep(min(30.0, 2.0 * 2**attempt) + random.random())
                continue

            self.stats.bump(requests=1, bytes_down=len(resp.content))
            self.stats.bump_host(host)

            if resp.status_code == 429:
                self.stats.bump(rate_limited=1)
                retry_after = resp.headers.get("retry-after")
                delay = float(retry_after) if (retry_after or "").replace(".", "", 1).isdigit() else 0.0
                delay = max(delay, min(60.0, 5.0 * 2**attempt)) + random.random()
                self._log(f"  [429] {host} -- backing off {delay:.1f}s (attempt {attempt + 1})")
                time.sleep(delay)
                continue

            if resp.status_code >= 500:
                self.stats.bump(retries=1)
                time.sleep(min(30.0, 2.0 * 2**attempt) + random.random())
                continue

            if resp.status_code >= 400:
                self.stats.bump(errors=1)
                raise PolymarketError(
                    f"HTTP {resp.status_code} {method} {url} params={params}: {resp.text[:300]}"
                )

            try:
                payload = resp.json()
            except ValueError as exc:
                raise PolymarketError(f"non-JSON from {url}: {resp.text[:200]}") from exc

            if use_cache:
                _write_blob(path, payload)
            return payload

        self.stats.bump(errors=1)
        raise PolymarketError(f"exhausted retries for {method} {url}: {last_exc}")

    def get(self, url: str, **kw: Any) -> Any:
        return self.request("GET", url, **kw)

    # -- discovery --------------------------------------------------------

    def count_events(self, **filters: Any) -> int:
        """Exact event count.  ``/events/pagination`` is the only honest total
        (and returns a nonsense ``totalResults: 2`` when called with no filter
        at all, so always pass one)."""
        if not filters:
            raise ValueError("pass at least one filter; a bare call returns nonsense")
        payload = self.get(f"{GAMMA}/events/pagination", params={"limit": 1, **filters})
        pag = payload.get("pagination", payload) if isinstance(payload, dict) else {}
        return int(pag.get("totalResults", 0))

    def tags_page(self, offset: int = 0, limit: int = 100) -> list[dict]:
        """``/tags`` is hard-capped at 100 per page."""
        payload = self.get(f"{GAMMA}/tags", params={"limit": limit, "offset": offset})
        return payload if isinstance(payload, list) else payload.get("data", [])

    def related_tags(self, slug: str) -> list[dict]:
        payload = self.get(f"{GAMMA}/tags/slug/{slug}/related-tags/tags")
        return payload if isinstance(payload, list) else payload.get("data", [])

    def iter_events(
        self,
        *,
        tag_slug: str | None = None,
        closed: bool | None = None,
        order: str = "id",
        ascending: bool = True,
        limit: int = 100,
        max_pages: int | None = None,
        **extra: Any,
    ) -> Iterator[dict]:
        """Keyset walk over ``/events/keyset``.

        ``order=id&ascending=true`` is deliberate: it makes the cursor chain
        *stable* for an already-closed corpus, so a re-run replays every page
        out of cache and only fetches the new tail.  Ordering by closedTime or
        volume reshuffles the chain on every run and defeats the cache.
        """
        params: dict[str, Any] = {"limit": min(limit, 100), "order": order,
                                  "ascending": str(ascending).lower(), **extra}
        if tag_slug:
            params["tag_slug"] = tag_slug
        if closed is not None:
            params["closed"] = str(closed).lower()

        cursor: str | None = None
        pages = 0
        while True:
            page_params = dict(params)
            if cursor:
                page_params["after_cursor"] = cursor
            payload = self.get(f"{GAMMA}/events/keyset", params=page_params)
            events = payload.get("events") or []
            if not events:
                return
            yield from events
            pages += 1
            cursor = payload.get("next_cursor")
            if not cursor or (max_pages is not None and pages >= max_pages):
                return

    def event_by_slug(self, slug: str) -> dict | None:
        try:
            payload = self.get(f"{GAMMA}/events/slug/{slug}")
        except PolymarketError:
            return None
        if isinstance(payload, list):
            return payload[0] if payload else None
        return payload

    def series_by_slug(self, slug: str) -> dict | None:
        """``/series?slug=`` is the only cheap way in: events carry no series
        reference at all (verified -- neither ``/events/keyset`` nor
        ``/events/{id}`` returns a ``series`` key), so the link has to be
        guessed from the slug stem and confirmed here."""
        try:
            payload = self.get(f"{GAMMA}/series", params={"slug": slug})
        except PolymarketError:
            return None
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        return rows[0] if rows else None

    # -- prices -----------------------------------------------------------

    def price_path(self, token_id: str, *, fidelity: int = DAILY_FIDELITY,
                   interval: str = "max") -> list[dict]:
        payload = self.get(
            f"{CLOB}/prices-history",
            params={"market": token_id, "interval": interval, "fidelity": fidelity},
        )
        return payload.get("history") or []

    def batch_price_paths(
        self, token_ids: Sequence[str], *, fidelity: int = DAILY_FIDELITY,
        interval: str = "max",
    ) -> dict[str, list[dict]]:
        """``POST /batch-prices-history``, 20 token ids per call.

        Body shape is ``{"markets": [...], "interval": ..., "fidelity": ...}``
        -- note ``markets``, not ``requests``, and a flat list of ids rather
        than per-id objects.  The response is keyed by token id, and a token
        with no stored history is simply absent from the map.
        """
        if not token_ids:
            return {}
        if len(token_ids) > BATCH_TOKENS:
            raise ValueError(f"at most {BATCH_TOKENS} token ids per batch call")
        payload = self.request(
            "POST",
            f"{CLOB}/batch-prices-history",
            json_body={"markets": list(token_ids), "interval": interval, "fidelity": fidelity},
        )
        return payload.get("history") or {}

    def iter_batch_price_paths(
        self, token_ids: Sequence[str], *, workers: int = PRICE_WORKERS,
        fidelity: int = DAILY_FIDELITY,
    ) -> Iterator[tuple[list[str], dict[str, list[dict]]]]:
        """Yield ``(batch, history)`` for every batch, a few in flight at once.

        Results come back as they complete, so the caller must key off the
        returned batch rather than assume input order.
        """
        batches = list(_chunk(list(token_ids), BATCH_TOKENS))
        if not batches:
            return
        if workers <= 1:
            for batch in batches:
                yield batch, self._safe_batch(batch, fidelity)
            return
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {pool.submit(self._safe_batch, b, fidelity): b for b in batches}
            for fut in as_completed(pending):
                yield pending[fut], fut.result()

    def _safe_batch(self, batch: list[str], fidelity: int) -> dict[str, list[dict]]:
        try:
            return self.batch_price_paths(batch, fidelity=fidelity)
        except PolymarketError as exc:
            self._log(f"  price batch failed ({len(batch)} tokens): {exc}")
            return {}

    # -- outcomes ---------------------------------------------------------

    def resolutions(self, *, conditions: Sequence[str] | None = None,
                    event_ids: Sequence[str] | None = None) -> list[dict]:
        """``/v2/resolutions`` -- the authoritative settled outcome.

        ``event_id`` is the cheap key: 20 events per call returns every market
        in them, where ``condition`` would need one slot per market.
        """
        params: dict[str, Any] = {}
        if conditions:
            if len(conditions) > BATCH_CONDITIONS:
                raise ValueError(f"at most {BATCH_CONDITIONS} conditions per call")
            params["condition"] = ",".join(conditions)
        if event_ids:
            if len(event_ids) > BATCH_CONDITIONS:
                raise ValueError(f"at most {BATCH_CONDITIONS} event ids per call")
            params["event_id"] = ",".join(str(e) for e in event_ids)
        if not params:
            return []
        payload = self.get(f"{DATA_V2}/resolutions", params=params)
        return payload.get("data") or []

    def open_interest(self, conditions: Sequence[str]) -> list[dict]:
        payload = self.get(f"{DATA_V2}/oi", params={"condition": ",".join(conditions)})
        return payload.get("data") or []

    def book(self, token_id: str) -> dict:
        """The only trustworthy depth measurement.  ``liquidityNum`` is total
        resting-bid notional across *both* books and ranks zero-bid markets as
        their event's most liquid."""
        return self.get(f"{CLOB}/book", params={"token_id": token_id})


# --------------------------------------------------------------------------
# Field normalisation
# --------------------------------------------------------------------------


def _jsonish(value: Any) -> Any:
    """Gamma returns several array fields as JSON *strings*."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("[", "{")):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ts(value: Any) -> str | None:
    """Gamma emits at least three timestamp spellings, including
    ``2026-05-09 19:52:26+00`` alongside ``2026-05-09T19:35:40.504738Z`` for the
    same logical instant in one response tree.  Normalise to UTC ISO-8601."""
    if not value:
        return None
    text = str(value).strip()
    candidates = [text, text.replace(" ", "T")]
    for cand in candidates:
        c = cand
        if c.endswith("Z"):
            c = c[:-1] + "+00:00"
        elif re.search(r"[+-]\d{2}$", c):
            c = c + ":00"
        try:
            dt = datetime.fromisoformat(c)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return text


def _date_int(iso: str | None) -> int | None:
    """``YYYYMMDD`` mirror -- the house convention, and what lets a document
    store answer "what resolved in window W"."""
    if not iso:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso)
    return int(m.group(1) + m.group(2) + m.group(3)) if m else None


def resolution_outcome(row: dict | None) -> dict[str, Any]:
    """Decode a ``/v2/resolutions`` record.

    ``price`` is 1e18-scaled: 1e18 = Yes, 0 = No, 5e17 = a UMA "Unknown"
    50-50 vote, and the string ``"69"`` is the unresolved sentinel.  So the
    settled outcome is **not** boolean.
    """
    out: dict[str, Any] = {
        "resolution_status": None,
        "settled_yes_price": None,
        "settled_outcome": None,
        "was_disputed": None,
        "extended_review": None,
        "resolution_tx": None,
        "resolution_ts": None,
    }
    if not row:
        return out
    raw = str(row.get("price", ""))
    out["resolution_status"] = row.get("status")
    out["was_disputed"] = row.get("was_disputed")
    out["extended_review"] = row.get("extended_review")
    out["resolution_tx"] = row.get("transaction_hash")
    ts = row.get("last_update_timestamp")
    if ts:
        try:
            out["resolution_ts"] = datetime.fromtimestamp(int(ts), timezone.utc)\
                .isoformat().replace("+00:00", "Z")
        except (TypeError, ValueError, OSError):
            pass
    if raw and raw != UNRESOLVED_PRICE_SENTINEL:
        try:
            val = int(raw) / PRICE_SCALE
        except ValueError:
            return out
        out["settled_yes_price"] = val
        if val >= 0.999:
            out["settled_outcome"] = "YES"
        elif val <= 0.001:
            out["settled_outcome"] = "NO"
        elif abs(val - 0.5) < 1e-6:
            out["settled_outcome"] = "FIFTY_FIFTY"
        else:
            out["settled_outcome"] = "PARTIAL"
    return out


def market_record(event: dict, market: dict, tags: list[dict],
                  domains: set[str]) -> dict[str, Any]:
    """One flat row per market, carrying every field the analysis needs."""
    tokens = _jsonish(market.get("clobTokenIds")) or []
    outcomes = _jsonish(market.get("outcomes")) or []
    prices = _jsonish(market.get("outcomePrices")) or []
    statuses = _jsonish(market.get("umaResolutionStatuses")) or []

    end_iso = _ts(market.get("endDate"))
    closed_iso = _ts(market.get("closedTime"))
    start_iso = _ts(market.get("startDate"))

    return {
        # -- identity ----------------------------------------------------
        "market_id": str(market.get("id")),
        "condition_id": market.get("conditionId"),
        "question_id": market.get("questionID"),
        "slug": market.get("slug"),
        "event_id": str(event.get("id")),
        "event_slug": event.get("slug"),
        "event_ticker": event.get("ticker"),
        "event_title": event.get("title"),
        "yes_token_id": tokens[0] if len(tokens) > 0 else None,
        "no_token_id": tokens[1] if len(tokens) > 1 else None,
        "outcomes": outcomes,
        "group_item_title": market.get("groupItemTitle"),
        "group_item_threshold": market.get("groupItemThreshold"),
        # -- the contract ------------------------------------------------
        "question": market.get("question"),
        "description": market.get("description"),          # the resolution text, verbatim
        "resolution_source": market.get("resolutionSource") or None,
        "resolved_by": market.get("resolvedBy"),
        # -- lifecycle ---------------------------------------------------
        "created_at": _ts(market.get("createdAt")),
        "start_date": start_iso,
        "accepting_orders_ts": _ts(market.get("acceptingOrdersTimestamp")),
        "end_date": end_iso,                               # eligibility, NOT resolution
        "closed_time": closed_iso,                         # market-level clock
        "event_closed_time": _ts(event.get("closedTime")), # a different clock, same tree
        "uma_end_date": _ts(market.get("umaEndDate")),
        "updated_at": _ts(market.get("updatedAt")),
        "created_at_int": _date_int(_ts(market.get("createdAt"))),
        "end_date_int": _date_int(end_iso),
        "closed_time_int": _date_int(closed_iso),
        "active": market.get("active"),
        "closed": market.get("closed"),
        "archived": market.get("archived"),
        "accepting_orders": market.get("acceptingOrders"),
        # -- quality fields the API offers --------------------------------
        "volume_num": _num(market.get("volumeNum")),
        "volume_clob": _num(market.get("volumeClob")),
        "liquidity_num": _num(market.get("liquidityNum")),   # both-sides bid notional; not depth
        "event_open_interest": _num(event.get("openInterest")),
        "event_volume": _num(event.get("volume")),
        "competitive": _num(market.get("competitive")),      # Polymarket's own book-quality score
        "spread": _num(market.get("spread")),
        "best_bid": _num(market.get("bestBid")),
        "best_ask": _num(market.get("bestAsk")),
        "last_trade_price": _num(market.get("lastTradePrice")),
        "outcome_prices": prices,
        "one_day_price_change": _num(market.get("oneDayPriceChange")),
        "one_week_price_change": _num(market.get("oneWeekPriceChange")),
        "one_month_price_change": _num(market.get("oneMonthPriceChange")),
        "order_price_min_tick_size": _num(market.get("orderPriceMinTickSize")),
        "order_min_size": _num(market.get("orderMinSize")),
        "enable_order_book": market.get("enableOrderBook"),
        "neg_risk": market.get("negRisk"),
        "neg_risk_market_id": market.get("negRiskMarketID"),
        "neg_risk_other": market.get("negRiskOther"),
        "event_neg_risk": event.get("negRisk"),
        "event_neg_risk_augmented": event.get("negRiskAugmented"),
        "event_cumulative_markets": event.get("cumulativeMarkets"),
        "fee_type": market.get("feeType"),
        "fee_schedule": market.get("feeSchedule"),
        "fees_enabled": market.get("feesEnabled"),
        "holding_rewards_enabled": market.get("holdingRewardsEnabled"),
        "uma_bond": _num(market.get("umaBond")),
        "uma_reward": _num(market.get("umaReward")),
        "uma_resolution_status": market.get("umaResolutionStatus"),
        "uma_resolution_statuses": statuses,
        "automatically_resolved": market.get("automaticallyResolved"),
        "restricted": market.get("restricted"),
        # -- provenance ---------------------------------------------------
        "tag_slugs": sorted({t.get("slug") for t in tags if t.get("slug")}),
        "domains": sorted(domains),
    }


# --------------------------------------------------------------------------
# Ladder detection
#
# The user's framing, and the reason this section exists: a row of "X by date
# T" markets is a CUMULATIVE DISTRIBUTION over the resolution date.  Adjacent
# rungs difference into the probability mass in each interval, exactly as an
# option strike ladder gives a density over price.  A ladder can be judged on
# internal coherence -- monotonicity, implied interval hazards, arbitrage
# bounds -- which a single market cannot.  So the grouping is a first-class
# output, not a convenience.
#
# Three kinds are recorded, because they are different objects:
#
#   cumulative        "X by T1", "X by T2", ...   -> price IS the CDF at T
#   exclusive_bucket  "When will X happen?" with disjoint date buckets inside
#                     one neg-risk event -> price is the interval MASS; the CDF
#                     is the running sum
#   threshold         "X above/below V" -> the option-strike analogue over
#                     value rather than date; recorded but not a date ladder
# --------------------------------------------------------------------------

# The subject string is lowercased, so the placeholders have to be lowercase
# too -- guarding on "<DATE>" against a lowercased subject silently matches
# nothing, which is exactly how the cross-event ladder rule came to be dead.
DATE_TOKEN = "<date>"
NUM_TOKEN = "<num>"
MARKER_TOKEN = "<by>"

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sept": 9, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))

# Ordered most-specific first.  Each returns a normalised deadline.
_DATE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("ymd",        r"\b(?P<y>20\d{2})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b"),
    ("mdy",        rf"\b(?P<mon>{_MONTH_RE})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>20\d{{2}})\b"),
    ("slash",      r"\b(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>20\d{2}|\d{2})\b"),
    ("eom_year",   rf"\b(?:the\s+)?end\s+of\s+(?P<mon>{_MONTH_RE})\.?\s+(?P<y>20\d{{2}})\b"),
    ("my",         rf"\b(?P<mon>{_MONTH_RE})\.?\s+(?P<y>20\d{{2}})\b"),
    ("quarter",    r"\b(?P<q>q[1-4])\s*,?\s*(?P<y>20\d{2})\b"),
    ("half",       r"\b(?P<h>h[12])\s*,?\s*(?P<y>20\d{2})\b"),
    ("eoy",        r"\b(?:the\s+)?end\s+of\s+(?P<y>20\d{2})\b"),
    ("md",         rf"\b(?P<mon>{_MONTH_RE})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\b"),
    ("eom",        rf"\b(?:the\s+)?end\s+of\s+(?P<mon>{_MONTH_RE})\b"),
    # A bare month is only a date when a preposition puts it in a deadline
    # position: "a ceasefire before July" is a rung, "the July press
    # conference" is a subject.  The preposition is captured so it can be
    # re-emitted rather than swallowed.
    ("pre_month",  rf"\b(?P<pre>by|before|prior to|no later than|on or before|in|on|during)"
                   rf"\s+(?:the\s+)?(?P<mon>{_MONTH_RE})\b(?!\s*\.?\s*\d)"),
    ("year",       r"\b(?P<y>20\d{2})\b"),
)
_DATE_RE = re.compile(
    "|".join(f"(?P<{name}>{pat})" for name, pat in
             ((n, p.replace("(?P<", f"(?P<{n}_")) for n, p in _DATE_PATTERNS)),
    re.IGNORECASE,
)

# A cumulative rung says "by"/"before"/"prior to" in front of its date.  That
# marker is the whole discriminator: without it, "the 2026 Senate race" and
# "the 2028 Senate race" collapse into one bogus ladder.
_CUMULATIVE_MARKER = re.compile(
    r"\b(by|before|prior to|no later than|on or before|as of)\b", re.IGNORECASE)
# The marker has to be the word that actually GOVERNS the date, not merely one
# that appears nearby.  "largest company in the world by market cap on <date>"
# has a 'by' seven words before the date and is a point-in-time question, so a
# proximity test misreads a whole family of recurring markets as a CDF.
_MARKER_GOVERNS = re.compile(
    r"\b(by|before|prior to|no later than|on or before|as of)\s+(?:the\s+)?$",
    re.IGNORECASE)
# Only the occurrence that actually governs the date is canonicalised, so a
# stray 'by' elsewhere in the question ("a bill passed by Congress") is left
# alone.
_MARKER_BEFORE_DATE = re.compile(
    r"\b(?:by|before|prior to|no later than|on or before)\s+(?:the\s+)?<date>")
_THRESHOLD_MARKER = re.compile(
    r"\b(above|below|over|under|at least|greater than|less than|exceed|reach|hit|or more|or higher|or lower)\b",
    re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?%?\b")

_EOM = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
        7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _clamp_day(year: int, month: int, day: int) -> date | None:
    last = _EOM[month] + (1 if month == 2 and year % 4 == 0 and
                          (year % 100 != 0 or year % 400 == 0) else 0)
    try:
        return date(year, month, min(max(day, 1), last))
    except ValueError:
        return None


def _deadline_from_match(m: re.Match, ref_year: int | None,
                         marker: str | None = None) -> date | None:
    g = m.groupdict()

    def grab(kind: str, name: str) -> str | None:
        return g.get(f"{kind}_{name}")

    for kind, _ in _DATE_PATTERNS:
        if g.get(kind) is None:
            continue
        if kind == "year":
            y = int(grab(kind, "y"))
            # "before 2027" is a CDF point at the end of 2026, not 2027.
            if marker in ("before", "prior to"):
                return _clamp_day(y - 1, 12, 31)
            return _clamp_day(y, 12, 31)
        if kind == "ymd":
            return _clamp_day(int(grab(kind, "y")), int(grab(kind, "m")), int(grab(kind, "d")))
        if kind == "mdy":
            mon = MONTHS[grab(kind, "mon").lower().rstrip(".")]
            return _clamp_day(int(grab(kind, "y")), mon, int(grab(kind, "d")))
        if kind == "slash":
            y = int(grab(kind, "y"))
            y = y + 2000 if y < 100 else y
            return _clamp_day(y, int(grab(kind, "m")), int(grab(kind, "d")))
        if kind in ("eom_year", "my"):
            mon = MONTHS[grab(kind, "mon").lower().rstrip(".")]
            y = int(grab(kind, "y"))
            return _clamp_day(y, mon, 31)
        if kind == "quarter":
            q = int(grab(kind, "q")[1])
            return _clamp_day(int(grab(kind, "y")), q * 3, 31)
        if kind == "half":
            h = int(grab(kind, "h")[1])
            return _clamp_day(int(grab(kind, "y")), 6 if h == 1 else 12, 31)
        if kind == "eoy":
            return _clamp_day(int(grab(kind, "y")), 12, 31)
        if kind == "md":
            if ref_year is None:
                return None
            mon = MONTHS[grab(kind, "mon").lower().rstrip(".")]
            return _clamp_day(ref_year, mon, int(grab(kind, "d")))
        if kind == "eom":
            if ref_year is None:
                return None
            mon = MONTHS[grab(kind, "mon").lower().rstrip(".")]
            return _clamp_day(ref_year, mon, 31)
        if kind == "pre_month":
            if ref_year is None:
                return None
            mon = MONTHS[grab(kind, "mon").lower().rstrip(".")]
            pre = (grab(kind, "pre") or "").lower()
            if pre in ("before", "prior to"):
                # "before July" closes at the end of June.
                mon, year = (12, ref_year - 1) if mon == 1 else (mon - 1, ref_year)
                return _clamp_day(year, mon, 31)
            return _clamp_day(ref_year, mon, 31)
    return None


def parse_deadline(text: str, ref_year: int | None = None
                   ) -> tuple[str, str | None, str | None, tuple[str, ...]]:
    """Return ``(subject_with_placeholder, deadline_iso, marker, other_numbers)``.

    ``subject_with_placeholder`` is the question with every date expression
    replaced by ``<DATE>`` and every number by ``<NUM>``, lowercased and
    whitespace-collapsed.  Two rungs of the same ladder share it exactly.
    ``marker`` is the cumulative word that preceded the date, or ``None``.
    ``other_numbers`` are the literal non-date numbers, which a date ladder
    must hold FIXED -- otherwise "oil above 70 by March" and "oil above 80 by
    June" would merge into one ladder that varies along two axes at once.
    """
    if not text:
        return "", None, None, ()
    last_deadline: date | None = None
    marker: str | None = None
    out: list[str] = []
    pos = 0
    for m in _DATE_RE.finditer(text):
        out.append(text[pos:m.start()])
        pos = m.end()
        # A pre_month match consumed its own preposition, so put it back --
        # otherwise the deadline marker is lost and the rung looks like a
        # bare date.
        pre = m.groupdict().get("pre_month_pre")
        if pre:
            local_marker = pre.lower() if _CUMULATIVE_MARKER.fullmatch(pre.lower()) else None
            out.append(f" {pre.lower()} {DATE_TOKEN} ")
        else:
            out.append(f" {DATE_TOKEN} ")
            lead = text[max(0, m.start() - 24):m.start()]
            governs = _MARKER_GOVERNS.search(lead)
            local_marker = governs.group(1).lower() if governs else None
        if local_marker:
            marker = local_marker
        d = _deadline_from_match(m, ref_year, local_marker)
        if d and (last_deadline is None or d > last_deadline):
            last_deadline = d
    out.append(text[pos:])
    masked = "".join(out)
    numbers = tuple(_NUMBER_RE.findall(masked))
    subject = _NUMBER_RE.sub(f" {NUM_TOKEN} ", masked)
    subject = re.sub(r"[^\w<>\s]", " ", subject).lower()
    subject = re.sub(r"\s+", " ", subject).strip()
    # 'by', 'before', 'prior to' and 'no later than' are the same rung on a
    # CDF, so they collapse to one token -- otherwise the Russia-Ukraine
    # ceasefire ladder splits into a 'before July' half and a 'by August 15'
    # half.  'in' and 'on' are NOT collapsed: "ceasefire in 2025" is an
    # interval, not a deadline, and belongs to a different object.
    subject = _MARKER_BEFORE_DATE.sub(f"{MARKER_TOKEN} {DATE_TOKEN}", subject)
    return (subject, (last_deadline.isoformat() if last_deadline else None),
            marker, numbers)


_RESIDUAL_LABELS = {"other", "none", "none of the above", "no change", "neither",
                    "something else", "any other", "all others"}
_LABEL_NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

# A word that signs the *quantity* -- '50+ bps decrease' is a move of -50.
_SIGN_NEGATIVE = re.compile(
    r"\b(decrease[sd]?|decreasing|cut[s]?|reduction|drop[s]?|negative)\b|[−]", re.IGNORECASE)
# A word that only sets the *inequality* -- 'below 80%' is still the level 80.
# It orders the rung, it does not negate it.
_INEQ_BELOW = re.compile(
    r"^\s*[<≤↓]|\b(below|under|less than|fewer|or less|or fewer|or lower|or below|at most)\b",
    re.IGNORECASE)
_INEQ_ABOVE = re.compile(
    r"^\s*[>≥↑]|\b(above|over|greater than|at least|or more|or higher|or above)\b|\+\s*$",
    re.IGNORECASE)

# Tokens that are units or comparators rather than subject, so two labels that
# differ only in these belong on the same axis.
_LABEL_STOPWORDS = {
    "bps", "bp", "basis", "point", "points", "pts", "times", "time", "or",
    "more", "less", "fewer", "higher", "lower", "above", "below", "under",
    "over", "at", "least", "most", "than", "to", "and", "between", "increase",
    "decrease", "cut", "cuts", "hike", "hikes", "up", "down", "pct", "percent",
    "k", "m", "bn", "usd", "in", "of", "the", "a", "x",
}


def _numeric_label(label: str | None) -> float | None:
    """The first number in a bucket label, signed only by a *quantity* word.

    '50+ bps decrease' -> -50, '25 bps increase' -> 25, '<-2.4%' -> -2.4,
    '↓ 80%' -> 80 (the inequality is carried separately), '≤49' -> 49.
    Used to order the rungs of a value ladder; the label is kept verbatim.
    """
    if not label:
        return None
    m = _LABEL_NUM_RE.search(label.replace(",", ""))
    if not m:
        return None
    try:
        val = float(m.group(0))
    except ValueError:
        return None
    return -abs(val) if _SIGN_NEGATIVE.search(label) else val


def _ineq_hint(label: str | None) -> int:
    """-1 for an open lower tail, +1 for an open upper tail, 0 for a closed
    bin, so '<4.0%' sorts before the '4.0-4.3%' bin that shares its number."""
    if not label:
        return 0
    if _INEQ_BELOW.search(label):
        return -1
    if _INEQ_ABOVE.search(label):
        return 1
    return 0


def _label_stem(label: str | None) -> str:
    """The subject of a value label, with numbers, units and comparators
    stripped.  'Inflation 40+ times' and 'Inflation 50+ times' share a stem and
    are one ladder; 'Tariff 13+ times' has a different stem and is another.
    '25 bps decrease' and '25 bps increase' both reduce to the empty stem, so
    a Fed-decision partition stays a single ladder across its zero."""
    if not label:
        return ""
    text = re.sub(r"[^\w\s]", " ", label.lower())
    tokens = [t for t in text.split()
              if not any(ch.isdigit() for ch in t) and t not in _LABEL_STOPWORDS]
    return " ".join(sorted(set(tokens)))


def _label_kind(label: str | None) -> str:
    """Classify a ``groupItemTitle`` as a date bucket, a value bucket, the
    residual leg, or none of those."""
    if not label:
        return "none"
    lab = label.strip().lower()
    if not lab or lab in {"yes", "no"}:
        return "none"
    if lab in _RESIDUAL_LABELS:
        return "residual"
    if _is_date_bucket(label):
        return "date"
    if _LABEL_NUM_RE.search(lab):
        return "value"
    return "none"


def _is_date_bucket(label: str | None) -> bool:
    """A ``groupItemTitle`` like 'September 24 or earlier', 'October', 'Q1
    2027', 'December 31 or later'."""
    if not label:
        return False
    lab = label.strip().lower()
    if lab in {"other", "none", "no", "yes"}:
        return False
    if _DATE_RE.search(lab):
        return True
    # A bare month or a bare month range is the commonest bucket label and
    # carries no year, so the generic date regex misses it.
    return bool(re.fullmatch(
        rf"(?:(?:early|mid|late|end of)\s+)?(?:{_MONTH_RE})\.?"
        rf"(?:\s*(?:-|–|to|or later|or earlier|or before|or after)\s*"
        rf"(?:{_MONTH_RE})?\.?)?",
        lab))


def _ref_year(row: dict) -> int | None:
    for key in ("end_date", "closed_time", "created_at"):
        v = row.get(key)
        if v:
            try:
                return int(str(v)[:4])
            except ValueError:
                continue
    return None


def detect_ladders(markets: list[dict], *, min_rungs: int = 2) -> list[dict]:
    """Group markets into ladders.  See the section header for what a ladder is
    and why each kind is separate."""
    for row in markets:
        subject, deadline, marker, numbers = parse_deadline(
            row.get("question") or "", _ref_year(row))
        row["_subject"] = subject
        row["_stated_deadline"] = deadline
        row["_deadline_marker"] = marker
        row["_other_numbers"] = numbers

    for row in markets:
        label = row.get("group_item_title")
        row["_label_kind"] = _label_kind(label)
        row["_rung_value"] = _numeric_label(label)
        row["_ineq"] = _ineq_hint(label)
        row["_label_stem"] = _label_stem(label) if row["_label_kind"] == "value" else ""

    ladders: list[dict] = []
    claimed: set[str] = set()

    # -- 1. the venue's own partition: an event whose markets are labelled
    #       by date or by value.  This is structural rather than textual, so
    #       it is the high-confidence path, and it is where most ladders are.
    by_event: dict[str, list[dict]] = defaultdict(list)
    for row in markets:
        by_event[row["event_id"]].append(row)

    for event_id, rows in by_event.items():
        neg_risk = bool(rows[0].get("event_neg_risk"))
        cumulative_flag = bool(rows[0].get("event_cumulative_markets"))
        residual = [r for r in rows if r["_label_kind"] == "residual"]

        for label_kind in ("date", "value"):
            legs = [r for r in rows if r["_label_kind"] == label_kind]
            if len(legs) < min_rungs:
                continue
            # Value labels are split by stem, because one event can carry
            # several unrelated axes ("Inflation 40+ times" and "Tariff 13+
            # times" are two ladders, not one).  Date labels are not: they are
            # already one axis by construction.
            groups: dict[str, list[dict]] = defaultdict(list)
            for r in legs:
                groups[r["_label_stem"] if label_kind == "value" else ""].append(r)
            multi = len(groups) > 1
            for stem, leg_rows in sorted(groups.items()):
                if len(leg_rows) < min_rungs:
                    continue
                distinct = {(r.get("group_item_title") or "").strip().lower()
                            for r in leg_rows}
                if len(distinct) < min_rungs:
                    continue
                if label_kind == "date":
                    # neg-risk means the legs are mutually exclusive, so each
                    # price is interval mass and the CDF is the running sum.
                    if neg_risk and not cumulative_flag:
                        kind = "exclusive_bucket"
                    else:
                        # Without neg-risk the legs either overlap, in which
                        # case the price already IS the CDF, or they are the
                        # SAME question re-asked once per day -- "Will Israel
                        # strike Lebanon ON October 29?" -- which is not a
                        # distribution over one resolution date at all.  The
                        # deadline marker separates them: a CDF rung says
                        # "by"/"before", a recurrence leg says "on".
                        marked = sum(1 for r in leg_rows if r["_deadline_marker"])
                        kind = ("cumulative"
                                if marked >= max(2, len(leg_rows) / 2)
                                else "recurrence_panel")
                else:
                    kind = "value_bucket" if neg_risk else "threshold"
                suffix = ("-" + hashlib.sha1(stem.encode()).hexdigest()[:6]) if (multi and stem) else ""
                ladders.append(_make_ladder(
                    ladder_id=f"evt-{event_id}-{label_kind}{suffix}",
                    kind=kind,
                    method=f"event_group_item_title_{label_kind}s",
                    confidence="high",
                    subject=((rows[0].get("event_title") or "") +
                             (f" [{stem}]" if (multi and stem) else "")),
                    # The residual leg belongs to whichever axis is the only
                    # one in the event; with several axes it is ambiguous, so
                    # it is left out rather than duplicated.
                    rows=leg_rows + (residual if not multi else []),
                ))
                claimed.update(r["market_id"] for r in leg_rows)
            if not multi:
                claimed.update(r["market_id"] for r in residual)

    # -- 2. cumulative "X by T" rungs, within or across events -------------
    by_subject: dict[str, list[dict]] = defaultdict(list)
    for row in markets:
        if row["market_id"] in claimed:
            continue
        if not row["_deadline_marker"] or not row["_stated_deadline"]:
            continue
        if DATE_TOKEN not in row["_subject"]:
            continue
        # The non-date numbers are part of the key: a ladder must vary in
        # exactly ONE coordinate, so rungs that differ in a strike as well as
        # a deadline are two different ladders, not one.
        by_subject[row["_subject"] + "||" + ",".join(row["_other_numbers"])].append(row)

    for group_key, rows in by_subject.items():
        subject = group_key.split("||", 1)[0]
        if len({r["_stated_deadline"] for r in rows}) < min_rungs:
            continue
        events = {r["event_id"] for r in rows}
        ladders.append(_make_ladder(
            ladder_id="cum-" + hashlib.sha1(group_key.encode()).hexdigest()[:12],
            kind="cumulative",
            method=("question_text_date_placeholder_same_event" if len(events) == 1
                    else "question_text_date_placeholder_cross_event"),
            confidence="high" if len(events) == 1 else "medium",
            subject=subject,
            rows=rows,
        ))
        claimed.update(r["market_id"] for r in rows)

    # -- 3. value-threshold ladders (the strike analogue) -------------------
    by_thresh: dict[str, list[dict]] = defaultdict(list)
    for row in markets:
        if row["market_id"] in claimed:
            continue
        q = row.get("question") or ""
        if not _THRESHOLD_MARKER.search(q) or not _NUMBER_RE.search(q):
            continue
        key = f"{row['event_id']}|{row['_subject']}"
        by_thresh[key].append(row)

    for key, rows in by_thresh.items():
        if len(rows) < min_rungs:
            continue
        if len({(r.get("question") or "").lower() for r in rows}) < min_rungs:
            continue
        ladders.append(_make_ladder(
            ladder_id="thr-" + hashlib.sha1(key.encode()).hexdigest()[:12],
            kind="threshold",
            method="question_text_number_placeholder_same_event",
            confidence="medium",
            subject=rows[0].get("event_title") or rows[0]["_subject"],
            rows=rows,
        ))
        claimed.update(r["market_id"] for r in rows)

    for lad in ladders:
        lad["n_rungs"] = len(lad["rungs"])
        _annotate_coherence(lad)
    ladders.sort(key=lambda l: (-l["n_rungs"], l["ladder_id"]))
    return ladders


def _annotate_coherence(lad: dict) -> None:
    """Flag whether the settled outcomes are coherent for the ladder's kind.

    For a ``cumulative`` ladder the settled outcomes must be monotone: once the
    event has happened by T, it has happened by any later T.  A violation means
    one of three things, and the flag does not distinguish them -- (a) the rungs
    are ROLLING windows rather than nested ones, which happens whenever the
    underlying event is not absorbing ("US bank failure by June 30" then
    "before September" are disjoint windows, so differencing is invalid);
    (b) two same-worded markets with different criteria were merged; (c) the
    venue settled inconsistently.  Treat a false flag as "do not difference
    this ladder until you have read the rungs".

    For ``exclusive_bucket`` / ``value_bucket`` the legs partition the space,
    so exactly one should settle YES.
    """
    legs = [r for r in lad["rungs"] if r.get("rung_label_kind") != "residual"]
    settled = [r["settled_outcome"] for r in legs
               if r.get("settled_outcome") in ("YES", "NO")]
    lad["n_settled_rungs"] = len(settled)
    lad["outcome_monotone"] = None
    lad["exactly_one_yes"] = None
    if lad["kind"] == "cumulative" and len(settled) >= 2:
        lad["outcome_monotone"] = not any(
            settled[i] == "YES" and settled[i + 1] == "NO"
            for i in range(len(settled) - 1))
    if lad["kind"] in ("exclusive_bucket", "value_bucket"):
        yes = sum(1 for r in lad["rungs"] if r.get("settled_outcome") == "YES")
        lad["exactly_one_yes"] = (yes == 1)
        lad["n_yes_legs"] = yes


_SLUG_TAIL = {"will", "in", "by", "before", "on", "the", "a", "of", "to", "at"}


def series_slug_candidates(event_slugs: Sequence[str]) -> list[str]:
    """Guess the ``/series?slug=`` key for a set of sibling event slugs.

    Events carry no series reference of their own, so the only way to ask the
    venue whether it links a ladder is to reconstruct the series slug from the
    shared stem of the event slugs.  ``will-china-invade-taiwan-in-2025`` and
    ``will-china-invade-taiwan-before-2027`` share the stem
    ``china-invade-taiwan``, which is the real series slug for id 10171.
    """
    if not event_slugs:
        return []
    parts = [(s or "").split("-") for s in event_slugs if s]
    if not parts:
        return []
    prefix: list[str] = []
    for tokens in zip(*parts):
        if len(set(tokens)) != 1:
            break
        prefix.append(tokens[0])
    while prefix and (prefix[-1] in _SLUG_TAIL or prefix[-1].isdigit()):
        prefix.pop()
    if not prefix:
        return []
    out: list[str] = []
    if prefix[0] in _SLUG_TAIL:
        out.append("-".join(prefix[1:]))
    out.append("-".join(prefix))
    return [c for c in dict.fromkeys(out) if c]


def check_ladders_against_series(
    reader: PolymarketReader, ladders: Sequence[dict],
    event_slugs: dict[str, str], *, sample: int = 150, log: Any = print,
) -> dict[str, Any]:
    """Probe the venue's series primitive for the cross-event ladders.

    Returns coverage: how many text-derived cross-event ladders the venue also
    links through a series, and whether the series agrees on membership.  This
    is the honest reliability statement for the cross-event rule.
    """
    cross = [l for l in ladders
             if l["detection_method"].endswith("cross_event") and len(l["event_ids"]) >= 2]
    cross.sort(key=lambda l: -l["n_rungs"])
    probed = cross[:sample]
    result = {"cross_event_ladders": len(cross), "probed": len(probed),
              "series_found": 0, "series_superset": 0, "series_exact": 0,
              "series_partial": 0, "examples": []}
    for i, lad in enumerate(probed, 1):
        slugs = [event_slugs.get(e) for e in lad["event_ids"]]
        series = None
        for cand in series_slug_candidates([s for s in slugs if s]):
            series = reader.series_by_slug(cand)
            if series:
                break
        if not series:
            continue
        result["series_found"] += 1
        series_events = {str(e.get("id")) for e in (series.get("events") or [])}
        mine = set(lad["event_ids"])
        # Record the venue's own linkage on the ladder itself, so the corpus
        # carries a series id wherever one exists -- events do not expose it.
        lad["series_id"] = str(series.get("id"))
        lad["series_slug"] = series.get("slug")
        lad["series_event_ids"] = sorted(series_events)
        if mine == series_events:
            result["series_exact"] += 1
            verdict = "exact"
        elif mine < series_events:
            result["series_superset"] += 1
            verdict = "series_has_more"
        else:
            result["series_partial"] += 1
            verdict = "disagree"
        lad["series_agreement"] = verdict
        if len(result["examples"]) < 25:
            result["examples"].append({
                "ladder_id": lad["ladder_id"], "subject": lad["subject"][:90],
                "series_slug": series.get("slug"), "series_id": series.get("id"),
                "my_events": len(mine), "series_events": len(series_events),
                "overlap": len(mine & series_events),
                "mine_only": len(mine - series_events),
                "series_only": len(series_events - mine),
                "verdict": verdict,
            })
        if i % 25 == 0:
            log(f"  series check {i}/{len(probed)}: {result['series_found']} linked")
    return result


def _make_ladder(*, ladder_id: str, kind: str, method: str, confidence: str,
                 subject: str, rows: list[dict]) -> dict:
    """Order the rungs along the axis the ladder actually runs on -- deadline
    for a date ladder, level for a value ladder -- with the residual leg last,
    so ``rungs`` can be differenced straight into interval mass."""
    value_axis = kind in ("value_bucket", "threshold")

    def sort_key(r: dict) -> tuple:
        residual = 1 if r.get("_label_kind") == "residual" else 0
        if value_axis:
            v = r.get("_rung_value")
            return (residual, 0 if v is not None else 1, v if v is not None else 0.0,
                    r.get("_ineq") or 0, r.get("group_item_title") or "",
                    r.get("market_id"))
        return (residual,
                r.get("_stated_deadline") or (r.get("end_date") or "9999")[:10],
                r.get("group_item_title") or "", r.get("market_id"))

    ordered = sorted(rows, key=sort_key)
    return {
        "ladder_id": ladder_id,
        "kind": kind,
        "detection_method": method,
        "confidence": confidence,
        "subject": subject,
        "event_ids": sorted({r["event_id"] for r in ordered}),
        "tag_slugs": sorted({t for r in ordered for t in r.get("tag_slugs", [])}),
        "rungs": [
            {
                "rung_index": i,
                "market_id": r["market_id"],
                "condition_id": r["condition_id"],
                "yes_token_id": r["yes_token_id"],
                "event_id": r["event_id"],
                "slug": r["slug"],
                "question": r["question"],
                "group_item_title": r.get("group_item_title"),
                "rung_label_kind": r.get("_label_kind"),
                "rung_value": r.get("_rung_value"),
                "rung_inequality": r.get("_ineq"),
                "stated_deadline": r.get("_stated_deadline"),
                "deadline_marker": r.get("_deadline_marker"),
                "end_date": r.get("end_date"),
                "closed_time": r.get("closed_time"),
                "settled_outcome": r.get("settled_outcome"),
                "settled_yes_price": r.get("settled_yes_price"),
                "volume_num": r.get("volume_num"),
            }
            for i, r in enumerate(ordered)
        ],
    }


# --------------------------------------------------------------------------
# Resumable stores
# --------------------------------------------------------------------------


class JsonlStore:
    """Append-only newline JSON, keyed, read back to build a resume set.

    A ``.gz`` path is appended as concatenated gzip members, which Python's
    reader handles transparently -- worth ~8x on raw Gamma event payloads,
    which run to tens of KB apiece.
    """

    def __init__(self, path: Path, key: str) -> None:
        self.path = Path(path)
        self.key = key
        self.gz = self.path.suffix == ".gz"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seen: set[str] = set()
        if self.path.exists():
            for row in self._scan():
                try:
                    self.seen.add(str(row[self.key]))
                except KeyError:
                    continue
        self._fh = self._open_append()

    def _open_read(self):
        return (gzip.open(self.path, "rt", encoding="utf-8") if self.gz
                else self.path.open("r", encoding="utf-8"))

    def _scan(self) -> Iterator[dict]:
        try:
            with self._open_read() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except (OSError, EOFError):
            return

    def _open_append(self):
        return (gzip.open(self.path, "at", encoding="utf-8") if self.gz
                else self.path.open("a", encoding="utf-8"))

    def add(self, row: dict) -> bool:
        k = str(row[self.key])
        if k in self.seen:
            return False
        self._fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.seen.add(k)
        return True

    def flush(self) -> None:
        """Leave the file fully valid on disk.

        A ``GzipFile.flush()`` only emits a sync point, with no trailer, so any
        other reader -- including a later run, or a person looking at the cache
        mid-harvest -- hits EOFError at the end.  Closing and reopening
        finalises the member instead; gzip members concatenate, so the file
        stays one readable stream.
        """
        if self.gz:
            self._fh.close()
            self._fh = self._open_append()
        else:
            self._fh.flush()

    def close(self) -> None:
        self._fh.close()

    def iter_rows(self) -> Iterator[dict]:
        self.flush()
        yield from self._scan()


def write_jsonl_gz(path: Path, rows: Iterable[dict]) -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n, path.stat().st_size


def _chunk(seq: Sequence[Any], size: int) -> Iterator[list]:
    for i in range(0, len(seq), size):
        yield list(seq[i:i + size])


# --------------------------------------------------------------------------
# Reading the corpus back
# --------------------------------------------------------------------------

MARKETS_FILE = "polymarket_markets.jsonl.gz"
EVENTS_FILE = "polymarket_events.jsonl.gz"
PRICE_PATHS_FILE = "polymarket_price_paths.jsonl.gz"
LADDERS_FILE = "polymarket_ladders.json"
MANIFEST_FILE = "polymarket_manifest.json"


def iter_corpus(name: str, data_dir: Path = DATA_DIR) -> Iterator[dict]:
    """Stream one of the ``.jsonl.gz`` corpus files.  Streaming matters: the
    price-path file is one row per token with its whole daily history inline."""
    path = Path(data_dir) / name
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def iter_markets(data_dir: Path = DATA_DIR) -> Iterator[dict]:
    return iter_corpus(MARKETS_FILE, data_dir)


def iter_events(data_dir: Path = DATA_DIR) -> Iterator[dict]:
    return iter_corpus(EVENTS_FILE, data_dir)


def iter_price_paths(data_dir: Path = DATA_DIR) -> Iterator[dict]:
    return iter_corpus(PRICE_PATHS_FILE, data_dir)


def load_ladders(data_dir: Path = DATA_DIR) -> dict:
    return json.loads((Path(data_dir) / LADDERS_FILE).read_text())


def load_manifest(data_dir: Path = DATA_DIR) -> dict:
    return json.loads((Path(data_dir) / MANIFEST_FILE).read_text())


def daily_series(points: Sequence[Sequence], *, hour: int = 0) -> list[dict]:
    """Reduce a stored path to one value per UTC day.

    The buckets land at 00:00 and 12:00 UTC even at ``fidelity=1440``, so "the
    last print of the day" is often a MIDDAY price wearing a date label, which
    lies when spliced against a daily macro series.  This takes the print
    nearest ``hour`` (00:00 by default) and carries the actual bucket timestamp
    alongside, so the reduction stays auditable.

    Lossy by nature: ``russia-x-ukraine-ceasefire-by-may-31-2026`` has a daily
    path ending at p=0.044 and settled YES, because the whole repricing
    happened inside 20 hours.  Use the raw points for event-speed questions.
    """
    best: dict[str, tuple[int, int, float]] = {}
    for pt in points:
        if not pt or pt[0] is None:
            continue
        ts = int(pt[0])
        dt = datetime.fromtimestamp(ts, timezone.utc)
        day = dt.date().isoformat()
        gap = abs(dt.hour * 3600 + dt.minute * 60 - hour * 3600)
        prev = best.get(day)
        if prev is None or gap < prev[0]:
            best[day] = (gap, ts, pt[1])
    return [{"date": d, "value": str(v), "bucket_ts": ts}
            for d, (_, ts, v) in sorted(best.items())]


# --------------------------------------------------------------------------
# The harvest
# --------------------------------------------------------------------------


def harvest(
    *,
    tags: Sequence[str] = ALL_TAGS,
    data_dir: Path = DATA_DIR,
    cache_dir: Path = CACHE_DIR,
    limit_events: int | None = None,
    skip_prices: bool = False,
    log_path: Path | None = None,
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    log_fh = log_path.open("a", encoding="utf-8") if log_path else None

    def log(msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        if log_fh:
            log_fh.write(line + "\n")
            log_fh.flush()

    reader = PolymarketReader(cache_dir=cache_dir, log=log)
    events_store = JsonlStore(cache_dir / "events.jsonl.gz", "id")
    res_store = JsonlStore(cache_dir / "resolutions.jsonl.gz", "condition_id")
    price_store = JsonlStore(cache_dir / "prices.jsonl.gz", "token_id")

    manifest: dict[str, Any] = {
        "harvested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "filter": "closed=true, political + financial/macro tag registry",
        "tags": list(tags),
    }

    try:
        # -- census ------------------------------------------------------
        log(f"=== census over {len(tags)} tags ===")
        census: dict[str, int] = {}
        for i, tag in enumerate(tags, 1):
            try:
                census[tag] = reader.count_events(tag_slug=tag, closed="true")
            except PolymarketError as exc:
                log(f"  census {tag}: FAILED {exc}")
                census[tag] = -1
            if i % 10 == 0 or i == len(tags):
                log(f"  census {i}/{len(tags)} tags, running sum={sum(v for v in census.values() if v > 0):,}")
        manifest["census_closed_events_by_tag"] = census
        manifest["census_sum_with_overlap"] = sum(v for v in census.values() if v > 0)
        log(f"  tag-sum (with overlap) = {manifest['census_sum_with_overlap']:,}")

        # -- phase A: events ----------------------------------------------
        log("=== phase A: keyset walk over closed events ===")
        event_tags: dict[str, set[str]] = defaultdict(set)
        new_events = 0
        for ti, tag in enumerate(tags, 1):
            got = 0
            try:
                for ev in reader.iter_events(tag_slug=tag, closed=True):
                    eid = str(ev.get("id"))
                    event_tags[eid].add(tag)
                    if events_store.add(ev):
                        new_events += 1
                    got += 1
                    if limit_events and len(event_tags) >= limit_events:
                        break
            except PolymarketError as exc:
                log(f"  tag {tag}: FAILED mid-walk: {exc}")
            log(f"  [{ti}/{len(tags)}] {tag}: {got:,} events  (union={len(event_tags):,}, "
                f"req={reader.stats.requests:,}, hit={reader.stats.cache_hits:,})")
            events_store.flush()
            if limit_events and len(event_tags) >= limit_events:
                log(f"  --limit-events {limit_events} reached, stopping walk")
                break

        # -- phase B: stream the raw cache once, flatten to slim rows -------
        # Raw Gamma events run to tens of KB apiece, so they are never all held
        # in memory: one streaming pass produces the slim event rows and the
        # market rows, and the raw payload is dropped.
        log("=== phase B: flatten markets (streaming) ===")
        markets: list[dict] = []
        ev_rows: list[dict] = []
        skipped_no_token = 0
        seen_events: set[str] = set()
        for ev in events_store.iter_rows():
            eid = str(ev.get("id"))
            if eid not in event_tags or eid in seen_events:
                continue
            seen_events.add(eid)
            etags = ev.get("tags") or []
            htags = sorted(event_tags[eid])
            domains = {TAG_DOMAIN[t] for t in htags if t in TAG_DOMAIN}
            ev_markets = ev.get("markets") or []
            for mk in ev_markets:
                row = market_record(ev, mk, etags, domains)
                row["harvest_tags"] = htags
                if not row["yes_token_id"]:
                    skipped_no_token += 1
                markets.append(row)
            ev_rows.append({
                "event_id": eid,
                "slug": ev.get("slug"),
                "ticker": ev.get("ticker"),
                "title": ev.get("title"),
                "description": ev.get("description"),
                "start_date": _ts(ev.get("startDate")),
                "creation_date": _ts(ev.get("creationDate")),
                "end_date": _ts(ev.get("endDate")),
                "closed_time": _ts(ev.get("closedTime")),
                "end_date_int": _date_int(_ts(ev.get("endDate"))),
                "closed_time_int": _date_int(_ts(ev.get("closedTime"))),
                "volume": _num(ev.get("volume")),
                "open_interest": _num(ev.get("openInterest")),
                "comment_count": ev.get("commentCount"),
                "neg_risk": ev.get("negRisk"),
                "neg_risk_augmented": ev.get("negRiskAugmented"),
                "cumulative_markets": ev.get("cumulativeMarkets"),
                "enable_order_book": ev.get("enableOrderBook"),
                "restricted": ev.get("restricted"),
                "n_markets": len(ev_markets),
                "tag_slugs": sorted({t.get("slug") for t in etags if t.get("slug")}),
                "harvest_tags": htags,
                "domains": sorted(domains),
            })
        n_events = len(seen_events)
        log(f"  union = {n_events:,} closed events ({new_events:,} new this run)")
        log(f"  {len(markets):,} markets across {n_events:,} events "
            f"({skipped_no_token:,} with no CLOB token id)")
        manifest["markets_without_token"] = skipped_no_token

        # -- phase C: resolutions -------------------------------------------
        log("=== phase C: authoritative outcomes via /v2/resolutions ===")
        have = res_store.seen
        need = sorted({m["event_id"] for m in markets if m["condition_id"] not in have})
        log(f"  {len(need):,} events need resolution lookup "
            f"({len(have):,} conditions already cached)")
        batches = list(_chunk(need, BATCH_CONDITIONS))
        for bi, batch in enumerate(batches, 1):
            try:
                for row in reader.resolutions(event_ids=batch):
                    if row.get("condition_id"):
                        res_store.add(row)
            except PolymarketError as exc:
                log(f"  resolutions batch {bi}: FAILED {exc}")
            if bi % 25 == 0 or bi == len(batches):
                res_store.flush()
                log(f"  resolutions {bi}/{len(batches)} batches, "
                    f"{len(res_store.seen):,} conditions, req={reader.stats.requests:,}")

        res_by_cond = {r["condition_id"]: r for r in res_store.iter_rows()}
        n_resolved = 0
        for row in markets:
            row.update(resolution_outcome(res_by_cond.get(row["condition_id"])))
            if row["settled_outcome"]:
                n_resolved += 1
        log(f"  {n_resolved:,}/{len(markets):,} markets carry a settled outcome")
        manifest["markets_with_settled_outcome"] = n_resolved

        # -- phase D: daily price paths --------------------------------------
        if skip_prices:
            log("=== phase D: SKIPPED (--skip-prices) ===")
        else:
            log(f"=== phase D: daily price paths (fidelity={DAILY_FIDELITY}, "
                f"{BATCH_TOKENS} tokens/call) ===")
            tokens = [m["yes_token_id"] for m in markets if m["yes_token_id"]]
            tokens = [t for t in dict.fromkeys(tokens) if t not in price_store.seen]
            log(f"  {len(tokens):,} YES tokens to fetch "
                f"({len(price_store.seen):,} already cached)")
            n_batches = (len(tokens) + BATCH_TOKENS - 1) // BATCH_TOKENS
            empty = 0
            bi = 0
            t0 = time.time()
            for batch, hist in reader.iter_batch_price_paths(tokens):
                bi += 1
                for tok in batch:
                    pts = hist.get(tok) or []
                    if not pts:
                        empty += 1
                    price_store.add({
                        "token_id": tok,
                        "n_points": len(pts),
                        "points": [[p.get("t"), p.get("p")] for p in pts],
                    })
                if bi % 25 == 0 or bi == n_batches:
                    price_store.flush()
                    rate = bi / max(time.time() - t0, 1e-9)
                    eta = (n_batches - bi) / max(rate, 1e-9)
                    log(f"  prices {bi}/{n_batches} batches "
                        f"({bi * BATCH_TOKENS:,} tokens, {empty:,} empty), "
                        f"{rate * BATCH_TOKENS:.0f} tok/s, ETA {eta / 60:.1f} min")
            manifest["price_tokens_empty_this_run"] = empty

        # Only a per-token summary is held in memory; the point arrays are
        # streamed straight from the cache when the corpus file is written,
        # because at this scale they are the largest object by far.
        price_store.flush()
        summary: dict[str, tuple] = {}
        for row in price_store.iter_rows():
            pts = row.get("points") or []
            summary[row["token_id"]] = (
                row.get("n_points", len(pts)),
                pts[0][0] if pts else None,
                pts[-1][0] if pts else None,
                pts[-1][1] if pts else None,
            )
        for row in markets:
            n_pts, first_ts, last_ts, last_val = summary.get(
                row["yes_token_id"] or "", (0, None, None, None))
            row["price_path_points"] = n_pts
            row["price_first_ts"] = first_ts
            row["price_last_ts"] = last_ts
            row["price_last_value"] = last_val

        # -- phase E: ladders --------------------------------------------------
        log("=== phase E: ladder detection ===")
        ladders = detect_ladders(markets)
        by_kind: dict[str, int] = defaultdict(int)
        rungs_by_kind: dict[str, int] = defaultdict(int)
        for lad in ladders:
            by_kind[lad["kind"]] += 1
            rungs_by_kind[lad["kind"]] += lad["n_rungs"]
        ladder_of: dict[str, list[str]] = defaultdict(list)
        for lad in ladders:
            for r in lad["rungs"]:
                ladder_of[r["market_id"]].append(lad["ladder_id"])
        for row in markets:
            ids = ladder_of.get(row["market_id"], [])
            row["ladder_ids"] = ids
            row["in_ladder"] = bool(ids)
        for lad in ladders:
            lad_kind = lad["kind"]
            log_line = f"  {lad_kind:18s} {lad['n_rungs']:3d} rungs  {lad['subject'][:70]}"
            if lad["n_rungs"] >= 12:
                log(log_line)
        log(f"  {len(ladders):,} ladders: " +
            ", ".join(f"{k}={v:,} ({rungs_by_kind[k]:,} rungs)" for k, v in sorted(by_kind.items())))

        # -- write -------------------------------------------------------------
        log("=== writing corpus ===")
        for row in markets:
            for k in ("_subject", "_stated_deadline", "_deadline_marker",
                      "_label_kind", "_rung_value", "_ineq", "_label_stem",
                      "_other_numbers"):
                row.pop(k, None)

        files: dict[str, Any] = {}

        n, size = write_jsonl_gz(data_dir / "polymarket_markets.jsonl.gz", markets)
        files["polymarket_markets.jsonl.gz"] = {"rows": n, "bytes": size,
                                                "grain": "one market (binary question)"}
        log(f"  polymarket_markets.jsonl.gz      {n:>8,} rows  {size / 1e6:>8.1f} MB")

        n, size = write_jsonl_gz(data_dir / "polymarket_events.jsonl.gz", ev_rows)
        files["polymarket_events.jsonl.gz"] = {"rows": n, "bytes": size, "grain": "one event"}
        log(f"  polymarket_events.jsonl.gz       {n:>8,} rows  {size / 1e6:>8.1f} MB")

        tok2m = {m["yes_token_id"]: (m["market_id"], m["condition_id"], m["event_id"])
                 for m in markets if m["yes_token_id"]}

        def path_rows() -> Iterator[dict]:
            emitted: set[str] = set()
            for p in price_store.iter_rows():
                tok = p["token_id"]
                ids = tok2m.get(tok)
                if ids is None or tok in emitted or not p.get("points"):
                    continue
                emitted.add(tok)
                market_id, condition_id, event_id = ids
                yield {
                    "token_id": tok,
                    "market_id": market_id,
                    "condition_id": condition_id,
                    "event_id": event_id,
                    "side": "YES",
                    "fidelity_minutes": DAILY_FIDELITY,
                    "n_points": p["n_points"],
                    "points": p["points"],
                }

        n, size = write_jsonl_gz(data_dir / "polymarket_price_paths.jsonl.gz", path_rows())
        files["polymarket_price_paths.jsonl.gz"] = {
            "rows": n, "bytes": size,
            "grain": "one YES token; points = [[unix_ts, price], ...] daily"}
        log(f"  polymarket_price_paths.jsonl.gz  {n:>8,} rows  {size / 1e6:>8.1f} MB")

        lad_path = data_dir / "polymarket_ladders.json"
        lad_path.write_text(json.dumps({
            "generated_at": manifest["harvested_at"],
            "axes": {
                "date": ["cumulative", "exclusive_bucket", "recurrence_panel"],
                "value": ["threshold", "value_bucket"],
            },
            "which_kinds_are_distributions": {
                "over_resolution_date": ["cumulative", "exclusive_bucket"],
                "over_value": ["threshold", "value_bucket"],
                "not_a_distribution": ["recurrence_panel"],
            },
            "kinds": {
                "cumulative": "rungs are 'X by T' and overlap; the price IS "
                              "P(resolve <= T), so the ladder is already a CDF over the "
                              "resolution date and ADJACENT DIFFERENCES are the "
                              "probability mass in each interval",
                "exclusive_bucket": "one neg-risk event partitioned into DISJOINT date "
                                    "buckets ('When will X happen?'); each price is the "
                                    "interval MASS and the CDF is the RUNNING SUM",
                "threshold": "overlapping value strikes ('will Y hit 4.3%', '4.4%', ...); "
                             "the price is P(Y >= v), a survival function over level -- "
                             "the option-strike analogue, differenced into a density",
                "value_bucket": "one neg-risk event partitioned into DISJOINT value "
                                "buckets ('GDP growth 0.7-0.9%'); each price is already "
                                "the density mass in that bin",
                "recurrence_panel": "NOT a distribution. The same question re-asked once "
                                    "per period -- 'Will Israel strike Lebanon ON October "
                                    "29?', then the 30th, then the 31st. The legs are "
                                    "independent daily binaries, so differencing them is "
                                    "meaningless; read the row as a HAZARD-RATE time "
                                    "series instead (and as a conflict-intensity series in "
                                    "its own right). Separated from cumulative by the "
                                    "absence of a by/before marker on the legs.",
            },
            "a_cdf_needs_an_absorbing_event":
                "'X by T' is a CDF over the resolution date only when X can "
                "happen at most once. For a RECURRING event the re-issues are "
                "ROLLING windows, not nested ones -- 'US bank failure by "
                "October 31 2024' settled YES while 'US bank failure before "
                "December 2024' settled NO, because the second market's window "
                "opened after the first one closed. Differencing such a row is "
                "invalid. Check `outcome_monotone` before treating any "
                "cumulative ladder as a distribution.",
            "coherence_flags":
                "`outcome_monotone` (cumulative only): the settled outcomes never "
                "go YES then NO along the deadline axis. `exactly_one_yes` "
                "(exclusive_bucket / value_bucket): the partition settled with one "
                "winning leg. `n_settled_rungs` is how many rungs the flags are "
                "based on. A false flag is a warning about the GROUPING or the "
                "event's recurrence, not necessarily about the venue.",
            "rung_order": "rungs are sorted along the ladder's own axis -- deadline for a "
                          "date ladder, signed rung_value for a value ladder -- with any "
                          "residual 'Other'/'No change' leg last, so consecutive rungs can "
                          "be differenced directly.",
            "detection": {
                "event_group_item_title_dates":
                    "markets inside one event whose groupItemTitle parses as a date. "
                    "Venue-structural, so high confidence. negRisk=true means the legs "
                    "are mutually exclusive (exclusive_bucket); negRisk=false means "
                    "overlapping 'by T' rungs (cumulative).",
                "event_group_item_title_values":
                    "same, for numeric labels. negRisk=true -> value_bucket (a density), "
                    "negRisk=false -> threshold (a survival function).",
                "question_text_date_placeholder_same_event":
                    "question text with every date replaced by <DATE> and every number "
                    "by <NUM>, grouped on the remainder, requiring a by/before/prior-to "
                    "marker in front of the date and >=2 distinct parsed deadlines. "
                    "Same event, so high confidence.",
                "question_text_date_placeholder_cross_event":
                    "same rule across events. Medium confidence: the subject string has "
                    "to match exactly, so re-wordings split a real ladder (false "
                    "negatives), and a shared boilerplate phrasing could merge two "
                    "subjects (false positives, rarer).",
                "question_text_number_placeholder_same_event":
                    "value strikes inside one event. Medium confidence.",
            },
            "n_ladders": len(ladders),
            "by_kind": dict(by_kind),
            "rungs_by_kind": dict(rungs_by_kind),
            "ladders": ladders,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        files["polymarket_ladders.json"] = {
            "ladders": len(ladders), "bytes": lad_path.stat().st_size,
            "grain": "one ladder, with ordered rungs"}
        log(f"  polymarket_ladders.json          {len(ladders):>8,} ladders  "
            f"{lad_path.stat().st_size / 1e6:>8.1f} MB")

        # -- a self-describing manifest ----------------------------------------
        outcome_counts: dict[str, int] = defaultdict(int)
        disputed = 0
        path_points = 0
        with_path = 0
        terminal_agree = terminal_disagree = 0
        for row in markets:
            outcome_counts[str(row["settled_outcome"])] += 1
            if row["was_disputed"]:
                disputed += 1
            if row["price_path_points"]:
                with_path += 1
                path_points += row["price_path_points"]
            v, o = row["price_last_value"], row["settled_outcome"]
            if v is not None and o in ("YES", "NO") and row["price_path_points"]:
                ok = (v > 0.9) if o == "YES" else (v < 0.1)
                terminal_agree += ok
                terminal_disagree += not ok

        cum = [l for l in ladders
               if l["kind"] == "cumulative" and l["outcome_monotone"] is not None]
        partitions = [l for l in ladders
                      if l["kind"] in ("exclusive_bucket", "value_bucket")
                      and l["exactly_one_yes"] is not None]

        elapsed = time.time() - started
        manifest.update({
            "elapsed_seconds": round(elapsed, 1),
            "http": reader.stats.as_dict(),
            "events": n_events,
            "markets": len(markets),
            "resolution": {
                "settled_outcome_counts": dict(outcome_counts),
                "was_disputed": disputed,
                "note": "price is 1e18-scaled and '69' is the unresolved sentinel, so "
                        "the outcome is not boolean: a UMA 'Unknown' vote settles both "
                        "tokens at 0.50 and appears here as FIFTY_FIFTY.",
            },
            "price_paths": {
                "tokens_requested": len([m for m in markets if m["yes_token_id"]]),
                "markets_with_a_path": with_path,
                "markets_with_no_stored_history": len(markets) - with_path,
                "total_daily_observations": path_points,
                "fidelity_minutes": DAILY_FIDELITY,
                "delivered_grain": "one print per day, in the 00:00 UTC hour (measured)",
                "terminal_print_agrees_with_settled_outcome": terminal_agree,
                "terminal_print_disagrees": terminal_disagree,
                "terminal_note": "The stored path does NOT reliably end at the settled "
                                 "value: the resolving move often happens inside a single "
                                 "day and the 00:00 UTC bucket misses it. Take the label "
                                 "from /v2/resolutions, never from the last price.",
            },
            "ladders": {
                "total": len(ladders), "by_kind": dict(by_kind),
                "rungs_by_kind": dict(rungs_by_kind),
                "cumulative_testable": len(cum),
                "cumulative_outcome_monotone": sum(1 for l in cum if l["outcome_monotone"]),
                "partitions_testable": len(partitions),
                "partitions_exactly_one_yes": sum(1 for l in partitions if l["exactly_one_yes"]),
            },
            "skipped_and_why": {
                "open markets": "only closed=true was harvested; a settled label is the "
                                "point of this corpus",
                "sports, crypto-price and entertainment tags": "out of scope, and crypto "
                    "dailies would swamp the corpus. Note that a tag like `multi-strikes` "
                    "means multiple STRIKE PRICES and silently drags ~1,000 Bitcoin "
                    "threshold markets into anything that trusts it, which is why the tag "
                    "set is a hand-curated registry rather than a tag walk",
                "NO-side token paths": "for a binary market NO = 1 - YES, so only the YES "
                                       "token's path is stored",
                "sub-daily price detail": f"fidelity={DAILY_FIDELITY}. Finer buckets have "
                    "7-90 day retention and cannot be backfilled for a closed corpus; "
                    "fidelity=720 would give 12-hour buckets permanently and is a "
                    "parameter change away",
                "/clob/book depth": "a closed market has no live book; depth is only "
                                    "measurable on open markets",
                "/v2/oi, /v2/holders, /v2/trades": "open interest is ~0 after settlement, "
                    "and v2 is the one rate-limited host. Event-level openInterest is kept "
                    "from Gamma",
                "the series primitive as a grouping key": "events expose no series "
                    "reference at all; it covers a minority of cross-event ladders and is "
                    "cross-checked rather than relied on. See polymarket_ladders.json "
                    "series_cross_check",
            },
            "files": files,
        })
        (data_dir / "polymarket_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"=== done in {elapsed / 60:.1f} min, "
            f"{reader.stats.requests:,} requests, {reader.stats.cache_hits:,} cache hits, "
            f"{reader.stats.bytes_down / 1e6:.0f} MB down, "
            f"{reader.stats.rate_limited} x 429 ===")
        return manifest
    finally:
        events_store.close()
        res_store.close()
        price_store.close()
        reader.close()
        if log_fh:
            log_fh.close()


# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("harvest")
    h.add_argument("--limit-events", type=int, default=None)
    h.add_argument("--skip-prices", action="store_true")
    h.add_argument("--tags", nargs="*", default=None)
    h.add_argument("--log", default=None)

    sub.add_parser("census")

    sc = sub.add_parser("series-check")
    sc.add_argument("--sample", type=int, default=150)

    args = ap.parse_args(argv)
    if args.cmd == "census":
        with PolymarketReader() as r:
            for tag in ALL_TAGS:
                print(f"{tag:26s} {r.count_events(tag_slug=tag, closed='true'):>8,}")
        return 0

    if args.cmd == "series-check":
        lad_path = DATA_DIR / "polymarket_ladders.json"
        doc = json.loads(lad_path.read_text())
        slugs: dict[str, str] = {}
        with gzip.open(DATA_DIR / "polymarket_events.jsonl.gz", "rt") as fh:
            for line in fh:
                ev = json.loads(line)
                slugs[ev["event_id"]] = ev.get("slug")
        with PolymarketReader() as r:
            res = check_ladders_against_series(
                r, doc["ladders"], slugs, sample=args.sample)
        doc["series_cross_check"] = res
        lad_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        man_path = DATA_DIR / "polymarket_manifest.json"
        if man_path.exists():
            man = json.loads(man_path.read_text())
            man["series_cross_check"] = res
            man_path.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({k: v for k, v in res.items() if k != "examples"}, indent=1))
        return 0

    harvest(
        tags=args.tags or ALL_TAGS,
        limit_events=args.limit_events,
        skip_prices=args.skip_prices,
        log_path=Path(args.log) if args.log else None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
