"""What the DataverseNL deposits hold, measured rather than assumed.

One pass over every filed deposit, producing ``data/inventory.json``: per
indicator, the workbook's layout, what its two border schemes carry, what the
working paper provides, and how the stored series stand to the main site.

The schemes are counted apart because they mean different things. **GeaCron**
rows are historical border periods -- the reason this source exists -- and
**CShapes** rows are post-1946 states whose series reach back before 1946, the
main site's data in another layout. Every workbook lists ~1,412 GeaCron
periods, and counting them separately is what shows that in all but five
indicators they are empty.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from . import accept, historical_series, workbook

INVENTORY = "inventory.json"

#: The four grades the template's "Data quality" section offers. A section that
#: lists only these has not said which applies.
_GRADES = {"central statistical agencies", "historical reconstructions", "estimates", "conjectures"}


def quality_stated(section: str | None) -> bool:
    """Whether a paper's data-quality section says more than the template's menu."""
    for line in (section or "").splitlines():
        text = line.strip().lstrip("ivx").lstrip(".").strip().rstrip(".").casefold()
        if text and text not in _GRADES:
            return True
    return False


def measure(path: Path) -> dict[str, Any]:
    """Rows, values and decade coverage for each border scheme in one workbook."""
    book = workbook.read(path)
    out: dict[str, Any] = {"layout": book["layout"]}
    for scheme in ("geacron", "cshapes"):
        rows = [p for p in book["polities"] if p["scheme"] == scheme]
        with_values = [p for p in rows if p["values"]]
        if scheme == "geacron":
            # only what lies inside a row's own border period is its own
            kept = {id(p): [y for y in p["values"] if p["border_start"] <= y <= p["border_end"]]
                    for p in with_values}
        else:
            kept = {id(p): list(p["values"]) for p in with_values}
        years = [y for ys in kept.values() for y in ys]
        decades: dict[int, set] = defaultdict(set)
        for p in with_values:
            for y in kept[id(p)]:
                decades[y // 10 * 10].add(p["code"])
        out[scheme] = {
            "rows": len(rows),
            "rows_with_values": len(with_values),
            "observations": len(years),
            "start": min(years) if years else None,
            "end": max(years) if years else None,
            "rows_by_decade": {str(d): len(c) for d, c in sorted(decades.items())},
        }
    return out


def build(data_dir: Path = accept.DATA_DIR) -> dict[str, dict[str, Any]]:
    """Measure every filed deposit and write ``inventory.json``."""
    data_dir = Path(data_dir)
    docs = yaml.safe_load((data_dir / "documentation.yaml").read_text())
    datasets = json.loads((data_dir / "datasets.json").read_text())
    clio_inventory = json.loads((historical_series.CLIO_DATA / "inventory.json").read_text())

    records, _ = historical_series.build_all(data_dir)
    relations: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        meta = r["metadata"][historical_series.SOURCE]
        relations[meta["indicator"][0]][meta["relation"][0]] += 1

    filed = {e["clio_slug"] for e in docs.values()}
    out: dict[str, dict[str, Any]] = {}
    for key, e in sorted(docs.items()):
        m = measure(data_dir / "raw" / e["folder"] / e["workbook"])
        ind = clio_inventory.get(e["clio_slug"], {})
        out[key] = {
            "name": " ".join(e["indicator"].split()),
            "category": ind.get("category"),
            "kind": ind.get("kind"),
            "doi": e["doi"],
            "folder": e["folder"],
            "paper": bool(e.get("paper")),
            "paper_version": e.get("version_number"),
            "workbook_unit": e.get("workbook_unit"),
            "paper_unit": e.get("unit"),
            "paper_unit_source": e.get("unit_source"),
            "quality_stated": quality_stated(e.get("data_quality")),
            "abstract_source": e.get("abstract_source"),
            "text_chars": len(e.get("text") or ""),
            "superseded": len(e.get("superseded") or []),
            **m,
            "stored": dict(relations.get(key, {})),
        }
    unfiled = sorted(" ".join(v["name"].split()) for s, v in datasets.items() if s not in filed)
    (data_dir / INVENTORY).write_text(json.dumps(
        {"indicators": out, "unfiled": unfiled}, indent=1, sort_keys=True) + "\n")
    return out
