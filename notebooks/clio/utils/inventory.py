"""What is actually in the Clio-Infra download, measured rather than assumed.

One pass over every workbook's ``Data Long Format`` sheet, producing
``data/inventory.json``: per indicator the countries, observations, span, how
regular the years are, and whether the file agrees with what the index
published about it.

The index badge (``1820 [5053] 2008``) is the one independent claim to check a
file against, the way NVSR's published life expectancies checked the workbook
parse. Disagreement is recorded, not raised -- the real-wage file already holds
5,084 observations against a badge of 5,053, and knowing the size of that gap
across all 86 is the point.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from . import xlsx
from .fetch import DATA_DIR, HISTORICAL_BORDERS, MANIFEST, RAW

LONG = "Data Long Format"
META = "Metadata"
INVENTORY = "inventory.json"

#: ISO 3166 numeric for the United States -- the country the SDT work is about,
#: so its coverage is reported on its own.
US_CODE = 840


def _number(text: str | None) -> float | None:
    try:
        return float(text) if text not in (None, "") else None
    except ValueError:
        return None


def measure(path: Path) -> dict[str, Any]:
    """Coverage and regularity of one workbook's long-format sheet."""
    by_country: dict[Any, list[int]] = defaultdict(list)
    names: dict[Any, str] = {}
    unparsed = duplicates = uncoded = 0
    values: list[float] = []
    seen: set[tuple[Any, int]] = set()

    for rec in xlsx.records(path, LONG):
        code, year, value = (_number(rec.get("ccode")), _number(rec.get("year")),
                             _number(rec.get("value")))
        if year is None or value is None:
            unparsed += 1
            continue
        # A blank code is a real country, not an aggregate: Sudan, Canada and
        # Morocco lose theirs in some files, and eight territories (Palestine,
        # Macau, Jersey...) never have one. Name and code are one-to-one across
        # the whole download, so the name is a sound identity when the code is
        # absent -- dropping these rows discarded 861 observations.
        name = (rec.get("country.name") or "").strip()
        if code is None:
            uncoded += 1
            c: Any = f"name:{name}"
        else:
            c = int(code)
        y = int(year)
        if (c, y) in seen:
            duplicates += 1
            continue
        seen.add((c, y))
        by_country[c].append(y)
        values.append(value)
        names.setdefault(c, name)

    years = [y for ys in by_country.values() for y in ys]
    # Not all rows are measurements. A binary event panel is mostly zeros --
    # Armed Conflicts is 0/1 for every country since 1500 -- and a model
    # reconstruction covers every country at benchmark years. Coverage counts
    # both as if they were observed, so these two numbers say which is which.
    zero_share = round(sum(1 for v in values if v == 0) / len(values), 3) if values else None
    distinct_values = len(set(values))
    steps: Counter[int] = Counter()
    for ys in by_country.values():
        ys.sort()
        steps.update(b - a for a, b in zip(ys, ys[1:]))
    modal = steps.most_common(1)[0][0] if steps else None
    us = sorted(by_country.get(US_CODE, []))
    # countries with any observation in each decade -- the coverage picture
    decades: dict[int, set] = defaultdict(set)
    for c, ys in by_country.items():
        for y in ys:
            decades[y // 10 * 10].add(c)

    return {
        "countries": len(by_country),
        "observations": len(years),
        "start": min(years) if years else None,
        "end": max(years) if years else None,
        "unparsed_rows": unparsed,
        "duplicate_rows": duplicates,
        "rows_without_code": uncoded,
        "zero_share": zero_share,
        "distinct_values": distinct_values,
        # the usual spacing, and how much of the data follows it
        "modal_step": modal,
        "share_at_modal_step": round(steps[modal] / sum(steps.values()), 3) if modal else None,
        "largest_step": max(steps) if steps else None,
        "us": {"observations": len(us), "start": us[0] if us else None,
               "end": us[-1] if us else None},
        "countries_by_decade": {str(d): len(cs) for d, cs in sorted(decades.items())},
        "longest": sorted(((names[c], len(v), min(v), max(v)) for c, v in by_country.items()),
                          key=lambda t: -t[1])[:3],
    }


def _citation(path: Path) -> dict[str, str]:
    meta = {r.get("Description"): r.get("Value") for r in xlsx.records(path, META)}
    text = meta.get("Text Citation") or ""
    doi = re.search(r"10622[/_][A-Z0-9]+", meta.get("XML Citation") or text)
    return {"citation": text, "handle": doi.group(0).replace("_", "/") if doi else None}


def build(data_dir: Path = DATA_DIR) -> dict[str, dict[str, Any]]:
    """Measure every indicator in the manifest and write ``inventory.json``."""
    data_dir = Path(data_dir)
    manifest = json.loads((data_dir / MANIFEST).read_text())
    out: dict[str, dict[str, Any]] = {}

    for file, entry in sorted(manifest.items()):
        if file == HISTORICAL_BORDERS:
            continue
        path = data_dir / RAW / file
        m = measure(path)
        panels = entry.get("panels", {})
        published = entry.get("published_count")
        out[entry["slug"]] = {
            "name": entry["name"],
            "category": entry["category"],
            "file": file,
            "definition": panels.get("Variable(s)"),
            "stated_period": panels.get("Time period"),
            "production_date": panels.get("Production date"),
            **_citation(path),
            **m,
            "published": {"start": entry.get("published_start"),
                          "count": published,
                          "end": entry.get("published_end")},
            "count_vs_published": (m["observations"] - published) if published else None,
        }

    (data_dir / INVENTORY).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return out
