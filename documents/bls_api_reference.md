# BLS Public Data API — Endpoint Reference

Summary of the U.S. Bureau of Labor Statistics (BLS) Public Data API, for the
planned BLS data source in the MCP server (navi client + models, meida MCP
tools). Source: BLS Developers docs — API Signatures v2, v1, and FAQ/Getting
Started pages (last modified Oct 5, 2020). bls.gov blocks automated requests, so
these were retrieved via the Wayback Machine mirror.

- Developers home: https://www.bls.gov/developers/home.htm
- API Signatures v2: https://www.bls.gov/developers/api_signature_v2.htm
- API Signatures v1: https://www.bls.gov/developers/api_signature.htm
- FAQs: https://www.bls.gov/developers/api_faqs.htm

## Basics

- **Two versions, same paths, different base URL:**
  - v2 → `https://api.bls.gov/publicAPI/v2`
  - v1 → `https://api.bls.gov/publicAPI/v1`
- **v2 requires a free registration key**; v1 is open but limited. The key goes
  in the **request body** (`registrationkey`) for POST, or as a **query param**
  (`?registrationkey=`) for GET.
- **`GET` is used only for single-series reads; `POST` (JSON body,
  `Content-Type: application/json`) for everything multi-series or parameterized.**
- **Series ID rules:** may contain `_`, `-`, `#`; no lowercase letters or other
  special characters. Years are 4-digit `YYYY`.
- ⚠️ **Errors come back as HTTP 200** with `"status":"REQUEST_NOT_PROCESSED"`
  and details in the `message[]` array (bad syntax, exceeded limits, etc.).
  `400`/`500` are true HTTP errors. A client must check the `status` field, not
  just the HTTP status code.
- **Output formats:** JSON, or Excel by appending `.xlsx` to the data path.

## Limits (registered v2 vs unregistered v1)

| | v2 (Registered) | v1 (Unregistered) |
| --- | --- | --- |
| Daily queries | 500 | 25 |
| Series per query | 50 | 25 |
| Years per query | 20 | 10 |
| Net/Percent-change calculations | ✅ | ❌ |
| Series description (catalog) | ✅ | ❌ |

## Endpoints (v2)

### 1. Single Series
`GET /timeseries/data/{seriesID}`
Returns the last 3 years for one series. No key needed for the basic call.
Excel: append `.xlsx` to the path.

### 2. Multiple Series
`POST /timeseries/data/`
JSON body: `{"seriesid":["id1", …, "idN"]}` (up to 50). Defaults to last 3
years. Add `"registrationkey"` for v2 limits.

### 3. One or More Series with Optional Parameters
`POST /timeseries/data/` — the full-featured call. JSON body fields:

| Field | Type | Notes |
| --- | --- | --- |
| `seriesid` | array | required |
| `startyear` / `endyear` | `"YYYY"` | up to a 20-year span |
| `catalog` | bool | include series metadata (title, survey, seasonality, area, occupation…) |
| `calculations` | bool | net & percent changes over 1/3/6/12-period spans |
| `annualaverage` | bool | include annual-average data points |
| `aspects` | bool | extra aspects (e.g. Relative Standard Error) |
| `registrationkey` | string | required to use any of the above optional params |

Optional params default to `false`.

### 4. Latest Series Data
`GET /timeseries/data/{seriesID}?latest=true`
Just the single most-recent datapoint for a series.

### 5. Popular Series
`GET /timeseries/popular`
The 25 most-popular series IDs overall; optional `?survey=XX` narrows to one
survey (e.g. `LA` = Local Area Unemployment). Returns only series IDs.

### 6. All Surveys
`GET /surveys`
Catalog of every BLS survey: `survey_abbreviation` + `survey_name`.

### 7. Single Survey
`GET /surveys/{abbreviation}`
Metadata for one survey (e.g. `TU`): name, plus `allowsNetChange`,
`allowsPercentChange`, `hasAnnualAverages` flags.

## v1 Endpoints

v1 (`/publicAPI/v1/...`, no key, lower limits, no `catalog`/`calculations`)
offers only:

- **Single Series** — `GET /timeseries/data/{seriesID}`
- **Multiple Series** — `POST /timeseries/data/` with `{"seriesid":[...]}`
- **One or More Series, Specifying Years** — `POST` with `startyear`/`endyear`

## Response shape (all data endpoints)

```json
{
  "status": "REQUEST_SUCCEEDED",
  "responseTime": 37,
  "message": [],
  "Results": { "series": [
    { "seriesID": "LAUCN040010000000005",
      "catalog": { "series_title": "...", "survey_name": "...", "...": "..." },  // if catalog=true
      "data": [
        { "year": "2013", "period": "M11", "periodName": "November",
          "value": "16393", "latest": "true",                             // latest flag on most-recent
          "footnotes": [ { "code": "P", "text": "Preliminary." } ],
          "calculations": { "net_changes": {}, "pct_changes": {} },       // if calculations=true
          "aspects": [ ] }                                                // if aspects=true
      ]
    }
  ] }
}
```

Notes:

- `value` is a **string**; `year` too.
- `period` is coded: `M01`–`M12` monthly (`M13` = annual avg on some series),
  `Q01`–`Q04` quarterly, `A01` annual, `S01`/`S02` semiannual. `periodName` is
  the human label.
- `calculations.net_changes` / `pct_changes` are keyed by period-span offsets
  (e.g. `"1"`, `"3"`, `"6"`, `"12"`).
- The docs' single/multiple examples render `Results` as an **array**, but the
  live API returns it as an **object** with a `series` array. Pin this down
  against a real response when building the client.

## Implications for the navi/meida integration

- navi's existing FRED/Tiingo clients are **GET-only**; the BLS client needs a
  **POST path** with a JSON body and key-in-body handling.
- Add **status-field error checking** — raise on `REQUEST_NOT_PROCESSED` even
  though the HTTP status is 200.
- Config already scaffolded in navi `lib/env.py`: `get_bls_api_key()`
  (`BLS_API_KEY`), `get_bls_base_url()` (default `https://api.bls.gov/publicAPI/v2`).
- Suggested MCP tool surface mirroring the endpoints:
  `bls_series_data` (POST #3 with optional params), `bls_popular_series`,
  `bls_all_surveys`, `bls_survey_info`.
