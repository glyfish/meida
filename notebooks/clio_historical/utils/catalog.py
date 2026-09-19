"""Catalog entries for the historical-borders series, and the ``.jsonl`` the loader reads.

One catalog file per Clio category, as ``notebooks/clio`` does. The facets add
what makes these series different from the main site's: the ``polity`` and its
``border_start`` / ``border_end``, and -- where the main site carries the same
numbers under a successor state -- ``modern_country``, the link from the
Ottoman Empire's rows to Turkey's. Descriptions are Clio's own definitions, as
for ``clio``.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from . import accept
from . import historical_series as hs


def catalog_entry(record: dict[str, Any], definition: str | None) -> dict[str, Any]:
    meta = record["metadata"][hs.SOURCE]
    facets = {"indicator": meta["indicator"][0], "polity": hs.snake(meta["polity"][0]),
              "category": hs.snake(meta["category"][0]), "kind": meta["kind"][0],
              "border_start": meta["border_start"][0], "border_end": meta["border_end"][0]}
    facets["relation"] = meta["relation"][0]
    if meta["modern_country"][0]:
        facets["modern_country"] = hs.snake(meta["modern_country"][0])
    return {
        "series_id": record["native_id"],
        "concept": meta["indicator"][0],
        "unit": record["units"],
        "frequency": record["frequency"].lower(),
        "provisional": False,
        "live": False,
        "title": record["title"],
        "facets": facets,
        "observation_start": record["observation_start"][:4],
        "observation_end": record["observation_end"][:4],
        "description": definition,
        "sources": [{"kind": "dataverse", "doi": meta["doi"][0], "geacron": meta["geacron"][0],
                     "paper_version": meta["paper_version"][0], "downloaded": meta["downloaded"][0]}],
        "retrieval": {"tool": "timeseries_source_data", "source": hs.SOURCE,
                      "native_id": record["native_id"]},
    }


def export(data_dir: Path = accept.DATA_DIR) -> dict[str, Any]:
    data_dir = Path(data_dir)
    records, report = hs.build_all(data_dir)
    inventory = json.loads((hs.CLIO_DATA / "inventory.json").read_text())
    definition = {hs.snake(v["name"]): v.get("definition") for v in inventory.values()}
    (data_dir / "timeseries").mkdir(parents=True, exist_ok=True)
    with (data_dir / "timeseries" / f"{hs.SOURCE}.jsonl").open("w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    groups: dict[str, list] = defaultdict(list)
    for r in records:
        meta = r["metadata"][hs.SOURCE]
        groups[hs.snake(meta["category"][0])].append(catalog_entry(r, definition.get(meta["indicator"][0])))
    for old in data_dir.glob(f"{hs.SOURCE}_series_*.yaml"):
        old.unlink()
    for group, entries in sorted(groups.items()):
        (data_dir / f"{hs.SOURCE}_series_{group}.yaml").write_text(yaml.safe_dump(
            {"group": group, "series_count": len(entries), "series": entries},
            sort_keys=False, allow_unicode=True, width=88))
    return {**report, "catalog_files": len(groups)}
