# meida

## Supported APIs

- FRED: [https://fred.stlouisfed.org/docs/api/fred/](https://fred.stlouisfed.org/docs/api/fred/)
- Bureau of Labor Statistics: [https://www.bls.gov/audience/developers.htm](https://www.bls.gov/audience/developers.htm)

## Secrets

Store shared API credentials in `../navi/.env`. The `navi.lib.env` helpers use `python-dotenv`
to load the file and expose `get_fred_api_key()` / `get_bls_api_key()` (plus
`get_fred_base_url()` / `get_bls_base_url()`) to any VS Code project that installs `navi`.

### Running the FRED MCP notebook

1. Install deps: `pip install -r requirements.txt`.
2. Export the repo path so the editable `../navi` package is on `PYTHONPATH` (see `.env`).
3. Ensure `../navi/.env` contains `FRED_API_KEY` / `BLS_API_KEY`.
4. Start the MCP server in a separate shell (stdio transport):

   ```bash
   python mcp_server.py
   ```

5. Open `notebooks/fred/mcp.ipynb` and run the setup cell; it imports `navi.lib.env`
   and confirms the keys are available before invoking the MCP tools.
