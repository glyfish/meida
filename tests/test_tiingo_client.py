"""Tests for navi's ``TiingoClient`` (``lib/clients/tiingo.py``).

Uses an ``httpx.MockTransport`` to assert the auth header, the conditional
query-param assembly in ``get_prices``, ticker normalization, model parsing,
and error wrapping.
"""
from __future__ import annotations

import httpx
import pytest

from lib.clients import TiingoClient, TiingoAPIError
from lib.clients.models.tiingo import TiingoMeta, TiingoPriceSeries


async def test_get_meta_sends_token_header(make_tiingo_client, tiingo_meta_payload):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=tiingo_meta_payload)

    async with make_tiingo_client(handler) as client:
        result = await client.get_meta("aapl")

    assert seen["path"].endswith("/daily/aapl")
    assert seen["auth"] == "Token test-key"
    assert isinstance(result, TiingoMeta)
    assert result.exchange_code == "NASDAQ"
    assert str(result.start_date) == "1980-12-12"


async def test_get_prices_assembles_optional_params(make_tiingo_client, tiingo_prices_payload):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=tiingo_prices_payload)

    async with make_tiingo_client(handler) as client:
        result = await client.get_prices(
            "aapl", start_date="2024-01-01", end_date="2024-01-05", resample_freq="daily"
        )

    assert seen["path"].endswith("/daily/aapl/prices")
    assert seen["params"] == {
        "startDate": "2024-01-01",
        "endDate": "2024-01-05",
        "resampleFreq": "daily",
    }
    assert isinstance(result, TiingoPriceSeries)
    assert result.ticker == "AAPL"  # normalized to upper-case
    assert result.prices[0].adj_close == 184.25


async def test_get_prices_omits_unset_params(make_tiingo_client, tiingo_prices_payload):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=tiingo_prices_payload)

    async with make_tiingo_client(handler) as client:
        await client.get_prices("msft")

    assert seen["params"] == {}


async def test_http_error_wrapped_as_tiingo_api_error(make_tiingo_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with pytest.raises(TiingoAPIError) as exc_info:
        async with make_tiingo_client(handler) as client:
            await client.get_meta("nope")

    assert "not found" in str(exc_info.value)
