"""Helpers for the prediction-market venues.

    polymarket  Gamma, CLOB and Data API v2: events, markets, price paths, resolutions
    kalshi      the CFTC-regulated venue: series, markets, candlesticks, settlement sources
    predictit   the academic-exemption venue: 197 political markets, 5 requests/minute,
                and a chart endpoint that serves exactly 7 days for the first 6
                contracts of a market -- a backfill cushion, not an archive, so
                `predictit.record_snapshot` accumulates history from today
    iem         no API and 3 open markets, but daily prices back to 1988-06-01
    corpus      one shape for all three, and the quality metrics computed over it
    metrics     the metric catalogue: every measure of market quality that public
                data supports, plus `NOT_COMPUTABLE` for the ones it does not
    corpus_iem  the labelled IEM corpus: resolved markets, full paths, known outcomes

Read-only and unauthenticated throughout. Nothing here places an order, holds a
key or touches a wallet: the venues are being measured, not traded.
"""
