"""Tests for meida's MCP server logic (``mcp_server/server.py``).

These exercise the logic meida actually owns: response serialization, the
per-tool conditional parameter assembly, and the incomplete-observations
warning. The navi client itself is replaced with a recording fake so these
stay isolated from ``clients`` (covered separately).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from mcp_server import cdc_query, server


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

    async def get_category_children(self, category_id: int) -> Any:
        return self._record("get_category_children", {"category_id": category_id})

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
        from clients.models.tiingo import TiingoMeta

        self.calls.append(("get_meta", {"ticker": ticker}))
        return TiingoMeta.model_validate(
            {"ticker": ticker.upper(), "name": "Apple Inc", "exchangeCode": "NASDAQ",
             "startDate": "1980-12-12", "endDate": "2024-01-03"}
        )

    async def get_prices(self, ticker: str, **params: Any) -> Any:
        from clients.models.tiingo import TiingoPriceSeries

        self.calls.append(("get_prices", {"ticker": ticker, **params}))
        return TiingoPriceSeries.model_validate(
            {"ticker": ticker.upper(),
             "prices": [{"date": "2024-01-03T00:00:00.000Z", "open": 1.0, "high": 2.0,
                         "low": 3.0, "close": 4.0, "volume": 5, "adjOpen": 6.0,
                         "adjHigh": 7.0, "adjLow": 8.0, "adjClose": 9.0,
                         "adjVolume": 10.0, "divCash": 11.0, "splitFactor": 12.0}]}
        )


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
        from clients.models.bis import BisDataflow

        self.calls.append(("get_dataflows", {"agency": agency}))
        return [BisDataflow(id="WS_TC", name="Total credit")]

    async def get_datastructure(self, dsd_id: str, agency: str = "BIS") -> Any:
        from clients.models.bis import BisCodelist, BisDataStructure, BisDimension

        self.calls.append(("get_datastructure", {"dsd_id": dsd_id, "agency": agency}))
        return BisDataStructure(
            id=dsd_id,
            dimensions=[BisDimension(id="FREQ", codelist_id="CL_FREQ")],
            codelists={"CL_FREQ": BisCodelist(id="CL_FREQ", codes={"M": "Monthly", "A": "Annual"})},
        )

    async def get_data(self, flow: str, key: str = "all", **params: Any) -> Any:
        from clients.models.bis import BisDataResponse

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


async def test_category_children_uses_the_typed_client_method(monkeypatch):
    """It used to reach past the client to the private _get, which returned an
    unvalidated dict and left the tool with no response model to describe."""
    fake = RecordingFredClient()
    _patch_fred(monkeypatch, fake)

    result = await server.list_category_children(category_id=7)

    assert fake.calls == [("get_category_children", {"category_id": 7})]
    assert result.categories == []


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
    """A bare list yields no structuredContent, so the tool wraps it."""
    fake = RecordingBisClient()
    _patch_bis(monkeypatch, fake)

    result = await server.bis_dataflows()

    assert fake.calls == [("get_dataflows", {"agency": "BIS"})]
    assert result.dataflows[0].id == "WS_TC"


async def test_bis_datastructure_omits_codes_by_default(monkeypatch):
    """Codelists can hold 1000+ entries; the tool must not dump them unasked."""
    fake = RecordingBisClient()
    _patch_bis(monkeypatch, fake)

    result = await server.bis_datastructure(dsd_id="BIS_TOTAL_CREDIT")

    codelist = result.codelists["CL_FREQ"]
    assert codelist.codes == {}
    assert codelist.code_count == 2               # the count survives the omission
    assert [d.id for d in result.dimensions] == ["FREQ"]


async def test_bis_datastructure_include_codes(monkeypatch):
    fake = RecordingBisClient()
    _patch_bis(monkeypatch, fake)

    result = await server.bis_datastructure(dsd_id="BIS_TOTAL_CREDIT", include_codes=True)

    assert result.codelists["CL_FREQ"].codes == {"M": "Monthly", "A": "Annual"}


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
        from clients.models.cdc import CdcCatalogEntry

        self.calls.append(("discover", {"query": query, "category": category, "limit": limit}))
        return [CdcCatalogEntry(id="w9j2-ggv5", name="Life expectancy")]

    async def categories(self) -> Any:
        from clients.models.cdc import CdcCategory

        self.calls.append(("categories", {}))
        return [CdcCategory(category="National Center for Health Statistics", count=287)]

    async def tags(self) -> Any:
        from clients.models.cdc import CdcTag

        self.calls.append(("tags", {}))
        return [CdcTag(tag="mortality", count=117)]

    async def columns(self, dataset_id: str) -> Any:
        from clients.models.cdc import CdcColumn, CdcDataset

        self.calls.append(("columns", {"dataset_id": dataset_id}))
        return CdcDataset(id=dataset_id, name="LE", columns=[CdcColumn(field_name="year")])

    async def query(self, dataset_id: str, **params: Any) -> Any:
        from clients.models.cdc import CdcDataResponse

        self.calls.append(("query", {"dataset_id": dataset_id, **params}))
        return CdcDataResponse(dataset_id=dataset_id, rows=[{"year": "1900"}])


def _patch_cdc(monkeypatch, fake: RecordingCdcClient) -> None:
    async def fake_call_cdc(handler):
        return await handler(fake)

    monkeypatch.setattr(server, "_call_cdc", fake_call_cdc)


async def test_cdc_discover_wraps_list(monkeypatch):
    """A bare list yields no structuredContent, so the tool wraps it."""
    fake = RecordingCdcClient()
    _patch_cdc(monkeypatch, fake)

    result = await server.cdc_discover(query="life expectancy")

    assert fake.calls == [("discover", {"query": "life expectancy", "category": None, "limit": 20})]
    assert result.datasets[0].id == "w9j2-ggv5"


async def test_cdc_dataset_columns(monkeypatch):
    fake = RecordingCdcClient()
    _patch_cdc(monkeypatch, fake)

    result = await server.cdc_dataset_columns(dataset_id="w9j2-ggv5")

    assert fake.calls == [("columns", {"dataset_id": "w9j2-ggv5"})]
    assert result.columns[0].field_name == "year"


async def test_cdc_series_data_builds_soql_from_named_facets(monkeypatch):
    """The caller names facets; the server owns every column name and literal."""
    fake = RecordingCdcClient()
    _patch_cdc(monkeypatch, fake)

    result = await server.cdc_series_data(
        dataset_id="w9j2-ggv5", concept="life_expectancy",
        race="black", sex="female", year_start=1950, year_end=2000, limit=5,
    )

    name, params = fake.calls[0]
    assert name == "query"
    assert params["dataset_id"] == "w9j2-ggv5"
    # canonical tokens became this dataset's literals
    assert set(params["where"].split(" AND ")) == {
        "race='Black'", "sex='Female'", "year >= '1950'", "year <= '2000'",
    }
    assert params["select"] == "year AS year, average_life_expectancy AS value"
    assert params["limit"] == 5
    # typed response model -> the tool advertises a real output schema
    assert result.rows[0].year == "1900"
    assert result.row_count == len(result.rows)
    assert result.where == params["where"]      # provenance: an output, not an input


async def test_cdc_series_data_rejects_soql_injection_through_a_facet():
    """Facet values are validated against a vocabulary, never interpolated raw."""
    with pytest.raises(cdc_query.CdcQueryError, match="not valid"):
        await server.cdc_series_data(
            dataset_id="w9j2-ggv5", concept="life_expectancy",
            race="all' OR 1=1 --",
        )


async def test_cdc_series_data_names_valid_values_on_a_bad_token():
    """An error has to be actionable: the enums are a union across datasets."""
    with pytest.raises(cdc_query.CdcQueryError) as excinfo:
        await server.cdc_series_data(
            dataset_id="w9j2-ggv5", concept="life_expectancy", race="hispanic",
        )
    assert "all, black, white" in str(excinfo.value)


async def test_cdc_dataset_facets_reports_the_per_dataset_subset():
    result = await server.cdc_dataset_facets(
        dataset_id="w9j2-ggv5", concept="life_expectancy"
    )
    assert result.facets["race"] == ["all", "black", "white"]


async def test_cdc_categories(monkeypatch):
    fake = RecordingCdcClient()
    _patch_cdc(monkeypatch, fake)

    result = await server.cdc_categories()

    assert fake.calls == [("categories", {})]
    assert result.categories[0].category == "National Center for Health Statistics"
    assert result.categories[0].count == 287


async def test_cdc_tags(monkeypatch):
    fake = RecordingCdcClient()
    _patch_cdc(monkeypatch, fake)

    result = await server.cdc_tags()

    assert fake.calls == [("tags", {})]
    assert result.tags[0].tag == "mortality"


# --- time-series source tools ------------------------------------------------


class RecordingTimeSeriesSourceClient:
    """Fake TimeSeriesSourceClient returning the real pydantic models."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @staticmethod
    def _ref(**over: Any) -> Any:
        from mcp_server.timeseries_source_models import TimeSeriesRef

        base = dict(
            source="cdc_wonder",
            native_id="cdc/alcohol_induced/wonder/national/age_adjusted",
            title="Alcohol-induced deaths, age-adjusted rate, United States",
            frequency="Annual",
            units="deaths per 100,000",
            observation_count=26,
        )
        base.update(over)
        return TimeSeriesRef(**base)

    async def list_series(self, source: Any = None) -> Any:
        self.calls.append(("list_series", {"source": source}))
        return [self._ref()]

    async def list_stale(self, source: Any = None) -> Any:
        self.calls.append(("list_stale", {"source": source}))
        return [self._ref(native_id="cdc/life_expectancy/nvsr/race=all/sex=both",
                          source="cdc_nvsr", stale=True)]

    async def get_series(self, source: str, native_id: str, frequency: Any = None) -> Any:
        from mcp_server.timeseries_source_models import Observation, TimeSeriesRecord

        self.calls.append(
            ("get_series", {"source": source, "native_id": native_id, "frequency": frequency})
        )
        return TimeSeriesRecord(
            **self._ref().model_dump(),
            metadata={"observation_count": 1},
            observations=[Observation(date="1999-01-01", value="7.1", deaths=19469)],
        )


def _patch_timeseries_source(monkeypatch, fake: RecordingTimeSeriesSourceClient) -> None:
    async def fake_call(handler):
        payload = await handler(fake)
        return (server.TimeSeriesRefList(series=payload)
                if isinstance(payload, list) else payload)

    monkeypatch.setattr(server, "_call_timeseries_source", fake_call)


async def test_timeseries_source_list_wraps_series(monkeypatch):
    """A bare list yields no structuredContent, so the tool wraps it."""
    fake = RecordingTimeSeriesSourceClient()
    _patch_timeseries_source(monkeypatch, fake)

    result = await server.timeseries_source_list()

    assert fake.calls == [("list_series", {"source": None})]
    assert result.series[0].source == "cdc_wonder"


async def test_timeseries_source_list_passes_source_filter(monkeypatch):
    fake = RecordingTimeSeriesSourceClient()
    _patch_timeseries_source(monkeypatch, fake)

    await server.timeseries_source_list(source="cdc_nvsr")

    assert fake.calls == [("list_series", {"source": "cdc_nvsr"})]


async def test_timeseries_source_data_passes_frequency(monkeypatch):
    fake = RecordingTimeSeriesSourceClient()
    _patch_timeseries_source(monkeypatch, fake)

    result = await server.timeseries_source_data(
        source="cdc_wonder", native_id="a/b", frequency="Annual"
    )

    assert fake.calls == [
        ("get_series", {"source": "cdc_wonder", "native_id": "a/b", "frequency": "Annual"})
    ]
    # observations survive, including the extra WONDER keys the model allows
    assert result.observations[0].value == "7.1"
    assert result.observations[0].model_dump()["deaths"] == 19469


async def test_timeseries_source_stale_returns_flagged_series(monkeypatch):
    fake = RecordingTimeSeriesSourceClient()
    _patch_timeseries_source(monkeypatch, fake)

    result = await server.timeseries_source_stale()

    assert fake.calls == [("list_stale", {"source": None})]
    assert result.series[0].stale is True


async def test_dataset_facets_needs_a_concept_only_when_it_changes_the_answer():
    """The registry is keyed by (dataset_id, concept) because neither is unique
    alone, but the facet vocabulary is usually shared across a dataset's
    concepts. Demanding one that cannot change the answer is friction."""
    # w9j2-ggv5 serves life_expectancy and mortality with identical facets
    shared = await server.cdc_dataset_facets(dataset_id="w9j2-ggv5")
    explicit = await server.cdc_dataset_facets(
        dataset_id="w9j2-ggv5", concept="life_expectancy"
    )
    assert shared.facets == explicit.facets == {"race": ["all", "black", "white"],
                                                "sex": ["both", "female", "male"]}

    # hksd-2xuw genuinely differs: alcohol_consumption has no breakdowns
    with pytest.raises(cdc_query.CdcQueryError, match="different facets per concept"):
        await server.cdc_dataset_facets(dataset_id="hksd-2xuw")

    consumption = await server.cdc_dataset_facets(
        dataset_id="hksd-2xuw", concept="alcohol_consumption"
    )
    binge = await server.cdc_dataset_facets(
        dataset_id="hksd-2xuw", concept="alcohol_binge"
    )
    assert sorted(consumption.facets) == ["state"]
    assert "race" in binge.facets


async def test_fetching_still_requires_the_concept():
    """Relaxing the facets tool must not relax the data tool: w9j2-ggv5's two
    concepts read different value columns, so a guess would return wrong data."""
    with pytest.raises(cdc_query.CdcQueryError, match="serves several concepts"):
        await server.cdc_series_data(dataset_id="w9j2-ggv5", race="all", sex="both")
