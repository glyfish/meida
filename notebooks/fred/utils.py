"""Helpers for exploring FRED data through the MCP server.

Mirrors notebooks/{bls,cdc,bis}/utils.py: thin wrappers over the FRED MCP tools,
the category-tree crawlers that build the exported catalogs, and plotting. The
MCP server must be running (see the project README).
"""

import sys as _sys
from pathlib import Path as _Path

# meida's repo root, so `clients` resolves. The clients package used to live in
# navi (installed, hence importable from anywhere); it now sits beside
# mcp_server, which the notebooks' cwd does not reach. Anchored to __file__
# rather than "../.." so it holds whatever directory the kernel started in.
_sys.path.append(str(_Path(__file__).resolve().parents[2]))

from typing import TYPE_CHECKING, Any
from datetime import datetime
import textwrap
import yaml
import time
import json

import numpy

from lib.mcp_client import MCPClient, MCPClientConfig
from lib.utils import print_json_vertical
from environment import get_mcp_url

if TYPE_CHECKING:  # typed-client models: annotations only, no runtime import
    from clients.models.fred import ObservationsResponse, Series

MCP_URL = get_mcp_url()
config = MCPClientConfig(url=MCP_URL)

async def call_tool(tool_name: str, arguments: dict[str, Any] | None = None):
    async with MCPClient(config) as client:
        return await client.call_tool(tool_name, arguments or {})


#: Name prefixes of the FRED tools. ``list_releases`` predates the source-prefix
#: convention every other tool follows, so filtering on "fred_" alone silently
#: drops it -- the pair is what actually selects FRED's tools.
FRED_TOOL_PREFIXES = ("fred_", "list_releases")


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





async def children_of_categories(categories: list[Any]):
    for category in categories:
        category_id = category["id"]
        category_name = category["name"]
        args = {"category_id": category_id}
        result = await call_tool("fred_category_children", args)
        children = result.structuredContent['categories']  # type: ignore
        print(f"Category {category_id}, {category_name} has {len(children)} children")


async def explore_categories(root_id: int = 0, depth: int = 2):
    async with MCPClient(config) as client:
        queue = [(root_id, 0)]
        while queue:
            category_id, level = queue.pop(0)
            indent = "  " * level
            print(f"{indent}- category {category_id}")
            if level >= depth:
                continue
            response = await client.call_tool("fred_category_children", {"category_id": category_id})
            payload = response.structuredContent or {}
            for child in payload.get("categories", []):
                queue.append((child["id"], level + 1))


#: Where the category walks and the series merge persist their YAML. Both are
#: relative to notebooks/fred/, are gitignored, and are what yada's
#: fred_document_loader reads.
CATEGORY_DATA = _Path(__file__).resolve().parent / "categories" / "category_data"
SERIES_DATA = _Path(__file__).resolve().parent / "series" / "series_data"


def _resolve(output_path: str, default_dir: _Path) -> _Path:
    """A bare filename lands in *default_dir*; a path with a separator is used as given.

    The category notebooks pass a bare ``fred_prices_32455.yaml``, which used to
    be written beside the notebook and then moved into ``category_data/`` by
    hand -- an undocumented step that left at least one file stranded in the
    wrong directory. Resolving it here removes the step.
    """
    path = _Path(output_path)
    return path if path.is_absolute() or path.parent != _Path(".") else default_dir / path


async def find_leaf_categories(
    root_id: int = 0,
    root_name: str = "Root",
    output_path: str = "leaf_categories.yaml",
) -> None:
    """Walk the FRED category tree from *root_id* and record every leaf.

    Writes ``{leaf_id, leaf_name, path}`` per leaf to
    ``categories/category_data/<output_path>`` -- a bare filename resolves
    there. One ``fred_category_children`` call per node with a 2 second pause,
    so a full branch is minutes of FRED's 120 req/min budget.
    """
    leaves: list[dict[str, object]] = []
    queue: list[tuple[int, list[dict[str, object]]]] = [
        (root_id, [{"id": root_id, "name": root_name}])
    ]

    async with MCPClient(config) as client:
        while queue:
            time.sleep(2.0)  # Be kind to the FRED server
            category_id, path = queue.pop(0)

            response = await client.call_tool(
                "fred_category_children", {"category_id": category_id}
            )
            payload = response.structuredContent or {}
            children = payload.get("categories", [])

            if not children:
                leaves.append(
                    {
                        "leaf_id": category_id,
                        "leaf_name": path[-1]["name"],
                        "path": path,
                    }
                )
                print(f"Found Leaf category {path[-1]['name']}")
                continue

            for child in children:
                queue.append(
                    (
                        child["id"],
                        path + [{"id": child["id"], "name": child["name"]}],
                    )
                )

    target = _resolve(output_path, CATEGORY_DATA)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        payload = json.loads(json.dumps(leaves))
        yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)
    print(f"Wrote {len(leaves)} leaf categories (with names) to {target}")


async def export_finance_category_series(input_path: str, output_path: str, delay_seconds: float = 2.0,) -> None:
    """Merge a leaf-category file with FRED's series metadata for each leaf.

    Reads ``categories/category_data/<input_path>``, calls
    ``fred_category_series`` per leaf, and writes
    ``series/series_data/<output_path>`` as
    ``[{category_id, category_name, seriess: [...]}]``. Bare filenames resolve
    into those directories.

    **Metadata only** -- no observations. Each series record carries id, title,
    coverage bounds, frequency, units, seasonal adjustment, last_updated,
    popularity and notes. This is what yada's ``fred_document_loader`` indexes.

    One API call per leaf with *delay_seconds* between, so a branch of 160
    leaves is roughly six minutes.

    The name is historical: it was written for the finance branch and is used
    for all of them.
    """

    print(f"Reading categories from {input_path}")
    print(f"Writing series to {output_path}")

    source = _resolve(input_path, CATEGORY_DATA)
    with open(source, "r", encoding="utf-8") as fh:
        categories: list[dict[str, Any]] = yaml.safe_load(fh) or []

    print(f"Loaded {len(categories)} categories")

    series_bundle: list[dict[str, Any]] = []
    async with MCPClient(config) as client:
        for category in categories:
            time.sleep(delay_seconds)  # keep us polite with FRED
            category_id = category["leaf_id"]
            category_name = category["leaf_name"]

            response = await client.call_tool(
                "fred_category_series",
                {"category_id": category_id},
            )
            payload = response.structuredContent or {}

            # `count` is FRED's total for the category; the response carries only
            # what this call returned, so the two differ when it is truncated.
            # (This block used to read a "pagination" sub-dict that no FRED
            # response has ever had, so count/offset/limit were always 0.)
            count = payload.get("count", 0)
            seriess = payload.get("series", [])

            print(f"Processing {len(seriess)} series for category {category_id}, {category_name}")
            print(f"FRED reports {count} series in this category")

            series_bundle.append(
                {
                    "category_id": category_id,
                    "category_name": category_name,
                    "seriess": seriess,
                }
            )

    target = _resolve(output_path, SERIES_DATA)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        sanitized = json.loads(json.dumps(series_bundle))
        yaml.safe_dump(sanitized, fh, sort_keys=False, allow_unicode=True)

    print(f"Wrote series data for {len(series_bundle)} categories to {target}")

# --- tool results -------------------------------------------------------------


def unwrap(result: Any) -> dict[str, Any]:
    """Return a tool call's payload from its MCP ``structuredContent``, or raise.

    On failure this surfaces the tool's own error text -- an unknown tool because
    the running server predates it, a FRED key that is not set -- instead of the
    ``None`` a bare ``result.structuredContent[...]`` would blow up on one line
    later.
    """
    content = getattr(result, "structuredContent", None)
    if content and not getattr(result, "isError", False):
        # FastMCP derives structuredContent from the tool's return annotation: a
        # pydantic model (which every FRED tool returns) puts its fields at the
        # top level, while a plain mapping is wrapped as {"result": ...}.
        return content["result"] if set(content) == {"result"} else content
    blocks = getattr(result, "content", None) or []
    detail = " ".join(getattr(block, "text", "") for block in blocks).strip()
    raise RuntimeError(f"MCP tool error: {detail or content!r}")


def _schema_type(spec: dict[str, Any]) -> str:
    """Render a JSON-schema property's type.

    An optional parameter (``int | None``) arrives as
    ``anyOf: [{"type": "integer"}, {"type": "null"}]`` rather than a plain
    ``type``, so reading ``spec["type"]`` alone shows nothing for exactly the
    parameters most worth documenting. Optionality is already carried by the
    required/optional flag, so the null arm is dropped.
    """
    if "type" in spec:
        return str(spec["type"])
    arms = [arm.get("type") for arm in spec.get("anyOf", []) if arm.get("type") != "null"]
    return "|".join(arm for arm in arms if arm) or "?"


async def show_tool_schema(tool_name: str, raw: bool = False) -> dict[str, Any]:
    """Print one tool's arguments compactly: type, required/optional, default.

    Named to match the other sources' helpers, which all print this compact
    form. ``raw=True`` dumps the JSON schema instead -- the authoritative shape
    an MCP consumer actually parses. The compact form is where a default that
    matters is visible at a glance, such as ``fred_series_observations``'
    ``limit=100``.
    """
    async with MCPClient(config) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
    if tool_name not in tools:
        raise RuntimeError(f"no tool {tool_name!r} on the server. Available: {sorted(tools)}")
    schema = dict(tools[tool_name].inputSchema or {})
    if raw:
        print_json_vertical(schema)
        return schema
    required = set(schema.get("required") or [])
    print(f"{tool_name}\n  {tools[tool_name].description}\n")
    for name, spec in (schema.get("properties") or {}).items():
        flag = "required" if name in required else "optional"
        default = spec.get("default")
        suffix = "" if default is None else f", default={default!r}"
        print(f"  {name:12} {_schema_type(spec):8} {flag}{suffix}")
    return schema


# --- plotting -----------------------------------------------------------------


def fred_observations_to_arrays(
    observations: dict[str, Any],
) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Return ``(values, dates)`` from a ``fred_series_observations`` payload.

    Two things about FRED's observations are handled here rather than at every
    call site:

    * **Missing values.** FRED writes one as a single period; the response model
      maps that to ``value: null`` and *keeps the row*, so the series' calendar
      stays intact (DGS10 carries a null for every market holiday since 1962).
      Those rows are dropped here -- a gap is not a zero, and it is not
      plottable either.
    * **Strings.** Values arrive as strings, matching the house observation
      contract, so they are cast to float.
    """
    points: list[tuple[datetime, float]] = []
    for observation in observations.get("observations", []):
        raw = observation.get("value")
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        points.append((datetime.fromisoformat(observation["date"]), value))

    points.sort(key=lambda point: point[0])
    dates = numpy.array([point[0] for point in points])
    values = numpy.array([point[1] for point in points])
    return values, dates


def plot_fred_series(
    observations: dict[str, Any],
    info: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    """Plot one FRED series with the project style.

    ``info`` is an entry from ``fred_series_info``; pass it and the title and
    y-label come from FRED's own metadata instead of being retyped. FRED titles
    are full descriptive sentences ("Market Yield on U.S. Treasury Securities at
    10-Year Constant Maturity, Quoted on an Investment Basis"), so the title is
    shortened to fit the figure. Extra kwargs pass through to ``lib.plots.curve``
    (``figsize``, ``ylim``, ``plot_axis_type``, ``file_name``, ...).
    """
    # Imported lazily: lib.plots pulls in matplotlib and backtrader, which the
    # non-plotting notebooks shouldn't pay for on `import utils`.
    from lib.plots import curve

    values, dates = fred_observations_to_arrays(observations)
    info = info or {}
    title = info.get("title") or observations.get("series_id") or ""
    kwargs.setdefault("title", textwrap.shorten(title, width=72, placeholder=" ..."))
    kwargs.setdefault("xlabel", "Date")
    kwargs.setdefault("ylabel", info.get("units") or "Value")
    curve(values, dates, **kwargs)


# --- typed client models ------------------------------------------------------
#
# The helpers above take the MCP server's payloads, where a FRED observation
# arrives as a dict whose missing values have already been mapped to ``None``.
# The two below take navi's ``FredClient`` models instead, which keep FRED's own
# shape: ``Observation.value`` is the string the vendor sent, and a missing
# period is the single character ".". They are additions, not replacements, so
# notebooks/fred/client.ipynb can plot without the server running.


def fred_client_observations_to_arrays(
    response: "ObservationsResponse",
    max_show: int = 8,
) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Return ``(values, dates)`` from a client ``ObservationsResponse``.

    Values arrive as strings and FRED writes a missing period as ".", so rows
    have to be filtered before anything can be plotted. Every dropped row is
    announced rather than quietly skipped: the total, split by reason, then up
    to ``max_show`` of the offending rows and a count of the rest. A plot with
    fewer points than the series carries, and no note saying so, is the specific
    thing this print exists to prevent.

    Both return values are numpy arrays because matplotlib takes ArrayLike, and
    a plain ``list[datetime]`` is not one. The ``(values, dates)`` order matches
    ``fred_observations_to_arrays`` and ``lib.plots.curve(y, x)``.
    """
    points: list[tuple[datetime, float]] = []
    sentinel: list[Any] = []
    unparsable: list[Any] = []

    for observation in response.observations:
        raw = observation.value
        if raw is None or raw.strip() in ("", "."):
            sentinel.append(observation)
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            unparsable.append(observation)
            continue
        points.append((datetime.combine(observation.date, datetime.min.time()), value))

    points.sort(key=lambda point: point[0])
    values = numpy.array([point[1] for point in points], dtype=float)
    dates = numpy.array([point[0] for point in points])

    dropped = sentinel + unparsable
    total = len(response.observations)
    print(f"{len(points)} of {total} observations kept, {len(dropped)} dropped "
          f"({len(sentinel)} carrying FRED's '.' sentinel, "
          f"{len(unparsable)} otherwise non-numeric)")
    for observation in dropped[:max_show]:
        print(f"    dropped {observation.date}  value={observation.value!r}")
    if len(dropped) > max_show:
        print(f"    ... and {len(dropped) - max_show} further dropped rows")
    return values, dates


def plot_fred_client_series(
    values: numpy.ndarray,
    dates: numpy.ndarray,
    series: "Series | None" = None,
    **kwargs: Any,
) -> None:
    """Plot arrays built by ``fred_client_observations_to_arrays``.

    Takes the arrays rather than the response so the drop report is printed
    once, by the conversion, instead of again here. ``series`` is a typed
    ``Series`` (``response.seriess[0]``), so the title and y-label come from
    FRED's own metadata; its titles are full descriptive sentences, so the title
    is shortened to fit the figure. Extra kwargs pass through to
    ``lib.plots.curve`` (``figsize``, ``ylim``, ``file_name``, ...).
    """
    # Imported lazily: lib.plots pulls in matplotlib and backtrader, which the
    # non-plotting notebooks shouldn't pay for on `import utils`.
    from lib.plots import curve

    title = series.title if series is not None else ""
    units = (series.units if series is not None else None) or "Value"
    kwargs.setdefault("title", textwrap.shorten(title, width=72, placeholder=" ..."))
    kwargs.setdefault("xlabel", "Date")
    kwargs.setdefault("ylabel", units)
    curve(values, dates, **kwargs)
