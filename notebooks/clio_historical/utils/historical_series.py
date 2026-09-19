"""Stored series from the DataverseNL deposits: Clio indicators at historical borders.

Every deposit's workbook lists the same ~1,412 GeaCron border periods, but in
all except five indicators those rows are empty: the deposit's data is its
CShapes rows, and those are the main site's series, already stored as
``clio``. What is genuinely new is small -- about 400 border-period series in
three indicators: exchange rates to the pound, days lost in labour disputes,
and labourers' real wages.

So a series here is **one polity within one border period**, holding only the
values inside that period: ``clio_historical/labourers_real_wage/
german_confederation_1820_1839``. Outside its period a row repeats what the
CShapes row already carries.

Checked against the main site before storing. A row whose values match a
*different* country's series is usually a predecessor and its successor --
England and the United Kingdom, the Ottoman Empire and Turkey, Persia and Iran
-- and ``modern_country`` records that link. One is not: Canada's real-wage
rows for 1925-1945 hold the United States' numbers, digit for digit, so they
are excluded (:data:`EXCLUDED`).

Refreshed by hand, per the source's plan: a ten-year TTL says "not on a
schedule" without a nullable ``expires_at``.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from . import accept, workbook, xlsx

SOURCE = "clio_historical"
TTL_DAYS = 3650
CLIO_DATA = Path(__file__).resolve().parents[2] / "clio" / "data"

#: Rows proven wrong, never stored: (indicator id, GeaCron code) -> why.
EXCLUDED = {
    ("labourers_real_wage", f"geacron/{n}"):
        "values equal the United States' real-wage series, digit for digit, and "
        "none of Canada's -- a labelling error in the deposit"
    for n in (236, 237, 238, 239)
}
FREQUENCY = {1: "Annual", 10: "Decadal"}


def snake(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def _main_site(slug: str, inventory: dict) -> dict[str, dict[int, float]]:
    """The main site's series for one indicator, country -> {year: value}."""
    out: dict[str, dict[int, float]] = {}
    for r in xlsx.records(CLIO_DATA / "raw" / inventory[slug]["file"], "Data Long Format"):
        try:
            out.setdefault((r["country.name"] or "").strip(), {})[int(float(r["year"]))] = float(r["value"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def same_number(a: float, b: float) -> bool:
    """Equal allowing for rounding. The main site keeps seven significant figures
    (``14.44252``), DataverseNL full precision (``14.4425187753``) -- one part in
    ten million apart. An absolute tolerance of 1e-6 read that as disagreement
    for every value above ten, and called most of France's rows different."""
    return math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-9)


def relate(values: dict[int, float], name: str,
           main: dict[str, dict[int, float]]) -> tuple[str | None, str]:
    """How these values stand to the main site: the country, and the relation.

    ``same``       the same-named country carries every value
    ``extends``    it agrees on every year both have, and this adds years
    ``successor``  another country carries them all -- Ottoman to Turkey
    ``differs``    the same-named country has overlapping years that disagree
    ``new``        no main-site country has any of these years to compare

    "Every value" alone was too strict: France's 1660-1679 exchange rates match
    the main site year for year, but the main site lacks some of those years,
    and that once read as "not on the main site".
    """
    def compare(series: dict[int, float]) -> tuple[int, int]:
        shared = [y for y in values if y in series]
        agree = sum(1 for y in shared if same_number(series[y], values[y]))
        return len(shared), agree

    shared, agree = compare(main.get(name, {}))
    if shared and agree == shared:
        return name, "same" if shared == len(values) else "extends"
    for country, series in main.items():
        if country != name:
            s, a = compare(series)
            if s == len(values) and a == s:
                return country, "successor"
    if shared:
        return name, "differs"
    return None, "new"


def build_all(data_dir: Path = accept.DATA_DIR) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data_dir = Path(data_dir)
    docs = yaml.safe_load((data_dir / "documentation.yaml").read_text())
    inventory = json.loads((CLIO_DATA / "inventory.json").read_text())
    records, excluded, ids = [], [], set()
    for key, entry in sorted(docs.items()):
        path = data_dir / "raw" / entry["folder"] / entry["workbook"]
        book = workbook.read(path)
        rows = [p for p in book["polities"] if p["scheme"] == "geacron"
                and any(p["border_start"] <= y <= p["border_end"] for y in p["values"])]
        if not rows:
            continue
        ind = inventory[entry["clio_slug"]]
        main = _main_site(entry["clio_slug"], inventory)
        unit = entry.get("workbook_unit") or entry.get("unit")
        freq = FREQUENCY.get(ind.get("modal_step") or 1, f"Every {ind.get('modal_step')} years")
        downloaded = date.fromtimestamp(path.stat().st_mtime).isoformat()
        for p in rows:
            if (key, p["code"]) in EXCLUDED:
                excluded.append((key, p["code"], p["name"], EXCLUDED[(key, p["code"])]))
                continue
            inside = sorted(y for y in p["values"] if p["border_start"] <= y <= p["border_end"])
            native_id = f"{SOURCE}/{key}/{snake(p['name'])}_{p['border_start']}_{p['border_end']}"
            if native_id in ids:                      # two rows, same name and period
                native_id += f"_g{p['code'].split('/')[-1]}"
            ids.add(native_id)
            start, end = f"{inside[0]:04d}-01-01", f"{inside[-1]:04d}-01-01"
            modern, relation = relate({y: p["values"][y] for y in inside}, p["name"], main)
            records.append({
                "source": SOURCE, "native_id": native_id,
                "title": f"{' '.join(entry['indicator'].split())} — {p['name']} "
                         f"(borders {p['border_start']}–{p['border_end']})",
                "frequency": freq, "units": unit,
                "observation_start": start, "observation_end": end,
                "observation_count": len(inside), "ttl_days": TTL_DAYS,
                "metadata": {
                    "observation_count": len(inside), "units": unit,
                    SOURCE: {
                        "indicator": [key], "category": [ind["category"]], "kind": [ind["kind"]],
                        "polity": [p["name"]], "geacron": [p["code"]],
                        "border_start": [p["border_start"]], "border_end": [p["border_end"]],
                        "modern_country": [modern], "relation": [relation],
                        "doi": [entry["doi"]], "paper_version": [entry.get("paper_version")],
                        "downloaded": [downloaded],
                        "observation_start_int": [int(start.replace("-", ""))],
                        "observation_end_int": [int(end.replace("-", ""))],
                    },
                },
                "observations": [{"date": f"{y:04d}-01-01", "value": p["texts"][y]} for y in inside],
            })
    return records, {"series": len(records), "excluded": excluded,
                     "observations": sum(r["observation_count"] for r in records)}
