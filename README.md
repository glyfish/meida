# meida

An MCP server and Jupyter notebook workspace for exploring economic and financial data. Built on top of [navi](../navi/README.md), which provides the API clients, statistical models, and environment configuration.

## What's here

- **`mcp_server/`** — [FastMCP](https://github.com/jlowin/fastmcp) server exposing FRED and Tiingo tools over SSE on `http://localhost:8080`
- **`notebooks/fred/`** — notebooks for browsing FRED categories, series metadata, and observations
- **`notebooks/tiingo/`** — notebooks for Tiingo end-of-day price data

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

## Supported data sources

- **FRED** — [Federal Reserve Economic Data](https://fred.stlouisfed.org/docs/api/fred/)
- **Tiingo** — [end-of-day equity prices](https://api.tiingo.com/)
- **BLS** — [Bureau of Labor Statistics](https://www.bls.gov/developers/)
