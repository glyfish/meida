"""Which DataverseNL dataset holds each Clio-Infra indicator.

DataverseNL cannot be browsed by script, but it does not need to be: every
main-site workbook cites its indicator by Handle (``10622/QK8VRF``, IISH's
prefix), and the Handle resolver redirects that to the DataverseNL DOI
(``10.34894/UFVNXT``). The resolver is not behind the bot check, and only its
``Location`` header is read -- the redirect is never followed to DataverseNL.

So the full list of what to download comes from ``notebooks/clio``'s
inventory, one small request per indicator, and lands in ``data/datasets.json``:
indicator, category, handle, DOI, the dataset page to open in a browser, and
how much of the main-site data falls before 1946 -- the part historical
borders can change. After 1946 the deposit's CShapes rows reproduce the main
site, so an indicator that starts then gains only its unit and working paper.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .accept import DATA_DIR

CLIO_DATA = Path(__file__).resolve().parents[2] / "clio" / "data"
DATASETS = "datasets.json"
HANDLE_URL = "https://hdl.handle.net/{handle}"
PAGE_URL = "https://dataverse.nl/dataset.xhtml?persistentId=doi:{doi}"
#: The year CShapes takes over from GeaCron in the deposits.
BORDER_CHANGE = 1946
PAUSE = 0.5


class DatasetsError(RuntimeError):
    """A handle did not redirect to a DOI."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def resolve(handle: str) -> str:
    """``10622/QK8VRF`` -> ``10.34894/UFVNXT``, from the resolver's redirect alone."""
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        opener.open(urllib.request.Request(HANDLE_URL.format(handle=handle), method="HEAD"), timeout=30)
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location") or ""
        if exc.code in (301, 302, 303, 307, 308) and "doi.org/" in location:
            return location.split("doi.org/", 1)[1].strip()
        raise DatasetsError(f"{handle}: HTTP {exc.code}, Location {location!r}") from exc
    raise DatasetsError(f"{handle}: did not redirect")


def build(data_dir: Path = DATA_DIR, clio_data: Path = CLIO_DATA, *,
          refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Resolve every indicator's DOI and write ``datasets.json``. Resolved ones are kept."""
    inventory = json.loads((clio_data / "inventory.json").read_text())
    path = Path(data_dir) / DATASETS
    known = json.loads(path.read_text()) if path.exists() and not refresh else {}

    out = {}
    for slug, ind in sorted(inventory.items()):
        entry = known.get(slug) or {}
        if not entry.get("doi"):
            entry = {"doi": resolve(ind["handle"])}
            time.sleep(PAUSE)
        decades = {int(d): n for d, n in ind.get("countries_by_decade", {}).items()}
        out[slug] = {
            **entry,
            "name": ind["name"],
            "category": ind["category"],
            "handle": ind["handle"],
            "page": PAGE_URL.format(doi=entry["doi"]),
            "start": ind["start"], "end": ind["end"],
            # decades with any data before the border change -- where GeaCron adds something
            "decades_before_1946": sum(1 for d in decades if d < BORDER_CHANGE - 6),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return out
