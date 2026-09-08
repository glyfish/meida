"""Tests for ``WonderSourceClient`` — the database-backed WONDER reader.

Same seam as the other database client tests: a SQLite in-memory engine injected
through ``engine=``, so real SQL runs with no Postgres and no network.

The behaviour worth pinning is the flag. A live WONDER query costs a throttled
request against a bot-filtered endpoint, so a cache miss must fail loudly rather
than quietly reaching for the network — the failure is nearly always a typo or
an unloaded pull, and both are fixed offline.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from mcp_server.wonder_source import (
    NATIVE_ID, SOURCE, WonderNotStoredError, WonderSourceClient,
)

FUTURE = datetime.now(tz=timezone.utc) + timedelta(days=365)


def _make_engine() -> sa.Engine:
    engine = sa.create_engine(
        "sqlite://",
        poolclass=sa.pool.StaticPool,
        connect_args={"check_same_thread": False},
    )
    md = sa.MetaData()
    sa.Table(
        "time_series_source", md,
        sa.Column("source_id", sa.Text, primary_key=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("native_id", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("frequency", sa.Text, nullable=False),
        sa.Column("units", sa.Text),
        sa.Column("metadata", sa.JSON, nullable=False),
        sa.Column("observations", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ttl_days", sa.Integer),
        sa.Column("observation_start", sa.Date),
        sa.Column("observation_end", sa.Date),
        sa.UniqueConstraint("source", "native_id", "frequency",
                            name="uq_tss_source_native_frequency"),
    )
    md.create_all(engine)
    return engine


def _insert(engine: sa.Engine, concept: str) -> None:
    row = {
        "source_id": f"id-{concept}",
        "source": SOURCE,
        "native_id": NATIVE_ID.format(concept=concept),
        "title": f"{concept} deaths, age-adjusted rate, United States",
        "frequency": "Annual",
        "units": "deaths per 100,000",
        "metadata": {"observation_count": 2},
        "observations": [{"date": "1999-01-01", "value": "7.1"},
                         {"date": "2000-01-01", "value": "7.0"}],
        "expires_at": FUTURE,
        "ttl_days": 365,
        "observation_start": date(1999, 1, 1),
        "observation_end": date(2000, 1, 1),
    }
    table = sa.Table("time_series_source", sa.MetaData(), autoload_with=engine)
    with engine.begin() as conn:
        conn.execute(table.insert().values(**row))


@pytest.fixture
def engine() -> sa.Engine:
    e = _make_engine()
    for concept in ("alcohol_induced", "suicide", "firearm"):
        _insert(e, concept)
    return e


async def test_get_series_reads_the_stored_row(engine):
    async with WonderSourceClient(engine=engine) as wonder:
        record = await wonder.get_series("alcohol_induced")

    assert record.units == "deaths per 100,000"
    assert [o.value for o in record.observations] == ["7.1", "7.0"]


async def test_concept_maps_to_the_stored_identifier(engine):
    """The concept is the only varying part -- stored series are all national
    and age-adjusted, so the caller should not have to spell the rest."""
    async with WonderSourceClient(engine=engine) as wonder:
        record = await wonder.get_series("suicide")

    assert record.native_id == "cdc/suicide/wonder/national/age_adjusted"


async def test_list_concepts_is_the_discovery_step(engine):
    async with WonderSourceClient(engine=engine) as wonder:
        assert await wonder.list_concepts() == [
            "alcohol_induced", "firearm", "suicide"
        ]


async def test_a_miss_fails_instead_of_reaching_for_the_network(engine):
    """The point of the flag: a live query is throttled to one per 120 seconds
    behind a bot filter, so a miss must not quietly cost one."""
    async with WonderSourceClient(engine=engine, stored_only=True) as wonder:
        with pytest.raises(WonderNotStoredError) as excinfo:
            await wonder.get_series("not_a_concept")

    message = str(excinfo.value)
    assert "not_a_concept" in message
    # the error carries the fix: what IS available
    assert "alcohol_induced" in message and "suicide" in message


async def test_stored_only_is_the_default(engine):
    """Defaulting to the fallback would make the expensive path the easy one."""
    async with WonderSourceClient(engine=engine) as wonder:
        assert wonder.stored_only is True
        with pytest.raises(WonderNotStoredError):
            await wonder.get_series("absent")


async def test_disabling_the_flag_does_not_silently_fetch(engine):
    """stored_only=False still refuses, but for a different reason: fetching a
    concept means choosing ICD-10 codes and stitching two database vintages,
    which is a deliberate offline step, not something to do inline."""
    async with WonderSourceClient(engine=engine, stored_only=False) as wonder:
        with pytest.raises(NotImplementedError, match="wonder_series"):
            await wonder.get_series("absent")


async def test_empty_database_says_how_to_fix_it(engine):
    empty = _make_engine()
    async with WonderSourceClient(engine=empty) as wonder:
        with pytest.raises(WonderNotStoredError, match="load_timeseries"):
            await wonder.get_series("alcohol_induced")
