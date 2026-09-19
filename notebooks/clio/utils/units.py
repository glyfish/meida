"""Units for the Clio-Infra indicators, which the main-site workbooks never state.

``notebooks/clio/units.yaml`` is **committed** -- it is curated, not
regenerable -- keyed by indicator id, each unit with where it came from. The
only authoritative source found so far is row 2 of a DataverseNL deposit's
workbook, so :func:`harvest` reads every deposit filed under
``notebooks/clio_historical`` and adds its unit. Nothing is guessed: an
indicator without a filed deposit, or a definition that states its unit, stays
unit-less until someone checks.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from . import xlsx

UNITS_FILE = Path(__file__).resolve().parents[1] / "units.yaml"
HISTORICAL = Path(__file__).resolve().parents[2] / "clio_historical" / "data"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")


def load(path: Path = UNITS_FILE) -> dict[str, dict[str, Any]]:
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


def harvest(historical: Path = HISTORICAL, path: Path = UNITS_FILE) -> dict[str, str]:
    """Add the unit from every filed DataverseNL deposit. Returns what was added."""
    manifest_path = historical / "manifest.json"
    if not manifest_path.exists():
        return {}
    known = load(path)
    added = {}
    for doi, entry in json.loads(manifest_path.read_text()).items():
        book = historical / "raw" / doi.replace("/", "_") / entry["workbook"]
        rows = xlsx.rows(book, "Data")
        title, unit = (rows[0].get("A") or "").strip(), (rows[1].get("A") or "").strip()
        if not title or not unit:
            continue
        key = _slug(title)
        record = {"unit": unit, "source": f"DataverseNL doi:{doi} v{entry.get('version')}, workbook row 2"}
        if known.get(key) != record:
            known[key] = record
            added[key] = unit
    if added:
        path.write_text(
            "# Units for the Clio-Infra indicators. The main-site workbooks state none;\n"
            "# each entry says where its unit came from. Filled by utils.units.harvest()\n"
            "# from DataverseNL deposits -- nothing here is inferred.\n"
            + yaml.safe_dump(dict(sorted(known.items())), sort_keys=False, allow_unicode=True, width=88))
    return added
