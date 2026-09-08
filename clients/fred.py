"""Async client for the Federal Reserve Economic Data (FRED) API."""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional

import httpx

from lib.env import get_fred_api_key, get_fred_base_url
from .models.fred import (
    CategoryResponse,
    ObservationsResponse,
    ReleasesResponse,
    SeriesResponse,
)


class FredAPIError(RuntimeError):
    """Raised when the FRED API returns an error response."""


class FredClient:
    """Thin wrapper around the public FRED API."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.api_key = api_key or get_fred_api_key()
        self.base_url = (base_url or get_fred_base_url()).rstrip("/")
        self._client = client or httpx.AsyncClient(base_url=self.base_url, timeout=timeout)
        self._owns_client = client is None

    async def __aenter__(self) -> "FredClient":
        return self


    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()


    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        if self._owns_client:
            await self._client.aclose()


    async def _get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        query: MutableMapping[str, Any] = {"api_key": self.api_key, "file_type": "json"}
        if params:
            query.update(params)
        try:
            response = await self._client.get(path, params=query)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FredAPIError(f"FRED request failed: {exc.response.text}") from exc
        return response.json()


    async def get_category_children(self, category_id: int) -> CategoryResponse:
        """Return the subcategories for the given category."""
        data = await self._get("/category/children", {"category_id": category_id})
        return CategoryResponse.model_validate(data)


    async def get_category_series(self, category_id: int, **kwargs: Any) -> SeriesResponse:
        """Return the series that belong to the given category."""
        params = {"category_id": category_id}
        params.update(kwargs)
        data = await self._get("/category/series", params)
        return SeriesResponse.model_validate(data)


    async def get_series(self, series_id: str) -> SeriesResponse:
        """Fetch metadata about a FRED series."""
        data = await self._get("/series", {"series_id": series_id})
        return SeriesResponse.model_validate(data)


    async def get_series_updates(self, **kwargs: Any) -> SeriesResponse:
        """Return recently updated series."""
        data = await self._get("/series/updates", kwargs)
        return SeriesResponse.model_validate(data)


    async def get_series_observations(self, series_id: str, **kwargs: Any) -> ObservationsResponse:
        """Return observations for a series."""
        params = {"series_id": series_id}
        params.update(kwargs)
        data = await self._get("/series/observations", params)
        return ObservationsResponse.model_validate(data)


    async def get_releases(self, **kwargs: Any) -> ReleasesResponse:
        """Return all FRED releases."""
        data = await self._get("/releases", kwargs)
        return ReleasesResponse.model_validate(data)


    async def get_release_series(self, release_id: int, **kwargs: Any) -> SeriesResponse:
        """Return the series associated with a release."""
        params = {"release_id": release_id}
        params.update(kwargs)
        data = await self._get("/release/series", params)
        return SeriesResponse.model_validate(data)
