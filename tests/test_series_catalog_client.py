"""Tests for meida's ``SeriesCatalogClient``.

Same seam as ``test_timeseries_source_client``: a SQLite in-memory engine
injected through ``engine=``, so real SQL runs with no Postgres and no network.

SQLite covers the equality filters, ordering, counting and limiting. It cannot
cover JSONB containment (``@>``), which is the one thing here that is genuinely
Postgres-only -- that path is exercised against the live database in
``test_series_catalog_facets``, skipped when no database is reachable.
"""
from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa

from mcp_server.series_catalog import SeriesCatalogClient, SeriesCatalogError


def _make_engine() -> sa.Engine:
    """A SQLite engine holding a table shaped like ``series_catalog``.

    Mirrors the migration with the Postgres-only types swapped (JSONB -> JSON,
    UUID -> TEXT). check_same_thread=False because the client runs its SQL in
    ``asyncio.to_thread``.
    """
    engine = sa.create_engine(
        "sqlite://",
        poolclass=sa.pool.StaticPool,
        connect_args={"check_same_thread": False},
    )
    md = sa.MetaData()
    sa.Table(
        "series_catalog", md,
        sa.Column("catalog_id", sa.Text, primary_key=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("series_id", sa.Text, nullable=False),
        sa.Column("dataset_id", sa.Text),
        sa.Column("concept", sa.Text),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("units", sa.Text),
        sa.Column("frequency", sa.Text),
        sa.Column("provisional", sa.Boolean, nullable=False),
        sa.Column("is_active", sa.Boolean),
        sa.Column("facets", sa.JSON, nullable=False),
        sa.Column("retrieval", sa.JSON, nullable=False),
        sa.Column("observation_start", sa.Date),
        sa.Column("observation_end", sa.Date),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source", "series_id", name="uq_sc_source_series"),
    )
    md.create_all(engine)
    return engine


def _insert(engine: sa.Engine, **overrides) -> None:
    row = {
        "catalog_id": overrides.get("catalog_id", overrides.get("series_id", "id-1")),
        "source": "cdc",
        "series_id": "cdc/alcohol_binge/hksd-2xuw/state=tx/race=hispanic/crude",
        "dataset_id": "hksd-2xuw",
        "concept": "alcohol_binge",
        "title": "alcohol binge (state=TX, race=hispanic, crude)",
        "description": "Annual prevalence of binge drinking among adults.",
        "units": "percent",
        "frequency": "annual",
        "provisional": False,
        "is_active": True,
        "facets": {"state": "TX", "race": "hispanic", "rate_type": "crude"},
        "retrieval": {"tool": "cdc_series_data", "dataset_id": "hksd-2xuw"},
        "observation_start": date(2019, 1, 1),
        "observation_end": date(2023, 1, 1),
    }
    row.update(overrides)
    table = sa.Table("series_catalog", sa.MetaData(), autoload_with=engine)
    with engine.begin() as conn:
        conn.execute(table.insert().values(**row))


@pytest.fixture
def client() -> SeriesCatalogClient:
    return SeriesCatalogClient(engine=_make_engine())


# --- search ------------------------------------------------------------------


async def test_search_returns_entries_and_a_total(client):
    for i in range(3):
        _insert(client._engine, series_id=f"cdc/s/{i}", catalog_id=f"id-{i}")

    entries, total = await client.search()

    assert total == 3 and len(entries) == 3


async def test_total_counts_matches_before_the_limit(client):
    """The point of reporting total separately: a caller must be able to tell
    'three series exist' from 'the first three of nine hundred'."""
    for i in range(10):
        _insert(client._engine, series_id=f"cdc/s/{i:02d}", catalog_id=f"id-{i}")

    entries, total = await client.search(limit=3)

    assert total == 10 and len(entries) == 3


async def test_search_filters_by_concept_and_dataset(client):
    _insert(client._engine, series_id="cdc/a", catalog_id="a", concept="alcohol_binge")
    _insert(client._engine, series_id="cdc/b", catalog_id="b", concept="suicide",
            dataset_id="w26f-tf3h")

    entries, total = await client.search(concept="suicide")
    assert total == 1 and entries[0].concept == "suicide"

    entries, total = await client.search(dataset_id="hksd-2xuw")
    assert total == 1 and entries[0].series_id == "cdc/a"


async def test_active_only_excludes_retired_series(client):
    _insert(client._engine, series_id="cdc/live", catalog_id="1", is_active=True)
    _insert(client._engine, series_id="cdc/dead", catalog_id="2", is_active=False)
    _insert(client._engine, series_id="cdc/unknown", catalog_id="3", is_active=None)

    entries, total = await client.search(active_only=True)

    assert total == 1 and entries[0].series_id == "cdc/live"


async def test_results_are_ordered_by_series_id(client):
    for sid in ("cdc/c", "cdc/a", "cdc/b"):
        _insert(client._engine, series_id=sid, catalog_id=sid)

    entries, _ = await client.search()

    assert [e.series_id for e in entries] == ["cdc/a", "cdc/b", "cdc/c"]


async def test_limit_is_clamped_to_the_ceiling(client):
    """A facetless query must not be able to pull the whole catalog into context."""
    from mcp_server.series_catalog import MAX_LIMIT

    for i in range(5):
        _insert(client._engine, series_id=f"cdc/s/{i}", catalog_id=f"id-{i}")

    entries, _ = await client.search(limit=10_000)
    assert len(entries) <= MAX_LIMIT

    entries, _ = await client.search(limit=0)     # floors at 1 rather than returning none
    assert len(entries) == 1


# --- retrieval routing -------------------------------------------------------


async def test_entry_carries_the_tool_that_fetches_it(client):
    """The field that lets one listing serve both routes."""
    _insert(client._engine, series_id="cdc/live", catalog_id="1",
            retrieval={"tool": "cdc_series_data", "dataset_id": "hksd-2xuw"})
    _insert(client._engine, series_id="cdc/stored", catalog_id="2",
            retrieval={"tool": "timeseries_source_data", "source": "cdc_wonder",
                       "native_id": "cdc/alcohol_induced/wonder/national/age_adjusted"})

    entries, _ = await client.search()
    tools = {e.series_id: e.retrieval["tool"] for e in entries}

    assert tools == {"cdc/live": "cdc_series_data",
                     "cdc/stored": "timeseries_source_data"}


async def test_facets_round_trip_as_tool_arguments(client):
    """A catalog row's facets are the arguments cdc_series_data takes, verbatim."""
    _insert(client._engine)

    (entry,), _ = await client.search()

    assert entry.facets == {"state": "TX", "race": "hispanic", "rate_type": "crude"}


# --- get ---------------------------------------------------------------------


async def test_get_returns_one_entry(client):
    _insert(client._engine)

    entry = await client.get("cdc/alcohol_binge/hksd-2xuw/state=tx/race=hispanic/crude")

    assert entry.units == "percent" and entry.observation_end == date(2023, 1, 1)


async def test_get_names_the_missing_id(client):
    with pytest.raises(SeriesCatalogError, match="cdc/nope"):
        await client.get("cdc/nope")


# --- concepts ----------------------------------------------------------------


async def test_concepts_counts_per_concept_and_dataset(client):
    _insert(client._engine, series_id="cdc/a", catalog_id="a")
    _insert(client._engine, series_id="cdc/b", catalog_id="b")
    _insert(client._engine, series_id="cdc/c", catalog_id="c", concept="suicide",
            dataset_id="w26f-tf3h")

    concepts = await client.concepts()

    assert concepts[0] == {"concept": "alcohol_binge", "dataset_id": "hksd-2xuw",
                           "series_count": 2}
    assert {"concept": "suicide", "dataset_id": "w26f-tf3h", "series_count": 1} in concepts


async def test_a_concept_spanning_datasets_is_reported_per_dataset(client):
    """suicide lives in several datasets with different coverage and race
    vocabularies -- collapsing them would hide that they are different series."""
    _insert(client._engine, series_id="cdc/x", catalog_id="x", concept="suicide",
            dataset_id="9j2v-jamp")
    _insert(client._engine, series_id="cdc/y", catalog_id="y", concept="suicide",
            dataset_id="w26f-tf3h")

    rows = [c for c in await client.concepts() if c["concept"] == "suicide"]

    assert {r["dataset_id"] for r in rows} == {"9j2v-jamp", "w26f-tf3h"}


# --- JSONB containment (Postgres only) ---------------------------------------


@pytest.mark.asyncio
async def test_series_catalog_facets():
    """Facet filtering uses JSONB ``@>``, which SQLite cannot stand in for."""
    from environment import get_meida_db_url

    try:
        engine = sa.create_engine(get_meida_db_url())
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1 FROM series_catalog LIMIT 1"))
    except Exception as exc:                     # noqa: BLE001 -- any DB problem skips
        pytest.skip(f"meida database not reachable: {type(exc).__name__}")

    async with SeriesCatalogClient(engine=engine) as catalog:
        entries, total = await catalog.search(
            concept="alcohol_binge", facets={"state": "TX"}, limit=200
        )
        assert total > 0
        # containment, not equality: every match carries state=TX plus whatever else
        assert all(e.facets.get("state") == "TX" for e in entries)
        assert any(len(e.facets) > 1 for e in entries)

        narrower, narrower_total = await catalog.search(
            concept="alcohol_binge", facets={"state": "TX", "rate_type": "crude"},
            limit=200,
        )
        assert 0 < narrower_total <= total
        assert all(e.facets.get("rate_type") == "crude" for e in narrower)
