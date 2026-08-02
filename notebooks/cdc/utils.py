"""Helpers for exploring CDC (Socrata) data through the MCP server.

Mirrors notebooks/{fred,bls,bis}/utils.py: thin wrappers over the CDC MCP tools,
plus plotting. CDC datasets are **heterogeneous** -- each has its own
time/value/facet columns -- so the plotting helpers take explicit x/y field
names rather than assuming a fixed shape. The MCP server must be running (see
the README).
"""
from typing import Any
from datetime import datetime

import numpy

from lib.mcp_client import MCPClient, MCPClientConfig
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
    """Return a tool's payload from its MCP structuredContent, or raise.

    On failure, surfaces the tool's error text (e.g. an unknown tool because the
    running server predates it -- restart the MCP server) instead of a bare None.
    """
    content = getattr(result, "structuredContent", None)
    if content and "result" in content:
        return content["result"]
    blocks = getattr(result, "content", None) or []
    detail = " ".join(getattr(block, "text", "") for block in blocks).strip()
    if getattr(result, "isError", False) or detail:
        raise RuntimeError(f"MCP tool error: {detail or content!r}")
    raise RuntimeError(f"Unexpected MCP response: {content!r}")


async def list_categories(top: int | None = None) -> list[dict[str, Any]]:
    """Print and return CDC catalog categories with dataset counts (the topic map)."""
    categories = _unwrap(await call_tool("cdc_categories"))["categories"]
    categories.sort(key=lambda category: -category["count"])
    for category in categories[:top]:
        print(f"  {category['count']:>5}  {category['category']}")
    return categories


async def list_tags(top: int | None = 30) -> list[dict[str, Any]]:
    """Print and return CDC catalog tags with dataset counts (finer-grained topics)."""
    tags = _unwrap(await call_tool("cdc_tags"))["tags"]
    tags.sort(key=lambda tag: -tag["count"])
    for tag in tags[:top]:
        print(f"  {tag['count']:>5}  {tag['tag']}")
    return tags


async def discover(
    query: str = "", category: str | None = None, limit: int = 10
) -> list[dict[str, Any]]:
    """Search the CDC catalog by keyword and/or category; print + return datasets."""
    datasets = _unwrap(await call_tool(
        "cdc_discover", {"query": query, "category": category, "limit": limit}
    ))["datasets"]
    for dataset in datasets:
        print(f"{dataset['id']:14s} {dataset.get('name', '')}")
    return datasets


async def show_columns(dataset_id: str) -> list[dict[str, Any]]:
    """Print and return a dataset's columns (field name, type, label).

    CDC datasets differ wildly, so inspect columns before querying to learn the
    time / value / facet fields.
    """
    dataset = _unwrap(await call_tool("cdc_dataset_columns", {"dataset_id": dataset_id}))
    print(f"{dataset['id']}: {dataset.get('name', '')}")
    for col in dataset["columns"]:
        print(f"  {col['field_name']:32s} {col.get('data_type', ''):8s} {col.get('name', '')}")
    return dataset["columns"]


async def get_rows(
    dataset_id: str,
    where: str | None = None,
    select: str | None = None,
    order: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Fetch rows from a dataset via SoQL. Returns the raw string-valued rows."""
    return _unwrap(await call_tool(
        "cdc_series_data",
        {"dataset_id": dataset_id, "where": where, "select": select,
         "order": order, "limit": limit},
    ))["rows"]


def _to_date(value: Any) -> datetime:
    """Parse a CDC time value ('YYYY' or 'YYYY-MM') into a datetime."""
    text = str(value).strip()[:7]
    if "-" in text:
        year, month = text.split("-")[:2]
        return datetime(int(year), int(month), 1)
    return datetime(int(text[:4]), 1, 1)


def cdc_rows_to_arrays(
    rows: list[dict[str, Any]], x_field: str, y_field: str
) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Return ``(values, dates)`` from rows, sorted by time, skipping blanks.

    ``x_field`` is the time column (e.g. 'year'); ``y_field`` the numeric value
    (e.g. 'average_life_expectancy'). Socrata values are strings, so ``y`` is
    cast to float and non-numeric / suppressed cells are dropped.
    """
    points: list[tuple[datetime, float]] = []
    for row in rows:
        x, y = row.get(x_field), row.get(y_field)
        if x in (None, "") or y in (None, ""):
            continue
        try:
            points.append((_to_date(x), float(y)))
        except (ValueError, TypeError):
            continue
    points.sort(key=lambda point: point[0])
    dates = numpy.array([point[0] for point in points])
    values = numpy.array([point[1] for point in points])
    return values, dates


def plot_cdc_series(
    rows: list[dict[str, Any]], x_field: str, y_field: str, **kwargs: Any
) -> None:
    """Plot a CDC series (one x/y column pair) with the project style.

    Extra kwargs pass through to ``lib.plots.curve`` (title, ylabel, ...).
    """
    from lib.plots import curve  # lazy: pulls in matplotlib

    values, dates = cdc_rows_to_arrays(rows, x_field, y_field)
    label = y_field.replace("_", " ").title()
    kwargs.setdefault("title", label)
    kwargs.setdefault("xlabel", "Year")
    kwargs.setdefault("ylabel", label)
    curve(values, dates, **kwargs)


# Facet-wide aggregate labels (e.g. the 'All Races' / 'Both Sexes' totals). They
# are dropped by default when breaking a facet out so the per-group lines stay
# readable; pass ``exclude=()`` to keep one as a labeled reference baseline.
_CDC_AGGREGATE_LABELS = frozenset(
    {"All Races", "Both Sexes", "All", "Total", "All persons", "All ages"}
)


def plot_cdc_series_by(
    rows: list[dict[str, Any]],
    x_field: str,
    y_field: str,
    group_field: str,
    exclude: Any = _CDC_AGGREGATE_LABELS,
    **kwargs: Any,
) -> None:
    """Overlay one labeled line per ``group_field`` value on a shared scale.

    Splits ``rows`` into series by their ``group_field`` value (e.g. 'sex' or
    'race') and plots them together with ``lib.plots.comparison`` -- one axes,
    shared y-scale, an auto legend, and the project's brand color cycle. Each
    series is built with ``cdc_rows_to_arrays``, so Socrata strings are cast to
    float and blank / suppressed cells are dropped (a group left with no numeric
    points is skipped); per-group x arrays are passed so series of unequal length
    -- e.g. a facet whose 2018 cell is suppressed -- still line up on the time
    axis.

    Facet-wide aggregate rows (``exclude``, default the 'All Races' / 'Both
    Sexes' style totals) are omitted so the breakdown stays readable; pass
    ``exclude=()`` to keep one as a labeled reference baseline. Group order
    follows first appearance in ``rows``, so control it with the SoQL ``order``.

    Extra kwargs pass through to ``comparison`` (title, ylabel, legend_loc, ...).
    """
    from lib.plots import comparison  # lazy: pulls in matplotlib

    excluded = set(exclude or ())
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = row.get(group_field)
        if key in (None, "") or key in excluded:
            continue
        groups.setdefault(key, []).append(row)

    labels: list[str] = []
    xs: list[numpy.ndarray] = []
    ys: list[numpy.ndarray] = []
    for key, group_rows in groups.items():
        values, dates = cdc_rows_to_arrays(group_rows, x_field, y_field)
        if len(values) == 0:
            continue
        labels.append(key)
        ys.append(values)
        xs.append(dates)

    if not ys:
        raise ValueError(f"No plottable series for group_field={group_field!r}")

    axis_label = y_field.replace("_", " ").title()
    kwargs.setdefault("title", axis_label)
    kwargs.setdefault("xlabel", "Year")
    kwargs.setdefault("ylabel", axis_label)
    kwargs.setdefault("labels", labels)
    kwargs.setdefault("legend_title", group_field.replace("_", " ").title())
    comparison(ys, xs, **kwargs)
