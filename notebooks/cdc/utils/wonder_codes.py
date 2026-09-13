"""The ICD-10 code sets that define each WONDER concept, and how to check them.

These were lost. The first WONDER pull ran from a script that is gone; what
survived is ``data/wonder/*.json`` -- results only, no queries -- and
``_download_summary.json``, which records a citation and a code *count* per
concept but not the codes. So the cached series could be read and never
rebuilt, and a re-pull would have silently produced a different measure.

Two things make a reconstruction checkable rather than a guess:

**The counts.** :func:`check_counts` compares each rebuilt set against the
recorded ``num_codes``. Seven of the nine are standard NCHS groupings and
matched on the first attempt, which is weak evidence individually and strong
across seven.

**The cached results.** :func:`verify_against_cache` is the real test: query
WONDER with a candidate set and compare deaths year by year against what the
original pull returned. Codes that define the same population return the same
deaths, so an exact match over 20+ years settles it. This costs one throttled
query (WONDER allows roughly one per two minutes), which is why the count
check runs first.

``despair_composite`` is a **set union, never a sum of series** -- the
components overlap (X60-X64 sit in both drug-induced and suicide, X65 in both
alcohol-induced and suicide), so adding rates would double-count.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "wonder"
SUMMARY = DATA_DIR / "_download_summary.json"
DATABASES = ("D76", "D158")


def _span(prefix: str, lo: int, hi: int) -> list[str]:
    """``X40``-style codes: the letter plus a zero-padded two-digit number."""
    return [f"{prefix}{i:02d}" for i in range(lo, hi + 1)]


def _sub(code: str, parts: Iterable[int]) -> list[str]:
    """Four-character subselections, e.g. ``F11.1``-``F11.5``."""
    return [f"{code}.{i}" for i in parts]


#: NCHS "Alcohol-Induced Causes" -- Data Brief 448 / the WONDER UCD help.
#: The one set that survived, in wonder.ipynb; filtering to it reproduces the
#: published alcohol-induced age-adjusted rate exactly.
ALCOHOL_INDUCED = [
    "E24.4", "F10", "G31.2", "G62.1", "G72.1", "I42.6", "K29.2",
    "K70", "K85.2", "K86.0", "R78.0", "X45", "X65", "Y15",
]

#: Diseases of heart, NVSR 70-08 Table C.
CARDIOMETABOLIC = _span("I", 0, 9) + ["I11", "I13"] + _span("I", 20, 51)

#: Chronic liver disease and cirrhosis, NVSR 70-08 Table C.
CHRONIC_LIVER = ["K70", "K73", "K74"]

#: Drug overdose -- formally a subcategory of drug-induced, NVSR 70-08 p.74.
DRUG_OVERDOSE = _span("X", 40, 44) + _span("X", 60, 64) + ["X85"] + _span("Y", 10, 14)

#: Suicide. ``*U03`` is the terrorism reclassification; WONDER's finder rejects
#: the asterisk codes, so the stored series omit them (<10 deaths/yr).
SUICIDE = _span("X", 60, 84) + ["Y87.0", "*U03"]

#: Homicide, including the assault sequelae and terrorism codes.
HOMICIDE = _span("X", 85, 99) + _span("Y", 0, 9) + ["Y87.1", "*U01", "*U02"]

#: Firearm deaths of all intents -- unintentional, suicide, homicide,
#: undetermined, legal intervention, terrorism.
FIREARM = (_span("W", 32, 34) + _span("X", 72, 74) + _span("X", 93, 95)
           + _span("Y", 22, 24) + ["Y35.0", "*U01.4"])

#: Drug-induced causes, NVSR 70-08 p.74. The F-block is enumerated as
#: four-character subselections rather than whole three-character codes:
#: ``.0`` (acute intoxication) and ``.6`` (amnesic syndrome) are not
#: drug-induced deaths, so each substance block contributes ``.1``-``.5`` and
#: ``.7``-``.9``. Dropping ``.0`` is what takes the set from 133 to the
#: recorded 125.
_DRUG_F_BLOCKS = ["F11", "F12", "F13", "F14", "F15", "F16", "F18", "F19"]
DRUG_INDUCED = (
    ["D52.1", "D59.0", "D59.2", "D61.1", "D64.2", "E06.4", "E16.0",
     "E23.1", "E24.2", "E27.3", "E66.1"]
    + [c for block in _DRUG_F_BLOCKS for c in _sub(block, [1, 2, 3, 4, 5, 7, 8, 9])]
    + _sub("F17", [0, 3, 4, 5, 7, 8, 9])
    + ["G21.1", "G24.0", "G25.1", "G25.4", "G25.6", "G44.4", "G62.0", "G72.0"]
    + ["I95.2", "J70.2", "J70.3", "J70.4"]
    + ["L10.5", "L27.0", "L27.1"]
    + ["M10.2", "M32.0", "M80.4", "M81.4", "M83.5", "M87.1"]
    + ["R50.2"] + _sub("R78", [1, 2, 3, 4, 5])
    + _span("X", 40, 44) + _span("X", 60, 64) + ["X85"] + _span("Y", 10, 14)
)

#: Deaths of despair. A union, not a sum -- the components share codes.
DESPAIR_COMPOSITE = sorted(set(ALCOHOL_INDUCED) | set(DRUG_INDUCED) | set(SUICIDE))

#: Where each definition comes from, carried into the pull's summary.
CITATIONS: dict[str, str] = {
    "alcohol_induced": "NCHS Data Brief 448 / WONDER UCD help",
    "cardiometabolic": "NVSR 70-08 Table C p.10 (heart disease)",
    "chronic_liver": "NVSR 70-08 Table C p.10",
    "despair_composite": "union: alcohol_induced+drug_induced+suicide",
    "drug_induced": "NVSR 70-08 p.74",
    "drug_overdose": "NVSR 70-08 p.74 (subcategory)",
    "firearm": "NVSR 70-08 p.75",
    "homicide": "NVSR 70-08 p.11,40,43",
    "suicide": "NVSR 70-08 Table C p.10",
}

#: The one concept whose cached files are not named after it.
FILE_STEM = {"alcohol_induced": "alcohol"}

CODE_SETS: dict[str, list[str]] = {
    "alcohol_induced": ALCOHOL_INDUCED,
    "cardiometabolic": CARDIOMETABOLIC,
    "chronic_liver": CHRONIC_LIVER,
    "despair_composite": DESPAIR_COMPOSITE,
    "drug_induced": DRUG_INDUCED,
    "drug_overdose": DRUG_OVERDOSE,
    "firearm": FIREARM,
    "homicide": HOMICIDE,
    "suicide": SUICIDE,
}


class WonderCodesError(RuntimeError):
    """Raised when a rebuilt set disagrees with what the original pull used."""


def recorded_counts(summary: Path = SUMMARY) -> dict[str, int]:
    """``num_codes`` per concept from the original pull's summary."""
    data = json.loads(Path(summary).read_text())
    counts = {k: v["num_codes"] for k, v in data.items()}
    counts.setdefault("alcohol_induced", len(ALCOHOL_INDUCED))   # pulled by the notebook
    return counts


def check_counts(summary: Path = SUMMARY) -> dict[str, tuple[int, int]]:
    """``{concept: (rebuilt, recorded)}``. Cheap, offline, and runs first."""
    recorded = recorded_counts(summary)
    return {c: (len(codes), recorded.get(c, -1)) for c, codes in sorted(CODE_SETS.items())}


def cached_series(concept: str, database: str = "D76",
                  data_dir: Path = DATA_DIR) -> list[dict[str, Any]]:
    """The original pull's rows for one concept, as the comparison baseline."""
    path = Path(data_dir) / f"{FILE_STEM.get(concept, concept)}_{database}.json"
    if not path.exists():
        raise WonderCodesError(f"no cached pull at {path}")
    return json.loads(path.read_text())


def compare_to_cache(concept: str, rows: Sequence[Any],
                     database: str = "D76",
                     data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Compare fresh rows against the cached pull, year by year.

    Deaths rather than rates: a rate depends on the population vintage, which
    WONDER may have revised, but the death count for a fixed code set and year
    does not move.
    """
    def pairs(items):
        # cached rows are dicts; a live response yields WonderRow models
        for r in items:
            d = r if isinstance(r, dict) else r.model_dump()
            yield int(d["year"]), int(d["deaths"])

    cached = dict(pairs(cached_series(concept, database, data_dir)))
    fresh = dict(pairs(rows))
    shared = sorted(set(cached) & set(fresh))
    diffs = {y: (cached[y], fresh[y]) for y in shared if cached[y] != fresh[y]}
    return {
        "concept": concept, "database": database,
        "years_compared": len(shared),
        "years_only_cached": sorted(set(cached) - set(fresh)),
        "years_only_fresh": sorted(set(fresh) - set(cached)),
        "mismatches": diffs,
        "match": not diffs and not (set(cached) ^ set(fresh)),
    }


#: WONDER names the codes it will not accept in its 500 body.
_REJECTED = re.compile(r"Invalid 'ICD-10 Codes' codes were found: '([^']+)'")


def rejected_codes(message: str) -> list[str]:
    """The codes WONDER named in a rejection, or ``[]`` if it said something else."""
    m = _REJECTED.search(message)
    return [c.strip() for c in m.group(1).split(",")] if m else []


async def query(concept: str, client, database: str = "D76") -> dict[str, Any]:
    """Query WONDER for one concept, dropping codes it refuses and retrying.

    Two kinds of code get refused, and both have to be survivable or most of
    these concepts cannot be fetched at all:

    * the NCHS pseudo-codes ``*U01``-``*U03``, which the published definitions
      of suicide, homicide and firearm include but WONDER's finder rejects;
    * codes that simply do not exist in ICD-10 -- the "diseases of heart"
      range has gaps (``I03``, ``I23``, ``I41`` ...) that a naive span
      enumerates.

    Either way the fix is the same: drop what it named, ask again, and record
    the deviation. ``dropped`` is what makes the resulting series honest about
    departing from the published definition -- terrorism-reclassified deaths
    are a handful a year, but they are missing, and that belongs in metadata
    rather than a commit message.
    """
    codes, dropped = list(CODE_SETS[concept]), []
    for _ in range(3):
        try:
            resp = await client.age_adjusted_rate_by_year(
                codes, database=database, title=f"{concept} ({database})")
        except Exception as exc:                       # noqa: BLE001
            bad = rejected_codes(str(exc))
            if not bad:
                raise
            dropped += bad
            codes = [c for c in codes if c not in set(bad)]
            if not codes:
                raise WonderCodesError(f"{concept}: every code was refused")
            continue
        return {"rows": resp.rows, "codes_sent": codes, "dropped_codes": dropped,
                "variant": "full" if not dropped else "reduced"}
    raise WonderCodesError(f"{concept}: still refused after 3 attempts, dropped {dropped}")


async def verify_against_cache(concept: str, client, database: str = "D76",
                               data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Query WONDER with the rebuilt set and diff it against the cached pull.

    One throttled request, or a few if codes get refused. *client* is an open
    ``WonderClient``; reuse it across concepts so its self-throttle paces them.
    """
    out = await query(concept, client, database)
    result = compare_to_cache(concept, out["rows"], database, data_dir)
    result["dropped_codes"] = out["dropped_codes"]
    result["codes_sent"] = len(out["codes_sent"])
    return result
