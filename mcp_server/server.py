from __future__ import annotations
from typing import Any, Awaitable, Callable, Mapping
from lib.logger import get_logger

from mcp.server.fastmcp import FastMCP

from lib.clients import BisClient, BlsClient, CdcClient, FredClient, TiingoClient


logger = get_logger("meida.mcp")

server = FastMCP(
    name="mcp-server",
    instructions="Access curated Federal Reserve Economic Data (FRED) and Tiingo end-of-day price tools.",
    host="0.0.0.0",
    port=8080,
)


async def _call_fred(handler: Callable[[FredClient], Awaitable[Any]]) -> Mapping[str, Any]:
    """Create a FredClient, invoke the handler, and serialize the response."""
    async with FredClient() as client:
        payload = await handler(client)
    return _serialize(payload)


def _serialize(payload: Any) -> Mapping[str, Any]:
    """Normalize pydantic models (or mappings) into JSON-serializable dicts."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    raise TypeError("Tool response must be pydantic BaseModel or mapping")


async def _call_tiingo(handler: Callable[[TiingoClient], Awaitable[Any]]) -> Mapping[str, Any]:
    """Create a TiingoClient, invoke the handler, and serialize the response."""
    async with TiingoClient() as client:
        payload = await handler(client)
    return _serialize(payload)


async def _call_bls(handler: Callable[[BlsClient], Awaitable[Any]]) -> Mapping[str, Any]:
    """Create a BlsClient, invoke the handler, and serialize the response."""
    async with BlsClient() as client:
        payload = await handler(client)
    return _serialize(payload)


async def _call_bis(handler: Callable[[BisClient], Awaitable[Any]]) -> Mapping[str, Any]:
    """Create a BisClient, invoke the handler, and serialize the response."""
    async with BisClient() as client:
        payload = await handler(client)
    return _serialize(payload)


async def _call_cdc(handler: Callable[[CdcClient], Awaitable[Any]]) -> Mapping[str, Any]:
    """Create a CdcClient, invoke the handler, and serialize the response."""
    async with CdcClient() as client:
        payload = await handler(client)
    return _serialize(payload)


@server.tool(
    name="fred_category_children",
    description="List the child categories for a FRED category.",
)
async def list_category_children(category_id: int) -> Mapping[str, Any]:
    async def handler(client: FredClient) -> Any:
        return await client._get('/category/children', {'category_id': category_id})

    return await _call_fred(handler)


@server.tool(
    name="fred_category_series",
    description="List the series contained within a FRED category.",
)
async def list_category_series(
    category_id: int,
    limit: int | None = None,
    order_by: str | None = None,
) -> Mapping[str, Any]:
    async def handler(client: FredClient) -> Any:
        params: dict[str, Any] = {"category_id": category_id}
        if limit is not None:
            params["limit"] = limit
        if order_by:
            params["order_by"] = order_by
        return await client.get_category_series(**params)

    return await _call_fred(handler)


@server.tool(
    name="fred_series_info",
    description="Fetch metadata for a single FRED series.",
)
async def get_series_info(series_id: str) -> Mapping[str, Any]:
    async def handler(client: FredClient) -> Any:
        return await client.get_series(series_id)

    return await _call_fred(handler)


@server.tool(
    name="fred_series_observations",
    description="Return observations for a series (limit defaults to 100).",
)
async def get_series_observations(
    series_id: str,
    limit: int | None = 100,
    offset: int | None = 0,
    frequency: str | None = None,
    units: str | None = None,
) -> Mapping[str, Any]:
    async def handler(client: FredClient) -> Any:
        params: dict[str, Any] = {"series_id": series_id}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if frequency:
            params["frequency"] = frequency
        if units:
            params["units"] = units

        response = await client.get_series_observations(**params)
        total = response.count or 0
        returned = len(response.observations)
        effective_limit = limit if limit is not None else total
        effective_offset = offset or 0

        if (effective_offset + returned) < total:
            logger.warning(
                "Incomplete observations for %s (offset=%s, limit=%s, returned=%s, total=%s)",
                series_id,
                effective_offset,
                effective_limit,
                returned,
                total,
            )
        return response

    return await _call_fred(handler)


@server.tool(
    name="fred_series_updates",
    description="Return recently updated FRED series.",
)
async def get_series_updates(limit: int | None = 100, offset: int | None = 0) -> Mapping[str, Any]:
    async def handler(client: FredClient) -> Any:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if offset:
            params["offset"] = offset
        return await client.get_series_updates(**params)

    return await _call_fred(handler)


@server.tool(
    name="list_releases",
    description="List the series that belong to a FRED release.",
)
async def list_releases(limit: int | None = 100, order_by: str | None = None) -> Mapping[str, Any]:
    async def handler(client: FredClient) -> Any:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if order_by:
            params["order_by"] = order_by
        return await client.get_releases(**params)

    return await _call_fred(handler)


@server.tool(
    name="fred_release_series",
    description="List the series that belong to a FRED release.",
)
async def list_release_series(release_id: int, limit: int | None = 100) -> Mapping[str, Any]:
    async def handler(client: FredClient) -> Any:
        params: dict[str, Any] = {"release_id": release_id}
        if limit is not None:
            params["limit"] = limit
        return await client.get_release_series(**params)

    return await _call_fred(handler)


@server.tool(
    name="tiingo_series_info",
    description="Fetch metadata for a Tiingo ticker (ETF, mutual fund, or stock), including its available date range.",
)
async def get_tiingo_series_info(ticker: str) -> Mapping[str, Any]:
    async def handler(client: TiingoClient) -> Any:
        return await client.get_meta(ticker)

    return await _call_tiingo(handler)


@server.tool(
    name="tiingo_price_series",
    description=(
        "Return the end-of-day price series (OHLCV plus split/dividend-adjusted prices) for a "
        "Tiingo ticker. Provide start_date/end_date as YYYY-MM-DD for a range; omit for the latest day."
    ),
)
async def get_tiingo_price_series(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    resample_freq: str | None = None,
) -> Mapping[str, Any]:
    async def handler(client: TiingoClient) -> Any:
        return await client.get_prices(
            ticker,
            start_date=start_date,
            end_date=end_date,
            resample_freq=resample_freq,
        )

    return await _call_tiingo(handler)


@server.tool(
    name="bls_series_data",
    description=(
        "Fetch observations for one or more BLS series IDs (up to 50). Optionally "
        "restrict to a start_year/end_year range and enable catalog metadata, net/"
        "percent-change calculations, annual averages, and aspects."
    ),
)
async def bls_series_data(
    series_ids: list[str],
    start_year: int | None = None,
    end_year: int | None = None,
    catalog: bool = False,
    calculations: bool = False,
    annualaverage: bool = False,
    aspects: bool = False,
) -> Mapping[str, Any]:
    async def handler(client: BlsClient) -> Any:
        return await client.get_series_data(
            series_ids,
            start_year=start_year,
            end_year=end_year,
            catalog=catalog,
            calculations=calculations,
            annualaverage=annualaverage,
            aspects=aspects,
        )

    return await _call_bls(handler)


@server.tool(
    name="bls_series_latest",
    description="Return the single most-recent datapoint for a BLS series.",
)
async def bls_series_latest(series_id: str) -> Mapping[str, Any]:
    async def handler(client: BlsClient) -> Any:
        return await client.get_series_latest(series_id)

    return await _call_bls(handler)


@server.tool(
    name="bls_popular_series",
    description="List the 25 most popular BLS series IDs, optionally within a survey (e.g. 'LA').",
)
async def bls_popular_series(survey: str | None = None) -> Mapping[str, Any]:
    async def handler(client: BlsClient) -> Any:
        return await client.get_popular_series(survey)

    return await _call_bls(handler)


@server.tool(
    name="bls_all_surveys",
    description="List all BLS surveys (abbreviation and name).",
)
async def bls_all_surveys() -> Mapping[str, Any]:
    async def handler(client: BlsClient) -> Any:
        return await client.get_all_surveys()

    return await _call_bls(handler)


@server.tool(
    name="bls_survey_info",
    description="Fetch metadata for a single BLS survey by its abbreviation (e.g. 'TU').",
)
async def bls_survey_info(survey_abbreviation: str) -> Mapping[str, Any]:
    async def handler(client: BlsClient) -> Any:
        return await client.get_survey(survey_abbreviation)

    return await _call_bls(handler)


@server.tool(
    name="bis_dataflows",
    description=(
        "List the BIS statistical dataflows (datasets) available, such as total "
        "credit, policy rates, property prices, and banking statistics. Each entry "
        "gives the dataflow id used by the other BIS tools."
    ),
)
async def bis_dataflows(agency: str = "BIS") -> Mapping[str, Any]:
    async def handler(client: BisClient) -> Any:
        flows = await client.get_dataflows(agency)
        # A bare list is not serializable by _serialize; wrap it.
        return {"dataflows": [flow.model_dump() for flow in flows]}

    return await _call_bis(handler)


@server.tool(
    name="bis_datastructure",
    description=(
        "Describe a BIS dataflow's structure: the ordered dimensions that make up "
        "a series key and the codelist that decodes each one. Set include_codes=true "
        "to also return every code/label pair — some codelists have 1000+ entries, "
        "so it is off by default."
    ),
)
async def bis_datastructure(
    dsd_id: str,
    agency: str = "BIS",
    include_codes: bool = False,
) -> Mapping[str, Any]:
    async def handler(client: BisClient) -> Any:
        structure = await client.get_datastructure(dsd_id, agency)
        payload = structure.model_dump()
        if not include_codes:
            for codelist in payload.get("codelists", {}).values():
                codelist["code_count"] = len(codelist.get("codes", {}))
                codelist["codes"] = {}
        return payload

    return await _call_bis(handler)


@server.tool(
    name="bis_series_data",
    description=(
        "Return observations for a BIS dataflow. 'key' is the dot-joined series key "
        "in dimension order (e.g. 'M.US' for monthly/United States); omit a position "
        "to wildcard it ('M..A'), use '+' for alternatives ('M.US+GB'), or 'all' for "
        "every series. Dimension values come back as codes — use bis_datastructure "
        "to decode them."
    ),
)
async def bis_series_data(
    flow: str,
    key: str = "all",
    start_period: str | None = None,
    end_period: str | None = None,
) -> Mapping[str, Any]:
    async def handler(client: BisClient) -> Any:
        return await client.get_data(
            flow, key, start_period=start_period, end_period=end_period
        )

    return await _call_bis(handler)


@server.tool(
    name="cdc_discover",
    description=(
        "Search the CDC open-data (Socrata) catalog for datasets by keyword "
        "(e.g. 'life expectancy', 'drug overdose') and/or a 'category' from "
        "cdc_categories. Returns dataset ids + names for the other CDC tools."
    ),
)
async def cdc_discover(
    query: str = "", category: str | None = None, limit: int = 20
) -> Mapping[str, Any]:
    async def handler(client: CdcClient) -> Any:
        entries = await client.discover(query, category=category, limit=limit)
        return {"datasets": [entry.model_dump() for entry in entries]}

    return await _call_cdc(handler)


@server.tool(
    name="cdc_categories",
    description=(
        "List the CDC catalog's categories with dataset counts (e.g. 'National "
        "Center for Health Statistics', 'Behavioral Risk Factors') — the topic map "
        "for browsing. Pass a category to cdc_discover to list its datasets."
    ),
)
async def cdc_categories() -> Mapping[str, Any]:
    async def handler(client: CdcClient) -> Any:
        categories = await client.categories()
        return {"categories": [category.model_dump() for category in categories]}

    return await _call_cdc(handler)


@server.tool(
    name="cdc_tags",
    description=(
        "List the CDC catalog's tags with dataset counts (e.g. 'mortality', "
        "'covid-19', 'prevalence') — finer-grained topics for search."
    ),
)
async def cdc_tags() -> Mapping[str, Any]:
    async def handler(client: CdcClient) -> Any:
        tags = await client.tags()
        return {"tags": [tag.model_dump() for tag in tags]}

    return await _call_cdc(handler)


@server.tool(
    name="cdc_dataset_columns",
    description=(
        "Describe a CDC dataset's columns (field name, type, label) from its id — "
        "use it to see which fields to filter/select in cdc_series_data. CDC "
        "datasets have inconsistent schemas, so check columns before querying."
    ),
)
async def cdc_dataset_columns(dataset_id: str) -> Mapping[str, Any]:
    async def handler(client: CdcClient) -> Any:
        return await client.columns(dataset_id)

    return await _call_cdc(handler)


@server.tool(
    name="cdc_series_data",
    description=(
        "Return rows from a CDC dataset by id, filtered with SoQL. 'where' is a "
        "SoQL predicate (e.g. \"race='All Races' AND year>2010\"); 'select' and "
        "'order' are optional comma-separated field lists; 'limit'/'offset' page "
        "the results. Values come back as strings — cast as needed."
    ),
)
async def cdc_series_data(
    dataset_id: str,
    where: str | None = None,
    select: str | None = None,
    order: str | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> Mapping[str, Any]:
    async def handler(client: CdcClient) -> Any:
        return await client.query(
            dataset_id, where=where, select=select, order=order,
            limit=limit, offset=offset,
        )

    return await _call_cdc(handler)


def run() -> None:
    """Start the MCP server over SSE transport."""
    logger.info("Starting meida MCP server on port %s (transport=sse)", server.settings.port)
    server.run(transport="sse")


if __name__ == "__main__":
    run()
