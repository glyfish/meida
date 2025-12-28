"""MCP server that exposes FRED tools via FastMCP."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping
import logging

from mcp.server.fastmcp import FastMCP

from lib.clients import FredClient


logger = logging.getLogger("meida.mcp")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

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
    name="fred.category_children",
    description="List the child categories for a FRED category.",
)
async def list_category_children(category_id: int) -> Mapping[str, Any]:
    async def handler(client: FredClient) -> Any:
        return await client._get('/category/children', {'category_id': category_id})

    return await _call_fred(handler)


@server.tool(
    name="fred.category_series",
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
    name="fred.series_info",
    description="Fetch metadata for a single FRED series.",
)
async def get_series_info(series_id: str) -> Mapping[str, Any]:
    async def handler(client: FredClient) -> Any:
        return await client.get_series(series_id)

    return await _call_fred(handler)


@server.tool(
    name="fred.series_observations",
    description="Return observations for a series (limit defaults to 100).",
)
async def get_series_observations(
    series_id: str,
    limit: int | None = 100,
    frequency: str | None = None,
    units: str | None = None,
) -> Mapping[str, Any]:
    async def handler(client: FredClient) -> Any:
        params: dict[str, Any] = {"series_id": series_id}
        if limit is not None:
            params["limit"] = limit
        if frequency:
            params["frequency"] = frequency
        if units:
            params["units"] = units
        return await client.get_series_observations(**params)

    return await _call_fred(handler)


@server.tool(
    name="fred.series_updates",
    description="Return recently updated FRED series.",
)
async def get_series_updates(limit: int | None = 50, offset: int | None = 0) -> Mapping[str, Any]:
    async def handler(client: FredClient) -> Any:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if offset:
            params["offset"] = offset
        return await client.get_series_updates(**params)

    return await _call_fred(handler)


@server.tool(
    name="fred.releases",
    description="List the available FRED releases.",
)
async def list_releases(limit: int | None = 50, order_by: str | None = None) -> Mapping[str, Any]:
    async def handler(client: FredClient) -> Any:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if order_by:
            params["order_by"] = order_by
        return await client.get_releases(**params)

    return await _call_fred(handler)


@server.tool(
    name="fred.release_series",
    description="List the series that belong to a FRED release.",
)
async def list_release_series(release_id: int, limit: int | None = 50) -> Mapping[str, Any]:
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
