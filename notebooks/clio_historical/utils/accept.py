"""File a hand-downloaded DataverseNL dataset folder.

DataverseNL denies automated clients, so each dataset arrives as a folder the
user downloaded in a browser -- ``<name>-historical.xlsx``, ``<name>.docx`` and
Dataverse's ``MANIFEST.TXT``. :func:`accept` copies it to
``data/raw/<doi>/`` and records in ``data/manifest.json`` what the files
themselves do not carry: the DOI, the deposit version and when it was
downloaded. The version is what says a copy is out of date; the date alone
cannot.

The source folder is copied, never moved or deleted.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import workbook

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
RAW = "raw"
MANIFEST = "manifest.json"


class AcceptError(RuntimeError):
    """The folder is not a Dataverse download, the DOI is malformed, or the
    workbook cannot be matched to a dataset."""


def _norm(text: str) -> str:
    """Clio's names carry doubled spaces -- 15 of 86 -- so compare collapsed."""
    return " ".join(text.split()).casefold()


def identify(title: str, data_dir: Path = DATA_DIR) -> str:
    """The DOI of the dataset whose indicator is *title*, from ``datasets.json``.

    Matched on the name exactly, after collapsing whitespace and case. Verified
    for Labourers Real Wage; a deposit that titles its indicator differently
    raises rather than being matched to the nearest name.
    """
    path = Path(data_dir) / "datasets.json"
    if not path.exists():
        raise AcceptError("no datasets.json -- run utils.datasets.build() first, or pass doi=")
    hits = [d["doi"] for d in json.loads(path.read_text()).values() if _norm(d["name"]) == _norm(title)]
    if len(hits) != 1:
        raise AcceptError(f"workbook title {title!r} matches {len(hits)} datasets -- pass doi= explicitly")
    return hits[0]


def doi_dir(doi: str) -> str:
    """``10.34894/UFVNXT`` -> ``10.34894_UFVNXT``, a safe directory name."""
    if not doi.startswith("10.") or "/" not in doi:
        raise AcceptError(f"not a DOI: {doi!r}")
    return doi.replace("/", "_")


def accept(folder: Path, *, version: str, doi: str | None = None, released: str | None = None,
           downloaded: str | None = None, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Copy *folder* into the raw tree and record it. Returns the manifest entry.

    *doi* is found from the workbook's title row when omitted. When given, it
    must agree with the title -- a mismatch means the wrong folder, and is
    refused rather than filed under the wrong dataset.

    *version* is required: it is on the dataset page, not in the download, and
    it is the field that says whether a copy is stale.

    *downloaded* defaults to the folder's modification date -- when the browser
    wrote it -- rather than today, so filing late does not misdate the copy.
    """
    folder = Path(folder).expanduser()
    books = sorted(folder.glob("*-historical.xlsx"))
    if not books:
        raise AcceptError(f"{folder}: no *-historical.xlsx -- is this a DataverseNL download?")
    title = workbook.read(books[0])["title"]
    found = None
    try:
        found = identify(title, data_dir)
    except AcceptError:
        if doi is None:
            raise
    if doi is None:
        doi = found
    elif found is not None and found != doi:
        raise AcceptError(f"{folder}: the workbook is {title!r}, dataset {found}, not {doi}")
    target = Path(data_dir) / RAW / doi_dir(doi)
    target.mkdir(parents=True, exist_ok=True)

    files = {}
    for f in sorted(folder.iterdir()):
        if f.is_file():
            shutil.copy2(f, target / f.name)
            files[f.name] = {"bytes": f.stat().st_size,
                             "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}

    stamp = downloaded or date.fromtimestamp(folder.stat().st_mtime).isoformat()
    entry = {"doi": doi, "title": title, "version": version, "released": released,
             "downloaded": stamp, "accepted": datetime.now().isoformat(timespec="seconds"),
             "workbook": books[0].name, "files": files}
    manifest_path = Path(data_dir) / MANIFEST
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest[doi] = entry
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return entry
