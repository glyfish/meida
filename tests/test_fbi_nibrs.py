"""Tests for the NIBRS clearance reader (``notebooks/fbi/utils/nibrs.py``).

No network. Each test builds a small state-year zip in memory, using the full
headers of the FBI's tables as they appear in NY-2024. The zip is handed to
the reader in place of :func:`fetch`, so columns are found by name exactly as
they are in the real files.

What is pinned is the counting rules. Each was checked against the NIBRS User
Manual, and breaking any of them would move a clearance share without raising
an error:

* an incident with several of the eight offences counts once under each;
* an arrestee record beats an exceptional code;
* code 6 (N) is not cleared;
* rape is 11A + 11B + 11C, not 11D or 36B;
* the month comes from the incident date;
* an arrest made the next year still clears the incident;
* every cell comes back, zeros included;
* an ORI missing from a year's file, or listed with no incident at all, raises
  instead of giving a year of zeros.

Alongside those, the guards: the 2023 nested layout, a renumbered
cleared-except table, an incident dated outside its file, Nebraska's NB
prefix, and a download that fails part way or comes up short of its
Content-Length.

The last tests rerun NYPD 2023-2025 from the cached zips. They must reproduce
the verified table byte for byte. They are skipped when the cache is absent
or holds a different vintage of the files.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import zipfile
from pathlib import Path
from typing import Callable

import pytest

from notebook_modules import load

N = load("fbi/utils", "nibrs")

ORI, AGENCY_ID = "VT0040100", "5001"
OTHER_ORI, OTHER_ID = "VT0040200", "5002"

# Headers copied from the NY-2024 zip. The reader must find its columns by name.
AGENCIES_HEADER = tuple(
    "yearly_agency_id,agency_id,data_year,ori,legacy_ori,covered_by_legacy_ori,"
    "direct_contributor_flag,dormant_flag,dormant_year,reporting_type,ucr_agency_name,"
    "ncic_agency_name,pub_agency_name,pub_agency_unit,agency_status,state_id,state_name,"
    "state_abbr,state_postal_abbr,division_code,division_name,region_code,region_name,"
    "region_desc,agency_type_name,population,submitting_agency_id,sai,submitting_agency_name,"
    "suburban_area_flag,population_group_id,population_group_code,population_group_desc,"
    "parent_pop_group_code,parent_pop_group_desc,mip_flag,pop_sort_order,summary_rape_def,"
    "pe_reported_flag,male_officer,male_civilian,male_officer+male_civilian,female_officer,"
    "female_civilian,female_officer+female_civilian,officer_rate,employee_rate,nibrs_cert_date,"
    "nibrs_start_date,nibrs_leoka_start_date,nibrs_ct_start_date,nibrs_multi_bias_start_date,"
    "nibrs_off_eth_start_date,covered_flag,county_name,msa_name,publishable_flag,participated,"
    "nibrs_participated".split(","))
INCIDENT_HEADER = tuple(
    "data_year,agency_id,incident_id,nibrs_month_id,cargo_theft_flag,submission_date,"
    "incident_date,report_date_flag,incident_hour,cleared_except_id,cleared_except_date,"
    "incident_status,data_home,orig_format,did".split(","))
OFFENSE_HEADER = tuple(
    "data_year,offense_id,incident_id,offense_code,attempt_complete_flag,location_id,"
    "num_premises_entered,method_entry_code".split(","))
ARRESTEE_HEADER = tuple(
    "data_year,arrestee_id,incident_id,arrestee_seq_num,arrest_date,arrest_type_id,"
    "multiple_indicator,offense_code,age_id,age_num,sex_code,race_id,ethnicity_id,"
    "resident_code,under_18_disposition_code,clearance_ind,age_range_low_num,"
    "age_range_high_num".split(","))
CLEARED_EXCEPT_HEADER = ("cleared_except_id", "cleared_except_code", "cleared_except_name",
                         "cleared_except_desc")
CLEARED_EXCEPT_ROWS = [
    ("1", "A", "Death of Offender", "Death of Offender"),
    ("2", "B", "Prosecution Declined", "Prosecution Declined (by the prosecutor ...)"),
    ("3", "C", "In Custody of Other Jurisdiction", "In Custody of Other Jurisdiction"),
    ("4", "D", "Victim Refused to Cooperate", "Victim Refused to Cooperate (in the prosecution)"),
    ("5", "E", "Juvenile/No Custody", "Juvenile/No Custody (the handling of a juvenile ...)"),
    ("6", "N", "Not Applicable", "Not Applicable (not cleared exceptionally)"),
]


def _csv(header: tuple[str, ...], rows: list[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, header, restval="", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


class StateYear:
    """One state-year zip under construction: an agency, its incidents, offences, arrests."""

    def __init__(self, year: int, agencies: tuple[tuple[str, str], ...] = (
            (ORI, AGENCY_ID), (OTHER_ORI, OTHER_ID))) -> None:
        self.year = year
        self.agencies = [{"yearly_agency_id": f"{aid}{year}", "agency_id": aid,
                          "data_year": str(year), "ori": ori, "pub_agency_name": f"Town {aid}",
                          "nibrs_start_date": "2021-01-01"} for ori, aid in agencies]
        self.cleared_except = [dict(zip(CLEARED_EXCEPT_HEADER, r)) for r in CLEARED_EXCEPT_ROWS]
        self.incidents: list[dict[str, str]] = []
        self.offenses: list[dict[str, str]] = []
        self.arrestees: list[dict[str, str]] = []

    def add(self, date: str, *codes: str, cleared: str = "6", arrests: tuple[str, ...] = (),
            agency_id: str = AGENCY_ID, **fields: str) -> str:
        """One incident dated *date* with offence *codes*; returns its incident_id."""
        incident = str(900_000 + len(self.incidents))
        self.incidents.append({"data_year": str(self.year), "agency_id": agency_id,
                               "incident_id": incident, "nibrs_month_id": "1",
                               "submission_date": f"{date} 12:00:00.000", "incident_date": date,
                               "cleared_except_id": cleared, "incident_status": "ACCEPTED",
                               **fields})
        for code in codes:
            self.offenses.append({"data_year": str(self.year),
                                  "offense_id": str(len(self.offenses) + 1),
                                  "incident_id": incident, "offense_code": code,
                                  "attempt_complete_flag": "C"})
        for seq, when in enumerate(arrests, 1):
            self.arrestees.append({"data_year": str(self.year),
                                   "arrestee_id": str(len(self.arrestees) + 1),
                                   "incident_id": incident, "arrestee_seq_num": str(seq),
                                   "arrest_date": when, "arrest_type_id": "3",
                                   "offense_code": codes[0] if codes else ""})
        return incident

    def zip(self, prefix: str = "") -> bytes:
        """The zip; *prefix* nests the members the way the 2023 files do."""
        tables = {
            "agencies.csv": (AGENCIES_HEADER, self.agencies),
            "NIBRS_incident.csv": (INCIDENT_HEADER, self.incidents),
            "NIBRS_OFFENSE.csv": (OFFENSE_HEADER, self.offenses),
            "NIBRS_ARRESTEE.csv": (ARRESTEE_HEADER, self.arrestees),
            "NIBRS_CLEARED_EXCEPT.csv": (CLEARED_EXCEPT_HEADER, self.cleared_except),
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, (header, rows) in tables.items():
                zf.writestr(prefix + name, _csv(header, rows))
            zf.writestr(prefix + "README.md", "not a table\n")
        return buffer.getvalue()


Serve = Callable[..., None]


@pytest.fixture
def serve(monkeypatch: pytest.MonkeyPatch) -> Serve:
    """Stand in for :func:`nibrs.fetch`: serve zips from memory, keyed by (state, year)."""
    files: dict[tuple[str, int], bytes] = {}

    def fake_fetch(state: str, year: int, directory: Path | None = None) -> io.BytesIO:
        if (state, year) not in files:
            raise FileNotFoundError(f"{state}-{year}.zip was not served")
        return io.BytesIO(files[state, year])

    def install(*state_years: StateYear, state: str = "VT", prefix: str = "") -> None:
        for sy in state_years:
            files[state, sy.year] = sy.zip(prefix)

    monkeypatch.setattr(N, "fetch", fake_fetch)
    return install


def _grid(cells: list) -> dict[tuple[int, int, str, str], int]:
    return {(c.year, c.month, c.offense, c.reason): c.incidents for c in cells}


def _nonzero(cells: list) -> dict[tuple[int, int, str, str], int]:
    return {k: v for k, v in _grid(cells).items() if v}


# --- the counting rules --------------------------------------------------------------


def test_an_incident_with_several_offences_counts_once_under_each(serve: Serve) -> None:
    """Robbery + aggravated assault + two larceny codes: one each, larceny once."""
    sy = StateYear(2024)
    sy.add("2024-06-10", "120", "13A", "23C", "23F", "520")
    serve(sy)
    assert _nonzero(N.clearance_by_reason(ORI, [2024])) == {
        (2024, 6, "robbery", "not_cleared"): 1,
        (2024, 6, "aggravated_assault", "not_cleared"): 1,
        (2024, 6, "larceny", "not_cleared"): 1,
    }


def test_an_arrestee_beats_an_exceptional_code(serve: Serve) -> None:
    sy = StateYear(2024)
    sy.add("2024-02-01", "13A", cleared="4", arrests=("2024-02-03",))
    sy.add("2024-02-01", "13A", cleared="4")
    serve(sy)
    assert _nonzero(N.clearance_by_reason(ORI, [2024])) == {
        (2024, 2, "aggravated_assault", "arrest"): 1,
        (2024, 2, "aggravated_assault", "D"): 1,
    }


def test_several_arrestees_clear_an_incident_once(serve: Serve) -> None:
    sy = StateYear(2024)
    sy.add("2024-02-01", "120", arrests=("2024-02-01", "2024-02-02", "2024-03-09"))
    serve(sy)
    assert _nonzero(N.clearance_by_reason(ORI, [2024])) == {(2024, 2, "robbery", "arrest"): 1}


@pytest.mark.parametrize("cleared, reason", [
    ("1", "A"), ("2", "B"), ("3", "C"), ("4", "D"), ("5", "E"), ("6", "not_cleared")])
def test_exceptional_ids_become_letters_and_6_is_not_cleared(
        serve: Serve, cleared: str, reason: str) -> None:
    sy = StateYear(2024)
    sy.add("2024-05-05", "220", cleared=cleared)
    serve(sy)
    assert _nonzero(N.clearance_by_reason(ORI, [2024])) == {(2024, 5, "burglary", reason): 1}


#: The brief's offence codes, written out here rather than read from the module.
CODE_OFFENSE = [
    ("09A", "homicide"), ("11A", "rape"), ("11B", "rape"), ("11C", "rape"), ("120", "robbery"),
    ("13A", "aggravated_assault"), ("220", "burglary"),
    *((f"23{letter}", "larceny") for letter in "ABCDEFGH"),
    ("240", "motor_vehicle_theft"), ("200", "arson"),
]


@pytest.mark.parametrize("code, offense", CODE_OFFENSE)
def test_each_offence_code_counts_under_its_offence(serve: Serve, code: str, offense: str) -> None:
    sy = StateYear(2024)
    sy.add("2024-10-10", code)
    serve(sy)
    assert _nonzero(N.clearance_by_reason(ORI, [2024])) == {(2024, 10, offense, "not_cleared"): 1}


def test_no_other_code_counts() -> None:
    assert sorted(N.CODE_TO_OFFENSE.items()) == sorted(CODE_OFFENSE)


def test_rape_takes_11a_11b_11c_and_not_11d_or_36b(serve: Serve) -> None:
    sy = StateYear(2024)
    for code in ("11A", "11B", "11C", "11D", "36B"):
        sy.add("2024-01-15", code)
    sy.add("2024-01-15", "11A", "11B")               # one incident, one rape
    serve(sy)
    assert _nonzero(N.clearance_by_reason(ORI, [2024])) == {
        (2024, 1, "rape", "not_cleared"): 4}


def test_the_month_is_the_incident_dates(serve: Serve) -> None:
    """Not the submission, the NIBRS month id, the arrest or the clearance date."""
    sy = StateYear(2024)
    sy.add("2024-03-31", "240", arrests=("2024-05-02",), nibrs_month_id="777",
           submission_date="2024-04-15 09:00:00.000")
    sy.add("2024-03-01", "240", cleared="2", cleared_except_date="2024-06-30")
    serve(sy)
    assert _nonzero(N.clearance_by_reason(ORI, [2024])) == {
        (2024, 3, "motor_vehicle_theft", "arrest"): 1,
        (2024, 3, "motor_vehicle_theft", "B"): 1,
    }


def test_an_arrest_made_the_next_year_still_clears(serve: Serve) -> None:
    sy = StateYear(2024)
    sy.add("2024-12-20", "09A", arrests=("2025-02-10",))
    serve(sy)
    assert _nonzero(N.clearance_by_reason(ORI, [2024])) == {(2024, 12, "homicide", "arrest"): 1}


def test_warnings_status_incidents_are_kept(serve: Serve) -> None:
    sy = StateYear(2024)
    sy.add("2024-07-04", "200", incident_status="WARNINGS")
    serve(sy)
    assert _nonzero(N.clearance_by_reason(ORI, [2024])) == {(2024, 7, "arson", "not_cleared"): 1}


def test_other_agencies_in_the_file_are_ignored(serve: Serve) -> None:
    sy = StateYear(2024)
    sy.add("2024-08-08", "120", agency_id=OTHER_ID, arrests=("2024-08-09",))
    sy.add("2024-08-08", "120")
    serve(sy)
    assert _nonzero(N.clearance_by_reason(ORI, [2024])) == {(2024, 8, "robbery", "not_cleared"): 1}


def test_every_cell_is_returned_even_when_zero(serve: Serve) -> None:
    first, second = StateYear(2023), StateYear(2024)
    first.add("2023-01-02", "120")
    second.add("2024-03-03", "520")                  # a year with none of the eight offences
    serve(first, prefix="VT-2023/VT/")
    serve(second)
    cells = N.clearance_by_reason(ORI, [2024, 2023, 2024])
    assert len(cells) == 2 * 12 * len(N.OFFENSES) * len(N.REASONS) == 1344
    assert len(_grid(cells)) == len(cells)
    assert sum(c.incidents for c in cells) == 1
    assert cells[0] == N.Cell(2023, 1, "homicide", "arrest", 0)
    assert cells[-1] == N.Cell(2024, 12, "arson", "not_cleared", 0)
    order = [(c.year, c.month, list(N.OFFENSES).index(c.offense), N.REASONS.index(c.reason))
             for c in cells]
    assert order == sorted(order)


def test_the_2023_nested_layout_is_read(serve: Serve) -> None:
    sy = StateYear(2023)
    sy.add("2023-09-09", "13A", arrests=("2023-09-09",))
    serve(sy, prefix="VT-2023/VT/")
    assert _nonzero(N.clearance_by_reason(ORI, [2023])) == {
        (2023, 9, "aggravated_assault", "arrest"): 1}


# --- guards ------------------------------------------------------------------------------


def test_an_unknown_ori_raises(serve: Serve) -> None:
    serve(StateYear(2024))
    with pytest.raises(N.UnknownAgency, match="VT9999999"):
        N.clearance_by_reason("VT9999999", [2024])
    with pytest.raises(LookupError):
        N.agency("VT9999999", 2024)


def test_an_ori_missing_from_one_year_raises_rather_than_giving_zeros(serve: Serve) -> None:
    listed, unlisted = StateYear(2024), StateYear(2025, agencies=((OTHER_ORI, OTHER_ID),))
    listed.add("2024-05-05", "120")
    serve(listed, unlisted)
    with pytest.raises(N.UnknownAgency, match="2025"):
        N.clearance_by_reason(ORI, [2024, 2025])


def test_a_listed_agency_with_no_incidents_raises_rather_than_giving_zeros(serve: Serve) -> None:
    """Listed in agencies.csv, but not one incident of any kind: not a year of zeros."""
    reported, silent = StateYear(2024), StateYear(2025)
    reported.add("2024-05-05", "120")
    silent.add("2025-05-05", "120", agency_id=OTHER_ID)
    serve(reported, silent)
    with pytest.raises(N.NoIncidents, match=f"{ORI} \\(Town 5001\\) has no incidents in VT-2025"):
        N.clearance_by_reason(ORI, [2024, 2025])
    assert issubclass(N.NoIncidents, LookupError)
    assert N.agency(ORI, 2025).agency_id == AGENCY_ID      # the lookup itself still works


def test_a_renumbered_cleared_except_table_is_refused(serve: Serve) -> None:
    sy = StateYear(2024)
    first, second = sy.cleared_except[0], sy.cleared_except[1]
    first["cleared_except_code"], second["cleared_except_code"] = "B", "A"
    serve(sy)
    with pytest.raises(ValueError, match="NIBRS_CLEARED_EXCEPT"):
        N.clearance_by_reason(ORI, [2024])


def test_an_incident_dated_outside_its_file_raises(serve: Serve) -> None:
    sy = StateYear(2024)
    sy.add("2023-12-31", "120")
    serve(sy)
    with pytest.raises(ValueError, match="outside the 2024 file"):
        N.clearance_by_reason(ORI, [2024])


def test_nebraska_oris_read_the_ne_file(serve: Serve) -> None:
    assert N.state_of("NB0280100") == "NE"
    assert N.state_of(" ny0303000 ") == "NY"
    sy = StateYear(2024, agencies=(("NB0280100", "7001"),))
    sy.add("2024-04-04", "120", agency_id="7001")
    serve(sy, state="NE")
    assert _nonzero(N.clearance_by_reason("nb0280100", [2024])) == {
        (2024, 4, "robbery", "not_cleared"): 1}


def test_no_years_is_an_error(serve: Serve) -> None:
    with pytest.raises(ValueError):
        N.clearance_by_reason(ORI, [])


# --- helpers -----------------------------------------------------------------------------


def test_agency_lookup(serve: Serve) -> None:
    serve(StateYear(2024))
    assert N.agency(ORI.lower(), 2024) == N.Agency(ORI, 2024, AGENCY_ID, "Town 5001", "2021-01-01")


def test_pooled_shares_by_reason(serve: Serve) -> None:
    sy = StateYear(2024)
    sy.add("2024-01-01", "120", arrests=("2024-01-02",))
    sy.add("2024-06-01", "120", cleared="4")
    sy.add("2024-12-01", "120")
    sy.add("2024-12-01", "120")
    serve(sy)
    shares = {(s.offense, s.reason): s for s in N.pooled(N.clearance_by_reason(ORI, [2024]))}
    assert len(shares) == len(N.OFFENSES) * len(N.REASONS)
    assert shares["robbery", "arrest"] == N.Share("robbery", "arrest", 1, 0.25)
    assert shares["robbery", "D"].share == 0.25
    assert shares["robbery", "not_cleared"].share == 0.5
    assert shares["robbery", "A"] == N.Share("robbery", "A", 0, 0.0)
    assert math.isnan(shares["homicide", "arrest"].share)     # no homicides: undefined, not 0


def test_pooled_covers_only_the_offences_given() -> None:
    cells = [N.Cell(2024, 1, "burglary", r, 1 if r == "arrest" else 0) for r in N.REASONS]
    assert [s.offense for s in N.pooled(cells)] == ["burglary"] * len(N.REASONS)


def test_labels_cover_every_reason() -> None:
    assert list(N.REASON_LABELS) == list(N.REASONS)
    assert {N.REASON_LABELS[c] for c in "ABCDE"} == {r[2] for r in CLEARED_EXCEPT_ROWS[:5]}


# --- fetch: the cache, and a download that fails part way -------------------------------


class _Response(io.BytesIO):
    """A stand-in for the S3 response: a body and the Content-Length it claims."""

    def __init__(self, body: bytes, length: int | None = None) -> None:
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body) if length is None else length)}


def _no_network(*args: object, **kwargs: object) -> None:
    raise AssertionError("the network was touched")


def test_fetch_returns_a_cached_zip_without_asking(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "VT-2024.zip").write_bytes(b"cached")
    monkeypatch.setattr(N, "_signed_url", _no_network)
    monkeypatch.setattr(N.urllib.request, "urlopen", _no_network)
    assert N.fetch("vt", 2024, directory=tmp_path) == tmp_path / "VT-2024.zip"


def test_fetch_asks_for_the_key_the_downloads_page_uses(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []
    body = StateYear(2024).zip()
    monkeypatch.setattr(N, "_signed_url", lambda k: asked.append(k) or "https://s3.test/signed")
    monkeypatch.setattr(N.urllib.request, "urlopen", lambda url, timeout: _Response(body))
    path = N.fetch("VT", 2024, directory=tmp_path)
    assert asked == ["nibrs/incident/2024/VT-2024.zip"]
    assert path.read_bytes() == body
    assert sorted(p.name for p in tmp_path.iterdir()) == ["VT-2024.zip"]


def _whole_zip() -> bytes:
    return StateYear(2024).zip()


@pytest.mark.parametrize("response, error, message", [
    (lambda: _Response(_whole_zip()[:100], length=len(_whole_zip())), OSError, "received 100 of"),
    # A whole, valid zip that is still short of its Content-Length. http.client's
    # read(amt) does not raise when the connection closes early, so only the
    # length check catches this one.
    (lambda: _Response(_whole_zip(), length=len(_whole_zip()) + 1), OSError, "received"),
    (lambda: _Response(b"<Error>AccessDenied</Error>"), zipfile.BadZipFile, None),
], ids=["truncated", "whole-zip-short-of-its-length", "not-a-zip"])
def test_a_broken_download_never_looks_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                              response: Callable[[], _Response],
                                              error: type[Exception], message: str | None) -> None:
    monkeypatch.setattr(N, "_signed_url", lambda k: "https://s3.test/signed")
    monkeypatch.setattr(N.urllib.request, "urlopen", lambda url, timeout: response())
    with pytest.raises(error, match=message):
        N.fetch("VT", 2024, directory=tmp_path)
    assert list(tmp_path.iterdir()) == []


# --- the verified NYPD table, from the cached zips -------------------------------------

#: SHA-256 of the zips the verified table was built from (downloaded 2026-09-21).
VERIFIED_ZIPS = {
    "NY-2023.zip": "c9f3ccde2b6c4e3651f1091f22091df7c8bb38103301d74c7f20c548f53152da",
    "NY-2024.zip": "e9af4fc6db0f6d1212543fcbe9a30634cbced9f98b833db0998c01b5179e0b88",
    "NY-2025.zip": "d1d7796cdea16e848bcbbb06a985ff880d50f096bca92d1582323dd1dd7a64f8",
}
#: SHA-256 of nypd_clearance_by_reason.csv as built and independently re-derived.
VERIFIED_CSV_SHA256 = "43c45a94950456341dd72cb04e97db1ec9aea0120ef9a5b07017c3126d50f2fa"
#: The reason names that table uses.
VERIFIED_REASON_NAMES = {
    "arrest": "arrest",
    "A": "exceptional_A_death_of_offender",
    "B": "exceptional_B_prosecution_declined",
    "C": "exceptional_C_in_custody_other_jurisdiction",
    "D": "exceptional_D_victim_refused_to_cooperate",
    "E": "exceptional_E_juvenile_no_custody",
    "not_cleared": "not_cleared",
}
#: Its 2023-2025 totals: arrest, A, B, C, D, E, not cleared.
NYPD_POOLED = {
    "homicide": (634, 9, 0, 0, 0, 0, 307),
    "rape": (2732, 1, 0, 0, 0, 0, 4703),
    "robbery": (24078, 1, 0, 0, 1, 0, 22851),
    "aggravated_assault": (76093, 5, 0, 0, 4, 1, 33305),
    "burglary": (16458, 0, 0, 0, 0, 4, 23780),
    "larceny": (130381, 0, 0, 0, 1, 1, 373802),
    "motor_vehicle_theft": (8384, 0, 0, 0, 0, 0, 42264),
    "arson": (603, 0, 0, 0, 0, 0, 1768),
}


def _verified_cache() -> list[Path]:
    """The cached NY zips, or a skip if any is absent or is not the verified vintage."""
    paths = [N.NIBRS_DIR / name for name in VERIFIED_ZIPS]
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"NIBRS cache absent: {missing} not in {N.NIBRS_DIR}")
    for path in paths:
        with open(path, "rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != VERIFIED_ZIPS[path.name]:
                pytest.skip(f"{path.name} is not the vintage the table was verified on")
    return paths


def test_reproduces_the_verified_nypd_table_from_the_cache() -> None:
    _verified_cache()
    cells = N.clearance_by_reason("NY0303000", [2023, 2024, 2025])
    pooled = {}
    for s in N.pooled(cells):
        pooled.setdefault(s.offense, []).append(s.incidents)
    assert {k: tuple(v) for k, v in pooled.items()} == NYPD_POOLED
    text = "year,month,offense,reason,incidents\n" + "".join(
        f"{c.year},{c.month},{c.offense},{VERIFIED_REASON_NAMES[c.reason]},{c.incidents}\n"
        for c in cells)
    assert hashlib.sha256(text.encode()).hexdigest() == VERIFIED_CSV_SHA256


def test_a_real_listed_agency_with_no_incidents_raises() -> None:
    """Youngstown Village is in NY-2023's agencies.csv with no incident at all."""
    _verified_cache()
    with pytest.raises(N.NoIncidents, match="NY0312300 \\(Youngstown Village\\)"):
        N.clearance_by_reason("NY0312300", [2023])


def test_labels_match_the_fbi_table_in_every_cached_zip() -> None:
    for path in _verified_cache():
        with zipfile.ZipFile(path) as zf:
            names = {code: name for code, name in N._rows(
                zf, "NIBRS_CLEARED_EXCEPT.csv", ("cleared_except_code", "cleared_except_name"))}
        assert {c: N.REASON_LABELS[c] for c in "ABCDE"} == {c: names[c] for c in "ABCDE"}
