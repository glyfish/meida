"""Tests for the Voteview downloader (``notebooks/voteview/fetch.py``).

No network. Voteview is a plain static-file host -- no auth, no throttle, no
bot filter -- so the fetch itself is uninteresting; what these pin is the size
gate and the panel checks, which are the two things that would otherwise fail
quietly.
"""
from __future__ import annotations

import csv
import json
import pathlib

import pytest

from notebook_modules import load

F = load("voteview/utils", "fetch")

HEADER = ("congress,chamber,icpsr,state_abbrev,party_code,district_code,"
          "bioname,nominate_dim1")


def _members(tmp_path, rows: list[str]) -> pathlib.Path:
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "HSall_members.csv").write_text(HEADER + "\n" + "\n".join(rows) + "\n")
    return d


def _row(congress, chamber="House", party="200", dim1="0.4", icpsr="1"):
    return f"{congress},{chamber},{icpsr},AL,{party},1,SMITH,{dim1}"


# --- the party_code trap ------------------------------------------------------

@pytest.mark.parametrize("raw, want", [("200", 200), ("200.0", 200),
                                       ("100", 100), ("100.0", 100), ("13", 13)])
def test_party_code_normalises_both_spellings(raw, want):
    """115-117 write it as a float; a raw string compare drops them silently."""
    assert F.party_code({"party_code": raw}) == want


def test_the_float_spelling_is_what_makes_normalising_necessary():
    """Documents the failure: the naive compare returns nothing, not an error."""
    rows = [{"party_code": "200.0"}, {"party_code": "200"}]
    naive = sum(1 for r in rows if r["party_code"] == "200")
    assert naive == 1                                    # half the rows vanish
    assert sum(1 for r in rows if F.party_code(r) == 200) == 2


# --- the size gate ------------------------------------------------------------

def test_the_default_set_excludes_the_700mb_file():
    assert set(F.DEFAULT) == {"parties", "members"}
    assert "votes" not in F.DEFAULT
    assert F.FILES["votes"][1] > F.SIZE_GATE_MB


def test_an_unknown_file_is_refused_with_the_known_names(tmp_path):
    with pytest.raises(F.VoteviewFetchError, match="unknown file"):
        F.fetch(["nominate"], data_dir=tmp_path)


def test_a_cached_file_is_not_refetched(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    (d / "HSall_parties.csv").write_bytes(b"congress\n")
    monkeypatch.setattr(F, "_get", lambda url: pytest.fail(f"refetched {url}"))
    out = F.fetch(["parties"], data_dir=d)
    assert out["parties"]["status"] == "cached"


def test_fetch_writes_a_manifest(tmp_path, monkeypatch):
    """The manifest records the SERVER's Last-Modified, not our download time.

    Voteview rebuilds its static tree nightly, so a file on disk can be hours
    behind with nothing recording it. The previous manifest stored the local
    mtime, which only ever said when we fetched."""
    monkeypatch.setattr(F, "_get",
                        lambda url: (b"congress\n1\n", "Sun, 13 Sep 2026 06:13:58 GMT"))
    monkeypatch.setattr(F, "PAUSE", 0)
    F.fetch(["parties"], data_dir=tmp_path)
    manifest = json.loads((tmp_path / "_manifest.json").read_text())
    assert manifest["parties"]["bytes"] == len(b"congress\n1\n")
    assert manifest["parties"]["published"] == "Sun, 13 Sep 2026 06:13:58 GMT"
    assert "fetched" in manifest["parties"]


# --- the panel checks ---------------------------------------------------------

def test_verify_accepts_a_well_formed_panel(tmp_path):
    d = _members(tmp_path, [_row(1), _row(1, "Senate", "100", "-0.4", "2"),
                            _row(2), _row(2, "Senate", "100", "-0.4", "2")])
    out = F.verify_members(d)
    assert out["congresses"] == "1-2" and out["gaps"] == []
    assert out["chambers"] == {"House": 2, "Senate": 2}
    assert out["two_party_from"] == 1             # both parties present from the start


def test_verify_catches_a_missing_congress(tmp_path):
    """A truncated republish still parses; this is what notices."""
    d = _members(tmp_path, [_row(1), _row(1, "Senate", "100", "-0.4", "2"),
                            _row(3), _row(3, "Senate", "100", "-0.4", "2")])
    with pytest.raises(F.VoteviewFetchError, match=r"missing congresses: \[2\]"):
        F.verify_members(d)


def test_verify_requires_both_chambers(tmp_path):
    d = _members(tmp_path, [_row(1), _row(1, party="100", icpsr="2", dim1="-0.4")])
    with pytest.raises(F.VoteviewFetchError, match="expected House and Senate"):
        F.verify_members(d)


def test_verify_reports_when_the_two_party_frame_begins(tmp_path):
    """Before it, a D-vs-R series is meaningless -- there are no D's or R's."""
    d = _members(tmp_path, [
        _row(1, party="13"), _row(1, "Senate", "13", "0.1", "2"),
        _row(2, party="100", dim1="-0.4"), _row(2, "Senate", "200", "0.4", "2"),
    ])
    assert F.verify_members(d)["two_party_from"] == 2


def test_verify_counts_unscored_members(tmp_path):
    d = _members(tmp_path, [_row(1), _row(1, "Senate", "100", "", "2")])
    out = F.verify_members(d)
    assert out["scored"] == 1 and out["unscored"] == 1


def test_verify_needs_the_file(tmp_path):
    with pytest.raises(F.VoteviewFetchError, match="fetch first"):
        F.verify_members(tmp_path)
