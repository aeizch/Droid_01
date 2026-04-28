from quant.exchange.base import Exchange, SymbolFilters
from quant.exchange.binance_client import BinanceConnector
from quant.exchange.binance_futures import BinanceFuturesConnector


def build_connector(
    market_type: str,
    api_key: str,
    api_secret: str,
    testnet: bool = True,
    recv_window_ms: int = 5000,
) -> Exchange:
    """Factory: pick spot or futures based on config."""
    market_type = market_type.lower()
    if market_type == "spot":
        return BinanceConnector(api_key, api_secret, testnet, recv_window_ms)
    if market_type == "futures":
        return BinanceFuturesConnector(api_key, api_secret, testnet, recv_window_ms)
    raise ValueError(f"Unknown market_type '{market_type}', use 'spot' or 'futures'")


__all__ = [
    "Exchange",
    "SymbolFilters",
    "BinanceConnector",
    "BinanceFuturesConnector",
    "build_connector",
]
