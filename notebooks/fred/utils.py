from typing import Any
import yaml
import time
import json

from lib.mcp_client import MCPClient, MCPClientConfig
from lib.utils import print_json_vertical
from lib.env import get_mcp_url

MCP_URL = get_mcp_url()
config = MCPClientConfig(url=MCP_URL)

async def call_tool(tool_name: str, arguments: dict[str, Any] | None = None):
    async with MCPClient(config) as client:
        return await client.call_tool(tool_name, arguments or {})


async def list_mcp_tools():
    async with MCPClient(config) as client:
        tools = await client.list_tools()
        for tool in tools:
            print(f"{tool.name}: {tool.description}")


async def show_tool_schema(tool_name: str):
    async with MCPClient(config) as client:
        schema = await client.get_tool_schema(tool_name)
        print_json_vertical(schema)


async def children_of_categories(categories: list[Any]):
    for category in categories:
        category_id = category["id"]
        category_name = category["name"]
        args = {"category_id": category_id}
        result = await call_tool("fred.category_children", args)
        children = result.structuredContent['result']['categories']  # type: ignore
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
            response = await client.call_tool("fred.category_children", {"category_id": category_id})
            payload = response.structuredContent or {}
            for child in payload.get("categories", []):
                queue.append((child["id"], level + 1))


async def find_leaf_categories(
    root_id: int = 0,
    root_name: str = "Root",
    output_path: str = "leaf_categories.yaml",
) -> None:
    leaves: list[dict[str, object]] = []
    queue: list[tuple[int, list[dict[str, object]]]] = [
        (root_id, [{"id": root_id, "name": root_name}])
    ]

    async with MCPClient(config) as client:
        while queue:
            time.sleep(2.0)  # Be kind to the FRED server
            category_id, path = queue.pop(0)

            response = await client.call_tool(
                "fred.category_children", {"category_id": category_id}
            )
            payload = response.structuredContent or {}
            children = payload["result"].get("categories", [])

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

    with open(output_path, "w", encoding="utf-8") as fh:
        payload = json.loads(json.dumps(leaves))
        yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)
    print(f"Wrote {len(leaves)} leaf categories (with names) to {output_path}")


async def export_finance_category_series(input_path: str, output_path: str, delay_seconds: float = 2.0,) -> None:
    """
    Load finance category metadata, pull FRED series for each leaf, and persist to YAML.
    """

    print(f"Reading categories from {input_path}")
    print(f"Writing series to {output_path}")

    with open(input_path, "r", encoding="utf-8") as fh:
        categories: list[dict[str, Any]] = yaml.safe_load(fh) or []

    print(f"Loaded {len(categories)} categories")

    series_bundle: list[dict[str, Any]] = []
    async with MCPClient(config) as client:
        for category in categories:
            time.sleep(delay_seconds)  # keep us polite with FRED
            category_id = category["leaf_id"]
            category_name = category["leaf_name"]

            response = await client.call_tool(
                "fred.category_series",
                {"category_id": category_id},
            )
            payload = (response.structuredContent or {}).get("result", {})

            pagination = payload.get("pagination", {})
            count = pagination.get("count", 0)
            offset = pagination.get("offset", 0)
            limit = pagination.get("limit", 0)
            seriess = payload.get("seriess", [])

            print(f"Processing {len(seriess)} series for category {category_id}, {category_name}")
            print(f"Pagination: count={count}, offset={offset}, limit={limit}")

            series_bundle.append(
                {
                    "category_id": category_id,
                    "category_name": category_name,
                    "seriess": seriess,
                }
            )

    with open(output_path, "w", encoding="utf-8") as fh:
        sanitized = json.loads(json.dumps(series_bundle))
        yaml.safe_dump(sanitized, fh, sort_keys=False, allow_unicode=True)

    print(f"Wrote series data for {len(series_bundle)} categories to {output_path}")