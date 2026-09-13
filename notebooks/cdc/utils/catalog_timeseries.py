"""Catalog entries for the file-delivered CDC sources (WONDER and NVSR).

``catalog.py`` builds the Socrata half of the CDC catalog: one entry per atomic
series, each carrying a replayable ``cdc_series_data`` recipe. This module does
the same for the two sources that have no live API, deriving entries from the
records :mod:`wonder_series` and :mod:`nvsr_series` already build -- so titles,
facets and coverage are defined once.

Two things differ from a Socrata entry, both consequences of the data being
file-delivered:

* **``sources`` is provenance, not a fetch instruction.** A Socrata segment says
  how to re-query the API; a ``wonder`` or ``nvsr`` segment records which
  database or workbook a stretch of the series came from, so it can be
  *regenerated*. The ``kind`` field discriminates -- absent means Socrata, which
  is what every existing entry is.
* **``retrieval`` names the tool.** With two retrieval paths on the server, an
  entry says which one serves it rather than leaving a consumer to infer it from
  the shape of the recipe.

Everything else -- ``series_id``, ``concept``, ``unit``, ``facets``, the
observation bounds -- keeps the shape ``catalog.py`` established, so one
document loader can read the whole CDC catalog.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import nvsr_series as ns
from . import wonder_series as ws

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

#: Group keys in the catalog index, and their output files.
WONDER_GROUP = "wonder"
NVSR_GROUP = "nvsr"


def _bounds(record: dict[str, Any]) -> tuple[str, str]:
    """Catalog bounds are bare years, matching the Socrata entries."""
    return record["observation_start"][:4], record["observation_end"][:4]


def _retrieval(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool": "timeseries_source_data",
        "source": record["source"],
        "native_id": record["native_id"],
    }


def wonder_entries(*, data_dir: Path = DATA_DIR) -> list[dict[str, Any]]:
    """Catalog entries for the WONDER cause-of-death series."""
    entries = []
    for record in ws.build_all(data_dir=data_dir / "wonder"):
        meta = record["metadata"][ws.SOURCE]
        concept = meta["concept"][0]
        start, end = _bounds(record)
        key = next(k for k, v in ws.CONCEPTS.items() if v["concept"] == concept)

        entry: dict[str, Any] = {
            "series_id": record["native_id"],
            "concept": concept,
            "unit": record["units"],
            "frequency": "annual",
            "cadence": "R/P1Y",          # a year is added when CDC publishes finals
            "provisional": False,        # D76/D158 are final vintages
            "live": True,
            "title": record["title"],
            "facets": {"geography": "national", "measure": "age_adjusted"},
            "observation_start": start,
            "observation_end": end,
            "definition": meta["definition"][0],
            "sources": [
                {"kind": "wonder", "database": "D76",
                 "years": {"from": int(start), "to": ws.SPLICE_YEAR},
                 "data_file": f"data/wonder/{key}_D76.json"},
                {"kind": "wonder", "database": "D158",
                 "years": {"from": ws.SPLICE_YEAR + 1, "to": int(end)},
                 "data_file": f"data/wonder/{key}_D158.json"},
            ],
            "retrieval": _retrieval(record),
        }
        # A deviation from the published definition belongs in the catalog too,
        # not only in the series metadata -- this is what search surfaces.
        if meta.get("excluded_codes"):
            entry["excluded_codes"] = meta["excluded_codes"]
        entries.append(entry)
    return entries


def nvsr_entries(*, data_dir: Path = DATA_DIR) -> list[dict[str, Any]]:
    """Catalog entries for the NVSR life-expectancy series."""
    entries = []
    for record in ns.build_all(data_dir=data_dir / "nvsr"):
        meta = record["metadata"][ns.SOURCE]
        start, end = _bounds(record)
        facets = {
            k: meta[k][0]
            for k in ("race", "sex", "state", "geography")
            if k in meta
        }
        is_state = "state" in facets
        volumes = ns.STATE_VOLUMES if is_state else ns.US_VOLUMES

        entries.append({
            "series_id": record["native_id"],
            "concept": "life_expectancy",
            "unit": record["units"],
            "frequency": "annual",
            "cadence": "R/P1Y",
            "provisional": False,
            "live": True,
            "title": record["title"],
            "facets": facets,
            "observation_start": start,
            "observation_end": end,
            "definition": meta["definition"][0],
            "sources": [
                {"kind": "nvsr", "volume_dir": volumes[year], "year": year,
                 "data_file": f"data/nvsr/{'state' if is_state else 'us'}/{year}/"}
                for year in sorted(
                    int(o["date"][:4]) for o in record["observations"]
                )
                if year in volumes
            ],
            "retrieval": _retrieval(record),
        })
    return entries


def _write_group(group: str, entries: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    """Write one group file and return its index row."""
    entries = sorted(entries, key=lambda e: e["series_id"])
    filename = f"cdc_series_{group}.yaml"
    (out_dir / filename).write_text(
        yaml.safe_dump(
            {"group": group, "series_count": len(entries), "series": entries},
            sort_keys=False, default_flow_style=False,
        )
    )
    return {
        "group": group,
        "series_file": filename,
        "series_count": len(entries),
        "concepts": sorted({e["concept"] for e in entries}),
    }


def export(out_dir: Path = DATA_DIR, *, data_dir: Path = DATA_DIR) -> dict[str, int]:
    """Write the WONDER and NVSR group files and refresh the catalog index.

    The index is *merged*, not overwritten: ``catalog.py`` owns the Socrata
    groups and this owns two more, and either may run alone.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        _write_group(WONDER_GROUP, wonder_entries(data_dir=data_dir), out_dir),
        _write_group(NVSR_GROUP, nvsr_entries(data_dir=data_dir), out_dir),
    ]

    index_path = out_dir / "dataset.yaml"
    index = yaml.safe_load(index_path.read_text()) if index_path.exists() else {}
    groups = [g for g in index.get("groups", []) if g["group"] not in {WONDER_GROUP, NVSR_GROUP}]
    groups.extend(rows)
    index_path.write_text(
        yaml.safe_dump(
            {
                "source": "cdc",
                "total_series": sum(g["series_count"] for g in groups),
                "groups": groups,
            },
            sort_keys=False, default_flow_style=False,
        )
    )
    return {row["group"]: row["series_count"] for row in rows}


if __name__ == "__main__":
    for group, count in export().items():
        print(f"{group}: {count} series")
