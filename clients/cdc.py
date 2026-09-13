"""Async client for the CDC Socrata (SODA) API.

CDC data lives on a Socrata portal (``data.cdc.gov``). Reading public data needs
**no credentials**; an optional Socrata **app token** (``CDC_API_KEY``) only
raises rate limits and is sent in the ``X-App-Token`` header when configured.

Two request shapes:

* **Data / metadata** on the portal host (``get_cdc_base_url()``): a dataset's
  rows via ``/resource/{id}.json`` (SoQL query params) and its columns via
  ``/api/views/{id}.json``.
* **Discovery** on Socrata's cross-domain catalog (``api.us.socrata.com``):
  search datasets within the CDC domain.

Socrata is one API over **many datasets with inconsistent schemas**, so this
client stays generic (fetch rows / columns / search) and returns rows as plain
dicts; per-dataset field mapping lives with the catalog export, not here. Every
value comes back as a string -- casting is left to the caller.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

import httpx

from environment import get_cdc_api_key, get_cdc_base_url
from .models.cdc import (
    CdcCatalogEntry,
    CdcCategory,
    CdcColumn,
    CdcDataResponse,
    CdcDataset,
    CdcTag,
)

CDC_USER_AGENT = "navi-cdc-client"

# Socrata's discovery API is a fixed, portal-independent host (not data.cdc.gov).
_DISCOVERY_URL = "https://api.us.socrata.com/api/catalog/v1"
_DISCOVERY_DOMAIN = "data.cdc.gov"


def _cached_contents(cached: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Pull the useful parts out of a column's ``cachedContents``.

    Socrata ships per-column value statistics alongside the schema. ``top`` is
    the most common values with counts (capped at 20); ``smallest``/``largest``
    bound a numeric column. ``cardinality`` is deliberately ignored -- it is the
    distinct count on some datasets and the row count on others, so it cannot be
    used to tell whether ``top`` is complete.
    """
    if not cached:
        return {}
    def _int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return {
        "cached_top": [
            {"item": t.get("item"), "count": _int(t.get("count"))}
            for t in (cached.get("top") or [])
            if isinstance(t, Mapping)
        ],
        "cached_smallest": cached.get("smallest"),
        "cached_largest": cached.get("largest"),
        "cached_non_null": _int(cached.get("non_null")),
        "cached_null": _int(cached.get("null")),
    }


class CdcAPIError(RuntimeError):
    """Raised when the CDC/Socrata API returns an error response."""


class CdcClient:
    """Thin wrapper around the CDC Socrata (SODA) API."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        app_token: Optional[str] = None,
        timeout: float = 60.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = (base_url or get_cdc_base_url()).rstrip("/")
        # Optional app token -- only raises rate limits; None is fine. Sent as a
        # per-request header (see ``_auth_headers``) so it applies whether or not
        # the caller injects their own httpx client.
        self._app_token = app_token if app_token is not None else get_cdc_api_key()
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"User-Agent": CDC_USER_AGENT},
        )
        self._owns_client = client is None

    def _auth_headers(self) -> dict[str, str]:
        """The ``X-App-Token`` header, when an app token is configured."""
        return {"X-App-Token": self._app_token} if self._app_token else {}

    async def __aenter__(self) -> "CdcClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        if self._owns_client:
            await self._client.aclose()

    async def _get(
        self, url: str, params: Optional[Mapping[str, Any]] = None
    ) -> httpx.Response:
        try:
            response = await self._client.get(url, params=params, headers=self._auth_headers())
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CdcAPIError(f"CDC request failed: {exc.response.text}") from exc
        return response

    async def query(
        self,
        dataset_id: str,
        *,
        where: Optional[str] = None,
        select: Optional[str] = None,
        order: Optional[str] = None,
        group: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> CdcDataResponse:
        """Fetch rows from a dataset via SoQL.

        Socrata caps a single page; use ``limit``/``offset`` (or ``iter_all``) to
        page. Values come back as strings.
        """
        params: dict[str, Any] = {"$limit": limit, "$offset": offset}
        if where:
            params["$where"] = where
        if select:
            params["$select"] = select
        if order:
            params["$order"] = order
        if group:
            params["$group"] = group
        response = await self._get(f"/resource/{dataset_id}.json", params=params)
        return CdcDataResponse(dataset_id=dataset_id, rows=response.json())

    async def iter_all(
        self,
        dataset_id: str,
        *,
        where: Optional[str] = None,
        select: Optional[str] = None,
        order: Optional[str] = None,
        page_size: int = 50_000,
    ) -> list[dict[str, Any]]:
        """Page through a whole dataset (or filtered slice) and return all rows.

        Pages by ``$offset`` until a short page is returned. Passing a stable
        ``order`` key is recommended for consistent paging.
        """
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self.query(
                dataset_id, where=where, select=select, order=order,
                limit=page_size, offset=offset,
            )
            rows.extend(page.rows)
            if len(page.rows) < page_size:
                break
            offset += page_size
        return rows

    async def columns(self, dataset_id: str) -> CdcDataset:
        """Fetch a dataset's metadata + columns from ``/api/views/{id}.json``."""
        response = await self._get(f"/api/views/{dataset_id}.json")
        payload = response.json()
        columns = [
            CdcColumn(
                field_name=c.get("fieldName"),
                name=c.get("name"),
                data_type=c.get("dataTypeName"),
                description=c.get("description"),
                **_cached_contents(c.get("cachedContents")),
            )
            for c in payload.get("columns", [])
            if c.get("fieldName")
        ]
        return CdcDataset(
            id=dataset_id,
            name=payload.get("name"),
            description=payload.get("description"),
            columns=columns,
        )

    async def discover(
        self, query: str = "", *, category: Optional[str] = None, limit: int = 20
    ) -> list[CdcCatalogEntry]:
        """Search the CDC Socrata catalog for datasets.

        Filter by keyword (``query``) and/or ``category`` (a domain category from
        ``categories()``). Hits the cross-domain discovery host (absolute URL),
        so it bypasses the portal ``base_url``.
        """
        params: dict[str, Any] = {"domains": _DISCOVERY_DOMAIN, "q": query, "limit": limit}
        if category:
            # Domain categories require search_context; plain `domains` returns 0.
            params["categories"] = category
            params["search_context"] = _DISCOVERY_DOMAIN
        try:
            response = await self._client.get(
                _DISCOVERY_URL, params=params, headers=self._auth_headers()
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CdcAPIError(f"CDC discovery failed: {exc.response.text}") from exc
        entries: list[CdcCatalogEntry] = []
        for result in response.json().get("results", []):
            res = result.get("resource", {})
            entries.append(
                CdcCatalogEntry(
                    id=res.get("id"),
                    name=res.get("name"),
                    description=res.get("description"),
                    domain=(result.get("metadata") or {}).get("domain"),
                )
            )
        return entries

    async def categories(self) -> list[CdcCategory]:
        """List the CDC domain's categories and their dataset counts."""
        results = await self._catalog_facet("domain_categories")
        return [
            CdcCategory(category=r["domain_category"], count=r.get("count", 0))
            for r in results
            if r.get("domain_category")
        ]

    async def tags(self) -> list[CdcTag]:
        """List the CDC domain's tags and their dataset counts."""
        results = await self._catalog_facet("domain_tags")
        return [
            CdcTag(tag=r["domain_tag"], count=r.get("count", 0))
            for r in results
            if r.get("domain_tag")
        ]

    async def _catalog_facet(self, facet: str) -> list[dict[str, Any]]:
        """GET a catalog facet endpoint (``domain_categories`` / ``domain_tags``)."""
        params = {"search_context": _DISCOVERY_DOMAIN}
        try:
            response = await self._client.get(
                f"{_DISCOVERY_URL}/{facet}", params=params, headers=self._auth_headers()
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CdcAPIError(f"CDC {facet} failed: {exc.response.text}") from exc
        return response.json().get("results", [])
