"""Helpers for exploring BLS data through the MCP server.

Mirrors notebooks/fred/utils.py: thin wrappers over the MCP tools plus a couple
of discovery routines that persist survey/series metadata to YAML. The MCP
server must be running (see the project README).
"""

import sys as _sys
from pathlib import Path as _Path

# meida's repo root, so `clients` resolves. The clients package used to live in
# navi (installed, hence importable from anywhere); it now sits beside
# mcp_server, which the notebooks' cwd does not reach. Anchored to __file__
# rather than "../.." so it holds whatever directory the kernel started in.
_sys.path.append(str(_Path(__file__).resolve().parents[2]))

from typing import Any
from datetime import date, datetime
from pathlib import Path
import asyncio
import os
import random
import re
import time

import numpy
from curl_cffi import CurlError
from curl_cffi import requests as curl_requests
from curl_cffi.requests import AsyncSession
import yaml

from lib.mcp_client import MCPClient, MCPClientConfig
from lib.utils import print_json_vertical
from environment import get_mcp_url
from clients.models.bls import (
    BlsBaseResponse,
    BlsSeriesResponse,
    BlsSurveysResponse,
    Observation,
    Series,
    Survey,
)

MCP_URL = get_mcp_url()
config = MCPClientConfig(url=MCP_URL)


async def call_tool(tool_name: str, arguments: dict[str, Any] | None = None):
    async with MCPClient(config) as client:
        return await client.call_tool(tool_name, arguments or {})


async def list_mcp_tools(prefix: str | tuple[str, ...] | None = None) -> None:
    """Print the server's tools, optionally only those whose name starts with ``prefix``.

    Print-only: the notebooks call this as a bare expression, so returning a
    value would echo the list underneath the printed output. ``prefix`` accepts
    a tuple because a source's tools are not always one family -- FRED's
    ``list_releases`` predates the naming convention, and CDC spans ``cdc_``,
    ``timeseries_source_`` and ``series_catalog_``.
    """
    prefixes = (prefix,) if isinstance(prefix, str) else prefix
    async with MCPClient(config) as client:
        for tool in await client.list_tools():
            if prefixes and not tool.name.startswith(tuple(prefixes)):
                continue
            print(f"{tool.name}: {tool.description}")


def _schema_type(spec: dict[str, Any]) -> str:
    """Render a JSON-schema property as a short Python-ish type name."""
    options = spec.get("anyOf")
    if options:
        named = [_schema_type(o) for o in options if o.get("type") != "null"]
        return " | ".join(named) + " | None"
    kind = spec.get("type", "any")
    if kind == "array":
        return f"list[{_schema_type(spec.get('items', {}))}]"
    return {"integer": "int", "number": "float", "string": "str",
            "boolean": "bool", "object": "dict"}.get(kind, str(kind))


async def show_tool_schema(tool_name: str) -> dict[str, Any]:
    """Print one tool's arguments -- name, type, and required-or-default."""
    async with MCPClient(config) as client:
        schema = dict(await client.get_tool_schema(tool_name) or {})
    required = set(schema.get("required", []))
    print(f"{tool_name}(")
    for name, spec in (schema.get("properties") or {}).items():
        default = "required" if name in required else f"default={spec.get('default')!r}"
        print(f"    {name:<14} {_schema_type(spec):<20} {default}")
    print(")")
    return schema


async def show_all_surveys(match: str | None = None) -> list[dict[str, Any]]:
    """Print and return BLS surveys (abbreviation + name).

    BLS publishes ~70 survey programs, so ``match`` filters to the ones whose
    name or abbreviation contains it (case-insensitive) rather than printing
    the whole catalog.
    """
    result = await call_tool("bls_all_surveys")
    surveys = result.structuredContent["surveys"]  # type: ignore
    if match:
        needle = match.lower()
        hits = [s for s in surveys
                if needle in s["survey_name"].lower()
                or needle in s["survey_abbreviation"].lower()]
        print(f"{len(hits)} of {len(surveys)} surveys match {match!r}\n")
        surveys = hits
    for survey in surveys:
        print(f"{survey['survey_abbreviation']}: {survey['survey_name']}")
    return surveys


def show_notices(payload: dict[str, Any]) -> list[str]:
    """Print the advisories BLS attached to a SUCCESSFUL response.

    ``notices`` is the only place a silently trimmed result shows up: BLS still
    answers 200 with data, and only the notice says the data is not what was
    asked for. Worth printing after every fetch.
    """
    notices = list(payload.get("notices") or [])
    if not notices:
        print("no notices: BLS answered the request as asked")
    for notice in notices:
        print(f"notice: {notice}")
    return notices


def show_series_catalog(payload: dict[str, Any]) -> dict[str, str]:
    """Print ``series_id  title  [units]`` for a ``catalog=True`` fetch.

    Returns the id -> title mapping, which is what turns a list of opaque BLS
    ids into something a caller can choose from.
    """
    titles: dict[str, str] = {}
    for series in payload.get("series", []):
        catalog = series.get("catalog") or {}
        title = catalog.get("series_title") or "(no catalog metadata)"
        units = catalog.get("measure_data_type") or ""
        titles[series["series_id"]] = title
        print(f"{series['series_id']}  {title}" + (f"  [{units}]" if units else ""))
    return titles


def show_observations(series: dict[str, Any], count: int = 6,
                      on_date: str | None = None) -> None:
    """Print observations as ``date  period  period_type  value``.

    ``on_date`` keeps only the rows carrying that ISO date -- the way to see
    the annual-average row (M13/Q05/S03) sitting on the same date as the year's
    first period.
    """
    rows = series.get("observations", [])
    if on_date:
        rows = [row for row in rows if row.get("date") == on_date]
    for row in rows[:count]:
        print(f"{row.get('date')}  {row.get('period'):<4} "
              f"{row.get('period_type'):<15} {row.get('value')}")


def filter_observations(series: dict[str, Any],
                        period_type: str = "monthly") -> dict[str, Any]:
    """Return a copy of ``series`` holding only rows of one ``period_type``.

    Requested with ``annualaverage=True``, a series interleaves aggregate rows
    (M13/Q05/S03) dated to the same day as the year's first period, so plotting
    the raw list draws two points on one x. ``period_type`` is the only field
    that separates them.
    """
    rows = [row for row in series.get("observations", [])
            if row.get("period_type") == period_type]
    return {**series, "observations": rows}


def observation_span(series: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return the (earliest, latest) ISO date in a series.

    BLS returns observations newest-first, and a truncated response looks
    exactly like a complete one, so the span is what shows which years actually
    came back.
    """
    dates = sorted(row["date"] for row in series.get("observations", []) if row.get("date"))
    return (dates[0], dates[-1]) if dates else (None, None)


async def popular_series(survey: str | None = None) -> list[str]:
    """Return the popular series IDs overall, or for a single survey."""
    args = {"survey": survey} if survey else {}
    result = await call_tool("bls_popular_series", args)
    if not result or not result.structuredContent or "series" not in result.structuredContent:
        print(f"No result for survey {survey}")
        return []
    series = result.structuredContent["series"]  # type: ignore
    return [s["series_id"] for s in series]


# --- BLS flat-file metadata export -------------------------------------------
#
# The BLS API cannot enumerate series (only 25 "popular" per survey), and it
# exposes neither coverage dates nor index bases. All of that lives in the flat
# files at download.bls.gov, which are the source of truth for this export.
#
# Pipeline:  fetch_bls_source_files()  ->  /tmp/bls_source/<survey>/
#            write_survey_yaml()       ->  data/survey.yaml
#            write_all_series_yaml()   ->  data/bls_series_<CODE>.yaml

BLS_DOWNLOAD_BASE = "https://download.bls.gov/pub/time.series"

# download.bls.gov blocks non-browser TLS fingerprints -- plain httpx/curl get a
# 403 "Access Denied" (same page it serves for rate-limiting, so the two are
# indistinguishable). curl_cffi impersonating a browser presents a matching
# fingerprint and passes. Still be gentle: this host rate-limits bulk access.
BLS_IMPERSONATE = "chrome"

BLS_SOURCE_DIR = Path("/tmp/bls_source")
BLS_DATA_DIR = Path("data")

# Economic core: injury/illness, retired, and the giant occupation x geography
# cross-product surveys (OE, NW, WM, CX, EP) are excluded. ~271k series.
CORE_SURVEYS = [
    "AP", "CU", "CW", "SU", "EI", "WP", "PC", "ND",          # prices
    "LN", "LA", "CE", "SM", "JT", "BD", "CI", "FM",          # employment
    "LE", "CM", "LU",                                        # wages
    "PR", "MP", "IP",                                        # productivity
]

# Lookups we never need: huge (.aspect can be 30MB+), or redundant because we
# derive dates ourselves (.period), or map-related (.areamaps, .map_info).
_SKIP_LOOKUPS = {"aspect", "footnote", "period", "areamaps", "map_info", "contacts", "txt"}

# Columns that carry units, in priority order. Decoded via the matching lookup.
# OE's ``datatype_code`` is the measure (employment count vs. mean/median wage),
# i.e. the series' units -- decoded via oe.datatype.
_UNITS_COLUMNS = ("tdat_code", "tdata_code", "data_type_code", "datatype_code",
                  "measure_code", "ratelevel_code")

# Surveys with neither a units column nor an index base: units are implicit in
# the survey itself (AP is average prices in dollars, per the item name).
_UNITS_FALLBACK = {"AP": "Dollars"}

# Columns that are never facets (they are promoted to top-level fields).
_NON_FACET = {"series_id", "series_title", "series_name", "seasonal", "periodicity_code",
              "footnote_codes", "begin_year", "begin_period", "end_year", "end_period",
              "base_code", "base_period", "base_date", "benchmark_year", "srd_code"}

_PERIOD_MONTH = {"M": lambda i: i, "Q": lambda i: 3 * i - 2, "S": lambda i: 6 * i - 5}


def _period_to_month(period: str) -> int:
    """Map a BLS period code (M06, Q02, A01, S02) to a starting month."""
    fn = _PERIOD_MONTH.get(period[:1])
    if fn is None:
        return 1
    try:
        month = fn(int(period[1:]))
    except ValueError:
        return 1
    return month if 1 <= month <= 12 else 1


def _iso_and_int(year: str, period: str) -> tuple[str, int]:
    """Return ('YYYY-MM-01', YYYYMM01) for a BLS year + period pair."""
    y = int(year)
    m = _period_to_month(period)
    return f"{y:04d}-{m:02d}-01", y * 10000 + m * 100 + 1


async def _bls_get(
    session: AsyncSession,
    url: str,
    delay: float = 1.0,
    max_attempts: int = 4,
):
    """GET a BLS file, pausing between calls and backing off on throttling.

    download.bls.gov rate-limits bulk access and answers with the *same* 403
    "Access Denied" page it uses for a blocked fingerprint, so a 403 is
    ambiguous: it may mean "not a browser" or "slow down". The session already
    impersonates a browser; a lingering 403 means throttling, so we retry with
    growing delays and give up after ``max_attempts``.
    """
    for attempt in range(1, max_attempts + 1):
        # Jittered pause so the cadence isn't a fixed metronome (looks human,
        # and stays gentle on a host that rate-limits bulk access).
        await asyncio.sleep(random.uniform(delay, delay * 1.8))
        try:
            response = await session.get(url)
        except CurlError:
            response = None
        if response is not None and response.status_code == 200:
            return response
        # 404 is permanent (the file genuinely doesn't exist, e.g. ce has no
        # data_type lookup) -- don't burn escalating backoff retrying it.
        if response is not None and response.status_code == 404:
            return None
        if attempt < max_attempts:
            backoff = delay * (4 ** attempt)
            status = response.status_code if response is not None else "transport error"
            print(f"    {status} on {url.rsplit('/', 1)[-1]} — waiting {backoff:.0f}s")
            await asyncio.sleep(backoff)
    return None


def _read_tsv(path: Path) -> tuple[list[str], list[list[str]]]:
    """Read a BLS tab-delimited file into (header, rows) with values stripped."""
    with open(path, encoding="utf-8", errors="ignore") as fh:
        lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    if not lines:
        return [], []
    header = [h.strip() for h in lines[0].split("\t")]
    rows = [[c.strip() for c in ln.split("\t")] for ln in lines[1:]]
    return header, rows


def _needed_lookups(header: list[str]) -> set[str]:
    """Lookup file suffixes implied by a .series header (e.g. area_code -> area)."""
    names = {c[:-5] for c in header if c.endswith("_code")}
    if "seasonal" in header:
        names.add("seasonal")
    return {n for n in names if n and n not in _SKIP_LOOKUPS}


async def fetch_bls_source_files(
    surveys: list[str] | None = None,
    dest: Path | str = BLS_SOURCE_DIR,
    force: bool = False,
    delay: float = 1.0,
) -> dict[str, Any]:
    """Download the .series file and needed lookups for each survey into ``dest``.

    Only fetches what the export needs: the series catalog plus the lookup
    tables its ``*_code`` columns reference. Skips the multi-hundred-MB
    ``.data.*`` observation files (observations come from the API) and the
    oversized ``.aspect`` lookups. Missing lookups are recorded, not fatal --
    ``ce``/``sm`` genuinely have no ``data_type`` file.

    Returns a manifest of what was fetched, including BLS's own mtime/size per
    file so a later run can tell whether the source actually changed.
    """
    surveys = [s.upper() for s in (surveys or CORE_SURVEYS)]
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {}

    async with AsyncSession(impersonate=BLS_IMPERSONATE, timeout=120.0) as client:
        # Survey names live only in the top-level overview.txt, not per-survey;
        # write_survey_yaml needs it, so always ensure it's present.
        if not (dest / "overview.txt").exists():
            ov = await _bls_get(client, f"{BLS_DOWNLOAD_BASE}/overview.txt", delay)
            if ov is not None:
                (dest / "overview.txt").write_text(ov.text, encoding="utf-8")

        for code in surveys:
            s = code.lower()
            out_dir = dest / s
            out_dir.mkdir(parents=True, exist_ok=True)

            listing_response = await _bls_get(client, f"{BLS_DOWNLOAD_BASE}/{s}/", delay)
            if listing_response is None:
                print(f"  {code}: blocked fetching directory listing (throttled?) — skipped")
                continue
            listing = listing_response.text
            stamps = {
                name: {"bytes": int(size), "mtime": f"{d} {t} {ampm}"}
                for d, t, ampm, size, name in re.findall(
                    rf'([\d/]+)\s+([\d:]+)\s+(AM|PM)\s+(\d+) <A HREF="/pub/time\.series/{s}/([^"]+)"',
                    listing,
                )
            }

            async def grab(filename: str, _dir: Path = out_dir, _s: str = s) -> bool:
                target = _dir / filename
                if target.exists() and not force:
                    return True  # already cached; re-run with force=True to refresh
                r = await _bls_get(client, f"{BLS_DOWNLOAD_BASE}/{_s}/{filename}", delay)
                if r is None:
                    return False
                target.write_text(r.text, encoding="utf-8")
                return True

            if not await grab(f"{s}.series"):
                print(f"  {code}: FAILED to fetch {s}.series")
                continue

            header, _ = _read_tsv(out_dir / f"{s}.series")
            wanted = _needed_lookups(header)
            got, missing = [], []
            for name in sorted(wanted):
                (got if await grab(f"{s}.{name}") else missing).append(name)

            manifest[code] = {
                "dir": str(out_dir),
                "series_file": f"{s}.series",
                "lookups": got,
                "missing_lookups": missing,
                "source_mtime": stamps.get(f"{s}.series", {}).get("mtime"),
                "source_bytes": stamps.get(f"{s}.series", {}).get("bytes"),
                "columns": header,
            }
            note = f" (missing: {', '.join(missing)})" if missing else ""
            print(f"  {code}: {len(got)} lookups{note}")

    return manifest


def _load_lookups(survey: str, source_dir: Path, series_columns: list[str]) -> dict[str, dict[str, Any]]:
    """Load lookup tables as {name: {"key_cols": [...], "table": {tuple: label}}}.

    Lookup files come in three shapes and a naive col0->col1 map is wrong for two
    of them:

    * simple ``code, text`` (e.g. ``ln.race``) -- keyed by its one code column;
    * extra attribute columns (e.g. ``ce.industry`` = industry_code, naics_code,
      ..., industry_name) -- the label is the ``*_name``/``*_text`` column, not
      col 1;
    * compound key (e.g. ``wp.item`` = group_code, item_code, item_name) where
      ``item_code`` is not unique -- keyed by *(group_code, item_code)*.

    Key columns are the lookup's ``*_code`` columns that also appear in the
    ``.series`` (so we can rebuild the key from a series row); ``ce.industry``
    keeps only ``industry_code`` because ``naics_code`` isn't a series column,
    while ``wp.item`` keeps both. Falls back to the first column when no
    ``*_code`` matches (the ``seasonal`` lookup, whose code the series stores in a
    column literally named ``seasonal``).
    """
    s = survey.lower()
    series_cols = set(series_columns)
    lookups: dict[str, dict[str, Any]] = {}
    for path in sorted((source_dir / s).glob(f"{s}.*")):
        name = path.name.split(".", 1)[1]
        if name == "series" or name in _SKIP_LOOKUPS:
            continue
        header, rows = _read_tsv(path)
        if len(header) < 2:
            continue
        key_idx = [i for i, h in enumerate(header) if h.endswith("_code") and h in series_cols]
        key_cols = [header[i] for i in key_idx] if key_idx else [header[0]]
        if not key_idx:
            key_idx = [0]
        val_idx = next((i for i, h in enumerate(header)
                        if h.endswith("_name") or h.endswith("_text")), len(header) - 1)
        bound = max(key_idx + [val_idx])
        table = {tuple(r[i] for i in key_idx): r[val_idx] for r in rows if len(r) > bound}
        lookups[name] = {"key_cols": key_cols, "table": table}
    return lookups


def _normalize_base(text: str) -> str:
    """Normalize base-period casing: 'DECEMBER 1997=100' -> 'December 1997=100'."""
    return re.sub(r"[A-Z]{3,}", lambda m: m.group(0).title(), text.strip())


def _format_base_date(value: str) -> str:
    """Format PPI's packed base_date: '201004' -> '2010-04', '198200' -> '1982'."""
    value = value.strip()
    if len(value) == 6 and value.isdigit():
        return value[:4] if value[4:] == "00" else f"{value[:4]}-{value[4:]}"
    return value


def _resolve_units(row: list[str], ix: dict[str, int], lookups: dict[str, dict[str, Any]]):
    """Return (units, index_base). BLS encodes units three different ways.

    Surveys carry either an explicit data-type column (LN/LE/LA/JT...), an index
    base (CPI/PPI/EI), or neither (AP is dollars). ``ce``/``sm`` have a
    ``data_type_code`` but ship no lookup table, so the code is returned raw.
    """
    for col in _UNITS_COLUMNS:
        if col in ix and ix[col] < len(row):
            code = row[ix[col]]
            lk = lookups.get(col[:-5])
            label = lk["table"].get((code,)) if lk else None
            if label:
                return label, None
            if code:
                return code, None  # no lookup shipped (e.g. ce/sm data_type)
    for col, fmt in (("base_period", _normalize_base), ("base_date", _format_base_date)):
        if col in ix and ix[col] < len(row) and row[ix[col]]:
            return "Index", fmt(row[ix[col]])
    return None, None


def _resolve_frequency(row: list[str], ix: dict[str, int], lookups: dict[str, dict[str, Any]]) -> str:
    """Frequency from periodicity_code when present, else derived from the period."""
    if "periodicity_code" in ix and ix["periodicity_code"] < len(row):
        code = row[ix["periodicity_code"]]
        lk = lookups.get("periodicity")
        label = lk["table"].get((code,)) if lk else None
        if label:
            return label
    period = row[ix["end_period"]] if "end_period" in ix and ix["end_period"] < len(row) else ""
    return {"M": "Monthly", "Q": "Quarterly", "S": "Semiannual", "A": "Annual"}.get(period[:1], "")


def _survey_names(source_dir: Path) -> dict[str, str]:
    """Parse code -> name from the cached LABSTAT overview.txt."""
    overview = Path(source_dir) / "overview.txt"
    if not overview.exists():
        return {}
    names = {}
    for line in overview.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"\s*([A-Z]{2})\s+(\S.*?)\s*$", line)
        if m:
            names[m.group(1)] = m.group(2)
    return names


def _survey_stats(source_dir: Path, survey: str) -> dict[str, Any]:
    """Series/active counts and max end_year for one survey's .series file."""
    s = survey.lower()
    header, rows = _read_tsv(Path(source_dir) / s / f"{s}.series")
    ix = {h: i for i, h in enumerate(header)}
    years = [int(r[ix["end_year"]]) for r in rows
             if ix.get("end_year", 99) < len(r) and r[ix["end_year"]].isdigit()]
    if not years:
        return {"series_count": len(rows), "active_count": 0, "max_end_year": None}
    mx = max(years)
    return {"series_count": len(rows),
            "active_count": sum(1 for y in years if y >= mx - 1),
            "max_end_year": mx}


def write_survey_yaml(
    source_dir: Path | str = BLS_SOURCE_DIR,
    output_path: Path | str = BLS_DATA_DIR / "survey.yaml",
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write one survey.yaml describing every survey present in ``source_dir``.

    Series files reference these entries by the two-character survey code.
    """
    source_dir, output_path = Path(source_dir), Path(output_path)
    names = _survey_names(source_dir)
    surveys = []
    for d in sorted(p for p in source_dir.iterdir() if p.is_dir()):
        code = d.name.upper()
        if not (d / f"{d.name}.series").exists():
            continue
        stats = _survey_stats(source_dir, code)
        entry = {
            "code": code,
            "name": names.get(code, ""),
            "series_file": f"bls_series_{code}.yaml",
            **stats,
            # A survey whose newest data is years old is a retired program.
            "is_active": bool(stats["max_end_year"] and stats["max_end_year"] >= date.today().year - 4),
        }
        if manifest and code in manifest:
            entry["source_file"] = manifest[code]["series_file"]
            entry["source_mtime"] = manifest[code].get("source_mtime")
            entry["source_bytes"] = manifest[code].get("source_bytes")
            entry["lookups"] = manifest[code].get("lookups", [])
        surveys.append(entry)

    payload = {
        "generated": date.today().isoformat(),
        "source": f"{BLS_DOWNLOAD_BASE}/",
        "survey_count": len(surveys),
        "surveys": surveys,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)
    print(f"Wrote {len(surveys)} surveys to {output_path}")
    return payload


def write_series_yaml(
    survey: str,
    source_dir: Path | str = BLS_SOURCE_DIR,
    output_dir: Path | str = BLS_DATA_DIR,
    popular_ids: set[str] | None = None,
) -> int:
    """Write bls_series_<CODE>.yaml for one survey. Returns the record count.

    Every series is written (not just active ones) with an ``is_active`` flag,
    so consumers can re-filter without regenerating. Records are sorted by
    series_id so successive exports diff cleanly.
    """
    code = survey.upper()
    s = code.lower()
    source_dir, output_dir = Path(source_dir), Path(output_dir)
    header, rows = _read_tsv(source_dir / s / f"{s}.series")
    ix = {h: i for i, h in enumerate(header)}
    lookups = _load_lookups(code, source_dir, header)
    popular_ids = popular_ids or set()

    years = [int(r[ix["end_year"]]) for r in rows
             if ix.get("end_year", 99) < len(r) and r[ix["end_year"]].isdigit()]
    max_end_year = max(years) if years else 0

    units_cols = {c for c in _UNITS_COLUMNS if c in ix}
    facet_cols = [c for c in header
                  if c.endswith("_code") and c not in _NON_FACET and c not in units_cols]

    records = []
    for r in rows:
        if len(r) < len(header):
            continue
        g = lambda col: r[ix[col]] if col in ix and ix[col] < len(r) else ""
        end_year = g("end_year")
        if not end_year.isdigit():
            continue
        start_iso, start_int = _iso_and_int(g("begin_year") or end_year, g("begin_period") or "M01")
        end_iso, end_int = _iso_and_int(end_year, g("end_period") or "M01")
        units, index_base = _resolve_units(r, ix, lookups)
        units = units or _UNITS_FALLBACK.get(code)

        facets = {}
        for col in facet_cols:
            value = g(col)
            # All-zero / dash codes mean "all ages, all races, ..." — noise.
            if not value or not value.strip("0-"):
                continue
            name = col[:-5]
            lk = lookups.get(name)
            if lk:
                # Compound lookups (e.g. item keyed by group+item) pull their
                # other key columns from this same series row.
                key = tuple(g(kc) for kc in lk["key_cols"])
                facets[name] = lk["table"].get(key, value)
            else:
                facets[name] = value

        seasonal_lk = lookups.get("seasonal")
        seasonal = (seasonal_lk["table"].get((g("seasonal"),)) if seasonal_lk else None)

        record = {
            "series_id": g("series_id"),
            "title": g("series_title") or g("series_name"),
            "survey": code,
            "units": units,
            "frequency": _resolve_frequency(r, ix, lookups),
            "seasonal_adjustment": seasonal or g("seasonal") or None,
            "observation_start": start_iso,
            "observation_start_int": start_int,
            "observation_end": end_iso,
            "observation_end_int": end_int,
            "is_active": int(end_year) >= max_end_year - 1,
            "is_popular": g("series_id") in popular_ids,
        }
        if index_base:
            record["index_base"] = index_base
        if facets:
            record["facets"] = facets
        records.append(record)

    records.sort(key=lambda rec: rec["series_id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"bls_series_{code}.yaml"
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"survey": code, "generated": date.today().isoformat(),
                        "series_count": len(records), "series": records},
                       fh, sort_keys=False, allow_unicode=True)
    active = sum(1 for rec in records if rec["is_active"])
    print(f"  {code}: {len(records):,} series ({active:,} active) -> {path}")
    return len(records)


def write_all_series_yaml(
    surveys: list[str] | None = None,
    source_dir: Path | str = BLS_SOURCE_DIR,
    output_dir: Path | str = BLS_DATA_DIR,
    popular: dict[str, set[str]] | None = None,
) -> int:
    """Write a series YAML per survey. Returns the total record count.

    ``popular`` maps a survey code to its popular series IDs (from
    ``fetch_popular_ids``); passed through so each record's ``is_popular`` is set.
    """
    source_dir = Path(source_dir)
    surveys = surveys or [p.name.upper() for p in sorted(source_dir.iterdir())
                          if p.is_dir() and (p / f"{p.name}.series").exists()]
    popular = popular or {}
    return sum(write_series_yaml(c, source_dir, output_dir, popular.get(c.upper()))
               for c in surveys)


async def fetch_popular_ids(
    surveys: list[str] | None = None,
    delay: float = 1.0,
) -> dict[str, set[str]]:
    """Fetch each survey's ~25 most-popular series IDs for the ``is_popular`` flag.

    Uses the BLS API directly (not the MCP server), so it fits the otherwise
    offline generation flow. Pass the result to ``write_all_series_yaml(popular=...)``
    and ``export_oe_national(popular_ids=...)``.
    """
    from clients import BlsClient  # lazy: only needed during generation

    surveys = [s.upper() for s in (surveys or CORE_SURVEYS)]
    popular: dict[str, set[str]] = {}
    async with BlsClient() as client:
        for code in surveys:
            await asyncio.sleep(delay)  # BLS API is rate-limited; be gentle
            try:
                response = await client.get_popular_series(survey=code)
                popular[code] = {s.series_id for s in response.results.series}
            except Exception as exc:  # a survey may have no popular list
                popular[code] = set()
                print(f"  {code}: no popular series ({type(exc).__name__})")
    return popular


# OE (Occupational Employment & Wage Statistics) is a ~6M-series
# occupation x geography x industry cross-product -- too large to catalog whole.
# We keep only the national, all-industries occupation series: employment and
# wages by detailed occupation (the elite-overproduction data, ~16.5k series).
OE_NATIONAL_FILTER = {"areatype_code": "N", "industry_code": "000000"}


def _stream_download(url: str, dest: Path, chunk: int = 1 << 20) -> int:
    """Stream a large file to disk (curl_cffi browser fingerprint), returning bytes.

    Used for oe.series (~1.26 GB) so the whole file is never held in memory.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with curl_requests.Session() as session:
        response = session.get(url, impersonate=BLS_IMPERSONATE, stream=True, timeout=1800)
        if response.status_code != 200:
            raise RuntimeError(f"download failed: HTTP {response.status_code} for {url}")
        with open(dest, "wb") as fh:
            for piece in response.iter_content(chunk_size=chunk):
                fh.write(piece)
                total += len(piece)
    return total


def _filter_series_file(src: Path, dst: Path, keep: dict[str, str]) -> int:
    """Write header + rows matching every ``keep`` {column: value}. Streaming."""
    kept = 0
    with open(src, encoding="utf-8", errors="ignore") as fin:
        header = fin.readline()
        cols = [h.strip() for h in header.rstrip("\n").split("\t")]
        idx = {c: cols.index(c) for c in keep if c in cols}
        with open(dst, "w", encoding="utf-8") as fout:
            fout.write(header)
            for line in fin:
                parts = line.rstrip("\n").split("\t")
                if all(len(parts) > i and parts[i].strip() == keep[c] for c, i in idx.items()):
                    fout.write(line)
                    kept += 1
    return kept


async def export_oe_national(
    dest: Path | str = BLS_SOURCE_DIR,
    output_dir: Path | str = BLS_DATA_DIR,
    keep_full: bool = False,
    force: bool = False,
    delay: float = 3.0,
    popular_ids: set[str] | None = None,
) -> int:
    """Download OE, filter to the national/all-industries slice, write its YAML.

    Wraps the whole OE process into one call: stream ``oe.series`` (~1.26 GB) to
    disk, filter to ``areatype=N`` + ``industry=000000`` (~16.5k occupation
    employment/wage series), fetch OE's lookups (so occupation/datatype decode),
    and write ``bls_series_OE.yaml``. Returns the record count.

    The full file is removed after filtering unless ``keep_full`` is set. With
    the filtered ``oe.series`` already present, a re-run skips the big download
    unless ``force=True``.
    """
    dest, output_dir = Path(dest), Path(output_dir)
    oe_dir = dest / "oe"
    oe_dir.mkdir(parents=True, exist_ok=True)
    full = oe_dir / "oe.series.full"
    filtered = oe_dir / "oe.series"

    if force or not filtered.exists():
        if force or not full.exists():
            print("Downloading oe.series (~1.26 GB, streamed)...")
            n = await asyncio.to_thread(
                _stream_download, f"{BLS_DOWNLOAD_BASE}/oe/oe.series", full
            )
            print(f"  downloaded {n / 1e6:.0f} MB")
        kept = _filter_series_file(full, filtered, OE_NATIONAL_FILTER)
        print(f"  filtered to {kept:,} national / all-industries series")
        if not keep_full:
            full.unlink(missing_ok=True)

    # oe.series is now small, so fetching lookups (and overview.txt) is cheap.
    await fetch_bls_source_files(["OE"], dest=dest, delay=delay)
    return write_series_yaml("OE", source_dir=dest, output_dir=output_dir,
                             popular_ids=popular_ids)


def bls_point_to_date(row: dict[str, Any]) -> datetime:
    """Convert a BLS observation's ``year`` + ``period`` into a datetime.

    BLS has no date field. Periods are coded ``M01``-``M12`` (monthly, with
    ``M13`` = annual average), ``Q01``-``Q04`` (quarterly, ``Q05`` = annual),
    ``S01``-``S02`` (semiannual, ``S03`` = annual) and ``A01`` (annual).
    Aggregate periods collapse to January 1st of the year.
    """
    year = int(row["year"])
    period = str(row["period"])
    prefix, code = period[:1], period[1:]

    try:
        index = int(code)
    except ValueError:
        return datetime(year, 1, 1)

    if prefix == "M" and 1 <= index <= 12:
        return datetime(year, index, 1)
    if prefix == "Q" and 1 <= index <= 4:
        return datetime(year, 3 * index - 2, 1)
    if prefix == "S" and 1 <= index <= 2:
        return datetime(year, 6 * index - 5, 1)
    return datetime(year, 1, 1)  # A01, M13, Q05, S03 and anything unexpected


def suppressed_observations(series: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows whose value will not parse as a number.

    BLS withholds a figure by publishing a non-numeric placeholder ('-') rather
    than omitting the row, usually with a footnote saying why.
    ``bls_series_to_arrays`` drops these so a plot does not break, which means
    the point count silently disagrees with the observation count unless a
    caller looks -- so this makes looking easy.
    """
    out = []
    for row in series.get("observations", series.get("data", [])):
        try:
            float(row["value"])
        except (TypeError, ValueError, KeyError):
            out.append(row)
    return out


def bls_series_to_arrays(series: dict[str, Any]) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Return ``(values, dates)`` for one series, in chronological order.

    BLS returns observations newest-first with string values, so this sorts
    ascending and casts to float. Rows whose value will not parse are skipped.
    """
    points: list[tuple[datetime, float]] = []
    # `observations` is meida's name for what BLS calls `data`. The rows now
    # carry a derived ISO `date`, so bls_point_to_date is only the fallback for
    # a row whose period code the server could not resolve.
    for row in series.get("observations", series.get("data", [])):
        try:
            value = float(row["value"])
        except (TypeError, ValueError):
            continue  # e.g. suppressed or non-numeric entries
        iso = row.get("date")
        when = datetime.fromisoformat(iso) if iso else bls_point_to_date(row)
        points.append((when, value))

    points.sort(key=lambda point: point[0])
    dates = numpy.array([point[0] for point in points])
    values = numpy.array([point[1] for point in points])
    return values, dates


def plot_bls_series(series: dict[str, Any], **kwargs: Any) -> None:
    """Plot one BLS series with the project style.

    Titles/labels default to the series catalog when it was requested with
    ``catalog=True``. Extra kwargs pass through to ``lib.plots.curve``
    (``plot_axis_type``, ``figsize``, ``ylim``, ``file_name``, ...).
    """
    # Imported lazily: lib.plots pulls in matplotlib and backtrader, which the
    # non-plotting notebooks shouldn't pay for on `import utils`.
    from lib.plots import curve

    values, dates = bls_series_to_arrays(series)
    catalog = series.get("catalog") or {}
    kwargs.setdefault("title", catalog.get("series_title") or series.get("series_id"))
    kwargs.setdefault("xlabel", "Date")
    kwargs.setdefault("ylabel", catalog.get("measure_data_type") or "Value")
    curve(values, dates, **kwargs)


async def fetch_series(
    series_ids: list[str],
    output_path: str,
    start_year: int | None = None,
    end_year: int | None = None,
    calculations: bool = False,
    delay_seconds: float = 0.5,
) -> None:
    """Fetch observations for the given series IDs (batched by 50) and write YAML."""
    all_series: list[dict[str, Any]] = []
    for start in range(0, len(series_ids), 50):  # BLS caps at 50 series per query
        batch = series_ids[start : start + 50]
        time.sleep(delay_seconds)  # be polite with the BLS API
        result = await call_tool(
            "bls_series_data",
            {
                "series_ids": batch,
                "start_year": start_year,
                "end_year": end_year,
                "calculations": calculations,
            },
        )
        payload = result.structuredContent  # type: ignore
        all_series.extend(payload["series"])
        print(f"Fetched {len(batch)} series (total {len(all_series)})")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(all_series, fh, sort_keys=False, allow_unicode=True)
    print(f"Wrote {len(all_series)} series to {output_path}")


# --- direct-client helpers (client.ipynb) ------------------------------------
#
# Everything above works on the MCP server's payloads: dicts with renamed keys
# (`observations`, `series_id`, `period_type`) and a derived ISO `date` on every
# row. navi's BlsClient does none of that renaming -- it returns the pydantic
# models in clients/models/bls.py, holding BLS's own field names and string
# values. These are separate functions rather than edits to the ones above
# because both shapes have to keep working side by side.


def show_client_envelope(response: BlsBaseResponse) -> None:
    """Print the envelope every BLS response carries: status, time, messages.

    ``message`` is the field to watch. BLS answers 200 with data even when it
    silently trimmed the request, and the advisory listed here is the only
    sign that what came back is not what was asked for.
    """
    print(f"status={response.status}  response_time={response.response_time}ms")
    if not response.message:
        print("message: []  -- BLS answered the request as asked")
    for message in response.message:
        print(f"message: {message}")


def show_client_surveys(response: BlsSurveysResponse,
                        match: str | None = None) -> list[Survey]:
    """Print and return ``Survey`` models (abbreviation + name).

    BLS publishes ~70 survey programs, so ``match`` filters to the ones whose
    name or abbreviation contains it (case-insensitive) rather than printing
    the whole catalog.
    """
    surveys = list(response.results.survey)
    if match:
        needle = match.lower()
        hits = [survey for survey in surveys
                if needle in survey.survey_name.lower()
                or needle in survey.survey_abbreviation.lower()]
        print(f"{len(hits)} of {len(surveys)} surveys match {match!r}\n")
        surveys = hits
    for survey in surveys:
        print(f"{survey.survey_abbreviation}: {survey.survey_name}")
    return surveys


def show_client_series_catalog(response: BlsSeriesResponse) -> dict[str, str]:
    """Print ``series_id  title  [units]`` for a ``catalog=True`` fetch.

    Returns the id -> title mapping, which is what turns a list of opaque BLS
    ids into something a caller can choose from.
    """
    titles: dict[str, str] = {}
    for series in response.results.series:
        catalog = series.catalog
        title = (catalog.series_title if catalog else None) or "(no catalog metadata)"
        units = (catalog.measure_data_type if catalog else None) or ""
        titles[series.series_id] = title
        print(f"{series.series_id}  {title}" + (f"  [{units}]" if units else ""))
    return titles


def show_client_observations(rows: list[Observation], count: int = 6) -> None:
    """Print observations as ``year  period  periodName  value``.

    Those are the model's own fields: no date, and a value that is still a
    string. Rows arrive newest-first, so the head of the list is the most
    recent data BLS returned for the request.
    """
    for row in rows[:count]:
        print(f"{row.year}  {row.period:<4} {row.period_name:<10} {row.value}")


def client_observation_date(observation: Observation) -> datetime:
    """Derive a datetime from an ``Observation``'s ``year`` + ``period``.

    The models carry no date field because BLS sends none: a row is dated by a
    year string and a period *code*. Turning the pair into a datetime is the
    caller's job here, and it is one of the steps the MCP layer performs before
    a payload reaches the walkthrough notebook.
    """
    return bls_point_to_date({"year": observation.year, "period": observation.period})


def client_observation_span(rows: list[Observation]) -> tuple[str | None, str | None]:
    """Return the (earliest, latest) derived ISO date across observations.

    A response trimmed to the 20-year limit looks exactly like a complete one,
    so the span is what shows which years actually came back.
    """
    dates = sorted(client_observation_date(row) for row in rows)
    if not dates:
        return (None, None)
    return (dates[0].date().isoformat(), dates[-1].date().isoformat())


def client_monthly_observations(series: Series) -> list[Observation]:
    """Keep only the true monthly rows (``M01``-``M12``) of a ``Series``.

    Requested with ``annualaverage=True``, a monthly series interleaves an
    ``M13`` row per year holding that year's mean. ``M13`` names no month, so
    any date derivation collapses it onto January 1st -- the same date as that
    year's ``M01`` -- and plotting the unfiltered list draws two points on one
    x. The period code is the only field that separates them.
    """
    return [row for row in series.data
            if row.period.startswith("M") and row.period != "M13"]


def show_client_suppressed(rows: list[Observation]) -> list[Observation]:
    """Print, and return, the observations whose value will not parse.

    BLS withholds a figure by publishing a non-numeric placeholder ('-')
    rather than omitting the row, usually with a footnote saying why. Arrays
    built from these rows are therefore shorter than the list they came from,
    so the count and the offending rows get printed rather than left implicit.
    """
    withheld: list[Observation] = []
    for row in rows:
        try:
            float(row.value)
        except (TypeError, ValueError):
            withheld.append(row)
    print(f"{len(rows)} observations, {len(rows) - len(withheld)} plottable")
    for row in withheld:
        notes = "; ".join(note.text or "" for note in row.footnotes)
        print(f"  withheld: {row.year}-{row.period}  value={row.value!r}  {notes}")
    return withheld


def client_observations_to_arrays(
    rows: list[Observation],
) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Return ``(values, dates)`` as numpy arrays, in chronological order.

    Three things the client leaves to the caller happen here: the string value
    is parsed to a float, the year/period pair is turned into a datetime, and
    the newest-first list is sorted ascending. Rows whose value will not parse
    are skipped -- ``show_client_suppressed`` reports which ones.
    """
    points: list[tuple[datetime, float]] = []
    for row in rows:
        try:
            value = float(row.value)
        except (TypeError, ValueError):
            continue  # withheld or otherwise non-numeric
        points.append((client_observation_date(row), value))

    points.sort(key=lambda point: point[0])
    dates = numpy.array([point[0] for point in points])
    values = numpy.array([point[1] for point in points])
    return values, dates


def plot_client_series(series: Series, rows: list[Observation] | None = None,
                       **kwargs: Any) -> None:
    """Plot a ``Series`` model with the project style.

    ``rows`` defaults to every observation on the series; pass a filtered list
    (see ``client_monthly_observations``) to plot a subset. Titles and labels
    default to the catalog, which is only populated when the fetch asked for
    ``catalog=True``. Extra kwargs pass through to ``lib.plots.curve``.
    """
    # Imported lazily: lib.plots pulls in matplotlib and backtrader, which the
    # non-plotting notebooks shouldn't pay for on `import utils`.
    from lib.plots import curve

    values, dates = client_observations_to_arrays(series.data if rows is None else rows)
    catalog = series.catalog
    kwargs.setdefault("title", (catalog.series_title if catalog else None) or series.series_id)
    kwargs.setdefault("xlabel", "Date")
    kwargs.setdefault("ylabel", (catalog.measure_data_type if catalog else None) or "Value")
    curve(values, dates, **kwargs)
