"""Tests for the shared catalog loader (``data/load_catalog.py``).

SQLite in-memory through ``db_url=``, the same seam the client tests use, so
real SQL runs with no Postgres.

The behaviour worth pinning is the prune. ``load`` rewrites a source's catalog
whole and deletes rows absent from the files it just read -- correct, because a
series that vanishes from an export has genuinely gone away. It is also why
``source`` has to scope the delete: while this lived under ``notebooks/cdc/``
with ``SOURCE = "cdc"`` baked in, pointing it at a second source's files would
have written those rows and then dropped every CDC row for not appearing in
them.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
import yaml

from data import load_catalog as L


@pytest.fixture
def db(tmp_path) -> str:
    url = f"sqlite:///{tmp_path/'t.db'}"
    engine = sa.create_engine(url)
    md = sa.MetaData()
    sa.Table(
        "series_catalog", md,
        sa.Column("catalog_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("series_id", sa.Text, nullable=False),
        sa.Column("dataset_id", sa.Text), sa.Column("concept", sa.Text),
        sa.Column("title", sa.Text, nullable=False), sa.Column("description", sa.Text),
        sa.Column("units", sa.Text), sa.Column("frequency", sa.Text),
        sa.Column("provisional", sa.Boolean), sa.Column("is_active", sa.Boolean),
        sa.Column("facets", sa.JSON), sa.Column("retrieval", sa.JSON),
        sa.Column("observation_start", sa.Date), sa.Column("observation_end", sa.Date),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source", "series_id", name="uq_sc_source_series"),
    )
    md.create_all(engine)
    engine.dispose()
    return url


def _write(dir_: Path, source: str, group: str, series_ids: list[str]) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / f"{source}_series_{group}.yaml").write_text(yaml.safe_dump({
        "group": group,
        "series": [{"series_id": s, "dataset_id": "ds1", "concept": "c",
                    "title": s, "facets": {}} for s in series_ids],
    }))


def _rows(url: str) -> list[tuple[str, str]]:
    engine = sa.create_engine(url)
    with engine.begin() as c:
        out = [tuple(r) for r in c.execute(sa.text(
            "SELECT source, series_id FROM series_catalog ORDER BY source, series_id"))]
    engine.dispose()
    return out


def test_loads_only_its_own_source_files(tmp_path, db):
    _write(tmp_path, "cdc", "g", ["cdc/a"])
    _write(tmp_path, "voteview", "g", ["vv/a"])
    assert L.load(tmp_path, "cdc", db_url=db) == {"written": 1, "pruned": 0}
    assert _rows(db) == [("cdc", "cdc/a")]


def test_a_second_source_does_not_prune_the_first(tmp_path, db):
    """The reason `source` scopes the delete, and the reason this moved."""
    _write(tmp_path, "cdc", "g", ["cdc/a", "cdc/b"])
    _write(tmp_path, "voteview", "g", ["vv/a"])
    L.load(tmp_path, "cdc", db_url=db)
    L.load(tmp_path, "voteview", db_url=db)
    assert _rows(db) == [("cdc", "cdc/a"), ("cdc", "cdc/b"), ("voteview", "vv/a")]


def test_prune_removes_series_that_left_the_export(tmp_path, db):
    _write(tmp_path, "cdc", "g", ["cdc/a", "cdc/b"])
    L.load(tmp_path, "cdc", db_url=db)
    _write(tmp_path, "cdc", "g", ["cdc/a"])          # b is gone from the export
    assert L.load(tmp_path, "cdc", db_url=db) == {"written": 1, "pruned": 1}
    assert _rows(db) == [("cdc", "cdc/a")]


def test_prune_can_be_turned_off(tmp_path, db):
    _write(tmp_path, "cdc", "g", ["cdc/a", "cdc/b"])
    L.load(tmp_path, "cdc", db_url=db)
    _write(tmp_path, "cdc", "g", ["cdc/a"])
    assert L.load(tmp_path, "cdc", db_url=db, prune=False)["pruned"] == 0
    assert len(_rows(db)) == 2


def test_an_empty_directory_raises_rather_than_pruning_everything(tmp_path, db):
    """Otherwise a mistyped path silently empties the table."""
    _write(tmp_path, "cdc", "g", ["cdc/a"])
    L.load(tmp_path, "cdc", db_url=db)
    with pytest.raises(FileNotFoundError, match="cdc_series_"):
        L.load(tmp_path / "empty", "cdc", db_url=db)
    assert _rows(db) == [("cdc", "cdc/a")]


def test_upsert_preserves_identity(tmp_path, db):
    _write(tmp_path, "cdc", "g", ["cdc/a"])
    L.load(tmp_path, "cdc", db_url=db)
    engine = sa.create_engine(db)
    with engine.begin() as c:
        before = c.execute(sa.text("SELECT catalog_id FROM series_catalog")).scalar()
    L.load(tmp_path, "cdc", db_url=db)
    with engine.begin() as c:
        after = c.execute(sa.text("SELECT catalog_id FROM series_catalog")).scalar()
    engine.dispose()
    assert before == after
