"""Units for the Clio-Infra indicators, which the main-site workbooks never state.

Built into ``notebooks/clio/data/units.yaml`` -- generated, gitignored, beside
the rest of the build output -- from what the DataverseNL deposits say. Those
belong to ``notebooks/clio_historical``, whose ``documentation.build()``
records, per indicator, the workbook's row 2 and the working paper's unit. This
reads that one file and nothing else: no manifest, no shared code.

**Row 2 wins, the paper is the fallback.** Where both exist they agree word for
word on 2 of 30. Row 2 is usually the more useful label -- "scale from 1
(unlimited authority) to 7", "autocracy-democracy on a -10 to 10 scale" --
where the paper says "dimensionless, multi-nominal scale" or "index". The paper
covers what row 2 cannot: the two workbook layouts that have no row 2. Both are
kept in each entry so nothing is lost by the choice.

Nothing is inferred: an indicator neither states stays without a unit.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .fetch import DATA_DIR

UNITS_FILE = DATA_DIR / "units.yaml"
DOCUMENTATION = (Path(__file__).resolve().parents[2]
                 / "clio_historical" / "data" / "documentation.yaml")


def load(path: Path = UNITS_FILE) -> dict[str, dict[str, Any]]:
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


def choose(entry: dict[str, Any]) -> tuple[str | None, str | None]:
    """The unit to use for one indicator, and where it came from."""
    if entry.get("workbook_unit"):
        return entry["workbook_unit"], "workbook row 2"
    if entry.get("unit"):
        return entry["unit"], f"working paper, {entry.get('unit_source')}"
    return None, None


def harvest(documentation: Path = DOCUMENTATION, path: Path = UNITS_FILE) -> dict[str, Any]:
    """Write ``units.yaml`` from the DataverseNL documentation. Returns counts."""
    if not documentation.exists():
        return {"indicators": 0, "with_unit": 0, "missing": str(documentation)}
    docs = yaml.safe_load(documentation.read_text()) or {}
    out = {}
    for key, entry in sorted(docs.items()):
        unit, source = choose(entry)
        out[key] = {"unit": unit, "source": source,
                    "workbook_unit": entry.get("workbook_unit"),
                    "paper_unit": entry.get("unit"),
                    "doi": entry.get("doi")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Units for the Clio-Infra indicators, built by utils.units.harvest() from\n"
        "# notebooks/clio_historical/data/documentation.yaml. Workbook row 2 is\n"
        "# preferred, the working paper's unit is the fallback; both are kept.\n"
        + yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=88))
    return {"indicators": len(out), "with_unit": sum(1 for v in out.values() if v["unit"]),
            "from_workbook": sum(1 for v in out.values() if v["source"] == "workbook row 2")}
