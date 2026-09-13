"""Catalog entries for the Voteview series, and the ``.jsonl`` the loader reads.

Voteview has no live API, so its series are stored and served by
``timeseries_source_data`` -- the same route as CDC's WONDER and NVSR. That
makes the catalog entry small: a `retrieval` block naming the tool, plus the
facets a caller would search on.

One download feeds everything. Every series here is reduced from the single
``HSall_members.csv``, so they share one refresh horizon; there is no sense in
their coming due separately when refreshing any one of them re-fetches the file
that produces all eight.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import voteview_series as vs
from .fetch import DATA_DIR

TIMESERIES_DIR = DATA_DIR / "timeseries"
CATALOG_DIR = DATA_DIR


def catalog_entry(record: dict[str, Any]) -> dict[str, Any]:
    meta = record["metadata"][vs.SOURCE]
    start, end = record["observation_start"][:4], record["observation_end"][:4]
    return {
        "series_id": record["native_id"],
        "concept": meta["concept"][0],
        "unit": record["units"],
        "frequency": "biennial",
        "cadence": "R/P2Y",
        "provisional": False,
        "live": True,
        "title": record["title"],
        "facets": {"measure": meta["measure"][0], "chamber": meta["chamber"][0]},
        "observation_start": start,
        "observation_end": end,
        # load_catalog maps `description`, not `definition` -- carrying it here
        # means the prose survives into the catalog and is searchable, rather
        # than being dropped at load. CDC generates these with an LLM; Voteview's
        # are written by hand in MEASURES because there are eight of them.
        "description": meta["definition"][0],
        "definition": meta["definition"][0],
        "sources": [{"kind": "voteview", "file": "HSall_members.csv",
                     "url": "https://voteview.com/static/data/out/members/HSall_members.csv"}],
        "retrieval": {"tool": "timeseries_source_data",
                      "source": vs.SOURCE, "native_id": record["native_id"]},
    }


def export(data_dir: Path = DATA_DIR) -> dict[str, int]:
    """Write the ``.jsonl`` and the catalog YAML. Returns counts."""
    import yaml

    records = vs.build_all(data_dir)
    ts_dir = Path(data_dir) / "timeseries"
    ts_dir.mkdir(parents=True, exist_ok=True)
    with (ts_dir / "voteview.jsonl").open("w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")

    entries = [catalog_entry(r) for r in records]
    (Path(data_dir) / "voteview_series_nominate.yaml").write_text(
        yaml.safe_dump({"group": "nominate", "series_count": len(entries),
                        "series": entries},
                       sort_keys=False, allow_unicode=True, width=88))
    return {"series": len(records), "catalog_entries": len(entries)}


if __name__ == "__main__":
    print(export())
