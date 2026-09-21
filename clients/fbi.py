"""Async client for the FBI Crime Data Explorer (CDE) API.

Like FRED, BLS and BIS this is a live API, so nothing here is stored: the
series are fetched per request and cached downstream, unlike WONDER and NVSR,
which cannot be fetched at all and live in Postgres instead.

**The live base is** ``https://api.usa.gov/crime/fbi/cde``. The older
``crime/fbi/sapi`` service that most documentation still describes now returns
404, and the published Swagger documents that dead service. Everything below
was established by probing the live API.

Authentication is the shared **api.data.gov** key (``DATA_GOV_KEY``), which
opens every service behind that gateway rather than the FBI alone. It goes in
the query string as ``API_KEY``, capitalised -- the CDE routes ignore the
lowercase ``api_key`` other api.data.gov services accept. ``DEMO_KEY`` allows
roughly thirty calls an hour; a real key allows a thousand.

Offences and clearances come at three grains -- national, state and **agency**
-- all monthly, as counts and as rates. Employment comes at agency grain only.
So a city panel of crime against police staffing is buildable from this one
source, which is the pairing the enforcement question needs.

**One request yields four series.** The API is parameterised by scope, offence
and date range only: offences *and* clearances, as counts *and* as rates, all
arrive together. Measure and unit are therefore selections made after the call,
not things asked for in it -- which is what a cache in front of this client
should key on. Keyed on the payload (scope, offence, range) four series cost
one request; keyed on the caller's measure and unit they cost four, against an
allowance of a thousand an hour.

What the API serves, and three traps that make it easy to store wrong numbers:

1. ``summarized/agency/{ORI}/{offense}`` returns **three geographies at once**
   -- the agency, its state and the nation -- and the state series come first.
   Reading the first entry of ``rates`` gives "New York Offenses" when the
   request was for NYPD, which looks right and is not. The ``actuals`` block
   holds the agency alone; the labels are what disambiguate ``rates``. This
   client filters by label and returns only the scope that was asked for
   unless ``include_comparisons`` says otherwise.
2. ``pe/national`` and ``pe/state/{ST}`` answer 200 with the full response
   shape and every value null. Employment exists **only** per agency.
3. The ``rates`` block of ``pe`` divides by a "participated population" that is
   sometimes zero, giving impossible figures. Use the counts.

Both offence and employment payloads carry a **coverage** percentage -- the
share of the population living where agencies reported. It sits at 96-98% and
drops to 74% in 2021. Carry it with the data: it is what makes a 2021 value
interpretable.

**The 2021 break is two breaks.** The FBI retired the Summary Reporting System
(SRS) on 1 January 2021 in favour of the National Incident-Based Reporting
System (NIBRS), and agencies that had not converted stopped reporting -- that
is the coverage dip, and the coverage series measures it. But the two systems
also *count differently*: SRS applied the hierarchy rule, so an incident
contributed only its most serious offence, while NIBRS records every offence in
the incident. A robbery with an assault is one offence before 2021 and two
after. Coverage returning to 96% does not undo that, and no series in this API
carries a flag for it. Treat any series spanning 2021 as spliced, not
continuous.
"""
from __future__ import annotations

import asyncio
from typing import Any, Mapping, Optional

import httpx

from environment import get_data_gov_key, get_fbi_base_url
from .models.fbi import (
    FbiAgency,
    FbiEmploymentResponse,
    FbiObservation,
    FbiOffenseResponse,
    FbiSeries,
)

#: Offence slugs the summarized endpoints accept, each verified against the
#: live API. There is a ``lookup/`` family but it returns nulls for the type
#: values tried, so this list is maintained here rather than fetched.
OFFENSES = (
    "violent-crime", "homicide", "rape", "robbery", "aggravated-assault",
    "property-crime", "burglary", "larceny", "motor-vehicle-theft", "arson",
)

#: The earliest year ``pe`` accepts. Asking for less returns 400 with
#: "Please enter a from year greater than 1984" rather than clamping.
EMPLOYMENT_FROM = 1985


class FbiAPIError(RuntimeError):
    """Raised when the CDE API returns an error response."""


def _measure(label: str) -> str:
    """The measure a CDE label names: 'Texas Clearances' -> 'clearances'."""
    lowered = label.casefold()
    for measure in ("clearances", "offenses", "officers", "civilians"):
        if measure in lowered:
            return measure
    return "value"


def _chronological(period: str) -> tuple[str, str]:
    """Sort key for a CDE period. ``MM-YYYY`` does not sort as text.

    Sorted as strings, '01-2016' precedes '06-2015', so a multi-year series
    comes back month-major -- every January, then every February -- and the
    first and last filled periods are not the earliest and latest. Spans then
    go into the catalogue wrong for any series that does not begin in January,
    which is most agencies.
    """
    if "-" in period:
        month, year = period.split("-")
        return year, month
    return period, ""


def _series(block: Mapping[str, Any], scope: str, unit: str | None) -> list[FbiSeries]:
    """Pivot one ``{label: {period: value}}`` block into series, in date order."""
    out: list[FbiSeries] = []
    for label, points in (block or {}).items():
        if not isinstance(points, dict):
            continue
        out.append(FbiSeries(
            label=label, scope=scope, measure=_measure(label), unit=unit,
            observations=[FbiObservation(period=period, value=value)
                          for period, value in sorted(points.items(),
                                                      key=lambda kv: _chronological(kv[0]))],
        ))
    return out


class FbiClient:
    """Thin wrapper around the FBI Crime Data Explorer API."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 60.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = (base_url or get_fbi_base_url()).rstrip("/")
        self._api_key = api_key or get_data_gov_key()
        self._client = client or httpx.AsyncClient(base_url=self.base_url, timeout=timeout)
        self._owns_client = client is None

    async def __aenter__(self) -> "FbiClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, params: Optional[Mapping[str, Any]] = None,
                   attempts: int = 4) -> Any:
        """One GET, retrying the responses the gateway gives when pushed.

        Sustained pulls meet 429 (the hourly allowance) and 503 ("Client
        Failure Limit Exceeded", and upstream resets). Both are transient and
        both arrive mid-run, so a catalogue build that does not back off loses
        scattered scopes rather than failing outright -- 58 of 520 in one run
        here, which is the kind of gap that is easy not to notice.
        """
        query = {**(params or {}), "API_KEY": self._api_key}
        for attempt in range(attempts):
            try:
                response = await self._client.get(path, params=query)
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                status, body = exc.response.status_code, exc.response.text[:300]
                if status in (429, 503) and attempt < attempts - 1:
                    await asyncio.sleep(5 * 2 ** attempt)      # 5s, 10s, 20s
                    continue
                if status == 429:
                    raise FbiAPIError(f"api.data.gov rate limit reached: {body}") from exc
                raise FbiAPIError(f"FBI request failed ({status}): {body}") from exc
        if not response.text.lstrip().startswith(("{", "[")):    # the 404 page is HTML
            raise FbiAPIError(f"{path}: expected JSON, got {response.text[:120]!r}")
        return response.json()

    @staticmethod
    def route(scope: str) -> tuple[str, str]:
        """Turn a catalog scope into a path fragment: 'national', a state or an ORI.

        The catalog's ``scope`` facet and this argument are the same string, so
        an entry's retrieval block maps to a call without translation.
        """
        if scope == "national":
            return "national", "national"
        if len(scope) == 2 and scope.isalpha():
            return f"state/{scope.upper()}", scope.upper()
        return f"agency/{scope}", scope

    async def get_offenses(
        self,
        offense: str,
        *,
        scope: Optional[str] = None,
        state: Optional[str] = None,
        ori: Optional[str] = None,
        include_comparisons: bool = False,
        start: str = "01-1985",
        end: str = "12-2024",
    ) -> FbiOffenseResponse:
        """Monthly offences and clearances for the nation, a state or an agency.

        Dates are ``MM-YYYY``. Give *ori* for one agency, *state* for a state,
        neither for the nation.

        An agency request also returns its state and the nation, and a state
        request returns the nation, with the wider geography listed first.
        Those comparison series are dropped unless *include_comparisons* is
        set, so the caller gets what it asked for rather than what happened to
        be first in the payload.
        """
        if offense not in OFFENSES:
            raise FbiAPIError(f"unknown offence {offense!r}; expected one of {OFFENSES}")
        if sum(x is not None for x in (scope, state, ori)) > 1:
            raise FbiAPIError("give one of scope, state or ori")
        chosen = scope or ori or state or "national"
        fragment, scope = self.route(chosen)
        path = f"summarized/{fragment}/{offense}"
        ori = chosen if fragment.startswith("agency/") else None
        state = chosen if fragment.startswith("state/") else None
        payload = await self._get(path, {"from": start, "to": end})
        offenses = payload.get("offenses", {}) or {}
        tooltips = payload.get("tooltips", {}) or {}
        populations = payload.get("populations", {}) or {}
        properties = payload.get("cde_properties", {}) or {}
        series = (
            _series(offenses.get("actuals", {}), scope, "count")
            + _series(offenses.get("rates", {}), scope, "rate per 100,000")
            + _series(populations.get("population", {}), scope, "people")
            + _series(tooltips.get("Percent of Population Coverage", {}), scope, "percent")
        )
        if not include_comparisons and (ori or state):
            # The wider geographies ride along on every request. Keep only the
            # labels that are not the comparison, identified by what the API
            # calls the scope in its own labels.
            comparisons = ("United States",) if state else ("United States", )
            agency_names = {s.label.rsplit(" ", 1)[0] for s in series
                            if s.measure in ("offenses", "clearances")}
            keep = max(agency_names, key=len) if ori and agency_names else None
            series = [s for s in series
                      if (keep is None or s.label.startswith(keep)
                          or s.measure not in ("offenses", "clearances"))
                      and not any(s.label.startswith(c) for c in comparisons)]
        return FbiOffenseResponse(
            offense=offense, scope=scope, series=series,
            max_data_date=(properties.get("max_data_date") or {}).get("UCR"),
            last_refresh_date=(properties.get("last_refresh_date") or {}).get("UCR"),
        )

    async def get_states(self) -> list[tuple[str, str]]:
        """Every state scope the API serves, as ``(abbr, name)``.

        ``lookup/states`` is the one lookup that answers -- ``regions`` and
        ``agency-types`` return "Invalid Lookup", and ``offenses`` returns a
        null crime-group list. It gives the 50 states and DC, no territories.
        """
        payload = await self._get("lookup/states")
        rows = (((payload or {}).get("get_states") or {})
                .get("cde_states_query") or {}).get("states") or []
        return [(row["abbr"], row["name"]) for row in rows]

    async def get_agencies(self, state: str) -> list[FbiAgency]:
        """Every agency in a state, flattened out of the API's per-county map."""
        payload = await self._get(f"agency/byStateAbbr/{state}")
        return [FbiAgency(**row)
                for rows in (payload or {}).values() if isinstance(rows, list)
                for row in rows]

    async def get_employment(
        self,
        ori: str,
        *,
        start: int = EMPLOYMENT_FROM,
        end: int = 2024,
    ) -> FbiEmploymentResponse:
        """Officer and civilian counts for one agency, annual.

        *ori* comes from :meth:`get_agencies`. ``start`` before 1985 is refused
        by the API rather than clamped.
        """
        if start < EMPLOYMENT_FROM:
            raise FbiAPIError(f"employment starts in {EMPLOYMENT_FROM}; asked for {start}")
        payload = await self._get(f"pe/agency/{ori}", {"from": str(start), "to": str(end)})
        actuals = (payload.get("actuals") or {})
        populations = (payload.get("populations") or {})
        properties = (payload.get("cde_properties") or {})
        series = (_series(actuals, ori, "count")
                  + _series(populations, ori, "people"))
        return FbiEmploymentResponse(
            ori=ori, series=series,
            max_data_date=(properties.get("max_data_date") or {}).get("UCR"),
            last_refresh_date=(properties.get("last_refresh_date") or {}).get("UCR"),
        )
