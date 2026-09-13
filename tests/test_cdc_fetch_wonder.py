"""Tests for the WONDER side of ``notebooks/cdc/fetch.py``.

No network: a stub client stands in for ``WonderClient``. What these pin is
the bookkeeping around the pull rather than the pull itself, because that is
where it went wrong -- fetching one concept rewrote the summary with only that
concept in it, silently dropping the ``dropped_codes`` the other eight had
recorded. ``wonder_series`` reads those to note each series' departure from
the published definition, so the damage showed up two steps later as
``excluded_codes: null`` in the built series.
"""
from __future__ import annotations

import asyncio
import json
import sys

import pytest

from notebook_modules import load

F = load("cdc/utils", "fetch")
wc = load("cdc/utils", "wonder_codes")


class _Row(dict):
    """Stands in for a WonderRow; fetch_wonder accepts dicts or models."""


class _StubClient:
    """Returns one row and refuses any asterisk code, as WONDER does."""

    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def age_adjusted_rate_by_year(self, codes, *, database, title):
        self.calls.append(list(codes))
        bad = [c for c in codes if c.startswith("*")]
        if bad:
            raise RuntimeError(
                f"WONDER {database} HTTP 500: WONDER returned no <data-table>: "
                f"Invalid 'ICD-10 Codes' codes were found: '{', '.join(bad)}'.")
        return type("R", (), {"rows": [_Row(year=1999, deaths=1, population=2,
                                            crude_rate=0.1, age_adjusted_rate=0.1)]})()


@pytest.fixture
def stub(monkeypatch):
    client = _StubClient()
    module = type(sys)("clients")
    module.WonderClient = lambda *a, **k: client
    monkeypatch.setitem(sys.modules, "clients", module)
    return client


def test_a_single_concept_fetch_keeps_the_others_in_the_summary(stub, tmp_path):
    """The bug: fetching one concept wiped the other eight from the file."""
    prior = {"suicide": {"citation": "x", "num_codes": 27,
                         "databases": {"D76": {"status": "ok", "variant": "no_asterisk",
                                               "dropped_codes": ["*U03"]}}}}
    (tmp_path / "_download_summary.json").write_text(json.dumps(prior))
    (tmp_path / "chronic_liver_D76.json").write_text("[]")

    out = asyncio.run(F.fetch_wonder(["chronic_liver"], databases=["D76"], data_dir=tmp_path))

    assert "suicide" in out, "a partial fetch dropped the other concepts"
    assert out["suicide"]["databases"]["D76"]["dropped_codes"] == ["*U03"]
    on_disk = json.loads((tmp_path / "_download_summary.json").read_text())
    assert set(on_disk) == {"suicide", "chronic_liver"}


def test_a_cached_concept_is_not_requeried(stub, tmp_path):
    (tmp_path / "chronic_liver_D76.json").write_text("[]")
    asyncio.run(F.fetch_wonder(["chronic_liver"], databases=["D76"], data_dir=tmp_path))
    assert stub.calls == [], "a cached concept must not cost a throttled query"


def test_refresh_requeries_and_records_what_was_dropped(stub, tmp_path):
    out = asyncio.run(F.fetch_wonder(["suicide"], databases=["D76"],
                                     data_dir=tmp_path, refresh=True))
    entry = out["suicide"]["databases"]["D76"]
    assert entry["status"] == "ok"
    assert entry["variant"] == "reduced"
    assert entry["dropped_codes"] == ["*U03"]
    assert len(stub.calls) == 2                      # rejected, then retried without it
    assert "*U03" not in stub.calls[1]


def test_the_summary_records_the_full_intended_count(stub, tmp_path):
    """num_codes is the published definition, not what survived the retry."""
    out = asyncio.run(F.fetch_wonder(["suicide"], databases=["D76"],
                                     data_dir=tmp_path, refresh=True))
    assert out["suicide"]["num_codes"] == len(wc.SUICIDE) == 27


def test_a_failure_is_recorded_rather_than_raised(stub, tmp_path, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("WONDER D76 HTTP 504: gateway timeout")
    monkeypatch.setattr(stub, "age_adjusted_rate_by_year", boom)

    out = asyncio.run(F.fetch_wonder(["chronic_liver"], databases=["D76"],
                                     data_dir=tmp_path, refresh=True))
    assert out["chronic_liver"]["databases"]["D76"]["status"] == "error"
