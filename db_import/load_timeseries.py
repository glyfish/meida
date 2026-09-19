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

from environment import get_meida_db_url

TABLE_NAME = "time_series_source"

#: Rows per INSERT. Postgres caps a statement at 65,535 bound parameters and a
#: row binds about fourteen, so one statement holds ~4,600 series. Clio-Infra's
#: 11,044 would not fit; CDC's 171 and Voteview's 8 never came close.
BATCH = 1000


def _chunks(items: list, size: int | None = None):
    size = size or BATCH            # read at call time, so a test can shrink it
    for start in range(0, len(items), size):
        yield items[start:start + size]


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
    labels: dict[tuple[str, str, str], tuple] = {}
    with engine.begin() as conn:
        for source in {k[0] for k in keys}:
            for sid, nid, freq, obs, title, units in conn.execute(sa.select(
                    table.c.source, table.c.native_id, table.c.frequency,
                    table.c.observations, table.c.title, table.c.units).where(table.c.source == source)):
                stored[(sid, nid, freq)] = obs
                labels[(sid, nid, freq)] = (title, units)

    new, changed, moved, relabelled = [], [], 0, []
    for row, key in zip(rows, keys):
        before = stored.get(key)
        if before is None:
            new.append(row["native_id"])
            continue
        # Observations are the revision signal, but a title or unit change is a
        # change too -- units harvested for 8,687 Clio series once reported as
        # "0 changed" because only observations were compared.
        if labels[key] != (row["title"], row["units"]):
            relabelled.append(row["native_id"])
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
    return {"new": new, "changed": changed, "observations_moved": moved, "relabelled": relabelled}


def load_file(path: Path, engine: sa.Engine, *,
              now: datetime | None = None, prune: bool = True) -> dict[str, Any]:
    """Upsert every series in one ``.jsonl`` file, and drop the ones it no longer has.

    Returns the series count plus what changed -- see :func:`_diff`.

    *prune* deletes stored series of this file's sources that the file itself
    no longer carries. Without it a rebuild that renames an id leaves the old
    row behind, still served by ``timeseries_source_data`` and no longer in the
    catalog: seven clio_historical series outlived their ids that way. It
    assumes one file per source, which :func:`load_all` checks before asking
    for it.
    """
    now = now or datetime.now(tz=timezone.utc)
    table = sa.Table(TABLE_NAME, sa.MetaData(), autoload_with=engine)
    rows = [_row(rec, now) for rec in read_jsonl(path)]
    if not rows:
        return {"series": 0, "new": [], "changed": [], "observations_moved": 0,
                "relabelled": [], "pruned": []}

    changes = _diff(table, rows, engine)

    # One transaction, several statements: a load still lands whole or not at all.
    with engine.begin() as conn:
        for batch in _chunks(rows):
            stmt = pg_insert(table).values(batch)
            # created_at and source_id are deliberately untouched -- a refresh
            # updates a series, it does not replace its identity.
            conn.execute(stmt.on_conflict_do_update(
                constraint="uq_tss_source_native_frequency",
                set_={
                    c: stmt.excluded[c]
                    for c in ("title", "frequency", "units", "metadata", "observations",
                              "observation_start", "observation_end", "ttl_days",
                              "expires_at", "updated_at")
                },
            ))
    removed: list[str] = []
    if prune:
        keep = {(r["source"], r["native_id"]) for r in rows}
        with engine.begin() as conn:
            for source in sorted({r["source"] for r in rows}):
                # The set difference is taken here rather than as NOT IN (...),
                # which would bind every id in one statement.
                stale = [nid for (nid,) in conn.execute(
                    sa.select(table.c.native_id).where(table.c.source == source))
                         if (source, nid) not in keep]
                for batch in _chunks(stale):
                    conn.execute(sa.delete(table).where(
                        table.c.source == source, table.c.native_id.in_(batch)))
                removed += stale
    return {"series": len(rows), "pruned": removed, **changes}


def load_all(directory: Path, db_url: str | None = None) -> dict[str, Any]:
    """Load every ``.jsonl`` in *directory*. Returns per-file counts.

    *directory* is required: each source keeps its own build output under
    ``notebooks/<source>/data/timeseries``, and a default pointing at one of
    them is how the wrong source gets loaded.
    """
    paths = sorted(directory.glob("*.jsonl"))
    # Pruning is per source, so a source split across two files would have each
    # file delete the other's series. Check before letting that happen.
    files_by_source: dict[str, list[str]] = {}
    for path in paths:
        for source in {rec["source"] for rec in read_jsonl(path)}:
            files_by_source.setdefault(source, []).append(path.name)
    split = {s: f for s, f in files_by_source.items() if len(f) > 1}

    engine = sa.create_engine(db_url or get_meida_db_url())
    try:
        out = {p.name: load_file(p, engine, prune=not split) for p in paths}
        if split:
            out["prune_skipped"] = split
        return out
    finally:
        engine.dispose()


if __name__ == "__main__":
    import sys

    for name, result in load_all(Path(sys.argv[1])).items():
        if name == "prune_skipped":
            print(f"prune skipped, a source spans several files: {result}")
            continue
        print(f"{name}: {result['series']} series")
        if result["new"]:
            print(f"  new: {len(result['new'])}")
        for native_id, n in result["changed"]:
            print(f"  changed: {native_id} ({n} observations)")
        if result.get("pruned"):
            print(f"  pruned: {len(result['pruned'])}")
        if not result["new"] and not result["changed"]:
            print("  unchanged")
