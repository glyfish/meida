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

**Access (verified).** Data portal at <https://data.bis.org/>, an **SDMX API**,
and **bulk CSV** at <https://data.bis.org/bulkdownload>. Terms of permitted use
apply; no rate limits published.

**Data.** Credit to the non-financial sector, debt service ratios, residential
property prices, effective exchange rates, policy rates, locational and
consolidated banking statistics, debt securities, OTC derivatives, global
liquidity indicators, consumer prices.

**Evaluation.** The strongest candidate — it fits the existing pattern exactly
and adds genuine coverage: cross-country banking, derivatives, and credit
aggregates that FRED carries only thinly. Some overlap with FRED (which
republishes selected BIS property-price and credit-gap series), so the same
provenance question as §1 applies, at smaller scale.

**Challenges.** SDMX is a different paradigm — dimension-coded series keys and
XML/JSON-SDMX rather than plain REST. Conceptually close to BLS's dimension
codes, so the facet machinery built for BLS should transfer. Bulk CSV is the
easier on-ramp; the SDMX API is the better long-term interface.

**Value:** high. **Effort:** moderate — mostly the SDMX learning curve.

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

1. **FRED/BLS overlap** — a live problem the moment both catalogs are indexed.
2. **BIS** — best value-to-effort; reuses everything already built.
3. **LittleSis** — small, open, no auth; good pilot for non-series data.
4. **Congress.gov** — larger; needs a mapping strategy to pay off.
5. **Polymarket** — highest novelty, needs its own architecture; do it when
   there's appetite for a second storage model.
6. **Columbia CLIO** — separate project, sequence independently.
