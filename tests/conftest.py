"""Shared fixtures and sample payloads for the meida test suite.

Covers meida's MCP server (``mcp_server/server.py``) and the navi HTTP clients
(``lib/clients``), which are importable here via navi's editable install.

The client fixtures wire a ``FredClient``/``TiingoClient`` to an
``httpx.MockTransport`` so no network access or API keys are required: both
clients accept explicit ``api_key``/``base_url``/``client`` arguments.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

from lib.clients import BlsClient, FredClient, TiingoClient

HttpHandler = Callable[[httpx.Request], httpx.Response]

FRED_BASE_URL = "https://fred.test/fred"
TIINGO_BASE_URL = "https://tiingo.test/tiingo"
BLS_BASE_URL = "https://bls.test/publicAPI/v2"

_FIXTURES = Path(__file__).parent / "fixtures"


def _mock_async_client(handler: HttpHandler, base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=base_url)


@pytest.fixture
async def make_fred_client() -> Callable[[HttpHandler], FredClient]:
    """Factory building a FredClient whose HTTP calls are served by ``handler``.

    The injected transport clients are closed on teardown (the FredClient does
    not own a caller-supplied client, so it won't close them itself).
    """
    created: list[httpx.AsyncClient] = []

    def _factory(handler: HttpHandler) -> FredClient:
        http = _mock_async_client(handler, FRED_BASE_URL)
        created.append(http)
        return FredClient(api_key="test-key", base_url=FRED_BASE_URL, client=http)

    yield _factory

    for http in created:
        await http.aclose()


@pytest.fixture
async def make_tiingo_client() -> Callable[[HttpHandler], TiingoClient]:
    """Factory building a TiingoClient whose HTTP calls are served by ``handler``."""
    created: list[httpx.AsyncClient] = []

    def _factory(handler: HttpHandler) -> TiingoClient:
        http = _mock_async_client(handler, TIINGO_BASE_URL)
        created.append(http)
        return TiingoClient(api_key="test-key", base_url=TIINGO_BASE_URL, client=http)

    yield _factory

    for http in created:
        await http.aclose()


@pytest.fixture
async def make_bls_client() -> Callable[[HttpHandler], BlsClient]:
    """Factory building a BlsClient whose HTTP calls are served by ``handler``."""
    created: list[httpx.AsyncClient] = []

    def _factory(handler: HttpHandler, **kwargs: Any) -> BlsClient:
        """Extra kwargs go to BlsClient (e.g. max_attempts, backoff_seconds)."""
        http = _mock_async_client(handler, BLS_BASE_URL)
        created.append(http)
        return BlsClient(api_key="test-key", base_url=BLS_BASE_URL, client=http, **kwargs)

    yield _factory

    for http in created:
        await http.aclose()


@pytest.fixture
def load_bls_fixture() -> Callable[[str], Any]:
    """Return a loader for the captured BLS response fixtures (tests/fixtures/bls)."""

    def _load(name: str) -> Any:
        return json.loads((_FIXTURES / "bls" / f"{name}.json").read_text())

    return _load


# --- Sample payloads (shaped to satisfy the pydantic models) -----------------


@pytest.fixture
def fred_category_payload() -> dict[str, Any]:
    return {
        "realtime_start": "2024-01-01",
        "realtime_end": "2024-01-01",
        "categories": [
            {"id": 125, "name": "Trade Balance", "parent_id": 13},
            {"id": 32992, "name": "National Accounts", "parent_id": 18},
        ],
    }


@pytest.fixture
def fred_series_payload() -> dict[str, Any]:
    return {
        "realtime_start": "2024-01-01",
        "realtime_end": "2024-01-01",
        "count": 1,
        "offset": 0,
        "limit": 1000,
        "seriess": [
            {
                "id": "GDP",
                "title": "Gross Domestic Product",
                "observation_start": "1947-01-01",
                "observation_end": "2024-01-01",
                "frequency": "Quarterly",
                "frequency_short": "Q",
                "units": "Billions of Dollars",
                "units_short": "Bil. of $",
                "seasonal_adjustment": "Seasonally Adjusted Annual Rate",
                "seasonal_adjustment_short": "SAAR",
                "last_updated": "2024-03-28 07:56:01-05",
                "popularity": 92,
                "notes": "BEA Account Code: A191RC",
            }
        ],
    }


@pytest.fixture
def fred_observations_payload() -> dict[str, Any]:
    return {
        "realtime_start": "2024-01-01",
        "realtime_end": "2024-01-01",
        "count": 3,
        "offset": 0,
        "limit": 100,
        "observations": [
            {"realtime_start": "2024-01-01", "realtime_end": "2024-01-01", "date": "2023-10-01", "value": "27000.0"},
            {"realtime_start": "2024-01-01", "realtime_end": "2024-01-01", "date": "2023-07-01", "value": "26900.0"},
            {"realtime_start": "2024-01-01", "realtime_end": "2024-01-01", "date": "2023-04-01", "value": "26800.0"},
        ],
    }


@pytest.fixture
def fred_releases_payload() -> dict[str, Any]:
    return {
        "realtime_start": "2024-01-01",
        "realtime_end": "2024-01-01",
        "releases": [
            {
                "id": 53,
                "name": "Gross Domestic Product",
                "press_release": True,
                "link": "https://www.bea.gov/data/gdp",
                "realtime_start": "2024-01-01",
                "realtime_end": "2024-01-01",
            }
        ],
    }


@pytest.fixture
def tiingo_meta_payload() -> dict[str, Any]:
    return {
        "ticker": "aapl",
        "name": "Apple Inc",
        "exchangeCode": "NASDAQ",
        "startDate": "1980-12-12",
        "endDate": "2024-01-05",
        "description": "Apple Inc. designs and manufactures consumer electronics.",
    }


@pytest.fixture
def tiingo_prices_payload() -> list[dict[str, Any]]:
    return [
        {
            "date": "2024-01-03T00:00:00.000Z",
            "open": 184.22,
            "high": 185.88,
            "low": 183.43,
            "close": 184.25,
            "volume": 58414460,
            "adjOpen": 184.22,
            "adjHigh": 185.88,
            "adjLow": 183.43,
            "adjClose": 184.25,
            "adjVolume": 58414460.0,
            "divCash": 0.0,
            "splitFactor": 1.0,
        }
    ]
