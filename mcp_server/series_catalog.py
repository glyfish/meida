"""Read-only accessor for meida's ``series_catalog`` table.

The discovery counterpart to :mod:`timeseries_source`. That one answers "give
me this stored series"; this one answers "which series exist, and what fetches
them" -- across both routes, because a catalog row carries a ``retrieval``
block naming its tool.

Search is by exact metadata, not by similarity. Descriptions are generated per
*bucket* of series that differ only by facet value, so 1,014 ``alcohol_binge``
series share four description strings: free-text ranking cannot separate them,
and facet filtering is the only thing that can. Semantic search over the
descriptions is yada's document store's job; this is the exact-match index
underneath it.

Follows the same shape as ``TimeSeriesSourceClient``: an injectable ``engine``
for tests, lazy reflection, and blocking SQLAlchemy calls pushed to a thread so
the async tool handlers are not blocked.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import sqlalchemy as sa

from lib.env import get_meida_db_url

from .series_catalog_models import CatalogEntry

TABLE_NAME = "series_catalog"

#: Cap on rows one search returns. The table holds ~2,700 entries and a
#: facetless query would otherwise hand an entire catalog to a model's context.
MAX_LIMIT = 200


class SeriesCatalogError(RuntimeError):
    """Raised when a catalog lookup cannot be satisfied."""


class SeriesCatalogClient:
    """Read-only accessor for the series catalog."""

    def __init__(
        self,
        *,
        db_url: Optional[str] = None,
        engine: Optional[sa.Engine] = None,
        timeout: float = 30.0,
    ) -> None:
        self.db_url = db_url or get_meida_db_url()
        self._engine = engine or sa.create_engine(
            self.db_url, connect_args={"connect_timeout": int(timeout)}
        )
        # Don't dispose an engine the caller handed us -- they may still be using it.
        self._owns_engine = engine is None
        self._table: Optional[sa.Table] = None

    async def __aenter__(self) -> "SeriesCatalogClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_engine:
            await asyncio.to_thread(self._engine.dispose)

    def _reflect(self) -> sa.Table:
        """Reflect the table once, lazily, so constructing a client needs no DB."""
        if self._table is None:
            self._table = sa.Table(TABLE_NAME, sa.MetaData(), autoload_with=self._engine)
        return self._table

    @staticmethod
    def _entry(row: Any) -> CatalogEntry:
        return CatalogEntry(
            source=row.source,
            series_id=row.series_id,
            dataset_id=row.dataset_id,
            concept=row.concept,
            title=row.title,
            description=row.description,
            units=row.units,
            frequency=row.frequency,
            provisional=row.provisional,
            is_active=row.is_active,
            facets=row.facets or {},
            retrieval=row.retrieval or {},
            observation_start=row.observation_start,
            observation_end=row.observation_end,
        )

    async def search(
        self,
        *,
        source: Optional[str] = None,
        dataset_id: Optional[str] = None,
        concept: Optional[str] = None,
        facets: Optional[dict[str, Any]] = None,
        active_only: bool = False,
        limit: int = 50,
    ) -> tuple[list[CatalogEntry], int]:
        """Return matching entries and the total number that matched.

        The total is computed before the limit so a caller can tell a narrow
        result from a truncated one -- the difference between "three series
        exist" and "the first three of nine hundred".
        """
        limit = max(1, min(int(limit), MAX_LIMIT))

        def _run() -> tuple[list[CatalogEntry], int]:
            table = self._reflect()
            clauses = []
            if source:
                clauses.append(table.c.source == source)
            if dataset_id:
                clauses.append(table.c.dataset_id == dataset_id)
            if concept:
                clauses.append(table.c.concept == concept)
            if active_only:
                clauses.append(table.c.is_active.is_(True))
            if facets:
                # JSONB containment, which is what idx_sc_facets (GIN) serves.
                clauses.append(table.c.facets.contains(facets))
            where = sa.and_(*clauses) if clauses else sa.true()

            with self._engine.connect() as conn:
                total = conn.execute(
                    sa.select(sa.func.count()).select_from(table).where(where)
                ).scalar_one()
                rows = conn.execute(
                    sa.select(table).where(where)
                    .order_by(table.c.series_id).limit(limit)
                ).fetchall()
            return [self._entry(r) for r in rows], int(total)

        return await asyncio.to_thread(_run)

    async def get(self, series_id: str, source: str = "cdc") -> CatalogEntry:
        """Fetch one entry by id, raising with the id when it is not there."""

        def _run() -> CatalogEntry:
            table = self._reflect()
            with self._engine.connect() as conn:
                row = conn.execute(
                    sa.select(table).where(
                        table.c.source == source, table.c.series_id == series_id
                    )
                ).fetchone()
            if row is None:
                raise SeriesCatalogError(f"no catalog entry {source}:{series_id}")
            return self._entry(row)

        return await asyncio.to_thread(_run)

    async def concepts(self, source: Optional[str] = None) -> list[dict[str, Any]]:
        """Concepts with series counts -- the coarse map to search within."""

        def _run() -> list[dict[str, Any]]:
            table = self._reflect()
            stmt = sa.select(
                table.c.concept, table.c.dataset_id, sa.func.count().label("n")
            ).where(table.c.concept.isnot(None))
            if source:
                stmt = stmt.where(table.c.source == source)
            stmt = stmt.group_by(table.c.concept, table.c.dataset_id).order_by(
                sa.desc("n")
            )
            with self._engine.connect() as conn:
                rows = conn.execute(stmt).fetchall()
            return [
                {"concept": r.concept, "dataset_id": r.dataset_id, "series_count": r.n}
                for r in rows
            ]

        return await asyncio.to_thread(_run)
