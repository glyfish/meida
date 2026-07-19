# FRED API — Endpoint Reference

Summary of the Federal Reserve Economic Data (FRED) API as used by the MCP
server (navi `FredClient` + meida tools).

Endpoint paths and response shapes below were **verified against the live API**
(26 endpoints probed successfully); auth/limit details come from FRED's official
docs at <https://fred.stlouisfed.org/docs/api/fred/>, which blocks automated
fetching.

## Basics

- **Base URL:** `https://api.stlouisfed.org/fred`
- **Auth:** `api_key` **query parameter** (32-character lower-case alphanumeric).
  There is no header-based auth.
- **`file_type=json` is required for JSON** — the API defaults to **XML**.
  navi's `FredClient._get` injects both `api_key` and `file_type=json` on every
  request, so callers never think about it.
- **Rate limit:** FRED publishes a cap of **120 requests per minute**.
- **Errors** use real HTTP status codes (400 for bad parameters, 429 when
  throttled), unlike BLS. navi wraps them as `FredAPIError`.

### Common parameters

Most endpoints accept: `realtime_start`, `realtime_end` (vintage/ALFRED dates,
`YYYY-MM-DD`), `limit`, `offset`, `order_by`, `sort_order` (`asc`/`desc`).
Paginated responses echo these back alongside `count`.

## Endpoints

All paths are relative to the base URL. ✅ = verified live during this review.

### Categories

| Endpoint | ✅ | Description |
| --- | --- | --- |
| `GET /category` | ✅ | A single category by `category_id` |
| `GET /category/children` | ✅ | Child categories of a category |
| `GET /category/related` | ✅ | Related categories |
| `GET /category/series` | ✅ | Series within a category |
| `GET /category/tags` | ✅ | Tags for the series in a category |
| `GET /category/related_tags` | | Related tags within a category |

### Releases

| Endpoint | ✅ | Description |
| --- | --- | --- |
| `GET /releases` | ✅ | All releases of economic data |
| `GET /releases/dates` | ✅ | Release dates for all releases |
| `GET /release` | ✅ | A single release by `release_id` |
| `GET /release/dates` | ✅ | Release dates for one release |
| `GET /release/series` | ✅ | Series belonging to a release |
| `GET /release/sources` | ✅ | Sources for a release |
| `GET /release/tables` | ✅ | Release table trees (`elements`) |
| `GET /release/tags` | | Tags for a release |
| `GET /release/related_tags` | | Related tags for a release |

### Series

| Endpoint | ✅ | Description |
| --- | --- | --- |
| `GET /series` | ✅ | Metadata for one series |
| `GET /series/categories` | ✅ | Categories a series belongs to |
| `GET /series/observations` | ✅ | **The actual time-series values** |
| `GET /series/release` | ✅ | The release a series belongs to |
| `GET /series/search` | ✅ | Full-text search over series |
| `GET /series/tags` | ✅ | Tags for a series |
| `GET /series/updates` | ✅ | Recently updated series |
| `GET /series/vintagedates` | ✅ | Vintage (revision) dates |
| `GET /series/search/tags` | | Tags for a search result set |
| `GET /series/search/related_tags` | | Related tags for a search |

### Sources and Tags

| Endpoint | ✅ | Description |
| --- | --- | --- |
| `GET /sources` | ✅ | All data sources |
| `GET /source` | ✅ | A single source |
| `GET /source/releases` | ✅ | Releases for a source |
| `GET /tags` | ✅ | All tags |
| `GET /related_tags` | ✅ | Tags related to given `tag_names` |
| `GET /tags/series` | ✅ | Series matching given `tag_names` |

Maps/GeoFRED endpoints (`/geofred/*`) exist for regional data but are outside
this integration's scope.

### Key parameters for `/series/observations`

Beyond the common set: `observation_start`, `observation_end`, `units`
(`lin`, `chg`, `pch`, `pc1`, `log`, …), `frequency` (`d`, `w`, `m`, `q`, `a`,
with aggregation variants), `aggregation_method` (`avg`/`sum`/`eop`),
`output_type`, and `vintage_dates`.

## Response shapes

FRED has **no single envelope** — the wrapper varies by endpoint.

**Paginated collections** (`/category/series`, `/releases`, `/series/search`, …):

```json
{
  "realtime_start": "2026-07-19", "realtime_end": "2026-07-19",
  "order_by": "series_id", "sort_order": "asc",
  "count": 1234, "offset": 0, "limit": 1000,
  "seriess": [ ... ]
}
```

**Unpaginated** (`/category`, `/series/categories`) return just `{"categories": [...]}`;
`/series` and `/release` return `{realtime_start, realtime_end, seriess|releases}`.
`/series/observations` adds `observation_start`, `observation_end`, `units`,
`output_type`, `file_type`.

### Object fields (verified live)

| Collection | Fields |
| --- | --- |
| `categories` | `id`, `name`, `parent_id` |
| `seriess` | `id`, `realtime_start`, `realtime_end`, `title`, `observation_start`, `observation_end`, `frequency`, `frequency_short`, `units`, `units_short`, `seasonal_adjustment`, `seasonal_adjustment_short`, `last_updated`, `popularity`, `group_popularity`, `notes` |
| `observations` | `realtime_start`, `realtime_end`, `date`, `value` |
| `releases` | `id`, `realtime_start`, `realtime_end`, `name`, `press_release`, `link`, `notes` |
| `sources` | `id`, `realtime_start`, `realtime_end`, `name`, `link` |
| `tags` | `name`, `group_id`, `notes`, `created`, `popularity`, `series_count` |
| `release_dates` | `release_id`, `date` |

### Gotchas

- **`seriess`** — the series collection key really is spelled with a double `s`.
- **`value` is a string**, and missing observations come back as `"."` rather
  than null. Verified: `DGS10` on the 2024-01-01 holiday returns `"."`. Callers
  must handle that sentinel before numeric conversion.
- **`last_updated` uses a non-standard short timezone** (`2024-03-28 07:56:01-05`,
  two-digit offset). navi's `Series._parse_last_updated` normalizes `-05` →
  `-0500` and falls back to naive parsing.
- **Pagination caps differ by endpoint** (verified): collection endpoints cap at
  `limit=1000` ("Variable limit is not between 1 and 1000"), while
  `/series/observations` allows up to `limit=100000`. Exceeding either returns
  HTTP 400.

## What the integration wraps

navi `FredClient` (`lib/clients/fred.py`) covers 7 of the endpoints:

| Client method | Endpoint | MCP tool |
| --- | --- | --- |
| `get_category_children` | `/category/children` | `fred_category_children` |
| `get_category_series` | `/category/series` | `fred_category_series` |
| `get_series` | `/series` | `fred_series_info` |
| `get_series_observations` | `/series/observations` | `fred_series_observations` |
| `get_series_updates` | `/series/updates` | `fred_series_updates` |
| `get_releases` | `/releases` | `list_releases` |
| `get_release_series` | `/release/series` | `fred_release_series` |

Typed models live in `lib/clients/models/fred.py`: `CategoryResponse`,
`SeriesResponse`, `ObservationsResponse`, `ReleasesResponse`. They are frozen
and ignore undeclared fields (e.g. `group_popularity` is dropped).

Not yet wrapped and plausibly useful: `/series/search` (discovery without
walking the category tree), `/series/categories`, `/tags/series`, and the
sources family.

See [architecture.md](architecture.md) §10 for two known naming quirks in the
FRED tool layer (`list_releases` prefix/description, and
`fred_category_children` returning a raw dict).
