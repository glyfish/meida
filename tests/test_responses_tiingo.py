"""Tests for the published Tiingo response models (``mcp_server/responses/tiingo.py``).

Pure: navi models are hand-built, nothing touches the network. What these guard
is the contract the MCP tools publish -- snake_case property names, no vendor
aliases, ISO dates, and that mapping never silently loses a price row.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from clients.models.tiingo import TiingoMeta, TiingoPrice, TiingoPriceSeries

from mcp_server.responses import tiingo as responses


ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- Builders ----------------------------------------------------------------


def _navi_price(date: str = "2024-01-03T00:00:00.000Z", **overrides) -> TiingoPrice:
    """A navi price row, validated from Tiingo's own camelCase wire payload."""
    payload = {
        "date": date,
        "open": 184.22,
        "high": 185.88,
        "low": 183.43,
        "close": 184.25,
        "volume": 58414460,
        "adjOpen": 184.10,
        "adjHigh": 185.70,
        "adjLow": 183.30,
        "adjClose": 184.05,
        "adjVolume": 58414460.0,
        "divCash": 0.24,
        "splitFactor": 2.0,
    }
    payload.update(overrides)
    return TiingoPrice.model_validate(payload)


def _navi_meta(**overrides) -> TiingoMeta:
    payload = {
        "ticker": "AAPL",
        "name": "Apple Inc",
        "exchangeCode": "NASDAQ",
        "startDate": "1980-12-12",
        "endDate": "2024-01-03",
        "description": "Apple Inc. designs and sells consumer electronics.",
    }
    payload.update(overrides)
    return TiingoMeta.model_validate(payload)


# --- Field renaming ----------------------------------------------------------


def test_price_row_renames_every_camel_case_alias():
    row = responses.from_tiingo_price(_navi_price())

    assert row.adj_open == 184.10
    assert row.adj_high == 185.70
    assert row.adj_low == 183.30
    assert row.adj_close == 184.05
    assert row.adj_volume == 58414460.0
    assert row.div_cash == 0.24
    assert row.split_factor == 2.0


def test_price_row_dump_carries_no_vendor_alias():
    dumped = responses.from_tiingo_price(_navi_price()).model_dump()

    for alias in (
        "adjOpen",
        "adjHigh",
        "adjLow",
        "adjClose",
        "adjVolume",
        "divCash",
        "splitFactor",
    ):
        assert alias not in dumped
    assert set(dumped) == {
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adj_open",
        "adj_high",
        "adj_low",
        "adj_close",
        "adj_volume",
        "div_cash",
        "split_factor",
    }


def test_series_info_renames_meta_aliases():
    info = responses.from_tiingo_meta(_navi_meta())

    assert info.exchange_code == "NASDAQ"
    assert info.start_date == "1980-12-12"
    assert info.end_date == "2024-01-03"
    dumped = info.model_dump()
    for alias in ("exchangeCode", "startDate", "endDate"):
        assert alias not in dumped


def test_raw_ohlcv_columns_are_carried_through():
    row = responses.from_tiingo_price(_navi_price())

    assert (row.open, row.high, row.low, row.close) == (184.22, 185.88, 183.43, 184.25)
    assert row.volume == 58414460


# --- Published JSON Schema ---------------------------------------------------


@pytest.mark.parametrize(
    "model",
    [responses.TiingoSeriesInfo, responses.TiingoPriceRow, responses.TiingoPriceSeries],
)
def test_schema_properties_are_snake_case_only(model):
    schema = model.model_json_schema()
    for name in schema["properties"]:
        assert name == name.lower(), f"{model.__name__}.{name} is not lower-case"
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name), f"{model.__name__}.{name} is not snake_case"


@pytest.mark.parametrize(
    "model",
    [responses.TiingoSeriesInfo, responses.TiingoPriceRow, responses.TiingoPriceSeries],
)
def test_every_schema_property_is_documented(model):
    schema = model.model_json_schema()
    for name, spec in schema["properties"].items():
        assert spec.get("description"), f"{model.__name__}.{name} has no description"


def test_nested_price_row_schema_is_snake_case_too():
    schema = responses.TiingoPriceSeries.model_json_schema()
    row_schema = schema["$defs"]["TiingoPriceRow"]
    assert all(name == name.lower() for name in row_schema["properties"])


# --- Envelope / request-echo removal ----------------------------------------


def test_series_response_drops_transport_and_request_echo_fields():
    series = responses.from_tiingo_price_series(
        TiingoPriceSeries(ticker="AAPL", prices=[_navi_price()])
    )
    dumped = series.model_dump()

    assert set(dumped) == {"ticker", "count", "prices"}
    for dropped in ("status", "response_time", "message", "offset", "limit", "sort_order"):
        assert dropped not in dumped


def test_count_reports_rows_returned():
    dates = ["2024-01-02T00:00:00.000Z", "2024-01-03T00:00:00.000Z", "2024-01-04T00:00:00.000Z"]
    series = responses.from_tiingo_price_series(
        TiingoPriceSeries(ticker="AAPL", prices=[_navi_price(d) for d in dates])
    )

    assert series.count == 3
    assert series.count == len(series.prices)


# --- Date derivation ---------------------------------------------------------


def test_price_date_is_iso_day_not_timestamp():
    row = responses.from_tiingo_price(_navi_price("2024-01-03T00:00:00.000Z"))

    assert row.date == "2024-01-03"
    assert ISO_DATE.fullmatch(row.date)


def test_price_date_drops_a_nonzero_time_component():
    row = responses.from_tiingo_price(_navi_price("2024-03-11T21:30:00.000Z"))

    assert row.date == "2024-03-11"


def test_meta_dates_are_iso_strings_not_date_objects():
    info = responses.from_tiingo_meta(_navi_meta())

    assert isinstance(info.start_date, str)
    assert isinstance(info.end_date, str)
    assert ISO_DATE.fullmatch(info.start_date)
    assert ISO_DATE.fullmatch(info.end_date)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("2024-01-03", "2024-01-03"),
        ("2024-01-03T00:00:00.000Z", "2024-01-03"),
        ("2024-01-03 00:00:00", "2024-01-03"),
    ],
)
def test_iso_date_helper_normalizes_vendor_shapes(value, expected):
    assert responses._iso_date(value) == expected


# --- Empty / None inputs -----------------------------------------------------


def test_mappers_are_total_on_none():
    """The container mappers return an empty record, not None.

    server.py serializes whatever a tool returns and cannot accept None, so the
    two mappers wired into tools are total the way the fred and bls ones are.
    from_tiingo_price maps a single row and is allowed to return None, since its
    caller filters.
    """
    assert responses.from_tiingo_meta(None) == responses.TiingoSeriesInfo(ticker="", name="")
    assert responses.from_tiingo_price(None) is None
    empty = responses.from_tiingo_price_series(None)
    assert empty.prices == [] and empty.count == 0


def test_meta_with_only_required_fields_maps_to_all_none_optionals():
    info = responses.from_tiingo_meta(TiingoMeta.model_validate({"ticker": "VOO", "name": "Vanguard S&P 500 ETF"}))

    assert info.ticker == "VOO"
    assert info.exchange_code is None
    assert info.start_date is None
    assert info.end_date is None
    assert info.description is None


def test_empty_price_series_maps_to_empty_list_and_zero_count():
    series = responses.from_tiingo_price_series(TiingoPriceSeries(ticker="AAPL"))

    assert series.ticker == "AAPL"
    assert series.count == 0
    assert series.prices == []


# --- No observation is dropped ----------------------------------------------


def test_every_row_survives_mapping_in_order():
    dates = [f"2024-01-{day:02d}T00:00:00.000Z" for day in range(2, 27)]
    navi_series = TiingoPriceSeries(
        ticker="AAPL",
        prices=[_navi_price(d, close=100.0 + i) for i, d in enumerate(dates)],
    )

    series = responses.from_tiingo_price_series(navi_series)

    assert len(series.prices) == len(navi_series.prices)
    assert [row.date for row in series.prices] == [f"2024-01-{day:02d}" for day in range(2, 27)]
    assert [row.close for row in series.prices] == [100.0 + i for i in range(len(dates))]


def test_duplicate_dates_are_not_deduplicated():
    navi_series = TiingoPriceSeries(
        ticker="AAPL",
        prices=[_navi_price("2024-01-03T00:00:00.000Z") for _ in range(3)],
    )

    series = responses.from_tiingo_price_series(navi_series)

    assert series.count == 3
    assert len(series.prices) == 3


# --- Immutability ------------------------------------------------------------


def test_published_models_are_frozen():
    series = responses.from_tiingo_price_series(TiingoPriceSeries(ticker="AAPL"))
    with pytest.raises(Exception):
        series.ticker = "MSFT"


# --- Drift and mis-wiring guards ---------------------------------------------
#
# The tests above assert on a handful of fields, which lets a dropped or
# cross-wired field pass unnoticed: a mutation run showed `description=None`,
# `name=meta.ticker` and `adj_volume=float(volume)` all surviving the suite.
# These two tests close that by giving every field a value unique in the payload,
# so any field reading from the wrong source is caught by value, and by asserting
# the published models still cover navi's fields, so a field navi adds later
# cannot be silently dropped.


def _distinct_price() -> TiingoPrice:
    """A price row where no two numbers are equal.

    The shared builder sets adjVolume == volume, which is exactly why an
    `adj_volume=float(price.volume)` mutation went undetected.
    """
    return TiingoPrice.model_validate({
        "date": "2024-01-03T00:00:00.000Z",
        "open": 1.0, "high": 2.0, "low": 3.0, "close": 4.0, "volume": 5,
        "adjOpen": 6.0, "adjHigh": 7.0, "adjLow": 8.0, "adjClose": 9.0,
        "adjVolume": 10.0, "divCash": 11.0, "splitFactor": 12.0,
    })


def test_every_price_field_maps_from_its_own_source():
    row = responses.from_tiingo_price(_distinct_price())

    assert (row.date, row.open, row.high, row.low, row.close, row.volume) == (
        "2024-01-03", 1.0, 2.0, 3.0, 4.0, 5)
    assert (row.adj_open, row.adj_high, row.adj_low, row.adj_close, row.adj_volume) == (
        6.0, 7.0, 8.0, 9.0, 10.0)
    assert (row.div_cash, row.split_factor) == (11.0, 12.0)


def test_every_meta_field_maps_from_its_own_source():
    info = responses.from_tiingo_meta(_navi_meta())

    assert info.ticker == "AAPL"
    assert info.name == "Apple Inc"                      # never asserted before
    assert info.exchange_code == "NASDAQ"
    assert info.start_date == "1980-12-12"
    assert info.end_date == "2024-01-03"
    assert info.description.startswith("Apple Inc. designs")   # never asserted non-None


@pytest.mark.parametrize("navi_model, published", [
    (TiingoMeta, responses.TiingoSeriesInfo),
    (TiingoPrice, responses.TiingoPriceRow),
])
def test_published_model_covers_every_navi_field(navi_model, published):
    """A field navi adds later must not vanish silently from the published schema."""
    missing = set(navi_model.model_fields) - set(published.model_fields)
    assert not missing, f"{published.__name__} does not carry: {sorted(missing)}"


def test_a_dropped_row_is_visible_in_the_count():
    """count reflects what Tiingo sent, so a skipped row shows as a mismatch."""
    series = SimpleNamespace(ticker="AAPL", prices=[_distinct_price(), None])
    out = responses.from_tiingo_price_series(series)

    assert out.count == 2 and len(out.prices) == 1


@pytest.mark.parametrize("bad", ["01/03/2024", "2024-1-3", "2024-13-45T00:00:00Z",
                                 "nan", 20240103, []])
def test_malformed_vendor_dates_yield_none_not_a_date_shaped_string(bad):
    assert responses._iso_date(bad) is None
