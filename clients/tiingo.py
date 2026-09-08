"""Async client for the Tiingo end-of-day (EOD) price API."""

from __future__ import annotations

from typing import Any, Mapping, Optional

import httpx

from lib.env import get_tiingo_api_key, get_tiingo_base_url
from .models.tiingo import TiingoMeta, TiingoPrice, TiingoPriceSeries


class TiingoAPIError(RuntimeError):
    """Raised when the Tiingo API returns an error response."""


class TiingoClient:
    """Thin wrapper around the Tiingo end-of-day price API."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.api_key = api_key or get_tiingo_api_key()
        self.base_url = (base_url or get_tiingo_base_url()).rstrip("/")
        self._client = client or httpx.AsyncClient(base_url=self.base_url, timeout=timeout)
        self._owns_client = client is None


    async def __aenter__(self) -> "TiingoClient":
        return self


    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()


    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        if self._owns_client:
            await self._client.aclose()


    async def _get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        headers = {"Authorization": f"Token {self.api_key}", "Content-Type": "application/json"}
        try:
            response = await self._client.get(path, params=params, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TiingoAPIError(f"Tiingo request failed: {exc.response.text}") from exc
        return response.json()


    async def get_meta(self, ticker: str) -> TiingoMeta:
        """Fetch metadata for a ticker (ETF, mutual fund, or stock), including its date range."""
        data = await self._get(f"/daily/{ticker}")
        return TiingoMeta.model_validate(data)


    async def get_prices(
        self,
        ticker: str,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        resample_freq: Optional[str] = None,
    ) -> TiingoPriceSeries:
        """Return the EOD price series for a ticker over an optional date range."""
        params: dict[str, Any] = {}
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        if resample_freq:
            params["resampleFreq"] = resample_freq
        data = await self._get(f"/daily/{ticker}/prices", params)
        prices = [TiingoPrice.model_validate(row) for row in data]
        return TiingoPriceSeries(ticker=ticker.upper(), prices=prices)
