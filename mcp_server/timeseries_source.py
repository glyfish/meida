"""Queries over meida's time-series source database.

Two CDC sources cannot be fetched per request: **WONDER** is throttled to ~1
query per 2 minutes behind an Akamai bot filter, and **NVSR** is annual Excel
downloads with no programmatic URL discovery. meida pulls them once into
``time_series_source`` and serves from there.

This lives in meida rather than navi deliberately. navi's clients speak to
**external providers** over HTTP; this database is meida's own, alongside the
schema and the migrations, so the SQL belongs here and navi stays free of a
database dependency. Consumers still reach the data uniformly -- through the
MCP tools in :mod:`mcp_server.server`, exactly as they reach FRED.

Constructor mirrors navi's client shape so the two read alike, with one
substitution: where an HTTP client takes ``client=`` (an ``httpx.AsyncClient``),
this takes ``engine=`` (a SQLAlchemy engine). That parameter is what keeps the
tests hermetic -- pass a SQLite in-memory engine and no database is required.

**Expiry never withholds a row.** ``expires_at`` here means "due for an
update", not "too old to serve": a refresh has to go re-run a throttled WONDER
pull or look for a new NVSR volume, and annual data three weeks late is fine
where a missing series is not. Reads flag staleness and return the data.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

import sqlalchemy as sa

from environment import get_meida_db_url

from .timeseries_source_models import Observation, TimeSeriesRecord, TimeSeriesRef

TABLE_NAME = "time_series_source"


class TimeSeriesSourceError(RuntimeError):
    """Raised when the time-series source database cannot serve a request."""


def _observation_count(metadata: Any, observations: Sequence[Any]) -> int:
    """Prefer the stored count, fall back to the payload length."""
    if isinstance(metadata, dict):
        stored = metadata.get("observation_count")
        if isinstance(stored, int):
            return stored
    return len(observations)


def _payload(observations: Any) -> list[dict]:
    """Unwrap the observations column.

    Stored either as the bare list or wrapped as ``{"observations": [...]}`` --
    the latter matching yada's cache payload. Accept both so a row copied
    verbatim from either side round-trips.
    """
    if isinstance(observations, dict):
        observations = observations.get("observations", [])
    return list(observations) if isinstance(observations, list) else []


class TimeSeriesSourceClient:
    """Read-only accessor for meida's ``time_series_source`` table."""

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

    async def __aenter__(self) -> "TimeSeriesSourceClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Dispose the engine, if this client created it."""
        if self._owns_engine:
            await asyncio.to_thread(self._engine.dispose)

    def _reflect(self) -> sa.Table:
        """Reflect the table once, lazily.

        Reflection rather than a declared model keeps navi free of a schema
        definition that meida's migrations own.
        """
        if self._table is None:
            try:
                self._table = sa.Table(TABLE_NAME, sa.MetaData(), autoload_with=self._engine)
            except sa.exc.SQLAlchemyError as exc:
                raise TimeSeriesSourceError(
                    f"cannot reflect {TABLE_NAME!r}: {exc}"
                ) from exc
        return self._table

    @staticmethod
    def _is_stale(expires_at: Any) -> bool:
        if not isinstance(expires_at, datetime):
            return False
        # Rows written through SQLite in tests come back naive; treat those as UTC.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at < datetime.now(tz=timezone.utc)

    def _ref_fields(self, row: Any) -> dict:
        observations = _payload(row.observations)
        return {
            "source": row.source,
            "native_id": row.native_id,
            "title": row.title,
            "frequency": row.frequency,
            "units": row.units,
            "observation_start": row.observation_start,
            "observation_end": row.observation_end,
            "observation_count": _observation_count(row.metadata, observations),
            "expires_at": row.expires_at,
            "stale": self._is_stale(row.expires_at),
        }

    def _select(self, columns: Optional[list] = None) -> sa.Select:
        table = self._reflect()
        return sa.select(*(columns or [table]))

    async def get_series(
        self, source: str, native_id: str, frequency: Optional[str] = None
    ) -> TimeSeriesRecord:
        """Fetch one series in full.

        Raises ``TimeSeriesSourceError`` when no row matches, or when
        ``frequency`` is omitted and the identifier is ambiguous.
        """
        def _run() -> TimeSeriesRecord:
            table = self._reflect()
            stmt = sa.select(table).where(
                table.c.source == source, table.c.native_id == native_id
            )
            if frequency is not None:
                stmt = stmt.where(table.c.frequency == frequency)
            with self._engine.connect() as conn:
                rows = conn.execute(stmt).all()

            if not rows:
                raise TimeSeriesSourceError(f"no series {source}:{native_id}")
            if len(rows) > 1:
                found = ", ".join(sorted(r.frequency for r in rows))
                raise TimeSeriesSourceError(
                    f"{source}:{native_id} matches {len(rows)} rows "
                    f"({found}) -- pass frequency to disambiguate"
                )

            row = rows[0]
            return TimeSeriesRecord(
                **self._ref_fields(row),
                metadata=row.metadata if isinstance(row.metadata, dict) else {},
                observations=[Observation(**o) for o in _payload(row.observations)],
            )

        return await asyncio.to_thread(_run)

    async def list_series(self, source: Optional[str] = None) -> list[TimeSeriesRef]:
        """List series without their observations, ordered by source then id.

        Deliberately excludes the ``observations`` column -- it dominates row
        size, and a listing never needs it.
        """
        def _run() -> list[TimeSeriesRef]:
            table = self._reflect()
            stmt = sa.select(
                table.c.source, table.c.native_id, table.c.title, table.c.frequency,
                table.c.units, table.c.metadata, table.c.observation_start,
                table.c.observation_end, table.c.expires_at,
            ).order_by(table.c.source, table.c.native_id)
            if source is not None:
                stmt = stmt.where(table.c.source == source)
            with self._engine.connect() as conn:
                rows = conn.execute(stmt).all()
            return [
                TimeSeriesRef(
                    source=r.source, native_id=r.native_id, title=r.title,
                    frequency=r.frequency, units=r.units,
                    observation_start=r.observation_start,
                    observation_end=r.observation_end,
                    observation_count=_observation_count(r.metadata, []),
                    expires_at=r.expires_at, stale=self._is_stale(r.expires_at),
                )
                for r in rows
            ]

        return await asyncio.to_thread(_run)

    async def list_stale(self, source: Optional[str] = None) -> list[TimeSeriesRef]:
        """List series past ``expires_at`` -- those due for a refresh.

        This is the query that replaces a polling process: ask what needs
        updating when you want to know, rather than running a checker.
        """
        return [ref for ref in await self.list_series(source) if ref.stale]
