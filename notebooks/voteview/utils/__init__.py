"""Helpers for the Voteview notebooks.

Mirrors ``notebooks/cdc/utils``: fetchers and builders as importable modules,
the notebooks only drive them. The MCP wrappers below are the same thin shape
as the other sources', kept short because Voteview needs only the two
stored-series tools and the catalog — it has no source-specific tools of its
own, which is the point of storing it the same way as WONDER and NVSR.

The MCP server must be running (see the README).
"""
from typing import Any

import numpy

# ``environment`` is a plain module in meida's root, not an installed package --
# unlike navi's ``lib``, which pip resolves from anywhere. A kernel started in
# this notebook's directory would not find it, so anchor the root here instead
# of asking every notebook to append it.
import sys as _sys
from pathlib import Path as _Path
_MEIDA_ROOT = str(_Path(__file__).resolve().parents[3])
if _MEIDA_ROOT not in _sys.path:
    _sys.path.insert(0, _MEIDA_ROOT)

from environment import get_mcp_url
from lib.mcp_client import MCPClient, MCPClientConfig

MCP_URL = get_mcp_url()
config = MCPClientConfig(url=MCP_URL)

SOURCE = "voteview"


async def call_tool(tool_name: str, arguments: dict[str, Any] | None = None):
    async with MCPClient(config) as client:
        return await client.call_tool(tool_name, arguments or {})


async def list_mcp_tools(prefix: str | tuple[str, ...] | None = None) -> None:
    """Print the server's tools, optionally filtered by name prefix. Print-only."""
    prefixes = (prefix,) if isinstance(prefix, str) else prefix
    async with MCPClient(config) as client:
        for tool in await client.list_tools():
            if prefixes and not tool.name.startswith(tuple(prefixes)):
                continue
            print(f"{tool.name}: {tool.description}")


def _unwrap(result: Any) -> Any:
    """A tool's payload from its structuredContent, or a useful error.

    FastMCP wraps a plain Mapping as ``{"result": ...}`` and leaves a pydantic
    model's fields at the top level; both shapes appear.
    """
    content = getattr(result, "structuredContent", None)
    if content and not getattr(result, "isError", False):
        return content["result"] if set(content) == {"result"} else content
    blocks = getattr(result, "content", None) or []
    detail = " ".join(getattr(b, "text", "") for b in blocks).strip()
    raise RuntimeError(f"MCP tool error: {detail or content!r}")


async def show_tool_schema(tool_name: str) -> dict[str, Any]:
    """Print a tool's parameters and its response shape. Returns the schema."""
    async with MCPClient(config) as client:
        tool = next(t for t in await client.list_tools() if t.name == tool_name)
    schema = tool.inputSchema or {}
    required = set(schema.get("required") or [])
    print(f"{tool.name}\n  {tool.description}\n")
    for name, spec in (schema.get("properties") or {}).items():
        kind = spec.get("type") or ("enum" if "enum" in spec else "any")
        flag = "required" if name in required else "optional"
        print(f"  {name:20s} {str(kind):10s} {flag:9s} {spec.get('description', '')[:60]}")
    return schema


async def list_series() -> list[dict[str, Any]]:
    """Voteview's stored series -- metadata only, no observations."""
    return _unwrap(await call_tool("timeseries_source_list", {"source": SOURCE}))["series"]


async def get_series(native_id: str) -> dict[str, Any]:
    """One stored series in full."""
    return _unwrap(await call_tool(
        "timeseries_source_data", {"source": SOURCE, "native_id": native_id}))


async def search_catalog(**facets: Any) -> list[dict[str, Any]]:
    """Find Voteview series by facet -- ``measure=``, ``chamber=``."""
    args: dict[str, Any] = {"source": SOURCE, "limit": 50}
    if facets:
        args["facets"] = facets
    return _unwrap(await call_tool("series_catalog_search", args))["entries"]


def to_arrays(series: dict[str, Any]) -> tuple[numpy.ndarray, numpy.ndarray]:
    """``(years, values)`` as numpy arrays.

    Years rather than dates: the resolution is one Congress, two years apart,
    so a date axis would imply a precision the data does not have.
    """
    obs = [o for o in series.get("observations", []) if o.get("value") not in (None, "", ".")]
    return (numpy.array([int(o["date"][:4]) for o in obs]),
            numpy.array([float(o["value"]) for o in obs]))


def break_gaps(years: numpy.ndarray, values: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Reindex onto the full two-year grid, NaN where a Congress is missing.

    A gated Congress has no value -- ``party_predicts_position`` declines to
    compare a large median against a rump. Plotted as-is the line joins the
    Congresses either side of the hole, drawing a segment through values that
    were deliberately not computed. NaN breaks the line instead, so the absence
    is visible as absence.
    """
    if len(years) < 2:
        return years, values
    grid = numpy.arange(int(years[0]), int(years[-1]) + 1, 2)
    known = dict(zip(years.tolist(), values.tolist()))
    return grid, numpy.array([known.get(int(y), numpy.nan) for y in grid])


def stamp_source(*series: dict[str, Any], figure: Any = None) -> None:
    """Print the native_ids the figure was drawn from, along its bottom edge.

    A plot of stored data should say which rows it is. The title says what the
    measure means; this says what to ask the database for to get the same
    numbers back.
    """
    from matplotlib import pyplot

    ids = [str(s.get("native_id") or s.get("series_id") or "?") for s in series]
    if not ids:
        return
    fig = figure or pyplot.gcf()
    fig.subplots_adjust(bottom=max(0.12, 0.06 + 0.035 * len(ids)))
    fig.text(0.995, 0.005, "\n".join(ids), ha="right", va="bottom",
             fontsize=7, family="monospace", alpha=0.65)


def plot_series(series: dict[str, Any], **kwargs: Any) -> None:
    """Plot one stored series with the project style."""
    from lib.plots import curve

    years, values = break_gaps(*to_arrays(series))
    kwargs.setdefault("title", series.get("title") or series.get("native_id"))
    kwargs.setdefault("xlabel", "Year")
    kwargs.setdefault("ylabel", series.get("units") or "value")
    curve(values, years, **kwargs)
    stamp_source(series)


def plot_group(series_list: list[dict[str, Any]], labels: list[str], title: str,
               ylabel: str | None = None, figsize: tuple[int, int] = (11, 5)) -> None:
    """Overlay several stored series, for when the comparison is the point."""
    from matplotlib import pyplot

    pyplot.figure(figsize=figsize)
    for series, label in zip(series_list, labels):
        years, values = break_gaps(*to_arrays(series))
        pyplot.plot(years, values, label=label, linewidth=2)
    pyplot.ylabel(ylabel or str(series_list[0].get("units") or "value") if series_list else "value")
    pyplot.xlabel("Year")
    pyplot.title(title)
    if series_list:
        pyplot.legend()
    stamp_source(*series_list)
