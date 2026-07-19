# Data Sources — Backlog and Evaluation

Candidate data sources beyond FRED, Tiingo, and BLS. Each entry records what it
is, how it's accessed, how it fits the current architecture, and what it would
cost to add. Findings below were verified against the live sites except where
marked *unverified*.

See [architecture.md](architecture.md) for the current client/tool pattern.

---

## The key architectural question

The stack currently assumes one shape: **a series with observations over time**
(navi client → pydantic models → MCP tools → ChromaDB catalog + Postgres cache).

Only one candidate below fits that shape. The rest break it in four different
ways, and each needs a deliberate decision about whether it belongs in the same
stores or gets its own.

| Source | Data shape | Fits current pattern? |
| --- | --- | --- |
| BIS | Time series | ✅ Directly |
| FRED/BLS overlap | — (reconciliation task) | n/a |
| Polymarket | Ephemeral, high-frequency probabilities | ❌ Different lifecycle |
| LittleSis | Graph (entities + relationships) | ❌ Not time series |
| Congress.gov | Text documents | ❌ RAG-shaped, not numeric |
| Columbia CLIO | Bibliographic records | ❌ Different domain entirely |

---

## 1. FRED / BLS overlap — reconciliation, not a new source

**The problem.** FRED republishes BLS data. CPI, unemployment, and payrolls
exist under both a FRED series ID (`UNRATE`, `CPIAUCSL`) and a BLS series ID
(`LNS14000000`, `CUUR0000SA0`). Once both catalogs are in the vector store the
same underlying statistic appears twice, with different IDs, titles, and units
vocabularies — semantic search will return both and the agent has no basis to
choose.

**Considerations.**

- FRED is a *mirror*: it adds its own IDs, consistent units metadata, and ALFRED
  vintage/revision history that BLS's API does not expose.
- BLS is the *origin*: richer faceting (demographics, industry, occupation) and
  the authoritative release.
- Revisions may land at different times, so the two can disagree transiently.

**Options.** (a) Prefer BLS for BLS-origin series and suppress the FRED
duplicate; (b) keep both but tag `provenance` and `is_mirror`; (c) build a
mapping table for the top overlapping series and let the agent pick by need
(vintages → FRED, facets → BLS).

**Value:** high — prevents confusing duplicate results.
**Effort:** moderate; mostly analysis, and only the popular series matter.

---

## 2. BIS — Bank for International Settlements

> **Status: client and MCP tools built** (navi `fff84bf`, meida `b05a7c2`).
> Remaining work is the document-store catalog export.

**Access (verified).** SDMX 2.1 API at `https://stats.bis.org/api/v1`, plus a
data portal at <https://data.bis.org/> and **bulk CSV** at
<https://data.bis.org/bulkdownload>. **No credentials of any kind** — verified
on both structure and observation endpoints with only a `User-Agent`. This makes
BIS the only unauthenticated source in the stack, so there is no `.env` entry
and no quota to design around.

**Data.** 29 dataflows: total credit, debt service ratios, residential and
commercial property prices, effective exchange rates, central bank policy rates,
locational and consolidated banking statistics, debt securities, OTC
derivatives, global liquidity indicators, CPMI payments, consumer prices.

**Structural model.** Maps almost one-to-one onto the BLS work:

| BLS | BIS (SDMX) |
| --- | --- |
| Survey (68) | **Dataflow** (29) |
| Facet columns (`lfst_code`) | **Dimensions** (7 for total credit) |
| Lookup files (`ln.lfst`) | **Codelists** (`CL_AREA`, 101 codes) |
| Per-survey column layout | **DSD** (data structure definition) |

BIS is the *easier* of the two: the DSD declares which codelist decodes each
dimension, so nothing has to be reverse-engineered from filenames (the trap that
made `ce`/`sm` fail in BLS), and `?references=children` returns the DSD plus all
codelists in a single request. Units are a real dimension (`UNIT_TYPE`) rather
than three per-survey encodings.

**What was built.**

- `lib/clients/bis.py` — `BisClient` with `get_dataflows`, `get_datastructure`,
  `get_data`; `lib/clients/models/bis.py` — frozen models with
  `BisDataStructure.decode()`.
- MCP tools `bis_dataflows`, `bis_datastructure`, `bis_series_data`.
- 22 tests against fixtures captured live, including one asserting that **no
  credentials are ever sent**.

**Implementation notes worth keeping.**

- **SDMX-JSON needs an exact version.** `version=1.0.0` or `2.0.0`; a bare
  `version=1.0` returns HTTP 406.
- **CSV for data, SDMX-JSON for structure.** Requesting `format=csv` on the data
  path avoids SDMX-XML parsing entirely — dimensions arrive as plain columns.
  This kept the client to ~230 lines instead of pulling in `pandasdmx`.
- **Data responses carry codes, not labels.** `UNIT_MEASURE: '368'`, not
  `'Per cent per annum'`. Decoding requires pairing with `get_datastructure()`.
- **Codelists are large.** `CL_BIS_UNIT` has 1,096 codes; a full DSD dump is
  ~42 KB versus ~1.8 KB without codes. `bis_datastructure` therefore suppresses
  code/label pairs by default (`include_codes=False`) and reports counts.

**Remaining.** Series enumeration strategy (query with wildcards vs the
availability endpoint) determines whether the catalog is thousands or millions
of series — verify this first, as it did for BLS. Then the export:
dataflows → `survey.yaml`, series + dimensions → series files, codelists →
facet decoding. Also the FRED overlap from §1, at smaller scale, since FRED
republishes selected BIS property-price and credit-gap series.

**Value:** high. **Effort:** the catalog export only; the client is done.

---

## 3. Polymarket

**Access (partly verified).** Public docs at <https://docs.polymarket.com>, with
a machine-readable index at `llms.txt`. Read access needs **no authentication**.
Gamma API (market metadata) and CLOB API (prices, order books), plus official
Python/TypeScript/Rust SDKs. *Endpoint specifics and rate limits unverified.*

**Evaluation.** The most *differentiated* candidate — forward-looking implied
probabilities of future events, which nothing else here provides. Also the worst
fit for the current architecture.

**Challenges.**

- **Lifecycle, not history.** Markets are created, trade, then resolve to 0 or 1
  and stop. That's not a continuing series; the catalog churns constantly.
- **Refresh cadence.** Yearly rebuilds are meaningless here. Prices move
  continuously and a market's interesting window may be days.
- **Modeling.** A price *is* a probability, bounded 0–1, with a resolution date
  and criteria. Needs its own schema, not the series/observation model.
- **The text is the value.** Market questions and resolution criteria are prose,
  making them a natural RAG target — but they'd need a separate store with an
  aggressive refresh, not the annual-rebuild catalog.

Trading later means wallet/auth and a much higher correctness bar; keeping
read-only strictly separate from any future trading path is worth doing from the
start.

**Value:** high but distinct. **Effort:** high — needs its own storage strategy.

---

## 4. LittleSis

**Access (verified).** Free JSON API at <https://littlesis.org/api>, **no API
key or authentication** (may be rate-limited). Endpoints: `/api/entities/:id`,
`/api/relationships/:id`, `/api/entities/:id/relationships`, `/connections`,
`/lists`, and `/api/entities/search?q=`. Bulk dataset download available.
Licensed **CC BY-SA 4.0**.

**Data.** People and organizations, plus the relationships between them: board
memberships, donations, ownership, employment.

**Evaluation.** Genuinely different and complementary — board interlocks,
ownership networks, and influence mapping are questions the time-series stack
simply cannot answer.

**Challenges.**

- **It's a graph.** Entities and edges don't fit the series model. Natural homes
  are Postgres (nodes/edges) or a graph store; forcing it into ChromaDB alone
  loses the traversal that makes it valuable.
- **Provenance.** Activist-curated and partly crowd-sourced. Coverage is uneven
  and framing is not neutral. Fine for exploration and lead generation; needs
  corroboration before anything decision-critical.
- **CC BY-SA 4.0** carries share-alike obligations if data is redistributed —
  worth checking against how yada surfaces it.

**Value:** medium-high, exploratory. **Effort:** medium, plus a storage decision.

---

## 5. Congress.gov

**Access (unverified — docs not reachable in this pass).** Official API at
`api.congress.gov`, believed to require a free **api.data.gov** key with an
hourly request cap. Endpoints for bills, amendments, members, committees,
nominations, treaties, and the Congressional Record. GovInfo offers bulk data as
an alternative. **Confirm key mechanics and rate limits before building.**

**Evaluation.** Legislative and regulatory signal — useful for connecting policy
activity to sectors. Text-heavy, so it suits a RAG document store better than
the numeric pipeline, and bill text is exactly what vector search is good at.

**Challenges.** Volume is large and bills are long (chunking strategy needed).
Mapping legislation to tickers/sectors is a hard, fuzzy problem and probably the
real work — the ingestion is comparatively easy.

**Value:** medium, depends on the mapping. **Effort:** medium for ingest, high
to make it analytically useful.

---

## 6. Columbia CLIO open data

**Access (verified).** <https://library.columbia.edu/bts/clio-data.html> —
Columbia University Libraries' catalog open data. **MARCXML bulk download**,
**CC0 public domain**, monthly updates. **No API.** Excludes Law Library,
ReCAP partner records (NYPL, Princeton), and vendor-restricted records.

**Data.** Bibliographic and holdings records — books, serials, music, video,
images, cartographic materials, manuscripts, archival collections.

**Evaluation.** Not financial data at all; this is library catalog metadata.
Sensible for the separate research/bibliography project it was flagged for, and
CC0 with bulk download makes it unusually easy to work with. It should be its
own store with no connection to the financial pipeline.

**Challenges.** MARC is an idiosyncratic format (use `pymarc`); records are
descriptive metadata, not full text. Monthly updates "with potential structural
and format changes" means the parser needs to be defensive.

**Value:** high for its own project, nil for finance. **Effort:** low-medium.

---

## Suggested order

| # | Source | Status |
| --- | --- | --- |
| 1 | **BIS** | Client + MCP tools **done**; catalog export remains |
| 2 | **FRED/BLS overlap** | Not started — bites as soon as both catalogs are indexed |
| 3 | **LittleSis** | Not started — small, open, no auth; good pilot for non-series data |
| 4 | **Congress.gov** | Not started — larger; needs a mapping strategy to pay off |
| 5 | **Polymarket** | Not started — highest novelty, needs its own storage model |
| 6 | **Columbia CLIO** | Separate project, sequence independently |

BIS moved to the front because its client is built. Finishing its catalog export
next also keeps the export machinery fresh from the BLS work, and BIS is the
cleaner of the two to build against.

The FRED/BLS overlap stays high because it is a *correctness* problem rather
than a feature: the moment both catalogs are in the vector store, the same
statistic appears twice with no basis for the agent to choose. Adding BIS
enlarges it slightly, since FRED republishes selected BIS series too.
