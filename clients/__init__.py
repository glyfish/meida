"""HTTP clients for external data providers."""

from .fred import FredClient, FredAPIError
from .tiingo import TiingoClient, TiingoAPIError
from .bls import BlsClient, BlsAPIError
from .bis import BisClient, BisAPIError
from .cdc import CdcClient, CdcAPIError
from .wonder import WonderClient, WonderAPIError
from .fbi import FbiClient, FbiAPIError

__all__ = [
    "FredClient",
    "FredAPIError",
    "TiingoClient",
    "TiingoAPIError",
    "BlsClient",
    "BlsAPIError",
    "BisClient",
    "BisAPIError",
    "CdcClient",
    "CdcAPIError",
    "WonderClient",
    "WonderAPIError",
    "FbiClient",
    "FbiAPIError",
]
