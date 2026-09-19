"""Tests for ``db_import/load_timeseries.py`` against an in-memory table.

Until now only the builders were tested, not the load. The case that forced
this file: Clio-Infra's 11,044 series exceed what one INSERT can bind.
"""
from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa

from db_import import load_timeseries as T


def _engine(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 't.db'}"
    engine = sa.create_engine(url)
    md = sa.MetaData()
    sa.Table(
        "time_series_source", md,
        sa.Column("source_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("native_id", sa.Text, nullable=False),
        sa.Column("title", sa.Text), sa.Column("frequency", sa.Text, nullable=False),
        sa.Column("units", sa.Text), sa.Column("metadata", sa.JSON),
        sa.Column("observations", sa.JSON),
        sa.Column("observation_start", sa.Date), sa.Column("observation_end", sa.Date),
        sa.Column("ttl_days", sa.Integer),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source", "native_id", "frequency", name="uq_tss_source_native_frequency"),
    )
    md.create_all(engine)
    engine.dispose()
    return url


def _jsonl(tmp_path: Path, n: int, value: str = "1.0") -> Path:
    path = tmp_path / "src.jsonl"
    path.write_text("".join(json.dumps({
        "source": "clio", "native_id": f"clio/x/{i}", "title": f"x {i}", "frequency": "Annual",
        "units": None, "observation_start": "1900-01-01", "observation_end": "1900-01-01",
        "ttl_days": 365, "metadata": {}, "observations": [{"date": "1900-01-01", "value": value}],
    }) + "\n" for i in range(n)))
    return path


def _count(url: str) -> int:
    engine = sa.create_engine(url)
    with engine.begin() as c:
        n = c.execute(sa.text("SELECT count(*) FROM time_series_source")).scalar()
    engine.dispose()
    return n


def test_more_series_than_one_batch_are_all_written(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "BATCH", 3)
    url = _engine(tmp_path)
    engine = sa.create_engine(url)
    result = T.load_file(_jsonl(tmp_path, 10), engine)
    engine.dispose()
    assert (result["series"], len(result["new"]), _count(url)) == (10, 10, 10)


def test_a_reload_across_batches_updates_in_place(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "BATCH", 3)
    url = _engine(tmp_path)
    engine = sa.create_engine(url)
    T.load_file(_jsonl(tmp_path, 7), engine)
    result = T.load_file(_jsonl(tmp_path, 7, value="2.0"), engine)
    engine.dispose()
    assert _count(url) == 7                                # no duplicates
    assert (len(result["changed"]), result["observations_moved"]) == (7, 7)


def test_the_chunks_cover_every_row_once():
    items = list(range(10))
    assert [x for batch in T._chunks(items, 3) for x in batch] == items
    assert [len(b) for b in T._chunks(items, 3)] == [3, 3, 3, 1]
