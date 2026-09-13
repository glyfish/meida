"""Load normalized ``.jsonl`` series into meida's ``time_series_source`` table.

The builders (:mod:`wonder_series`, :mod:`nvsr_series`) turn raw pulls and
spreadsheets into JSON Lines; this puts them in the database the MCP tools
read. Upsert on ``(source, native_id, frequency)`` -- the same conflict target
yada's cache uses -- so re-running after a refresh replaces a series in place
rather than duplicating it, and ``source_id`` stays stable for anything holding
a reference.

``expires_at`` is computed here from ``ttl_days``. It means "due for an
update", not "too old to serve": the client always returns the row and flags
it, because refreshing needs a throttled WONDER pull or a manual NVSR download.

Every load reports what moved. These sources are *revised in place* -- NCHS
reclassifies death certificates after publication, so re-running the pipeline
changes numbers that were already loaded, and a silent upsert would hide that.
Re-pulling drug-induced today shifts eight of its twenty-two years by a death
or two, in both directions. The build artifacts are gitignored and
regenerable, so this diff is the only place an upstream revision becomes
visible.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lib.env import get_meida_db_url

TABLE_NAME = "time_series_source"


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Stream one series per line, so a large file never lands in memory at once."""
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _row(record: dict[str, Any], now: datetime) -> dict[str, Any]:
    ttl = record.get("ttl_days")
    return {
        "source": record["source"],
        "native_id": record["native_id"],
        "title": record["title"],
        "frequency": record["frequency"],
        "units": record.get("units"),
        "metadata": record.get("metadata", {}),
        "observations": record["observations"],
        "observation_start": date.fromisoformat(record["observation_start"]),
        "observation_end": date.fromisoformat(record["observation_end"]),
        "ttl_days": ttl,
        "expires_at": now + timedelta(days=ttl if ttl is not None else 365),
        "updated_at": now,
    }


def _diff(table: sa.Table, rows: list[dict[str, Any]],
          engine: sa.Engine) -> dict[str, Any]:
    """What this load will change, compared against what is stored.

    Read before the upsert, because afterwards there is nothing to compare
    against. Observations are compared as parsed JSON rather than as text so a
    reformat does not read as a revision.
    """
    keys = [(r["source"], r["native_id"], r["frequency"]) for r in rows]
    stored: dict[tuple[str, str, str], Any] = {}
    with engine.begin() as conn:
        for source in {k[0] for k in keys}:
            for sid, nid, freq, obs in conn.execute(sa.select(
                    table.c.source, table.c.native_id, table.c.frequency,
                    table.c.observations).where(table.c.source == source)):
                stored[(sid, nid, freq)] = obs

    new, changed, moved = [], [], 0
    for row, key in zip(rows, keys):
        before = stored.get(key)
        if before is None:
            new.append(row["native_id"])
            continue
        if isinstance(before, str):
            before = json.loads(before)
        after = row["observations"]
        if before == after:
            continue
        was = {o["date"]: o.get("value") for o in before}
        now_ = {o["date"]: o.get("value") for o in after}
        differing = [d for d in set(was) | set(now_) if was.get(d) != now_.get(d)]
        changed.append((row["native_id"], len(differing)))
        moved += len(differing)
    return {"new": new, "changed": changed, "observations_moved": moved}


def load_file(path: Path, engine: sa.Engine, *,
              now: datetime | None = None) -> dict[str, Any]:
    """Upsert every series in one ``.jsonl`` file.

    Returns the series count plus what changed -- see :func:`_diff`.
    """
    now = now or datetime.now(tz=timezone.utc)
    table = sa.Table(TABLE_NAME, sa.MetaData(), autoload_with=engine)
    rows = [_row(rec, now) for rec in read_jsonl(path)]
    if not rows:
        return {"series": 0, "new": [], "changed": [], "observations_moved": 0}

    changes = _diff(table, rows, engine)

    stmt = pg_insert(table).values(rows)
    # created_at and source_id are deliberately untouched -- a refresh updates a
    # series, it does not replace its identity.
    stmt = stmt.on_conflict_do_update(
        constraint="uq_tss_source_native_frequency",
        set_={
            c: stmt.excluded[c]
            for c in ("title", "frequency", "units", "metadata", "observations",
                      "observation_start", "observation_end", "ttl_days",
                      "expires_at", "updated_at")
        },
    )
    with engine.begin() as conn:
        conn.execute(stmt)
    return {"series": len(rows), **changes}


def load_all(directory: Path, db_url: str | None = None) -> dict[str, Any]:
    """Load every ``.jsonl`` in *directory*. Returns per-file counts.

    *directory* is required: each source keeps its own build output under
    ``notebooks/<source>/data/timeseries``, and a default pointing at one of
    them is how the wrong source gets loaded.
    """
    engine = sa.create_engine(db_url or get_meida_db_url())
    try:
        return {p.name: load_file(p, engine) for p in sorted(directory.glob("*.jsonl"))}
    finally:
        engine.dispose()


if __name__ == "__main__":
    import sys

    for name, result in load_all(Path(sys.argv[1])).items():
        print(f"{name}: {result['series']} series")
        if result["new"]:
            print(f"  new: {len(result['new'])}")
        for native_id, n in result["changed"]:
            print(f"  changed: {native_id} ({n} observations)")
        if not result["new"] and not result["changed"]:
            print("  unchanged")
