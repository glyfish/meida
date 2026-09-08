"""LLM-generated descriptions for the CDC catalog.

The catalog's ``title`` is formulaic -- ``suicide (sex=male, age=15-19, crude)``
-- which identifies a series but says nothing about what it measures or who
collected it. The document store embeds free text, so a sentence or two of real
prose is what makes semantic search work.

**One call per bucket, not per series.** 2,682 series collapse into ~38
``(group, concept, facet-shape, unit)`` buckets: within a bucket the series
differ only in which value each facet takes, so one description describes them
all, and the per-series facet values are already in the entry. That is ~38
requests rather than 2,682.

**Descriptions live in a sidecar.** ``descriptions.yaml`` is keyed by bucket and
merged in at export time, so regenerating the catalog needs no API key and
cannot silently drop the text. Re-running only fills gaps unless asked to
refresh.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
KEY_PATH = REPO_ROOT / ".keys" / ".anthropic_key"
DATA_DIR = Path(__file__).parent / "data"
SIDECAR = DATA_DIR / "descriptions.yaml"

MODEL = "claude-opus-5"

SYSTEM = """You write one-sentence-to-two-sentence descriptions of public-health \
and economic time series for a data catalog. The descriptions are embedded for \
semantic search, so they must be factual and specific.

Rules:
- State what is measured, for which population, and by whom it is collected.
- Name the source program (CDC WONDER, NCHS/NVSR life tables, CDC Socrata \
open-data portal, BRFSS, VSRR) when it is given to you.
- When the context covers several series, describe the family: the listed \
facets vary across them, so do not fix them to particular values. When it \
covers exactly one series (series_count is 1), describe that one series and do \
NOT say the facets vary -- they do not.
- No marketing language, no "this dataset provides", no restating the title \
verbatim. Do not invent coverage years, methods, or caveats you were not given.
- Two sentences maximum."""


class DescriptionError(RuntimeError):
    """Raised when descriptions cannot be generated."""


def ensure_api_key() -> None:
    """Put the Anthropic key in the environment, if it is not already there.

    Mirrors yada's ``.keys/`` convention, but resolves the path from the repo
    root rather than the working directory -- this module runs from
    ``notebooks/cdc/``, where a relative ``.keys/...`` would not resolve.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    if not KEY_PATH.exists():
        raise DescriptionError(
            f"ANTHROPIC_API_KEY is not set and {KEY_PATH} does not exist"
        )
    os.environ["ANTHROPIC_API_KEY"] = KEY_PATH.read_text().strip()


def bucket_key(group: str, entry: dict[str, Any]) -> str:
    """Stable key for the bucket an entry belongs to.

    ``(group, concept, facet-shape, unit)`` -- the facet *names*, not their
    values, since the values are what vary within a bucket.
    """
    facets = "+".join(sorted(entry.get("facets", {})))
    return f"{group}|{entry['concept']}|{facets}|{entry.get('unit', '')}"


def buckets(catalog: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Collapse ``{group: [entries]}`` into one prompt context per bucket."""
    out: dict[str, dict[str, Any]] = {}
    for group, entries in catalog.items():
        for entry in entries:
            key = bucket_key(group, entry)
            ctx = out.setdefault(key, {
                "group": group,
                "concept": entry["concept"],
                "unit": entry.get("unit"),
                "frequency": entry.get("frequency"),
                "facet_names": sorted(entry.get("facets", {})),
                "facet_examples": {},
                "series_count": 0,
                "observation_start": entry.get("observation_start"),
                "observation_end": entry.get("observation_end"),
                "provisional": entry.get("provisional"),
                "titles": [],
            })
            ctx["series_count"] += 1
            if len(ctx["titles"]) < 3:
                ctx["titles"].append(entry.get("title"))
            for name, value in (entry.get("facets") or {}).items():
                seen = ctx["facet_examples"].setdefault(name, [])
                if value not in seen and len(seen) < 4:
                    seen.append(value)
            # widest coverage seen in the bucket
            if entry.get("observation_start", "9999") < (ctx["observation_start"] or "9999"):
                ctx["observation_start"] = entry["observation_start"]
            if entry.get("observation_end", "") > (ctx["observation_end"] or ""):
                ctx["observation_end"] = entry["observation_end"]
            for extra in ("definition", "excluded_codes"):
                if entry.get(extra) and extra not in ctx:
                    ctx[extra] = entry[extra]
    return out


def _prompt(ctx: dict[str, Any]) -> str:
    return (
        "Describe this family of time series for a data catalog.\n\n"
        + json.dumps({k: v for k, v in ctx.items() if v not in (None, [], {})}, indent=2)
    )


def generate(
    contexts: dict[str, dict[str, Any]],
    *,
    existing: dict[str, str] | None = None,
    refresh: bool = False,
) -> dict[str, str]:
    """Generate a description per bucket, skipping ones already written."""
    import anthropic

    ensure_api_key()
    client = anthropic.Anthropic()
    out = dict(existing or {})

    todo = [k for k in contexts if refresh or k not in out]
    for i, key in enumerate(sorted(todo), 1):
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": _prompt(contexts[key])}],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not text:
            raise DescriptionError(f"empty description for {key}")
        out[key] = text
        print(f"  [{i}/{len(todo)}] {key.split('|')[0]:14} {key.split('|')[1]:24} {text[:70]}...")
    return out


def load_sidecar(path: Path = SIDECAR) -> dict[str, str]:
    return yaml.safe_load(path.read_text()) or {} if path.exists() else {}


def save_sidecar(descriptions: dict[str, str], path: Path = SIDECAR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(descriptions, sort_keys=True, default_flow_style=False,
                                   allow_unicode=True, width=88))


def read_catalog(data_dir: Path = DATA_DIR) -> dict[str, list[dict[str, Any]]]:
    """Read every ``cdc_series_*.yaml`` group file as ``{group: [entries]}``."""
    catalog: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(data_dir.glob("cdc_series_*.yaml")):
        doc = yaml.safe_load(path.read_text())
        catalog[doc["group"]] = doc["series"]
    return catalog


def apply_to_catalog(data_dir: Path = DATA_DIR, path: Path = SIDECAR) -> int:
    """Merge sidecar descriptions into the group files. Returns entries updated."""
    descriptions = load_sidecar(path)
    if not descriptions:
        raise DescriptionError(f"no descriptions at {path}")

    updated = 0
    for file in sorted(data_dir.glob("cdc_series_*.yaml")):
        doc = yaml.safe_load(file.read_text())
        for entry in doc["series"]:
            text = descriptions.get(bucket_key(doc["group"], entry))
            if text:
                entry["description"] = text
                updated += 1
        file.write_text(yaml.safe_dump(doc, sort_keys=False, default_flow_style=False,
                                       allow_unicode=True, width=88))
    return updated


if __name__ == "__main__":
    import sys

    refresh = "--refresh" in sys.argv
    contexts = buckets(read_catalog())
    print(f"{sum(c['series_count'] for c in contexts.values())} series -> {len(contexts)} buckets")
    descriptions = generate(contexts, existing=load_sidecar(), refresh=refresh)
    save_sidecar(descriptions)
    print(f"wrote {len(descriptions)} descriptions -> {SIDECAR}")
    print(f"applied to {apply_to_catalog()} catalog entries")
