# meida — MCP server + data-access API

@../sefer/overview.md
@../sefer/conventions.md

Exposes navi's data clients as MCP tools and builds the metadata catalogs
(FRED, Tiingo, BLS, BIS). Reference docs live in `sefer/meida/`.

## Environment & commands

- pyenv env `meida-3.14.7`; deps are pip-compiled (`requirements.in` → `.txt`,
  includes `-e ../navi`).
- Tests: `pytest tests`.
- Run: the MCP server over SSE on port 8080.

## Gotchas

- BLS flat-file fetch needs `curl_cffi` (a browser TLS fingerprint) to pass the
  bot filter; **be gentle on bulk pulls** — aggressive access trips a multi-day
  block.
- Exported catalogs under `notebooks/*/data/` are large, **gitignored, and
  regenerable** — never commit them.
