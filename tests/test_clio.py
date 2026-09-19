"""Tests for the Clio-Infra download and inventory (``notebooks/clio/utils``).

No network: the index and page snippets are hand-built in the site's own
markup, and the workbooks are assembled in memory from the four XML parts an
``.xlsx`` needs.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from notebook_modules import load

fetch = load("clio/utils", "fetch")
xlsx = load("clio/utils", "xlsx")
inventory = load("clio/utils", "inventory")
# the package itself holds the notebooks' plotting helpers; loading any module
# above registers it, so reach it by name rather than executing it a second time
plots = sys.modules["clio_utils"]


# --- the index ----------------------------------------------------------------

def _item(slug, name, file, badge):
    return (f'<p class="list-group-item"><a href="../Indicators/{slug}.html">{name}</a>'
            f'<span class="badge"><a href="../data/{file}"><font color="FFFFFF">'
            f'{badge}</font></a></span></p>')


def _index(*parts):
    return "<html>" + "\n".join(parts) + "</html>"


def _category(name):
    return f'<a href="#" class="list-group-item active">\n  {name}\n</a>'


def test_each_indicator_takes_the_nearest_category_above_it():
    page = _index(_category("Prices and Wages"),
                  _item("LabourersRealWage", "Labourers Real Wage",
                        "LabourersRealWage_Compact.xlsx", " 1820 [5053] 2008"),
                  _category("Demography"),
                  _item("Height", "Height", "Height_Compact.xlsx", " 1550 [1234] 2000"))
    got = fetch.parse_index(page)
    assert [(i["slug"], i["category"]) for i in got] == [
        ("LabourersRealWage", "Prices and Wages"), ("Height", "Demography")]


def test_the_badge_gives_span_and_published_count():
    page = _index(_category("Prices and Wages"),
                  _item("LabourersRealWage", "Labourers Real Wage",
                        "LabourersRealWage_Compact.xlsx", " 1820 [5053] 2008"))
    ind = fetch.parse_index(page)[0]
    assert (ind["published_start"], ind["published_count"], ind["published_end"]) == (1820, 5053, 2008)


def test_the_file_name_is_taken_as_published_not_derived_from_the_page():
    """The page and the file disagree in punctuation; guessing would break."""
    page = _index(_category("Demography"),
                  _item("LifeExpectancyatBirthTotal", "Life Expectancy at Birth (Total)",
                        "LifeExpectancyatBirth(Total)_Compact.xlsx", " 1750 [9] 2000"))
    ind = fetch.parse_index(page)[0]
    assert ind["slug"] == "LifeExpectancyatBirthTotal"
    assert ind["file"] == "LifeExpectancyatBirth(Total)_Compact.xlsx"


def test_an_indicator_listed_twice_is_kept_once():
    item = _item("Height", "Height", "Height_Compact.xlsx", " 1550 [1] 2000")
    page = _index(_category("Demography"), item, _category("Human Capital"), item)
    assert len(fetch.parse_index(page)) == 1


def test_an_index_that_no_longer_parses_is_an_error_not_an_empty_list():
    with pytest.raises(fetch.ClioFetchError, match="zero indicators"):
        fetch.parse_index("<html>redesigned</html>")


def test_indicator_page_panels_become_a_dict():
    page = ('<h3 class="panel-title">Variable(s)</h3>\n</div>\n'
            '<div class="panel-body">\n  Daily wage &amp; basket\n</div>'
            '<h3 class="panel-title">Time period</h3></div><div class="panel-body">1820-2000</div>')
    assert fetch.parse_panels(page) == {"Variable(s)": "Daily wage & basket",
                                        "Time period": "1820-2000"}


# --- the workbook reader ------------------------------------------------------

def _workbook(path: Path, sheets: dict[str, list[list[object]]]) -> Path:
    """A minimal .xlsx: strings go through sharedStrings, numbers stay inline."""
    strings: list[str] = []

    def cell(col: str, row: int, value: object) -> str:
        if isinstance(value, str):
            if value not in strings:
                strings.append(value)
            return f'<c r="{col}{row}" t="s"><v>{strings.index(value)}</v></c>'
        if value is None:
            return ""
        return f'<c r="{col}{row}"><v>{value}</v></c>'

    with zipfile.ZipFile(path, "w") as z:
        entries, rels = [], []
        for n, (name, table) in enumerate(sheets.items(), start=1):
            body = "".join(
                f'<row r="{r}">' + "".join(cell("ABCDEFG"[c], r, v) for c, v in enumerate(vals))
                + "</row>" for r, vals in enumerate(table, start=1))
            z.writestr(f"xl/worksheets/sheet{n}.xml",
                       f"<worksheet><sheetData>{body}</sheetData></worksheet>")
            entries.append(f'<sheet name="{name}" sheetId="{n}" r:id="rId{n}"/>')
            rels.append(f'<Relationship Id="rId{n}" Target="worksheets/sheet{n}.xml"/>')
        z.writestr("xl/workbook.xml", f"<workbook><sheets>{''.join(entries)}</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", f"<Relationships>{''.join(rels)}</Relationships>")
        z.writestr("xl/sharedStrings.xml",
                   "<sst>" + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
    return path


def test_sheets_are_found_by_name_not_position(tmp_path):
    book = _workbook(tmp_path / "b.xlsx", {"Metadata": [["Description", "Value"]],
                                           "Data Long Format": [["ccode", "value"], [56.0, 1.5]]})
    assert xlsx.records(book, "Data Long Format") == [{"ccode": "56.0", "value": "1.5"}]


def test_a_missing_sheet_names_the_ones_that_exist(tmp_path):
    book = _workbook(tmp_path / "b.xlsx", {"Metadata": [["a"]]})
    with pytest.raises(xlsx.XlsxError, match="Metadata"):
        xlsx.rows(book, "Data Long Format")


# --- measuring a workbook -----------------------------------------------------

LONG_HEADER = ["ccode", "country.name", "year", "value"]


def _long(tmp_path, rows):
    return _workbook(tmp_path / "w.xlsx", {"Data Long Format": [LONG_HEADER, *rows]})


def test_a_country_with_no_code_is_kept_by_name(tmp_path):
    """861 real observations were once dropped this way -- Sudan, Canada, Macau."""
    book = _long(tmp_path, [[124.0, "Canada", 1900.0, 1.0],
                            [None, "Macau, China", 1900.0, 2.0],
                            [None, "Macau, China", 1901.0, 3.0]])
    m = inventory.measure(book)
    assert m["countries"] == 2
    assert m["observations"] == 3
    assert m["rows_without_code"] == 2
    assert m["unparsed_rows"] == 0


def test_a_repeated_country_year_counts_once(tmp_path):
    book = _long(tmp_path, [[56.0, "Belgium", 1820.0, 1.0], [56.0, "Belgium", 1820.0, 1.0]])
    m = inventory.measure(book)
    assert (m["observations"], m["duplicate_rows"]) == (1, 1)


def test_a_zero_filled_panel_is_distinguishable_from_a_measured_one(tmp_path):
    book = _long(tmp_path, [[c, f"c{c}", 1500.0, 1.0 if c == 1 else 0.0] for c in range(1, 11)])
    m = inventory.measure(book)
    assert m["zero_share"] == 0.9
    assert m["distinct_values"] == 2


def test_spacing_reports_the_usual_step_and_the_largest(tmp_path):
    years = [1900, 1901, 1902, 1903, 1910]
    book = _long(tmp_path, [[56.0, "Belgium", float(y), 1.0] for y in years])
    m = inventory.measure(book)
    assert m["modal_step"] == 1
    assert m["share_at_modal_step"] == 0.75
    assert m["largest_step"] == 7


def test_the_united_states_is_reported_on_its_own(tmp_path):
    book = _long(tmp_path, [[840.0, "United States", 1925.0, 1.0],
                            [840.0, "United States", 2007.0, 2.0],
                            [826.0, "United Kingdom", 1820.0, 3.0]])
    assert inventory.measure(book)["us"] == {"observations": 2, "start": 1925, "end": 2007}


# --- building series ----------------------------------------------------------

clio_series = load("clio/utils", "clio_series")
catalog = load("clio/utils", "catalog")
units_mod = load("clio/utils", "units")

INV_ENTRY = {"name": "Labourers  Real Wage", "category": "Prices and Wages",
             "file": "w.xlsx", "modal_step": 1, "zero_share": 0.0, "distinct_values": 500,
             "handle": "10622/QK8VRF", "definition": "Daily wage over a subsistence basket"}


def _build(tmp_path, rows, codes=None, unit=None):
    raw = tmp_path / "raw"; raw.mkdir()
    _workbook(raw / "w.xlsx", {"Data Long Format": [LONG_HEADER, *rows]})
    return clio_series.series_for("LabourersRealWage", INV_ENTRY, tmp_path, codes or {}, unit)


def test_ids_come_from_display_names_not_page_slugs():
    assert clio_series.snake("GDP per Capita") == "gdp_per_capita"
    assert clio_series.snake("Macau, China") == "macau_china"
    assert clio_series.indicator_id({"name": "Labourers  Real Wage"}) == "labourers_real_wage"


def test_frequency_follows_the_usual_step():
    assert [clio_series.frequency(s) for s in (1, 10, 50)] == ["Annual", "Decadal", "Every 50 years"]


def test_one_series_per_country_with_values_kept_as_written(tmp_path):
    series, _ = _build(tmp_path, [[826.0, "United Kingdom", 1820.0, "16.62734117"],
                                  [826.0, "United Kingdom", 1821.0, "9.307143E-5"]])
    (s,) = series
    assert s["native_id"] == "clio/labourers_real_wage/united_kingdom"
    assert s["title"] == "Labourers Real Wage — United Kingdom"
    assert [o["value"] for o in s["observations"]] == ["16.62734117", "9.307143E-5"]
    assert s["metadata"]["clio"]["ccode"] == [826]


def test_a_blank_code_takes_the_code_its_name_carries_elsewhere(tmp_path):
    series, collisions = _build(tmp_path, [[None, "Sudan", 1950.0, "3.0"]], codes={"Sudan": 729})
    assert series[0]["metadata"]["clio"]["ccode"] == [729]
    assert collisions == []


def test_on_a_clash_the_coded_row_wins_and_the_clash_is_reported(tmp_path):
    """Canada's uncoded 1946 real wage is the United States' number."""
    series, collisions = _build(tmp_path, [[124.0, "Canada", 1946.0, "40.99"],
                                           [None, "Canada", 1946.0, "66.73"]],
                                codes={"Canada": 124})
    assert [o["value"] for o in series[0]["observations"]] == ["40.99"]
    assert collisions == [("LabourersRealWage", "Canada", 1946, "66.73", "40.99")]


def test_a_territory_never_coded_anywhere_is_kept_by_name(tmp_path):
    series, _ = _build(tmp_path, [[None, "Macau, China", 1900.0, "2.0"]])
    assert series[0]["native_id"] == "clio/labourers_real_wage/macau_china"
    assert series[0]["metadata"]["clio"]["ccode"] == [None]


def test_the_catalog_entry_carries_facets_for_filtering_out_what_was_not_measured(tmp_path):
    series, _ = _build(tmp_path, [[826.0, "United Kingdom", 1820.0, "16.6"]], unit="baskets")
    entry = catalog.catalog_entry(series[0])
    assert entry["facets"] == {"indicator": "labourers_real_wage", "country": "united_kingdom",
                               "category": "prices_and_wages", "kind": "measured", "ccode": 826}
    assert entry["retrieval"] == {"tool": "timeseries_source_data", "source": "clio",
                                  "native_id": "clio/labourers_real_wage/united_kingdom"}
    assert (entry["unit"], entry["description"]) == ("baskets", "Daily wage over a subsistence basket")


def test_kind_separates_measured_from_panels_and_reconstructions():
    k = inventory.kind
    assert k("X", {"category": "Agriculture"}) == "reconstruction"
    assert k("Conflicts", {"category": "Institutions", "zero_share": 0.97, "distinct_values": 2}) == "panel"
    assert k("Wage", {"category": "Prices and Wages", "zero_share": 0.0, "distinct_values": 4900}) == "measured"


def test_row_2_is_preferred_and_the_paper_is_the_fallback(tmp_path):
    """Where both exist they agree on 2 of 30; row 2 is usually the better label."""
    docs = tmp_path / "documentation.yaml"
    docs.write_text(yaml.safe_dump({
        "polity2_index": {"workbook_unit": "autocracy-democracy on a -10 to 10 scale",
                          "unit": "index", "unit_source": "unit_of_analysis", "doi": "10.34894/P"},
        "social_spending": {"workbook_unit": None, "unit": "percentage of GDP",
                            "unit_source": "unit_of_measurement", "doi": "10.34894/S"},
        "height": {"workbook_unit": None, "unit": None, "doi": "10.34894/H"},
    }))
    out = tmp_path / "units.yaml"
    assert units_mod.harvest(docs, out) == {"indicators": 3, "with_unit": 2, "from_workbook": 1}
    got = units_mod.load(out)
    assert (got["polity2_index"]["unit"], got["polity2_index"]["source"]) == (
        "autocracy-democracy on a -10 to 10 scale", "workbook row 2")
    assert got["polity2_index"]["paper_unit"] == "index"               # the other is kept, not lost
    assert got["social_spending"]["source"] == "working paper, unit_of_measurement"
    assert got["height"]["unit"] is None                               # nothing is inferred


def test_without_the_documentation_there_are_no_units_rather_than_an_error(tmp_path):
    assert units_mod.harvest(tmp_path / "absent.yaml", tmp_path / "u.yaml")["with_unit"] == 0


# --- the notebooks' plotting helpers -------------------------------------------

@pytest.mark.parametrize("frequency,expected", [
    ("Annual", 1), ("Decadal", 10), ("Every 5 years", 5), ("", 1), (None, 1),
])
def test_the_step_comes_from_the_frequency_label(frequency, expected):
    assert plots.step({"frequency": frequency}) == expected


def _arrays(*years):
    import numpy
    return numpy.array(years), numpy.array([float(y) for y in years])


def test_a_missing_year_breaks_the_line_rather_than_bridging_it():
    import numpy
    grid, values = plots.break_gaps(*_arrays(1900, 1901, 1903))
    assert grid.tolist() == [1900, 1901, 1902, 1903]
    assert numpy.isnan(values[2]) and values[3] == 1903


def test_an_observation_off_the_step_grid_is_kept():
    """Algeria's income inequality is 1910, 1929, 1990 under a Decadal label --
    on a bare decadal grid 1929 was dropped, and a three-point series drawn as
    two."""
    import numpy
    grid, values = plots.break_gaps(*_arrays(1910, 1929, 1990), every=10)
    assert 1929 in grid.tolist()
    assert not numpy.isnan(values[grid.tolist().index(1929)])


def test_annual_observations_under_a_decadal_label_all_survive():
    """The livestock indicators are decadal to 2000 and annual after it, so
    Estonia's eleven goat observations plotted as two."""
    import numpy
    years = list(range(2000, 2011))
    grid, values = plots.break_gaps(*_arrays(*years), every=10)
    assert grid.tolist() == years
    assert not numpy.isnan(values).any()


def test_a_row_excel_left_out_comes_back_empty(tmp_path):
    """Eleven deposits jump from row 1 to row 3. Appending in document order
    closed the gap and shifted every row up a place."""
    path = tmp_path / "gap.xlsx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml",
                   '<worksheet><sheetData>'
                   '<row r="1"><c r="A1" t="inlineStr"><is><t>Title</t></is></c></row>'
                   '<row r="3"><c r="A3" t="inlineStr"><is><t>Header</t></is></c></row>'
                   '</sheetData></worksheet>')
        z.writestr("xl/workbook.xml",
                   '<workbook><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')

    table = xlsx.rows(path, "Data")

    assert [r.get("A") for r in table] == ["Title", None, "Header"]
