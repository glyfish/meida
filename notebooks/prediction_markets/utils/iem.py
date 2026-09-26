"""Iowa Electronic Markets: no API, no monitoring value, and the only multi-decade record anywhere.

IEM is a University of Iowa futures market run since 1988 under CFTC no-action
relief for research and teaching.  Three markets are open today, so it is
useless as a live signal.  What it has instead is the thing no commercial venue
publishes: **a per-day, per-contract record of share volume, dollar volume,
low, high and last price for the entire life of every market it has ever run,
going back to 1988** -- real-money political prediction markets across ten
presidential cycles.

That makes it the right place to *develop* a calibration method before pointing
it at Polymarket, where the horizon question is open and the corpus is being
built from scratch.  IEM's questions resolved long ago, the outcomes are known,
and the data is a static file rather than an API that may change.

WHAT IS ACTUALLY DOWNLOADABLE, verified 2026-09-26
--------------------------------------------------
There are **two archives with two different access routes**, and the site's own
navigation is broken in a way that hides half of one of them.

**Archive A -- 1998 to present.**  A month-at-a-time HTML table, reachable by a
plain unauthenticated GET even though the site presents it as a POST form::

    https://iemweb.biz.uiowa.edu/iem_pricehistory/pricehistory
        ?Market_ID={id}&Month={MonthName}&Year={yyyy}&Parent={parent_id}

``Month`` takes an English month **name**, not a number -- ``Month=10`` is
silently ignored and returns a default page, which is the sort of failure that
produces a wrong answer rather than an error.  `MONTHS` below has the spellings.

`build_registry` harvested the index: **57 markets, 155 market-year pairs,
spanning 2000 to 2026.**  One request per market-month means a complete pull of
the whole modern archive is 155 x 12 = **1,860 requests** -- an afternoon at
polite pacing, and a one-time cost since the data never changes.

Columns, in order, with no header row served::

    date  contract  units  dollar_volume  low  high  last

`parse_price_table` handles the markup, which is malformed: the tables carry
**unclosed ``<td>`` tags**, so the obvious ``<td>(.*?)</td>`` regex silently
merges adjacent cells into ``'DEM20_WTA573'`` instead of failing.  Split on tag
boundaries instead.

**Archive B -- 1988 to 1996.**  A static tree of fixed-width text files.  The
index at ``/historicaldata/`` lists 44 markets, and **every "Price Data" link
but one points at ``/request.cfm?MarketCode=N&RequestType=3``, a ColdFusion
handler that no longer exists -- it returns HTTP 404 behind a WordPress error
page.**  Read at face value, the 1988-1996 archive is simply gone.

It is not gone.  The files are still served at a guessable static path::

    /historicaldata/<category>/<market_dir>/<market_dir>_pricedata.txt

Probing that pattern recovers **32 of the 44 markets**; the remaining 12 have
no file under any of the four naming variants tried and appear genuinely lost.
`RECOVERY_PATTERNS` holds the variants.

.. warning::

   **The per-market format specs cannot be trusted.**  Each market directory
   ships a ``*_fileformat.txt`` describing its columns.  The 1996 Powell
   nomination spec describes **9 fields**; its data file has **16**.  Infer the
   column count from the file and use the spec only as a hint about what the
   leading columns mean.  ``-1`` marks a day with no transaction -- it is not a
   price and must never be averaged in.

WHAT A RESEARCHER CAN DO WITH IT
--------------------------------
* **Calibration at long horizons, on resolved questions, for free.**  IEM
  vote-share and winner-take-all markets ran for a year or more before
  election day.  Because every market is closed and its outcome is public
  record, a reliability curve binned by days-to-resolution can be computed
  end to end -- which is exactly the analysis that has never been published
  beyond one month for any modern venue.
* **Ladders.**  Vote-share bucket markets are strike ladders over a
  continuous outcome, so `metrics.ladder_report` applies directly and the
  ground truth is the certified vote.
* **Favourite-longshot bias across ten cycles, uncontaminated by fees.**
  Verified from the IEM FAQ: accounts open for **$5 to $500**, there is a
  **one-time $5 set-up fee, and no trading commission at all**.  So IEM is the
  only venue here where a measured longshot bias is a property of traders
  rather than of a fee schedule -- PredictIt's 10%-of-profit fee alone opens a
  **5.3-point** band at p = 0.50 and is indistinguishable from bias unless you
  model it.  Use IEM to estimate the bias, then subtract the fee wedge
  elsewhere.
* **Volume as a real variable.**  IEM publishes both share count and dollar
  volume per contract per day for the market's whole life.  Polymarket's
  volume is uncheckable and PredictIt's exists for seven days.

WHAT IT CANNOT DO
-----------------
* **No order book, ever** -- not live, not historical.  Every depth and spread
  metric in `metrics` is unavailable; only the daily low-high range survives as
  a very weak proxy.
* **No monitoring.**  Three open markets.
* **Tiny stakes, by design.**  A trading account is capped at **$500**, so IEM
  answers "are these prices well calibrated" and never "could I have traded on
  it".  That cap is also why it survived as a research market while everything
  larger drew a regulator.
* **Nothing after 2026 is guaranteed.**  This is a university project, not a
  business.

.. note::

   Read-only.  Nothing here opens an account or places an order.  Pace politely
   -- this is a university WordPress instance, not a CDN.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

__all__ = [
    "IEMError",
    "MONTHS",
    "PRICE_COLUMNS",
    "RECOVERY_PATTERNS",
    "DATA_DIR",
    "IEMMarket",
    "parse_price_table",
    "fetch_month",
    "fetch_market_history",
    "parse_legacy_file",
    "parse_1988_wide",
    "LEGACY_LAYOUT_A_COLUMNS",
    "PRICE_SCALES",
    "CONTRACTS_1988",
    "load_registry",
    "load_legacy_manifest",
]

BASE = "https://iemweb.biz.uiowa.edu"
PRICE_HISTORY = f"{BASE}/iem_pricehistory/pricehistory"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)

#: ``Month`` is matched by name, not number.  ``Month=10`` returns a default
#: page with HTTP 200 and no error, which is why this list is explicit.
MONTHS: tuple[str, ...] = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

#: Column order of the 1998-present tables.  No header row is served.
PRICE_COLUMNS: tuple[str, ...] = (
    "date", "contract", "units", "dollar_volume", "low", "high", "last",
)

#: Naming variants tried when recovering a 1988-1996 file whose ``request.cfm``
#: link is dead.  The first recovered 32 of 44; the others recovered none, and
#: are kept so the search is reproducible rather than lucky.
RECOVERY_PATTERNS: tuple[str, ...] = (
    "{name}_pricedata.txt",
    "{name}_PriceData.txt",
    "{name}.txt",
    "pricedata.txt",
)

#: In the legacy files a price of -1 means "no transaction that day".
NO_TRADE_SENTINEL = -1.0

#: **An IEM price is not always a probability, and not always on [0, 1].**
#:
#: The early markets sold *unit portfolios* at a face value above $1 and
#: liquidated each contract at that face value times the candidate's vote
#: share.  Their published prices are therefore on the portfolio's scale, and
#: the per-market format spec says so explicitly -- the 1990 Iowa Senate spec
#: reads "prices should be interpreted as **twice** the vote share."
#:
#: A calibration study that reads these files as probabilities without dividing
#: by the scale is wrong by a factor of two or two and a half on the oldest
#: data, and the error is invisible because the numbers still look plausible.
#: Divide by the scale, and remember that a **vote-share** market's settlement
#: is a continuous fraction, not a 0/1 outcome, so it is a strike ladder rather
#: than a binary event.
#:
#: Verified from each market's own ``*_fileformat.txt``.  Markets absent from
#: this mapping are winner-take-all on a $1 scale; confirm per market rather
#: than assuming.
PRICE_SCALES: dict[str, float] = {
    "1988presidential": 2.50,   # "Unit portfolios ... sold for $2.50"
    "1990iowasenate": 2.00,     # "Liquidation values were $2.00 x share of vote"
    "1990illinoissenate": 2.00,
}


class IEMError(RuntimeError):
    """A failed fetch or an unparseable IEM page."""


@dataclass(frozen=True)
class IEMMarket:
    """One market in the 1998-present archive, as the registry records it."""

    code: str
    market_id: int
    parent_id: int
    years: tuple[str, ...]
    open_date: str | None
    close_date: str | None
    description: str | None
    assets: tuple[str, ...]

    @classmethod
    def from_json(cls, row: dict[str, Any]) -> "IEMMarket":
        return cls(
            code=row["code"],
            market_id=row["market_id"],
            parent_id=row["parent_id"],
            years=tuple(row.get("years") or ()),
            open_date=row.get("open_date"),
            close_date=row.get("close_date"),
            description=row.get("description"),
            assets=tuple(row.get("assets") or ()),
        )


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------


def _get(url: str, timeout: float = 40.0, retries: int = 3) -> str:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise IEMError(f"GET {url} -> HTTP {exc.code}") from exc
        except Exception as exc:  # pragma: no cover - network
            last = exc
            time.sleep(2 * (attempt + 1))
    raise IEMError(f"GET {url} failed after {retries} attempts: {last}")


def parse_price_table(page: str) -> list[list[str]]:
    """Extract the price rows from an IEM month page.

    **The markup is malformed and this is the whole reason the function
    exists.**  Cells are opened with ``<td valign="Top">`` and closed only
    sometimes, so the natural ``<td[^>]*>(.*?)</td>`` pattern quietly merges
    neighbours -- ``DEM20_WTA`` and ``573`` come back as ``'DEM20_WTA573'``
    with no error raised.  Splitting on tag boundaries and discarding empties
    is correct against both the closed and unclosed forms.

    Returns rows of seven strings in `PRICE_COLUMNS` order, with thousands
    separators stripped so the numerics parse.
    """
    rows: list[list[str]] = []
    for tr in re.findall(r"<tr.*?</tr>", page, re.S):
        cells = [html.unescape(c).strip().replace(",", "") for c in re.split(r"<[^>]+>", tr)]
        cells = [c for c in cells if c]
        if len(cells) >= 7 and re.match(r"^\d\d/\d\d/\d\d$", cells[0]):
            rows.append(cells[:7])
    return rows


def fetch_month(
    market_id: int, parent_id: int, month: str, year: str | int, pause: float = 0.5
) -> list[list[str]]:
    """One market-month of daily prices.

    ``month`` must be an English month name from `MONTHS`.  A numeric month is
    accepted by the server, ignored, and answered with a default page -- so
    this raises rather than let that pass silently.
    """
    if month not in MONTHS:
        raise ValueError(f"month must be one of {MONTHS}, got {month!r}")
    url = (
        f"{PRICE_HISTORY}?Market_ID={int(market_id)}&Month={month}"
        f"&Year={year}&Parent={int(parent_id)}"
    )
    page = _get(url)
    time.sleep(pause)
    return parse_price_table(page)


def fetch_market_history(
    market: IEMMarket, pause: float = 0.5, progress: Any = None
) -> list[dict[str, Any]]:
    """Every month of a market's life, as typed dicts.

    Costs ``12 * len(market.years)`` requests.  Across all 57 registry markets
    that is ~1,860 requests; run it in the background and poll the log.  The
    archive is static, so this is a one-time cost.

    Rows with a ``-1`` price are days with no transaction.  They are returned
    as-is with ``no_trade=True`` rather than dropped, because the *absence* of
    trading on a given day is itself a quality measurement -- see
    ``metrics.distinct_trading_days`` and ``metrics.path_staleness``.
    """
    out: list[dict[str, Any]] = []
    for year in market.years:
        for month in MONTHS:
            for row in fetch_month(market.market_id, market.parent_id, month, year, pause):
                out.append(_typed_row(row, market.code))
            if progress:
                progress(f"{market.code} {year}-{month}: {len(out)} rows")
    return out


def _typed_row(row: Sequence[str], code: str) -> dict[str, Any]:
    def num(x: str) -> float | None:
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    mm, dd, yy = row[0].split("/")
    century = "19" if int(yy) >= 80 else "20"
    values = {k: num(v) for k, v in zip(PRICE_COLUMNS[2:], row[2:7])}
    no_trade = values.get("units") in (0.0, None) or values.get("last") == NO_TRADE_SENTINEL
    return {
        "venue": "iem",
        "market": code,
        "date": f"{century}{yy}-{mm}-{dd}",
        "contract": row[1],
        **values,
        "no_trade": bool(no_trade),
    }


# --------------------------------------------------------------------------
# the 1988-1996 legacy tree
# --------------------------------------------------------------------------


_DATE_RE = re.compile(r"^\d\d?/\d\d?/\d\d$")
_TIME_RE = re.compile(r"^\d\d?:\d\d:\d\d$")


def parse_legacy_file(text: str) -> list[dict[str, Any]]:
    """Parse a 1988-1996 price file, whichever of its layouts it uses.

    **There is no single legacy format, and the per-market specs do not
    reliably describe the one you have.**  Across the 32 recovered files this
    pass found three layouts:

    ============================================  =====  ========================
    layout                                        files  shape
    ============================================  =====  ========================
    A  whitespace, date first                     20     9 fields
    B  whitespace, date first                     5      **16** fields
    C  comma-separated, day-index first           4      9 fields, date in [1]
    D  quoted CSV, ``"EC"`` marker first          2      date in [1], tab-padded
    E  **wide: one row per day, 4 contracts**     1      1988 only -- see below
    ============================================  =====  ========================

    Layouts C and D carry a multi-line header block (address, contact, a title
    line, an "as of" line) before the data, so a parser that assumes field 0 is
    a date silently returns **nothing at all** for those files rather than
    failing -- which is how they first appeared to be empty.

    Layout E, the 1988 presidential market, is not row-per-contract at all:
    each line is one **day** carrying bid, ask, last and volume for all four
    candidates side by side.  It needs `parse_1988_wide`, and it is worth the
    special case because **it is the only file in the entire archive that
    publishes a bid and an ask** -- the one place IEM lets you measure a
    spread.

    The 1996 Powell nomination file is the format-spec counterexample: its own
    ``*_fileformat.txt`` lists **9** fields and the file has **16**.  Infer the
    width from the data.

    Returns one dict per row with ``date`` (ISO), ``contract``, and ``fields``
    holding every remaining column as a string in file order, plus ``no_trade``
    where the file's ``-1`` sentinel marks a day with no transaction.  The raw
    columns are deliberately left uninterpreted beyond the date and symbol:
    the widths differ, the specs are unreliable, and guessing which of 16
    columns is "last price" is how a corpus acquires silent errors.
    """
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        raw = [p.strip().strip('"').strip() for p in (line.split(",") if "," in line else line.split())]
        raw = [p for p in raw if p]
        if not raw:
            continue
        # Layout A/B put the date first; C and D put an index or a literal
        # marker first, so look at the first two fields for a date.
        if _DATE_RE.match(raw[0]):
            didx = 0
        elif len(raw) > 1 and _DATE_RE.match(raw[1]):
            didx = 1
        else:
            continue
        mm, dd, yy = raw[didx].split("/")
        century = "19" if int(yy) >= 80 else "20"
        rest = raw[didx + 1 :]
        # Layout D interposes a clock time between the date and the security
        # id, so the field after the date is not the contract. Left in place,
        # every 1990 row comes back with a contract of "23:59:59".
        if rest and _TIME_RE.match(rest[0]):
            rest = rest[1:]
        rows.append(
            {
                "venue": "iem",
                "date": f"{century}{yy}-{int(mm):02d}-{int(dd):02d}",
                "contract": rest[0] if rest else None,
                "fields": rest[1:],
                "n_fields": len(raw),
                "no_trade": any(f.startswith("-1") for f in rest[1:]),
            }
        )
    return [_name_layout_a(r) for r in rows]


#: Column names for the dominant legacy layout, taken **verbatim** from a spec
#: this pass actually read -- ``1996uspresidential_wta_fileformat.txt``, which
#: lists exactly nine fields in this order.  Applied only to 9-field,
#: date-first rows, because that is the only combination the read spec covers.
#:
#: The 16-field files are deliberately **not** named.  Their own specs claim
#: nine fields, so the extra seven are undocumented and guessing at them is how
#: a calibration corpus acquires a silent error.  Same for the comma-separated
#: layouts, whose field order differs again.
LEGACY_LAYOUT_A_COLUMNS: tuple[str, ...] = (
    "contract_num", "symbol", "n_trades", "n_shares",
    "dollar_volume", "low", "high", "last",
)


def _name_layout_a(row: dict[str, Any]) -> dict[str, Any]:
    """Attach named columns to a 9-field, date-first legacy row.

    Leaves every other layout untouched, so a caller can tell a row whose
    columns are known from one whose columns merely exist.  ``-1`` is mapped to
    ``None``: it is the archive's no-transaction sentinel, not a price, and
    letting it through as a number is how a mean price ends up negative.
    """
    if row.get("n_fields") != 9 or row.get("contract") is None:
        return row
    raw = [row["contract"], *row.get("fields", ())]
    if len(raw) != len(LEGACY_LAYOUT_A_COLUMNS):
        return row
    named: dict[str, Any] = {"layout": "A", "columns_known": True}
    for key, tok in zip(LEGACY_LAYOUT_A_COLUMNS, raw):
        if key in {"contract_num", "symbol"}:
            named[key] = tok
            continue
        try:
            val = float(tok)
        except (TypeError, ValueError):
            val = None
        named[key] = None if (val is not None and val <= NO_TRADE_SENTINEL) else val
    row = {**row, **named}
    # The symbol is the human-readable contract; the bare number is not.
    row["contract"] = named.get("symbol") or row["contract"]
    row["no_trade"] = not named.get("n_trades")
    return row


#: Candidate order of the 1988 wide file's column groups, from its own spec.
CONTRACTS_1988: tuple[str, ...] = ("RoF", "Bush", "Dukakis", "Jackson")


def parse_1988_wide(text: str, year: int = 1988) -> list[dict[str, Any]]:
    """Parse the 1988 presidential file -- the archive's only quoted market.

    Layout E: ``month day`` followed by four groups of ``bid ask last volume``,
    one group per candidate in `CONTRACTS_1988` order (Rest of Field, Bush,
    Dukakis, Jackson), per its own ``*_fileformat.txt``.

    Two things make this file worth a bespoke reader:

    * **It is the only IEM file with a bid and an ask.**  Everywhere else the
      archive publishes low, high and last, so a spread cannot be computed at
      all.  Here it can, which makes 1988 the only IEM market that supports
      ``metrics.absolute_spread`` and ``metrics.relative_spread``.
    * **Its prices are on a $2.50 scale**, because unit portfolios sold for
      $2.50 and each contract liquidated at $2.50 times the candidate's vote
      share.  The integers in the file are cents on that scale -- ``113`` is
      $1.13, which is a 45% vote share, not a 113% probability.  `PRICE_SCALES`
      carries the divisor; this function applies it and returns vote shares.

    A ``.`` in a price column means no quote.  Returns one row per
    candidate-day so the output joins to everything else.
    """
    scale = PRICE_SCALES.get("1988presidential", 2.50)
    rows: list[dict[str, Any]] = []

    def num(tok: str) -> float | None:
        if tok in {".", "-", ""}:
            return None
        try:
            return float(tok)
        except ValueError:
            return None

    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2 + 4 * len(CONTRACTS_1988):
            continue
        if not (parts[0].isdigit() and parts[1].isdigit()):
            continue
        month, day = int(parts[0]), int(parts[1])
        for i, name in enumerate(CONTRACTS_1988):
            bid, ask, last, vol = parts[2 + 4 * i : 6 + 4 * i]
            b, a, l, v = num(bid), num(ask), num(last), num(vol)
            rows.append(
                {
                    "venue": "iem",
                    "market": "1988presidential",
                    "date": f"{year}-{month:02d}-{day:02d}",
                    "contract": name,
                    # Published integers are cents on the $2.50 portfolio
                    # scale; dividing by the scale yields an implied vote share.
                    "bid": (b / 100.0 / scale) if b is not None else None,
                    "ask": (a / 100.0 / scale) if a is not None else None,
                    "last": (l / 100.0 / scale) if l is not None else None,
                    "volume": v,
                    "price_scale": scale,
                    "settles_on": "vote_share",
                    "no_trade": not v,
                }
            )
    return rows


# --------------------------------------------------------------------------
# corpus files
# --------------------------------------------------------------------------


def load_registry(directory: Path | None = None) -> list[IEMMarket]:
    """The 57-market registry written to ``data/iem_market_registry.json``."""
    directory = directory or DATA_DIR
    path = directory / "iem_market_registry.json"
    if not path.exists():
        raise IEMError(f"registry not built; expected {path}")
    return [IEMMarket.from_json(r) for r in json.loads(path.read_text())]


def load_legacy_manifest(directory: Path | None = None) -> list[dict[str, Any]]:
    """What was and was not recovered from the broken 1988-1996 index.

    Entries with ``path is None`` carry a note explaining that the
    ``request.cfm`` handler is dead and no static file was found -- those
    markets' price data appears genuinely lost, not merely unlinked.
    """
    directory = directory or DATA_DIR
    path = directory / "iem_1988_1996_manifest.json"
    if not path.exists():
        raise IEMError(f"manifest not built; expected {path}")
    return json.loads(path.read_text())
