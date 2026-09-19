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

from pathlib import Path
from typing import Any

from . import xlsx

SHEET = "Data"


class WorkbookError(RuntimeError):
    """The sheet does not have the title / unit / header layout."""


def _year(text: str | None) -> int | None:
    try:
        return int(float(text)) if text not in (None, "") else None
    except ValueError:
        return None


def read(path: Path) -> dict[str, Any]:
    """Title, unit and one entry per polity-period, with its values by year."""
    table = xlsx.rows(path, SHEET)
    if len(table) < 3 or "A" not in table[2] or "start year" not in table[2].values():
        raise WorkbookError(f"{path}: expected title, unit and header in rows 1-3")
    header = table[2]
    years = {col: int(text) for col, text in header.items() if text.strip().isdigit()}
    cols = {text.strip(): col for col, text in header.items() if col not in years}

    polities = []
    for row in table[3:]:
        code = (row.get(cols["Webmapper code"]) or "").strip()
        if not code:
            continue
        values = {}
        for col, year in years.items():
            text = row.get(col)
            if text not in (None, ""):
                values[year] = float(text)
        ccode = _year(row.get(cols["ccode"]))
        polities.append({
            "code": code,
            "scheme": code.split("/")[0],
            "numeric": _year(row.get(cols["Webmapper numeric code"])),
            "ccode": ccode,
            "name": (row.get(cols["country name"]) or "").strip(),
            "border_start": _year(row.get(cols["start year"])),
            "border_end": _year(row.get(cols["end year"])),
            "values": values,
        })
    return {"title": (table[0].get("A") or "").strip(),
            "unit": (table[1].get("A") or "").strip(),
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
