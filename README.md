# meida

An MCP server and Jupyter notebook workspace for exploring economic and financial data. Built on top of [navi](../navi/README.md), which provides the API clients, statistical models, and environment configuration.

## What's here

- **`mcp_server/`** — [FastMCP](https://github.com/jlowin/fastmcp) server exposing FRED, Tiingo, and BLS tools over SSE on `http://localhost:8080`
- **`notebooks/fred/`** — notebooks for browsing FRED categories, series metadata, and observations
- **`notebooks/tiingo/`** — notebooks for Tiingo end-of-day price data
- **`notebooks/bls/`** — notebooks for browsing BLS surveys and time series
- **`documents/`** — reference docs (e.g. [BLS API endpoints](documents/bls_api_reference.md))

## Dependencies

This project depends on **navi**, which must be checked out as a sibling directory:

```text
gly.fish/
├── meida/   ← this repo
└── navi/    ← required sibling
```

navi is installed as a local editable package via `requirements.in`:

```text
-e ../navi
```

## Setup

### 1. Check out navi

```bash
git clone <navi-repo-url> ../navi
```

### 2. Configure API keys

API keys are read from `../navi/.env`. Follow the [navi setup instructions](../navi/README.md#setup) to create that file.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Start the MCP server

```bash
python mcp_server/server.py
```

The server listens on `http://localhost:8080/sse`.

### 5. Open notebooks

Launch JupyterLab and open any notebook under `notebooks/`.

## Generating the FRED data files

The category and series metadata under `notebooks/fred/categories/category_data/`
and `notebooks/fred/series/series_data/` are **not tracked in git** (they are large
and fully regenerable, so they are `.gitignore`d). Rebuild them locally with the
notebooks below.

Both stages call FRED tools over the MCP server, so the server must be running
(see [step 4](#4-start-the-mcp-server)) before you begin. Both helpers throttle
their requests with `time.sleep` to stay within FRED's rate limits, so a full
rebuild takes a while and the resulting `series_data/` is a few hundred MB.

Files follow the naming convention `fred_<name>_<root_category_id>.yaml`, and a
`series_data/` file is generated from the `category_data/` file of the same name.

### Stage 1 — category leaf discovery → `category_data/`

Run the notebooks in `notebooks/fred/categories/` (`academic`, `finance`,
`international`, `national_accounts`, `population`, `prices`, `production`,
`regional_data`). Each walks the FRED category tree from a root category via the
`fred.category_children` tool and writes its leaf categories with
[`find_leaf_categories(root_id, root_name, output_path)`](notebooks/fred/utils.py)
into `category_data/`, e.g.:

```python
root_id = 32991
root_name = "Money, Banking, & Finance"
await find_leaf_categories(root_id, root_name, f"fred_finance_{root_id}.yaml")
```

### Stage 2 — series metadata export → `series_data/`

Run [notebooks/fred/series/series_info.ipynb](notebooks/fred/series/series_info.ipynb).
For each `category_data/` file it pulls the FRED series for every leaf category via
the `fred.category_series` tool and writes them with
[`export_finance_category_series(input_path, output_path)`](notebooks/fred/utils.py)
into `series_data/` under the same filename:

```python
filename = "fred_finance_32991.yaml"
input_path = str(Path(f"../categories/category_data/{filename}").absolute())
output_path = str(Path(f"series_data/{filename}").absolute())
await export_finance_category_series(input_path, output_path)
```

## Testing

Unit tests live in `tests/` and cover the MCP server logic
([mcp_server/server.py](mcp_server/server.py)) and the navi HTTP clients
(`lib/clients`). They use `httpx.MockTransport`, so no network access or API
keys are required.

```bash
pip install -r requirements-dev.txt
pytest
```

## BLS tools

The server exposes these Bureau of Labor Statistics tools (see
[documents/bls_api_reference.md](documents/bls_api_reference.md) for the
underlying API):

- `bls_series_data` — observations for up to 50 series IDs, with optional
  `start_year`/`end_year`, `catalog`, `calculations`, `annualaverage`, `aspects`
- `bls_series_latest` — the most-recent datapoint for a series
- `bls_popular_series` — the 25 most popular series IDs (optionally per survey)
- `bls_all_surveys` / `bls_survey_info` — survey catalog and per-survey metadata

BLS works without a key at reduced limits; set `BLS_API_KEY` in `../navi/.env`
to raise the limits and enable `catalog`/`calculations`. Explore via the
notebooks in `notebooks/bls/`.

## Supported data sources

- **FRED** — [Federal Reserve Economic Data](https://fred.stlouisfed.org/docs/api/fred/)
- **Tiingo** — [end-of-day equity prices](https://api.tiingo.com/)
- **BLS** — [Bureau of Labor Statistics](https://www.bls.gov/developers/)
