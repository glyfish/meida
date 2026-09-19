"""Tests for the shared catalog loader (``db_import/load_catalog.py``).

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

from db_import import load_catalog as L


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


# --- date coercion ------------------------------------------------------------
#
# The exports carry three shapes, and ``date.fromisoformat`` accepts only one of
# them. Handling just ``YYYY`` and full ISO left 442 rows -- 424 monthly, 18
# quarterly -- with a null span and no error to say so.

@pytest.mark.parametrize("text,expected", [
    ("2019", "2019-01-01"),          # bare year, the common case
    ("1900", "1900-01-01"),
    ("2015-01", "2015-01-01"),       # fromisoformat rejects YYYY-MM outright
    ("2015-12", "2015-12-01"),
    ("2023 Q1", "2023-01-01"),       # quarters snap to the quarter's first month
    ("2023 Q2", "2023-04-01"),
    ("2023 Q3", "2023-07-01"),
    ("2023 Q4", "2023-10-01"),
    ("2023 q4", "2023-10-01"),       # BIS lowercases it in places
    ("2023Q4", "2023-10-01"),        # and sometimes omits the space
    ("1900-05-17", "1900-05-17"),    # a full date still passes through
])
def test_every_published_bound_shape_becomes_a_date(text, expected):
    assert L._as_date(text).isoformat() == expected


@pytest.mark.parametrize("text", ["", None, "junk", "2015-13", "2023 Q9", "20xx"])
def test_unusable_bounds_are_none_rather_than_a_guess(text):
    assert L._as_date(text) is None


def test_monthly_and_quarterly_bounds_survive_the_load(tmp_path, db):
    """The regression itself: these shapes used to land with a null span."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "cdc_series_g.yaml").write_text(yaml.safe_dump({
        "group": "g",
        "series": [
            {"series_id": "cdc/q", "title": "q", "facets": {},
             "observation_start": "2023 Q1", "observation_end": "2023 Q4"},
            {"series_id": "cdc/m", "title": "m", "facets": {},
             "observation_start": "2015-01", "observation_end": "2015-12"},
            {"series_id": "cdc/y", "title": "y", "facets": {},
             "observation_start": "2019", "observation_end": "2021"},
        ],
    }))
    L.load(tmp_path, "cdc", db_url=db)

    engine = sa.create_engine(db)
    with engine.begin() as conn:
        spans = {r[0]: (str(r[1]), str(r[2])) for r in conn.execute(sa.text(
            "SELECT series_id, observation_start, observation_end FROM series_catalog"))}
    engine.dispose()

    assert spans["cdc/q"] == ("2023-01-01", "2023-10-01")
    assert spans["cdc/m"] == ("2015-01-01", "2015-12-01")
    assert spans["cdc/y"] == ("2019-01-01", "2021-01-01")


# --- description loss guard ---------------------------------------------------
#
# A fresh export has no descriptions; they are merged in from a sidecar. The
# upsert replaces the column wholesale, so loading an unmerged export once
# blanked every CDC description with no error. The loader now refuses.

def _write_described(dir_: Path, series: dict[str, str | None]) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "cdc_series_g.yaml").write_text(yaml.safe_dump({
        "group": "g",
        "series": [{"series_id": s, "title": s, "facets": {},
                    **({"description": d} if d else {})} for s, d in series.items()],
    }))


def _descriptions(url: str) -> dict[str, str | None]:
    engine = sa.create_engine(url)
    with engine.begin() as c:
        out = {r[0]: r[1] for r in c.execute(sa.text(
            "SELECT series_id, description FROM series_catalog"))}
    engine.dispose()
    return out


def test_an_unmerged_export_cannot_erase_stored_descriptions(tmp_path, db):
    _write_described(tmp_path, {"cdc/a": "Alpha.", "cdc/b": "Beta."})
    L.load(tmp_path, "cdc", db_url=db)

    _write_described(tmp_path, {"cdc/a": None, "cdc/b": None})   # the fresh export
    with pytest.raises(L.DescriptionLossError, match="would erase 2 stored"):
        L.load(tmp_path, "cdc", db_url=db)
    assert _descriptions(db) == {"cdc/a": "Alpha.", "cdc/b": "Beta."}   # nothing written


def test_losing_even_one_description_is_refused(tmp_path, db):
    _write_described(tmp_path, {"cdc/a": "Alpha.", "cdc/b": "Beta."})
    L.load(tmp_path, "cdc", db_url=db)
    _write_described(tmp_path, {"cdc/a": "Alpha.", "cdc/b": None})
    with pytest.raises(L.DescriptionLossError, match="would erase 1 stored"):
        L.load(tmp_path, "cdc", db_url=db)


def test_the_first_load_needs_no_descriptions(tmp_path, db):
    """Nothing stored yet, so there is nothing to lose."""
    _write_described(tmp_path, {"cdc/a": None})
    assert L.load(tmp_path, "cdc", db_url=db)["written"] == 1


def test_replacing_a_description_with_another_is_allowed(tmp_path, db):
    _write_described(tmp_path, {"cdc/a": "Old."})
    L.load(tmp_path, "cdc", db_url=db)
    _write_described(tmp_path, {"cdc/a": "New."})
    L.load(tmp_path, "cdc", db_url=db)
    assert _descriptions(db) == {"cdc/a": "New."}


def test_clearing_descriptions_on_purpose_is_possible(tmp_path, db):
    _write_described(tmp_path, {"cdc/a": "Alpha."})
    L.load(tmp_path, "cdc", db_url=db)
    _write_described(tmp_path, {"cdc/a": None})
    L.load(tmp_path, "cdc", db_url=db, allow_description_loss=True)
    assert _descriptions(db) == {"cdc/a": None}


# --- batching -----------------------------------------------------------------
#
# Postgres binds at most 65,535 parameters per statement. Clio-Infra's 11,044
# series would not fit one INSERT, and the prune's NOT IN bound one parameter
# per series too. Shrinking BATCH to 2 makes every boundary reachable with a
# handful of rows.

def test_a_catalog_larger_than_one_batch_is_written_whole(tmp_path, db, monkeypatch):
    monkeypatch.setattr(L, "BATCH", 2)
    _write(tmp_path, "cdc", "g", [f"cdc/{i}" for i in range(5)])
    assert L.load(tmp_path, "cdc", db_url=db)["written"] == 5
    assert len(_rows(db)) == 5


def test_the_prune_removes_series_across_batches(tmp_path, db, monkeypatch):
    monkeypatch.setattr(L, "BATCH", 2)
    _write(tmp_path, "cdc", "g", [f"cdc/{i}" for i in range(7)])
    L.load(tmp_path, "cdc", db_url=db)
    _write(tmp_path, "cdc", "g", ["cdc/0", "cdc/1"])
    assert L.load(tmp_path, "cdc", db_url=db)["pruned"] == 5
    assert _rows(db) == [("cdc", "cdc/0"), ("cdc", "cdc/1")]
