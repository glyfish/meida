"""Async client for the Bank for International Settlements (BIS) SDMX API.

Unlike the other clients here, BIS requires **no credentials** -- there is no
API key, header, or query token. It differs in two further ways:

* Structure requests (dataflows, DSDs, codelists) return SDMX-JSON, and the
  version must be given exactly: ``version=1.0.0`` or ``2.0.0``. A bare
  ``version=1.0`` is rejected with HTTP 406.
* Data requests ask for ``format=csv``, which yields one row per observation
  with the series' dimensions repeated. This sidesteps SDMX-XML parsing.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Iterable, Mapping, Optional

import httpx

from environment import get_bis_base_url
from .models.bis import (
    BisCodelist,
    BisDataResponse,
    BisDataStructure,
    BisDataflow,
    BisDimension,
    BisObservation,
    BisSeries,
)

# BIS rejects a browser user-agent that isn't a browser; identify honestly.
BIS_USER_AGENT = "Mozilla/5.0 (compatible; navi-bis-client)"

_STRUCTURE_ACCEPT = "application/vnd.sdmx.structure+json;version=1.0.0"

# Columns in a CSV data response that describe the observation rather than the
# series; everything else identifies the series.
_OBSERVATION_COLUMNS = {
    "TIME_PERIOD", "OBS_VALUE", "OBS_STATUS", "OBS_CONF", "OBS_PRE_BREAK",
}


class BisAPIError(RuntimeError):
    """Raised when the BIS API returns an error response."""


def _codelist_id(urn: str | None) -> str | None:
    """Extract 'CL_AREA' from a codelist URN or 'BIS:CL_AREA(1.0)' reference."""
    if not urn:
        return None
    ref = urn.split("=")[-1]          # drop any urn:...Codelist= prefix
    ref = ref.split(":")[-1]          # drop the agency
    return ref.split("(")[0] or None  # drop the version


class BisClient:
    """Thin wrapper around the BIS SDMX statistics API."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = (base_url or get_bis_base_url()).rstrip("/")
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"User-Agent": BIS_USER_AGENT},
        )
        self._owns_client = client is None

    async def __aenter__(self) -> "BisClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        if self._owns_client:
            await self._client.aclose()

    async def _get(
        self,
        path: str,
        params: Optional[Mapping[str, Any]] = None,
        accept: Optional[str] = None,
    ) -> httpx.Response:
        headers = {"Accept": accept} if accept else None
        try:
            response = await self._client.get(path, params=params, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise BisAPIError(f"BIS request failed: {exc.response.text}") from exc
        return response

    async def get_dataflows(self, agency: str = "BIS") -> list[BisDataflow]:
        """List published dataflows -- the closest thing BIS has to a survey list."""
        response = await self._get(f"/dataflow/{agency}", accept=_STRUCTURE_ACCEPT)
        payload = response.json().get("data", {})
        return [
            BisDataflow(
                id=flow["id"],
                name=flow.get("name"),
                agency=flow.get("agencyID", agency),
                version=flow.get("version"),
                structure=flow.get("structure"),
            )
            for flow in payload.get("dataflows", [])
        ]

    async def get_datastructure(self, dsd_id: str, agency: str = "BIS") -> BisDataStructure:
        """Fetch a DSD with its codelists (``references=children`` in one call)."""
        response = await self._get(
            f"/datastructure/{agency}/{dsd_id}",
            params={"references": "children"},
            accept=_STRUCTURE_ACCEPT,
        )
        payload = response.json().get("data", {})

        structures = payload.get("dataStructures", [])
        if not structures:
            raise BisAPIError(f"BIS returned no data structure for {dsd_id}")
        dsd = structures[0]

        dimensions = [
            BisDimension(
                id=dim["id"],
                position=dim.get("position"),
                codelist_id=_codelist_id(
                    dim.get("localRepresentation", {}).get("enumeration")
                ),
            )
            for dim in dsd["dataStructureComponents"]["dimensionList"]["dimensions"]
        ]
        codelists = {
            cl["id"]: BisCodelist(
                id=cl["id"],
                name=cl.get("name"),
                codes={code["id"]: code.get("name", "") for code in cl.get("codes", [])},
            )
            for cl in payload.get("codelists", [])
        }
        return BisDataStructure(
            id=dsd["id"], name=dsd.get("name"),
            dimensions=dimensions, codelists=codelists,
        )

    async def get_data(
        self,
        flow: str,
        key: str = "all",
        *,
        start_period: Optional[str] = None,
        end_period: Optional[str] = None,
        provider: str = "all",
    ) -> BisDataResponse:
        """Fetch observations for a dataflow.

        ``key`` is the dot-joined series key in DSD dimension order, e.g.
        ``"M.US"`` for FREQ=M, REF_AREA=US. Omit a position to wildcard it
        (``"M..A"``); ``"all"`` returns every series in the flow.
        """
        params: dict[str, Any] = {"format": "csv"}
        if start_period:
            params["startPeriod"] = start_period
        if end_period:
            params["endPeriod"] = end_period

        response = await self._get(f"/data/{flow}/{key}/{provider}", params=params)
        return BisDataResponse(flow=flow, series=_parse_csv(response.text))


def _parse_csv(text: str) -> list[BisSeries]:
    """Group a flat CSV data response into series.

    Every row carries the full dimension set, so rows are grouped by their
    non-observation columns; each distinct combination is one series.
    """
    reader = csv.DictReader(io.StringIO(text))
    grouped: dict[tuple, dict[str, Any]] = {}

    for row in reader:
        dimensions = {
            k: (v or "").strip()
            for k, v in row.items()
            if k and k not in _OBSERVATION_COLUMNS
        }
        identity = tuple(sorted(dimensions.items()))
        bucket = grouped.setdefault(identity, {"dimensions": dimensions, "rows": []})
        bucket["rows"].append(row)

    series: list[BisSeries] = []
    for bucket in grouped.values():
        dimensions = bucket["dimensions"]
        observations = []
        for row in bucket["rows"]:
            raw = (row.get("OBS_VALUE") or "").strip()
            try:
                value = float(raw) if raw else None
            except ValueError:
                value = None  # non-numeric placeholder
            observations.append(
                BisObservation(
                    time_period=(row.get("TIME_PERIOD") or "").strip(),
                    value=value,
                    status=(row.get("OBS_STATUS") or "").strip() or None,
                )
            )
        observations.sort(key=lambda obs: obs.time_period)
        series.append(
            BisSeries(
                key=_series_key(dimensions),
                dimensions=dimensions,
                title=dimensions.get("TITLE") or None,
                unit_measure=dimensions.get("UNIT_MEASURE") or None,
                observations=observations,
            )
        )
    series.sort(key=lambda s: s.key)
    return series


def _series_key(dimensions: Mapping[str, str]) -> str:
    """Build a readable dot-joined key from the coded dimension columns.

    Free-text attributes (TITLE, COMPILATION, ...) are excluded so the key stays
    close to the SDMX series key rather than becoming a sentence.
    """
    skip = {"TITLE", "COMPILATION", "SOURCE_REF", "SUPP_INFO_BREAKS",
            "TIME_FORMAT", "DECIMALS", "UNIT_MULT"}
    parts: Iterable[str] = (
        v for k, v in sorted(dimensions.items()) if k not in skip and v
    )
    return ".".join(parts)
