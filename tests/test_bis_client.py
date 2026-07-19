"""Tests for navi's ``BisClient`` (``lib/clients/bis.py``).

Uses ``httpx.MockTransport`` with responses captured from the live BIS API:
SDMX-JSON for structure, CSV for data. BIS needs no credentials, so these
assert request shape, the SDMX-JSON Accept version, CSV grouping into series,
and error translation.
"""
from __future__ import annotations

import httpx
import pytest

from lib.clients import BisAPIError, BisClient
from lib.clients.models.bis import BisDataResponse, BisDataStructure


async def test_get_dataflows_parses_structure(make_bis_client, load_bis_fixture):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["accept"] = request.headers.get("accept")
        return httpx.Response(200, json=load_bis_fixture("dataflows.json"))

    async with make_bis_client(handler) as client:
        flows = await client.get_dataflows()

    assert seen["path"].endswith("/dataflow/BIS")
    # BIS rejects a bare "version=1.0" with HTTP 406; the exact version matters.
    assert "version=1.0.0" in seen["accept"]
    assert len(flows) == 29
    by_id = {f.id: f for f in flows}
    assert by_id["WS_CBPOL"].name == "Central bank policy rates"
    assert by_id["WS_TC"].name == "Total credit"


async def test_no_credentials_are_sent(make_bis_client, load_bis_fixture):
    """BIS is unauthenticated - no key, header, or token should appear."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = {k.lower() for k in request.headers}
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=load_bis_fixture("dataflows.json"))

    async with make_bis_client(handler) as client:
        await client.get_dataflows()

    assert "authorization" not in seen["headers"]
    assert "x-api-key" not in seen["headers"]
    assert not {"api_key", "token", "registrationkey"} & set(seen["params"])


async def test_datastructure_dimensions_and_codelists(make_bis_client, load_bis_fixture):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=load_bis_fixture("datastructure_total_credit.json"))

    async with make_bis_client(handler) as client:
        dsd = await client.get_datastructure("BIS_TOTAL_CREDIT")

    assert seen["path"].endswith("/datastructure/BIS/BIS_TOTAL_CREDIT")
    assert seen["params"]["references"] == "children"  # pulls codelists in one call
    assert isinstance(dsd, BisDataStructure)
    assert [d.id for d in dsd.dimensions] == [
        "FREQ", "BORROWERS_CTY", "TC_BORROWERS", "TC_LENDERS",
        "VALUATION", "UNIT_TYPE", "TC_ADJUST",
    ]
    # Dimension -> codelist wiring, parsed out of the SDMX urn.
    assert dsd.dimensions[1].codelist_id == "CL_AREA"


async def test_datastructure_decodes_codes(make_bis_client, load_bis_fixture):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_bis_fixture("datastructure_total_credit.json"))

    async with make_bis_client(handler) as client:
        dsd = await client.get_datastructure("BIS_TOTAL_CREDIT")

    assert dsd.decode("BORROWERS_CTY", "US") == "United States"
    assert dsd.decode("TC_BORROWERS", "P") == "Private non-financial sector"
    # Unknown codes and unknown dimensions fall back to the raw code.
    assert dsd.decode("BORROWERS_CTY", "ZZZZ") == "ZZZZ"
    assert dsd.decode("NOT_A_DIMENSION", "US") == "US"


async def test_get_data_groups_csv_into_series(make_bis_client, load_bis_fixture):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, text=load_bis_fixture("data_cbpol.csv"))

    async with make_bis_client(handler) as client:
        data = await client.get_data("WS_CBPOL", "M.US+GB", start_period="2025-01")

    assert seen["path"].endswith("/data/WS_CBPOL/M.US+GB/all")
    assert seen["params"]["format"] == "csv"
    assert seen["params"]["startPeriod"] == "2025-01"
    assert isinstance(data, BisDataResponse)
    # One CSV with rows for two countries must split into two series.
    assert data.series_count == 2
    assert [s.key for s in data.series] == ["M.GB.368", "M.US.368"]


async def test_observations_are_typed_and_sorted(make_bis_client, load_bis_fixture):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=load_bis_fixture("data_cbpol.csv"))

    async with make_bis_client(handler) as client:
        data = await client.get_data("WS_CBPOL", "M.US+GB")

    series = next(s for s in data.series if s.key.startswith("M.US"))
    assert series.title and series.title.startswith("Central bank policy rates")
    assert series.observations == sorted(series.observations, key=lambda o: o.time_period)
    first = series.observations[0]
    assert isinstance(first.value, float)
    assert first.time_period == "2025-01"


async def test_omitted_optional_periods(make_bis_client, load_bis_fixture):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, text=load_bis_fixture("data_cbpol.csv"))

    async with make_bis_client(handler) as client:
        await client.get_data("WS_CBPOL")

    assert seen["params"] == {"format": "csv"}  # no empty startPeriod/endPeriod


async def test_http_error_wrapped(make_bis_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="<message:Error>no such flow</message:Error>")

    with pytest.raises(BisAPIError) as exc_info:
        async with make_bis_client(handler) as client:
            await client.get_data("WS_NOT_A_FLOW")

    assert "no such flow" in str(exc_info.value)


async def test_empty_datastructure_raises(make_bis_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"dataStructures": []}})

    with pytest.raises(BisAPIError):
        async with make_bis_client(handler) as client:
            await client.get_datastructure("NOPE")


async def test_injected_client_not_owned(make_bis_client):
    client = make_bis_client(lambda request: httpx.Response(200, json={}))
    assert client._owns_client is False
