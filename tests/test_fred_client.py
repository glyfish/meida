"""Tests for navi's ``FredClient`` (``lib/clients/fred.py``).

Uses an ``httpx.MockTransport`` to assert the outgoing request (path, injected
``api_key``/``file_type``, merged params) and the typed model parsing, plus the
error-wrapping path.
"""
from __future__ import annotations

import httpx
import pytest

from lib.clients import FredClient, FredAPIError
from lib.clients.models.fred import (
    CategoryResponse,
    ObservationsResponse,
    ReleasesResponse,
    SeriesResponse,
)


async def test_get_injects_api_key_and_file_type(make_fred_client, fred_category_payload):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=fred_category_payload)

    async with make_fred_client(handler) as client:
        result = await client.get_category_children(125)

    assert seen["path"].endswith("/category/children")
    assert seen["params"]["api_key"] == "test-key"
    assert seen["params"]["file_type"] == "json"
    assert seen["params"]["category_id"] == "125"
    assert isinstance(result, CategoryResponse)
    assert [c.name for c in result.categories] == ["Trade Balance", "National Accounts"]
    assert result.categories[0].parent_id == 13


async def test_category_series_merges_extra_params(make_fred_client, fred_series_payload):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=fred_series_payload)

    async with make_fred_client(handler) as client:
        result = await client.get_category_series(32992, limit=10, order_by="popularity")

    assert seen["path"].endswith("/category/series")
    assert seen["params"]["category_id"] == "32992"
    assert seen["params"]["limit"] == "10"
    assert seen["params"]["order_by"] == "popularity"
    assert isinstance(result, SeriesResponse)
    assert result.seriess[0].id == "GDP"


async def test_series_observations_parses_model(make_fred_client, fred_observations_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/series/observations")
        assert dict(request.url.params)["series_id"] == "GDP"
        return httpx.Response(200, json=fred_observations_payload)

    async with make_fred_client(handler) as client:
        result = await client.get_series_observations("GDP", limit=100)

    assert isinstance(result, ObservationsResponse)
    assert result.count == 3
    assert len(result.observations) == 3
    assert result.observations[0].value == "27000.0"


async def test_releases_parses_model(make_fred_client, fred_releases_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/releases")
        return httpx.Response(200, json=fred_releases_payload)

    async with make_fred_client(handler) as client:
        result = await client.get_releases(limit=100)

    assert isinstance(result, ReleasesResponse)
    assert result.releases[0].press_release is True


async def test_http_error_wrapped_as_fred_api_error(make_fred_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    with pytest.raises(FredAPIError) as exc_info:
        async with make_fred_client(handler) as client:
            await client.get_category_children(1)

    assert "internal error" in str(exc_info.value)


async def test_owns_client_flag_when_injected(make_fred_client):
    """A caller-supplied client is not owned (so aclose leaves it to the caller)."""
    client = make_fred_client(lambda request: httpx.Response(200, json={}))
    assert client._owns_client is False
