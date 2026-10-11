"""Helpers for the Clio-Infra notebooks.

Mirrors ``notebooks/cdc/utils`` and ``notebooks/voteview/utils``: fetchers and
builders as importable modules, the notebooks only drive them.

    fetch        the index, 87 workbooks and 86 description pages
    xlsx         a stdlib worksheet reader -- openpyxl is not in meida's env
    inventory    what the download holds, measured against the index
    clio_series  one stored series per indicator per country
    catalog      the series as catalog entries, one file per category
    units        a unit per indicator, from the DataverseNL documentation

The MCP helpers below are the same thin shape as the other sources'. Clio has
no tools of its own: it is served by the stored-series tools, which take ids,
so every lookup starts at the catalog. The MCP server must be running.
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

SOURCE = "clio"


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
    """A tool's payload from its structured_content, or a useful error.

    FastMCP wraps a plain Mapping as ``{"result": ...}`` and leaves a pydantic
    model's fields at the top level; both shapes appear.
    """
    content = getattr(result, "structured_content", None)
    if content and not getattr(result, "is_error", False):
        return content["result"] if set(content) == {"result"} else content
    blocks = getattr(result, "content", None) or []
    detail = " ".join(getattr(b, "text", "") for b in blocks).strip()
    raise RuntimeError(f"MCP tool error: {detail or content!r}")


async def show_tool_schema(tool_name: str) -> dict[str, Any]:
    """Print a tool's parameters and its response shape. Returns the schema."""
    async with MCPClient(config) as client:
        tool = next(t for t in await client.list_tools() if t.name == tool_name)
    schema = tool.input_schema or {}
    required = set(schema.get("required") or [])
    print(f"{tool.name}\n  {tool.description}\n")
    for name, spec in (schema.get("properties") or {}).items():
        kind = spec.get("type") or ("enum" if "enum" in spec else "any")
        flag = "required" if name in required else "optional"
        print(f"  {name:20s} {str(kind):10s} {flag:9s} {spec.get('description', '')[:60]}")
    return schema


async def concepts() -> list[dict[str, Any]]:
    """Clio's indicators with a series count each -- where discovery starts."""
    return _unwrap(await call_tool("series_catalog_concepts", {"source": SOURCE}))["concepts"]


async def search_catalog(concept: str | None = None, limit: int = 50,
                         **facets: Any) -> dict[str, Any]:
    """Catalog entries plus ``total``, so a truncated answer is visible as one.

    Facets are ``indicator``, ``country``, ``category``, ``kind`` and ``ccode``;
    ``concept`` is the indicator id.
    """
    args: dict[str, Any] = {"source": SOURCE, "limit": limit}
    if concept:
        args["concept"] = concept
    if facets:
        args["facets"] = facets
    return _unwrap(await call_tool("series_catalog_search", args))


async def describe(native_ids: list[str]) -> dict[str, Any]:
    """Coverage and staleness for these ids, without observations."""
    return _unwrap(await call_tool("timeseries_source_list", {"native_ids": list(native_ids)}))


async def get_series(native_id: str) -> dict[str, Any]:
    """One stored series in full."""
    return _unwrap(await call_tool(
        "timeseries_source_data", {"source": SOURCE, "native_id": native_id}))


def ids(found: dict[str, Any]) -> list[str]:
    """The native_ids in a catalog search result."""
    return [e["retrieval"]["native_id"] for e in found["entries"]]


# --- plotting -----------------------------------------------------------------

def step(series: dict[str, Any]) -> int:
    """The series' usual spacing in years, from its frequency label."""
    freq = (series.get("frequency") or "").casefold()
    if freq == "annual":
        return 1
    if freq == "decadal":
        return 10
    digits = "".join(c for c in freq if c.isdigit())
    return int(digits) if digits else 1


def to_arrays(series: dict[str, Any]) -> tuple[numpy.ndarray, numpy.ndarray]:
    """``(years, values)`` as numpy arrays -- years, since the data is annual or coarser."""
    obs = [o for o in series.get("observations", []) if o.get("value") not in (None, "", ".")]
    return (numpy.array([int(o["date"][:4]) for o in obs]),
            numpy.array([float(o["value"]) for o in obs]))


def break_gaps(years: numpy.ndarray, values: numpy.ndarray,
               every: int = 1) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Reindex onto the series' own grid, NaN where a year is missing.

    Clio's annual series have holes -- real wages alone have 722 gaps longer than
    a year -- and a line plot would bridge them. On the series' own step
    (1 annual, 10 decadal), a missing year breaks the line instead.

    The step is the indicator's, not the country's, so observations land off it:
    the livestock indicators are decadal until 2000 and annual after it, and
    Estonia's eleven goat observations plotted as two on a bare decadal grid.
    Union the observed years in, and an off-grid one is drawn where it falls
    rather than dropped -- 12,110 observations across 1,423 series.
    """
    if len(years) < 2:
        return years, values
    grid = numpy.union1d(numpy.arange(int(years[0]), int(years[-1]) + 1, every), years)
    known = dict(zip(years.tolist(), values.tolist()))
    return grid, numpy.array([known.get(int(y), numpy.nan) for y in grid])


def stamp_source(*series: dict[str, Any], figure: Any = None) -> None:
    """Print the native_ids the figure was drawn from, along its bottom edge."""
    from matplotlib import pyplot

    names = [str(s.get("native_id") or s.get("series_id") or "?") for s in series]
    if not names:
        return
    fig = figure or pyplot.gcf()
    fig.subplots_adjust(bottom=max(0.12, 0.06 + 0.035 * len(names)))
    fig.text(0.995, 0.005, "\n".join(names), ha="right", va="bottom",
             fontsize=7, family="monospace", alpha=0.65)


def plot_group(series_list: list[dict[str, Any]], labels: list[str], title: str,
               ylabel: str | None = None, figsize: tuple[int, int] = (11, 5)) -> None:
    """Overlay several stored series, lines broken at each one's own gaps."""
    from matplotlib import pyplot

    pyplot.figure(figsize=figsize)
    for series, label in zip(series_list, labels):
        years, values = break_gaps(*to_arrays(series), every=step(series))
        # Markers, because breaking at gaps leaves a lone observation between two
        # holes with no line to draw -- the UK's sparse 1543-1840 life expectancy
        # vanished entirely without them.
        pyplot.plot(years, values, label=label, linewidth=2, marker="o", markersize=2.5)
    units = str(series_list[0].get("units") or "") if series_list else ""
    pyplot.ylabel(ylabel or units or "value")
    pyplot.xlabel("Year")
    pyplot.title(title)
    if series_list:
        pyplot.legend()
    stamp_source(*series_list)
