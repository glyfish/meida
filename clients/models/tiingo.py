"""Typed models describing Tiingo end-of-day (EOD) API payloads."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class TiingoBaseModel(BaseModel):
    """Base config for immutable Tiingo models."""

    model_config = {"frozen": True}


class TiingoMeta(TiingoBaseModel):
    ticker: str
    name: str
    exchange_code: Optional[str] = Field(default=None, alias="exchangeCode")
    start_date: Optional[date] = Field(default=None, alias="startDate")
    end_date: Optional[date] = Field(default=None, alias="endDate")
    description: Optional[str] = None


class TiingoPrice(TiingoBaseModel):
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    adj_open: float = Field(alias="adjOpen")
    adj_high: float = Field(alias="adjHigh")
    adj_low: float = Field(alias="adjLow")
    adj_close: float = Field(alias="adjClose")
    adj_volume: float = Field(alias="adjVolume")
    div_cash: float = Field(alias="divCash")
    split_factor: float = Field(alias="splitFactor")


class TiingoPriceSeries(TiingoBaseModel):
    ticker: str
    prices: List[TiingoPrice] = Field(default_factory=list)
