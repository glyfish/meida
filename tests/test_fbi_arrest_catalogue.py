"""Tests for the arrest half of the FBI catalogue.

``notebooks/fbi/utils/catalog.py``'s :func:`arrest_entries`, :func:`export` and
note table, and ``notebooks/fbi/utils/arrest_harvest.py``'s resumable loop. No
network: every payload is hand-built in the shape the live route returns, and
every figure a case turns on is one measured against the live API and named in
the test.

What is pinned is the decisions a full harvest cannot be re-run to check:

* an entry describes what ``fbi_arrests`` *returns*, so its span is the filings
  and not the requested window -- the NYPD's murder arrests start 01-2023, not
  at the 01-2018 the request asked for;
* ``retrieval`` minus ``tool`` is exactly what the tool takes, checked against
  the tool's own published schema rather than against a list restated here;
* a code with no arrests is catalogued, marked ``empty``, because "Vermont files
  no gambling arrests" and "nobody harvested gambling" must not look alike;
* every code in the FBI's table has a note, since five of the names mislead and
  a caller who reads only the name publishes a wrong number;
* the arrest files sort beside the offence files and collide with none of them;
* and a second run over a full checkpoint makes **no** requests, which is the
  only reason a three-hour harvest can be killed.
"""
from __future__ import annotations

import json

import pytest

from notebook_modules import load

catalog = load("fbi/utils", "catalog")
harvester = load("fbi/utils", "arrest_harvest")

from clients.fbi import ARREST_OFFENSES, PARTICIPATED                # noqa: E402
from clients.models.fbi import (                                     # noqa: E402
    FbiArrestResponse,
    FbiObservation,
    FbiSeries,
)
from mcp_server import server                                        # noqa: E402


# --- Payloads ----------------------------------------------------------------


def _months(count: int, first_year: int = 2018) -> list[str]:
    out = [f"{month:02d}-{year}" for year in range(first_year, first_year + 20)
           for month in range(1, 13)]
    return out[:count]


def _payload(values, *, code: str = "11", scope: str = "TX", label: str = "Texas",
             vintage: str = "12/2025", coverage: float = 96.5,
             participated: float = 29_000_000.0, arrests: bool = True) -> FbiArrestResponse:
    """One arrest payload, in the shape ``arrest/{scope}/{code}?type=counts`` sends.

    ``actuals`` carries the requested scope alone (that is what the client keeps),
    the populations and the coverage ride along, and nothing in the labels names
    the offence -- which is why *code* is carried separately.
    """
    periods = _months(len(values))
    series = []
    if arrests:
        series.append(FbiSeries(
            label=f"{label} Arrests", scope=scope, measure="arrests", unit="count",
            observations=[FbiObservation(period=p, value=v)
                          for p, v in zip(periods, values)]))
    series += [
        FbiSeries(label=label, scope=scope, measure="value", unit=PARTICIPATED,
                  observations=[FbiObservation(period=p, value=participated)
                                for p in periods]),
        FbiSeries(label=label, scope=scope, measure="value", unit="people",
                  observations=[FbiObservation(period=p, value=participated * 1.04)
                                for p in periods]),
        FbiSeries(label=label, scope=scope, measure="value", unit="percent",
                  observations=[FbiObservation(period=p, value=coverage)
                                for p in periods]),
    ]
    return FbiArrestResponse(offense=code, scope=scope, series=series,
                             max_data_date=vintage, last_refresh_date="09/15/2026")


def _entry(values=None, **kwargs):
    values = [100.0] * 24 if values is None else values
    code = kwargs.pop("code", "11")
    scope = kwargs.pop("scope", "TX")
    agencies = kwargs.pop("agencies", None)
    entries = catalog.arrest_entries(
        _payload(values, code=code, scope=scope, **kwargs), scope, code, agencies)
    assert len(entries) == 1, "one entry per (code, scope): the route serves one measure"
    return entries[0]


# --- The entry ---------------------------------------------------------------


def test_the_entry_names_the_offence_the_payload_does_not():
    """Every code comes back as "Texas Arrests", so the entry carries the code."""
    entry = _entry(code="50")

    assert entry["series_id"] == "fbi/arrests/50/TX"
    assert entry["concept"] == "arrests"
    assert entry["facets"]["offense"] == "50"
    assert entry["facets"]["offense_name"] == "Assault - Not Specified"
    assert entry["title"] == "Assault - Not Specified arrests, Texas, monthly"
    # and the definition is where a reader learns the name is wrong
    assert "Aggravated assault" in entry["definition"]
    assert entry["facets"]["measure"] == "arrests"
    assert (entry["unit"], entry["frequency"]) == ("count", "Monthly")


def test_the_text_is_written_under_both_names():
    """`description` is what the loader and the catalog table read; `definition`
    is what db_import's description generator reads as context for the family it
    is describing. An entry carrying one and not the other loses its text at
    whichever end reads the other -- which is how every FBI entry would have
    reached Postgres with none, while clio's, written twice, arrive intact.
    """
    entry = _entry(code="50")

    assert entry["description"] == entry["definition"]
    assert "Aggravated assault" in entry["description"]


def test_retrieval_minus_tool_is_what_fbi_arrests_takes():
    """The rule the whole catalogue turns on, checked against the tool's schema."""
    entry = _entry(code="260", scope="national", label="United States")
    arguments = {k: v for k, v in entry["retrieval"].items() if k != "tool"}

    assert entry["retrieval"]["tool"] == "fbi_arrests"
    assert arguments == {"offense": "260", "scope": "national", "unit": "count"}


async def test_every_retrieval_argument_is_published_on_the_tool():
    tool = next(t for t in await server.server.list_tools() if t.name == "fbi_arrests")
    entry = _entry(code="260", scope="national", label="United States")

    published = set(tool.input_schema["properties"])
    assert set(entry["retrieval"]) - {"tool"} <= published
    # and the offence really is one of the published values, not a slug
    assert entry["retrieval"]["offense"] in tool.input_schema["properties"]["offense"]["enum"]


def test_the_span_is_the_filings_and_not_the_requested_window():
    """The NYPD shape: a window asked for from 01-2018, filings from 01-2023.

    Here the last six months of the window are past ``max_data_date``, so the
    mapper leaves them null rather than reading them as zero arrests, and the
    entry's span ends at the last month with a return behind it.
    """
    entry = _entry([100.0] * 18 + [None] * 6, vintage="06/2019")

    assert entry["observation_start"] == "2018-01-01"
    assert entry["observation_end"] == "2019-06-01"     # not 2019-12, the window's end
    assert entry["filings"] == 18


def test_the_blank_months_are_the_notices_own_account():
    entry = _entry([100.0] * 18 + [None] * 6, vintage="06/2019")

    assert len(entry["blank_month_notices"]) == 1
    notice = entry["blank_month_notices"][0]
    assert "past max_data_date (06/2019)" in notice
    assert "07-2019..12-2019" in notice                # the notice names the span
    assert "returned as null" in notice


def test_the_agency_shape_measured_live_at_the_nypd(tmp_path):
    """The live entry this reproduces: 96 months requested, 36 filed, 60 blank.

    ``arrest/agency/NY0303000/11`` from 01-2018 to 12-2025 returns 60 blank
    months then 36 filings -- the department's NIBRS start is 01-2023 -- and the
    entry has to say so rather than claim a span back to 2018.
    """
    entry = _entry([None] * 60 + [25.0] * 36, scope="NY0303000",
                   label="New York City Police Department")

    assert entry["observation_start"] == "2023-01-01"
    assert entry["observation_end"] == "2025-12-01"
    assert entry["filings"] == 36
    assert entry["arrests_total"] == 900
    notice = entry["blank_month_notices"][0]
    assert "60 of the 96 months in this window record no filing" in notice
    assert "01-2018..12-2022" in notice


def test_a_clean_series_quotes_no_blank_month_notice():
    assert _entry()["blank_month_notices"] == []


def test_the_entry_carries_the_coverage_and_the_denominator():
    entry = _entry(coverage=74.12, participated=331_466_503.0)

    assert entry["coverage_mean_percent"] == 74.12
    assert entry["coverage_min_percent"] == 74.12
    assert entry["participated_population"] == 331_466_503.0


def test_the_endpoint_is_the_route_the_request_took():
    assert _entry(scope="national", label="United States")["sources"][0]["endpoint"] == (
        "arrest/national/11")
    assert _entry(scope="TX")["sources"][0]["endpoint"] == "arrest/state/TX/11"
    assert _entry(scope="NY0303000", label="New York City Police Department"
                  )["sources"][0]["endpoint"] == "arrest/agency/NY0303000/11"
    assert _entry()["sources"][0]["vintage"] == "12/2025"


def test_an_agency_scope_carries_the_registry_record():
    registry = {"NY0303000": {"agency_name": "New York City Police Department",
                              "agency_type_name": "City", "state_abbr": "NY",
                              "counties": "NOT SPECIFIED",
                              "nibrs_start_date": "2023-01-01"}}
    entry = _entry(scope="NY0303000", label="New York City Police Department",
                   agencies=registry)

    assert entry["facets"]["agency_type"] == "City"
    assert entry["facets"]["state"] == "NY"
    assert entry["nibrs_start_date"] == "2023-01-01"


# --- The empty code ----------------------------------------------------------


def test_a_code_with_no_arrests_is_catalogued_and_marked_empty():
    """Code 23 nationally: null in every month, because 20 holds the rape arrests.

    Nationally a month with no arrest under one code arrives as null and the
    mapper reads it back as the filed zero it is -- so the months are all
    present and it is the arrests that are absent. ``empty`` says that, and
    ``is_active`` keeps the entry out of anything that would try to plot it.
    """
    entry = _entry([None] * 24, code="23", scope="national", label="United States")

    assert entry["empty"] is True
    assert entry["is_active"] is False
    assert entry["arrests_total"] == 0
    assert entry["filings"] == 24                      # the nation filed; there were none
    assert entry["definition"].startswith(
        "No arrest was filed under this code at United States in 01-2018 to 12-2019.")
    assert entry["series_id"] == "fbi/arrests/23/national"


def test_a_payload_with_no_arrest_series_at_all_still_makes_an_entry():
    entry = _entry([None] * 24, code="172", arrests=False)

    assert (entry["empty"], entry["filings"], entry["arrests_total"]) == (True, 0, 0)
    assert entry["observation_start"] is None and entry["observation_end"] is None
    assert "No arrest was filed" in entry["definition"]


def test_an_empty_code_is_not_dropped_by_the_harvest_loop(tmp_path):
    async def fetch(code, scope):
        return _payload([None] * 24, code=code, scope=scope)

    report = _run(["170"], ["VT"], tmp_path, fetch=fetch)
    entries = harvester.entries_from_checkpoint(tmp_path / "cp.jsonl")

    assert report["entries"] == 1
    assert entries[0]["empty"] is True                 # does Vermont file gambling? no


# --- The note table ----------------------------------------------------------


def test_every_arrest_code_has_a_note():
    assert set(catalog.ARREST_NOTES) == set(ARREST_OFFENSES)
    assert all(note.strip() for note in catalog.ARREST_NOTES.values())
    assert len(catalog.ARREST_NOTES) == 48


def test_every_note_reaches_the_entry_it_describes():
    for code in ARREST_OFFENSES:
        entry = _entry(code=code)
        assert catalog.ARREST_NOTES[code] in entry["definition"]
        assert catalog.ARREST_MEASURE_NOTE in entry["definition"]


@pytest.mark.parametrize("code, expected", [
    ("50", "Aggravated assault, whatever the name says"),
    ("23", "filed under code 20"),
    ("20", "where the rape arrests are"),
    ("140", "not the group's total"),
    ("150", "NOT the drug total"),
    ("170", "not the group's total"),
    ("310", "the largest single code"),
    ("158", "largest drug code"),
])
def test_the_notes_name_the_traps(code, expected):
    """Each of these is a wrong number somebody would otherwise publish."""
    assert expected in catalog.ARREST_NOTES[code]


def test_the_drug_codes_say_how_the_group_splits():
    assert "151-155" in catalog.ARREST_NOTES["150"]
    assert "156-160" in catalog.ARREST_NOTES["150"]
    assert "sale" in catalog.ARREST_NOTES["151"]
    assert "possession" in catalog.ARREST_NOTES["156"].lower()


# --- Export ------------------------------------------------------------------


def _offence_entry(concept: str) -> dict:
    return {"series_id": f"fbi/{concept}/TX/offenses", "concept": concept,
            "facets": {"scope": "TX", "offense": concept, "measure": "offenses"}}


def _employment_entry() -> dict:
    return {"series_id": "fbi/employment/DCMPD0000/officers",
            "concept": "police_employment",
            "facets": {"scope": "DCMPD0000", "measure": "officers"}}


def test_export_writes_one_file_per_code_sorting_beside_the_offences(tmp_path):
    entries = [_offence_entry("aggravated-assault"), _offence_entry("arson"),
               _employment_entry(),
               _entry(code="all"), _entry(code="11"), _entry(code="310")]

    catalog.export(entries, tmp_path)
    names = sorted(p.name for p in tmp_path.glob("fbi_series_*.yaml"))

    assert names == [
        "fbi_series_aggravated_assault.yaml",
        "fbi_series_arrests_011.yaml",
        "fbi_series_arrests_310.yaml",
        "fbi_series_arrests_all.yaml",
        "fbi_series_arson.yaml",
        "fbi_series_employment.yaml",
    ]


def test_the_code_is_padded_so_the_files_sort_numerically():
    assert [catalog.arrest_group(c) for c in ("11", "20", "101", "310", "all")] == [
        "arrests_011", "arrests_020", "arrests_101", "arrests_310", "arrests_all"]
    # unpadded, "11" would sort after "101"
    assert sorted(["arrests_011", "arrests_101"]) == ["arrests_011", "arrests_101"]


def test_no_arrest_file_collides_with_an_offence_file():
    from clients.fbi import OFFENSES

    offence_stems = {o.replace("-", "_") for o in OFFENSES} | {"employment"}
    arrest_stems = {catalog.arrest_group(c).replace("-", "_") for c in ARREST_OFFENSES}
    assert offence_stems.isdisjoint(arrest_stems)
    assert len(arrest_stems) == 48


def test_export_counts_the_three_families_apart(tmp_path):
    entries = [_offence_entry("homicide"), _offence_entry("arson"), _employment_entry(),
               _entry(code="11"), _entry(code="310"),
               _entry([None] * 24, code="23", scope="national", label="United States")]

    report = catalog.export(entries, tmp_path)

    assert report == {"entries": 6, "files": 6, "offense_entries": 2,
                      "arrest_entries": 3, "employment_entries": 1,
                      "offense_files": 2, "arrest_files": 3,
                      "empty_arrest_entries": 1}


def test_the_written_file_is_the_group_shape_the_loader_reads(tmp_path):
    import yaml

    catalog.export([_entry(code="11"), _entry(code="11", scope="national",
                                              label="United States")], tmp_path)
    doc = yaml.safe_load((tmp_path / "fbi_series_arrests_011.yaml").read_text())

    assert doc["group"] == "arrests_011"
    assert doc["series_count"] == 2
    assert [e["series_id"] for e in doc["series"]] == [
        "fbi/arrests/11/TX", "fbi/arrests/11/national"]        # sorted, so diffs are clean


def test_group_of_routes_the_three_families():
    assert catalog.group_of(_offence_entry("homicide")) == "homicide"
    assert catalog.group_of(_employment_entry()) == "employment"
    assert catalog.group_of(_entry(code="11")) == "arrests_011"


# --- The resumable harvester -------------------------------------------------


def _run(codes, scopes, tmp_path, *, fetch, sleeps=None, **kwargs):
    """Drive the loop with no waiting and no printing."""
    import asyncio

    options = {"pause": 0.0, "retry_wait": 0.0} | kwargs
    return asyncio.run(harvester.run(
        codes, scopes,
        checkpoint=tmp_path / "cp.jsonl", failures_path=tmp_path / "failed.json",
        agencies={},
        sleep=(sleeps.append if sleeps is not None else (lambda _s: None)),
        log=lambda *a, **k: None, fetch=fetch, **options))


def _counting_fetch(calls: list):
    async def fetch(code, scope):
        calls.append((code, scope))
        return _payload([100.0] * 24, code=code, scope=scope)
    return fetch


def test_a_second_run_over_a_full_checkpoint_makes_no_requests(tmp_path):
    """Why the harvest can be killed: the reason this module exists."""
    calls: list = []
    first = _run(["11", "20"], ["TX", "NY"], tmp_path, fetch=_counting_fetch(calls))
    assert (first["requests"], first["pending"], len(calls)) == (4, 0, 4)

    async def refuse(code, scope):
        raise AssertionError(f"requested {code} {scope} a second time")

    second = _run(["11", "20"], ["TX", "NY"], tmp_path, fetch=refuse)

    assert second["requests"] == 0
    assert second["skipped"] == 4
    assert second["entries"] == 4
    assert second["pending"] == 0


def test_a_partial_checkpoint_fetches_only_what_is_missing(tmp_path):
    calls: list = []
    _run(["11"], ["TX", "NY"], tmp_path, fetch=_counting_fetch(calls))
    calls.clear()

    report = _run(["11"], ["TX", "NY", "VT", "CA"], tmp_path,
                  fetch=_counting_fetch(calls))

    assert calls == [("11", "VT"), ("11", "CA")]
    assert (report["requests"], report["skipped"], report["entries"]) == (2, 2, 4)


def test_the_pairs_are_taken_code_major_so_a_kill_leaves_whole_codes():
    done = {("11", "TX"): []}
    assert harvester.pending(["11", "20"], ["TX", "NY"], done) == [
        ("11", "NY"), ("20", "TX"), ("20", "NY")]


def test_a_truncated_last_line_costs_one_pair_and_not_the_checkpoint(tmp_path):
    """What a kill in the middle of a write leaves behind."""
    calls: list = []
    _run(["11"], ["TX", "NY"], tmp_path, fetch=_counting_fetch(calls))
    path = tmp_path / "cp.jsonl"
    path.write_text(path.read_text() + '{"code": "11", "scope": "VT", "entr')

    done = harvester.load_checkpoint(path)

    assert sorted(done) == [("11", "NY"), ("11", "TX")]
    assert harvester.pending(["11"], ["TX", "NY", "VT"], done) == [("11", "VT")]


def test_the_checkpoint_holds_the_entries_so_an_export_needs_no_requests(tmp_path):
    _run(["11", "all"], ["TX"], tmp_path, fetch=_counting_fetch([]))

    rows = [json.loads(line) for line in
            (tmp_path / "cp.jsonl").read_text().splitlines()]
    entries = harvester.entries_from_checkpoint(tmp_path / "cp.jsonl")

    assert [(r["code"], r["scope"]) for r in rows] == [("11", "TX"), ("all", "TX")]
    assert all("at" in row for row in rows)            # when it was fetched
    # ordered by padded code, so the export's files come out in code order
    assert [e["series_id"] for e in entries] == ["fbi/arrests/11/TX",
                                                 "fbi/arrests/all/TX"]


def test_a_refusal_is_retried_after_a_minute(tmp_path):
    attempts: list = []
    sleeps: list = []

    async def flaky(code, scope):
        attempts.append((code, scope))
        if len(attempts) == 1:
            raise RuntimeError("503 Client Failure Limit Exceeded")
        return _payload([100.0] * 24, code=code, scope=scope)

    report = _run(["11"], ["TX"], tmp_path, fetch=flaky, sleeps=sleeps,
                  retry_wait=60.0)

    assert len(attempts) == 2
    assert 60.0 in sleeps                              # waited a minute, then retried
    assert (report["failed"], report["entries"], report["pending"]) == (0, 1, 0)


def test_a_pair_that_never_answers_is_left_for_the_next_run(tmp_path):
    async def refuse(code, scope):
        raise RuntimeError("503 Client Failure Limit Exceeded")

    report = _run(["11"], ["TX"], tmp_path, fetch=refuse)

    assert report["failed"] == 1
    assert report["pending"] == 1                      # not checkpointed, so retried
    assert not (tmp_path / "cp.jsonl").exists()
    assert json.loads((tmp_path / "failed.json").read_text())[0][:2] == ["11", "TX"]


def test_a_clean_run_empties_the_failures_file_rather_than_leaving_it(tmp_path):
    (tmp_path / "failed.json").write_text('[["11", "TX", "503"]]')

    _run(["11"], ["TX"], tmp_path, fetch=_counting_fetch([]))

    assert json.loads((tmp_path / "failed.json").read_text()) == []


def test_the_window_ends_at_the_current_month_rather_than_a_fixed_date():
    """A fixed end is how a harvest quietly stops catalogueing its last two years.

    The route answered 09-2026 on 2026-09-27 -- it serves up to the current
    month -- so the window is computed at call time on both harvesters.
    """
    import inspect
    from datetime import date

    today = date.today()
    assert catalog.this_month() == f"{today.month:02d}-{today.year}"
    assert inspect.signature(catalog.harvest_arrests).parameters["end"].default is None
    assert inspect.signature(harvester.run).parameters["end"].default is None
    assert inspect.signature(catalog.harvest_arrests).parameters["start"].default == "01-2018"


def test_the_pace_is_four_seconds_with_margin_under_the_allowance(tmp_path):
    sleeps: list = []
    _run(["11"], ["TX", "NY", "VT"], tmp_path, fetch=_counting_fetch([]),
         sleeps=sleeps, pause=harvester.PAUSE)

    assert harvester.PAUSE == 4.0                      # 900 an hour against 1,000
    assert harvester.PAUSE > catalog.PAUSE             # the offence harvest fits in an hour
    assert sleeps == [4.0, 4.0]                        # between pairs, not after the last


def test_a_limit_stops_the_run_on_a_whole_pair(tmp_path):
    calls: list = []
    report = _run(["11", "20"], ["TX", "NY"], tmp_path,
                  fetch=_counting_fetch(calls), limit=3)

    assert len(calls) == 3
    assert report["pending"] == 1
    assert len(harvester.load_checkpoint(tmp_path / "cp.jsonl")) == 3


# --- The plan and the arguments ----------------------------------------------


def test_plan_prices_the_run_without_a_request(tmp_path):
    plan = harvester.plan(tuple(ARREST_OFFENSES), ("national", *catalog.STATES),
                          pause=4.0, checkpoint=tmp_path / "absent.jsonl")

    assert (plan["codes"], plan["scopes"]) == (48, 52)
    assert plan["pairs"] == plan["requests"] == 2_496
    assert plan["seconds"] == 2_496 * 4
    assert plan["estimate"] == "2h 46m"


def test_plan_counts_the_checkpoint_off_the_bill(tmp_path):
    _run(["11"], ["TX"], tmp_path, fetch=_counting_fetch([]))

    plan = harvester.plan(("11",), ("TX", "NY"), checkpoint=tmp_path / "cp.jsonl")

    assert (plan["pairs"], plan["done"], plan["requests"]) == (2, 1, 1)


def test_the_code_argument_expands():
    assert harvester.parse_codes("all") == tuple(ARREST_OFFENSES)
    assert harvester.parse_codes("all-only") == ("all",)
    assert harvester.parse_codes("11,260,11") == ("11", "260")
    assert len(harvester.parse_codes("curated")) == 28
    assert set(harvester.parse_codes("curated")) <= set(ARREST_OFFENSES)


def test_the_curated_subset_keeps_every_group_summable():
    """A group whose remainder reads as a total is out; the drug block is whole."""
    curated = set(harvester.CURATED)

    assert {str(c) for c in range(150, 161)} <= curated   # 150-160, so drugs sum
    assert "140" not in curated and "170" not in curated  # the misleading remainders
    assert {"20", "23"} <= curated                        # rape needs both codes
    assert {"all", "11", "50", "230", "260", "290", "300", "310"} <= curated


def test_the_scope_argument_expands():
    assert harvester.parse_scopes("national") == ("national",)
    assert len(harvester.parse_scopes("national,states")) == 52
    assert len(harvester.parse_scopes("national,states,cities")) == 57
    assert harvester.parse_scopes("TX,NY0303000") == ("TX", "NY0303000")
    assert harvester.parse_scopes("national,national") == ("national",)


def test_an_unknown_code_is_refused_before_a_request_is_spent():
    with pytest.raises(SystemExit):
        harvester.parse_codes("homicide")              # a summarized slug, not a code


def test_the_full_table_is_the_cost_the_notebook_quotes():
    codes = harvester.parse_codes("all")
    scopes = harvester.parse_scopes("national,states,cities")

    assert len(codes) * len(scopes) == 2_736
    assert harvester._clock(2_736 * harvester.PAUSE) == "3h 02m"
