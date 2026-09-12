"""Loaders that put built artifacts into Postgres.

These were written for CDC and lived under ``notebooks/cdc/`` while it was the
only source using them. They are not CDC-specific: every file-delivered source
builds the same two artifacts -- normalized ``.jsonl`` series and catalog YAML
-- and loads them into the same two tables. Keeping them here means a second
source adds a builder and nothing else.

The parameter that matters is ``source``. :func:`load_catalog.load` **prunes**
rows that are absent from the files it just read, scoped to one source, so
calling it with the wrong one deletes another source's catalog entirely.
"""
