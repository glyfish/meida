"""Read a worksheet out of an ``.xlsx`` with the standard library only.

meida's environment has pandas but not openpyxl, so ``pandas.read_excel``
cannot open these. An ``.xlsx`` is a zip of XML: the workbook lists the sheets
by name, each sheet is ``xl/worksheets/sheetN.xml``, and text cells hold an
index into ``xl/sharedStrings.xml`` rather than the string itself. That is all
this needs -- the Clio files are plain grids with no formulas worth evaluating.

Sheets are looked up **by name**, never by position. NVSR's 2018 volume taught
that: a workbook laid out differently from the rest reads without error and
means something else.
"""
from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path


class XlsxError(RuntimeError):
    """The workbook lacks a requested sheet, or is not a readable ``.xlsx``."""


_CELL = re.compile(r"<c\b([^>]*?)(?:/>|>(.*?)</c>)", re.S)
_TEXT = re.compile(r"<t[^>]*>(.*?)</t>", re.S)


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    xml = z.read("xl/sharedStrings.xml").decode()
    return [html.unescape("".join(_TEXT.findall(si)))
            for si in re.findall(r"<si>(.*?)</si>", xml, re.S)]


def sheet_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        return re.findall(r'<sheet\b[^>]*\bname="([^"]+)"',
                          z.read("xl/workbook.xml").decode())


def _sheet_file(z: zipfile.ZipFile, name: str) -> str:
    """Resolve a sheet name to its XML part through the workbook's relationships."""
    wb = z.read("xl/workbook.xml").decode()
    m = re.search(rf'<sheet\b[^>]*\bname="{re.escape(html.escape(name, quote=True))}"[^>]*/>', wb) \
        or re.search(rf'<sheet\b[^>]*\bname="{re.escape(name)}"[^>]*/>', wb)
    if not m:
        raise XlsxError(f"no sheet {name!r}; have {sheet_names_from(wb)}")
    rid = re.search(r'\br:id="([^"]+)"', m.group(0)).group(1)
    rels = z.read("xl/_rels/workbook.xml.rels").decode()
    target = re.search(rf'<Relationship\b[^>]*\bId="{re.escape(rid)}"[^>]*\bTarget="([^"]+)"', rels) \
        or re.search(rf'<Relationship\b[^>]*\bTarget="([^"]+)"[^>]*\bId="{re.escape(rid)}"', rels)
    part = target.group(1).lstrip("/")
    return part if part.startswith("xl/") else f"xl/{part}"


def sheet_names_from(workbook_xml: str) -> list[str]:
    return re.findall(r'<sheet\b[^>]*\bname="([^"]+)"', workbook_xml)


def rows(path: Path, sheet: str) -> list[dict[str, str]]:
    """Every row of *sheet* as ``{column letter: text}``, empty cells omitted."""
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise XlsxError(f"{path} is not an .xlsx") from exc
    with z:
        shared = _shared_strings(z)
        xml = z.read(_sheet_file(z, sheet)).decode()
    out = []
    for row in re.findall(r"<row\b[^>]*>(.*?)</row>", xml, re.S):
        cells: dict[str, str] = {}
        for attrs, body in _CELL.findall(row):
            col = re.search(r'\br="([A-Z]+)', attrs).group(1)
            value = re.search(r"<v>(.*?)</v>", body or "")
            if 't="s"' in attrs and value:
                cells[col] = shared[int(value.group(1))]
            elif 't="inlineStr"' in attrs:
                cells[col] = html.unescape("".join(_TEXT.findall(body or "")))
            elif value:
                cells[col] = html.unescape(value.group(1))
        out.append(cells)
    return out


def records(path: Path, sheet: str) -> list[dict[str, str]]:
    """Rows keyed by the header row's text rather than by column letter."""
    table = rows(path, sheet)
    if not table:
        return []
    header = table[0]
    return [{header[c]: v for c, v in r.items() if c in header} for r in table[1:]]
