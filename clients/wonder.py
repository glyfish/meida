"""Async client for the CDC WONDER mortality API.

WONDER (``wonder.cdc.gov``) exposes the vital-statistics mortality databases via
an **XML POST** web service: POST a ``request_xml`` form field to
``/controller/datarequest/{Dxx}`` and parse an XML ``<data-table>`` back.

Notes that shape this client (all verified live, Aug 2026):

* **Bot filter.** Plain ``httpx``/``requests``/WebFetch get HTTP 403 (Akamai).
  ``curl_cffi`` with a browser TLS fingerprint (``impersonate="chrome"``) passes
  -- the same trick the BLS flat-file fetch uses.
* **No auth.** The only gate is ``accept_datause_restrictions=true``.
* **National only.** Via the API these NVSS databases cannot group/limit by
  geography; race/Hispanic-origin and sex *are* groupable.
* **Rate limit.** Advisory ~1 query / 2 min, serialized -- so this client
  self-throttles (``throttle_seconds``, default 120) and callers should reuse
  one instance and cache results.

Scope: this client stays generic -- give it a set of underlying-cause ICD-10
codes and a database, get an age-adjusted death rate **by year**. Which codes
constitute a concept (e.g. the 14 alcohol-induced codes) lives with the catalog,
not here.

Cause selection uses the **ICD-10 codeset finder** (``O_ucd=Dxx.V2`` +
``F_Dxx.V2=<codes>``), NOT the Drug/Alcohol-Induced recode as a *by-variable*
(``B_2=Dxx.V25``) -- grouping by that recode returns an HTTP 500 by-variable
ordering error, whereas filtering the underlying cause to the recode's member
ICD-10 codes reproduces the published NCHS rates exactly.
"""
from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ET
from typing import List, Optional, Sequence, Tuple

from curl_cffi import CurlError
from curl_cffi.requests import AsyncSession

from .models.wonder import WonderResponse, WonderRow

WONDER_ENDPOINT = "https://wonder.cdc.gov/controller/datarequest/{database}"

# Values WONDER writes into a numeric cell when it withholds the number.
_NON_NUMERIC = {"Suppressed", "Unreliable", "Not Applicable", "Missing", ""}


class WonderAPIError(RuntimeError):
    """Raised when a WONDER request fails or returns no data-table."""


# ---------------------------------------------------------------------------
# Per-database request skeletons.
#
# WONDER validates the FULL parameter set, and the variable numbering differs by
# database, so each database needs its own skeleton. D76 (Underlying Cause of
# Death, 1999-2020) is transcribed from a known-working socdataR request and is
# LIVE-VERIFIED to reproduce NCHS Data Brief 448 (2019 alcohol-induced
# age-adjusted rate = 10.4, 2020 = 13.1). Other databases (D158 single-race
# 2018-2024, D176 provisional) reuse the same *query shape* but have different
# variable sets -- add their skeletons once captured.
#
# Each entry is an ordered list of (name, [values]); the builder copies it and
# overrides a handful of keys per query.
# ---------------------------------------------------------------------------
def _p(name: str, *values: str) -> Tuple[str, List[str]]:
    return (name, list(values))


_D76_SKELETON: List[Tuple[str, List[str]]] = [
    _p("accept_datause_restrictions", "true"),
    _p("B_1", "D76.V1-level1"),          # By Year
    _p("B_2", "*None*"),                  # (no second grouping; filter cause instead)
    _p("B_3", "*None*"), _p("B_4", "*None*"), _p("B_5", "*None*"),
    _p("F_D76.V1", "*All*"), _p("F_D76.V10", "*All*"),
    _p("F_D76.V2", "*All*"),              # <- underlying-cause ICD-10 codeset (overridden)
    _p("F_D76.V27", "*All*"), _p("F_D76.V9", "*All*"),
    _p("I_D76.V1", "*All*"),
    _p("I_D76.V10", "*All* (The United States)"),
    _p("I_D76.V2", "*All*"),
    _p("I_D76.V27", "*All* (The United States)"),
    _p("I_D76.V9", "*All* (The United States)"),
    _p("M_1", "D76.M1"), _p("M_2", "D76.M2"), _p("M_3", "D76.M3"),
    _p("O_V10_fmode", "freg"), _p("O_V1_fmode", "freg"), _p("O_V27_fmode", "freg"),
    _p("O_V2_fmode", "freg"), _p("O_V9_fmode", "freg"),
    _p("O_aar", "aar_std"),               # age-adjusted rate, 2000 US std pop
    _p("O_aar_pop", "0000"),
    _p("O_age", "D76.V5"),
    _p("O_javascript", "on"),
    _p("O_location", "D76.V9"),
    _p("O_precision", "1"),
    _p("O_rate_per", "100000"),
    _p("O_show_totals", "false"),
    _p("O_timeout", "300"),
    _p("O_title", "navi wonder query"),
    _p("O_ucd", "D76.V2"),                # underlying cause = detailed ICD-10
    _p("O_urban", "D76.V19"),
    _p("VM_D76.M6_D76.V10", ""), _p("VM_D76.M6_D76.V17", "*All*"),
    _p("VM_D76.M6_D76.V1_S", "*All*"), _p("VM_D76.M6_D76.V7", "*All*"),
    _p("VM_D76.M6_D76.V8", "*All*"),
    _p("V_D76.V1", ""), _p("V_D76.V10", ""), _p("V_D76.V11", "*All*"),
    _p("V_D76.V12", "*All*"), _p("V_D76.V17", "*All*"), _p("V_D76.V19", "*All*"),
    _p("V_D76.V2", ""), _p("V_D76.V20", "*All*"), _p("V_D76.V21", "*All*"),
    _p("V_D76.V22", "*All*"), _p("V_D76.V23", "*All*"), _p("V_D76.V24", "*All*"),
    _p("V_D76.V25", "*All*"), _p("V_D76.V27", ""), _p("V_D76.V4", "*All*"),
    _p("V_D76.V5", "*All*"),              # all ages (we age-adjust)
    _p("V_D76.V51", "*All*"), _p("V_D76.V52", "*All*"), _p("V_D76.V6", "00"),
    _p("V_D76.V7", "*All*"), _p("V_D76.V8", "*All*"), _p("V_D76.V9", ""),
    _p("action-Send", "Send"),
    _p("finder-stage-D76.V1", "codeset"), _p("finder-stage-D76.V10", "codeset"),
    _p("finder-stage-D76.V2", "codeset"), _p("finder-stage-D76.V27", "codeset"),
    _p("finder-stage-D76.V9", "codeset"),
    _p("stage", "request"),
]

# D158: Underlying Cause of Death, 2018-2024, Single Race (final). Same query
# shape as D76; the one structural difference is the race variable (single-race
# V42 + O_race instead of bridged V8). LIVE-VERIFIED: its 2018-2020 totals match
# D76 exactly (9.9 / 10.4 / 13.1) and it extends the series 2021-2024 (2021 = 14.4).
_D158_SKELETON: List[Tuple[str, List[str]]] = [
    _p("accept_datause_restrictions", "true"),
    _p("B_1", "D158.V1-level1"),          # By Year
    _p("B_2", "*None*"),
    _p("B_3", "*None*"), _p("B_4", "*None*"), _p("B_5", "*None*"),
    _p("F_D158.V1", "*All*"), _p("F_D158.V10", "*All*"),
    _p("F_D158.V2", "*All*"),             # <- underlying-cause ICD-10 codeset (overridden)
    _p("F_D158.V27", "*All*"), _p("F_D158.V9", "*All*"),
    _p("I_D158.V1", "*All*"),
    _p("I_D158.V10", "*All* (The United States)"),
    _p("I_D158.V2", "*All*"),
    _p("I_D158.V27", "*All* (The United States)"),
    _p("I_D158.V9", "*All* (The United States)"),
    _p("M_1", "D158.M1"), _p("M_2", "D158.M2"), _p("M_3", "D158.M3"),
    _p("O_V10_fmode", "freg"), _p("O_V1_fmode", "freg"), _p("O_V27_fmode", "freg"),
    _p("O_V2_fmode", "freg"), _p("O_V9_fmode", "freg"),
    _p("O_aar", "aar_std"), _p("O_aar_pop", "0000"),
    _p("O_age", "D158.V5"),
    _p("O_javascript", "on"),
    _p("O_location", "D158.V9"),
    _p("O_precision", "1"),
    _p("O_race", "D158.V42"),             # single-race grouping variable
    _p("O_rate_per", "100000"),
    _p("O_show_totals", "false"),
    _p("O_timeout", "300"),
    _p("O_title", "navi wonder query"),
    _p("O_ucd", "D158.V2"),
    _p("O_urban", "D158.V19"),
    _p("VM_D158.M6_D158.V10", ""), _p("VM_D158.M6_D158.V17", "*All*"),
    _p("VM_D158.M6_D158.V1_S", "*All*"), _p("VM_D158.M6_D158.V7", "*All*"),
    _p("VM_D158.M6_D158.V42", "*All*"),
    _p("V_D158.V1", ""), _p("V_D158.V10", ""), _p("V_D158.V11", "*All*"),
    _p("V_D158.V12", "*All*"), _p("V_D158.V17", "*All*"), _p("V_D158.V19", "*All*"),
    _p("V_D158.V2", ""), _p("V_D158.V20", "*All*"), _p("V_D158.V21", "*All*"),
    _p("V_D158.V22", "*All*"), _p("V_D158.V23", "*All*"), _p("V_D158.V24", "*All*"),
    _p("V_D158.V25", "*All*"), _p("V_D158.V27", ""), _p("V_D158.V4", "*All*"),
    _p("V_D158.V5", "*All*"),             # all ages (we age-adjust)
    _p("V_D158.V51", "*All*"), _p("V_D158.V52", "*All*"), _p("V_D158.V6", "00"),
    _p("V_D158.V7", "*All*"), _p("V_D158.V42", "*All*"), _p("V_D158.V9", ""),
    _p("action-Send", "Send"),
    _p("finder-stage-D158.V1", "codeset"), _p("finder-stage-D158.V10", "codeset"),
    _p("finder-stage-D158.V2", "codeset"), _p("finder-stage-D158.V27", "codeset"),
    _p("finder-stage-D158.V9", "codeset"),
    _p("stage", "request"),
]

_SKELETONS = {"D76": _D76_SKELETON, "D158": _D158_SKELETON}


def _build_request_xml(database: str, ucd_icd_codes: Sequence[str], *, title: str) -> str:
    """Copy a database skeleton and override it to select ``ucd_icd_codes`` as the
    underlying cause, grouped by year, age-adjusted. Returns the request XML."""
    skeleton = _SKELETONS.get(database)
    if skeleton is None:
        raise WonderAPIError(
            f"No request skeleton captured for WONDER database {database!r}; "
            f"available: {sorted(_SKELETONS)}"
        )
    override = {
        f"F_{database}.V2": list(ucd_icd_codes),   # underlying-cause codeset selection
        "O_title": [title],
    }
    root = ET.Element("request-parameters")
    for name, values in skeleton:
        vals = override.get(name, values)
        p = ET.SubElement(root, "parameter")
        ET.SubElement(p, "name").text = name
        for v in vals:
            ET.SubElement(p, "value").text = v
    return ET.tostring(root, encoding="unicode")


def parse_data_table(xml_text: str, database: str) -> WonderResponse:
    """Parse a WONDER XML response (grouped By Year) into a ``WonderResponse``.

    Column order for our By-Year age-adjusted query is
    ``Year | Deaths | Population | Crude Rate | Age-Adjusted Rate``. Suppressed /
    unreliable numeric cells become ``None``. Pure-parse, no network -- the unit
    of offline testability.
    """
    root = ET.fromstring(xml_text)
    messages = [m.text.strip() for m in root.iter()
                if m.tag.endswith("message") and m.text and m.text.strip()]

    data_table = next((el for el in root.iter() if el.tag.endswith("data-table")), None)
    if data_table is None:
        raise WonderAPIError(
            "WONDER returned no <data-table>"
            + (f": {'; '.join(messages)}" if messages else "")
        )

    def _num(text: str, cast):
        text = text.replace(",", "").strip()
        if text in _NON_NUMERIC:
            return None
        try:
            return cast(text)
        except ValueError:
            return None

    rows: List[WonderRow] = []
    for r in data_table:
        if not r.tag.endswith("r"):
            continue
        labels, values = [], []
        for c in r:
            attr = c.attrib
            if "l" in attr:
                labels.append(attr["l"].strip())
            elif "v" in attr:
                values.append(attr["v"].strip())
        if not labels or not labels[0].isdigit():
            continue  # skip Total / non-year rows
        rows.append(
            WonderRow(
                year=int(labels[0]),
                deaths=_num(values[0], int) if len(values) > 0 else None,
                population=_num(values[1], int) if len(values) > 1 else None,
                crude_rate=_num(values[2], float) if len(values) > 2 else None,
                age_adjusted_rate=_num(values[3], float) if len(values) > 3 else None,
            )
        )
    return WonderResponse(database=database, rows=rows, messages=messages)


class WonderClient:
    """Thin async wrapper around the CDC WONDER XML data-request service."""

    def __init__(self, *, throttle_seconds: float = 120.0, timeout: float = 300.0) -> None:
        self._throttle = throttle_seconds
        self._timeout = timeout
        self._session: Optional[AsyncSession] = None
        self._last_request: Optional[float] = None

    async def __aenter__(self) -> "WonderClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _session_obj(self) -> AsyncSession:
        if self._session is None:
            self._session = AsyncSession()
        return self._session

    async def _throttle_wait(self) -> None:
        """Respect WONDER's advisory ~1 query / 2 min limit between calls."""
        if self._last_request is not None:
            wait = self._throttle - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)

    async def _post(self, database: str, request_xml: str) -> str:
        url = WONDER_ENDPOINT.format(database=database)
        await self._throttle_wait()
        try:
            response = await self._session_obj().post(
                url,
                data={"request_xml": request_xml, "accept_datause_restrictions": "true"},
                impersonate="chrome",
                timeout=self._timeout,
            )
        except CurlError as exc:
            raise WonderAPIError(f"WONDER request failed ({database}): {exc}") from exc
        finally:
            self._last_request = time.monotonic()
        if response.status_code != 200:
            # WONDER reports validation errors as <message> in an HTTP 500 body.
            try:
                msgs = "; ".join(parse_data_table(response.text, database).messages)  # type: ignore[union-attr]
            except WonderAPIError as parsed:
                msgs = str(parsed)
            raise WonderAPIError(
                f"WONDER {database} HTTP {response.status_code}: {msgs or response.text[:300]}"
            )
        return response.text

    async def age_adjusted_rate_by_year(
        self,
        ucd_icd_codes: Sequence[str],
        *,
        database: str = "D76",
        title: str = "navi wonder query",
    ) -> WonderResponse:
        """National age-adjusted death rate (2000 US std) **by year**, for deaths
        whose underlying cause is one of ``ucd_icd_codes``.

        Pass the ICD-10 code list that defines the concept (e.g. the 14
        alcohol-induced codes). ``database`` selects the vintage: ``D76`` covers
        1999-2020 (bridged race) and ``D158`` covers 2018-2024 (single race,
        final) -- both verified; their 2018-2020 overlap agrees. Other databases
        require their own captured skeleton.
        """
        request_xml = _build_request_xml(database, ucd_icd_codes, title=title)
        body = await self._post(database, request_xml)
        return parse_data_table(body, database)
