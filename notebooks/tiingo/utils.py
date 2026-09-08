"""Helpers for exploring Tiingo data through the MCP server.

Mirrors ``notebooks/{fred,bls,bis,cdc}/utils.py``: thin wrappers over the
Tiingo MCP tools plus the discovery helpers, so the notebook can show what the
server publishes rather than only what ``TiingoClient`` returns.

The distinction matters here more than elsewhere. Tiingo's wire format is
camelCase (``adjClose``, ``divCash``, ``splitFactor``, ``exchangeCode``), and
navi's models carry those as pydantic *aliases* so they can parse it. The MCP
tools do not publish them: they return meida's own response models, so a price
row reaches a consumer as ``adj_close``/``div_cash``/``split_factor`` with an
ISO ``date`` string. Calling both paths side by side is the clearest way to see
where that translation happens.

The MCP server must be running (see the README).
"""

import sys as _sys
from pathlib import Path as _Path

# meida's repo root, so `clients` resolves. The clients package used to live in
# navi (installed, hence importable from anywhere); it now sits beside
# mcp_server, which the notebooks' cwd does not reach. Anchored to __file__
# rather than "../.." so it holds whatever directory the kernel started in.
_sys.path.append(str(_Path(__file__).resolve().parents[2]))

import math
from collections.abc import Sequence
from datetime import date, datetime
from numbers import Real
from typing import Any

import numpy
from pydantic import BaseModel

from clients import TiingoClient
from clients.models.tiingo import TiingoMeta, TiingoPriceSeries
from lib.mcp_client import MCPClient, MCPClientConfig
from lib.env import get_mcp_url
from lib.utils import print_json_vertical

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

    FastMCP derives structuredContent from the tool's return annotation: a
    plain Mapping is wrapped as ``{"result": ...}``, while a pydantic model puts
    its own fields at the top level. Handle both. On failure, surface the
    tool's error text (e.g. an unknown tool because the running server predates
    it -- restart the MCP server) rather than a bare None.
    """
    content = getattr(result, "structuredContent", None)
    if content and not getattr(result, "isError", False):
        return content["result"] if set(content) == {"result"} else content
    blocks = getattr(result, "content", None) or []
    detail = " ".join(getattr(block, "text", "") for block in blocks).strip()
    if getattr(result, "isError", False) or detail:
        raise RuntimeError(f"MCP tool error: {detail or content!r}")
    raise RuntimeError(f"Unexpected MCP response: {content!r}")


def _schema_type(spec: dict[str, Any]) -> str:
    """Render a JSON-schema property's type.

    An optional parameter (``str | None``) arrives as
    ``anyOf: [{"type": "string"}, {"type": "null"}]`` rather than a plain
    ``type``, so reading ``spec["type"]`` alone shows nothing for exactly the
    parameters most worth documenting.
    """
    if "type" in spec:
        return str(spec["type"])
    arms = [a.get("type") for a in spec.get("anyOf", []) if a.get("type") != "null"]
    return "|".join(a for a in arms if a) or "?"


def _schema_enum(spec: dict[str, Any]) -> list[str] | None:
    """The accepted values, if the property constrains them."""
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


def _print_properties(schema: dict[str, Any]) -> None:
    required = set(schema.get("required") or [])
    for name, spec in (schema.get("properties") or {}).items():
        flag = "required" if name in required else "optional"
        default = spec.get("default")
        suffix = "" if default is None else f", default={default!r}"
        print(f"  {name:14} {_schema_type(spec):8} {flag}{suffix}")
        description = spec.get("description")
        if description:
            print(f"  {'':14} {'':8} {description}")
        values = _schema_enum(spec)
        if values:
            shown = ", ".join(str(v) for v in values[:12])
            more = f", ... ({len(values)} total)" if len(values) > 12 else ""
            print(f"  {'':14} {'':8} one of: {shown}{more}")


async def show_tool_schema(tool_name: str, output: bool = True) -> dict[str, Any]:
    """Print and return one tool's schema.

    Shows the *output* schema as well as the input one. That is the half worth
    reading for Tiingo: it is what says a price row comes back as snake_case
    with an ISO date, rather than in Tiingo's own camelCase.
    """
    async with MCPClient(config) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
    if tool_name not in tools:
        raise RuntimeError(
            f"no tool {tool_name!r} on the server. Available: {sorted(tools)}"
        )
    tool = tools[tool_name]
    print(f"{tool_name}\n  {tool.description}\n")
    print("  -- arguments --")
    _print_properties(tool.inputSchema or {})
    if output and tool.outputSchema:
        print("\n  -- returns --")
        _print_properties(tool.outputSchema)
        for name, definition in (tool.outputSchema.get("$defs") or {}).items():
            print(f"\n  {name}:")
            _print_properties(definition)
    return tool.inputSchema or {}


async def get_series_info(ticker: str) -> dict[str, Any]:
    """Ticker metadata through MCP (``tiingo_series_info``)."""
    info = _unwrap(await call_tool("tiingo_series_info", {"ticker": ticker}))
    print(f"{info['ticker']} -- {info.get('name')}")
    print(f"  exchange: {info.get('exchange_code')}")
    print(f"  range:    {info.get('start_date')} -> {info.get('end_date')}")
    return info


async def get_price_series(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    show: int | None = 5,
) -> dict[str, Any]:
    """EOD prices through MCP (``tiingo_price_series``).

    ``count`` is how many rows Tiingo sent, so ``count != len(prices)`` means
    rows were dropped in mapping rather than never sent.
    """
    args: dict[str, Any] = {"ticker": ticker}
    if start_date:
        args["start_date"] = start_date
    if end_date:
        args["end_date"] = end_date
    series = _unwrap(await call_tool("tiingo_price_series", args))
    rows = series["prices"]
    print(f"{series['ticker']}: {len(rows)} rows (count={series['count']})")
    for row in rows[:show]:
        print(f"  {row['date']}  close={row['close']:>9.2f}  "
              f"adj_close={row['adj_close']:>12.4f}  vol={row['volume']}")
    if show is not None and len(rows) > show:
        print(f"  ... {len(rows) - show} more")
    return series


def price_series_to_arrays(
    series: dict[str, Any], field: str = "adj_close"
) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Return ``(values, dates)`` for one price field, chronologically.

    Rows with a null ``date`` are skipped: the tool publishes such a row with
    its prices rather than inventing a date, but there is nowhere to put it on
    a time axis. A null *value* is skipped for the same reason -- letting one
    through makes numpy fall back to ``dtype=object``, so the array stops being
    numeric and arithmetic on it silently misbehaves rather than raising.
    """
    points = [
        (datetime.fromisoformat(row["date"]), row[field])
        for row in series.get("prices") or []
        if row.get("date") is not None and row.get(field) is not None
    ]
    points.sort(key=lambda point: point[0])
    dates = numpy.array([point[0] for point in points])
    values = numpy.array([point[1] for point in points])
    return values, dates


def plot_price_series(
    series: dict[str, Any],
    fields: str | Sequence[str] = "adj_close",
    info: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    """Plot one or more price fields of a Tiingo EOD series with the project style.

    Defaults to ``adj_close``: it restates the history for splits and dividends,
    so it is the series returns are computed from. Pass several fields (e.g.
    ``("close", "adj_close")``) to see how far apart the two drift over a long
    window. The title comes from ``info`` (``tiingo_series_info``) when given,
    since the price payload carries the ticker but not the instrument's name.
    Extra kwargs pass through to ``lib.plots``.
    """
    # Imported lazily: lib.plots pulls in matplotlib, which the non-plotting
    # notebooks shouldn't pay for on `import utils`.
    from lib.plots import comparison, curve

    names = [fields] if isinstance(fields, str) else list(fields)
    ticker = series.get("ticker") or (info or {}).get("ticker") or ""
    title = (info or {}).get("name")
    kwargs.setdefault("title", f"{ticker} -- {title}" if title else ticker)
    kwargs.setdefault("xlabel", "Date")
    kwargs.setdefault("ylabel", "Price (USD)")

    if len(names) == 1:
        values, dates = price_series_to_arrays(series, names[0])
        curve(values, dates, **kwargs)
        return

    kwargs.setdefault("labels", names)
    arrays = [price_series_to_arrays(series, name) for name in names]
    comparison([values for values, _ in arrays], [dates for _, dates in arrays], **kwargs)


# ---------------------------------------------------------------------------
# Direct client (notebooks/tiingo/client.ipynb)
#
# The helpers above go through the MCP server and hand back plain dicts. The
# ones below call navi's ``TiingoClient`` directly and hand back the pydantic
# models, so a caller works with ``meta.start_date`` as a ``datetime.date`` and
# ``price.date`` as a ``datetime``, not with ISO strings. Kept separate rather
# than folded into the MCP helpers because the two return types are different
# and the notebooks that use them are different.
# ---------------------------------------------------------------------------


async def client_raw_meta(ticker: str) -> dict[str, Any]:
    """Print and return Tiingo's raw ``/daily/<ticker>`` payload.

    Reaches for the private ``_get`` on purpose: ``get_meta`` validates into
    ``TiingoMeta`` and the wire names are gone by the time it returns, so this
    is the only way to show ``exchangeCode``/``startDate``/``endDate`` beside
    the snake_case attributes they become.
    """
    async with TiingoClient() as client:
        raw = await client._get(f"/daily/{ticker}")
    print_json_vertical(raw)
    return raw


async def client_meta(ticker: str) -> TiingoMeta:
    """Print and return ticker metadata as a ``TiingoMeta`` (``get_meta``).

    The coverage window is the reason to call this first: a request outside it
    is not an error, just an empty list, which looks the same as a mistyped
    symbol. Types are printed alongside because they are what the model added.
    """
    async with TiingoClient() as client:
        meta = await client.get_meta(ticker)
    print(f"{meta.ticker} -- {meta.name}")
    print(f"  exchange_code: {meta.exchange_code}")
    print(f"  start_date:    {meta.start_date}  ({type(meta.start_date).__name__})")
    print(f"  end_date:      {meta.end_date}  ({type(meta.end_date).__name__})")
    return meta


async def client_raw_prices(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    show: int | None = 1,
) -> list[dict[str, Any]]:
    """Print and return raw ``/daily/<ticker>/prices`` rows.

    Note the request parameters are camelCase too (``startDate``/``endDate``);
    ``get_prices`` builds them from its snake_case keyword arguments.
    """
    params: dict[str, Any] = {}
    if start_date:
        params["startDate"] = start_date
    if end_date:
        params["endDate"] = end_date
    async with TiingoClient() as client:
        raw = await client._get(f"/daily/{ticker}/prices", params)
    print(f"{len(raw)} raw rows")
    for row in raw[: show or 0]:
        print_json_vertical(row)
    return raw


async def client_prices(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    show: int | None = 5,
) -> TiingoPriceSeries:
    """Print and return an EOD series as a ``TiingoPriceSeries`` (``get_prices``).

    ``price.date`` is a ``datetime`` here, so it formats and sorts without
    being parsed first -- the MCP tools publish the same field as an ISO
    string.
    """
    async with TiingoClient() as client:
        series = await client.get_prices(ticker, start_date=start_date, end_date=end_date)
    rows = series.prices
    print(f"{series.ticker}: {len(rows)} bars")
    for row in rows[: show or 0]:
        print(f"  {row.date:%Y-%m-%d}  close={row.close:>9.2f}  "
              f"adj_close={row.adj_close:>12.4f}  vol={row.volume}")
    if show is not None and len(rows) > show:
        print(f"  ... {len(rows) - show} more")
    return series


def show_field_aliases(model: type[BaseModel]) -> None:
    """Print each model attribute beside the wire field it parses.

    Print-only, so a bare call in a notebook shows the table and nothing else.
    A field with no alias is named the same on the wire; the aliased ones are
    where Tiingo's camelCase becomes navi's snake_case. The alias is also the
    *only* name accepted on input -- these models do not set
    ``populate_by_name`` -- so a row can be built from the payload but not from
    the attribute names it exposes.
    """
    print(f"{model.__name__}: attribute <- wire field")
    for name, field in model.model_fields.items():
        alias = field.alias
        marker = "  (aliased)" if alias else ""
        print(f"  {name:14} <- {alias or name}{marker}")


def client_series_to_arrays(
    series: TiingoPriceSeries, field: str = "adj_close"
) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Return ``(values, dates)`` for one price field of a typed series.

    Arrays rather than lists because matplotlib takes ArrayLike, and numeric
    rather than ``dtype=object`` because arithmetic on an object array
    misbehaves silently. Rows without a usable date, or whose value is missing,
    non-numeric or non-finite, cannot go on the axes -- they are dropped and
    reported, so a plot is never quietly shorter than the series it came from.
    """
    points: list[tuple[datetime, float]] = []
    dropped: list[tuple[Any, Any]] = []
    for row in series.prices:
        when = getattr(row, "date", None)
        value = getattr(row, field, None)
        usable = (
            isinstance(when, (datetime, date))
            and isinstance(value, Real)
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
        if usable:
            points.append((when, float(value)))
        else:
            dropped.append((when, value))
    points.sort(key=lambda point: point[0])
    print(f"{series.ticker} {field}: {len(points)} points, {len(dropped)} dropped")
    for when, value in dropped:
        print(f"  dropped: date={when!r} {field}={value!r}")
    dates = numpy.array([point[0] for point in points])
    values = numpy.array([point[1] for point in points], dtype=float)
    return values, dates


def plot_client_series(
    series: TiingoPriceSeries,
    field: str = "adj_close",
    meta: TiingoMeta | None = None,
    **kwargs: Any,
) -> None:
    """Plot one price field of a typed Tiingo series with the project style.

    Defaults to ``adj_close``: every bar restated for the splits and dividends
    that came after it, which is the series returns are computed from. The
    title takes the instrument's name from ``meta`` when given, since a price
    series carries the ticker but not the name. Extra kwargs pass through to
    ``lib.plots``.
    """
    # Imported lazily: lib.plots pulls in matplotlib, which the non-plotting
    # notebooks shouldn't pay for on `import utils`.
    from lib.plots import curve

    values, dates = client_series_to_arrays(series, field)
    name = meta.name if meta is not None else None
    kwargs.setdefault("title", f"{series.ticker} -- {name}" if name else series.ticker)
    kwargs.setdefault("xlabel", "Date")
    kwargs.setdefault("ylabel", f"{field} (USD)")
    curve(values, dates, **kwargs)
