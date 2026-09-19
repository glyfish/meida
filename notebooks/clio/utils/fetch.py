"""Download the Clio-Infra indicator workbooks and their description pages.

Clio-Infra (``clio-infra.eu``, IISH / Utrecht) publishes long-run economic and
well-being indicators, one ``.xlsx`` per indicator, country by year. Plain
static files: no auth, no token, no bot filter.

**Take file names from the index, never derive them.** The file for the page
``LifeExpectancyatBirthTotal.html`` is ``LifeExpectancyatBirth(Total)_Compact.xlsx``
-- the two spellings disagree in punctuation and capitalisation often enough
that guessing would fail silently on some. The index pairs them in one row::

    <p class="list-group-item"><a href="../Indicators/LabourersRealWage.html">
      Labourers Real Wage</a><span class="badge"><a href="../data/
      LabourersRealWage_Compact.xlsx">1820 [5053] 2008</a></span></p>

and the badge is useful in its own right: the published span and observation
count, which :mod:`inventory` checks each downloaded file against.

**Units are not in the workbooks.** Their ``Metadata`` sheet carries a source
URL and a DOI citation and nothing else. The indicator page's ``Variable(s)``
panel holds the definition, which is where units come from when they are
stated at all, so the pages are fetched alongside the files.

**Licence: CC0-1.0**, checked on DataverseNL for three indicators. Citation is
requested by the community norms, not required.

DataverseNL also hosts a **version 1.1** of every indicator (2026-01-08),
newer than these files (2024-09-02), but behind a JavaScript proof-of-work bot
check that scripts cannot pass. These are the main-site copies; whether 1.1
changed the data is not yet known.

Output, all under ``notebooks/clio/data/`` (gitignored):

=========================  ================================================
``index.html``             the index page as fetched
``raw/<file>.xlsx``        one workbook per indicator, name as published
``pages/<page>.html``      one description page per indicator
``downloads.json``         the manifest -- see :func:`fetch_all`
=========================  ================================================
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

SITE = "https://clio-infra.eu"
INDEX_URL = f"{SITE}/"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
RAW = "raw"
PAGES = "pages"
MANIFEST = "downloads.json"

#: One extra workbook outside the per-indicator list: series at the borders a
#: country had at the time, segmented by border period.
HISTORICAL_BORDERS = "DataAtHistoricalBorders.xlsx"

#: A courtesy, not a requirement -- the host has no rate limit anyone has hit.
PAUSE = 1.0
TIMEOUT = 120
USER_AGENT = "gly.fish meida (research; one-off indicator download)"


class ClioFetchError(RuntimeError):
    """The index no longer parses, or a download failed."""


# --- the index ----------------------------------------------------------------

_CATEGORY = re.compile(r'<a href="#" class="list-group-item active">\s*(.*?)\s*</a>', re.S)
_ITEM = re.compile(
    r'<p class="list-group-item"><a href="\.\./Indicators/([^"]+)\.html">(.*?)</a>'
    r'<span class="badge"><a href="\.\./data/([^"]+)">(.*?)</a></span></p>', re.S)
_BADGE = re.compile(r"(\d{3,4})\s*\[(\d+)\]\s*(\d{3,4})")


def parse_index(page: str) -> list[dict[str, Any]]:
    """Every indicator on the index, in page order, with its category.

    Categories are the ``list-group-item active`` headers; an indicator belongs
    to the nearest one above it.
    """
    marks = [(m.start(), "cat", _html.unescape(m.group(1)).strip())
             for m in _CATEGORY.finditer(page)]
    marks += [(m.start(), "item", m) for m in _ITEM.finditer(page)]
    category, out, seen = None, [], set()
    for _, kind, value in sorted(marks, key=lambda t: t[0]):
        if kind == "cat":
            category = value
            continue
        slug, name, file, badge = value.groups()
        if file in seen:              # the same indicator listed under two headings
            continue
        seen.add(file)
        text = re.sub(r"<[^>]+>", "", badge)
        b = _BADGE.search(text)
        out.append({
            "slug": slug,
            "name": _html.unescape(re.sub(r"<[^>]+>", "", name)).strip(),
            "category": category,
            "file": _html.unescape(file),
            "published_start": int(b.group(1)) if b else None,
            "published_count": int(b.group(2)) if b else None,
            "published_end": int(b.group(3)) if b else None,
        })
    if not out:
        raise ClioFetchError("index parsed to zero indicators -- the page layout changed")
    return out


# --- an indicator page ----------------------------------------------------------

_PANEL = re.compile(
    r'<h3 class="panel-title">\s*(.*?)\s*</h3>\s*</div>\s*<div class="panel-body">(.*?)</div>',
    re.S)


def parse_panels(page: str) -> dict[str, str]:
    """The labelled panels of an indicator page -- ``Variable(s)``, ``Time period``...

    Text only, whitespace collapsed. A heading that appears twice keeps its
    first value.
    """
    out: dict[str, str] = {}
    for title, body in _PANEL.findall(page):
        key = _html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
        text = _html.unescape(re.sub(r"<[^>]+>", " ", body))
        text = re.sub(r"\s+", " ", text).strip()
        if key and key not in out:
            out[key] = text
    return out


# --- download -----------------------------------------------------------------

def _get(url: str) -> tuple[bytes, str | None]:
    """Body and the server's ``Last-Modified`` -- when Clio published, not when we fetched."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read(), r.headers.get("Last-Modified")
    except OSError as exc:
        raise ClioFetchError(f"{url}: {exc}") from exc


def _url(path: str) -> str:
    return f"{SITE}/{urllib.request.quote(path, safe='/()')}"


def fetch_all(data_dir: Path = DATA_DIR, *, refresh: bool = False,
              pages: bool = True, limit: int | None = None) -> dict[str, Any]:
    """Download the index, every workbook, and every indicator page.

    Idempotent: a file already on disk is skipped unless ``refresh=True``. The
    manifest is merged, not rebuilt, so a partial run -- ``limit`` exists for
    trying it on a few -- never erases what an earlier run recorded.

    Returns the counts; the detail is in ``downloads.json``.
    """
    data_dir = Path(data_dir)
    (data_dir / RAW).mkdir(parents=True, exist_ok=True)
    (data_dir / PAGES).mkdir(parents=True, exist_ok=True)

    index_html, _ = _get(INDEX_URL)
    (data_dir / "index.html").write_bytes(index_html)
    indicators = parse_index(index_html.decode("utf-8", "replace"))
    if limit is not None:
        indicators = indicators[:limit]

    manifest_path = data_dir / MANIFEST
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    counts = {"indicators": len(indicators), "downloaded": 0, "cached": 0, "pages": 0}

    targets = [(ind["file"], ind) for ind in indicators] + [(HISTORICAL_BORDERS, None)]
    for file, ind in targets:
        entry = manifest.setdefault(file, {})
        if ind:
            entry.update({k: v for k, v in ind.items()})
        target = data_dir / RAW / file
        if target.exists() and not refresh:
            counts["cached"] += 1
        else:
            blob, published = _get(_url(f"data/{file}"))
            target.write_bytes(blob)
            entry.update({"bytes": len(blob),
                          "sha256": hashlib.sha256(blob).hexdigest(),
                          "last_modified": published,
                          "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            counts["downloaded"] += 1
            time.sleep(PAUSE)

        if ind and pages:
            page_file = data_dir / PAGES / f"{ind['slug']}.html"
            if not page_file.exists() or refresh:
                body, _ = _get(_url(f"Indicators/{ind['slug']}.html"))
                page_file.write_bytes(body)
                counts["pages"] += 1
                time.sleep(PAUSE)
            entry["panels"] = parse_panels(page_file.read_text("utf-8", "replace"))

        manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")

    return counts
