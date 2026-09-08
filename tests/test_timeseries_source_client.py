"""Tests for meida's ``TimeSeriesSourceClient``.

The client reads a SQL table rather than an HTTP API, so where the other client
tests inject an ``httpx.MockTransport``, these inject a **SQLite in-memory
engine** via the same ``engine=`` seam. Real SQL runs; no Postgres, no network.

SQLite stands in adequately because the client only does equality lookups and
ordering. It could not stand in for JSONB containment (``@>``) -- one reason
filtering belongs in the document store rather than this table.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from mcp_server.timeseries_source import TimeSeriesSourceClient, TimeSeriesSourceError

PAST = datetime.now(tz=timezone.utc) - timedelta(days=1)
FUTURE = datetime.now(tz=timezone.utc) + timedelta(days=365)

ALCOHOL_OBS = [
    {"date": "1999-01-01", "value": "7.1", "deaths": 19469, "population": 279040168,
     "crude_rate": "7.0"},
    {"date": "2000-01-01", "value": "7.0", "deaths": 19643, "population": 281421906,
     "crude_rate": "7.0"},
]


def _make_engine() -> sa.Engine:
    """A SQLite engine holding a table shaped like ``time_series_source``.

    Mirrors the migration, with the Postgres-only types swapped for SQLite
    equivalents (JSONB -> JSON, UUID -> TEXT). Nothing the client does depends
    on the difference.
    """
    # check_same_thread=False because the client runs its SQL in
    # ``asyncio.to_thread``; SQLite forbids cross-thread connection reuse and
    # Postgres does not. StaticPool keeps every thread on the one in-memory db.
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


def _insert(engine: sa.Engine, **overrides) -> None:
    row = {
        "source_id": overrides.get("source_id", "id-1"),
        "source": "cdc_wonder",
        "native_id": "cdc/alcohol_induced/wonder/national/age_adjusted",
        "title": "Alcohol-induced deaths, age-adjusted rate, United States",
        "frequency": "Annual",
        "units": "deaths per 100,000",
        "metadata": {"observation_count": 2, "units": "deaths per 100,000"},
        "observations": ALCOHOL_OBS,
        "expires_at": FUTURE,
        "ttl_days": 365,
        "observation_start": date(1999, 1, 1),
        "observation_end": date(2000, 1, 1),
    }
    row.update(overrides)
    table = sa.Table("time_series_source", sa.MetaData(), autoload_with=engine)
    with engine.begin() as conn:
        conn.execute(table.insert().values(**row))


@pytest.fixture
def engine() -> sa.Engine:
    eng = _make_engine()
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine: sa.Engine) -> TimeSeriesSourceClient:
    return TimeSeriesSourceClient(engine=engine)


async def test_get_series_returns_observations_in_order(client, engine):
    _insert(engine)
    rec = await client.get_series("cdc_wonder", "cdc/alcohol_induced/wonder/national/age_adjusted")
    assert rec.row_count == 2
    assert [o.date for o in rec.observations] == ["1999-01-01", "2000-01-01"]
    assert rec.observations[0].value == "7.1"          # value stays a STRING
    assert rec.units == "deaths per 100,000"


async def test_extra_observation_keys_are_preserved(client, engine):
    """WONDER carries deaths/population/crude_rate beside the rate."""
    _insert(engine)
    rec = await client.get_series("cdc_wonder", "cdc/alcohol_induced/wonder/national/age_adjusted")
    first = rec.observations[0].model_dump()
    assert first["deaths"] == 19469
    assert first["population"] == 279040168
    assert first["crude_rate"] == "7.0"


async def test_observations_accepts_wrapped_payload(client, engine):
    """A row copied verbatim from yada's cache wraps the list in a dict."""
    _insert(engine, observations={"observations": ALCOHOL_OBS})
    rec = await client.get_series("cdc_wonder", "cdc/alcohol_induced/wonder/national/age_adjusted")
    assert rec.row_count == 2


async def test_expired_row_is_served_and_flagged(client, engine):
    """Expiry means 'due for an update', never 'withhold'."""
    _insert(engine, expires_at=PAST)
    rec = await client.get_series("cdc_wonder", "cdc/alcohol_induced/wonder/national/age_adjusted")
    assert rec.stale is True
    assert rec.row_count == 2          # data still returned


async def test_unexpired_row_is_not_stale(client, engine):
    _insert(engine)
    rec = await client.get_series("cdc_wonder", "cdc/alcohol_induced/wonder/national/age_adjusted")
    assert rec.stale is False


async def test_missing_series_raises(client, engine):
    _insert(engine)
    with pytest.raises(TimeSeriesSourceError, match="no series"):
        await client.get_series("cdc_wonder", "does/not/exist")


async def test_ambiguous_identifier_raises_and_names_frequencies(client, engine):
    _insert(engine, source_id="a", frequency="Annual")
    _insert(engine, source_id="b", frequency="Monthly")
    with pytest.raises(TimeSeriesSourceError, match="disambiguate"):
        await client.get_series("cdc_wonder", "cdc/alcohol_induced/wonder/national/age_adjusted")


async def test_frequency_disambiguates(client, engine):
    _insert(engine, source_id="a", frequency="Annual")
    _insert(engine, source_id="b", frequency="Monthly")
    rec = await client.get_series(
        "cdc_wonder", "cdc/alcohol_induced/wonder/national/age_adjusted", frequency="Monthly"
    )
    assert rec.frequency == "Monthly"


async def test_list_series_orders_and_omits_observations(client, engine):
    _insert(engine, source_id="a", native_id="z/second")
    _insert(engine, source_id="b", native_id="a/first")
    _insert(engine, source_id="c", source="cdc_nvsr", native_id="m/nvsr")
    refs = await client.list_series()
    assert [r.native_id for r in refs] == ["m/nvsr", "a/first", "z/second"]  # source, then id
    assert all(not hasattr(r, "observations") for r in refs)
    assert refs[0].observation_count == 2      # read from stored metadata


async def test_list_series_filters_by_source(client, engine):
    _insert(engine, source_id="a")
    _insert(engine, source_id="b", source="cdc_nvsr", native_id="m/nvsr")
    assert [r.source for r in await client.list_series(source="cdc_nvsr")] == ["cdc_nvsr"]


async def test_list_stale_returns_only_expired(client, engine):
    _insert(engine, source_id="fresh", native_id="a/fresh", expires_at=FUTURE)
    _insert(engine, source_id="due", native_id="b/due", expires_at=PAST)
    assert [r.native_id for r in await client.list_stale()] == ["b/due"]


async def test_injected_engine_is_not_disposed(engine):
    """``_owns_engine`` -- closing the client must not close a caller's engine."""
    async with TimeSeriesSourceClient(engine=engine) as c:
        _insert(engine)
        assert (await c.list_series())[0].source == "cdc_wonder"
    with engine.connect() as conn:                      # still usable after aclose
        assert conn.execute(sa.text("select count(*) from time_series_source")).scalar() == 1


async def test_missing_table_raises_source_error():
    """A bare database surfaces as TimeSeriesSourceError, not a raw SQLAlchemy error."""
    empty = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool,
                             connect_args={"check_same_thread": False})
    client = TimeSeriesSourceClient(engine=empty)
    with pytest.raises(TimeSeriesSourceError, match="cannot reflect"):
        await client.list_series()
