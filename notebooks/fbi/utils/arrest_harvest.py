"""Harvest the arrest catalogue, resumably, from the command line.

    python notebooks/fbi/utils/arrest_harvest.py --codes curated
    python notebooks/fbi/utils/arrest_harvest.py --codes all --scopes national,states,cities
    python notebooks/fbi/utils/arrest_harvest.py --dry-run          # cost, no requests
    python notebooks/fbi/utils/arrest_harvest.py --export-only      # files from the checkpoint

Why this exists rather than :func:`utils.catalog.harvest_arrests`. The arrest
route's request dimension is a numeric UCR arrest code, there are 48 of them,
and there is no metadata endpoint -- so an entry costs a request. All 48 codes at
57 scopes is 2,736 requests, which at :data:`PAUSE` is **over three hours** and
nearly three times the 1,000-per-hour allowance. A run that long will be
interrupted: by a 503 from the shared key, by a laptop sleeping, by a kill.
``harvest_arrests`` holds its entries in memory and starts from the beginning,
so an interruption costs the whole run.

This is the same loop with the result of every (code, scope) appended to a
JSONL checkpoint as it completes, flushed and fsynced, so:

* a re-run reads the checkpoint, skips what is in it, and requests only the
  rest -- a full checkpoint makes **no** requests at all;
* it is safe to kill at any point, because a line is either complete on disk or
  absent, and a truncated last line is dropped on the next read;
* the entries live on disk rather than in memory, so ``--export-only`` writes
  the YAML files from a checkpoint gathered over several sittings.

:data:`PAUSE` is **4.0** seconds here rather than ``catalog.PAUSE``'s 3.6.
3.6 is 1,000 an hour exactly -- the allowance with no margin -- and the offence
harvest, which fits inside one hour, met 503 "Client Failure Limit Exceeded" on
58 of 520 calls at one a second. A three-hour run shares the key with whatever
else is using it, so it takes 900 an hour and leaves the rest.

A refusal is retried after a minute (:data:`RETRY_WAIT`) rather than recorded and
skipped, because the refusal a long run meets is the rate limiter rather than a
bad code, and a minute is enough for it. What still fails after
:data:`RETRIES` attempts is written to the failures file and left out of the
checkpoint, so the next run tries it again.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Sequence

_FBI = Path(__file__).resolve().parents[1]              # notebooks/fbi
_MEIDA_ROOT = _FBI.parents[1]
for _path in (str(_FBI), str(_MEIDA_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from clients import FbiClient                                        # noqa: E402
from clients.fbi import ARREST_OFFENSES, ARREST_VERIFIED_FROM        # noqa: E402

try:                                                  # imported as utils.arrest_harvest
    from . import catalog
except ImportError:                                   # run as a script: no package
    from utils import catalog                                        # noqa: E402

#: Seconds between requests: 900 an hour against an allowance of 1,000. See the
#: module docstring for why this is not ``catalog.PAUSE``.
PAUSE = 4.0

#: Seconds to wait before retrying a refused request, and how many attempts each
#: (code, scope) gets in total. The refusal a long run meets is the shared key's
#: rate limiter, which a minute clears.
RETRY_WAIT = 60.0
RETRIES = 3

#: Where the run's state lives. Under ``data/``, which is gitignored and
#: regenerable like everything else the harvests write.
CHECKPOINT = catalog.DATA_DIR / "arrest_harvest.jsonl"
FAILURES = catalog.DATA_DIR / "arrest_harvest_failures.json"

#: The catalog's five city departments, as ``catalog.ipynb`` fixes them.
CITIES = ("DCMPD0000", "NY0303000", "ILCPD0000", "CA0194200", "PAPEP0000")

#: A subset worth cataloguing before all 48 codes are. Every code here means
#: what its name says once :data:`catalog.ARREST_NOTES` is read with it, and the
#: groups that only add up as groups are complete: the whole drug block 150-160
#: is in, so "every drug arrest" is a sum a reader can take, while the
#: prostitution and gambling remainders -- 140 and 170, which read as group
#: totals and are not -- are out.
#:
#: 12 serious offences, the 11 drug codes, and the five a policing question
#: usually reaches for: weapons, DUI, disorderly conduct, vagrancy and the
#: residual.
CURATED: tuple[str, ...] = (
    "all", "11", "12", "20", "23", "30", "50", "55", "60", "70", "90", "110",
    "150", "151", "152", "153", "154", "155", "156", "157", "158", "159", "160",
    "230", "260", "290", "300", "310",
)

Fetch = Callable[[str, str], Awaitable[Any]]


# --- The checkpoint ----------------------------------------------------------


def load_checkpoint(path: Path = CHECKPOINT) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """``(code, scope) -> entries``, from the JSONL file if it exists.

    A line that does not parse is dropped rather than raising: the one line a
    kill can damage is the last one, and losing it costs one request on the next
    run where refusing to read the file costs the whole checkpoint.
    """
    done: dict[tuple[str, str], list[dict[str, Any]]] = {}
    if not Path(path).exists():
        return done
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            done[(row["code"], row["scope"])] = row["entries"]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return done


def record(path: Path, code: str, scope: str, entries: Sequence[dict[str, Any]]) -> None:
    """Append one completed (code, scope) to the checkpoint, durably.

    Appended, flushed and fsynced one line at a time: a rewritten file can be
    lost whole, and a buffered line is not on disk when the process is killed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"code": code, "scope": scope, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "entries": list(entries)}
    with path.open("a") as handle:
        handle.write(json.dumps(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def entries_from_checkpoint(path: Path = CHECKPOINT) -> list[dict[str, Any]]:
    """Every entry the checkpoint holds, in (code, scope) order."""
    done = load_checkpoint(path)
    return [entry for key in sorted(done, key=lambda k: (catalog._code_token(k[0]), k[1]))
            for entry in done[key]]


def pending(codes: Iterable[str], scopes: Iterable[str],
            done: dict[tuple[str, str], Any]) -> list[tuple[str, str]]:
    """The (code, scope) pairs still to fetch, code-major.

    Code-major so that an interrupted run leaves whole codes finished, and one
    code's file is written complete rather than every file being written partial.
    """
    return [(code, scope) for code in codes for scope in scopes
            if (code, scope) not in done]


# --- Scope and code arguments ------------------------------------------------


def parse_scopes(text: str) -> tuple[str, ...]:
    """``'national,states,cities'``, or an explicit list of scopes.

    The tokens expand; anything else is taken as a scope and passed through, so
    ``--scopes TX,NY0303000`` works.
    """
    out: list[str] = []
    for token in (t.strip() for t in text.split(",") if t.strip()):
        if token == "states":
            out.extend(catalog.STATES)
        elif token == "cities":
            out.extend(CITIES)
        elif token == "national":
            out.append("national")
        else:
            out.append(token)
    return tuple(dict.fromkeys(out))                    # de-duplicated, order kept


def parse_codes(text: str) -> tuple[str, ...]:
    """``'all'`` (every code), ``'curated'``, or an explicit list of codes.

    ``'all'`` is the *whole table*, which is awkward because ``all`` is also a
    code -- the every-offence total. ``--codes all`` means the table;
    ``--codes all-only`` or ``--codes all,11`` name the code.
    """
    tokens = [t.strip() for t in text.split(",") if t.strip()]
    if tokens == ["all"]:
        return tuple(ARREST_OFFENSES)
    if tokens == ["curated"]:
        return CURATED
    if tokens == ["all-only"]:
        return ("all",)
    unknown = [t for t in tokens if t not in ARREST_OFFENSES]
    if unknown:
        raise SystemExit(f"not arrest codes: {', '.join(unknown)}")
    return tuple(dict.fromkeys(tokens))


def plan(codes: Sequence[str], scopes: Sequence[str], *, pause: float = PAUSE,
         checkpoint: Path = CHECKPOINT) -> dict[str, Any]:
    """What a run would cost, without making a request. What ``--dry-run`` prints."""
    done = load_checkpoint(checkpoint)
    todo = pending(codes, scopes, done)
    seconds = len(todo) * pause
    return {"codes": len(codes), "scopes": len(scopes),
            "pairs": len(codes) * len(scopes), "done": len(done),
            "requests": len(todo), "seconds": round(seconds),
            "estimate": _clock(seconds),
            "entries_expected": len(todo) + sum(len(v) for v in done.values())}


def _clock(seconds: float) -> str:
    """``9312`` -> ``'2h 35m'``."""
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return (f"{hours}h {minutes:02d}m" if hours else
            f"{minutes}m {secs:02d}s" if minutes else f"{secs}s")


# --- The loop ----------------------------------------------------------------


async def run(codes: Sequence[str], scopes: Sequence[str], *,
              checkpoint: Path = CHECKPOINT,
              failures_path: Path = FAILURES,
              pause: float = PAUSE,
              retries: int = RETRIES,
              retry_wait: float = RETRY_WAIT,
              start: str = ARREST_VERIFIED_FROM,
              end: str | None = None,
              limit: int | None = None,
              agencies: dict[str, dict[str, Any]] | None = None,
              fetch: Fetch | None = None,
              sleep: Callable[[float], None] = time.sleep,
              log: Callable[..., None] = print) -> dict[str, Any]:
    """Fetch every pending (code, scope), checkpointing each as it completes.

    *fetch* is the one request, ``(code, scope) -> payload``; left out, a client
    is opened here. *sleep* and *log* are arguments so the loop can be tested
    without waiting or printing (*log* is called with ``flush=True``). *limit*
    stops after that many pairs, which is a smoke run rather than a shortened
    one: the pairs it did are checkpointed whole and the next run carries on.

    Progress is printed for every scope, not every code: a code is 52 scopes and
    three and a half minutes, which is too coarse to watch. Each line carries the
    pair, what came back, and the time left, so a watcher can tell a slow run
    from a stopped one.
    """
    end = end or catalog.this_month()
    done = load_checkpoint(checkpoint)
    todo = pending(codes, scopes, done)
    if limit is not None:
        todo = todo[:limit]
    # The registry is 5.7 MB of JSON and only agency scopes touch it, so it is
    # read once per run and can be handed in already loaded.
    agencies = catalog._agency_notes() if agencies is None else agencies
    failed: list[tuple[str, str, str]] = []
    requests = 0
    started = time.monotonic()
    log(f"arrest harvest: {len(todo)} of {len(codes) * len(scopes)} pairs to fetch "
        f"({len(done)} already in {Path(checkpoint).name}), "
        f"{_clock(len(todo) * pause)} at {pause}s", flush=True)

    async with contextlib.AsyncExitStack() as stack:
        if fetch is None:
            client = await stack.enter_async_context(FbiClient())

            async def fetch(code: str, scope: str) -> Any:  # noqa: F811 -- the default
                return await client.get_arrests(code, scope=scope, start=start, end=end)

        for index, (code, scope) in enumerate(todo, 1):
            entries: list[dict[str, Any]] | None = None
            note = ""
            for attempt in range(1, retries + 1):
                try:
                    requests += 1
                    payload = await fetch(code, scope)
                    entries = catalog.arrest_entries(payload, scope, code, agencies)
                    break
                except Exception as exc:                  # noqa: BLE001 -- retried, then recorded
                    note = str(exc)[:120]
                    if attempt < retries:
                        log(f"  ! {code} {scope}: {note} — retry {attempt}/{retries - 1} "
                            f"in {_clock(retry_wait)}", flush=True)
                        sleep(retry_wait)
                    else:
                        failed.append((code, scope, note))
            if entries is None:
                log(f"  x {code:>4} {scope:<10} failed after {retries}: {note}", flush=True)
            else:
                record(checkpoint, code, scope, entries)
                entry = entries[0]
                left = (len(todo) - index) * pause
                filed = "      EMPTY" if entry["empty"] else f"{entry['filings']:>3} filings"
                span = (f"{entry['observation_start'] or '-':>10}.."
                        f"{entry['observation_end'] or '-':<10}")
                log(f"[{index:>5}/{len(todo)}] {code:>4} {scope:<10} {filed} {span} "
                    f"{entry['arrests_total']:>12,.0f} arrests  "
                    f"elapsed {_clock(time.monotonic() - started)} "
                    f"left {_clock(left)}", flush=True)
            if index < len(todo):
                sleep(pause)

    # Written even when empty, so the file describes the last run rather than the
    # last run that went wrong -- a stale list of failures reads as current.
    Path(failures_path).parent.mkdir(parents=True, exist_ok=True)
    Path(failures_path).write_text(json.dumps(failed, indent=1) + "\n")
    held = load_checkpoint(checkpoint)
    return {"requests": requests, "fetched": len(todo) - len(failed),
            "skipped": len(done), "failed": len(failed),
            "pairs_done": len(held),
            "entries": sum(len(v) for v in held.values()),
            "pending": len(pending(codes, scopes, held)),
            "elapsed": _clock(time.monotonic() - started)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--codes", default="curated",
                        help="'all' (the 48-code table), 'curated' (28 codes), "
                             "'all-only' (just the every-offence total), or a "
                             "comma-separated list: 11,20,260")
    parser.add_argument("--scopes", default="national,states",
                        help="comma-separated; 'national', 'states' (51), 'cities' "
                             "(the catalog's five ORIs), or explicit scopes")
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
    parser.add_argument("--data-dir", type=Path, default=catalog.DATA_DIR,
                        help="where the YAML files are written")
    parser.add_argument("--pause", type=float, default=PAUSE)
    parser.add_argument("--retry-wait", type=float, default=RETRY_WAIT)
    parser.add_argument("--retries", type=int, default=RETRIES)
    parser.add_argument("--start", default=ARREST_VERIFIED_FROM)
    parser.add_argument("--end", default=None,
                        help="MM-YYYY; the current month by default, which is as "
                             "far as the route serves")
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after this many requests -- for a smoke run")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the cost and exit without a request")
    parser.add_argument("--export-only", action="store_true",
                        help="write the YAML files from the checkpoint, no requests")
    parser.add_argument("--no-export", action="store_true",
                        help="harvest into the checkpoint but write no YAML")
    args = parser.parse_args(argv)

    codes = parse_codes(args.codes)
    scopes = parse_scopes(args.scopes)

    if args.dry_run:
        print(json.dumps(plan(codes, scopes, pause=args.pause,
                              checkpoint=args.checkpoint), indent=1))
        return 0

    if not args.export_only:
        report = asyncio.run(run(codes, scopes, checkpoint=args.checkpoint,
                                 pause=args.pause, retries=args.retries,
                                 retry_wait=args.retry_wait, limit=args.limit,
                                 start=args.start, end=args.end))
        print(json.dumps(report, indent=1), flush=True)

    if not args.no_export:
        entries = entries_from_checkpoint(args.checkpoint)
        if not entries:
            print("nothing in the checkpoint to export")
            return 1
        report = catalog.export(entries, args.data_dir)
        print(json.dumps(report, indent=1))
        left = pending(codes, scopes, load_checkpoint(args.checkpoint))
        if left:
            print(f"NOTE: {len(left)} pairs still pending, so the files written are "
                  f"partial. Re-run to finish, then the export completes them.")
    return 0


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
