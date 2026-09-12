"""Download the Voteview roll-call and DW-NOMINATE files.

Voteview is a plain static-file host: no auth, no token, no bot filter, and
the member file arrives in under a second. So unlike CDC's downloads this
needs no fingerprinting or pacing -- what it needs is a **size gate**.

The four files span four orders of magnitude:

===============  ========  ==========================================
file             size      what it is
===============  ========  ==========================================
parties          0.1 MB    per-party aggregates per congress-chamber,
                           including ``nominate_dim1_median`` already
                           computed -- the polarization measure
members          6.2 MB    one row per member per congress, with
                           DW-NOMINATE coordinates
rollcalls       29.8 MB    one row per roll call: date, result, the
                           bill it was on
votes          701.6 MB    one row per member per roll call
===============  ========  ==========================================

:data:`DEFAULT` is parties + members, which is everything the ideology series
need. ``votes`` is **opt-in** and never fetched by default -- it is a hundred
times the size of everything else combined, and nothing in the current build
reads it.

Voteview republishes these in place as a Congress progresses, so a fetched
file is a snapshot, not a fixed artifact. :func:`fetch` records size and
modification time per file for that reason.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable

BASE = "https://voteview.com/static/data/out"
DATA_DIR = Path(__file__).parent / "data"

#: name -> (remote path, approximate MB). Sizes are for the size gate below.
FILES: dict[str, tuple[str, float]] = {
    "parties": ("parties/HSall_parties.csv", 0.1),
    "members": ("members/HSall_members.csv", 6.2),
    "rollcalls": ("rollcalls/HSall_rollcalls.csv", 29.8),
    "votes": ("votes/HSall_votes.csv", 701.6),
}

#: What the series build actually reads.
DEFAULT = ("parties", "members")

#: Anything larger has to be asked for by name.
SIZE_GATE_MB = 100.0

PAUSE = 0.5
TIMEOUT = 300


class VoteviewFetchError(RuntimeError):
    """Raised for an unknown file name or a refused oversized download."""


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        return r.read()


def fetch(names: Iterable[str] = DEFAULT, data_dir: Path = DATA_DIR,
          *, refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Download the named files. Idempotent: anything present is skipped.

    Pass ``refresh=True`` to re-pull -- worth doing when a Congress advances,
    since Voteview updates these in place rather than versioning them.

    A file over :data:`SIZE_GATE_MB` must be named explicitly; requesting one
    through a wildcard is refused rather than quietly pulling 700 MB.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    wanted = list(names)
    out: dict[str, dict[str, Any]] = {}

    for name in wanted:
        if name not in FILES:
            raise VoteviewFetchError(
                f"unknown file {name!r}; known: {', '.join(sorted(FILES))}")
        path, size_mb = FILES[name]
        target = data_dir / Path(path).name

        if target.exists() and not refresh:
            out[name] = {"status": "cached", "bytes": target.stat().st_size,
                         "path": str(target)}
            continue
        if size_mb > SIZE_GATE_MB and name not in set(names):
            raise VoteviewFetchError(f"{name} is ~{size_mb:.0f} MB; ask for it by name")

        blob = _get(f"{BASE}/{path}")
        target.write_bytes(blob)
        out[name] = {"status": "downloaded", "bytes": len(blob), "path": str(target)}
        time.sleep(PAUSE)

    manifest = data_dir / "_manifest.json"
    previous = json.loads(manifest.read_text()) if manifest.exists() else {}
    previous.update({
        name: {"bytes": info["bytes"],
               "modified": time.strftime("%Y-%m-%dT%H:%M:%S",
                                         time.gmtime(Path(info["path"]).stat().st_mtime))}
        for name, info in out.items()})
    manifest.write_text(json.dumps(previous, indent=1, sort_keys=True) + "\n")
    return out


# --- verification -------------------------------------------------------------

#: DW-NOMINATE scores presidents too; they are not members of either chamber.
CHAMBERS = ("House", "Senate")

#: Voteview's own party numbering. 100/200 are the modern two.
DEMOCRAT, REPUBLICAN = 100, 200


def party_code(row: dict[str, str]) -> int:
    """``party_code`` as an int, whichever way the CSV spelled it.

    Congresses 115-117 write it as ``"200.0"`` and the rest as ``"200"`` --
    1,669 rows of 51,064. Comparing the raw string drops those three
    congresses from any party filter and returns *nothing* rather than
    raising, which is how a polarization series ends up with a silent hole in
    2017-2021. ``district_code`` has the same split.
    """
    return int(float(row["party_code"]))


def verify_members(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Check the member panel is intact. Raises on anything structural.

    Cheap and offline, so it runs after every fetch: the file is republished
    in place as a Congress advances, and a truncated or reshaped download
    still parses.
    """
    import csv

    path = Path(data_dir) / "HSall_members.csv"
    if not path.exists():
        raise VoteviewFetchError(f"no member file at {path} -- fetch first")
    rows = list(csv.DictReader(path.open()))
    if not rows:
        raise VoteviewFetchError(f"{path} is empty")

    congresses = sorted({int(r["congress"]) for r in rows})
    gaps = sorted(set(range(congresses[0], congresses[-1] + 1)) - set(congresses))
    if gaps:
        raise VoteviewFetchError(f"missing congresses: {gaps}")

    chambers = {r["chamber"] for r in rows}
    if not set(CHAMBERS) <= chambers:
        raise VoteviewFetchError(f"expected House and Senate, found {sorted(chambers)}")

    try:
        codes = {party_code(r) for r in rows}
    except ValueError as exc:
        raise VoteviewFetchError(f"unparseable party_code: {exc}") from exc
    if not {DEMOCRAT, REPUBLICAN} <= codes:
        raise VoteviewFetchError("the two major party codes are not both present")

    # the congress both major parties first appear in -- before it, the
    # two-party frame does not exist and a D-vs-R series is meaningless
    by_congress: dict[int, set[int]] = {}
    for r in rows:
        by_congress.setdefault(int(r["congress"]), set()).add(party_code(r))
    two_party = sorted(c for c, s in by_congress.items()
                       if {DEMOCRAT, REPUBLICAN} <= s)

    scored = sum(1 for r in rows if r["nominate_dim1"])
    return {
        "rows": len(rows),
        "congresses": f"{congresses[0]}-{congresses[-1]}",
        "gaps": gaps,
        "chambers": {c: sum(1 for r in rows if r["chamber"] == c) for c in sorted(chambers)},
        "scored": scored,
        "unscored": len(rows) - scored,
        "float_party_codes": sum(1 for r in rows if "." in r["party_code"]),
        "two_party_from": two_party[0] if two_party else None,
    }
