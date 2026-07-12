"""Tests for navi's Tiingo pydantic models (``lib/clients/models/tiingo.py``).

Focus on camelCase alias mapping, optional-field defaults, and immutability.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from lib.clients.models.tiingo import TiingoMeta, TiingoPrice, TiingoPriceSeries


def test_price_maps_camel_case_aliases():
    price = TiingoPrice.model_validate(
        {
            "date": "2024-01-03T00:00:00.000Z",
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
            "splitFactor": 1.0,
        }
    )
    assert price.adj_open == 184.10
    assert price.adj_close == 184.05
    assert price.div_cash == 0.24
    assert price.split_factor == 1.0


def test_meta_alias_and_optional_defaults():
    meta = TiingoMeta.model_validate({"ticker": "AAPL", "name": "Apple Inc"})
    assert meta.exchange_code is None
    assert meta.start_date is None
    assert meta.end_date is None
    assert meta.description is None

    full = TiingoMeta.model_validate(
        {
            "ticker": "AAPL",
            "name": "Apple Inc",
            "exchangeCode": "NASDAQ",
            "startDate": "1980-12-12",
        }
    )
    assert full.exchange_code == "NASDAQ"
    assert str(full.start_date) == "1980-12-12"


def test_price_series_defaults_to_empty_prices():
    series = TiingoPriceSeries.model_validate({"ticker": "AAPL"})
    assert series.prices == []


def test_price_series_is_frozen():
    series = TiingoPriceSeries.model_validate({"ticker": "AAPL"})
    with pytest.raises(ValidationError):
        series.ticker = "MSFT"
