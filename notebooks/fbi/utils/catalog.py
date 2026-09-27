"""Build the FBI catalog out of the series calls themselves.

The CDE has no metadata endpoint -- ``lookup/offenses`` answers
``{"crimeGroups": null}`` for every type tried -- but it does not need one:
each ``summarized`` call returns the observations *and* everything a catalog
entry wants. One request per (scope, offence) yields both measures, both
units, the population denominator, the coverage percentage and the data
vintage, so the catalog is a by-product of reading the data rather than a
second pull.

That makes the cost 520 requests for all 52 scopes and 10 offences, inside the
1,000-per-hour allowance, and it is why :data:`PAUSE` is set for a single run
rather than for sustained traffic.

**The arrest route is catalogued the same way and costs an order more.** Its
request dimension is a numeric UCR arrest code rather than an offence slug, and
there are 48 of them against ten offences, so all 48 at 52 scopes is 2,496
calls -- two and a half hours, more than the hourly allowance, and therefore a
run that will be interrupted. :func:`harvest_arrests` is the offence loop's twin
for a subset small enough to sit in one sitting; ``utils/arrest_harvest.py`` is
the same loop with a checkpoint on disk for a full one. One entry per (code,
scope), because the route serves one measure, and an entry for a code with no
arrests too, marked ``empty`` -- otherwise "Vermont files no gambling arrests"
and "nobody harvested gambling" look identical from the catalogue.

**Frequency differs by family, and the catalog says which.** Offences and
clearances are monthly; police employment is annual. A caller building a
quarterly nowcast can use the first and not the second.

Two things the API cannot supply and this module does not invent:

* **Definitions.** What "aggravated assault" counts, whether "rape" is the
  revised 2013 definition or the legacy one, whether a clearance means arrest
  or exceptional means. Written into :data:`OFFENSE_NOTES` by hand, from FBI
  documentation, and carried into the entry so a reader is not guessing.
* **Descriptions.** Generated per bucket by ``db_import.descriptions``, the
  same machinery CDC uses. Twenty buckets here against CDC's two and a half
  thousand series.

Nothing is stored in Postgres: the FBI is a live source like FRED and BIS, so
the catalog's ``retrieval`` block points at the MCP tool, not at
``timeseries_source_data``.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Iterable

_MEIDA_ROOT = str(Path(__file__).resolve().parents[3])
if _MEIDA_ROOT not in sys.path:
    sys.path.insert(0, _MEIDA_ROOT)

from clients import FbiClient
from clients.fbi import ARREST_OFFENSES, ARREST_VERIFIED_FROM, OFFENSES

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

#: Seconds between requests. The allowance is 1,000 an hour, so one a second
#: (3,600) only works while the hour's budget is untouched -- a second run in
#: the same hour met 503 "Client Failure Limit Exceeded" on 58 of 520 calls and
#: silently lost 116 catalogue entries. 3.6 seconds is the sustainable rate.
PAUSE = 3.6

#: The 50 states and DC, as a fallback. :func:`scopes` fetches the live list
#: from ``lookup/states`` instead; this is only used if that call fails, and it
#: matched the API exactly when checked.
STATES = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO",
    "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
)


async def scopes() -> tuple[str, ...]:
    """Every geographic scope to catalogue: ``national`` and each state.

    The states come from the API rather than from :data:`STATES`, so a change
    upstream -- a territory appearing, say -- is picked up instead of silently
    missed. Falls back to the constant if the lookup fails.
    """
    try:
        async with FbiClient() as fbi:
            live = tuple(abbr for abbr, _ in await fbi.get_states())
    except Exception:                                 # noqa: BLE001 -- the constant is current
        live = STATES
    return ("national", *live)

#: What each offence slug counts, from FBI documentation rather than the API.
#: These are the caveats a reader needs and the payload does not carry.
OFFENSE_NOTES: dict[str, str] = {
    "violent-crime": "Murder and non-negligent manslaughter, rape, robbery and "
                     "aggravated assault combined.",
    "homicide": "Murder and non-negligent manslaughter. Excludes negligent "
                "manslaughter, justifiable homicide and attempts.",
    "rape": "Revised definition from 2013; series crossing that year mix two "
            "definitions and the level shifts upward on the revision.",
    "robbery": "Taking by force or threat of force.",
    "aggravated-assault": "Assault with intent to cause severe bodily injury, "
                          "usually involving a weapon.",
    "property-crime": "Burglary, larceny-theft and motor vehicle theft combined; "
                      "arson is counted separately.",
    "burglary": "Unlawful entry to commit a felony or theft.",
    "larceny": "Theft without force, violence or fraud.",
    "motor-vehicle-theft": "Theft or attempted theft of a motor vehicle.",
    "arson": "Wilful burning. Reported less completely than the other offences.",
}

MEASURE_NOTES = {
    "offenses": "Offences known to law enforcement.",
    "clearances": "Offences cleared by arrest or exceptional means. Divided by "
                  "offences this is the clearance rate, the usual measure of "
                  "enforcement intensity.",
}

#: What each UCR arrest code counts, and the traps that make its FBI name
#: misleading. The same job :data:`OFFENSE_NOTES` does for the ten summarized
#: slugs, for the 48 segments the arrest route accepts. The names are the FBI's,
#: from :data:`clients.fbi.ARREST_OFFENSES`, and are not restated here; what is
#: written here is what the name does not say.
#:
#: Five codes are not what they read as, and every one of them is a wrong number
#: a caller would publish without noticing: 50 is aggravated assault, 23 is
#: empty while 20 holds the rape arrests, and 140, 150 and 170 are their groups'
#: unspecified remainders rather than the group totals.
ARREST_NOTES: dict[str, str] = {
    "all": "Every arrest, all offences together. Nationally in 2023 the 47 coded "
           "series sum to this bar 905 arrests of 7,184,021 filed under "
           "'Suspicion', which has no code; 'Runaway' has none either and is no "
           "longer published.",
    "11": "Murder and non-negligent manslaughter. Killing through negligence is "
          "code 12 and is not in this one.",
    "12": "Killing through negligence. Outside the violent-crime group, which is "
          "codes 11, 20, 23, 30 and 50.",
    "20": "Rape under the legacy pre-2013 definition -- and, despite reading as a "
          "leftover, where the rape arrests are: 18,769 nationally in 2023 against "
          "none under code 23. Neither code alone is the offence; take both.",
    "23": "Rape under the revised 2013 definition. Empty nationally in 2023 -- null "
          "in all 84 months of 2018-2024 -- because that year's rape arrests are all "
          "filed under code 20. An empty series here is not an absence of rape "
          "arrests.",
    "30": "Robbery: taking by force or threat of force.",
    "50": "Aggravated assault, whatever the name says: the FBI's own 2023 totals "
          "file this code's 330,173 arrests as 'Aggravated Assault'. Simple assault "
          "is code 55, and pairing this with the summarized aggravated-assault "
          "series is the correct pairing.",
    "55": "Simple assault: assault without the aggravating weapon or injury. "
          "Outside the violent-crime group, which takes 50 and not this.",
    "60": "Burglary: unlawful entry to commit a felony or theft.",
    "70": "Larceny-theft: theft without force, violence or fraud. The largest of "
          "the property codes.",
    "90": "Motor vehicle theft, attempts included.",
    "101": "Human trafficking for commercial sex acts. Not one of the prostitution "
           "codes 140-143, which count the trade rather than the trafficking, and "
           "not inside their total.",
    "102": "Human trafficking for involuntary servitude.",
    "110": "Arson. Outside the property-crime group here as in the summarized "
           "route, and reported less completely than the other offences.",
    "140": "The unspecified remainder of prostitution and commercialized vice, not "
           "the group's total: the arrests given no sub-code. Add 140, 141, 142 and "
           "143 for every prostitution arrest.",
    "141": "Prostitution itself, within the 140-143 group.",
    "142": "Assisting or promoting prostitution -- the pimping side -- within the "
           "140-143 group.",
    "143": "Purchasing prostitution -- the buyer's side -- within the 140-143 group.",
    "150": "The unspecified remainder of drug abuse violations, NOT the drug total: "
           "55,325 of the 918,020 drug arrests nationally in 2023, which are codes "
           "150 to 160 together. Add 150-160 for every drug arrest, 151-155 for sale "
           "and manufacture, 156-160 for possession.",
    "151": "Drug sale or manufacture, substance unspecified: the remainder of the "
           "sale half, 151-155.",
    "152": "Sale or manufacture of opium, cocaine or their derivatives.",
    "153": "Sale or manufacture of marijuana.",
    "154": "Sale or manufacture of synthetic narcotics.",
    "155": "Sale or manufacture of other dangerous non-narcotic drugs.",
    "156": "Drug possession, substance unspecified: the remainder of the possession "
           "half, 156-160, which is much the larger of the two halves.",
    "157": "Possession of opium, cocaine or their derivatives.",
    "158": "Possession of marijuana. The single largest drug code, and the one a "
           "decriminalisation series is read off.",
    "159": "Possession of synthetic narcotics.",
    "160": "Possession of other dangerous non-narcotic drugs.",
    "170": "The unspecified remainder of gambling, not the group's total. Add 170, "
           "171, 172 and 173 for every gambling arrest.",
    "171": "Bookmaking on horses and sport, within the 170-173 group.",
    "172": "Numbers and lottery gambling, within the 170-173 group. Rare enough "
           "that a blank month is ordinary rather than a missing return: nationally "
           "21 of the 24 months of 2023-2024 carry no such arrest at all.",
    "173": "All other gambling, within the 170-173 group.",
    "180": "Forgery and counterfeiting.",
    "190": "Fraud.",
    "200": "Embezzlement.",
    "210": "Buying, receiving or possessing stolen property.",
    "220": "Vandalism: wilful damage short of arson.",
    "230": "Carrying or possessing weapons and the related offences. The weapons "
           "charge itself, not a violent offence: an armed robbery is filed under "
           "code 30.",
    "240": "Sex offences other than rape and other than the prostitution group: the "
           "residual sex-offence code.",
    "250": "Offences against the family and children -- non-support, neglect, abuse "
           "where charged as such.",
    "260": "Driving under the influence.",
    "270": "Liquor law violations: under-age possession, unlawful sale and the like. "
           "Neither DUI (code 260) nor public drunkenness (code 280).",
    "280": "Public drunkenness. Not an offence in every state, so a state's zero "
           "may be its statute book rather than its policing.",
    "290": "Disorderly conduct.",
    "300": "Vagrancy. Largely decriminalised, and a small code: a state's zero here "
           "is usually its statute book.",
    "310": "All other offences except traffic: the residual, and the largest single "
           "code in the table -- every arrest with no code of its own. Not an "
           "offence, and not comparable between agencies whose charging practice "
           "differs.",
    "330": "Curfew and loitering violations. Juveniles only by definition.",
}

#: What an arrest counts, carried into every arrest entry's ``definition`` the
#: way :data:`MEASURE_NOTES` is carried into an offence's. One sentence of it is
#: the misuse the numbers themselves cannot reveal: an arrest is in different
#: units from a clearance and the two are never differenced.
ARREST_MEASURE_NOTE = (
    "One arrest is one person arrested, cited or summoned on one occasion, filed "
    "under a single offence. Not a clearance: a clearance closes an offence, one "
    "arrest can clear several offences and several arrests one, so this cannot be "
    "differenced against fbi_offenses' clearances. Rates divide by the "
    "participated population -- the people living where agencies reported -- not "
    "by residents."
)

#: Notice text that is the response's own account of months with nothing behind
#: them. The catalogue quotes those notices rather than re-deriving the blank
#: months, because the mapper that nulls them is the only thing that knows which
#: blanks are missing returns, which are filed zeros and which are a window
#: outrunning the data -- and its sentence already names the spans.
#:
#: Two families of notice say it and both are wanted: the single offence's
#: reading (``_one_offence_notices`` -- nulls read as zero arrests, months with
#: no participated population, months past ``max_data_date``) and the
#: non-reporting rule (``_filing_notices`` -- runs nobody filed, a padded tail, a
#: trailing run kept). Nothing else on an arrest *count* response matches: the
#: 2021 splice, the coverage floor, the stood-in geography and the still-filling
#: last month are about the numbers rather than about their absence, and the
#: negative-rate notice cannot arise on a count.
BLANK_MONTH_PHRASES = (
    "record no filing",
    "past the last filing",
    "blank and",
    "returned as null",
    "returned as 0 arrests",
    "as zero arrests",
)


def _spans(series) -> tuple[str | None, str | None]:
    span = series.span
    return span if span else (None, None)


def _iso(period: str | None) -> str | None:
    """'03-2019' -> '2019-03-01'; '2019' -> '2019-01-01'."""
    if not period:
        return None
    if "-" in period:
        month, year = period.split("-")
        return f"{year}-{month}-01"
    return f"{period}-01-01"


def _agency_notes(data_dir: Path = DATA_DIR) -> dict[str, dict[str, Any]]:
    """ORI -> registry record, from ``raw/agencies.json`` if it has been pulled.

    The registry carries each agency's own NIBRS start date, which is where
    that agency's reporting break falls. Without it a reader has to infer the
    break from the national 2021 dip, which is wrong for any agency that moved
    in a different year.
    """
    path = Path(data_dir) / "raw" / "agencies.json"
    if not path.exists():
        return {}
    return {row["ori"]: row for row in json.loads(path.read_text())}


def entries_from(payload, scope: str, agencies: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Catalog entries for one (scope, offence) payload.

    Only the requested scope is catalogued. Every call also returns the
    national comparison series, which would otherwise be catalogued 51 times
    over.
    """
    wanted = "United States" if scope == "national" else None
    out: list[dict[str, Any]] = []
    # Every call carries two coverage series, the scope's and the nation's.
    # Taking the first gave every state the national figure.
    percents = [s for s in payload.series if s.unit == "percent"]
    coverage = next((s for s in percents
                     if (s.label == "United States") == (scope == "national")), None)
    covered = [o.value for o in coverage.observations if o.value is not None] if coverage else []

    for series in payload.series:
        if series.measure not in ("offenses", "clearances") or series.unit != "count":
            continue
        if scope != "national" and series.label.startswith("United States"):
            continue
        if wanted and not series.label.startswith(wanted):
            continue
        start, end = _spans(series)
        # The label names the geography: "New York City Police Department
        # Offenses" -> that department; "Texas Offenses" -> Texas.
        geography = series.label.rsplit(" ", 1)[0]
        out.append({
            "series_id": f"fbi/{payload.offense}/{scope}/{series.measure}",
            "concept": payload.offense,
            "title": f"{payload.offense.replace('-', ' ').title()} "
                     f"{series.measure}, {series.label.rsplit(' ', 1)[0]}, monthly",
            "unit": "count",
            "frequency": "Monthly",
            "provisional": False,
            "is_active": True,
            "facets": {"geography": geography, "scope": scope,
                       "offense": payload.offense, "measure": series.measure},
            "observation_start": _iso(start),
            "observation_end": _iso(end),
            "definition": f"{OFFENSE_NOTES.get(payload.offense, '')} "
                          f"{MEASURE_NOTES[series.measure]}".strip(),
            "coverage_mean_percent": round(sum(covered) / len(covered), 2) if covered else None,
            "coverage_min_percent": min(covered) if covered else None,
            "sources": [{"kind": "fbi_cde", "endpoint": f"summarized/{scope}/{payload.offense}",
                         "vintage": payload.max_data_date,
                         "refreshed": payload.last_refresh_date}],
            # One call returns offences and clearances together, so the block
            # names the measure as well: without it the two entries for a
            # scope are indistinguishable to a consumer holding one of them.
            "retrieval": {"tool": "fbi_offenses", "offense": payload.offense,
                          "scope": scope, "measure": series.measure,
                          "unit": "count"},
        })
        record = (agencies or {}).get(scope)
        if record:                                   # an agency scope, so say whose
            out[-1]["facets"] |= {
                "agency_type": record.get("agency_type_name"),
                "state": record.get("state_abbr"),
                "county": record.get("counties"),
            }
            out[-1]["nibrs_start_date"] = record.get("nibrs_start_date")
    return out


def employment_entries(payload, record: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Catalog entries for one agency's employment payload.

    Two series per agency -- officers and civilians -- each the sum of the
    male and female counts the API reports separately. Annual, unlike the
    monthly offence series, which is why they are a separate group.
    """
    out: list[dict[str, Any]] = []
    name = (record or {}).get("agency_name") or payload.ori
    for measure, note in (
        ("officers", "Sworn officers employed, male and female combined."),
        ("civilians", "Civilian employees, male and female combined."),
    ):
        periods = sorted({o.period for s in payload.series if s.measure == measure
                          for o in s.observations if o.value is not None})
        if not periods:
            continue
        out.append({
            "series_id": f"fbi/employment/{payload.ori}/{measure}",
            "concept": "police_employment",
            "title": f"{measure.title()}, {name}, annual",
            "unit": "count",
            "frequency": "Annual",
            "provisional": False,
            "is_active": True,
            "facets": {"geography": name, "scope": payload.ori, "measure": measure,
                       "agency_type": (record or {}).get("agency_type_name"),
                       "state": (record or {}).get("state_abbr")},
            "observation_start": _iso(periods[0]),
            "observation_end": _iso(periods[-1]),
            "definition": f"{note} Counts, not the API's own per-1,000 rate, whose "
                          f"population base is unreliable.",
            "nibrs_start_date": (record or {}).get("nibrs_start_date"),
            "sources": [{"kind": "fbi_cde", "endpoint": f"pe/agency/{payload.ori}",
                         "vintage": payload.max_data_date,
                         "refreshed": payload.last_refresh_date}],
            "retrieval": {"tool": "fbi_employment", "ori": payload.ori,
                          "measure": measure},
        })
    return out


async def harvest_employment(oris: Iterable[str]) -> list[dict[str, Any]]:
    """One call per agency; return employment catalog entries."""
    agencies = _agency_notes()
    entries: list[dict[str, Any]] = []
    async with FbiClient() as fbi:
        for ori in oris:
            payload = await fbi.get_employment(ori)
            entries.extend(employment_entries(payload, agencies.get(ori)))
            time.sleep(PAUSE)
    return entries


def this_month() -> str:
    """The current month as ``MM-YYYY``, the end of an arrest window.

    Computed rather than written down, as ``fbi_arrests`` computes its own
    default: a fixed end is how a harvest quietly stops catalogueing its last
    two years. The route answered 09-2026 on 2026-09-27, so it serves up to the
    current month; the final months are still filling -- national murder arrests
    were 220 in 08-2026 and 20 in 09-2026 against a level near 600 -- and the
    tool response's notices say so when the series is fetched.
    """
    from datetime import date

    today = date.today()
    return f"{today.month:02d}-{today.year}"


def _code_token(code: str) -> str:
    """A code that sorts numerically as text: ``'11'`` -> ``'011'``, ``'all'``.

    The file names carry this so ``fbi_series_arrests_011.yaml`` precedes
    ``_020`` precedes ``_310`` in a directory listing; unpadded, 11 would sort
    after 101.
    """
    return code.zfill(3) if code.isdigit() else code


def arrest_group(code: str) -> str:
    """The catalog group -- and so the file stem -- for one arrest code.

    ``'arrests_011'``. One file per code, which keeps a re-harvest of one code to
    one file the way one offence is one file, and sorts the arrest files as a
    block between ``aggravated_assault`` and ``arson`` without colliding with any
    offence slug.
    """
    return f"arrests_{_code_token(code)}"


def _last_value(context) -> float | None:
    """The most recent value of a context series, or None."""
    filled = [o.value for o in getattr(context, "observations", ()) or ()
              if o.value is not None]
    return filled[-1] if filled else None


def _blank_notices(notices: Iterable[str]) -> list[str]:
    """The notices that account for months with no filing behind them."""
    return [n for n in notices if any(p in n for p in BLANK_MONTH_PHRASES)]


def _as_arrest_series(payload, scope: str, code: str | None):
    """Whatever an arrest call gave, read as the tool's own response.

    The catalogue describes what ``fbi_arrests`` returns, not what the CDE
    sends, so a raw :class:`clients.models.fbi.FbiArrestResponse` is put through
    the same mapper the tool uses. That is what makes ``observation_start`` the
    first *filing* rather than the first month of the requested window, reads a
    single offence's national nulls as the zero arrests they are, nulls the runs
    nobody filed, and writes the notices this entry quotes. A response already
    mapped is passed through, so a caller who has one does not pay for it twice.
    """
    from mcp_server.responses.fbi import from_arrest_response

    if hasattr(payload, "observations"):               # already an FbiArrestSeries
        return payload
    return from_arrest_response(payload, scope=scope, unit="count", offense=code)


def arrest_entries(payload, scope: str, code: str | None = None,
                   agencies: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The catalog entry for one (code, scope) arrest payload -- always exactly one.

    One entry, not two: the arrest route serves one measure, so unlike
    :func:`entries_from` there is no ``measure`` to split on, and the offence is
    not in the payload's labels at all -- every code comes back as "Texas
    Arrests" -- so *code* (or the payload's own record of it) is the only thing
    that says which offence this is.

    **A code with no arrests still gets an entry, marked empty.** Dropping it
    would leave a reader unable to tell "Vermont files no gambling arrests" from
    "nobody looked", and the second is the answer they would assume. ``empty``
    is about the arrests, not about the months: nationally the CDE spells a month
    with no arrest under one code as null and the mapper reads it back as a filed
    zero, so an empty code comes through as a full window of zeros rather than as
    an absence.

    Everything measured is taken from the response rather than from the request:
    the span from the filings, coverage's mean and minimum, the participated
    population the rate divides by, and the notices' own sentences about the
    months nobody filed.
    """
    series = _as_arrest_series(payload, scope, code)
    code = series.offense
    name = series.offense_name or ARREST_OFFENSES.get(code, code)
    values = [o.value for o in series.observations if o.value is not None]
    total = sum(values)
    empty = not values or not total
    geography = series.geography or ("United States" if scope == "national" else scope)
    window = (f"{series.observations[0].period} to {series.observations[-1].period}"
              if series.observations else "the window harvested")
    definition = f"{ARREST_NOTES.get(code, '')} {ARREST_MEASURE_NOTE}".strip()
    if empty:
        definition = (f"No arrest was filed under this code at {geography} in "
                      f"{window}. {definition}")
    entry: dict[str, Any] = {
        "series_id": f"fbi/arrests/{code}/{scope}",
        "concept": "arrests",
        "title": f"{name} arrests, {geography}, monthly",
        "unit": "count",
        "frequency": "Monthly",
        "provisional": False,
        # An empty code is catalogued and discoverable, and says of itself that
        # there is nothing to fetch.
        "is_active": not empty,
        "facets": {"geography": geography, "scope": scope, "offense": code,
                   "offense_name": name, "measure": "arrests"},
        "observation_start": _iso(series.observation_start),
        "observation_end": _iso(series.observation_end),
        "definition": definition,
        "coverage_mean_percent": series.coverage_mean_percent,
        "coverage_min_percent": series.coverage_min_percent,
        # The rate's denominator, at its most recent month: an entry quoting a
        # count is read against the population that reported it, and at agency
        # scope this is the agency's own rather than its state's.
        "participated_population": _last_value(series.participated_population),
        "filings": len(values),
        "arrests_total": total,
        "empty": empty,
        # Quoted, not re-derived: the mapper's sentence names the spans and says
        # which blanks were missing returns rather than quiet months.
        "blank_month_notices": _blank_notices(series.notices),
        "sources": [{"kind": "fbi_cde",
                     "endpoint": f"arrest/{FbiClient.route(scope)[0]}/{code}",
                     "vintage": series.max_data_date,
                     "refreshed": series.last_refresh_date}],
        # retrieval minus tool is exactly what fbi_arrests takes. No measure:
        # the route serves arrests and nothing else.
        "retrieval": {"tool": "fbi_arrests", "offense": code, "scope": scope,
                      "unit": "count"},
    }
    record = (agencies or {}).get(scope)
    if record:                                        # an agency scope, so say whose
        entry["facets"] |= {
            "agency_type": record.get("agency_type_name"),
            "state": record.get("state_abbr"),
            "county": record.get("counties"),
        }
        entry["nibrs_start_date"] = record.get("nibrs_start_date")
    return [entry]


async def harvest_arrests(codes: Iterable[str] = tuple(ARREST_OFFENSES),
                          scopes: Iterable[str] = ("national", *STATES),
                          start: str = ARREST_VERIFIED_FROM,
                          end: str | None = None) -> list[dict[str, Any]]:
    """One call per (code, scope); return every arrest catalog entry.

    The offence pair's shape -- paced by :data:`PAUSE`, failures collected rather
    than raised -- with two differences. The window is
    :data:`clients.fbi.ARREST_VERIFIED_FROM` to :func:`this_month` rather than
    1985 to a fixed date: that is as far back as the route is known to answer and
    as far forward as it has. And the cost is an order up: 48 codes against 10
    offences, so all 48 at 52 scopes is 2,496 calls and about two and a half
    hours at ``PAUSE``.

    **For a full run use** ``utils/arrest_harvest.py`` **instead.** This
    function holds its entries in memory and starts from the beginning, which a
    three-hour run cannot afford; that module is the same loop with a checkpoint
    on disk, so it survives being killed.
    """
    end = end or this_month()
    entries: list[dict[str, Any]] = []
    failures: list[tuple[str, str, str]] = []
    agencies = _agency_notes()
    async with FbiClient() as fbi:
        for code in codes:
            for scope in scopes:
                try:
                    payload = await fbi.get_arrests(code, scope=scope,
                                                    start=start, end=end)
                    entries.extend(arrest_entries(payload, scope, code, agencies))
                except Exception as exc:                  # noqa: BLE001 -- recorded, not raised
                    failures.append((code, scope, str(exc)[:120]))
                time.sleep(PAUSE)
    if failures:
        (DATA_DIR / "arrest_harvest_failures.json").write_text(
            json.dumps(failures, indent=1) + "\n")
    return entries


async def harvest(offenses: Iterable[str] = OFFENSES,
                  scopes: Iterable[str] = ("national", *STATES),
                  start: str = "01-1985", end: str = "12-2024") -> list[dict[str, Any]]:
    """One call per (scope, offence); return every catalog entry.

    Paced by :data:`PAUSE`. Failures are collected rather than raised, so one
    bad scope does not lose the run.
    """
    entries: list[dict[str, Any]] = []
    failures: list[tuple[str, str, str]] = []
    agencies = _agency_notes()
    async with FbiClient() as fbi:
        for offense in offenses:
            for scope in scopes:
                try:
                    # 'national', a two-letter state, or an ORI
                    where = ({} if scope == "national"
                             else {"state": scope} if len(scope) == 2
                             else {"ori": scope})
                    payload = await fbi.get_offenses(offense, start=start, end=end, **where)
                    entries.extend(entries_from(payload, scope, agencies))
                except Exception as exc:                      # noqa: BLE001 -- recorded, not raised
                    failures.append((offense, scope, str(exc)[:120]))
                time.sleep(PAUSE)
    if failures:
        (DATA_DIR / "harvest_failures.json").write_text(json.dumps(failures, indent=1) + "\n")
    return entries


async def repair(data_dir: Path = DATA_DIR) -> dict[str, int]:
    """Re-harvest the pairs recorded in ``harvest_failures.json`` and merge them.

    A partial run is worth repairing rather than repeating: 58 failed pairs
    cost 58 calls, a full rebuild 520.
    """
    import yaml

    path = Path(data_dir) / "harvest_failures.json"
    if not path.exists():
        return {"repaired": 0}
    failures = json.loads(path.read_text())
    recovered: list[dict[str, Any]] = []
    still_failing: list[tuple[str, str, str]] = []
    agencies = _agency_notes()
    async with FbiClient() as fbi:
        for offense, scope, _ in failures:
            try:
                where = ({} if scope == "national"
                         else {"state": scope} if len(scope) == 2 else {"ori": scope})
                payload = await fbi.get_offenses(offense, start="01-1985",
                                                 end="12-2024", **where)
                recovered.extend(entries_from(payload, scope, agencies))
            except Exception as exc:                  # noqa: BLE001
                still_failing.append((offense, scope, str(exc)[:120]))
            time.sleep(PAUSE)

    # Merge into the files already written, replacing by series_id.
    for offense in {e["concept"] for e in recovered}:
        target = Path(data_dir) / f"fbi_series_{offense.replace('-', '_')}.yaml"
        existing = yaml.safe_load(target.read_text())["series"] if target.exists() else []
        merged = {e["series_id"]: e for e in existing}
        merged |= {e["series_id"]: e for e in recovered if e["concept"] == offense}
        rows = sorted(merged.values(), key=lambda e: e["series_id"])
        target.write_text(yaml.safe_dump(
            {"group": offense, "series_count": len(rows), "series": rows},
            sort_keys=False, allow_unicode=True, width=88))
    path.write_text(json.dumps(still_failing, indent=1) + "\n")
    return {"repaired": len(recovered), "still_failing": len(still_failing)}


def group_of(entry: dict[str, Any]) -> str:
    """The catalog group one entry belongs in, and so which file it is written to.

    Three families: the offence slug for crime, ``employment`` for staffing, and
    one group per arrest code. An arrest code gets its own file rather than
    sharing one because 48 codes in one file is a 2,700-entry diff on a
    re-harvest of any single code.
    """
    if entry["concept"] == "police_employment":
        return "employment"
    if entry["concept"] == "arrests":
        return arrest_group(entry["facets"]["offense"])
    return entry["concept"]


def export(entries: list[dict[str, Any]], data_dir: Path = DATA_DIR) -> dict[str, int]:
    """Write one catalog file per group, the way the other sources do.

    The report counts the three families apart, because they are not
    interchangeable and a total hides the one that is missing: 1,140 offence
    entries and no arrest entries reads as a healthy 1,140.
    """
    import yaml
    from collections import defaultdict

    data_dir.mkdir(parents=True, exist_ok=True)
    # One file per group, the convention every other source follows: BLS by
    # survey, BIS by dataflow, Clio by category. Here the offence slug is the
    # API's own request dimension, employment is a separate family, and an
    # arrest code is the arrest route's own request dimension.
    by_offense: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        by_offense[group_of(entry)].append(entry)
    for offense, group in sorted(by_offense.items()):
        group.sort(key=lambda e: e["series_id"])
        path = data_dir / f"fbi_series_{offense.replace('-', '_')}.yaml"
        path.write_text(yaml.safe_dump(
            {"group": offense, "series_count": len(group), "series": group},
            sort_keys=False, allow_unicode=True, width=88))
    arrests = [e for e in entries if e["concept"] == "arrests"]
    employment = [e for e in entries if e["concept"] == "police_employment"]
    arrest_groups = {group_of(e) for e in arrests}
    return {
        "entries": len(entries),
        "files": len(by_offense),
        "offense_entries": len(entries) - len(arrests) - len(employment),
        "arrest_entries": len(arrests),
        "employment_entries": len(employment),
        "offense_files": len(by_offense) - len(arrest_groups) - bool(employment),
        "arrest_files": len(arrest_groups),
        "empty_arrest_entries": sum(1 for e in arrests if e.get("empty")),
    }


if __name__ == "__main__":
    found = asyncio.run(harvest())
    print(export(found))
