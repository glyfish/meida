"""Helpers for exploring BIS data through the MCP server.

Mirrors notebooks/fred/utils.py and notebooks/bls/utils.py: thin wrappers over
the BIS MCP tools, plus decoding (BIS returns dimension *codes*, decoded via the
data structure) and plotting. The MCP server must be running (see the README).
"""
from typing import Any
from datetime import date, datetime
from pathlib import Path
import asyncio
import random
import re

import numpy
import yaml

from lib.mcp_client import MCPClient, MCPClientConfig
from lib.utils import print_json_vertical
from lib.env import get_mcp_url

MCP_URL = get_mcp_url()
config = MCPClientConfig(url=MCP_URL)


async def call_tool(tool_name: str, arguments: dict[str, Any] | None = None):
    async with MCPClient(config) as client:
        return await client.call_tool(tool_name, arguments or {})


async def list_mcp_tools() -> None:
    async with MCPClient(config) as client:
        for tool in await client.list_tools():
            print(f"{tool.name}: {tool.description}")


def _unwrap(result: Any) -> Any:
    """Return a tool's payload from its MCP structuredContent, or raise."""
    content = getattr(result, "structuredContent", None)
    if not content or "result" not in content:
        raise RuntimeError(f"Unexpected MCP response: {content!r}")
    return content["result"]


async def show_dataflows() -> list[dict[str, Any]]:
    """Print and return the available BIS dataflows (id + name)."""
    flows = _unwrap(await call_tool("bis_dataflows"))["dataflows"]
    for flow in flows:
        print(f"{flow['id']:22s} {flow.get('name', '')}")
    return flows


async def show_datastructure(dsd_id: str, include_codes: bool = False) -> dict[str, Any]:
    """Print and return a dataflow's dimensions and codelists.

    ``dsd_id`` is the data-structure id (often the dataflow id with WS_ swapped
    for BIS_, e.g. WS_TC -> BIS_TOTAL_CREDIT). Codelists are summarized by count
    unless ``include_codes=True`` (some hold 1000+ entries).
    """
    dsd = _unwrap(await call_tool(
        "bis_datastructure", {"dsd_id": dsd_id, "include_codes": include_codes}
    ))
    print(f"{dsd['id']}: {dsd.get('name', '')}")
    print("dimensions (key order):", [d["id"] for d in dsd["dimensions"]])
    for name, codelist in dsd.get("codelists", {}).items():
        count = codelist.get("code_count", len(codelist.get("codes", {})))
        print(f"  {name:22s} {count} codes")
    return dsd


async def get_series(
    flow: str,
    key: str = "all",
    start_period: str | None = None,
    end_period: str | None = None,
) -> dict[str, Any]:
    """Fetch observations for a dataflow. ``key`` is the dot-joined series key
    in dimension order (e.g. 'M.US'); omit a position to wildcard ('M..A')."""
    return _unwrap(await call_tool(
        "bis_series_data",
        {"flow": flow, "key": key, "start_period": start_period, "end_period": end_period},
    ))


async def decode_series(
    flow: str,
    key: str,
    dsd_id: str,
    start_period: str | None = None,
    end_period: str | None = None,
) -> dict[str, Any]:
    """Fetch a series and label its dimension codes using the data structure.

    Adds a ``labels`` dict to each series (code -> human name) alongside the raw
    ``dimensions``, so BIS's coded keys (BORROWERS_CTY='US') read as
    'United States'.
    """
    data = await get_series(flow, key, start_period, end_period)
    dsd = _unwrap(await call_tool(
        "bis_datastructure", {"dsd_id": dsd_id, "include_codes": True}
    ))
    tables = {dim["id"]: dsd["codelists"].get(dim.get("codelist_id"), {}).get("codes", {})
              for dim in dsd["dimensions"]}
    # UNIT_MEASURE is an attribute (not a dimension) carried as a code, e.g. 368;
    # its codelist is the unit one (CL_BIS_UNIT / CL_UNIT_MEASURE), not the
    # multiplier (CL_UNIT_MULT). Decode it so plots get "Per cent per year".
    unit_codes: dict[str, str] = {}
    for cid, cl in dsd["codelists"].items():
        if "UNIT" in cid and "MULT" not in cid:
            unit_codes = cl.get("codes", {})
            break
    for series in data.get("series", []):
        series["labels"] = {
            dim: tables.get(dim, {}).get(code, code)
            for dim, code in series.get("dimensions", {}).items()
            if dim in tables
        }
        unit = series.get("unit_measure")
        if unit and unit in unit_codes:
            series["unit_label"] = unit_codes[unit]
    return data


def bis_period_to_date(period: str) -> datetime:
    """Convert a BIS TIME_PERIOD to a datetime.

    Handles annual (YYYY), monthly (YYYY-MM), quarterly (YYYY-Qn), and
    semiannual (YYYY-Sn); anything else falls back to Jan 1 of the year.
    """
    period = period.strip()
    year = int(period[:4])
    if len(period) == 4:
        return datetime(year, 1, 1)
    tail = period[5:]
    if tail[:1] == "Q":
        return datetime(year, 3 * int(tail[1:]) - 2, 1)
    if tail[:1] == "S":
        return datetime(year, 6 * int(tail[1:]) - 5, 1)
    if tail.isdigit():  # YYYY-MM
        return datetime(year, int(tail), 1)
    return datetime(year, 1, 1)


def bis_series_to_arrays(series: dict[str, Any]) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Return ``(values, dates)`` for one series, chronologically, skipping nulls."""
    points = [
        (bis_period_to_date(obs["time_period"]), obs["value"])
        for obs in series.get("observations", [])
        if obs.get("value") is not None
    ]
    points.sort(key=lambda point: point[0])
    dates = numpy.array([p[0] for p in points])
    values = numpy.array([p[1] for p in points])
    return values, dates


def plot_bis_series(series: dict[str, Any], **kwargs: Any) -> None:
    """Plot one BIS series with the project style.

    Title defaults to the series' TITLE attribute (or its key). Extra kwargs
    pass through to ``lib.plots.curve``.
    """
    # Lazy import: lib.plots pulls in matplotlib, unneeded for pure data work.
    from lib.plots import curve

    values, dates = bis_series_to_arrays(series)
    kwargs.setdefault("title", series.get("title") or series.get("key"))
    kwargs.setdefault("xlabel", "Date")
    kwargs.setdefault("ylabel", series.get("unit_label") or series.get("unit_measure") or "Value")
    curve(values, dates, **kwargs)


# --- BIS metadata catalog export ---------------------------------------------
#
# Mirrors the BLS survey/series model: dataflow.yaml (the "survey" list) plus one
# bis_series_<FLOW>.yaml per dataflow. Metadata only -- observations are fetched
# from the API on demand. Built with the BLS-style paced request strategy
# (jittered delay + backoff), minus the browser fingerprint (BIS isn't blocked).

BIS_DATA_DIR = Path("data")

# The 5 giant cross-product flows (98% of the ~1.3M series -- banking/securities
# microdata) plus the one that errors on a keys query. Excluded; their useful
# aggregates could be added as filtered slices later (the OE approach).
BIS_SKIP_FLOWS = {
    "WS_LBS_D_PUB", "WS_CBS_PUB", "WS_DEBT_SEC2_PUB", "WS_NA_SEC_DSS",
    "WS_DER_OTC_TOV", "WS_NA_SEC_C3",
}


def _bis_period_int(period: str) -> int:
    """A BIS TIME_PERIOD -> YYYYMM01. Handles YYYY, YYYY-MM, YYYY-Qn, YYYY-Sn."""
    period = period.strip()
    year = int(period[:4])
    if len(period) == 4:
        return year * 10000 + 101
    tail = period[5:]
    if tail[:1] == "Q":
        return year * 10000 + (3 * int(tail[1:]) - 2) * 100 + 1
    if tail[:1] == "S":
        return year * 10000 + (6 * int(tail[1:]) - 5) * 100 + 1
    return year * 10000 + (int(tail) if tail.isdigit() else 1) * 100 + 1


def _bis_int_iso(value: int) -> str:
    return f"{value // 10000:04d}-{(value // 100) % 100:02d}-01"


def _dsd_id_from_structure(urn: str | None) -> str | None:
    """Extract the DSD id from a dataflow's structure urn (…=BIS:BIS_CBPOL(1.0))."""
    if not urn:
        return None
    ref = urn.split("=")[-1].split(":")[-1]
    return ref.split("(")[0] or None


async def _bis_retry(fn, *args, delay: float = 2.0, max_attempts: int = 4, **kwargs):
    """Call an async client method with jittered pacing + backoff (BLS strategy)."""
    last: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        await asyncio.sleep(random.uniform(delay, delay * 1.8))  # gentle, non-metronomic
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:  # BisAPIError / transport error
            last = exc
            if attempt < max_attempts:
                backoff = delay * (4 ** attempt)
                print(f"    {type(exc).__name__} — retrying in {backoff:.0f}s")
                await asyncio.sleep(backoff)
    raise last  # type: ignore[misc]


def build_bis_records(flow: str, dsd: Any, data: Any) -> list[dict[str, Any]]:
    """Build series-metadata records for one dataflow from its DSD + full data.

    Keys/facets/title come from the DSD dimensions -- not the client's ``key``,
    which is polluted by attribute columns (e.g. ``TITLE_TS``) on multi-attribute
    flows. Coverage is derived from the observations, then discarded: the catalog
    is metadata only.
    """
    dim_ids = [d.id for d in dsd.dimensions]
    decode = {
        d.id: (dsd.codelists[d.codelist_id].codes if d.codelist_id in dsd.codelists else {})
        for d in dsd.dimensions
    }
    unit_codes = next((cl.codes for cid, cl in dsd.codelists.items()
                       if "UNIT" in cid and "MULT" not in cid), {})

    records: list[dict[str, Any]] = []
    max_end_year = 0
    for series in data.series:
        dm = series.dimensions
        periods = [o.time_period for o in series.observations if o.value is not None]
        if not periods:
            continue
        start_int = min(_bis_period_int(p) for p in periods)
        end_int = max(_bis_period_int(p) for p in periods)
        max_end_year = max(max_end_year, end_int // 10000)
        key = ".".join(dm.get(i, "") for i in dim_ids)
        facets = {i.lower(): decode[i].get(dm[i], dm[i])
                  for i in dim_ids if i != "FREQ" and dm.get(i)}
        records.append({
            "series_id": f"{flow}/{key}",
            "key": key,
            "title": dm.get("TITLE") or dm.get("TITLE_TS"),
            "flow": flow,
            "units": unit_codes.get(dm.get("UNIT_MEASURE")),
            "frequency": decode.get("FREQ", {}).get(dm.get("FREQ")),
            "observation_start": _bis_int_iso(start_int),
            "observation_start_int": start_int,
            "observation_end": _bis_int_iso(end_int),
            "observation_end_int": end_int,
            "is_active": None,  # set below, per-flow
            "facets": facets,
        })
    for rec in records:
        rec["is_active"] = rec["observation_end_int"] // 10000 >= max_end_year - 1
    records.sort(key=lambda r: r["series_id"])
    return records


def _write_yaml(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)


async def export_bis_catalog(
    flows: list[str] | None = None,
    output_dir: Path | str = BIS_DATA_DIR,
    delay: float = 2.0,
) -> int:
    """Write the BIS metadata catalog: dataflow.yaml + bis_series_<FLOW>.yaml.

    Fetches each dataflow's structure (for decoding) and full data (for coverage
    dates) from the API, paced with BLS-style jitter + backoff. Metadata only;
    observations come from the API on demand. Returns the total record count.
    Defaults to the ~22 small flows (the giants in ``BIS_SKIP_FLOWS`` excluded).
    """
    from lib.clients import BisClient  # lazy: only needed for generation

    output_dir = Path(output_dir)
    async with BisClient() as client:
        all_flows = await _bis_retry(client.get_dataflows, delay=delay)
        by_id = {f.id: f for f in all_flows}
        flows = flows or [f.id for f in all_flows
                          if f.id.startswith("WS_") and f.id not in BIS_SKIP_FLOWS]

        entries: list[dict[str, Any]] = []
        for flow in flows:
            meta = by_id.get(flow)
            dsd_id = _dsd_id_from_structure(meta.structure if meta else None)
            dsd = await _bis_retry(client.get_datastructure, dsd_id, delay=delay)
            data = await _bis_retry(client.get_data, flow, "all", delay=delay)
            records = build_bis_records(flow, dsd, data)
            _write_yaml(
                {"flow": flow, "generated": date.today().isoformat(),
                 "series_count": len(records), "series": records},
                output_dir / f"bis_series_{flow}.yaml",
            )
            entries.append({
                "code": flow,
                "name": meta.name if meta else None,
                "dsd_id": dsd_id,
                "series_file": f"bis_series_{flow}.yaml",
                "series_count": len(records),
                "active_count": sum(r["is_active"] for r in records),
                "dimensions": [d.id for d in dsd.dimensions],
            })
            print(f"  {flow}: {len(records):,} series -> bis_series_{flow}.yaml")

        _write_yaml(
            {"generated": date.today().isoformat(),
             "source": "https://stats.bis.org/api/v1",
             "dataflow_count": len(entries), "dataflows": entries},
            output_dir / "dataflow.yaml",
        )
    return sum(e["series_count"] for e in entries)
