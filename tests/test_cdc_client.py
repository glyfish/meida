"""Tests for navi's ``CdcClient`` (``lib/clients/cdc.py``).

Uses ``httpx.MockTransport`` with small captured/crafted Socrata responses. CDC
needs no credentials; an optional app token is sent as ``X-App-Token``. These
assert SoQL param assembly, the token header, row/column/discovery parsing, the
cross-host discovery call, and error translation.
"""
from __future__ import annotations

import httpx
import pytest

from lib.clients import CdcAPIError, CdcClient
from lib.clients.models.cdc import CdcDataResponse, CdcDataset


async def test_query_builds_soql_and_parses_rows(make_cdc_client, load_cdc_fixture):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=load_cdc_fixture("resource_life_expectancy.json"))

    async with make_cdc_client(handler) as client:
        resp = await client.query(
            "w9j2-ggv5", where="race='All Races'", order="year", limit=3,
        )

    assert seen["path"] == "/resource/w9j2-ggv5.json"
    assert seen["params"]["$where"] == "race='All Races'"
    assert seen["params"]["$order"] == "year"
    assert seen["params"]["$limit"] == "3"
    assert isinstance(resp, CdcDataResponse)
    assert resp.row_count == 3
    assert resp.rows[0]["average_life_expectancy"] == "47.3"


async def test_optional_soql_params_omitted(make_cdc_client, load_cdc_fixture):
    """A bare query sends only $limit/$offset -- no empty $where/$select/etc."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=load_cdc_fixture("resource_life_expectancy.json"))

    async with make_cdc_client(handler) as client:
        await client.query("w9j2-ggv5")

    assert set(seen["params"]) == {"$limit", "$offset"}


async def test_app_token_header_sent_when_set(make_cdc_client, load_cdc_fixture):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("x-app-token")
        return httpx.Response(200, json=load_cdc_fixture("resource_life_expectancy.json"))

    async with make_cdc_client(handler, app_token="secret-abc") as client:
        await client.query("w9j2-ggv5")

    assert seen["token"] == "secret-abc"


async def test_no_token_header_when_absent(make_cdc_client, load_cdc_fixture):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = {k.lower() for k in request.headers}
        return httpx.Response(200, json=load_cdc_fixture("resource_life_expectancy.json"))

    async with make_cdc_client(handler, app_token="") as client:
        await client.query("w9j2-ggv5")

    assert "x-app-token" not in seen["headers"]


async def test_columns_parses_views(make_cdc_client, load_cdc_fixture):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/views/w9j2-ggv5.json"
        return httpx.Response(200, json=load_cdc_fixture("views_life_expectancy.json"))

    async with make_cdc_client(handler) as client:
        dataset = await client.columns("w9j2-ggv5")

    assert isinstance(dataset, CdcDataset)
    assert dataset.name == "NCHS - Death rates and life expectancy at birth"
    assert [c.field_name for c in dataset.columns] == [
        "year", "race", "sex", "average_life_expectancy", "mortality",
    ]
    life = next(c for c in dataset.columns if c.field_name == "average_life_expectancy")
    assert life.data_type == "number"


async def test_discover_hits_catalog_host(make_cdc_client, load_cdc_fixture):
    """Discovery targets the cross-domain host, not the portal base_url."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=load_cdc_fixture("discover_life_expectancy.json"))

    async with make_cdc_client(handler) as client:
        entries = await client.discover("life expectancy", limit=3)

    assert seen["host"] == "api.us.socrata.com"
    assert seen["params"]["domains"] == "data.cdc.gov"
    assert seen["params"]["q"] == "life expectancy"
    assert [e.id for e in entries] == ["w9j2-ggv5", "ss2j-8ajj"]
    assert entries[0].name.startswith("NCHS")
    assert entries[0].domain == "data.cdc.gov"


async def test_error_translation(make_cdc_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not found")

    async with make_cdc_client(handler) as client:
        with pytest.raises(CdcAPIError):
            await client.query("bad-id")


async def test_discover_with_category_filter(make_cdc_client, load_cdc_fixture):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=load_cdc_fixture("discover_life_expectancy.json"))

    async with make_cdc_client(handler) as client:
        await client.discover("mortality", category="National Center for Health Statistics")

    assert seen["params"]["q"] == "mortality"
    assert seen["params"]["categories"] == "National Center for Health Statistics"
    assert seen["params"]["search_context"] == "data.cdc.gov"


async def test_categories(make_cdc_client, load_cdc_fixture):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=load_cdc_fixture("categories.json"))

    async with make_cdc_client(handler) as client:
        categories = await client.categories()

    assert seen["path"].endswith("/domain_categories")
    assert seen["params"]["search_context"] == "data.cdc.gov"
    assert categories[0].category == "National Center for Health Statistics"
    assert categories[0].count == 287


async def test_tags(make_cdc_client, load_cdc_fixture):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/domain_tags")
        return httpx.Response(200, json=load_cdc_fixture("tags.json"))

    async with make_cdc_client(handler) as client:
        tags = await client.tags()

    assert {tag.tag for tag in tags} == {"mortality", "covid-19", "prevalence"}
    assert next(tag for tag in tags if tag.tag == "covid-19").count == 176
