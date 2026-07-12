"""Tests for navi's ``BlsClient`` (``lib/clients/bls.py``).

Uses ``httpx.MockTransport`` to assert POST body assembly, registrationkey
injection, GET endpoints, model parsing, and BLS's HTTP-200-with-error-status
behavior. Response bodies come from the fixtures captured off the live API.
"""
from __future__ import annotations

import json

import httpx
import pytest

from lib.clients import BlsAPIError
from lib.clients.models.bls import BlsSeriesResponse, BlsSurveysResponse


async def test_series_data_builds_post_body(make_bls_client, load_bls_fixture):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=load_bls_fixture("series_data_full"))

    async with make_bls_client(handler) as client:
        result = await client.get_series_data(
            ["LNS14000000"], start_year=2022, end_year=2023, catalog=True, calculations=True
        )

    assert seen["method"] == "POST"
    assert seen["path"].endswith("/timeseries/data/")
    assert seen["body"] == {
        "seriesid": ["LNS14000000"],
        "startyear": "2022",
        "endyear": "2023",
        "catalog": True,
        "calculations": True,
        "registrationkey": "test-key",  # injected from the client's key
    }
    assert isinstance(result, BlsSeriesResponse)
    assert result.results.series[0].series_id == "LNS14000000"


async def test_series_data_omits_unset_flags_and_years(make_bls_client, load_bls_fixture):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=load_bls_fixture("series_data_full"))

    async with make_bls_client(handler) as client:
        await client.get_series_data(["LNS14000000", "CES0000000001"])

    assert seen["body"] == {"seriesid": ["LNS14000000", "CES0000000001"], "registrationkey": "test-key"}


async def test_non_success_status_raises(make_bls_client, load_bls_fixture):
    def handler(request: httpx.Request) -> httpx.Response:
        # BLS signals failure with HTTP 200 + status field.
        return httpx.Response(200, json=load_bls_fixture("error_not_processed"))

    with pytest.raises(BlsAPIError) as exc_info:
        async with make_bls_client(handler) as client:
            await client.get_series_data(["LNS14000000"])

    assert "invalid" in str(exc_info.value).lower()


async def test_success_with_warning_message_does_not_raise(make_bls_client, load_bls_fixture):
    def handler(request: httpx.Request) -> httpx.Response:
        # REQUEST_SUCCEEDED but with an advisory message (year range reduced).
        return httpx.Response(200, json=load_bls_fixture("error_span"))

    async with make_bls_client(handler) as client:
        result = await client.get_series_data(["LNS14000000"], start_year=1990, end_year=2023)

    assert result.status == "REQUEST_SUCCEEDED"
    assert result.message and "20 years" in result.message[0]


async def test_latest_uses_get_with_params(make_bls_client, load_bls_fixture):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=load_bls_fixture("latest_single"))

    async with make_bls_client(handler) as client:
        result = await client.get_series_latest("LNS14000000")

    assert seen["method"] == "GET"
    assert seen["path"].endswith("/timeseries/data/LNS14000000")
    assert seen["params"] == {"latest": "true", "registrationkey": "test-key"}
    assert result.results.series[0].data[0].latest == "true"


async def test_all_surveys(make_bls_client, load_bls_fixture):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/surveys")
        return httpx.Response(200, json=load_bls_fixture("all_surveys"))

    async with make_bls_client(handler) as client:
        result = await client.get_all_surveys()

    assert isinstance(result, BlsSurveysResponse)
    assert result.results.survey[0].survey_abbreviation == "AP"


async def test_survey_info(make_bls_client, load_bls_fixture):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/surveys/TU")
        return httpx.Response(200, json=load_bls_fixture("single_survey"))

    async with make_bls_client(handler) as client:
        result = await client.get_survey("TU")

    assert result.results.survey[0].has_annual_averages == "false"


async def test_popular_series_with_survey_param(make_bls_client, load_bls_fixture):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=load_bls_fixture("popular"))

    async with make_bls_client(handler) as client:
        await client.get_popular_series(survey="LA")

    assert seen["path"].endswith("/timeseries/popular")
    assert seen["params"]["survey"] == "LA"


async def test_http_error_wrapped(make_bls_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    with pytest.raises(BlsAPIError):
        async with make_bls_client(handler) as client:
            await client.get_all_surveys()


async def test_client_without_key_omits_registrationkey():
    """With an empty api_key, the POST body carries no registrationkey.

    (api_key="" represents "no key" without falling back to the environment,
    keeping the test hermetic.)
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "REQUEST_SUCCEEDED", "Results": {"series": []}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://bls.test/publicAPI/v2")
    from lib.clients import BlsClient

    client = BlsClient(api_key="", base_url="https://bls.test/publicAPI/v2", client=http)
    async with client:
        await client.get_series_data(["LNS14000000"])
    await http.aclose()

    assert "registrationkey" not in seen["body"]
