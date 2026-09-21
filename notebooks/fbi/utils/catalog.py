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
from clients.fbi import OFFENSES

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


def export(entries: list[dict[str, Any]], data_dir: Path = DATA_DIR) -> dict[str, int]:
    """Write one catalog file per offence, the way the other sources do."""
    import yaml
    from collections import defaultdict

    data_dir.mkdir(parents=True, exist_ok=True)
    # One file per group, the convention every other source follows: BLS by
    # survey, BIS by dataflow, Clio by category. Here the offence slug is the
    # API's own request dimension, and employment is a separate family.
    by_offense: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        group_name = ("employment" if entry["concept"] == "police_employment"
                      else entry["concept"])
        by_offense[group_name].append(entry)
    for offense, group in sorted(by_offense.items()):
        group.sort(key=lambda e: e["series_id"])
        path = data_dir / f"fbi_series_{offense.replace('-', '_')}.yaml"
        path.write_text(yaml.safe_dump(
            {"group": offense, "series_count": len(group), "series": group},
            sort_keys=False, allow_unicode=True, width=88))
    return {"entries": len(entries), "files": len(by_offense)}


if __name__ == "__main__":
    found = asyncio.run(harvest())
    print(export(found))
