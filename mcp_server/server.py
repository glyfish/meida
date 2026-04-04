from __future__ import annotations
from typing import Any, Awaitable, Callable, Mapping
from lib.logger import get_logger

from mcp.server.fastmcp import FastMCP

from lib.clients import FredClient


logger = get_logger("meida.mcp")

server = FastMCP(
    name="mcp-server",
    instructions="Access curated Federal Reserve Economic Data (FRED) tools.",
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
    name="fred_release_series",
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


def run() -> None:
    """Start the MCP server over SSE transport."""
    logger.info("Starting meida MCP server on port %s (transport=sse)", server.settings.port)
    server.run(transport="sse")


if __name__ == "__main__":
    run()
