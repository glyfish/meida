"""Published response models for the Tiingo MCP tools.

navi's ``clients.models.tiingo`` models exist to *parse* Tiingo's wire
format, so they carry the vendor's camelCase aliases -- ``exchangeCode``,
``startDate``, ``endDate``, and on every price row ``adjOpen``, ``adjHigh``,
``adjLow``, ``adjClose``, ``adjVolume``, ``divCash``, ``splitFactor``. Pydantic
publishes an alias as the JSON Schema property name, so parsing those models
straight out of an MCP tool would leak Tiingo's naming into this API. The models
below are the *published* shape: snake_case throughout, no aliases anywhere, and
dates as ISO ``YYYY-MM-DD`` strings.

Tiingo is the one source whose observation is not a single number -- a day of
trading is OHLCV plus its split/dividend-adjusted twin -- so a price row keeps
its full body instead of collapsing to the house ``{date, value}`` pair. It
still carries a ``date`` field, in the same ISO form as every other source, so a
caller can align a price series with a FRED or BLS series without special-casing
Tiingo.

Mapping is one-way and pure: ``from_tiingo_meta`` and ``from_tiingo_price_series``
take navi models and return these, with no I/O and no network.
"""

from __future__ import annotations

from datetime import date as _date, datetime as _datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from clients.models import tiingo as navi_tiingo


__all__ = [
    "TiingoSeriesInfo",
    "TiingoPriceRow",
    "TiingoPriceSeries",
    "from_tiingo_meta",
    "from_tiingo_price",
    "from_tiingo_price_series",
]


def _iso_date(value: Any) -> Optional[str]:
    """Normalize a vendor date to an ISO ``YYYY-MM-DD`` string.

    Tiingo dates arrive in three shapes across the two endpoints: a ``datetime``
    (price rows parse ``2024-01-03T00:00:00.000Z``), a ``date`` (metadata
    coverage bounds), or -- if a payload was built by hand -- a string. Times are
    dropped: Tiingo's end-of-day feed timestamps every row at midnight UTC, so
    the time carries no information and only makes the field harder to join on.
    """
    if value is None:
        return None
    if isinstance(value, _datetime):
        return value.date().isoformat()
    if isinstance(value, _date):
        return value.isoformat()
    if not isinstance(value, str):
        # An int, float or list is not a date in any shape Tiingo sends; str()-ing
        # it would publish a date-shaped field containing something that is not one.
        return None
    text = value.strip()
    if not text:
        return None
    # ``2024-01-03T00:00:00.000Z`` / ``2024-01-03 00:00:00`` -> ``2024-01-03``.
    head = text.replace(" ", "T", 1).split("T", 1)[0]
    try:
        # Slicing alone would pass '2024-13-45' and '01/03/2024' straight through;
        # parsing is what makes the ISO promise in the field descriptions true.
        return _date.fromisoformat(head).isoformat()
    except ValueError:
        return None


class TiingoResponseModel(BaseModel):
    """Base config for the immutable, alias-free published models."""

    model_config = {"frozen": True}


class TiingoSeriesInfo(TiingoResponseModel):
    """Identity and coverage of one Tiingo ticker.

    Returned by ``tiingo_series_info``. Enough to decide whether a ticker is the
    instrument you want and whether its history covers the window you need,
    before pulling any prices.
    """

    ticker: str = Field(
        description="Tiingo's symbol for the instrument, e.g. 'AAPL'. Case-insensitive on input.",
    )
    name: str = Field(
        description="Full name of the instrument, e.g. 'Apple Inc'.",
    )
    exchange_code: Optional[str] = Field(
        default=None,
        description="Listing venue, e.g. 'NASDAQ' or 'NYSE ARCA'. Absent for some funds.",
    )
    start_date: Optional[str] = Field(
        default=None,
        description=(
            "First date with end-of-day data, ISO 'YYYY-MM-DD'. None when Tiingo "
            "publishes no coverage bound (typically a ticker with no price history)."
        ),
    )
    end_date: Optional[str] = Field(
        default=None,
        description=(
            "Most recent date with end-of-day data, ISO 'YYYY-MM-DD'. Lags the "
            "current date for delisted or thinly traded instruments."
        ),
    )
    description: Optional[str] = Field(
        default=None,
        description="Vendor prose about the instrument. Free text, often long, sometimes empty.",
    )


class TiingoPriceRow(TiingoResponseModel):
    """One trading day: raw OHLCV plus its split/dividend-adjusted twin.

    Unlike every other source in this API an observation here is not a single
    number, so the row is kept whole rather than reduced to ``{date, value}``.
    The ``date`` field is the same ISO ``YYYY-MM-DD`` string every other source
    uses, so rows still align on date across sources.

    Use the raw ``open``/``high``/``low``/``close`` to reproduce what printed on
    the tape that day; use the ``adj_*`` fields for anything comparing prices
    across time (returns, moving averages, charts), since only those are
    restated for later splits and dividends.
    """

    date: Optional[str] = Field(
        default=None,
        description=(
            "Trading day, ISO 'YYYY-MM-DD' (Tiingo's midnight-UTC timestamp is "
            "dropped). None when the vendor value was missing or not a parseable "
            "date -- the row is still published with its prices, rather than "
            "carrying a date-shaped field that is not a date."
        ),
    )
    open: float = Field(description="Opening price as traded, unadjusted.")
    high: float = Field(description="Session high as traded, unadjusted.")
    low: float = Field(description="Session low as traded, unadjusted.")
    close: float = Field(description="Closing price as traded, unadjusted.")
    volume: int = Field(description="Shares traded, unadjusted.")
    adj_open: float = Field(description="Opening price restated for splits and dividends.")
    adj_high: float = Field(description="Session high restated for splits and dividends.")
    adj_low: float = Field(description="Session low restated for splits and dividends.")
    adj_close: float = Field(
        description=(
            "Closing price restated for splits and dividends. This is the series "
            "to use for return calculations."
        ),
    )
    adj_volume: float = Field(
        description="Shares traded restated for splits; fractional after a split adjustment.",
    )
    div_cash: float = Field(
        description="Cash dividend per share going ex on this date; 0.0 on non-dividend days.",
    )
    split_factor: float = Field(
        description=(
            "Split ratio effective on this date; 1.0 on a normal day, 2.0 for a "
            "2-for-1, 0.5 for a 1-for-2 reverse split."
        ),
    )


class TiingoPriceSeries(TiingoResponseModel):
    """An end-of-day price series for one ticker.

    Returned by ``tiingo_price_series``. Rows come back in Tiingo's order, which
    is ascending by date.
    """

    ticker: str = Field(
        description="Tiingo symbol the rows belong to, echoed as Tiingo returned it."
    )
    count: int = Field(
        description=(
            "Number of rows Tiingo sent -- NOT the number mapped. A null row is "
            "skipped defensively, and counting the survivors would make the loss "
            "undetectable by agreeing with the list it had just shortened, so "
            "count != len(prices) means rows were dropped in translation."
        ),
    )
    prices: List[TiingoPriceRow] = Field(
        default_factory=list,
        description=(
            "One row per trading day in the requested window. Empty when the "
            "range covers no trading days, or predates the ticker's history."
        ),
    )


def from_tiingo_meta(meta: Optional[navi_tiingo.TiingoMeta]) -> TiingoSeriesInfo:
    """Map navi's ``TiingoMeta`` to the published :class:`TiingoSeriesInfo`.

    Renames ``exchangeCode``/``startDate``/``endDate`` to snake_case and renders
    the coverage bounds as ISO date strings. Total, like the fred and bls
    mappers: a ``None`` payload maps to an empty record rather than ``None``,
    because the tool boundary serializes the result and cannot accept ``None``.
    """
    if meta is None:
        return TiingoSeriesInfo(ticker="", name="")
    return TiingoSeriesInfo(
        ticker=meta.ticker,
        name=meta.name,
        exchange_code=meta.exchange_code,
        start_date=_iso_date(meta.start_date),
        end_date=_iso_date(meta.end_date),
        description=meta.description,
    )


def from_tiingo_price(price: Optional[navi_tiingo.TiingoPrice]) -> Optional[TiingoPriceRow]:
    """Map one navi ``TiingoPrice`` row to the published :class:`TiingoPriceRow`.

    Renames the seven ``adj*``/``divCash``/``splitFactor`` aliases and derives an
    ISO ``date`` from Tiingo's timestamp. Pure; ``None`` in, ``None`` out.
    """
    if price is None:
        return None
    return TiingoPriceRow(
        date=_iso_date(price.date),
        open=price.open,
        high=price.high,
        low=price.low,
        close=price.close,
        volume=price.volume,
        adj_open=price.adj_open,
        adj_high=price.adj_high,
        adj_low=price.adj_low,
        adj_close=price.adj_close,
        adj_volume=price.adj_volume,
        div_cash=price.div_cash,
        split_factor=price.split_factor,
    )


def from_tiingo_price_series(
    series: Optional[navi_tiingo.TiingoPriceSeries],
) -> TiingoPriceSeries:
    """Map navi's ``TiingoPriceSeries`` to the published :class:`TiingoPriceSeries`.

    Every row is carried over, in order. ``count`` is the number of rows Tiingo
    sent, NOT the number mapped: a null row is skipped defensively, and counting
    the survivors would make the loss undetectable by agreeing with the list it
    just shortened. ``count != len(prices)`` therefore means rows were dropped.
    Pure; ``None`` in, empty out.
    """
    if series is None:
        return TiingoPriceSeries(ticker="", count=0, prices=[])
    supplied = list(series.prices or [])
    rows = [
        mapped
        for mapped in (from_tiingo_price(price) for price in supplied)
        if mapped is not None
    ]
    return TiingoPriceSeries(ticker=series.ticker, count=len(supplied), prices=rows)
