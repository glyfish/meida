"""Read a DataverseNL Clio workbook: one ``Data`` sheet, wide by year.

Layout, verified on ``Labourers_wage-historical.xlsx``::

    row 1   the indicator name              Labourers Real Wage
    row 2   the unit -- absent on the main site
            Number of daily subsistence baskets that a daily wage buys
    row 3   header: Webmapper code, Webmapper numeric code, ccode,
            country name, start year, end year, then one column per year
    row 4+  one row per polity per border period

Two border schemes share the sheet, and they do not mean the same thing:

* ``geacron/<n>`` -- a historical border period. Its values fall **inside**
  its own start and end years. Never carries a modern ``ccode``.
* ``cshapes/<n>`` -- a post-1946 state. Its row holds the **whole** modern
  series, reaching back before 1946: the United Kingdom's runs 1820-2006.
  These rows are the main site's ``_Compact.xlsx`` file.

So a pre-1946 year for a continuing state appears twice, once in a GeaCron row
and once in the CShapes row. ``in_border_period`` says which reading a value
belongs to; counting every value naively gives the 7,542 the indicator page
quotes, of which 1,978 country-years are repeats.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import xlsx

SHEET = "Data"


class WorkbookError(RuntimeError):
    """The sheet does not have the title / unit / header layout."""


#: Excel counts days from 1899-12-30, so a date-formatted cell reads as a
#: five-figure "year". Four polity rows -- Australia, Austria, France,
#: Greenland -- carry ``end year`` that way in every one of the 76 workbooks,
#: and 7305 became a border period ending in the year 7305, which no filter
#: could be wrong about loudly.
_EXCEL_EPOCH = date(1899, 12, 30)


def _number(text: str | None) -> int | None:
    """A whole number from a cell -- a code, or a year before _year sees it."""
    try:
        return int(float(text)) if text not in (None, "") else None
    except ValueError:
        return None


def _year(text: str | None) -> int | None:
    """A border year, converting a date-formatted cell back to its year.

    Only for `start year` and `end year`: a country code of 826 is a country
    code, and would read as 1902 if it went through here.
    """
    number = _number(text)
    if number is None or 1000 <= number <= 2100:
        return number
    if 1 <= number < 100_000:                     # a date serial, not a year
        return (_EXCEL_EPOCH + timedelta(days=number)).year
    raise WorkbookError(f"implausible year {text!r}")


#: What sits above the header row. Every deposit uses the first: title on row
#: 1, unit on row 2, header on row 3 -- though eleven leave the unit blank, and
#: Excel omits an empty row entirely, which is why reading rows in document
#: order once made those look like a layout of their own.
LAYOUTS = {2: "title, unit, header", 1: "title, header", 0: "header"}


def read(path: Path) -> dict[str, Any]:
    """Title, unit and one entry per polity-period, with its values by year.

    The header row is found by what it says -- ``Webmapper code`` -- not by
    position, and whatever sits above it is the title and the unit. ``title``
    and ``unit`` are empty where a layout has none; ``layout`` says which.
    """
    names = xlsx.sheet_names(path)
    table = xlsx.rows(path, SHEET if SHEET in names else names[0])
    at = next((i for i, r in enumerate(table[:5])
               if (r.get("A") or "").strip() == "Webmapper code"), None)
    if at is None or at not in LAYOUTS:
        raise WorkbookError(f"{path}: no 'Webmapper code' header in the first rows")
    above = [(r.get("A") or "").strip() for r in table[:at]]
    header = table[at]
    years = {col: int(text) for col, text in header.items() if text.strip().isdigit()}
    cols = {text.strip(): col for col, text in header.items() if col not in years}

    polities = []
    for row in table[at + 1:]:
        code = (row.get(cols["Webmapper code"]) or "").strip()
        if not code:
            continue
        values, texts = {}, {}
        for col, year in years.items():
            text = row.get(col)
            if text not in (None, ""):
                values[year] = float(text)
                texts[year] = text.strip()      # as written -- a stored value is a string
        ccode = _number(row.get(cols["ccode"]))
        polities.append({
            "code": code,
            "scheme": code.split("/")[0],
            "numeric": _number(row.get(cols["Webmapper numeric code"])),
            "ccode": ccode,
            "name": (row.get(cols["country name"]) or "").strip(),
            "border_start": _year(row.get(cols["start year"])),
            "border_end": _year(row.get(cols["end year"])),
            "values": values,
            "texts": texts,
        })
    return {"title": above[0] if at >= 1 else "",
            "unit": above[1] if at >= 2 else "",
            "layout": LAYOUTS[at],
            "polities": polities}


def long_records(workbook: dict[str, Any]) -> list[dict[str, Any]]:
    """One record per polity-period per year, flagged for its border period."""
    out = []
    for p in workbook["polities"]:
        for year, value in sorted(p["values"].items()):
            inside = (p["border_start"] is not None and p["border_end"] is not None
                      and p["border_start"] <= year <= p["border_end"])
            out.append({"code": p["code"], "scheme": p["scheme"], "name": p["name"],
                        "ccode": p["ccode"], "border_start": p["border_start"],
                        "border_end": p["border_end"], "year": year, "value": value,
                        "in_border_period": inside})
    return out
