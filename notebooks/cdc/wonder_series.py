"""Build normalized time series from the cached CDC WONDER pulls.

WONDER is throttled to ~1 query per 2 minutes behind a bot filter, so meida
pulls each concept once into ``data/wonder/<concept>_<database>.json`` and
serves from there. This module turns those raw pulls into records shaped for
``time_series_source`` -- the shared observation contract yada's cache also
uses, so moving a series between them is a straight copy.

**Stitching.** Each concept is pulled from two databases: D76 (bridged race,
1999-2020) and D158 (single race, 2018-2024). They overlap on 2018-2020 and
agree exactly there, which is what makes the splice safe. The rule is D76 for
years <= 2020, D158 after -- one series per concept, 1999-2024.

**Asterisk codes.** WONDER rejects the NCHS pseudo-codes ``*U01``/``*U02``/
``*U03`` outright, so the suicide, homicide, firearm and despair-composite
pulls omit them (recorded per concept in ``_download_summary.json``). Those
series therefore exclude terrorism-reclassified deaths -- historically a
handful per year, but a real deviation from the published definition, so it is
carried into each series' metadata rather than left in a commit message.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable

DATA_DIR = Path(__file__).parent / "data" / "wonder"
SOURCE = "cdc_wonder"

#: D76 covers 1999-2020, D158 2018-2024. Splice at the last D76 year.
SPLICE_YEAR = 2020

#: Annual data; both WONDER databases gain a year when CDC publishes finals.
TTL_DAYS = 365

#: Per-concept presentation. Keys match the ``<concept>`` half of the filenames.
CONCEPTS: dict[str, dict[str, str]] = {
    "alcohol": {
        "concept": "alcohol_induced",
        "title": "Alcohol-induced deaths",
        "definition": "NCHS alcohol-induced causes (NVSR 70-08 p. 75)",
    },
    "drug_induced": {
        "concept": "drug_induced",
        "title": "Drug-induced deaths",
        "definition": "NCHS drug-induced causes (NVSR 70-08 p. 74)",
    },
    "drug_overdose": {
        "concept": "drug_overdose",
        "title": "Drug overdose deaths",
        "definition": "NCHS drug-overdose causes, a subcategory of drug-induced (NVSR 70-08 p. 74)",
    },
    "suicide": {
        "concept": "suicide",
        "title": "Suicide deaths",
        "definition": "Intentional self-harm, X60-X84 and Y87.0 (NVSR 70-08 Table C)",
    },
    "homicide": {
        "concept": "homicide",
        "title": "Homicide deaths",
        "definition": "Assault, X85-Y09 and Y87.1 (NVSR 70-08)",
    },
    "chronic_liver": {
        "concept": "chronic_liver_mortality",
        "title": "Chronic liver disease and cirrhosis deaths",
        "definition": "K70, K73-K74 (NVSR 70-08 Table C)",
    },
    "firearm": {
        "concept": "firearm",
        "title": "Firearm-related deaths",
        "definition": "W32-W34, X72-X74, X93-X95, Y22-Y24, Y35.0 (NVSR 70-08 p. 75)",
    },
    "cardiometabolic": {
        "concept": "cardiometabolic",
        "title": "Heart disease deaths",
        "definition": "Diseases of heart, I00-I09, I11, I13, I20-I51 (NVSR 70-08 Table C)",
    },
    "despair_composite": {
        "concept": "despair_composite",
        "title": "Deaths of despair (alcohol, drug-induced and suicide)",
        "definition": (
            "Set union of the alcohol-induced, drug-induced and suicide code sets, "
            "queried as one request -- summing the separate series would double-count "
            "the codes they share"
        ),
    },
}

UNITS = "deaths per 100,000"


class WonderSeriesError(RuntimeError):
    """Raised when the cached pulls cannot be assembled into a series."""


def _load(concept_key: str, database: str, data_dir: Path) -> list[dict[str, Any]]:
    path = data_dir / f"{concept_key}_{database}.json"
    if not path.exists():
        raise WonderSeriesError(f"missing WONDER pull: {path}")
    return json.loads(path.read_text())


def stitch(d76: Iterable[dict], d158: Iterable[dict]) -> list[dict]:
    """Splice the two databases into one ascending series.

    D76 supplies years through :data:`SPLICE_YEAR`, D158 everything after. The
    overlap is dropped from D158 rather than averaged -- the two agree exactly
    there, and preferring one keeps the series reproducible.
    """
    rows = [r for r in d76 if r["year"] <= SPLICE_YEAR]
    rows += [r for r in d158 if r["year"] > SPLICE_YEAR]
    rows.sort(key=lambda r: r["year"])

    years = [r["year"] for r in rows]
    if len(set(years)) != len(years):
        dupes = sorted({y for y in years if years.count(y) > 1})
        raise WonderSeriesError(f"duplicate years after stitch: {dupes}")
    return rows


def check_overlap(d76: list[dict], d158: list[dict]) -> list[int]:
    """Return the years where the two databases disagree on the rate.

    The splice rests on them agreeing; a non-empty result means a vintage
    changed under us and the stitch should not be trusted.
    """
    a = {r["year"]: r.get("age_adjusted_rate") for r in d76}
    b = {r["year"]: r.get("age_adjusted_rate") for r in d158}
    return sorted(y for y in a.keys() & b.keys() if a[y] != b[y])


def _observation(row: dict[str, Any]) -> dict[str, Any]:
    """One row -> the shared observation shape.

    ``value`` is the age-adjusted rate as a **string**, matching the contract
    FRED and Tiingo already use. Counts ride along beside it: they are what a
    caller needs to re-derive or re-weight a rate.
    """
    rate = row.get("age_adjusted_rate")
    obs: dict[str, Any] = {
        "date": f"{row['year']:04d}-01-01",       # annual -> January 1st
        "value": None if rate is None else str(rate),
    }
    for key in ("deaths", "population"):
        if row.get(key) is not None:
            obs[key] = row[key]
    if row.get("crude_rate") is not None:
        obs["crude_rate"] = str(row["crude_rate"])
    return obs


def build_series(concept_key: str, *, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Assemble one concept into a ``time_series_source`` record."""
    if concept_key not in CONCEPTS:
        raise WonderSeriesError(f"unknown concept {concept_key!r}")
    spec = CONCEPTS[concept_key]

    d76 = _load(concept_key, "D76", data_dir)
    d158 = _load(concept_key, "D158", data_dir)

    mismatched = check_overlap(d76, d158)
    if mismatched:
        raise WonderSeriesError(
            f"{concept_key}: D76 and D158 disagree on {mismatched} -- "
            "the splice assumes they match"
        )

    rows = stitch(d76, d158)
    observations = [_observation(r) for r in rows]
    start, end = observations[0]["date"], observations[-1]["date"]

    summary = _summary(data_dir).get(concept_key, {})
    dropped = _dropped_codes(summary)

    metadata: dict[str, Any] = {
        "observation_count": len(observations),
        "units": UNITS,
        SOURCE: {
            "concept": [spec["concept"]],
            "definition": [spec["definition"]],
            "databases": ["D76", "D158"],
            "geography": ["United States"],
            "measure": ["age-adjusted rate, 2000 US standard population"],
            "observation_start_int": [int(start[:4] + "0101")],
            "observation_end_int": [int(end[:4] + "0101")],
        },
    }
    if dropped:
        # A published-definition deviation belongs with the data, not in a
        # commit message -- anyone reading this series should see it.
        metadata[SOURCE]["excluded_codes"] = sorted(dropped)
        metadata[SOURCE]["exclusion_note"] = [
            "WONDER rejects the NCHS pseudo-codes listed in excluded_codes, so "
            "terrorism-reclassified deaths are omitted from this series"
        ]

    return {
        "source": SOURCE,
        "native_id": f"cdc/{spec['concept']}/wonder/national/age_adjusted",
        "title": f"{spec['title']}, age-adjusted rate, United States",
        "frequency": "Annual",
        "units": UNITS,
        "observation_start": start,
        "observation_end": end,
        "observation_count": len(observations),
        "ttl_days": TTL_DAYS,
        "metadata": metadata,
        "observations": observations,
    }


def _summary(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "_download_summary.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _dropped_codes(summary: dict[str, Any]) -> set[str]:
    """Codes WONDER refused, recorded by the downloader per database."""
    dropped: set[str] = set()
    for entry in (summary.get("databases") or {}).values():
        dropped.update(entry.get("dropped_codes") or [])
    return dropped


def build_all(*, data_dir: Path = DATA_DIR) -> list[dict[str, Any]]:
    """Build every concept that has both database pulls on disk."""
    out = []
    for key in CONCEPTS:
        if (data_dir / f"{key}_D76.json").exists():
            out.append(build_series(key, data_dir=data_dir))
    return out


def write_jsonl(records: list[dict[str, Any]], path: Path) -> int:
    """Write records as JSON Lines -- one series per line.

    Line-per-series so the importer can stream, individual series diff cleanly,
    and a partial write is recoverable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return len(records)
