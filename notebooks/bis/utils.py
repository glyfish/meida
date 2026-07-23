"""Helpers for exploring BIS data through the MCP server.

Mirrors notebooks/fred/utils.py and notebooks/bls/utils.py: thin wrappers over
the BIS MCP tools, plus decoding (BIS returns dimension *codes*, decoded via the
data structure) and plotting. The MCP server must be running (see the README).
"""
from typing import Any
from datetime import datetime

import numpy

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
    for series in data.get("series", []):
        series["labels"] = {
            dim: tables.get(dim, {}).get(code, code)
            for dim, code in series.get("dimensions", {}).items()
            if dim in tables
        }
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
    kwargs.setdefault("ylabel", series.get("unit_measure") or "Value")
    curve(values, dates, **kwargs)
