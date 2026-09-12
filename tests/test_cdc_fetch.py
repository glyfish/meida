"""Tests for the NVSR downloader (``notebooks/cdc/fetch.py``).

No network: the listing HTML is the only input the filename logic needs, so
these feed it directly. What they pin is the file *selection*, which is where
this went wrong by hand -- a volume whose naming differs silently yields the
wrong local tree, and the parser then reads whatever landed.
"""
from __future__ import annotations


from notebook_modules import load

F = load("cdc", "fetch")


def _links(*names: str) -> str:
    return "".join(f'<a href="{n}">{n}</a>' for n in names)


def test_state_skips_the_standard_error_tables(monkeypatch):
    """{ST}4 is standard errors, so a jurisdiction yields three files."""
    monkeypatch.setattr(F, "_listing",
                        lambda v: _links("AK1.xlsx", "AK2.xlsx", "AK3.xlsx", "AK4.xlsx"))
    assert F.state_files("74-12") == [
        ("AK1.xlsx", "AK1.xlsx"), ("AK2.xlsx", "AK2.xlsx"), ("AK3.xlsx", "AK3.xlsx")]


def test_the_2018_volume_is_renamed_to_postal_codes(monkeypatch):
    """70-01 spells states out; every other year uses the code the parser reads."""
    monkeypatch.setattr(F, "_listing", lambda v: _links(
        "Montana-1-Total.xlsx", "Montana-2-Male.xlsx",
        "Montana-3-Female.xlsx", "Montana-4-SE.xlsx"))
    assert F.state_files("70-01") == [
        ("Montana-1-Total.xlsx", "MT1.xlsx"),
        ("Montana-2-Male.xlsx", "MT2.xlsx"),
        ("Montana-3-Female.xlsx", "MT3.xlsx")]


def test_multiword_states_map(monkeypatch):
    monkeypatch.setattr(F, "_listing",
                        lambda v: _links("New-Mexico-1-Total.xlsx",
                                         "District-of-Columbia-1-Total.xlsx"))
    assert dict(F.state_files("70-01")) == {
        "New-Mexico-1-Total.xlsx": "NM1.xlsx",
        "District-of-Columbia-1-Total.xlsx": "DC1.xlsx"}


def test_an_unmapped_jurisdiction_is_skipped_loudly(monkeypatch, capsys):
    monkeypatch.setattr(F, "_listing", lambda v: _links("Guam-1-Total.xlsx"))
    assert F.state_files("70-01") == []
    assert "UNMAPPED" in capsys.readouterr().err


def test_national_accepts_the_lowercase_2020_volume(monkeypatch):
    """71-01 ships table01.xlsx; every other year capitalises it."""
    monkeypatch.setattr(F, "_listing",
                        lambda v: _links("table01.xlsx", "table18.xlsx"))
    assert F.national_files("71-01") == [
        ("table01.xlsx", "table01.xlsx"), ("table18.xlsx", "table18.xlsx")]


def test_a_file_already_on_disk_is_not_refetched(monkeypatch, tmp_path):
    """Re-runs resume. The bot filter makes a needless re-pull expensive."""
    (tmp_path / "AK1.xlsx").write_bytes(b"already here")
    calls = []
    monkeypatch.setattr(F, "_download", lambda url, target: calls.append(url) or True)
    monkeypatch.setattr(F, "PAUSE", 0)
    out = F._fetch_all("74-12", [("AK1.xlsx", "AK1.xlsx"), ("AK2.xlsx", "AK2.xlsx")], tmp_path)

    assert [u.rsplit("/", 1)[-1] for u in calls] == ["AK2.xlsx"]
    assert out == {"wanted": 2, "downloaded": 1, "on_disk": 1}


def test_pacing_is_not_quietly_lowered():
    """0.05s served 400 files and then every read timed out for the rest."""
    assert F.PAUSE >= 1.0
