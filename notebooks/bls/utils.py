"""Helpers for exploring BLS data through the MCP server.

Mirrors notebooks/fred/utils.py: thin wrappers over the MCP tools plus a couple
of discovery routines that persist survey/series metadata to YAML. The MCP
server must be running (see the project README).
"""
from typing import Any
import os
import time

import yaml

from lib.mcp_client import MCPClient, MCPClientConfig
from lib.utils import print_json_vertical
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


async def show_all_surveys() -> list[dict[str, Any]]:
    """Print and return every BLS survey (abbreviation + name)."""
    result = await call_tool("bls_all_surveys")
    surveys = result.structuredContent["result"]["results"]["survey"]  # type: ignore
    for survey in surveys:
        print(f"{survey['survey_abbreviation']}: {survey['survey_name']}")
    return surveys


async def popular_series(survey: str | None = None) -> list[str]:
    """Return the popular series IDs overall, or for a single survey."""
    args = {"survey": survey} if survey else {}
    result = await call_tool("bls_popular_series", args)
    series = result.structuredContent["result"]["results"]["series"]  # type: ignore
    return [s["series_id"] for s in series]


async def export_survey_catalog(
    survey: str,
    output_path: str,
    start_year: int | None = None,
    end_year: int | None = None,
) -> None:
    """Fetch the popular series for a survey with catalog metadata and write YAML."""
    series_ids = await popular_series(survey)
    print(f"Survey {survey}: {len(series_ids)} popular series")
    if not series_ids:
        return

    result = await call_tool(
        "bls_series_data",
        {
            "series_ids": series_ids,
            "start_year": start_year,
            "end_year": end_year,
            "catalog": True,
        },
    )
    payload = result.structuredContent["result"]  # type: ignore
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)
    print(f"Wrote {len(payload['results']['series'])} series to {output_path}")


async def fetch_series(
    series_ids: list[str],
    output_path: str,
    start_year: int | None = None,
    end_year: int | None = None,
    calculations: bool = False,
    delay_seconds: float = 0.5,
) -> None:
    """Fetch observations for the given series IDs (batched by 50) and write YAML."""
    all_series: list[dict[str, Any]] = []
    for start in range(0, len(series_ids), 50):  # BLS caps at 50 series per query
        batch = series_ids[start : start + 50]
        time.sleep(delay_seconds)  # be polite with the BLS API
        result = await call_tool(
            "bls_series_data",
            {
                "series_ids": batch,
                "start_year": start_year,
                "end_year": end_year,
                "calculations": calculations,
            },
        )
        payload = result.structuredContent["result"]  # type: ignore
        all_series.extend(payload["results"]["series"])
        print(f"Fetched {len(batch)} series (total {len(all_series)})")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(all_series, fh, sort_keys=False, allow_unicode=True)
    print(f"Wrote {len(all_series)} series to {output_path}")
