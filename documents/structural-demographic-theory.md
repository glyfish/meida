# Structural Demographic Theory — Data Plan

A project design for assembling the data behind **structural demographic theory
(SDT)** — Turchin/Goldstone's framework for social instability — combining
demographic, health, financial, and political data. Two horizons:

- **Historical** — Clio-Infra (1500–2018), the long backdrop, the part to *write
  about*.
- **Contemporary US** — BLS, CDC, FRED/BIS, and Congress, assembled into a
  present-day structural-demographic picture.

Access facts below were verified live except where marked *unverified*. See
[data-sources-backlog.md](data-sources-backlog.md) for the wider source list and
[architecture.md](architecture.md) for the client pattern.

---

## The framework

SDT models instability as the product of three slow-moving pressures. Turchin's
Political Stress Index combines them; each has measurable proxies.

| SDT driver | Plain meaning | Direction |
| --- | --- | --- |
| **Popular immiseration** | Mass well-being declining (wages, health) | worse well-being → more stress |
| **Intra-elite competition / cohesion** | Elites cooperating vs turning on each other | less cooperation → more stress |
| **State fiscal fragility** | Government's ability to fund itself | more debt / less capacity → more stress |

The key modeling note: Congress is **not** a demographic source. It supplies the
*intra-elite* signal — the hardest of the three to measure and the place to make
an original contribution. Demographic *inputs* (population, age structure) come
from Census/UN and Clio-Infra, not Congress.

---

## Source map

| SDT driver | Historical | Contemporary US |
| --- | --- | --- |
| Immiseration — economic | Clio-Infra (real wages, GDP/cap, inequality) | **BLS** (real earnings, CPI) |
| Immiseration — health | Clio-Infra (life expectancy, height, infant mortality) | **CDC** (life expectancy, deaths of despair) |
| Intra-elite cohesion | Clio-Infra (political competition) | **Congress** (cosponsorship, overlap, votes) |
| State fiscal | Clio-Infra (limited) | **FRED / BIS** (debt-to-GDP, rates) |

Every driver has a source at both horizons. The financial data is not
decoration — it *is* the state-fiscal leg (debt-to-GDP) plus elite-wealth signal
(asset prices via FRED/BIS/Tiingo).

---

## Access, per source

| Source | Access | Auth | Shape |
| --- | --- | --- | --- |
| Clio-Infra | Per-indicator `*.xlsx` downloads; **no API** | none | Time series (already) |
| Voteview | `HSall_members.csv` etc., direct download (verified: 6.2 MB, 51,063 member-Congress rows) | none | Time series / panel |
| Congress.gov API | `api.congress.gov/v3/...` (verified: cosponsors endpoint returns `API_KEY_MISSING` without a key) | **free api.data.gov key**, 5,000/hr | REST → derived series |
| CDC | Socrata `data.cdc.gov/resource/<id>.json` (verified: token-free rows) | app token optional | Time series (already) |
| BLS / FRED / BIS / Tiingo | existing clients | see each | Time series |

CDC dataset ids confirmed live: `w9j2-ggv5` (death rates & life expectancy —
fields `year, race, sex, average_life_expectancy, mortality`), `xkb8-kh2a`
(provisional drug-overdose deaths), `9j2v-jamp` (suicide death rates).

---

## Congress: cohesion metrics

Reframing from the discussion: **polarization** measures how far apart elites
vote; **cohesion/cooperation** measures whether they actively work together.
SDT's "elites cooperating = good" maps onto the *cooperation* metrics, which are
the better target. Ranked by fit to that framing:

| Metric | What it captures | Source | Effort |
| --- | --- | --- | --- |
| **Cross-party cosponsorship + network modularity** | Elites *choosing* to collaborate; how cleanly collaboration splits by party | Congress.gov cosponsors | Medium (network build) |
| **Moderate "overlap" bloc** | Members whose ideology sits *between* the party medians — the center that enables deals | Voteview DW-NOMINATE | Low |
| **Bipartisan vote fraction** | Roll calls passing with majorities of *both* parties | Voteview | Low |
| **Party-unity / cohesion scores** | Within-party discipline; cross-party opposition rate | Voteview | Low |
| **Legislative productivity / gridlock** | The *output* of cooperation — significant laws per Congress | GovInfo / Congress.gov | Medium |
| **Cloture / filibuster frequency** | Breakdown of Senate cooperation norms | Senate.gov | Low–Medium |
| **Text: comity vs hostility, partisan language divergence** | How members *talk* about each other | Congressional Record | High |

**Recommended headline metric: cross-party cosponsorship.** Andris et al. (2015,
PNAS, *"The Rise of Partisanship and Super-Cooperators in the U.S. House"*) built
exactly this — a declining cross-party-collaboration series from cosponsorship
networks. It directly measures elites deciding to work together (the user's
cohesion signal) and yields a clean annual series (cross-party edge fraction, or
network modularity). Pair it with the **overlap bloc** from DW-NOMINATE, which
Turchin uses directly in *Ages of Discord* as the shrinking-center indicator.

Two metrics, two verified sources (Congress.gov cosponsors + Voteview CSV), and a
defensible cohesion series is a few days' work.

---

## Health: contemporary immiseration

BLS covers *economic* well-being but not health. SDT's immiseration leg wants
mortality and life expectancy, and the highest-signal contemporary metric is
**deaths of despair** (Case & Deaton — drug, alcohol, and suicide mortality among
working-age adults). It is close to a purpose-built immiseration index.

- **CDC Socrata** (`data.cdc.gov`) — life expectancy (`w9j2-ggv5`), overdose
  (`xkb8-kh2a`), suicide (`9j2v-jamp`). JSON/CSV, token-free (token raises rate
  limits). **Best contemporary-US fit.**
- **CDC WONDER** — authoritative mortality-by-cause/age for building
  deaths-of-despair precisely, but a clunky XML-POST API.
- **OECD Health** — cross-country and **SDMX**, so `BisClient`'s paradigm
  transfers almost directly. Good if the international/historical framing matters.

Plan: CDC Socrata as the API source; deaths of despair as the headline metric.

---

## Architecture fit

Most of this drops into the existing series/observation model — only two pieces
are genuinely new machinery.

**Fits the existing pattern (new loaders, same shape):**

- **Clio-Infra** — per-indicator Excel → series. Loader parses `*.xlsx`; no API.
- **Voteview** — CSV → member/Congress panel; derive overlap/bipartisan series.
- **CDC** — Socrata JSON → series. A thin `CdcClient` mirroring the others.

**New machinery:**

- **Congress cosponsorship → network → series.** Fetch cosponsors per bill
  (Congress.gov API, keyed), build the per-Congress collaboration network, reduce
  to a scalar (cross-party edge fraction / modularity) per Congress. This is a
  graph-reduction step the current stack doesn't have.
- **Congressional Record text → derived series (research layer).** Full text via
  GovInfo bulk (`bulkdata/CREC` — *unverified path*), aggregate by Congress,
  normalize lexical/partisan measures per total words. The novel, write-worthy
  part.

Downstream (document store, cache, plotting) is unchanged — everything lands as a
standard series.

---

## Build sequence

1. **Assemble the known indicators (fast, high value).**
   - BLS real earnings + CPI (client exists)
   - Voteview: overlap bloc + bipartisan vote fraction
   - CDC: life expectancy + deaths of despair (`CdcClient`)
   - FRED/BIS: debt-to-GDP
   → a complete first-cut SDT dataset, all three drivers, plottable.

2. **Clio-Infra historical backbone.** Excel loader for the matching indicators
   (real wages, GDP/cap, inequality, life expectancy, political competition) to
   extend each contemporary series back centuries. This is the part to write
   about.

3. **Cross-party cosponsorship.** Congress.gov key, cosponsor fetch, network
   reduction → the headline cohesion series.

4. **Record-text indicators (research).** The NLP layer — comity/hostility and
   partisan language divergence over time.

Steps 1–2 give a working SDT picture; 3 sharpens the elite-cohesion leg; 4 is the
original contribution.

---

## Open questions / caveats

- **Clio-Infra licensing** unstated on the site; confirm reuse terms before
  redistributing derived data.
- **Congressional Record full-text path** (GovInfo `bulkdata/CREC`) is
  *unverified* — confirm before committing to the text layer.
- **Splicing historical + contemporary** series (Clio-Infra ↔ BLS/CDC) needs a
  documented join: different methodologies, definitions, and boundaries. The
  `_int` date-mirror and provenance conventions from the FRED/BLS stores apply.
- **DW-NOMINATE is one-dimensional cohesion.** Cosponsorship (behavioral) and
  Record text (rhetorical) are independent measures; agreement across all three
  is the robust signal, not any one alone.
- **This spans two new storage shapes** already flagged in the backlog: a graph
  reduction (cosponsorship) and a text→series pipeline (Record). Neither is large,
  but both are new to the stack.
