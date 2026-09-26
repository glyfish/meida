"""Clearance by reason, by month and offence, from the FBI's NIBRS incident files.

The CDE API reports clearances as one count per month, at national, state and
agency grain (``summarized/agency/{ORI}/{offense}``, see ``clients/fbi.py``),
with no split between arrest and exceptional means. The NIBRS incident files
carry every incident, so an agency's incidents can be split by how they were
cleared: by arrest, exceptionally under one of the codes A-E, or not at all.
This module reads those files straight from the zips. It does not touch
api.usa.gov and needs no key.

**Where the files are.** One zip per state and year. The CDE "Documents &
Downloads" page builds the key ``nibrs/incident/{year}/{ST}-{year}.zip`` and
asks ``https://cde.ucr.cjis.gov/LATEST/s3/signedurl?key=<key>`` for a link.
The answer is ``{key: url}``: a signed URL to the S3 bucket ``cde-prd-data``
(us-gov-east-1) that lasts 15 minutes. :func:`fetch` caches each zip in
``data/nibrs/``, which is gitignored and regenerable, and never downloads one
that is already there.

**Layout.** Each zip holds 44 CSVs, a README, a diagram and Postgres load
scripts. The 2023 zips nest the CSVs in ``NY-2023/NY/``; 2024 and 2025 are
flat. So members are found by basename and columns by header name. Tables
read here:

    agencies.csv              ori -> agency_id, pub_agency_name, nibrs_start_date
    NIBRS_incident.csv        incident_id, agency_id, incident_date, cleared_except_id
    NIBRS_OFFENSE.csv         incident_id, offense_code (up to ten per incident)
    NIBRS_ARRESTEE.csv        incident_id, one row per arrestee
    NIBRS_CLEARED_EXCEPT.csv  1-5 = A-E, 6 = N; the mapping is checked on every read

**Rules**, each checked against the NIBRS User Manual (2027.0 red-line):

* The unit is the incident. NIBRS clears incidents, not offences (p. 92). An
  incident with several of the eight offences counts once under each, and
  several codes of one offence (23C + 23F) count once for that offence. So
  the offence rows do not add up to the number of incidents.
* The reason is ``arrest`` if the incident has any arrestee record. The first
  Arrestee Segment clears the incident, and any arrest in connection with a
  Group A incident does so (pp. 92, 161). An incident already cleared by
  arrest cannot also be cleared exceptionally. Otherwise the reason is the A-E
  code if one is set, and otherwise ``not_cleared``. Code 6 (N, "Not
  Applicable") means not cleared.
* The month is the month of the incident date, never of the arrest or the
  clearance.
* A later arrest still counts. File Y attaches the arrests it carries to the
  year-Y incident, including those made early in year Y + 1, up to the file's
  cutoff (trap 2).
* Offences: homicide 09A; rape 11A + 11B + 11C; robbery 120; aggravated
  assault 13A; burglary 220; larceny 23A-23H; motor vehicle theft 240; arson
  200. 11B Sodomy and 11C Sexual Assault With An Object are "reclassified to
  11A Rape for reporting purposes". 36B Statutory Rape and 11D Criminal Sexual
  Contact are separate offences and are left out.
* Incidents with status WARNINGS are kept. They are accepted records, and the
  FBI's published 2023 New York table includes them.

**Traps**, measured on the New York and Tennessee files for 2023-2025:

1. **NYPD almost never records an exceptional clearance.** NYPD is ORI
   NY0303000, agency_id 13274. It sets an A-E code on 9, 22 and 12 incidents
   in 2023, 2024 and 2025, each cleared on the incident's own date. That is
   28 of 762,171 offence-incident rows. So an NYPD plot shows arrest against
   not cleared, and the A-E bands are invisible. That is how NYPD reports,
   not missing data. Nashville (TN0190100) clears 9.0-9.5% of incidents
   exceptionally.
2. **Late months are understated.** Each file carries arrests only up to a
   cutoff early in the next year, and that cutoff is months before the file
   was built. NYPD's latest arrest dates are 2024-02-29, 2025-02-28 and
   2026-02-28, and no arrest in any of the three New York files is later.
   Nashville's are 2024-04-01, 2025-03-26 and 2026-03-31. The files were
   built on 2024-09-20, 2025-07-02 and 2026-05-01. So the cutoff is not the
   build date, and the files do not say what sets it. A December NYPD
   incident had about two months to be cleared and a January incident about
   fourteen. Compare the same months across years, not January with December.
3. **New York's rape counts are unreliable from 2024-09 to 2025-07.** NYPD's
   11B incidents fall from 47-100 a month to zero from 2024-09, and the rest
   of the state's fall to 0-3. NYPD's 11A then swells to 370-489 a month from
   March to July 2025, against 75-167 in 2023-2024. The levels break, but
   NYPD's shares by reason hold. Tennessee has neither break: Nashville
   still reports 11B every month through 2025-12.
4. NIBRS 09A runs 2-11% below NYPD's own murder counts.
5. ``NIBRS_month.csv`` has one row per submitted document, not one per
   agency-month. Its row count equals ``NIBRS_incident.csv``'s in all six
   files, with no zero reports, and it holds a ``reported_status`` of "R"
   that the bundled README does not document. So it cannot tell a month
   nobody filed from a quiet one, and it is not read here.
6. TN-2023 carries two build dates. Its offence and arrestee tables are dated
   2024-07-10 and its incident table 2024-09-20. Every Nashville arrestee
   still matches an incident in the same zip.
7. Nebraska's ORIs begin ``NB``, but its file is ``NE-{year}.zip``. In the
   CDE agency list, every other state's ORI prefix is its postal code.
8. Every incident in the six files is dated in the file's year. A row that is
   not raises an error rather than landing silently in the wrong year.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import shutil
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from operator import itemgetter
from pathlib import Path
from typing import Iterable, Iterator, NamedTuple

NIBRS_DIR = Path(__file__).resolve().parents[1] / "data" / "nibrs"

#: The CDE web app's signing service. It takes ``key`` and answers ``{key: url}``.
SIGNED_URL = "https://cde.ucr.cjis.gov/LATEST/s3/signedurl"

#: Offence groups and their NIBRS codes. For rape, see the module docstring.
OFFENSES: dict[str, tuple[str, ...]] = {
    "homicide": ("09A",),
    "rape": ("11A", "11B", "11C"),
    "robbery": ("120",),
    "aggravated_assault": ("13A",),
    "burglary": ("220",),
    "larceny": ("23A", "23B", "23C", "23D", "23E", "23F", "23G", "23H"),
    "motor_vehicle_theft": ("240",),
    "arson": ("200",),
}
CODE_TO_OFFENSE: dict[str, str] = {code: off for off, codes in OFFENSES.items() for code in codes}

#: Reasons in plotting order: arrest, the five exceptional codes, not cleared.
REASONS: tuple[str, ...] = ("arrest", "A", "B", "C", "D", "E", "not_cleared")

#: Display labels. For A-E these are the ``cleared_except_name`` values in
#: NIBRS_CLEARED_EXCEPT.csv.
REASON_LABELS: dict[str, str] = {
    "arrest": "Cleared by Arrest",
    "A": "Death of Offender",
    "B": "Prosecution Declined",
    "C": "In Custody of Other Jurisdiction",
    "D": "Victim Refused to Cooperate",
    "E": "Juvenile/No Custody",
    "not_cleared": "Not Cleared",
}

#: ``cleared_except_id`` -> code. Id 6 is N (not applicable), which means not cleared.
EXCEPTIONAL: dict[str, str] = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"}

#: ORI prefixes that are not the state's postal code.
ORI_STATE: dict[str, str] = {"NB": "NE"}


class Agency(NamedTuple):
    """One agencies.csv row, for one year's file."""

    ori: str
    year: int
    agency_id: str
    name: str
    nibrs_start_date: str


class Cell(NamedTuple):
    """Incidents of one offence in one month, cleared for one reason."""

    year: int
    month: int
    offense: str
    reason: str
    incidents: int


class Share(NamedTuple):
    """Pooled incidents for one offence and reason, and their share of the offence."""

    offense: str
    reason: str
    incidents: int
    share: float


class UnknownAgency(LookupError):
    """The ORI is not in that state-year's agencies.csv."""


class NoIncidents(LookupError):
    """The ORI is in that state-year's agencies.csv but has no incident at all in it.

    The files carry no zero reports (trap 5), so a year like that cannot be
    told apart from a year that was never reported. Each of the six files
    checked lists one to three such agencies, e.g. Youngstown Village
    (NY0312300) in NY-2023.
    """


def state_of(ori: str) -> str:
    """The postal code whose file holds *ori*: its first two letters, except NB -> NE."""
    prefix = ori.strip().upper()[:2]
    return ORI_STATE.get(prefix, prefix)


def key(state: str, year: int) -> str:
    """The S3 key the CDE downloads page asks to have signed."""
    return f"nibrs/incident/{year}/{state.upper()}-{year}.zip"


def _signed_url(object_key: str) -> str:
    """A 15-minute download link for *object_key*."""
    query = urllib.parse.urlencode({"key": object_key})
    with urllib.request.urlopen(f"{SIGNED_URL}?{query}", timeout=60) as response:
        url = json.load(response).get(object_key)
    if not url:
        raise FileNotFoundError(f"the CDE signed no URL for {object_key}")
    return url


def fetch(state: str, year: int, directory: Path = NIBRS_DIR) -> Path:
    """Return the cached ``{ST}-{year}.zip``, downloading it first only if absent.

    The download streams to ``<name>.part`` and is renamed only after its
    length matches the server's and it opens as a zip. So an interrupted or
    truncated download never looks cached. A leftover ``.part`` is
    overwritten on the next try.
    """
    state = state.upper()
    path = Path(directory) / f"{state}-{year}.zip"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    try:
        with urllib.request.urlopen(_signed_url(key(state, year)), timeout=600) as response, \
                open(part, "wb") as out:
            shutil.copyfileobj(response, out, 1 << 20)
            expected = response.headers.get("Content-Length")
        size = part.stat().st_size
        if expected is not None and size != int(expected):
            raise OSError(f"{path.name}: received {size:,} of {int(expected):,} bytes")
        with zipfile.ZipFile(part):                    # the central directory is at the end
            pass
        os.replace(part, path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return path


def _member(zf: zipfile.ZipFile, name: str) -> str:
    """The one member called *name*, at whatever depth this year's layout uses."""
    hits = [n for n in zf.namelist() if n.rsplit("/", 1)[-1] == name]
    if len(hits) != 1:
        raise KeyError(f"expected one {name} in the zip, found {hits}")
    return hits[0]


def _rows(zf: zipfile.ZipFile, name: str, columns: tuple[str, ...]) -> Iterator[tuple[str, ...]]:
    """The named columns of every row of one CSV, read without extracting it."""
    with zf.open(_member(zf, name)) as raw:
        reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace",
                                             newline=""))
        header = next(reader)
        missing = [c for c in columns if c not in header]
        if missing:
            raise KeyError(f"{name} has no column {missing}; it has {header}")
        pick = itemgetter(*(header.index(c) for c in columns))
        if len(columns) == 1:
            for row in reader:
                yield (pick(row),)
        else:
            yield from map(pick, reader)


def _agency(zf: zipfile.ZipFile, ori: str, year: int) -> Agency:
    found = [Agency(ori, year, agency_id, name, start)
             for o, agency_id, name, start in _rows(
                 zf, "agencies.csv", ("ori", "agency_id", "pub_agency_name", "nibrs_start_date"))
             if o == ori]
    if len(found) != 1:
        where = f"{state_of(ori)}-{year}.zip"
        raise UnknownAgency(f"{ori} appears {len(found)} times in {where}'s agencies.csv")
    return found[0]


def agency(ori: str, year: int) -> Agency:
    """Look *ori* up in that year's agencies.csv. Raises :class:`UnknownAgency`."""
    ori = ori.strip().upper()
    with zipfile.ZipFile(fetch(state_of(ori), year)) as zf:
        return _agency(zf, ori, year)


def _check_exceptional_codes(zf: zipfile.ZipFile) -> None:
    """Stop if NIBRS_CLEARED_EXCEPT.csv no longer maps 1-5 to A-E and 6 to N."""
    found = dict(_rows(zf, "NIBRS_CLEARED_EXCEPT.csv",
                       ("cleared_except_id", "cleared_except_code")))
    if found != {**EXCEPTIONAL, "6": "N"}:
        raise ValueError(f"NIBRS_CLEARED_EXCEPT.csv has changed: {found}")


def _year_counts(zf: zipfile.ZipFile, ori: str, year: int) -> Counter[tuple[int, str, str]]:
    """``(month, offense, reason) -> incidents`` for one agency in one file."""
    _check_exceptional_codes(zf)
    listed = _agency(zf, ori, year)
    agency_id = listed.agency_id

    month: dict[str, int] = {}
    code: dict[str, str] = {}
    for incident, owner, date, cleared in _rows(
            zf, "NIBRS_incident.csv",
            ("incident_id", "agency_id", "incident_date", "cleared_except_id")):
        if owner != agency_id:
            continue
        if incident in month:
            raise ValueError(f"incident {incident} appears twice in NIBRS_incident.csv")
        if date[:4] != str(year):
            raise ValueError(f"incident {incident} is dated {date}, outside the {year} file")
        month[incident] = int(date[5:7])
        code[incident] = EXCEPTIONAL.get(cleared, "")
    if not month:
        raise NoIncidents(f"{ori} ({listed.name}) has no incidents in {state_of(ori)}-{year}.zip; "
                          "the file cannot tell a year with none from a year not reported")

    offenses: dict[str, set[str]] = {}
    for incident, offense_code in _rows(zf, "NIBRS_OFFENSE.csv", ("incident_id", "offense_code")):
        offense = CODE_TO_OFFENSE.get(offense_code)
        if offense and incident in month:
            offenses.setdefault(incident, set()).add(offense)

    arrested = {incident for (incident,) in _rows(zf, "NIBRS_ARRESTEE.csv", ("incident_id",))
                if incident in month}

    counts: Counter[tuple[int, str, str]] = Counter()
    for incident, groups in offenses.items():
        reason = "arrest" if incident in arrested else code[incident] or "not_cleared"
        for offense in groups:
            counts[month[incident], offense, reason] += 1
    return counts


def clearance_by_reason(ori: str, years: Iterable[int]) -> list[Cell]:
    """Incidents by year, month, offence and reason for one agency.

    Every combination is returned, zeros included, in the order year, month,
    offence (as :data:`OFFENSES`), reason (as :data:`REASONS`). So a missing
    row never stands in for a zero. The rules are in the module docstring.
    Rather than return a year of zeros, it raises :class:`UnknownAgency` if
    *ori* is missing from any year's agencies.csv, and :class:`NoIncidents` if
    it is listed but has no incident at all that year. An agency with
    incidents, but none of the eight offences, gets real zeros.
    """
    ori = ori.strip().upper()
    wanted = sorted(set(years))
    if not wanted:
        raise ValueError("no years given")
    cells: list[Cell] = []
    for year in wanted:
        with zipfile.ZipFile(fetch(state_of(ori), year)) as zf:
            counts = _year_counts(zf, ori, year)
        cells.extend(Cell(year, m, off, reason, counts.get((m, off, reason), 0))
                     for m in range(1, 13) for off in OFFENSES for reason in REASONS)
    return cells


def pooled(cells: Iterable[Cell]) -> list[Share]:
    """Incidents and shares by reason for each offence, summed over the cells given.

    Filter the cells first to pool a subset, for example to leave out the late
    months that have had less time to clear. An offence with no incidents gets
    ``nan`` shares rather than zeros.
    """
    cells = list(cells)
    totals: Counter[tuple[str, str]] = Counter()
    for cell in cells:
        totals[cell.offense, cell.reason] += cell.incidents
    present = {cell.offense for cell in cells}
    out: list[Share] = []
    for offense in (o for o in OFFENSES if o in present):
        n = sum(totals[offense, r] for r in REASONS)
        out.extend(Share(offense, r, totals[offense, r], totals[offense, r] / n if n else math.nan)
                   for r in REASONS)
    return out
