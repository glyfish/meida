"""Tests for meida's MCP server logic (``mcp_server/server.py``).

These exercise the logic meida actually owns: response serialization, the
per-tool conditional parameter assembly, and the incomplete-observations
warning. The navi client itself is replaced with a recording fake so these
stay isolated from ``lib.clients`` (covered separately).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from mcp_server import server


# --- _serialize --------------------------------------------------------------


class _Model(BaseModel):
    a: int
    b: str


def test_serialize_pydantic_model_returns_dump():
    assert server._serialize(_Model(a=1, b="x")) == {"a": 1, "b": "x"}


def test_serialize_dict_passthrough():
    payload = {"already": "a dict"}
    assert server._serialize(payload) is payload


def test_serialize_rejects_unsupported_type():
    with pytest.raises(TypeError):
        server._serialize(object())


# --- Recording fake + patching helpers --------------------------------------


class RecordingFredClient:
    """Records handler calls and returns configured responses per method."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._responses = responses or {}

    def _record(self, name: str, params: dict[str, Any]) -> Any:
        self.calls.append((name, params))
        return self._responses.get(name, {})

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        return self._record("_get", {"path": path, **params})

    async def get_category_series(self, **params: Any) -> Any:
        return self._record("get_category_series", params)

    async def get_series(self, series_id: str) -> Any:
        return self._record("get_series", {"series_id": series_id})

    async def get_series_observations(self, **params: Any) -> Any:
        return self._record("get_series_observations", params)

    async def get_series_updates(self, **params: Any) -> Any:
        return self._record("get_series_updates", params)

    async def get_releases(self, **params: Any) -> Any:
        return self._record("get_releases", params)

    async def get_release_series(self, **params: Any) -> Any:
        return self._record("get_release_series", params)


class RecordingTiingoClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_meta(self, ticker: str) -> Any:
        self.calls.append(("get_meta", {"ticker": ticker}))
        return {}

    async def get_prices(self, ticker: str, **params: Any) -> Any:
        self.calls.append(("get_prices", {"ticker": ticker, **params}))
        return {}


def _patch_fred(monkeypatch, fake: RecordingFredClient) -> None:
    async def fake_call_fred(handler):
        return await handler(fake)

    monkeypatch.setattr(server, "_call_fred", fake_call_fred)


def _patch_tiingo(monkeypatch, fake: RecordingTiingoClient) -> None:
    async def fake_call_tiingo(handler):
        return await handler(fake)

    monkeypatch.setattr(server, "_call_tiingo", fake_call_tiingo)


# --- Conditional parameter assembly -----------------------------------------


async def test_category_series_omits_optional_params(monkeypatch):
    fake = RecordingFredClient()
    _patch_fred(monkeypatch, fake)

    await server.list_category_series(category_id=42)

    assert fake.calls == [("get_category_series", {"category_id": 42})]


async def test_category_series_includes_optional_params(monkeypatch):
    fake = RecordingFredClient()
    _patch_fred(monkeypatch, fake)

    await server.list_category_series(category_id=42, limit=5, order_by="popularity")

    name, params = fake.calls[0]
    assert name == "get_category_series"
    assert params == {"category_id": 42, "limit": 5, "order_by": "popularity"}


async def test_category_children_uses_raw_get(monkeypatch):
    fake = RecordingFredClient()
    _patch_fred(monkeypatch, fake)

    await server.list_category_children(category_id=7)

    assert fake.calls == [("_get", {"path": "/category/children", "category_id": 7})]


async def test_release_series_default_limit(monkeypatch):
    fake = RecordingFredClient()
    _patch_fred(monkeypatch, fake)

    await server.list_release_series(release_id=53)

    assert fake.calls == [("get_release_series", {"release_id": 53, "limit": 100})]


async def test_tiingo_price_series_maps_camel_case(monkeypatch):
    fake = RecordingTiingoClient()
    _patch_tiingo(monkeypatch, fake)

    await server.get_tiingo_price_series(
        ticker="aapl", start_date="2024-01-01", end_date="2024-02-01"
    )

    name, params = fake.calls[0]
    assert name == "get_prices"
    # Passed through as handler kwargs (client maps to Tiingo's camelCase).
    assert params == {
        "ticker": "aapl",
        "start_date": "2024-01-01",
        "end_date": "2024-02-01",
        "resample_freq": None,
    }


# --- Incomplete-observations warning ----------------------------------------


class _RecordingLogger:
    def __init__(self) -> None:
        self.warnings: list[tuple] = []

    def warning(self, *args) -> None:
        self.warnings.append(args)

    def info(self, *args) -> None:  # pragma: no cover - unused but part of API
        pass


async def test_observations_warns_when_incomplete(monkeypatch):
    response = SimpleNamespace(count=10, observations=[object(), object(), object()])
    fake = RecordingFredClient({"get_series_observations": response})
    _patch_fred(monkeypatch, fake)
    logger = _RecordingLogger()
    monkeypatch.setattr(server, "logger", logger)

    await server.get_series_observations(series_id="GDP", limit=3, offset=0)

    assert len(logger.warnings) == 1
    # Optional params assembled correctly (frequency/units omitted).
    assert fake.calls[0][1] == {"series_id": "GDP", "limit": 3, "offset": 0}


async def test_observations_no_warning_when_complete(monkeypatch):
    response = SimpleNamespace(count=3, observations=[object(), object(), object()])
    fake = RecordingFredClient({"get_series_observations": response})
    _patch_fred(monkeypatch, fake)
    logger = _RecordingLogger()
    monkeypatch.setattr(server, "logger", logger)

    await server.get_series_observations(series_id="GDP", limit=100, offset=0)

    assert logger.warnings == []


async def test_observations_includes_frequency_and_units(monkeypatch):
    response = SimpleNamespace(count=1, observations=[object()])
    fake = RecordingFredClient({"get_series_observations": response})
    _patch_fred(monkeypatch, fake)
    monkeypatch.setattr(server, "logger", _RecordingLogger())

    await server.get_series_observations(
        series_id="GDP", limit=100, offset=0, frequency="q", units="lin"
    )

    assert fake.calls[0][1] == {
        "series_id": "GDP",
        "limit": 100,
        "offset": 0,
        "frequency": "q",
        "units": "lin",
    }
