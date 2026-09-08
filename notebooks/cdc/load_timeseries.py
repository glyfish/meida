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
DEFAULT_DIR = Path(__file__).parent / "data" / "timeseries"


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


def load_file(path: Path, engine: sa.Engine, *, now: datetime | None = None) -> int:
    """Upsert every series in one ``.jsonl`` file. Returns the row count."""
    now = now or datetime.now(tz=timezone.utc)
    table = sa.Table(TABLE_NAME, sa.MetaData(), autoload_with=engine)
    rows = [_row(rec, now) for rec in read_jsonl(path)]
    if not rows:
        return 0

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
    return len(rows)


def load_all(directory: Path = DEFAULT_DIR, db_url: str | None = None) -> dict[str, int]:
    """Load every ``.jsonl`` in *directory*. Returns per-file counts."""
    engine = sa.create_engine(db_url or get_meida_db_url())
    try:
        return {p.name: load_file(p, engine) for p in sorted(directory.glob("*.jsonl"))}
    finally:
        engine.dispose()


if __name__ == "__main__":
    for name, count in load_all().items():
        print(f"{name}: {count} series")
