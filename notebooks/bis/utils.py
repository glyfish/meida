"""Helpers for exploring BIS data through the MCP server.

Mirrors notebooks/fred/utils.py and notebooks/bls/utils.py: thin wrappers over
the BIS MCP tools, plus decoding (BIS returns dimension *codes*, decoded via the
data structure) and plotting. The MCP server must be running (see the README).
"""

import sys as _sys
from pathlib import Path as _Path

# meida's repo root, so `clients` resolves. The clients package used to live in
# navi (installed, hence importable from anywhere); it now sits beside
# mcp_server, which the notebooks' cwd does not reach. Anchored to __file__
# rather than "../.." so it holds whatever directory the kernel started in.
_sys.path.append(str(_Path(__file__).resolve().parents[2]))

from typing import Any, TYPE_CHECKING
from datetime import date, datetime
from pathlib import Path
import asyncio
import csv
import io
import random
import re

import numpy
import yaml

from lib.mcp_client import MCPClient, MCPClientConfig
from lib.utils import print_json_vertical
from environment import get_mcp_url

if TYPE_CHECKING:  # navi's pydantic models, imported for annotations only --
    from clients.models.bis import (  # importing clients at module scope
        BisDataflow,                      # would pull in every vendor client
        BisDataResponse,
        BisDataStructure,
        BisSeries,
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


def _unwrap(result: Any) -> Any:
    """Return a tool's payload from its MCP structuredContent, or raise.

    FastMCP derives structuredContent from the tool's return annotation: a
    plain Mapping is wrapped as ``{"result": ...}``, while a pydantic model
    puts its own fields at the top level. Handle both -- the tools moved to
    declared response models, so the wrapper is gone for most of them.
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
        if "enum" in spec:  # nothing in the BIS tools constrains its values --
            print(f"  {'':14} {'':8} one of: {spec['enum']}")  # that is the point


async def show_tool_schema(tool_name: str, output: bool = False) -> dict[str, Any]:
    """Print and return one tool's argument schema.

    ``output=True`` also prints the response schema. The argument half is the
    one that matters for BIS: it shows that ``key`` is an unconstrained string,
    which is why the data structure (not the schema) is where a caller learns
    what a key may contain.
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


def dsd_id_for_flow(flows: list[dict[str, Any]], flow_id: str) -> str:
    """Return a dataflow's data-structure id, read from its ``structure`` urn.

    Worth reading rather than guessing: the DSD id only *usually* looks like the
    flow id with ``WS_`` swapped for ``BIS_``. WS_CBTA is served by ``CBTA``,
    WS_SPP by ``BIS_SELECTED_PP``, and WS_CPP/WS_DPP share ``BIS_PROP_PRICES``.
    The urn each dataflow carries is authoritative.
    """
    for flow in flows:
        if flow["id"] == flow_id:
            dsd_id = _dsd_id_from_structure(flow.get("structure"))
            if not dsd_id:
                raise RuntimeError(f"{flow_id} carries no structure urn")
            print(f"{flow_id}: {flow.get('name')}")
            print(f"  structure: {flow.get('structure')}")
            print(f"  dsd_id:    {dsd_id}")
            return dsd_id
    raise RuntimeError(f"no dataflow {flow_id!r} in the {len(flows)} listed")


def find_codes(
    dsd: dict[str, Any],
    dimension: str,
    match: str | None = None,
    limit: int = 10,
) -> dict[str, str]:
    """Print the codes one key position accepts, optionally filtered.

    Resolves the dimension to its codelist through the DSD, which is the only
    way to learn what a position of a series key may hold. Needs a structure
    fetched with ``include_codes=True``; ``match`` is a case-insensitive
    substring tested against both code and label.
    """
    dims = {d["id"]: d for d in dsd["dimensions"]}
    if dimension not in dims:
        raise RuntimeError(f"{dimension!r} is not a dimension of {dsd['id']}: {list(dims)}")
    codelist_id = dims[dimension].get("codelist_id")
    codelist = dsd.get("codelists", {}).get(codelist_id, {})
    codes = codelist.get("codes", {})
    if not codes:
        raise RuntimeError(
            f"{codelist_id} carries no codes -- refetch with include_codes=True"
        )
    hits = {
        code: label for code, label in codes.items()
        if not match or match.lower() in code.lower() or match.lower() in label.lower()
    }
    print(f"{dimension} -> {codelist_id} ({codelist.get('code_count')} codes"
          f"{f', {len(hits)} matching {match!r}' if match else ''})")
    for code, label in list(hits.items())[:limit]:
        print(f"  {code:8} {label}")
    if len(hits) > limit:
        print(f"  ... {len(hits) - limit} more")
    return hits


def show_series(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Print each series in a response: key, title, decoded codes, coverage.

    The key printed back is longer than the key requested: BIS repeats the
    attribute columns (UNIT_MEASURE and friends) on every CSV row, so they ride
    along in ``dimensions`` next to the real key positions.
    """
    for series in data.get("series", []):
        periods = sorted(obs["time_period"] for obs in series.get("observations", [])
                         if obs.get("value") is not None)
        labels = ", ".join(f"{dim}={label}" for dim, label in series.get("labels", {}).items())
        print(f"{series['key']}  {series.get('title') or ''}")
        print(f"  decoded:  {labels or series.get('dimensions')}")
        print(f"  unit:     {series.get('unit_label') or series.get('unit_measure')}")
        if periods:
            print(f"  coverage: {periods[0]} -> {periods[-1]} ({len(periods)} observations)")
    return data.get("series", [])


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


def build_bis_records(
    flow: str, dsd: Any, data: Any, flow_name: str | None = None,
) -> list[dict[str, Any]]:
    """Build series-metadata records for one dataflow from its DSD + full data.

    Keys/facets/title come from the DSD dimensions -- not the client's ``key``,
    which is polluted by attribute columns (e.g. ``TITLE_TS``) on multi-attribute
    flows. When a flow carries no ``TITLE``/``TITLE_TS`` attribute, the title is
    synthesized from ``flow_name`` + the decoded facet labels (mirroring the BLS
    catalog) so every series has embeddable text. Coverage is derived from the
    observations, then discarded: the catalog is metadata only.
    """
    flow_name = flow_name or flow
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
        title = dm.get("TITLE") or dm.get("TITLE_TS")
        if not title:  # many flows carry no title attr -> synthesize from facets
            labels = ", ".join(str(v) for v in facets.values())
            title = f"{flow_name} — {labels}" if labels else flow_name
        records.append({
            "series_id": f"{flow}/{key}",
            "key": key,
            "title": title,
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
    from clients import BisClient  # lazy: only needed for generation

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
            records = build_bis_records(flow, dsd, data,
                                        flow_name=meta.name if meta else None)
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


# --- Direct-client helpers (navi BisClient, no MCP server) -------------------
#
# The helpers above take the MCP tools' JSON dicts; these take navi's pydantic
# models, whose fields are attributes rather than keys. They are kept as a
# separate family rather than made polymorphic so neither shape has to be
# sniffed at runtime, and so nothing the MCP notebooks already print changes.
#
# Print-only helpers return None on purpose: client.ipynb calls them as bare
# expressions, and a returned value would echo underneath the printed output.


def show_client_dataflows(
    flows: "list[BisDataflow]", match: str | None = None
) -> None:
    """Print id and name for each dataflow from ``BisClient.get_dataflows``.

    ``match`` is a case-insensitive substring tested against id and name.
    """
    hits = [
        flow for flow in flows
        if not match
        or match.lower() in flow.id.lower()
        or match.lower() in (flow.name or "").lower()
    ]
    for flow in hits:
        print(f"{flow.id:22s} {flow.name or ''}")
    suffix = f" matching {match!r}" if match else ""
    print(f"\n{len(hits)} of {len(flows)} dataflows{suffix}")


def dsd_id_for_dataflow(flows: "list[BisDataflow]", flow_id: str) -> str:
    """Return a dataflow model's data-structure id, read from its ``structure`` urn.

    The model-taking twin of :func:`dsd_id_for_flow`. Worth reading rather than
    guessing: the DSD id only *usually* looks like the flow id with ``WS_``
    swapped for ``BIS_``.
    """
    for flow in flows:
        if flow.id == flow_id:
            dsd_id = _dsd_id_from_structure(flow.structure)
            if not dsd_id:
                raise RuntimeError(f"{flow_id} carries no structure urn")
            print(f"{flow_id}: {flow.name}")
            print(f"  structure: {flow.structure}")
            print(f"  dsd_id:    {dsd_id}")
            return dsd_id
    raise RuntimeError(f"no dataflow {flow_id!r} in the {len(flows)} listed")


def show_client_datastructure(dsd: "BisDataStructure") -> None:
    """Print a data structure's dimensions (in key order) and codelist sizes.

    Unlike the ``bis_datastructure`` tool, the client fills every codelist in,
    so the counts here are of codes actually in hand.
    """
    print(f"{dsd.id}: {dsd.name or ''}")
    dimensions = sorted(dsd.dimensions, key=lambda d: d.position or 0)
    print("dimensions (key order):", [d.id for d in dimensions])
    for dimension in dimensions:
        print(f"  {dimension.position}. {dimension.id:16s} -> {dimension.codelist_id}")
    for name, codelist in dsd.codelists.items():
        print(f"  {name:22s} {len(codelist.codes)} codes")


def find_client_codes(
    dsd: "BisDataStructure",
    dimension: str,
    match: str | None = None,
    limit: int = 10,
) -> None:
    """Print the codes one key position accepts, optionally filtered.

    Resolves the dimension to its codelist through the DSD, which is the only
    way to learn what a position of a series key may hold. ``match`` is a
    case-insensitive substring tested against both code and label.
    """
    dimensions = {d.id: d for d in dsd.dimensions}
    if dimension not in dimensions:
        raise RuntimeError(
            f"{dimension!r} is not a dimension of {dsd.id}: {list(dimensions)}"
        )
    codelist_id = dimensions[dimension].codelist_id
    codelist = dsd.codelists.get(codelist_id) if codelist_id else None
    codes = codelist.codes if codelist else {}
    if not codes:
        raise RuntimeError(f"{codelist_id} carries no codes")
    hits = {
        code: label for code, label in codes.items()
        if not match or match.lower() in code.lower() or match.lower() in label.lower()
    }
    print(f"{dimension} -> {codelist_id} ({len(codes)} codes"
          f"{f', {len(hits)} matching {match!r}' if match else ''})")
    for code, label in list(hits.items())[:limit]:
        print(f"  {code:8} {label}")
    if len(hits) > limit:
        print(f"  ... {len(hits) - limit} more")


def client_unit_label(
    dsd: "BisDataStructure | None", series: "BisSeries"
) -> str | None:
    """Decode a series' ``UNIT_MEASURE`` code through the DSD's unit codelist.

    ``BisDataStructure.decode`` cannot do this: UNIT_MEASURE is an *attribute*
    of the series, not one of its key dimensions, so it appears in no
    ``dimensions`` entry. Its codelist is the unit one (CL_BIS_UNIT /
    CL_UNIT_MEASURE), never the multiplier (CL_UNIT_MULT).
    """
    if dsd is None or not series.unit_measure:
        return None
    for codelist_id, codelist in dsd.codelists.items():
        if "UNIT" in codelist_id and "MULT" not in codelist_id:
            return codelist.codes.get(series.unit_measure)
    return None


def show_client_series(
    data: "BisDataResponse", dsd: "BisDataStructure | None" = None
) -> None:
    """Print each series in a ``BisDataResponse``: key, decoded codes, coverage.

    The key printed back is longer than the key requested: BIS repeats the
    attribute columns (UNIT_MEASURE and friends) on every CSV row, so they ride
    along in ``dimensions`` next to the real key positions.
    """
    for series in data.series:
        periods = sorted(
            obs.time_period for obs in series.observations if obs.value is not None
        )
        labels = ", ".join(
            f"{dimension.id}={dsd.decode(dimension.id, series.dimensions[dimension.id])}"
            for dimension in (dsd.dimensions if dsd else [])
            if dimension.id in series.dimensions
        )
        print(f"{series.key}  {series.title or ''}")
        print(f"  decoded:  {labels or series.dimensions}")
        print(f"  unit:     {client_unit_label(dsd, series) or series.unit_measure}")
        if periods:
            print(f"  coverage: {periods[0]} -> {periods[-1]} "
                  f"({len(periods)} observations)")


def client_series_to_arrays(
    series: "BisSeries", verbose: bool = True
) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Return ``(values, dates)`` as numpy arrays, chronologically.

    Observations with no value, a non-finite value, or an unparseable period are
    dropped -- and reported, so a plot that shows fewer points than the series
    holds says so out loud rather than quietly.
    """
    kept: list[tuple[datetime, float]] = []
    dropped: list[tuple[Any, str]] = []
    for obs in series.observations:
        if obs.value is None or not numpy.isfinite(obs.value):
            dropped.append((obs, "no numeric value"))
            continue
        try:
            when = bis_period_to_date(obs.time_period)
        except (ValueError, IndexError):
            dropped.append((obs, "unparseable time_period"))
            continue
        kept.append((when, float(obs.value)))
    kept.sort(key=lambda point: point[0])

    if verbose:
        print(f"{len(series.observations)} observations, "
              f"{len(kept)} plotted, {len(dropped)} dropped")
        for obs, reason in dropped[:10]:
            print(f"  dropped {obs.time_period!r} value={obs.value!r} "
                  f"status={obs.status!r} ({reason})")
        if len(dropped) > 10:
            print(f"  ... {len(dropped) - 10} more")

    values = numpy.array([point[1] for point in kept])
    dates = numpy.array([point[0] for point in kept])
    return values, dates


def plot_client_series(
    series: "BisSeries", dsd: "BisDataStructure | None" = None, **kwargs: Any
) -> None:
    """Plot one ``BisSeries`` with the project style.

    Passing the DSD labels the y-axis with the decoded unit ("Per cent per
    year") instead of its code (368). Extra kwargs pass through to
    ``lib.plots.curve``.
    """
    # Lazy import: lib.plots pulls in matplotlib, unneeded for pure data work.
    from lib.plots import curve

    values, dates = client_series_to_arrays(series)
    kwargs.setdefault("title", series.title or series.key)
    kwargs.setdefault("xlabel", "Date")
    kwargs.setdefault(
        "ylabel",
        client_unit_label(dsd, series) or series.unit_measure or "Value",
    )
    curve(values, dates, **kwargs)


def first_csv_row(text: str) -> dict[str, str]:
    """Parse the first data row of a BIS CSV response into a column -> value dict.

    Used only to put the raw payload next to the typed model: it keeps the
    notebook from splitting on commas by hand, which a quoted free-text column
    (COMPILATION, TITLE) would break.
    """
    rows = csv.DictReader(io.StringIO(text))
    for row in rows:
        return {key: value for key, value in row.items() if key is not None}
    return {}
