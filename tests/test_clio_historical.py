"""Tests for Clio-Infra at historical borders (``notebooks/clio_historical/utils``).

Workbooks and working papers are assembled in memory in the layouts verified on
the real DataverseNL deposit; no network, and nothing touches ``~/Downloads``.
"""
from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from notebook_modules import load

workbook = load("clio_historical/utils", "workbook")
documentation = load("clio_historical/utils", "documentation")
accept = load("clio_historical/utils", "accept")
inventory = load("clio_historical/utils", "inventory")

HEADER = ["Webmapper code", "Webmapper numeric code", "ccode", "country name",
          "start year", "end year", "1820", "1821", "1822"]


def _col(i: int) -> str:
    return "ABCDEFGHIJKLMNOP"[i]


def _book(path: Path, rows: list[list[object]], sheet: str = "Data") -> Path:
    strings: list[str] = []

    def cell(ref: str, value: object) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, str):
            strings.append(value)
            return f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>'
        return f'<c r="{ref}"><v>{value}</v></c>'

    body = "".join(f'<row r="{r}">' + "".join(cell(f"{_col(c)}{r}", v) for c, v in enumerate(vals))
                   + "</row>" for r, vals in enumerate(rows, start=1))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet><sheetData>{body}</sheetData></worksheet>")
        z.writestr("xl/workbook.xml",
                   f'<workbook><sheets><sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml",
                   "<sst>" + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
    return path


def _historical(tmp_path: Path, *polities: list[object]) -> Path:
    return _book(tmp_path / "x-historical.xlsx",
                 [["Labourers Real Wage"],
                  ["Number of daily subsistence baskets that a daily wage buys"],
                  HEADER, *polities])


# --- the workbook -------------------------------------------------------------

def test_title_and_unit_come_from_the_first_two_rows(tmp_path):
    book = workbook.read(_historical(tmp_path))
    assert book["title"] == "Labourers Real Wage"
    assert book["unit"] == "Number of daily subsistence baskets that a daily wage buys"


def test_each_row_is_a_polity_with_its_border_period_and_values(tmp_path):
    book = workbook.read(_historical(
        tmp_path, ["geacron/388", 388, None, "German Confederation", 1820, 1839, 8.5, 9.0, None]))
    (p,) = book["polities"]
    assert (p["code"], p["scheme"], p["name"]) == ("geacron/388", "geacron", "German Confederation")
    assert (p["border_start"], p["border_end"], p["ccode"]) == (1820, 1839, None)
    assert p["values"] == {1820: 8.5, 1821: 9.0}          # a blank year is absent, not zero


def test_a_cshapes_row_can_hold_years_before_its_borders_existed(tmp_path):
    """The modern-state row carries the whole series -- the main site's, value for value."""
    book = workbook.read(_historical(
        tmp_path, ["cshapes/1434", 1434, 826, "United Kingdom", 1946, 2012, 15.0, 16.0, 17.0]))
    recs = workbook.long_records(book)
    assert [r["in_border_period"] for r in recs] == [False, False, False]
    assert recs[0]["ccode"] == 826


def test_a_geacron_value_inside_its_period_is_flagged_as_such(tmp_path):
    book = workbook.read(_historical(
        tmp_path, ["geacron/1", 1, None, "Somewhere", 1821, 1822, 1.0, 2.0, 3.0]))
    assert [(r["year"], r["in_border_period"]) for r in workbook.long_records(book)] == [
        (1820, False), (1821, True), (1822, True)]


def test_a_sheet_without_the_webmapper_header_is_refused(tmp_path):
    path = _book(tmp_path / "flat-historical.xlsx", [["ccode", "value"], [56, 1.0]])
    with pytest.raises(workbook.WorkbookError, match="Webmapper code"):
        workbook.read(path)


@pytest.mark.parametrize("above,layout,title,unit", [
    ([["Real Wage"], ["baskets"]], "title, unit, header", "Real Wage", "baskets"),
    ([["Working week"]], "title, header", "Working week", ""),
    ([], "header", "", ""),
])
def test_all_three_deposit_layouts_are_read(tmp_path, above, layout, title, unit):
    """The header is found by what it says; what sits above it is title and unit."""
    path = _book(tmp_path / "x-historical.xlsx",
                 [*above, HEADER, ["geacron/1", 1, None, "Aceh", 1820, 1822, 1.5]])
    book = workbook.read(path)
    assert (book["layout"], book["title"], book["unit"]) == (layout, title, unit)
    assert book["polities"][0]["values"] == {1820: 1.5}


# --- years, layouts and the papers' oddities ----------------------------------

def test_a_date_formatted_end_year_is_read_as_its_year(tmp_path):
    """Four rows in every workbook carry `end year` as an Excel date serial:
    7305 is 1919-12-31, and it became a border period ending in the year 7305."""
    book = workbook.read(_historical(
        tmp_path, ["geacron/82", 82, None, "Australia", 1840, 7305, 1.0]))
    (p,) = book["polities"]
    assert (p["border_start"], p["border_end"]) == (1840, 1919)


def test_an_impossible_year_is_refused(tmp_path):
    with pytest.raises(workbook.WorkbookError, match="implausible year"):
        workbook.read(_historical(
            tmp_path, ["geacron/1", 1, None, "Nowhere", 1820, 10_000_000, 1.0]))


def test_an_absent_row_does_not_shift_the_unit_into_the_title(tmp_path):
    """Ten deposits leave row 2 empty, and Excel omits the row entirely."""
    path = tmp_path / "gap-historical.xlsx"
    with zipfile.ZipFile(path, "w") as z:
        head = ("".join(f'<c r="{_col(i)}3" t="s"><v>{i}</v></c>' for i in range(len(HEADER))))
        z.writestr("xl/worksheets/sheet1.xml",
                   '<worksheet><sheetData>'
                   f'<row r="1"><c r="A1" t="s"><v>{len(HEADER)}</v></c></row>'
                   f'<row r="3">{head}</row>'
                   '</sheetData></worksheet>')
        z.writestr("xl/workbook.xml",
                   '<workbook><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", "<sst>"
                   + "".join(f"<si><t>{h}</t></si>" for h in HEADER)
                   + "<si><t>Real Wage</t></si></sst>")

    book = workbook.read(path)

    assert (book["title"], book["unit"]) == ("Real Wage", "")


def test_a_heading_that_carries_its_own_text_still_opens_its_section(tmp_path):
    """Two ILO papers write "13. Data quality: Central statistical agencies…",
    and the whole section was swallowed into the one above it."""
    fields = documentation.metadata(_paper(
        tmp_path,
        "12. Methodologies used for data collection and processing", "From the ILO.",
        "13. Data quality: Central statistical agencies which afford the ILO with their data"))

    assert fields["data_quality"] == "Central statistical agencies which afford the ILO with their data"
    assert "Data quality" not in (fields["methodology"] or "")


def test_a_form_field_delimiter_is_not_part_of_the_value(tmp_path):
    """Word writes [[[[value]]]] into the file; seven units read with them."""
    fields = documentation.metadata(_paper(
        tmp_path, "7b. Unit of measurement", "[[[[Percentage]]]]"))

    assert fields["unit_of_measurement"] == "Percentage"


# --- the inventory ------------------------------------------------------------

@pytest.mark.parametrize("section,stated", [
    (None, False),
    ("Central statistical agencies\nHistorical reconstructions\nEstimates\nConjectures", False),
    ("i. Central statistical agencies.\nii. Historical reconstructions\niii. Estimates\niv. Conjectures", False),
    ("Central statistical agencies\nEstimates\nBased on national censuses after 1870.", True),
    ("Good", True),
    # the template's own lead-in to the menu is not an assessment either
    ("Indication of the quality of the data based on the following categories:\n"
     "i. Central statistical agencies\nii. Estimates", False),
])
def test_the_template_menu_alone_does_not_state_a_quality(section, stated):
    """Half the papers keep the four grades as printed and never pick one."""
    assert inventory.quality_stated(section) is stated


def test_a_geacron_row_counts_only_values_inside_its_border_period(tmp_path):
    """Hong Kong's post-1946 values sit on a period ending in 1945 -- listed, not its own."""
    m = inventory.measure(_historical(
        tmp_path,
        ["geacron/1", 1, None, "Inside", 1820, 1822, 1.0, 2.0, 3.0],
        ["geacron/2", 2, None, "Outside", 1700, 1819, 4.0, 5.0, None],
        ["geacron/3", 3, None, "Empty", 1820, 1822],
        ["cshapes/9", 9, 2, "Modern", 1946, 2012, 6.0, None, 7.0]))
    g, c = m["geacron"], m["cshapes"]
    assert (g["rows"], g["rows_with_values"], g["observations"]) == (3, 2, 3)
    assert (g["start"], g["end"], g["rows_by_decade"]) == (1820, 1822, {"1820": 1})
    # a modern-state row keeps its whole series, before its borders or not
    assert (c["rows"], c["observations"], c["rows_by_decade"]) == (1, 2, {"1820": 1})
    assert m["layout"] == "title, unit, header"


# --- the working paper --------------------------------------------------------

def _docx(path: Path, paragraphs: list[str]) -> Path:
    def para(text: str) -> str:
        # a <w:tab/> in every paragraph: the run pattern once swallowed it
        return f'<w:p><w:r><w:tab/><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   "<w:document><w:body>" + "".join(para(p) for p in paragraphs) + "</w:body></w:document>")
    return path


def test_numbered_headings_split_the_paper_into_sections(tmp_path):
    paper = _docx(tmp_path / "p.docx", ["Working Paper", "7. Unit of analysis",
                                        "- number of subsistence baskets.",
                                        "13. Data quality", "i. Estimates", "ii. Conjectures"])
    s = documentation.sections(paper)
    assert s["7. Unit of analysis"] == "number of subsistence baskets."
    assert s["13. Data quality"] == "i. Estimates\nii. Conjectures"


def test_a_tab_does_not_leak_markup_into_the_text(tmp_path):
    paper = _docx(tmp_path / "p.docx", ["1. Title", "- Real wages"])
    assert "<" not in documentation.sections(paper)["1. Title"]


# --- accepting a download -----------------------------------------------------

def _download(tmp_path: Path) -> Path:
    folder = tmp_path / "Downloads" / "doi-10"
    folder.mkdir(parents=True)
    _historical(folder)
    (folder / "x.docx").write_bytes(b"doc")
    (folder / "MANIFEST.TXT").write_text("files\n")
    return folder


def test_accepting_copies_the_folder_and_records_doi_version_and_date(tmp_path):
    folder = _download(tmp_path)
    entry = accept.accept(folder, doi="10.34894/UFVNXT", version="1.1",
                          released="2026-01-08", downloaded="2026-09-19", data_dir=tmp_path / "data")
    target = tmp_path / "data" / "raw" / "10.34894_UFVNXT"
    assert sorted(f.name for f in target.iterdir()) == ["MANIFEST.TXT", "x-historical.xlsx", "x.docx"]
    assert (entry["version"], entry["downloaded"], entry["workbook"]) == ("1.1", "2026-09-19", "x-historical.xlsx")
    manifest = json.loads((tmp_path / "data" / "manifest.json").read_text())
    assert manifest["10.34894/UFVNXT"]["released"] == "2026-01-08"


def test_a_workbook_not_named_historical_is_still_a_deposit(tmp_path):
    """Ten of the 76 name theirs Global_Hunger.xlsx and the like, and the
    *-historical.xlsx glob refused every one as "not a DataverseNL download"."""
    folder = tmp_path / "Downloads" / "doi-10"
    folder.mkdir(parents=True)
    _book(folder / "Global_Hunger.xlsx",
          [["Labourers Real Wage"], ["baskets"], HEADER,
           ["geacron/1", 1, None, "Aceh", 1820, 1822, 1.5]])
    _datasets_json(tmp_path / "data", **{"Labourers Real Wage": "10.34894/UFVNXT"})

    entry = accept.accept(folder, version="1.1", data_dir=tmp_path / "data")

    assert entry["doi"] == "10.34894/UFVNXT"
    assert entry["workbook"] == "Global_Hunger.xlsx"


def test_the_workbook_that_names_a_dataset_wins_over_a_re_download(tmp_path):
    """Three folders hold two workbooks, and they are not copies."""
    folder = tmp_path / "Downloads" / "doi-68"
    folder.mkdir(parents=True)
    _book(folder / "GDP-historical.xlsx",
          [["Labourers Real Wage"], ["baskets"], HEADER,
           ["geacron/1", 1, None, "Aceh", 1820, 1822, 1.5]])
    _book(folder / "GDP-historical-1.xlsx",
          [["Something Else Entirely"], ["other"], HEADER,
           ["geacron/1", 1, None, "Aceh", 1820, 1822, 9.9]])
    _datasets_json(tmp_path / "data", **{"Labourers Real Wage": "10.34894/UFVNXT"})

    entry = accept.accept(folder, version="1.1", data_dir=tmp_path / "data")

    assert entry["workbook"] == "GDP-historical.xlsx"


def test_the_download_folder_is_left_where_it_was(tmp_path):
    folder = _download(tmp_path)
    accept.accept(folder, doi="10.34894/UFVNXT", version="1.1", data_dir=tmp_path / "data")
    assert (folder / "x-historical.xlsx").exists()


def test_the_download_date_defaults_to_when_the_browser_wrote_the_folder(tmp_path):
    """Filing a week late must not date the copy a week late."""
    folder = _download(tmp_path)
    stamp = datetime(2026, 9, 19, 12, 0).timestamp()       # local noon: no timezone edge
    os.utime(folder, (stamp, stamp))
    entry = accept.accept(folder, doi="10.34894/UFVNXT", version="1.1", data_dir=tmp_path / "data")
    assert entry["downloaded"] == "2026-09-19"


def test_a_folder_that_is_not_a_dataverse_download_is_refused(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(accept.AcceptError, match=r"no \.xlsx"):
        accept.accept(tmp_path / "empty", doi="10.34894/X", version="1.1", data_dir=tmp_path / "data")


def test_a_malformed_doi_is_refused(tmp_path):
    with pytest.raises(accept.AcceptError, match="not a DOI"):
        accept.doi_dir("UFVNXT")


# --- which dataset holds which indicator --------------------------------------

datasets = load("clio_historical/utils", "datasets")


def _datasets_json(data_dir: Path, **by_name: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "datasets.json").write_text(json.dumps(
        {name.replace(" ", ""): {"name": name, "doi": doi} for name, doi in by_name.items()}))


def test_a_workbook_title_identifies_its_dataset_despite_spacing_and_case(tmp_path):
    _datasets_json(tmp_path, **{"Labourers  Real Wage": "10.34894/UFVNXT"})
    assert accept.identify("labourers real wage", tmp_path) == "10.34894/UFVNXT"


def test_an_unknown_title_is_refused_rather_than_matched_to_the_nearest(tmp_path):
    _datasets_json(tmp_path, **{"Labourers Real Wage": "10.34894/UFVNXT"})
    with pytest.raises(accept.AcceptError, match="matches 0"):
        accept.identify("Labourers Nominal Wage", tmp_path)


def test_accepting_finds_the_doi_from_the_title(tmp_path):
    folder = _download(tmp_path)
    _datasets_json(tmp_path / "data", **{"Labourers Real Wage": "10.34894/UFVNXT"})
    entry = accept.accept(folder, version="1.1", data_dir=tmp_path / "data")
    assert (entry["doi"], entry["title"]) == ("10.34894/UFVNXT", "Labourers Real Wage")


def test_a_doi_that_contradicts_the_workbook_is_refused(tmp_path):
    """The wrong folder must not be filed under the dataset someone typed."""
    folder = _download(tmp_path)
    _datasets_json(tmp_path / "data", **{"Labourers Real Wage": "10.34894/UFVNXT"})
    with pytest.raises(accept.AcceptError, match="not 10.34894/H4HNSX"):
        accept.accept(folder, version="1.1", doi="10.34894/H4HNSX", data_dir=tmp_path / "data")
    assert not (tmp_path / "data" / "raw").exists()


def test_the_doi_comes_from_the_handle_redirect_alone(monkeypatch):
    class Redirect:
        def open(self, request, timeout):
            assert request.get_method() == "HEAD"
            raise datasets.urllib.error.HTTPError(
                request.full_url, 302, "Found", {"Location": "https://doi.org/10.34894/UFVNXT"}, None)
    monkeypatch.setattr(datasets.urllib.request, "build_opener", lambda *a: Redirect())
    assert datasets.resolve("10622/QK8VRF") == "10.34894/UFVNXT"


def test_building_the_list_keeps_dois_already_resolved(tmp_path, monkeypatch):
    clio = tmp_path / "clio"; clio.mkdir()
    (clio / "inventory.json").write_text(json.dumps({
        "Wage": {"name": "Wage", "category": "Prices", "handle": "10622/A", "start": 1820, "end": 2000,
                 "countries_by_decade": {"1820": 5, "1950": 9}},
        "Votes": {"name": "Votes", "category": "Institutions", "handle": "10622/B", "start": 1950,
                  "end": 2000, "countries_by_decade": {"1950": 9}}}))
    calls = []
    monkeypatch.setattr(datasets, "resolve", lambda h: calls.append(h) or f"10.34894/{h[-1]}")
    monkeypatch.setattr(datasets, "PAUSE", 0)
    out = datasets.build(tmp_path / "data", clio)
    assert out["Wage"]["page"].endswith("persistentId=doi:10.34894/A")
    assert (out["Wage"]["decades_before_1946"], out["Votes"]["decades_before_1946"]) == (1, 0)
    datasets.build(tmp_path / "data", clio)
    assert sorted(calls) == ["10622/A", "10622/B"]         # each once: the second build resolved nothing


# --- the working paper as named fields ----------------------------------------

def _paper(tmp_path: Path, *lines: str, name: str = "p.docx") -> Path:
    return _docx(tmp_path / name, list(lines))


def test_a_numbered_chapter_inside_the_text_is_not_a_new_section(tmp_path):
    """Income Inequality's paper numbers its own chapters after "17. Text"."""
    m = documentation.metadata(_paper(tmp_path, "16. Sources", "Allen 2001",
                                      "17. Text", "INTRODUCTION",
                                      "2. INCOME INEQUALITY IN THE POST-1945 PERIOD", "Ginis rose."))
    assert m["sources"] == "Allen 2001"
    assert "POST-1945" in m["text"] and "Ginis rose." in m["text"]


def test_the_authors_version_is_normalised_and_kept_apart_from_dataverse(tmp_path):
    cases = {"1st version.": "1", "Version 1.0": "1", "2nd version.": "2", "2": "2", "na": None}
    for i, (written, number) in enumerate(cases.items()):
        m = documentation.metadata(_paper(tmp_path, "4. Version", written, name=f"v{i}.docx"))
        assert (m["paper_version"], m["version_number"]) == (written, number)


def test_a_split_section_seven_takes_the_unit_from_7b(tmp_path):
    m = documentation.metadata(_paper(tmp_path, "7a. Unit of analysis", "Country",
                                      "7b. Unit of measurement", "Index, 0-1."))
    assert (m["unit"], m["unit_source"]) == ("Index, 0-1", "unit_of_measurement")


def test_country_as_the_unit_of_analysis_is_not_a_unit(tmp_path):
    """19 papers write "Country" there -- what is observed, not how it is measured."""
    m = documentation.metadata(_paper(tmp_path, "7. Unit of analysis", "Country"))
    assert (m["unit_of_analysis"], m["unit"]) == ("Country", None)


def test_a_real_unit_of_analysis_is_used(tmp_path):
    m = documentation.metadata(_paper(tmp_path, "7. Unit of analysis",
                                      "Number of deaths per 100.000 inhabitants"))
    assert (m["unit"], m["unit_source"]) == ("Number of deaths per 100.000 inhabitants", "unit_of_analysis")


def test_keywords_become_a_list_and_a_wikipedia_abstract_is_marked(tmp_path):
    m = documentation.metadata(_paper(tmp_path, "8. Keywords (5)", "Institutions, homicide rate; world",
                                      "9. Abstract (200 words) Taken from Wikipedia:", "An abstract."))
    assert m["keywords"] == ["Institutions", "homicide rate", "world"]
    assert (m["abstract"], m["abstract_source"]) == ("An abstract.", "wikipedia")


def _deposit(raw: Path, folder: str, title: str, papers: dict[str, list[str]]) -> None:
    d = raw / folder; d.mkdir(parents=True)
    _book(d / "x-historical.xlsx", [[title], ["a unit"], HEADER])
    for name, lines in papers.items():
        _docx(d / name, lines)


def test_building_ties_each_paper_to_its_indicator_through_the_workbook(tmp_path):
    data = tmp_path / "data"; raw = data / "raw"
    (raw).mkdir(parents=True)
    (data / "datasets.json").write_text(json.dumps({
        "HomicideRates": {"name": "Homicide Rates", "doi": "10.34894/F2XDR7"},
        "SocialSpending": {"name": "Social Spending", "doi": "10.34894/SS"},
        "GDPperCapita": {"name": "GDP per Capita", "doi": "10.34894/GDP"},
        "WealthTop10percentshare": {"name": "Wealth Top10 percent share", "doi": "10.34894/W"}}))
    _deposit(raw, "doi-10-60", "Homicide Rates", {"h.docx": ["1. Title", "Homicide", "4. Version", "2"]})
    _deposit(raw, "doi-10-69", "Social Transfers", {"s.docx": ["1. Title", "Social Spending and the Welfare State"]})
    _deposit(raw, "doi-10-68", "GDP per Capita", {
        "old.docx": ["1. Title", "First Update", "3. Production date", "January 2013.", "4. Version", "na"],
        "new.docx": ["1. Title", "The long view", "3. Production date", "January 2020.", "4. Version", "2"]})
    d = raw / "doi-10-99"; d.mkdir()
    _book(d / "y-historical.xlsx", [["Wealth Top 10 percent share"], ["share of wealth"], HEADER])

    report = documentation.build(data)
    written = yaml.safe_load((data / "documentation.yaml").read_text())
    assert written["homicide_rates"]["doi"] == "10.34894/F2XDR7"
    assert written["homicide_rates"]["workbook_unit"] == "a unit"
    assert written["social_spending"]["title"] == "Social Spending and the Welfare State"   # via the alias
    assert written["gdp_per_capita"]["title"] == "The long view"                           # latest edition
    assert written["gdp_per_capita"]["superseded"][0]["title"] == "First Update"
    # a single-file download still gets an entry: identity and unit, no paper
    assert written["wealth_top10_percent_share"]["paper"] is None
    assert written["wealth_top10_percent_share"]["workbook_unit"] == "share of wealth"
    assert report["workbook_only"] == ["doi-10-99"] and report["unmatched"] == []


def test_a_row_2_that_only_repeats_the_name_is_not_a_unit():
    """"CO2 Emissions per Capita" in row 2 of that workbook is a restated title."""
    read = [{"unit": "CO2  Emissions per capita"}]
    assert documentation._workbook_unit(read, "CO2 Emissions per Capita") is None
    assert documentation._workbook_unit([{"unit": "tonnes per person"}], "CO2 Emissions per Capita") == "tonnes per person"


# --- historical-borders series ------------------------------------------------

historical = load("clio_historical/utils", "historical_series")


def test_the_main_sites_seven_figure_rounding_is_not_a_difference():
    """14.44252 on the main site, 14.4425187753 on DataverseNL: the same number."""
    assert historical.same_number(14.44252, 14.4425187753)
    assert not historical.same_number(12.026, 14.754)          # the Netherlands kingdom row


MAIN = {"Netherlands": {1820: 13.8, 1821: 14.2},
        "Turkey": {1800: 12.0, 1801: 12.5},
        "United States": {1925: 68.48}}


@pytest.mark.parametrize("values,name,expected", [
    ({1820: 13.8, 1821: 14.2}, "Netherlands", ("Netherlands", "same")),
    ({1820: 13.8}, "Netherlands", ("Netherlands", "same")),
    ({1820: 13.8, 1822: 15.0}, "Netherlands", ("Netherlands", "extends")),
    ({1800: 12.0, 1801: 12.5}, "Ottoman", ("Turkey", "successor")),
    ({1820: 14.754}, "Netherlands", ("Netherlands", "differs")),
    ({1864: 3.0}, "Hong Kong", (None, "new")),
])
def test_every_series_is_related_to_the_main_site(values, name, expected):
    assert historical.relate(values, name, MAIN) == expected


def test_a_known_mislabelled_row_is_excluded_with_its_reason():
    reason = historical.EXCLUDED[("labourers_real_wage", "geacron/236")]
    assert "United States" in reason
    assert {code for (_, code) in historical.EXCLUDED} == {f"geacron/{n}" for n in (236, 237, 238, 239)}
