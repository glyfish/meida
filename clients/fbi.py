"""Async client for the FBI Crime Data Explorer (CDE) API.

Like FRED, BLS and BIS this is a live API, so nothing here is stored: the
series are fetched per request and cached downstream, unlike WONDER and NVSR,
which cannot be fetched at all and live in Postgres instead.

**The live base is** ``https://api.usa.gov/crime/fbi/cde``. The older
``crime/fbi/sapi`` service that most documentation still describes now returns
404, and the Swagger most documentation links to describes that dead service.
The live service has documentation of its own, but it is embedded in the CDE
website and was found late: it is what settled the arrest vocabulary below.
Everything else here was established by probing the live API.

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

**The offence and arrest rates are not per resident.** They divide by the
payload's ``participated_population`` -- the people living where agencies
reported -- and not by its ``population``: nationally in January 2023,
580,792 arrests over 323,289,818 participants is the API's 179.65, where over
338,357,687 residents it would be 171.65. That held in every month of the
saved payloads: arrests for ``all`` nationally over 1985-2024 (480 of 480)
and in New York State for 2023; murder arrests nationally over 1985-2024;
code 20 nationally over 2018-2024 (84 of 84); codes 11, 50, 70, 150, 260 and
290 nationally and code 11 in New York State for 2023; and homicide offences
and clearances nationally for 2023 and in California over 2018-2024.
``population`` reproduces none of national or New York ``all``, and only 42
of the 480 national murder months. At small counts it can still land on the
published figure, because two decimals hide the gap between the two
populations -- New York murder arrests in 10 of 12 months of 2023, California
homicide offences in 51 of 84 -- so a match there is not evidence for it.
Coverage is exactly ``100 * participated_population / population`` in every
month checked, so the rate is per 100,000 people living where agencies
reported. At agency scope the two populations are the same number in every
month the agency has one (the five agencies checked for ``all`` over
1985-2024 match both, and so cannot tell them apart). Where the participated
population is 0 -- in every month at an agency with no resident population of
its own, such as the Metro Transit Police (``DCMTP0000``) -- the arrest route
publishes a rate of -1 (the offence route was not checked for it). Both
populations are carried, ``participated_population`` under the unit
:data:`PARTICIPATED`.

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

**Arrests are a separate count, not the other half of a clearance.** An
arrest counts one person arrested, cited or summoned on one occasion; a
clearance counts one offence closed. One arrest can clear several offences and
several arrests can clear one, and most arrests are for offences that have no
clearance series at all: nationally in 2023 only 1,259,216 of 7,184,021 arrests
(17.5%) were for the eight offences :data:`OFFENSES` covers, and the rest were
for offences such as drug possession, DUI, simple assault, disorderly conduct
and "all other offenses". So arrests and clearances are in different units
over different offences, and they cannot be differenced against each other --
not in total and not for the same offence. In particular the pair does not
reveal how many clearances were *by exceptional means* (offender dead, victim
uncooperative, extradition refused) rather than by arrest. ``summarized``
reports one combined clearance series, and splitting it needs incident-level
data this API does not serve.

What arrests do answer is how much enforcement of each kind happened. Drug,
DUI and disorderly-conduct arrests depend on where police choose to look far
more than offences reported to them do, and the route serves them per offence
at every grain.

**The arrest vocabulary comes from the FBI's own documentation.** The API
page, https://cde.ucr.cjis.gov/LATEST/webapp/#/pages/docApi, is a Swagger UI
whose OpenAPI 3.0.1 spec is not fetched from anywhere: it is compiled into one
of the site's JavaScript bundles, whose hashed file name changes whenever the
site is redeployed. Its server is the live base above. The spec's
``arrest_offense`` schema enumerates 48 values with their names, and the
website's own arrest page loads the same 48 into its offence dropdown from
``https://cde.ucr.cjis.gov/LATEST/lookup/offenses?type=arrest`` (the site's
backend, no key). :data:`ARREST_OFFENSES` is that list.

- The shape is ``arrest/{scope}/{offense}?from=MM-YYYY&to=MM-YYYY&type=counts``.
  The scope fragments are exactly :meth:`FbiClient.route`'s -- ``national``, a
  state, an ORI -- so nothing about scoping changes.
- **The offence segment is a numeric UCR arrest code** -- ``11`` is murder and
  nonnegligent homicide, ``260`` driving under the influence -- or ``all``.
  :data:`OFFENSES` does **not** transfer: ``violent-crime``, ``offense``,
  ``age``, ``sex``, ``race``, ``ethnicity`` and ``counts`` were all refused
  there with 400 "An invalid offense was requested. Please see our API page for
  valid offense IDs". An unknown code is refused here instead, before it is
  spent: the gateway answers a key that produces too many failures with "503
  Client Failure Limit Exceeded", which locks out every job sharing the key.
- Verified live with ``type=counts``: ``all``, ``11``, ``70``, ``150``,
  ``260`` and ``290`` nationally, and ``11`` at state (``NY``) and agency
  (``NY0303000``) scope too. The other codes were not requested one by one, but
  every one of them carries a value in the live 2023 ``totals`` breakdown.
- **``type`` is required**, and the spec documents two values. ``counts`` is
  the monthly payload this client reads. ``totals`` returns one figure for the
  whole window with no months, rates or coverage, broken down by offence (at
  three granularities: ``Offense Breakdown``, ``Offense Name``, ``Offense
  Category``), arrestee sex, race, and age by sex; it works per offence too,
  and this client does not read it. ``rates``, ``age``, ``race``, ``sex`` and
  omitting ``type`` all answer 400 ``Invalid 'type'.`` in plain text.
- The API gateway's own 2022 documentation also lists
  ``arrest/{scope}/{offense}/{category}`` sub-paths (male, female, race,
  sex). The spec has no such operation, so they are not used here; ``totals``
  already carries sex, race and age.
- Dates are ``MM-YYYY`` at every scope. ``from=2023`` is a 400, so this client
  refuses a bare year before spending the request.

**The codes partition the total, checked against live data.** National,
01-2023 to 12-2023: ``all``'s monthly counts sum to 7,184,021. The ``totals``
breakdown sums to the same 7,184,021 at each of its three granularities, and
each code fetched monthly sums exactly to its own breakdown entry -- ``11``
11,451, ``70`` 634,062, ``150`` 55,325, ``260`` 755,014, ``290`` 248,864. The
47 codes together fall 905 short (0.013%): the breakdown's "Suspicion" (905)
and "Runaway" (0) have no code. So in that window every arrest sits under
exactly one code, and per-offence series add up to ``all`` bar "Suspicion".
Only that window was checked, and other years and scopes may differ.
"Runaway" is the obvious candidate, and nothing here measures it: the FBI's
SRS user manual says that since 2009 it "is no longer a required Part II
offense", that agencies may still report it, and that "while this data is
stored in UCR databases, the FBI no longer publishes information on runaways
as a Part II crime". So whether earlier years' ``all`` holds runaway arrests,
and how many, is unchecked. The demographic blocks of
``totals`` do *not* reach the total: sex, and age by sex, sum to 7,076,786,
which is 107,235 (1.49%) short; race sums to 7,075,847; and murder's race
block sums to 11,461 against 11,451 arrests.

Some codes are not what their names suggest, and two totals have no code:

- ``50`` "Assault - Not Specified" is **aggravated** assault -- ``totals``
  files its 330,173 national 2023 arrests as "Aggravated Assault". Simple
  assault is ``55``.
- ``23`` "Rape - Not Specified" is empty nationally in 2023; that year's 18,769
  rape arrests are all under ``20``, the legacy definition. Take both.
- ``140``, ``150`` and ``170`` are only the *unspecified remainder* of
  prostitution, drug and gambling arrests, not their group totals: ``150`` is
  55,325 of the 918,020 drug arrests in ``150``-``160``.
- There is no violent-crime or property-crime code. :data:`ARREST_CODES_FOR`
  gives the codes that make up each :data:`OFFENSES` slug; violent crime is
  ``11 + 20 + 23 + 30 + 50``, 425,725 nationally in 2023.

Four traps beyond the three above, all worse than their ``summarized``
equivalents:

4. **The blocks are not nested.** ``summarized`` puts the numbers under
   ``payload["offenses"]["actuals"]``; ``arrest`` puts ``actuals`` and ``rates``
   at the top level with no wrapper. Code that copies the ``summarized`` reader
   finds nothing and returns an empty series rather than failing.
5. **The requested scope has no fixed place in ``rates``.** ``summarized``
   leads with the widest comparison. ``arrest/agency/NY0303000/11`` returns
   ``rates`` keyed ``New York``, ``United States``, ``New York City Police
   Department`` -- the agency last -- while ``arrest/state/NY/11`` returns
   ``New York`` then ``United States``, the state first. So this client keeps
   the labels that appear in ``actuals``, which carries the requested scope
   alone at every grain. An agency's own coverage is ``null``, so its state's
   coverage is kept to stand in for it, exactly as for offences.
6. **The offence is not in the label.** Every code comes back as "United
   States Arrests" or "New York Arrests", murder and DUI alike, so nothing in
   the payload says which offence it counts. The code is carried from the
   request onto :class:`FbiArrestResponse` instead.

7. **Nationally, for one offence, a month with no arrest is null, not 0.**
   National gambling-numbers arrests (``172``) for 01-2023 to 12-2024 come
   back null in 21 of 24 months, with 3, 1 and 1 in the other three; the
   FBI's 2023 ``totals`` give that code 5, so the nulls are months with no
   such arrest, in months the nation reported (coverage 95-97%). ``23`` is
   null in all 84 months of 2018-2024 and its 2023 total is 0. At agency
   scope the spelling has not been seen: San Francisco's murder arrests are 0
   in 42 months in which the department filed other arrests, the NYPD's in
   8, and the only agency nulls in the saved payloads are months with no
   participated population at all. The client passes values through as it
   gets them. The MCP mapper reads a per-offence null as 0 where the scope's
   *own* participated population is above zero that month and the month is
   not past ``max_data_date`` -- a scope with no participated population for
   a month reported nothing in it (Los Angeles' and San Francisco's twelve
   null months of ``all`` are exactly the twelve with none) -- and leaves a
   zero the CDE sent as it came. Its non-reporting rule then judges runs of
   zeros on the counts, by the level around them. Nationally and for a state
   the trailing run is judged that way too, so a rare code's quiet final
   months stay 0; at agency scope it is nulled at any level, as for ``all``,
   because an agency's participated population carries on after it stops
   filing -- San Francisco's does through 2024, a year in which it filed no
   arrest.

History is verified back to ``01-2018`` (36 unbroken months of Texas from
January 2018). The earliest month is unestablished -- the full-span probe was
never answered -- so an early ``start`` is a request for whatever the API has,
not a claim that it has it.
"""
from __future__ import annotations

import asyncio
from typing import Any, Mapping, Optional

import httpx

from environment import get_data_gov_key, get_fbi_base_url
from .models.fbi import (
    FbiAgency,
    FbiArrestResponse,
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

#: The unit the client gives the ``participated_population`` block: the people
#: living where agencies reported, which is what the offence and arrest rates
#: divide by. Distinct from ``population``'s ``"people"`` so that the two, which
#: share their labels, cannot be picked up for each other.
PARTICIPATED = "participated people"

#: The earliest year ``pe`` accepts. Asking for less returns 400 with
#: "Please enter a from year greater than 1984" rather than clamping.
EMPLOYMENT_FROM = 1985

#: Every offence segment the arrest route accepts: UCR arrest code -> the FBI's
#: name for it. Taken from the CDE's own documentation (the ``arrest_offense``
#: schema of the spec behind https://cde.ucr.cjis.gov/LATEST/webapp/#/pages/docApi)
#: and cross-checked against the site's arrest-page dropdown, which lists the
#: same 48. The names are the site's, because they are also the keys of the
#: ``totals`` payload's ``Offense Breakdown``, so a code joins to a total by
#: name; where the spec's name differs it drops a qualifier -- "Drug Abuse
#: Violations" for code 150 -- that says the code is only a remainder.
#:
#: The codes are the API's and are kept as they are, since a slug invented
#: here would be one the API does not know; :func:`arrest_offense` accepts a
#: name and maps it to its code. ``all``, 11, 70, 150, 260 and 290 are verified
#: live one by one; every other code carries a value in the live 2023 totals.
#: Five are not what they say -- see the module docstring: 50 is aggravated
#: assault, 23 is empty in 2023 (20 holds rape), and 140, 150 and 170 are only
#: their groups' unspecified remainders.
ARREST_OFFENSES: dict[str, str] = {
    "all": "All Crimes",
    "11": "Murder and Nonnegligent Homicide",
    "12": "Manslaughter by Negligence",
    "20": "Rape - Not Specified (Legacy)",
    "23": "Rape - Not Specified",
    "30": "Robbery - Not Specified",
    "50": "Assault - Not Specified",
    "55": "Simple Assault",
    "60": "Burglary - Not Specified",
    "70": "Larceny - Theft (Not Specified)",
    "90": "Motor Vehicle Theft - Not Specified",
    "101": "Commercial Sex Acts",
    "102": "Involuntary Servitude",
    "110": "Arson (Not Specified)",
    "140": "Prostitution and Commercialized Vice (Unspecified)",
    "141": "Prostitution and Commercialized Vice - Prostitution",
    "142": "Prostitution and Commercialized Vice - Assisting or Promoting Prostitution",
    "143": "Prostitution and Commercialized Vice - Purchasing Prostitution",
    "150": "Drug Abuse Violations (Unspecified)",
    "151": "Drug Sale/Manufacturing (Unspecified)",
    "152": "Drug Sale/Manufacturing - Opium or Cocaine or Their Derivatives",
    "153": "Drug Sale/Manufacturing - Marijuana",
    "154": "Drug Sale/Manufacturing - Synthetic Narcotics",
    "155": "Drug Sale/Manufacturing - Other - Dangerous Nonnarcotic Drugs",
    "156": "Drug Possession (Unspecified)",
    "157": "Drug Possession - Opium or Cocaine or Their Derivatives",
    "158": "Drug Possession - Marijuana",
    "159": "Drug Possession - Synthetic Narcotics",
    "160": "Drug Possession - Other - Dangerous Nonnarcotic Drugs",
    "170": "Gambling (Unspecified)",
    "171": "Gambling - Bookmaking (Horse and Sport Book)",
    "172": "Gambling - Numbers and Lottery",
    "173": "Gambling - All Other Gambling",
    "180": "Forgery and Counterfeiting",
    "190": "Fraud",
    "200": "Embezzlement",
    "210": "Stolen Property: Buying, Receiving, Possessing",
    "220": "Vandalism",
    "230": "Weapons: Carrying, Possessing, Etc.",
    "240": "Sex Offenses (Except Rape, and Prostitution and Commercialized Vice)",
    "250": "Offenses Against the Family and Children",
    "260": "Driving Under the Influence",
    "270": "Liquor Law Violations",
    "280": "Drunkenness",
    "290": "Disorderly Conduct",
    "300": "Vagrancy",
    "310": "All Other Offenses (Except Traffic)",
    "330": "Curfew and Loitering Law Violations",
}

#: The arrest codes that make up each :data:`OFFENSES` slug. Not a vocabulary
#: the arrest route accepts -- a slug there is a 400, and is refused here -- but
#: the answer to the mistake that refusal is most often for. Violent and
#: property crime have no code of their own, so they are sums; arson is outside
#: property crime, as it is in ``summarized``; rape needs both of its codes.
ARREST_CODES_FOR: dict[str, tuple[str, ...]] = {
    "violent-crime": ("11", "20", "23", "30", "50"),
    "homicide": ("11",),
    "rape": ("20", "23"),
    "robbery": ("30",),
    "aggravated-assault": ("50",),
    "property-crime": ("60", "70", "90"),
    "burglary": ("60",),
    "larceny": ("70",),
    "motor-vehicle-theft": ("90",),
    "arson": ("110",),
}

#: ``type`` is required. The spec documents ``counts`` and ``totals``; this
#: client reads ``counts``, the monthly payload, which carries rates as well
#: as counts whatever its name says. ``totals`` is one figure for the whole
#: window with offence, sex, race and age breakdowns and no months.
ARREST_TYPE = "counts"

#: The earliest month the arrest route is known to serve. Not a floor the API
#: enforces -- it is simply as far back as a probe got an answer -- so it is
#: documentation, not validation.
ARREST_VERIFIED_FROM = "01-2018"


class FbiAPIError(RuntimeError):
    """Raised when the CDE API returns an error response."""


def _measure(label: str) -> str:
    """The measure a CDE label names: 'Texas Clearances' -> 'clearances'."""
    lowered = label.casefold()
    for measure in ("clearances", "offenses", "arrests", "officers", "civilians"):
        if measure in lowered:
            return measure
    return "value"


def _month(name: str, period: str) -> str:
    """Check a ``MM-YYYY`` argument before it is spent on a request.

    The annual form is the natural mistake -- employment takes ``YYYY`` -- and
    the API answers it with 400 "From year and month date is not valid,
    expected format MM-YYYY" rather than reading it as January. Refusing here
    costs nothing; letting it through costs one of a thousand hourly calls and
    returns an error the caller has to parse.
    """
    month, _, year = period.partition("-")
    if not (len(month) == 2 and month.isdigit() and 1 <= int(month) <= 12
            and len(year) == 4 and year.isdigit()):
        raise FbiAPIError(f"{name}={period!r} is not MM-YYYY; arrests are monthly")
    return period


_ARREST_NAMES: dict[str, str] = {
    name.casefold(): code for code, name in ARREST_OFFENSES.items()}


def arrest_offense(offense: str | int) -> str:
    """The UCR arrest code for *offense*, given as a code or as its FBI name.

    ``"11"``, ``11`` and ``"murder and nonnegligent homicide"`` all give
    ``"11"``. Anything else is refused here, before it is spent: the API
    answers an unknown code with a 400, and a key that collects enough failures
    is locked out with "503 Client Failure Limit Exceeded" -- along with every
    other job sharing it.

    Only the names in :data:`ARREST_OFFENSES` are accepted, not the spec's
    shorter ones: "Drug Abuse Violations" reads as every drug arrest, and code
    150 is only the ones given no sub-code.
    """
    key = " ".join(str(offense).split())
    if key.casefold() in ARREST_OFFENSES:
        return key.casefold()
    code = _ARREST_NAMES.get(key.casefold())
    if code is not None:
        return code
    parts = ARREST_CODES_FOR.get(key.casefold())
    if parts:
        named = ", ".join(f"{c} ({ARREST_OFFENSES[c]})" for c in parts)
        hint = (f" {key!r} is a summarized slug, not an arrest code; its arrests are "
                + (f"code {named}." if len(parts) == 1
                   else f"codes {named}, requested one at a time and added."))
    else:
        hint = ""
    raise FbiAPIError(
        f"unknown arrest offence {offense!r}: expected a UCR arrest code from "
        f"ARREST_OFFENSES ('all', '11', '260', ...) or its name.{hint}")


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
            + _series(populations.get("participated_population") or {}, scope,
                      PARTICIPATED)
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

    async def get_arrests(
        self,
        offense: str = "all",
        *,
        scope: Optional[str] = None,
        state: Optional[str] = None,
        ori: Optional[str] = None,
        include_comparisons: bool = False,
        start: str = "01-1985",
        end: str = "12-2024",
    ) -> FbiArrestResponse:
        """Monthly arrests for one offence, or all of them, in one geography.

        *offense* is a UCR arrest code from :data:`ARREST_OFFENSES` -- ``"11"``
        for murder and nonnegligent homicide, ``"260"`` for DUI -- or its name,
        and defaults to ``"all"``. It is not one of the :data:`OFFENSES` slugs,
        which this route refuses; an unknown value is refused here before a
        request is made. Nationally in 2023, the one window checked, each
        arrest sat under exactly one code and the codes added up to ``all``
        bar 905 arrests filed under "Suspicion", which has no code; other
        years and scopes are unchecked.

        Nationally, for a single offence the CDE spells a month with no arrest
        for it as ``null`` rather than 0; at agency scope it has been seen to
        send 0. The values here are passed through as the payload has them.
        :func:`mcp_server.responses.fbi.from_arrest_response` is what reads
        those nulls as zeros, where the scope's own participated population
        says it reported.

        Scoping works as in :meth:`get_offenses`: give *ori* for one agency,
        *state* for a state, neither for the nation, and *scope* for whichever
        of the three a catalog entry names. Dates are ``MM-YYYY``, checked here
        because a bare year is a 400 rather than a January.

        An arrest counts one person arrested, cited or summoned on one occasion;
        it is not a clearance, which counts an offence closed. One arrest can
        clear several offences and several arrests can clear one, so these
        series cannot be differenced against :meth:`get_offenses`' clearances,
        in total or for the same offence.

        The payload's labels never name the offence -- murder comes back as
        "New York Arrests", like everything else -- so the code is carried from
        the request onto the response.

        The wider geographies ride along as they do for offences, in no fixed
        position -- the requested state first, the requested agency last -- so
        they are dropped by matching the labels in ``actuals``, which carries
        the requested scope alone, rather than by position.
        *include_comparisons* keeps them.
        """
        code = arrest_offense(offense)
        if sum(x is not None for x in (scope, state, ori)) > 1:
            raise FbiAPIError("give one of scope, state or ori")
        chosen = scope or ori or state or "national"
        fragment, scope = self.route(chosen)
        ori = chosen if fragment.startswith("agency/") else None
        state = chosen if fragment.startswith("state/") else None
        payload = await self._get(
            f"arrest/{fragment}/{code}",
            {"from": _month("start", start), "to": _month("end", end),
             "type": ARREST_TYPE},
        )
        actuals = payload.get("actuals") or {}
        tooltips = payload.get("tooltips") or {}
        populations = payload.get("populations") or {}
        properties = payload.get("cde_properties") or {}
        series = (
            _series(actuals, scope, "count")
            + _series(payload.get("rates") or {}, scope, "rate per 100,000")
            + _series(populations.get("population") or {}, scope, "people")
            + _series(populations.get("participated_population") or {}, scope,
                      PARTICIPATED)
            + _series(tooltips.get("Percent of Population Coverage") or {},
                      scope, "percent")
        )
        if not include_comparisons and (ori or state):
            # ``actuals`` holds the requested scope alone at every grain, which
            # makes its labels the list to keep -- position cannot be used here,
            # because a requested agency is last in ``rates`` and a requested
            # state first.
            # Population and coverage are filtered against the nation only: an
            # agency publishes no coverage of its own, so its state's has to
            # survive to stand in for it, and the label says whose it is.
            keep = set(actuals)
            series = [s for s in series
                      if (s.label in keep if s.measure == "arrests" and keep
                          else not s.label.startswith("United States"))]
        return FbiArrestResponse(
            offense=code, scope=scope, series=series,
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
