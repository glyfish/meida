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

from notebook_modules import load

workbook = load("clio_historical/utils", "workbook")
documentation = load("clio_historical/utils", "documentation")
accept = load("clio_historical/utils", "accept")

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


def test_a_sheet_without_the_three_row_layout_is_refused(tmp_path):
    path = _book(tmp_path / "flat-historical.xlsx", [["ccode", "value"], [56, 1.0]])
    with pytest.raises(workbook.WorkbookError, match="rows 1-3"):
        workbook.read(path)


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
    with pytest.raises(accept.AcceptError, match="historical.xlsx"):
        accept.accept(tmp_path / "empty", doi="10.34894/X", version="1.1", data_dir=tmp_path / "data")


def test_a_malformed_doi_is_refused(tmp_path):
    with pytest.raises(accept.AcceptError, match="not a DOI"):
        accept.doi_dir("UFVNXT")
