"""Build the normalized ``.jsonl`` that ``db_import.load_timeseries`` reads.

The missing rung. :mod:`nvsr_series` and :mod:`wonder_series` build series
records and ``wonder_series.write_jsonl`` writes them, but nothing called it --
the two files under ``data/timeseries/`` were produced by hand and had no entry
point in the repo, so the documented pipeline had a step that only existed in
someone's shell history.

Both builders verify before emitting: ``nvsr_series.build_all`` runs the parse
guards over every workbook on disk, and ``wonder_series.build_all`` refuses a
concept whose download summary cannot account for the codes WONDER dropped.
Neither touches the network.

    python -m utils.build_timeseries              # from notebooks/cdc/
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import nvsr_series as ns
from . import wonder_series as ws

#: Where load_timeseries expects to find them.
TIMESERIES_DIR = Path(__file__).resolve().parents[1] / "data" / "timeseries"

BUILDERS = {"cdc_nvsr.jsonl": ns.build_all, "cdc_wonder.jsonl": ws.build_all}


def build(out_dir: Path = TIMESERIES_DIR) -> dict[str, int]:
    """Rebuild every ``.jsonl``. Returns ``{filename: series count}``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    return {name: ws.write_jsonl(builder(), out_dir / name)
            for name, builder in BUILDERS.items()}


if __name__ == "__main__":
    for name, count in build().items():
        print(f"{name}: {count} series")
