"""Catalog entries for the Clio-Infra series, and the ``.jsonl`` the loader reads.

One catalog file per Clio category -- ``clio_series_prices_and_wages.yaml`` and
so on, eleven of them -- because that is how the site groups its indicators and
how someone browsing would look for one. Every series is stored, so every
``retrieval`` names ``timeseries_source_data``.

The facets are what a caller filters on: ``indicator``, ``country``, the
``ccode`` where there is one, the ``category``, and the ``kind`` -- measured,
panel or reconstruction -- so a search can leave out rows that were never
measured. The description is Clio's own definition, from the indicator page.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from . import clio_series as cs
from .fetch import DATA_DIR

TIMESERIES_DIR = DATA_DIR / "timeseries"


def catalog_entry(record: dict[str, Any]) -> dict[str, Any]:
    meta = record["metadata"][cs.SOURCE]
    facets = {"indicator": meta["indicator"][0], "country": cs.snake(meta["country"][0]),
              "category": cs.snake(meta["category"][0]), "kind": meta["kind"][0]}
    if meta["ccode"][0] is not None:
        facets["ccode"] = meta["ccode"][0]
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
        "description": meta["definition"][0],
        "definition": meta["definition"][0],
        "sources": [{"kind": "clio", "handle": meta["handle"][0],
                     "url": f"https://clio-infra.eu/Indicators/{meta['slug'][0]}.html"}],
        "retrieval": {"tool": "timeseries_source_data", "source": cs.SOURCE,
                      "native_id": record["native_id"]},
    }


def export(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Write ``timeseries/clio.jsonl`` and one catalog file per category."""
    data_dir = Path(data_dir)
    records, report = cs.build_all(data_dir)
    ts_dir = data_dir / "timeseries"
    ts_dir.mkdir(parents=True, exist_ok=True)
    with (ts_dir / "clio.jsonl").open("w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")

    groups: dict[str, list] = defaultdict(list)
    for r in records:
        groups[cs.snake(r["metadata"][cs.SOURCE]["category"][0])].append(catalog_entry(r))
    for old in data_dir.glob("clio_series_*.yaml"):
        old.unlink()                 # a category that vanished must not linger
    for group, entries in sorted(groups.items()):
        (data_dir / f"clio_series_{group}.yaml").write_text(yaml.safe_dump(
            {"group": group, "series_count": len(entries), "series": entries},
            sort_keys=False, allow_unicode=True, width=88))
    return {**report, "catalog_files": len(groups)}
