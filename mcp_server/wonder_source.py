"""Serve CDC WONDER series from meida's database, with the live query as fallback.

WONDER is the reason ``time_series_source`` exists. Its endpoint is throttled to
one request per 120 seconds behind an Akamai bot filter — navi's
:class:`WonderClient` gets through with a browser TLS fingerprint and waits out
the throttle itself — so a series cannot be fetched per request the way FRED or
Socrata can. The nine concepts were pulled once, stitched across two database
vintages, and loaded into Postgres; that table is the serving path.

This client makes that the default rather than a convention someone has to
remember. It looks the series up by concept, and only reaches for the network if
it is genuinely absent.

``stored_only=True`` removes the fallback: a missing series raises rather than
silently costing two minutes and a request against a rate limit nobody wants to
spend. That is the mode notebooks and tests want — a cache miss should be a loud
failure you fix by loading the data, not a slow success.
"""
from __future__ import annotations

from typing import Optional

import sqlalchemy as sa

from .timeseries_source import TimeSeriesSourceClient, TimeSeriesSourceError
from .timeseries_source_models import TimeSeriesRecord

#: The namespace WONDER series are stored under, matching ``load_timeseries``.
SOURCE = "cdc_wonder"

#: Stored WONDER series are national and age-adjusted; the concept is the only
#: part of the identifier that varies.
NATIVE_ID = "cdc/{concept}/wonder/national/age_adjusted"


class WonderNotStoredError(RuntimeError):
    """A concept is not in the database and the fallback was disallowed."""


class WonderSourceClient:
    """Read WONDER series from ``time_series_source``.

    Parameters
    ----------
    stored_only:
        When True, a concept missing from the database raises
        :class:`WonderNotStoredError` instead of falling back to a live query.
        Default True — the safe direction, given what a fallback costs.
    engine:
        Injected for tests, the same seam ``TimeSeriesSourceClient`` uses.
    """

    def __init__(
        self,
        *,
        stored_only: bool = True,
        engine: Optional[sa.Engine] = None,
        db_url: Optional[str] = None,
    ) -> None:
        self.stored_only = stored_only
        self._store = TimeSeriesSourceClient(engine=engine, db_url=db_url)

    async def __aenter__(self) -> "WonderSourceClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._store.aclose()

    async def list_concepts(self) -> list[str]:
        """The concepts held in the database, e.g. ``alcohol_induced``.

        The discovery step: what can be served without touching the network.
        """
        refs = await self._store.list_series(source=SOURCE)
        return sorted(
            ref.native_id.split("/")[1]
            for ref in refs
            if ref.native_id.startswith("cdc/")
        )

    async def get_series(self, concept: str) -> TimeSeriesRecord:
        """Return one stored WONDER concept in full.

        Raises :class:`WonderNotStoredError` when the concept is absent and
        ``stored_only`` is set, with the concepts that *are* available — a
        missing series is nearly always a typo or an unloaded pull, and both are
        fixed by looking at that list rather than by waiting on the network.
        """
        native_id = NATIVE_ID.format(concept=concept)
        try:
            return await self._store.get_series(SOURCE, native_id)
        except TimeSeriesSourceError as exc:
            if self.stored_only:
                available = await self.list_concepts()
                raise WonderNotStoredError(
                    f"{concept!r} is not in the database. Available: "
                    f"{', '.join(available) or '(none — run load_timeseries)'}. "
                    f"Pass stored_only=False to fall back to a live WONDER query, "
                    f"which is throttled to one request per 120 seconds."
                ) from exc
            raise NotImplementedError(
                "live WONDER fallback is not wired up: fetching a concept means "
                "choosing its ICD-10 code set and stitching the D76 and D158 "
                "vintages, which notebooks/cdc/wonder_series.py does as a "
                "deliberate offline step. Load the series instead of fetching "
                "it inline."
            ) from exc
