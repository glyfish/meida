"""Harvest the closed Economics / Financials / Politics / Elections universe.

Two phases, each resumable, each writing JSONL under ``../data/``:

  meta    series catalogue + every settled market in the four target
          categories, across both the live and historical tiers.
  paths   daily candlestick paths for a selected subset, plus the quality
          metrics computed over them.

Run:  python -m utils.kalshi_harvest meta
      python -m utils.kalshi_harvest paths
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime

from . import kalshi as K

DATA = K.DATA_DIR
DATA.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    print(f"[{datetime.now(UTC):%H:%M:%S}] {msg}", flush=True)


# --------------------------------------------------------------------------


def phase_meta() -> None:
    r = K.Reader(pace=0.22, log=log)
    cut = r.cutoff()
    log(f"cutoff {cut['_raw']}")

    log("fetching full series catalogue ...")
    allser = r.series_list()
    log(f"  {len(allser)} series total")

    rows = []
    for s in allser:
        cls = K.classify_settlement(s.get("settlement_sources"))
        rows.append({
            "ticker": s.get("ticker"),
            "title": s.get("title"),
            "category": s.get("category"),
            "categories": s.get("categories"),
            "tags": s.get("tags"),
            "frequency": s.get("frequency"),
            "fee_type": s.get("fee_type"),
            "fee_multiplier": s.get("fee_multiplier"),
            "contract_terms_url": s.get("contract_terms_url"),
            "contract_url": s.get("contract_url"),
            "additional_prohibitions": s.get("additional_prohibitions"),
            **cls,
        })
    K.write_jsonl(rows, "kalshi_series.jsonl")
    log(f"  wrote kalshi_series.jsonl ({len(rows)})")

    targets = [s for s in rows if s["category"] in K.TARGET_CATEGORIES]
    log(f"  {len(targets)} series in {K.TARGET_CATEGORIES}")

    out = DATA / "kalshi_markets.jsonl"
    done_file = DATA / ".kalshi_markets_done"
    done = set()
    if done_file.exists() and out.exists():
        done = set(done_file.read_text().split())
        log(f"  resuming: {len(done)} series already harvested")
    fh = out.open("a" if done else "w")
    dfh = done_file.open("a" if done else "w")

    # A per-series cap, because a handful of series are repricing instruments
    # rather than forecast questions and they dominate everything. KXEURUSDH
    # (hourly EUR/USD strike ladders) alone produced 180,898 of the first
    # 226,388 rows -- 80% of the corpus from one series. Capping bounds the pull
    # and keeps the corpus about questions; capped series are logged by name so
    # the truncation is never silent.
    SERIES_CAP = 1500
    capped = []

    t0 = time.time()
    n_markets = 0
    for i, s in enumerate(targets, 1):
        st = s["ticker"]
        if st in done:
            continue
        try:
            got = 0
            for m in r.markets(series_ticker=st, cap=SERIES_CAP):
                m["category"] = s["category"]
                m["series_title"] = s["title"]
                fh.write(json.dumps(m, default=str) + "\n")
                got += 1
            n_markets += got
            if got >= SERIES_CAP:
                capped.append(st)
                log(f"  ~~ {st} hit the {SERIES_CAP} cap (high-frequency series)")
        except K.KalshiAPIError as e:
            log(f"  !! {st}: {e}")
            continue
        dfh.write(st + "\n")
        if i % 100 == 0:
            fh.flush(); dfh.flush()
            el = time.time() - t0
            log(f"  {i}/{len(targets)} series, {n_markets} markets, "
                f"{r.n_requests} reqs, {r.n_429} 429s, {el/60:.1f} min, "
                f"eta {(el/i)*(len(targets)-i)/60:.0f} min")
    fh.close(); dfh.close()
    if capped:
        (DATA / "kalshi_capped_series.json").write_text(json.dumps(capped, indent=1))
        log(f"  {len(capped)} series hit the cap: {capped}")
    log(f"DONE meta: {n_markets} markets, {r.n_requests} requests, {r.n_429} 429s")


# --------------------------------------------------------------------------

# Series that reprice every few minutes are a different animal: they are
# microstructure, not forecasts, and they would swamp the corpus. Excluded from
# the price-path pull by ticker suffix.
INTRADAY = ("15M", "1H", "HOURLY", "MINUTE", "5M", "30M")


def _is_intraday(series_ticker: str) -> bool:
    return any(series_ticker.upper().endswith(sfx) for sfx in INTRADAY)


def phase_paths(max_markets: int = 6000, min_volume: float = 1000.0) -> None:
    r = K.Reader(pace=0.22, log=log)
    r.cutoff()

    log("loading markets ...")
    mkts = K.read_jsonl("kalshi_markets.jsonl")
    log(f"  {len(mkts)} market rows")

    settled = [m for m in mkts if m.get("result") in ("yes", "no")]
    log(f"  {len(settled)} settled")

    elig = [m for m in settled
            if (m.get("volume") or 0) >= min_volume
            and not _is_intraday(m.get("series_ticker") or "")]

    def life(m):
        o, c = K.parse_ts(m.get("open_time")), K.parse_ts(m.get("close_time"))
        return (c - o) / 86400.0 if o and c else 0.0

    # Stratify rather than take the top of one ranking. Ranking on volume alone
    # would fill the corpus with short-fuse markets, and the whole point of
    # building this is the horizon beyond one month, where no published
    # calibration evidence exists. Half the budget goes to the most-traded
    # markets, half to the longest-lived ones that still clear the volume floor.
    half = max_markets // 2
    by_vol = sorted(elig, key=lambda m: -(m.get("volume") or 0))[:half]
    taken = {m["ticker"] for m in by_vol}
    by_life = [m for m in sorted(elig, key=lambda m: -life(m))
               if m["ticker"] not in taken][:max_markets - half]
    pool = by_vol + by_life
    lives = sorted(life(m) for m in pool)
    log(f"  {len(pool)} selected for price paths "
        f"({len(by_vol)} by volume + {len(by_life)} by life; "
        f"volume >= {min_volume:g}, non-intraday)")
    log(f"  life days: median {lives[len(lives)//2]:.0f}, "
        f"p90 {lives[int(len(lives)*0.9)]:.0f}, max {lives[-1]:.0f}")

    cand_out = (DATA / "kalshi_candles.jsonl").open("a")
    qual_out = (DATA / "kalshi_quality.jsonl").open("a")
    done_file = DATA / ".kalshi_paths_done"
    done = set(done_file.read_text().split()) if done_file.exists() else set()
    if done:
        log(f"  resuming: {len(done)} paths already pulled")
    dfh = done_file.open("a")

    t0 = time.time()
    n_ok = n_empty = 0
    for i, m in enumerate(pool, 1):
        t = m["ticker"]
        if t in done:
            continue
        try:
            cs = r.candles(m, period=1440)
        except K.KalshiAPIError as e:
            log(f"  !! {t}: {e}")
            continue
        if cs:
            n_ok += 1
            cand_out.write(json.dumps({
                "ticker": t, "event_ticker": m.get("event_ticker"),
                "series_ticker": m.get("series_ticker"),
                "category": m.get("category"), "tier": m.get("tier"),
                "result": m.get("result"), "settled": K.outcome(m),
                "close_time": m.get("close_time"),
                "candles": [{k: c[k] for k in
                             ("date", "ts", "mean", "close", "yes_bid",
                              "yes_ask", "mid", "volume", "open_interest",
                              "traded")} for c in cs],
            }, default=str) + "\n")
        else:
            n_empty += 1
        q = K.market_quality(m, cs)
        q["category"] = m.get("category")
        q["series_ticker"] = m.get("series_ticker")
        q["event_ticker"] = m.get("event_ticker")
        q["tier"] = m.get("tier")
        q["close_time"] = m.get("close_time")
        q["expiration_value"] = m.get("expiration_value")
        qual_out.write(json.dumps(q, default=str) + "\n")
        dfh.write(t + "\n")
        if i % 100 == 0:
            cand_out.flush(); qual_out.flush(); dfh.flush()
            el = time.time() - t0
            log(f"  {i}/{len(pool)} paths ({n_ok} with data, {n_empty} empty), "
                f"{r.n_requests} reqs, {r.n_429} 429s, {el/60:.1f} min, "
                f"eta {(el/i)*(len(pool)-i)/60:.0f} min")
    cand_out.close(); qual_out.close(); dfh.close()
    log(f"DONE paths: {n_ok} with data, {n_empty} empty, "
        f"{r.n_requests} requests, {r.n_429} 429s")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "meta"
    if cmd == "meta":
        phase_meta()
    elif cmd == "paths":
        kw = {}
        if len(sys.argv) > 2:
            kw["max_markets"] = int(sys.argv[2])
        if len(sys.argv) > 3:
            kw["min_volume"] = float(sys.argv[3])
        phase_paths(**kw)
    else:
        raise SystemExit(f"unknown phase {cmd}")
