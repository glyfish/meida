"""Bring the CDC catalog into line with the BLS and BIS catalogs.

CDC was written before those two settled on a shape and diverges from both in
four ways. BLS and BIS agree with each other, so CDC is the outlier:

===================  ==============  ===================================
field                BLS / BIS       CDC (before this)
===================  ==============  ===================================
``observation_*``    ISO date        bare year (``"1999"``, ``"2023 Q1"``)
``observation_*_int``  YYYYMMDD int  absent
``is_active``        bool            absent
``units``            ``units``       ``unit``
``generated``        file-level      absent
===================  ==============  ===================================

The ``_int`` mirrors are not cosmetic: yada's document store filters ranges on
them because Chroma rejects string operands for ``$gte``/``$lte``, so without
them a recency filter over CDC silently matches nothing.

This normalizes the exported YAML in place rather than re-running the exports --
the Socrata catalog would otherwise need thousands of live queries to rebuild
data that is already on disk and unchanged.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

#: ``2023 Q1`` -> the first month of that quarter.
_QUARTER_MONTH = {"1": "01", "2": "04", "3": "07", "4": "10"}


def to_iso(value: Any) -> str | None:
    """Normalize a CDC observation bound to an ISO date.

    Handles the three shapes CDC's ``_span`` produces, since it returns the raw
    min/max of whatever the dataset's time field happens to be: a bare year, a
    ``YYYY Qn`` quarter, and ``YYYY-MM``. Day is pinned to the 1st, matching the
    month-start convention BIS and BLS use.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}", text):
        return f"{text}-01-01"
    m = re.fullmatch(r"(\d{4})\s*Q([1-4])", text)
    if m:
        return f"{m.group(1)}-{_QUARTER_MONTH[m.group(2)]}-01"
    m = re.fullmatch(r"(\d{4})-(\d{2})", text)
    if m:
        return f"{text}-01"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    return None


def to_int(iso: str | None) -> int | None:
    """``2019-01-01`` -> ``20190101``, the mirror the range filters use."""
    return int(iso.replace("-", "")) if iso else None


def normalize_entry(entry: dict[str, Any], baselines: dict[bool, int]) -> dict[str, Any]:
    """Rewrite one entry into the shared shape, preserving field order."""
    if "unit" in entry and "units" not in entry:
        entry["units"] = entry.pop("unit")

    start = to_iso(entry.get("observation_start"))
    end = to_iso(entry.get("observation_end"))
    if start:
        entry["observation_start"] = start
        entry["observation_start_int"] = to_int(start)
    if end:
        entry["observation_end"] = end
        entry["observation_end_int"] = to_int(end)
        # BIS/BLS rule -- active if it runs to within a year of the newest
        # comparable series -- but the baseline is taken *per vintage*.
        # CDC mixes provisional VSRR counts (running to 2026) with final
        # mortality (2024, because NCHS finals lag ~11 months by design). One
        # shared baseline would mark every final series permanently stale,
        # including the newest WONDER and NVSR data.
        provisional = bool(entry.get("provisional"))
        entry["is_active"] = int(end[:4]) >= baselines[provisional] - 1
    return entry


def normalize_file(path: Path, baselines: dict[bool, int], *,
                   today: date | None = None) -> int:
    doc = yaml.safe_load(path.read_text())
    for entry in doc["series"]:
        normalize_entry(entry, baselines)
    doc = {
        **{k: v for k, v in doc.items() if k != "series"},
        "generated": (today or date.today()).isoformat(),
        "series": sorted(doc["series"], key=lambda e: e["series_id"]),
    }
    path.write_text(yaml.safe_dump(doc, sort_keys=False, default_flow_style=False,
                                   allow_unicode=True, width=88))
    return len(doc["series"])


def max_end_years(data_dir: Path = DATA_DIR) -> dict[bool, int]:
    """Newest end year per vintage: ``{provisional: year}``.

    Two baselines, because provisional and final data are not comparable on
    recency -- see :func:`normalize_entry`.
    """
    years: dict[bool, list[int]] = {True: [], False: []}
    for path in sorted(data_dir.glob("cdc_series_*.yaml")):
        for entry in yaml.safe_load(path.read_text())["series"]:
            iso = to_iso(entry.get("observation_end"))
            if iso:
                years[bool(entry.get("provisional"))].append(int(iso[:4]))
    fallback = date.today().year
    return {k: (max(v) if v else fallback) for k, v in years.items()}


def normalize_all(data_dir: Path = DATA_DIR) -> dict[str, int]:
    baselines = max_end_years(data_dir)
    return {
        path.name: normalize_file(path, baselines)
        for path in sorted(data_dir.glob("cdc_series_*.yaml"))
    }


if __name__ == "__main__":
    baselines = max_end_years()
    print(f"is_active baselines: final >= {baselines[False] - 1}, "
          f"provisional >= {baselines[True] - 1}")
    for name, count in normalize_all().items():
        print(f"  {name}: {count} series")
