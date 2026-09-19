"""Helpers for Clio-Infra at historical borders, from DataverseNL.

The same indicators as ``notebooks/clio``, deposited on DataverseNL with a
different geography: one row per **historical border period** (GeaCron before
1946, CShapes after) rather than one per modern country. The main site files
Ottoman wages under Turkey; this keeps the Ottoman Empire.

DataverseNL refuses automated clients outright -- headless Brave was denied on
sight -- so there is no fetch. Datasets are downloaded by hand and filed with
:func:`accept.accept`, which records the DOI, the deposit version and the
download date. Updating is manual and per dataset, which suits data that is
almost entirely historical.

    accept          file a hand-downloaded dataset folder under data/raw/
    workbook        read the Data sheet: title, unit, border periods, values
    documentation   read the .docx working paper into its numbered sections
    xlsx            stdlib worksheet reader, copied from notebooks/clio
    datasets        every indicator's DataverseNL DOI, from the Handle redirect
    historical_series   one stored series per polity per border period
    catalog         the series as catalog entries, one file per category

The MCP helpers below serve the stored series; the server must be running.
"""

from typing import Any

import numpy

# ``environment`` is a plain module in meida's root, not an installed package; a
# kernel started in a notebook directory would not find it, so anchor the root.
import sys as _sys
from pathlib import Path as _Path
_MEIDA_ROOT = str(_Path(__file__).resolve().parents[3])
if _MEIDA_ROOT not in _sys.path:
    _sys.path.insert(0, _MEIDA_ROOT)

from environment import get_mcp_url
from lib.mcp_client import MCPClient, MCPClientConfig

MCP_URL = get_mcp_url()
config = MCPClientConfig(url=MCP_URL)
SOURCE = "clio_historical"


async def call_tool(tool_name: str, arguments: dict[str, Any] | None = None):
    async with MCPClient(config) as client:
        return await client.call_tool(tool_name, arguments or {})


def _unwrap(result: Any) -> Any:
    """A tool's payload from its structuredContent, or a useful error."""
    content = getattr(result, "structuredContent", None)
    if content and not getattr(result, "isError", False):
        return content["result"] if set(content) == {"result"} else content
    blocks = getattr(result, "content", None) or []
    detail = " ".join(getattr(b, "text", "") for b in blocks).strip()
    raise RuntimeError(f"MCP tool error: {detail or content!r}")


async def concepts() -> list[dict[str, Any]]:
    """The indicators with historical-border series, and how many each."""
    return _unwrap(await call_tool("series_catalog_concepts", {"source": SOURCE}))["concepts"]


async def search_catalog(concept: str | None = None, limit: int = 50,
                         **facets: Any) -> dict[str, Any]:
    """Catalog entries plus ``total``. Facets: ``indicator``, ``polity``,
    ``category``, ``kind``, ``border_start``, ``border_end``, ``modern_country``."""
    args: dict[str, Any] = {"source": SOURCE, "limit": limit}
    if concept:
        args["concept"] = concept
    if facets:
        args["facets"] = facets
    return _unwrap(await call_tool("series_catalog_search", args))


async def borders_of(polity: str, concept: str) -> list[dict[str, Any]]:
    """Every border period one polity has for an indicator, earliest first."""
    found = await search_catalog(concept=concept, limit=200, polity=polity)
    return sorted(found["entries"], key=lambda e: e["facets"]["border_start"])


async def describe(native_ids: list[str]) -> dict[str, Any]:
    return _unwrap(await call_tool("timeseries_source_list", {"native_ids": list(native_ids)}))


async def get_series(native_id: str) -> dict[str, Any]:
    return _unwrap(await call_tool(
        "timeseries_source_data", {"source": SOURCE, "native_id": native_id}))


def to_arrays(series: dict[str, Any]) -> tuple[numpy.ndarray, numpy.ndarray]:
    obs = [o for o in series.get("observations", []) if o.get("value") not in (None, "", ".")]
    return (numpy.array([int(o["date"][:4]) for o in obs]),
            numpy.array([float(o["value"]) for o in obs]))


def break_gaps(years: numpy.ndarray, values: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Annual grid, NaN where a year is missing, so a line breaks instead of bridging."""
    if len(years) < 2:
        return years, values
    grid = numpy.arange(int(years[0]), int(years[-1]) + 1)
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
