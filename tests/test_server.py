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


class RecordingBlsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_series_data(self, series_ids: Any, **params: Any) -> Any:
        self.calls.append(("get_series_data", {"series_ids": series_ids, **params}))
        return {}

    async def get_series_latest(self, series_id: str) -> Any:
        self.calls.append(("get_series_latest", {"series_id": series_id}))
        return {}

    async def get_popular_series(self, survey: Any = None) -> Any:
        self.calls.append(("get_popular_series", {"survey": survey}))
        return {}

    async def get_all_surveys(self) -> Any:
        self.calls.append(("get_all_surveys", {}))
        return {}

    async def get_survey(self, survey_abbreviation: str) -> Any:
        self.calls.append(("get_survey", {"survey_abbreviation": survey_abbreviation}))
        return {}


def _patch_fred(monkeypatch, fake: RecordingFredClient) -> None:
    async def fake_call_fred(handler):
        return await handler(fake)

    monkeypatch.setattr(server, "_call_fred", fake_call_fred)


def _patch_tiingo(monkeypatch, fake: RecordingTiingoClient) -> None:
    async def fake_call_tiingo(handler):
        return await handler(fake)

    monkeypatch.setattr(server, "_call_tiingo", fake_call_tiingo)


def _patch_bls(monkeypatch, fake: RecordingBlsClient) -> None:
    async def fake_call_bls(handler):
        return await handler(fake)

    monkeypatch.setattr(server, "_call_bls", fake_call_bls)


class RecordingBisClient:
    """Fake BisClient returning minimal pydantic models the tools can dump."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_dataflows(self, agency: str = "BIS") -> Any:
        from lib.clients.models.bis import BisDataflow

        self.calls.append(("get_dataflows", {"agency": agency}))
        return [BisDataflow(id="WS_TC", name="Total credit")]

    async def get_datastructure(self, dsd_id: str, agency: str = "BIS") -> Any:
        from lib.clients.models.bis import BisCodelist, BisDataStructure, BisDimension

        self.calls.append(("get_datastructure", {"dsd_id": dsd_id, "agency": agency}))
        return BisDataStructure(
            id=dsd_id,
            dimensions=[BisDimension(id="FREQ", codelist_id="CL_FREQ")],
            codelists={"CL_FREQ": BisCodelist(id="CL_FREQ", codes={"M": "Monthly", "A": "Annual"})},
        )

    async def get_data(self, flow: str, key: str = "all", **params: Any) -> Any:
        from lib.clients.models.bis import BisDataResponse

        self.calls.append(("get_data", {"flow": flow, "key": key, **params}))
        return BisDataResponse(flow=flow)


def _patch_bis(monkeypatch, fake: RecordingBisClient) -> None:
    async def fake_call_bis(handler):
        return await handler(fake)

    monkeypatch.setattr(server, "_call_bis", fake_call_bis)


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


# --- BLS tools ----------------------------------------------------------------


async def test_bls_series_data_passes_all_params(monkeypatch):
    fake = RecordingBlsClient()
    _patch_bls(monkeypatch, fake)

    await server.bls_series_data(
        series_ids=["LNS14000000", "CES0000000001"],
        start_year=2020,
        end_year=2023,
        catalog=True,
        calculations=True,
    )

    name, params = fake.calls[0]
    assert name == "get_series_data"
    assert params == {
        "series_ids": ["LNS14000000", "CES0000000001"],
        "start_year": 2020,
        "end_year": 2023,
        "catalog": True,
        "calculations": True,
        "annualaverage": False,
        "aspects": False,
    }


async def test_bls_series_data_defaults(monkeypatch):
    fake = RecordingBlsClient()
    _patch_bls(monkeypatch, fake)

    await server.bls_series_data(series_ids=["LNS14000000"])

    _, params = fake.calls[0]
    assert params["start_year"] is None and params["end_year"] is None
    assert params["catalog"] is False and params["aspects"] is False


async def test_bls_series_latest(monkeypatch):
    fake = RecordingBlsClient()
    _patch_bls(monkeypatch, fake)

    await server.bls_series_latest(series_id="LNS14000000")

    assert fake.calls == [("get_series_latest", {"series_id": "LNS14000000"})]


async def test_bls_popular_series_optional_survey(monkeypatch):
    fake = RecordingBlsClient()
    _patch_bls(monkeypatch, fake)

    await server.bls_popular_series()
    await server.bls_popular_series(survey="LA")

    assert fake.calls == [
        ("get_popular_series", {"survey": None}),
        ("get_popular_series", {"survey": "LA"}),
    ]


async def test_bls_all_surveys_and_survey_info(monkeypatch):
    fake = RecordingBlsClient()
    _patch_bls(monkeypatch, fake)

    await server.bls_all_surveys()
    await server.bls_survey_info(survey_abbreviation="TU")

    assert fake.calls == [
        ("get_all_surveys", {}),
        ("get_survey", {"survey_abbreviation": "TU"}),
    ]


# --- BIS tools ----------------------------------------------------------------


async def test_bis_dataflows_wraps_list(monkeypatch):
    """get_dataflows returns a list, which _serialize cannot handle directly."""
    fake = RecordingBisClient()
    _patch_bis(monkeypatch, fake)

    result = await server.bis_dataflows()

    assert fake.calls == [("get_dataflows", {"agency": "BIS"})]
    assert result["dataflows"][0]["id"] == "WS_TC"


async def test_bis_datastructure_omits_codes_by_default(monkeypatch):
    """Codelists can hold 1000+ entries; the tool must not dump them unasked."""
    fake = RecordingBisClient()
    _patch_bis(monkeypatch, fake)

    result = await server.bis_datastructure(dsd_id="BIS_TOTAL_CREDIT")

    codelist = result["codelists"]["CL_FREQ"]
    assert codelist["codes"] == {}
    assert codelist["code_count"] == 2
    assert [d["id"] for d in result["dimensions"]] == ["FREQ"]


async def test_bis_datastructure_include_codes(monkeypatch):
    fake = RecordingBisClient()
    _patch_bis(monkeypatch, fake)

    result = await server.bis_datastructure(dsd_id="BIS_TOTAL_CREDIT", include_codes=True)

    assert result["codelists"]["CL_FREQ"]["codes"] == {"M": "Monthly", "A": "Annual"}


async def test_bis_series_data_passes_params(monkeypatch):
    fake = RecordingBisClient()
    _patch_bis(monkeypatch, fake)

    await server.bis_series_data(
        flow="WS_CBPOL", key="M.US", start_period="2025-01", end_period="2026-01"
    )

    assert fake.calls[0] == (
        "get_data",
        {"flow": "WS_CBPOL", "key": "M.US",
         "start_period": "2025-01", "end_period": "2026-01"},
    )


async def test_bis_series_data_defaults(monkeypatch):
    fake = RecordingBisClient()
    _patch_bis(monkeypatch, fake)

    await server.bis_series_data(flow="WS_CBPOL")

    _, params = fake.calls[0]
    assert params["key"] == "all"
    assert params["start_period"] is None and params["end_period"] is None


# --- CDC server tools --------------------------------------------------------


class RecordingCdcClient:
    """Fake CdcClient returning minimal pydantic models the tools can dump."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def discover(self, query: str = "", *, category: Any = None, limit: int = 20) -> Any:
        from lib.clients.models.cdc import CdcCatalogEntry

        self.calls.append(("discover", {"query": query, "category": category, "limit": limit}))
        return [CdcCatalogEntry(id="w9j2-ggv5", name="Life expectancy")]

    async def categories(self) -> Any:
        from lib.clients.models.cdc import CdcCategory

        self.calls.append(("categories", {}))
        return [CdcCategory(category="National Center for Health Statistics", count=287)]

    async def tags(self) -> Any:
        from lib.clients.models.cdc import CdcTag

        self.calls.append(("tags", {}))
        return [CdcTag(tag="mortality", count=117)]

    async def columns(self, dataset_id: str) -> Any:
        from lib.clients.models.cdc import CdcColumn, CdcDataset

        self.calls.append(("columns", {"dataset_id": dataset_id}))
        return CdcDataset(id=dataset_id, name="LE", columns=[CdcColumn(field_name="year")])

    async def query(self, dataset_id: str, **params: Any) -> Any:
        from lib.clients.models.cdc import CdcDataResponse

        self.calls.append(("query", {"dataset_id": dataset_id, **params}))
        return CdcDataResponse(dataset_id=dataset_id, rows=[{"year": "1900"}])


def _patch_cdc(monkeypatch, fake: RecordingCdcClient) -> None:
    async def fake_call_cdc(handler):
        return server._serialize(await handler(fake))

    monkeypatch.setattr(server, "_call_cdc", fake_call_cdc)


async def test_cdc_discover_wraps_list(monkeypatch):
    """discover returns a list, which _serialize cannot handle directly."""
    fake = RecordingCdcClient()
    _patch_cdc(monkeypatch, fake)

    result = await server.cdc_discover(query="life expectancy")

    assert fake.calls == [("discover", {"query": "life expectancy", "category": None, "limit": 20})]
    assert result["datasets"][0]["id"] == "w9j2-ggv5"


async def test_cdc_dataset_columns(monkeypatch):
    fake = RecordingCdcClient()
    _patch_cdc(monkeypatch, fake)

    result = await server.cdc_dataset_columns(dataset_id="w9j2-ggv5")

    assert fake.calls == [("columns", {"dataset_id": "w9j2-ggv5"})]
    assert result["columns"][0]["field_name"] == "year"


async def test_cdc_series_data_passes_soql(monkeypatch):
    fake = RecordingCdcClient()
    _patch_cdc(monkeypatch, fake)

    result = await server.cdc_series_data(dataset_id="w9j2-ggv5", where="year>2000", limit=5)

    name, params = fake.calls[0]
    assert name == "query"
    assert params["dataset_id"] == "w9j2-ggv5"
    assert params["where"] == "year>2000"
    assert params["limit"] == 5
    assert result["rows"][0]["year"] == "1900"


async def test_cdc_categories(monkeypatch):
    fake = RecordingCdcClient()
    _patch_cdc(monkeypatch, fake)

    result = await server.cdc_categories()

    assert fake.calls == [("categories", {})]
    assert result["categories"][0]["category"] == "National Center for Health Statistics"
    assert result["categories"][0]["count"] == 287


async def test_cdc_tags(monkeypatch):
    fake = RecordingCdcClient()
    _patch_cdc(monkeypatch, fake)

    result = await server.cdc_tags()

    assert fake.calls == [("tags", {})]
    assert result["tags"][0]["tag"] == "mortality"
