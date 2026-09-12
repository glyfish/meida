"""Download the raw CDC files that :mod:`nvsr_series` and :mod:`wonder_series` parse.

Two sources, two very different constraints. NVSR is a bulk FTP pull behind a
rate-based bot filter; WONDER is an XML-POST API throttled to roughly one
query every two minutes, so a full refresh of its nine concepts across both
database vintages takes about forty minutes and is not something to do by
accident.

NVSR has no API. It publishes life tables as Excel workbooks on an FTP tree
named by *volume number*, not data year, so the year -> directory mapping in
:mod:`nvsr_series` is the only thing that finds next year's files. Everything
here is idempotent -- a workbook already on disk is skipped -- so a re-run
resumes rather than re-downloads, which matters because:

**The bot filter is rate-based, not per-request.** A plain ``urllib`` pull at
~3 files/s served 400 workbooks and then stalled every subsequent read to a
timeout; ``curl_cffi`` with a browser fingerprint fetched the exact file it
was stuck on immediately. Hence :data:`PAUSE` and ``impersonate="chrome"``.
Aggressive access trips a multi-day block, so do not lower it.

Two naming quirks are load-bearing:

* The **2018 state volume** (``70-01``) names files ``Alabama-1-Total.xlsx``
  where every other year uses ``AL1.xlsx``. :data:`POSTAL_BY_NAME` maps them
  onto the postal-code scheme the parser expects, so the local tree is
  uniform regardless of what the remote year called them.
* **2020's national volume** uses lowercase ``table01.xlsx``. The parser's
  ``[Tt]able`` regex covers it; the listing regex here has to as well.

``{ST}4`` is a standard-error table rather than a life table, so it is never
fetched -- 153 files a year, not 204.
"""
from __future__ import annotations

import re
import sys
import time
import urllib.parse
from pathlib import Path
import json
from typing import Any, Iterable, Sequence

from curl_cffi import requests

import wonder_codes as wcodes
from nvsr_series import DATA_DIR, STATE_VOLUMES, US_VOLUMES

WONDER_DIR = Path(__file__).parent / "data" / "wonder"

BASE = "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/NVSR"

#: Seconds between file fetches. See the module docstring -- 0.05 tripped the
#: filter after ~400 files and every read after that timed out.
PAUSE = 1.0
TIMEOUT = 90
RETRIES = 4

#: Only the 2018 state volume needs this; it spells jurisdictions out.
POSTAL_BY_NAME: dict[str, str] = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District-of-Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME",
    "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE",
    "Nevada": "NV", "New-Hampshire": "NH", "New-Jersey": "NJ", "New-Mexico": "NM",
    "New-York": "NY", "North-Carolina": "NC", "North-Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode-Island": "RI",
    "South-Carolina": "SC", "South-Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West-Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}


class NvsrFetchError(RuntimeError):
    """Raised when a volume directory cannot be listed."""


def _get(url: str) -> bytes:
    r = requests.get(url, impersonate="chrome", timeout=TIMEOUT)
    r.raise_for_status()
    return r.content


def _listing(volume: str) -> str:
    try:
        return _get(f"{BASE}/{volume}/").decode("utf-8", "replace")
    except Exception as exc:                       # noqa: BLE001 -- reported, not handled
        raise NvsrFetchError(f"cannot list {volume}: {exc}") from exc


def _download(url: str, target: Path) -> bool:
    """Fetch one file, retrying with backoff. False if it was given up on."""
    for attempt in range(RETRIES):
        try:
            target.write_bytes(_get(url))
            return True
        except Exception as exc:                   # noqa: BLE001
            if attempt == RETRIES - 1:
                print(f"    GIVE UP {target.name}: {type(exc).__name__}", file=sys.stderr)
                target.unlink(missing_ok=True)
                return False
            time.sleep(5 * (attempt + 1))          # back off; the filter is watching
    return False


def _fetch_all(volume: str, pairs: list[tuple[str, str]], dest: Path) -> dict[str, int]:
    dest.mkdir(parents=True, exist_ok=True)
    got = 0
    for remote, local in pairs:
        target = dest / local
        if target.exists():                        # idempotent: a re-run resumes
            continue
        if _download(f"{BASE}/{volume}/{urllib.parse.quote(remote)}", target):
            got += 1
            time.sleep(PAUSE)
    return {"wanted": len(pairs), "downloaded": got,
            "on_disk": len(list(dest.glob("*.xlsx")))}


def national_files(volume: str) -> list[tuple[str, str]]:
    """``(remote, local)`` for one national volume. 2020 is lowercase."""
    names = sorted(set(re.findall(r'>([Tt]able\d+\.xlsx)<', _listing(volume))))
    return [(n, n) for n in names]


def state_files(volume: str) -> list[tuple[str, str]]:
    """``(remote, local)`` for one state volume, skipping the ``{ST}4`` SE tables.

    Handles both naming schemes: postal codes (2019+) and the full state names
    the 2018 volume uses, which are renamed on the way in.
    """
    html = _listing(volume)
    out: list[tuple[str, str]] = []
    for name in sorted(set(re.findall(r'>([A-Z]{2}[1-4]\.xlsx)<', html))):
        if name[2] != "4":
            out.append((name, name))
    for name in sorted(set(re.findall(r'>([A-Za-z_. -]+-[1-4]-\w+\.xlsx)<', html))):
        state, num, _ = name.rsplit("-", 2)
        if num == "4":
            continue
        code = POSTAL_BY_NAME.get(state)
        if code is None:
            print(f"    UNMAPPED jurisdiction: {state}", file=sys.stderr)
            continue
        out.append((name, f"{code}{num}.xlsx"))
    return out


def fetch_national(years: Iterable[int] | None = None,
                   data_dir: Path = DATA_DIR) -> dict[int, dict[str, int]]:
    """Download the national life tables. Defaults to every mapped year."""
    out = {}
    for year in sorted(years if years is not None else US_VOLUMES):
        volume = US_VOLUMES[year]
        out[year] = _fetch_all(volume, national_files(volume), data_dir / "us" / str(year))
        print(f"  {year} ({volume}): {out[year]}")
    return out


def fetch_state(years: Iterable[int] | None = None,
                data_dir: Path = DATA_DIR) -> dict[int, dict[str, int]]:
    """Download the per-state life tables. Defaults to every mapped year."""
    out = {}
    for year in sorted(years if years is not None else STATE_VOLUMES):
        volume = STATE_VOLUMES[year]
        out[year] = _fetch_all(volume, state_files(volume), data_dir / "state" / str(year))
        print(f"  {year} ({volume}): {out[year]}")
    return out


def fetch_all(data_dir: Path = DATA_DIR) -> dict[str, dict[int, dict[str, int]]]:
    """Everything NVSR publishes that the builders read. Safe to re-run."""
    return {"national": fetch_national(data_dir=data_dir),
            "state": fetch_state(data_dir=data_dir)}


# --- WONDER -----------------------------------------------------------------

async def fetch_wonder(concepts: Iterable[str] | None = None,
                       databases: Sequence[str] = wcodes.DATABASES,
                       data_dir: Path = WONDER_DIR,
                       *, refresh: bool = False) -> dict[str, Any]:
    """Pull each concept from each database vintage, and write the summary.

    Cached by default: a concept already on disk is skipped, because at one
    query per two minutes a needless refresh of all nine costs forty minutes.
    Pass ``refresh=True`` to re-pull deliberately -- worth doing occasionally,
    since WONDER revises: re-running this today moves eight of drug-induced's
    twenty-two years by one or two deaths.

    The summary records what was actually sent. Several concepts include codes
    WONDER refuses -- the NCHS pseudo-codes ``*U01``-``*U03``, and the
    non-existent gaps in the diseases-of-heart range -- so ``dropped_codes``
    is how the resulting series stays honest about departing from the
    published definition.
    """
    from clients import WonderClient          # lazy: only the WONDER path needs it

    data_dir.mkdir(parents=True, exist_ok=True)
    wanted = sorted(concepts if concepts is not None else wcodes.CODE_SETS)
    summary_path = data_dir / "_download_summary.json"
    # carry the previous run forward: wonder_series reads dropped_codes out of
    # this file to record each series' deviation from the published definition,
    # so a cached run must not blank what an earlier pull recorded
    previous: dict[str, Any] = (json.loads(summary_path.read_text())
                                if summary_path.exists() else {})
    # start from the previous run, so fetching one concept does not drop the
    # other eight from the file the builders read
    summary: dict[str, Any] = dict(previous)

    async with WonderClient() as client:      # self-throttles between requests
        for concept in wanted:
            stem = wcodes.FILE_STEM.get(concept, concept)
            entry = {"citation": wcodes.CITATIONS.get(concept, ""),
                     "num_codes": len(wcodes.CODE_SETS[concept]), "databases": {}}
            summary[concept] = entry
            for database in databases:
                target = data_dir / f"{stem}_{database}.json"
                if target.exists() and not refresh:
                    was = (previous.get(concept, {}).get("databases", {}) or {}).get(database)
                    entry["databases"][database] = was or {
                        "status": "cached", "variant": "unknown", "dropped_codes": []}
                    continue
                try:
                    out = await wcodes.query(concept, client, database)
                except Exception as exc:      # noqa: BLE001 -- recorded, not raised
                    entry["databases"][database] = {"status": "error",
                                                    "error": str(exc)}
                    print(f"  {concept:20s} {database}  ERROR {exc}", file=sys.stderr)
                    continue
                rows = [r if isinstance(r, dict) else r.model_dump() for r in out["rows"]]
                target.write_text(json.dumps(rows, indent=2) + "\n")
                entry["databases"][database] = {"status": "ok",
                                                "variant": out["variant"],
                                                "dropped_codes": out["dropped_codes"]}
                print(f"  {concept:20s} {database}  {len(rows)} years, "
                      f"sent {len(out['codes_sent'])}, dropped {out['dropped_codes']}")

    summary_path.write_text(json.dumps(summary, indent=1) + "\n")
    return summary


if __name__ == "__main__":
    fetch_all()
