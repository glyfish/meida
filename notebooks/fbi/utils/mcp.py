"""Helpers for reaching the FBI tools over MCP.

Mirrors ``notebooks/bis/utils.py`` and ``notebooks/fred/utils.py``: thin
wrappers over the two tools, plus the arithmetic the notebooks repeat. The MCP
server must be running, and **it does not hot-reload** -- a server started
before the FBI tools existed serves the old tool list and the calls here fail
as "unknown tool" rather than as anything more informative.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_MEIDA_ROOT = str(_Path(__file__).resolve().parents[3])
if _MEIDA_ROOT not in _sys.path:
    _sys.path.insert(0, _MEIDA_ROOT)

from typing import Any

from environment import get_mcp_url
from lib.mcp_client import MCPClient, MCPClientConfig

MCP_URL = get_mcp_url()
config = MCPClientConfig(url=MCP_URL)


class StaleServerError(RuntimeError):
    """The server is running, but it predates the tool being called."""


async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> Any:
    """Call one MCP tool and return its structured content.

    A server started before a tool existed answers normally and simply does not
    list it, so the failure surfaces as "unknown tool" with nothing to say what
    to do about it. The server does not hot-reload, so that is the usual cause
    of a call that worked yesterday failing today, and it is worth naming.
    """
    async with MCPClient(config) as client:
        available = {tool.name for tool in await client.list_tools()}
        if name not in available:
            raise StaleServerError(
                f"{MCP_URL} serves {len(available)} tools and {name!r} is not among them. "
                f"The server does not hot-reload: restart it (and the VS Code debug session "
                f"running it) so the tools defined in mcp_server/server.py are registered. "
                f"FBI tools present: {sorted(t for t in available if t.startswith('fbi_')) or 'none'}."
            )
        result = await client.call_tool(name, arguments or {})
    structured = getattr(result, "structuredContent", None)
    if not structured:
        # A failed call still returns a result object, and returning it raw
        # gives "'CallToolResult' object has no attribute 'get'" three cells
        # later. The tool's own message says what went wrong -- usually the
        # hourly api.data.gov allowance -- so surface that instead.
        content = getattr(result, "content", None) or []
        detail = " ".join(getattr(part, "text", "") for part in content).strip()
        raise RuntimeError(f"{name} returned no structured content: {detail or result!r}")
    return structured


async def list_tools(prefix: str = "") -> list[tuple[str, str]]:
    """Tool names and the first line of each description, optionally filtered."""
    async with MCPClient(config) as client:
        tools = await client.list_tools()
    return [(t.name, (t.description or "").split(".")[0])
            for t in tools if t.name.startswith(prefix)]


def observations(series: dict[str, Any]) -> dict[str, float]:
    """``{period: value}`` for the points that carry one."""
    return {o["period"]: o["value"] for o in series.get("observations", [])
            if o.get("value") is not None}


def _in_order(points: dict[str, float]) -> list[str]:
    """Periods sorted by date. 'MM-YYYY' does not sort as text."""
    return sorted(points, key=lambda p: (p.split("-")[1], p.split("-")[0]))


def unfiled(points: dict[str, float], run_floor: float = 25.0) -> set[str]:
    """Months that are blank because nobody filed, not because nothing happened.

    The API spells a missing return as ``0``, which is indistinguishable from a
    real zero until you look at the run. Washington filed nothing from January
    to July 2021 while converting to NIBRS, and summing those zeros turns five
    filed months into a year: 116 homicides against the 198 of the year before,
    a fall that never happened.

    A run counts as unfiled when the months it swallows would have carried more
    than *run_floor* between them, judged by the surrounding median. That keeps
    the genuine quiet months of a small department, where two consecutive zeros
    are ordinary.
    """
    ordered = _in_order(points)
    values = [points[p] for p in ordered]
    filed = [v for v in values if v]
    level = sorted(filed)[len(filed) // 2] if filed else 0.0
    out: set[str] = set()
    start = None
    for i, value in enumerate(values + [1.0]):            # sentinel closes a trailing run
        if not value and start is None:
            start = i
        elif value and start is not None:
            if (i - start) >= 2 and (i - start) * level >= run_floor:
                out.update(ordered[start:i])
            start = None
    return out


def rolling_12(points: dict[str, float], skip: set[str] | None = None) -> dict[str, float]:
    """Twelve-month rolling sum of ``MM-YYYY`` points, in date order.

    Monthly counts for one city are small and noisy -- a department with three
    homicides in a month and eight in the next has not changed -- so every
    comparison here is made on a rolling year. A window containing a month
    nobody filed is left out rather than summed: the point of the rule above.
    """
    skip = unfiled(points) if skip is None else skip
    ordered = _in_order(points)
    out: dict[str, float] = {}
    for i in range(11, len(ordered)):
        window = ordered[i - 11:i + 1]
        if any(p in skip for p in window):
            continue
        out[ordered[i]] = sum(points[p] for p in window)
    return out


def clearance_rate(offenses: dict[str, float], clearances: dict[str, float]) -> dict[str, float]:
    """Clearances divided by offences, as a percentage, on shared periods.

    Both are rolling sums by the time they reach here. A monthly ratio is
    meaningless for a city: a clearance is recorded when it happens, not when
    the offence it closes was committed, so a single month can exceed 100%.
    """
    return {period: 100 * clearances[period] / offenses[period]
            for period in sorted(offenses.keys() & clearances.keys())
            if offenses[period]}
