"""Configuration for meida: API keys, vendor base URLs, and the database URL.

This lived in ``navi/lib/env.py`` while navi owned the vendor clients. The
clients moved to meida and every consumer of this module is now in meida, so
the module followed them -- keeping meida's credentials in navi's tree was the
inversion that made the dotenv split hard to see.

The ``.env`` beside this file is the one that is loaded, so a terminal run and
a VS Code run (which injects the same file via ``python.envFile``) resolve
identically. ``MEIDA_ENV_FILE`` points somewhere else when that is wanted.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

#: ``meida/.env`` -- anchored to this file, never to the working directory, so
#: the answer does not depend on where the process was started.
_DEFAULT_ENV_PATH = Path(__file__).resolve().parent / ".env"
_ENV_PATH = Path(os.getenv("MEIDA_ENV_FILE") or _DEFAULT_ENV_PATH)

DEFAULT_FRED_BASE_URL = "https://api.stlouisfed.org/fred"
DEFAULT_BLS_BASE_URL = "https://api.bls.gov/publicAPI/v2"
DEFAULT_BIS_BASE_URL = "https://stats.bis.org/api/v1"
DEFAULT_MCP_URL = "http://localhost:8080/sse"
DEFAULT_TIINGO_BASE_URL = "https://api.tiingo.com/tiingo"
DEFAULT_CDC_BASE_URL = "https://data.cdc.gov"
DEFAULT_FBI_BASE_URL = "https://api.usa.gov/crime/fbi/cde"
DEFAULT_MEIDA_DB_URL = "postgresql+psycopg://meida@localhost/meida"

# ``load_dotenv`` never overrides an already-set variable, so the shell and any
# IDE-injected environment win; a developer may supply everything that way and
# have no file at all.
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)


@lru_cache
def _get_env_var(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Populate {_ENV_PATH} or export the variable.")
    return value


def get_fred_api_key() -> str:
    """Return the configured FRED API key."""
    return _get_env_var("FRED_API_KEY")


def get_bls_api_key(required: bool = True) -> str | None:
    """Return the configured Bureau of Labor Statistics API key.

    BLS (unlike FRED/Tiingo) works without a key at reduced limits, so callers
    may pass ``required=False`` to get ``None`` instead of an error when unset.
    """
    if required:
        return _get_env_var("BLS_API_KEY")
    return os.getenv("BLS_API_KEY") or None


def get_fred_base_url() -> str:
    """Return the base URL for FRED requests."""
    return os.getenv("FRED_BASE_URL", DEFAULT_FRED_BASE_URL)


def get_bls_base_url() -> str:
    """Return the base URL for BLS requests."""
    return os.getenv("BLS_BASE_URL", DEFAULT_BLS_BASE_URL)


def get_bis_base_url() -> str:
    """Return the base URL for BIS SDMX requests.

    The BIS statistics API needs no credentials, so there is no key accessor.
    """
    return os.getenv("BIS_BASE_URL", DEFAULT_BIS_BASE_URL)


def get_mcp_url() -> str:
    """Return the base URL for MCP requests."""
    return os.getenv("MCP_URL", DEFAULT_MCP_URL)


def get_tiingo_api_key() -> str:
    """Return the configured Tiingo API key."""
    return _get_env_var("TIINGO_API_KEY")


def get_tiingo_base_url() -> str:
    """Return the base URL for Tiingo requests."""
    return os.getenv("TIINGO_BASE_URL", DEFAULT_TIINGO_BASE_URL)


def get_cdc_api_key(required: bool = False) -> str | None:
    """Return the CDC (Socrata) app token, or ``None`` if unset.

    CDC's Socrata API needs no credentials to read public data; the token is
    optional and only raises rate limits, so it defaults to not-required. The
    client sends it in the ``X-App-Token`` header when present.
    """
    if required:
        return _get_env_var("CDC_API_KEY")
    return os.getenv("CDC_API_KEY") or None


def get_cdc_base_url() -> str:
    """Return the base URL for CDC Socrata requests."""
    return os.getenv("CDC_BASE_URL", DEFAULT_CDC_BASE_URL)


def get_anthropic_api_key(required: bool = True) -> str | None:
    """Return the Anthropic API key, used to generate catalog descriptions.

    Lives in ``.env`` with every other credential. It was previously read from
    ``.keys/.anthropic_key``, yada's convention, which meida no longer follows:
    one file, one loader, anchored on the repo rather than the working
    directory.
    """
    if required:
        return _get_env_var("ANTHROPIC_API_KEY")
    return os.getenv("ANTHROPIC_API_KEY") or None


def get_data_gov_key(required: bool = True) -> str | None:
    """Return the api.data.gov key, shared across every service behind it.

    One key covers the whole family -- the FBI Crime Data Explorer, NREL, the
    regulations and federal-register APIs -- so it is named for the gateway,
    not for whichever service reaches for it first. Self-service from
    https://api.data.gov/signup/ and issued instantly, 1,000 requests an hour.
    The shared ``DEMO_KEY`` allows about thirty an hour and then returns
    ``OVER_RATE_LIMIT``: enough to probe an endpoint, not enough to build a
    series.

    Each service wants it spelled its own way -- the CDE API takes ``API_KEY``
    capitalised and ignores the lowercase ``api_key`` others accept -- so the
    caller passes it, this only finds it.
    """
    if required:
        return _get_env_var("DATA_GOV_KEY")
    return os.getenv("DATA_GOV_KEY") or None


def get_fbi_base_url() -> str:
    """Return the base URL for FBI Crime Data Explorer requests."""
    return os.getenv("FBI_BASE_URL", DEFAULT_FBI_BASE_URL)


def get_meida_db_url() -> str:
    """Return the SQLAlchemy URL for meida's time-series source database.

    meida owns this database -- schema, migrations, and the client that reads
    it. Named for its owner rather than any consumer, so nothing here needs to
    know which project is asking.
    """
    return os.getenv("MEIDA_DB_URL", DEFAULT_MEIDA_DB_URL)
