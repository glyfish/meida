"""Build stored series from the Clio-Infra workbooks: one per indicator per country.

``clio/<indicator>/<country>`` -- both slugs from display names, so
``clio/gdp_per_capita/united_kingdom``. The page slugs split badly
(``GDPperCapita`` -> ``gdpper_capita``); the names do not, and all 86 indicator
and 202 country slugs are unique.

**Which country a row belongs to.** By its code where it has one. A row with a
blank code takes the code its name carries elsewhere -- name and code are
exactly one-to-one across the download -- and the eight territories never coded
anywhere (Palestine, Macau, Jersey...) are keyed by name. When a recovered row
lands on a year its country's coded series already has, **the coded row wins**:
Canada's two uncoded real-wage values for 1946-47 are the United States'
numbers (found against the DataverseNL deposit); Morocco's two for 1956-57 are
exact duplicates of its coded values. Four collisions in all, reported by
:func:`build_all`, never silently merged.

Values are kept as the workbook wrote them -- ``16.62734117``, ``9.307143E-5``
-- since a value is a string in the storage contract and the publisher's text
is the record.

**Frequency** follows the indicator's usual step: 1 is ``Annual``, 10
``Decadal``, anything else ``Every N years``. Annual indicators still have
holes; the step is the norm, not a promise.

**TTL is a year.** The whole set was published at once (2024-09-02) and is
scriptable, so a yearly check of ``Last-Modified`` is enough. Every series shares
it, like Voteview's, because one publication feeds all of them.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import inventory, units, xlsx
from .fetch import DATA_DIR, RAW

SOURCE = "clio"
TTL_DAYS = 365
FREQUENCY = {1: "Annual", 10: "Decadal"}


def snake(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def indicator_id(entry: dict[str, Any]) -> str:
    return snake(entry["name"])


def frequency(step: int | None) -> str:
    return FREQUENCY.get(step or 1, f"Every {step} years")


def _number(text: str | None) -> float | None:
    try:
        return float(text) if text not in (None, "") else None
    except ValueError:
        return None


def name_codes(data_dir: Path, inv: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Country name -> code, from every coded row in the download."""
    out: dict[str, int] = {}
    for entry in inv.values():
        for rec in xlsx.records(data_dir / RAW / entry["file"], inventory.LONG):
            code = _number(rec.get("ccode"))
            if code is not None:
                out.setdefault((rec.get("country.name") or "").strip(), int(code))
    return out


def series_for(slug: str, entry: dict[str, Any], data_dir: Path,
               codes: dict[str, int], unit: str | None) -> tuple[list[dict[str, Any]], list[tuple]]:
    """Every country series for one indicator, and the collisions it resolved."""
    values: dict[Any, dict[int, str]] = defaultdict(dict)
    names: dict[Any, str] = {}
    uncoded: list[tuple[str, int, str]] = []

    for rec in xlsx.records(data_dir / RAW / entry["file"], inventory.LONG):
        year, text = _number(rec.get("year")), (rec.get("value") or "").strip()
        if year is None or _number(text) is None:
            continue
        name = (rec.get("country.name") or "").strip()
        code = _number(rec.get("ccode"))
        if code is None:
            uncoded.append((name, int(year), text))
            continue
        values[int(code)][int(year)] = text
        names.setdefault(int(code), name)

    collisions = []
    for name, year, text in uncoded:
        key: Any = codes.get(name, f"name:{name}")
        if year in values[key]:
            collisions.append((slug, name, year, text, values[key][year]))
            continue
        values[key][year] = text
        names.setdefault(key, name)

    ind = indicator_id(entry)
    kind = inventory.kind(slug, entry)
    freq = frequency(entry.get("modal_step"))
    out = []
    for key, by_year in values.items():
        if not by_year:
            continue
        country = names[key]
        years = sorted(by_year)
        start, end = f"{years[0]:04d}-01-01", f"{years[-1]:04d}-01-01"
        ccode = key if isinstance(key, int) else None
        out.append({
            "source": SOURCE,
            "native_id": f"{SOURCE}/{ind}/{snake(country)}",
            "title": f"{' '.join(entry['name'].split())} — {country}",
            "frequency": freq,
            "units": unit,
            "observation_start": start,
            "observation_end": end,
            "observation_count": len(years),
            "ttl_days": TTL_DAYS,
            "metadata": {
                "observation_count": len(years),
                "units": unit,
                SOURCE: {
                    "indicator": [ind], "slug": [slug], "category": [entry["category"]],
                    "country": [country], "ccode": [ccode], "kind": [kind],
                    "handle": [entry.get("handle")],
                    "definition": [entry.get("definition")],
                    "observation_start_int": [int(start.replace("-", ""))],
                    "observation_end_int": [int(end.replace("-", ""))],
                },
            },
            "observations": [{"date": f"{y:04d}-01-01", "value": by_year[y]} for y in years],
        })
    return sorted(out, key=lambda r: r["native_id"]), collisions


def build_all(data_dir: Path = DATA_DIR) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every series for every indicator, plus a report of what was resolved."""
    data_dir = Path(data_dir)
    inv = json.loads((data_dir / inventory.INVENTORY).read_text())
    codes = name_codes(data_dir, inv)
    unit_of = units.load()
    records, collisions = [], []
    for slug, entry in sorted(inv.items()):
        rows, hits = series_for(slug, entry, data_dir, codes, unit_of.get(indicator_id(entry), {}).get("unit"))
        records += rows
        collisions += hits
    return records, {"series": len(records), "indicators": len(inv),
                     "observations": sum(r["observation_count"] for r in records),
                     "with_units": sum(1 for r in records if r["units"]),
                     "collisions": collisions}
