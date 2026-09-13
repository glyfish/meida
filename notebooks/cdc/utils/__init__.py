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
from environment import get_mcp_url

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


def _unwrap(result: Any) -> Any:
    """Return a tool's payload from its MCP structuredContent, or raise.

    On failure, surfaces the tool's error text (e.g. an unknown tool because the
    running server predates it -- restart the MCP server) instead of a bare None.
    """
    content = getattr(result, "structuredContent", None)
    if content and not getattr(result, "isError", False):
        # FastMCP derives structuredContent from the tool's return annotation:
        # a plain Mapping is wrapped as {"result": ...}, while a pydantic model
        # puts its own fields at the top level. Handle both.
        return content["result"] if set(content) == {"result"} else content
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


#: Facet keys the catalog carries. Used to reject a mistyped keyword rather
#: than silently forwarding it as a filter that matches nothing.
FACET_KEYS = {"state", "race", "sex", "age", "drug", "rate_type", "period",
              "geography", "measure"}


async def search_catalog(
    concept: str | None = None,
    dataset_id: str | None = None,
    limit: int = 20,
    verbose: bool = True,
    **facets: str,
) -> list[dict[str, Any]]:
    """Find which series exist, without fetching data.

    Covers both routes: Socrata series fetched live and WONDER/NVSR series
    served from Postgres. Each result's ``retrieval`` names the tool that
    fetches it, and its ``facets`` are the arguments that tool takes.

    ``limit`` is the only count that matters: it caps what the server returns
    *and* therefore what is printed. ``verbose=False`` keeps the full result
    but prints only the summary line, for a cell that wants to aggregate a
    large result rather than list it.
    """
    # A typo'd keyword would otherwise land in **facets and be sent as a filter
    # for a facet nobody publishes, which matches nothing and looks like "there
    # is no such data" rather than "you misspelled an argument".
    unknown = set(facets) - FACET_KEYS
    if unknown:
        raise TypeError(
            f"unknown argument(s): {', '.join(sorted(unknown))}. "
            f"Facets are {', '.join(sorted(FACET_KEYS))}; "
            f"other options are concept, dataset_id, limit, verbose."
        )
    args: dict[str, Any] = {"limit": limit}
    if concept:
        args["concept"] = concept
    if dataset_id:
        args["dataset_id"] = dataset_id
    if facets:
        args["facets"] = facets
    result = _unwrap(await call_tool("series_catalog_search", args))
    entries = result["entries"]
    # total counts every match; returned is capped by `limit`, so the two differ
    # exactly when the result was truncated.
    truncated = "" if result["total"] == result["returned"] else f", limit={limit}"
    print(f"  {result['total']} matching series ({result['returned']} returned{truncated})")
    if verbose:
        for entry in entries:
            tool = (entry.get("retrieval") or {}).get("tool") or "(no single-call route)"
            print(f"    {entry['series_id']}")
            print(f"      {entry['facets']} -> {tool}")
    return entries


async def catalog_concepts(top: int | None = None) -> list[dict[str, Any]]:
    """Print and return what the catalog measures, with series counts."""
    concepts = _unwrap(await call_tool("series_catalog_concepts", {}))["concepts"]
    for c in concepts[:top]:
        print(f"  {c['series_count']:>5}  {c['concept']:26} {c['dataset_id'] or '-'}")
    return concepts


async def get_dataset_facets(
    dataset_id: str, concept: str | None = None
) -> dict[str, list[str]]:
    """Print and return the facet tokens one dataset defines.

    The tool's enums are the union across datasets; this is the subset that
    actually resolves for this one.
    """
    args = {"dataset_id": dataset_id}
    if concept:
        args["concept"] = concept
    facets = _unwrap(await call_tool("cdc_dataset_facets", args))["facets"]
    for name, values in sorted(facets.items()):
        print(f"  {name:10} {values}")
    return facets


def _repo_root() -> str:
    """meida's repo root, so ``clients`` resolves from a notebook kernel."""
    from pathlib import Path
    return str(Path(__file__).resolve().parents[3])


async def query_rows(
    dataset_id: str,
    where: str | None = None,
    select: str | None = None,
    order: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Raw SoQL against one dataset, through ``CdcClient`` rather than MCP.

    ``get_rows`` goes over MCP and returns exactly ``{year, value}`` -- one
    series, its facets named rather than queried. That is deliberate: no SoQL
    crosses the wire, and the server owns each dataset's column names.

    Exploration needs the other thing: arbitrary columns, several series in one
    response, grouping by a column the tool has no argument for. SoQL still
    exists for that -- it just lives in the client now, which is the layer that
    always spoke it. Use this for a question the tool's facets cannot express,
    and ``get_rows`` for fetching a series someone will actually consume.
    """
    import sys
    if _repo_root() not in sys.path:
        sys.path.append(_repo_root())
    from clients import CdcClient   # lazy: only exploration notebooks need it

    async with CdcClient() as client:
        response = await client.query(
            dataset_id, where=where, select=select, order=order, limit=limit
        )
    return response.rows


async def get_rows(
    dataset_id: str,
    concept: str | None = None,
    *,
    state: str | None = None,
    race: str | None = None,
    sex: str | None = None,
    age: str | None = None,
    drug: str | None = None,
    rate_type: str | None = None,
    period: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Fetch one CDC series by naming its facets.

    The facet names are the catalog's ``facets`` metadata keys, so a value read
    off a discovered series can be passed straight back in. The server owns the
    column names and literals -- no SoQL crosses the wire.
    """
    args = {"dataset_id": dataset_id, "concept": concept, "state": state,
            "race": race, "sex": sex, "age": age, "drug": drug,
            "rate_type": rate_type, "period": period,
            "year_start": year_start, "year_end": year_end, "limit": limit}
    return _unwrap(await call_tool(
        "cdc_series_data", {k: v for k, v in args.items() if v is not None},
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


# --- MCP tool schemas --------------------------------------------------------


def _schema_type(spec: dict[str, Any]) -> str:
    """Render a JSON-schema property's type.

    An optional parameter (``str | None``) arrives as
    ``anyOf: [{"type": "string"}, {"type": "null"}]`` rather than a plain
    ``type``, so reading ``spec["type"]`` alone shows nothing for exactly the
    parameters most worth documenting. Collapse the ``anyOf`` and drop the null
    arm -- optionality is already conveyed by the required/optional flag.
    """
    if "type" in spec:
        return str(spec["type"])
    arms = [a.get("type") for a in spec.get("anyOf", []) if a.get("type") != "null"]
    return "|".join(a for a in arms if a) or "?"


def _schema_enum(spec: dict[str, Any]) -> list[str] | None:
    """The accepted values, if the property constrains them.

    Worth surfacing separately from the type: a parameter typed ``string`` with
    an 8-value enum is a very different thing to call than a free string, and an
    optional one hides its enum inside the ``anyOf`` arm.
    """
    if "enum" in spec:
        return list(spec["enum"])
    if "const" in spec:                 # pydantic renders a 1-value Literal as const
        return [spec["const"]]
    for arm in spec.get("anyOf", []):
        if "enum" in arm:
            return list(arm["enum"])
        if "const" in arm:
            return [arm["const"]]
    return None


async def show_tool_schema(tool_name: str) -> dict[str, Any]:
    """Print and return one tool's input schema.

    The schema is what an MCP consumer reads to know how to call a tool, so it
    is the fastest way to see a tool's arguments without leaving the notebook.
    """
    async with MCPClient(config) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
    if tool_name not in tools:
        raise RuntimeError(
            f"no tool {tool_name!r} on the server. Available: {sorted(tools)}"
        )
    schema = tools[tool_name].inputSchema or {}
    required = set(schema.get("required") or [])
    print(f"{tool_name}\n  {tools[tool_name].description}\n")
    for name, spec in (schema.get("properties") or {}).items():
        flag = "required" if name in required else "optional"
        default = spec.get("default")
        suffix = "" if default is None else f", default={default!r}"
        print(f"  {name:12} {_schema_type(spec):8} {flag}{suffix}")
        values = _schema_enum(spec)
        if values:
            shown = ", ".join(values[:12])
            more = f", ... ({len(values)} total)" if len(values) > 12 else ""
            print(f"  {'':12} {'':8} one of: {shown}{more}")
    return schema


# --- stored series (CDC WONDER and NVSR, served from meida's database) --------


async def list_stored_series(source: str | None = None) -> list[dict[str, Any]]:
    """List series held in meida's time-series database.

    ``source`` filters to ``cdc_wonder`` or ``cdc_nvsr``; omit it for both.
    Observations are excluded -- use :func:`get_stored_series` for those.
    """
    args = {"source": source} if source else {}
    return _unwrap(await call_tool("timeseries_source_list", args))["series"]


async def get_stored_series(source: str, native_id: str) -> dict[str, Any]:
    """Fetch one stored series in full, with its observations."""
    return _unwrap(
        await call_tool(
            "timeseries_source_data", {"source": source, "native_id": native_id}
        )
    )


async def list_stale_series(source: str | None = None) -> list[dict[str, Any]]:
    """List stored series past their refresh horizon.

    These sources have no live API, so refreshing is a deliberate act -- this is
    the query that answers "what needs updating?" without a polling process.
    """
    args = {"source": source} if source else {}
    return _unwrap(await call_tool("timeseries_source_stale", args))["series"]


def stored_series_to_arrays(
    series: dict[str, Any],
) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Split a stored series into plottable ``(dates, values)``.

    Values arrive as strings (the shared observation contract) and may be
    ``None`` where a source withheld a figure, so both are handled here rather
    than at every call site.

    Returns numpy arrays, matching every other source's ``*_to_arrays``
    builder. It used to return plain lists, which meant each plotting call site
    had to convert -- matplotlib takes ArrayLike, and ``list[datetime]`` is not.
    """
    dates: list[datetime] = []
    values: list[float] = []
    for obs in series.get("observations", []):
        raw = obs.get("value")
        if raw in (None, "", "."):
            continue
        dates.append(_to_date(obs["date"]))
        values.append(float(raw))
    return numpy.array(dates), numpy.array(values)


# --- column values -----------------------------------------------------------

#: Socrata caps ``cachedContents.top`` at 20 entries. A column reporting exactly
#: this many may have more values that were not returned.
_TOP_CAP = 20


def plot_cdc_arrays(values: numpy.ndarray, dates: numpy.ndarray, **kwargs: Any) -> None:
    """Plot arrays that a caller has already built and reported on.

    :func:`plot_cdc_series` converts rows itself, which is right when the
    conversion has nothing to say. When the caller wants to disclose what was
    dropped first -- via :func:`cdc_rows_to_arrays_with_dropped` -- it needs to
    do the conversion, so this takes the arrays and keeps the plotting in a
    helper rather than putting a bare ``curve`` call in a notebook cell.
    """
    from lib.plots import curve  # lazy: pulls in matplotlib

    kwargs.setdefault("xlabel", "Year")
    curve(values, dates, **kwargs)


def plot_stored_series(series: dict[str, Any], **kwargs: Any) -> None:
    """Plot one stored (WONDER or NVSR) series with the project style.

    The counterpart to :func:`plot_cdc_series`, which takes raw Socrata rows.
    Stored series already carry ISO dates and a units label, so the axes label
    themselves. Extra kwargs pass through to ``lib.plots.curve``.
    """
    from lib.plots import curve  # lazy: pulls in matplotlib

    dates, values = stored_series_to_arrays(series)
    kwargs.setdefault("title", series.get("title") or series.get("native_id"))
    kwargs.setdefault("xlabel", "Year")
    kwargs.setdefault("ylabel", series.get("units") or "value")
    curve(values, dates, **kwargs)


def plot_stored_series_group(
    series_list: list[dict[str, Any]],
    labels: list[str],
    title: str,
    ylabel: str | None = None,
    figsize: tuple[int, int] = (10, 5),
) -> None:
    """Overlay several stored series on one axis.

    Used where the comparison *is* the point -- the despair components, or life
    expectancy across race groups -- which ``curve`` does not cover since it
    draws a single line.
    """
    from matplotlib import pyplot

    pyplot.figure(figsize=figsize)
    for series, label in zip(series_list, labels):
        dates, values = stored_series_to_arrays(series)
        pyplot.plot(dates, values, label=label, linewidth=2)
    # str() the units before the fallback chain: the series dicts are
    # dict[str, Any], so .get() widens to Any | None and the whole expression
    # would type as possibly-None where pyplot.ylabel wants a str.
    units = str(series_list[0].get("units") or "") if series_list else ""
    pyplot.ylabel(ylabel or units or "value")
    pyplot.title(title)
    if series_list:      # legend() warns when there is nothing labelled to show
        pyplot.legend()


async def column_values(dataset_id: str, column: str) -> list[dict[str, Any]]:
    """Every distinct value of one column, with row counts.

    A ``$group=`` query, so the result is exhaustive where
    ``cachedContents.top`` is only the 20 most common. Returns ``[]`` when the
    column holds no data -- an empty column is a fact worth reporting, not an
    error, and a caller filtering on it should see zero rather than a failure.
    """
    rows = _unwrap(await call_tool("cdc_series_data", {
        "dataset_id": dataset_id,
        "select": f"{column}, count(*) AS count",
        "order": f"{column}",
        "limit": 5000,
    }))["rows"]
    return [
        {"value": r.get(column), "count": int(r.get("count", 0))}
        for r in rows
        if r.get(column) is not None
    ]


async def show_column_values(
    dataset_id: str, fill_capped: bool = True
) -> dict[str, list[dict[str, Any]]]:
    """Print each text column's values, filling in any Socrata truncated.

    ``cachedContents.top`` is free but caps at 20, and ``cardinality`` cannot be
    trusted to say whether that is the whole set -- on ``xkb8-kh2a`` every
    column reports the row count instead. So any column sitting exactly at the
    cap is re-queried with :func:`column_values` to get the real list; the rest
    are reported straight from the cached metadata at no extra cost.
    """
    dataset = _unwrap(await call_tool("cdc_dataset_columns", {"dataset_id": dataset_id}))
    out: dict[str, list[dict[str, Any]]] = {}

    for col in dataset["columns"]:
        name, kind = col["field_name"], col.get("data_type")
        cached = col.get("cached_top") or []
        if kind != "text":
            lo, hi = col.get("cached_smallest"), col.get("cached_largest")
            print(f"  {name:26} {kind:8} range {lo} .. {hi}")
            continue

        if fill_capped and len(cached) >= _TOP_CAP:
            values = await column_values(dataset_id, name)
            note = f"{len(values)} values (queried; cached list was capped at {_TOP_CAP})"
        else:
            values = [{"value": t["item"], "count": int(t["count"])} for t in cached]
            note = f"{len(values)} values (cached)"

        out[name] = values
        preview = ", ".join(str(v["value"]) for v in values[:6])
        print(f"  {name:26} {kind:8} {note}\n{'':38}{preview}"
              f"{' ...' if len(values) > 6 else ''}")
    return out


# --- direct-client helpers (notebooks/cdc/client.ipynb) -----------------------
#
# The two builders above (:func:`cdc_rows_to_arrays`,
# :func:`stored_series_to_arrays`) drop unusable cells silently, which is right
# for a plotting wrapper but wrong for a notebook that wants to *say* what it
# dropped. These return the discarded rows alongside the arrays so a caller can
# print them; the originals are untouched so their notebooks' output is stable.


def cdc_rows_to_arrays_with_dropped(
    rows: list[dict[str, Any]], x_field: str, y_field: str
) -> tuple[numpy.ndarray, numpy.ndarray, list[dict[str, Any]]]:
    """``(values, dates, dropped)`` from raw Socrata rows, sorted by time.

    Same parse as :func:`cdc_rows_to_arrays` -- Socrata returns every value as a
    string, so ``y_field`` is cast to float -- but the rows that could not be
    used (missing time, missing value, or a non-numeric cell such as a
    suppression marker) are returned rather than discarded, so the caller can
    report them. Arrays, not lists: matplotlib takes ArrayLike and
    ``list[datetime]`` is not.
    """
    points: list[tuple[datetime, float]] = []
    dropped: list[dict[str, Any]] = []
    for row in rows:
        x, y = row.get(x_field), row.get(y_field)
        if x in (None, "") or y in (None, ""):
            dropped.append(row)
            continue
        try:
            points.append((_to_date(x), float(y)))
        except (ValueError, TypeError):
            dropped.append(row)
    points.sort(key=lambda point: point[0])
    dates = numpy.array([point[0] for point in points])
    values = numpy.array([point[1] for point in points])
    return values, dates, dropped


def wonder_rows_to_arrays(
    rows: list[dict[str, Any]], field: str = "age_adjusted_rate"
) -> tuple[numpy.ndarray, numpy.ndarray, list[dict[str, Any]]]:
    """``(values, dates, dropped)`` from WONDER rows grouped by year.

    Takes ``WonderRow`` dicts (``row.model_dump()``, or a cached pull read back
    from ``data/wonder/``). WONDER writes ``None`` into a numeric cell it
    suppresses or marks unreliable, so those rows are collected into ``dropped``
    instead of being plotted as a gap the reader cannot see. ``year`` becomes a
    January-1 ``datetime`` to match every other source's date axis.
    """
    points: list[tuple[datetime, float]] = []
    dropped: list[dict[str, Any]] = []
    for row in rows:
        year, value = row.get("year"), row.get(field)
        if year in (None, "") or value is None:
            dropped.append(row)
            continue
        try:
            points.append((datetime(int(year), 1, 1), float(value)))
        except (ValueError, TypeError):
            dropped.append(row)
    points.sort(key=lambda point: point[0])
    dates = numpy.array([point[0] for point in points])
    values = numpy.array([point[1] for point in points])
    return values, dates, dropped
