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

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
RAW = "raw"
MANIFEST = "manifest.json"


class AcceptError(RuntimeError):
    """The folder is not a Dataverse download, or the DOI is malformed."""


def doi_dir(doi: str) -> str:
    """``10.34894/UFVNXT`` -> ``10.34894_UFVNXT``, a safe directory name."""
    if not doi.startswith("10.") or "/" not in doi:
        raise AcceptError(f"not a DOI: {doi!r}")
    return doi.replace("/", "_")


def accept(folder: Path, *, doi: str, version: str, released: str | None = None,
           downloaded: str | None = None, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Copy *folder* into the raw tree and record it. Returns the manifest entry.

    *downloaded* defaults to the folder's modification date -- when the browser
    wrote it -- rather than today, so filing late does not misdate the copy.
    """
    folder = Path(folder).expanduser()
    books = sorted(folder.glob("*-historical.xlsx"))
    if not books:
        raise AcceptError(f"{folder}: no *-historical.xlsx -- is this a DataverseNL download?")
    target = Path(data_dir) / RAW / doi_dir(doi)
    target.mkdir(parents=True, exist_ok=True)

    files = {}
    for f in sorted(folder.iterdir()):
        if f.is_file():
            shutil.copy2(f, target / f.name)
            files[f.name] = {"bytes": f.stat().st_size,
                             "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}

    stamp = downloaded or date.fromtimestamp(folder.stat().st_mtime).isoformat()
    entry = {"doi": doi, "version": version, "released": released,
             "downloaded": stamp, "accepted": datetime.now().isoformat(timespec="seconds"),
             "workbook": books[0].name, "files": files}
    manifest_path = Path(data_dir) / MANIFEST
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest[doi] = entry
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return entry
