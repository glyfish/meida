# BLS Metadata Export — Status and Remaining Work

Working notes for resuming the BLS document-store export. The design is settled
and the code is written; what remains is running it once, one design doc, and
commits.

See [bls_api_reference.md](bls_api_reference.md) for the API, and
[architecture.md](architecture.md) for how meida and navi fit together.

---

## Current state

### Done and verified

**Three export functions in [notebooks/bls/utils.py](../notebooks/bls/utils.py):**

| Function | Purpose |
|---|---|
| `fetch_bls_source_files(surveys, dest, force, delay)` | Downloads `<survey>.series` plus only the lookup tables its `*_code` columns reference. Caches to `/tmp/bls_source`, records BLS's mtime/bytes for rebuild checks. |
| `write_survey_yaml(source_dir, output_path, manifest)` | One `data/survey.yaml` for all surveys. |
| `write_series_yaml(survey, ...)` / `write_all_series_yaml(...)` | One `data/bls_series_<CODE>.yaml` per survey. |

Verified against cached data — counts match independent measurements exactly:

```
AP: 1,483 series (590 active)     units: Dollars
WP: 5,310 series (4,355 active)   units: Index, index_base: 1982
```

`is_active` correctly flags `WPS00000000` (ends 1974) as false; the units
fallback and index-base derivation both work.

### Blocked

`download.bls.gov` **rate-limited us** during exploration (a few hundred
requests, ~800 MB). It returns 403 to everything, including `curl`. Expected to
be temporary — the same user-agent returned 200 minutes earlier, which is a
threshold being crossed, not a ban.

Without the lookup files, facets and seasonality render as raw codes. That's the
designed fallback, but the real export needs the fetch to succeed first.

---

## Remaining work

### 1. Run the export (~10 min once unblocked)

From `notebooks/bls/`:

```python
manifest = await fetch_bls_source_files(delay=2.0)   # 22 surveys, ~200 requests
write_survey_yaml(manifest=manifest)                 # -> data/survey.yaml
write_all_series_yaml()                              # -> data/bls_series_<CODE>.yaml
```

Idempotent — a partial run resumes rather than re-downloading.

**Verification:** with lookups present, facets and seasonality must decode to
names, not codes. Currently `AP` shows `item: '701111'` and `seasonal: S`; after
a real fetch those should read `item: Flour, white, all purpose…` and
`Not Seasonally Adjusted`. Still-raw values mean the lookup fetch silently
failed.

Expect ~**271K series across 22 files**, largest `LN` ~30 MB, ~100 MB total.

### 2. Write `data-store-bls.md`

Design is settled; needs writing up:

- Flat-file sources and locations, plus the regeneration calls above
- `survey.yaml` and `bls_series_<CODE>.yaml` schemas
- The ~249K-active economic core and why injury/retired/cross-product surveys are excluded
- Two-level active rule: survey retired if `current_year - survey_max_end_year >= 5`; within live surveys `is_active = end_year >= survey_max_end_year - 1`
- Per-survey units resolution + `index_base`
- Sparse-facet handling (only non-"all" codes)
- **Access gotchas** (below)

### 3. Commit

**meida** (possibly 2–3 commits — several threads mixed):

- `documents/fred_api_reference.md`, `documents/tiingo_api_reference.md` (new), plus `architecture.md` / `README.md` / `bls_api_reference.md` edits
- `notebooks/bls/utils.py` — plot helpers **and** export machinery
- `tests/conftest.py`, `tests/test_bls_client.py` — retry tests
- `.gitignore` — ignores `notebooks/bls/data/` (outputs are committed in yada)
- `notebooks/bls/api.ipynb`, `surveys.ipynb` — notebook runs

**navi:** `lib/clients/bls.py` — retry with exponential backoff. **65 tests pass.**

### 4. Deferred (optional)

- `catalog` flag on `bls_series_latest` — makes it a cheap metadata lookup
  (`GET ?latest=true&catalog=true` returns full catalog + 1 datapoint)
- 20-year chunking helper for observations — likely redundant, since the series
  cache fetcher will chunk

### 5. Cleanup

~833 MB of scratch in `/tmp`, including a **744 MB truncated `oe.series`** that
is incomplete and must not be mistaken for a real catalog:

```bash
rm -rf /tmp/*_series.txt /tmp/bls_out /tmp/bls_*.json
# keep /tmp/bls_source — it is the fetch cache
```

---

## Open decision

**Gzip the output?** ~100 MB of YAML regenerated annually into yada's history
repeats the pattern we purged from meida (206 MB of FRED YAML removed from all
history). Measured: YAML compresses **34×** — the whole core is ~4 MB gzipped,
for a one-line loader change (`yaml.safe_load(gzip.open(path))`).

Easy to switch now; annoying after the files are committed.

---

## Access gotchas (carry into the design doc)

- **Do not spoof a browser user-agent.** `download.bls.gov` rejects requests
  claiming to be Chrome without a real browser's fingerprint. An honest
  automation UA works: `Mozilla/5.0 (compatible; meida-bls-exporter)`. A bare
  token with no `Mozilla/5.0` prefix is also rejected.
- **403 is ambiguous.** BLS serves the *same* "Access Denied" page for a
  rejected user-agent and for rate limiting, so a 403 cannot be diagnosed from
  the status code alone. If a UA that previously worked starts failing, assume
  throttling and back off.
- **Be polite.** The fetcher uses a 1s inter-request delay and exponential
  backoff. Bulk exploration without delays is what got us limited.
