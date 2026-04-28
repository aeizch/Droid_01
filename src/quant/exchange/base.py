"""Common exchange interface shared by spot and futures connectors."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any, Protocol

import pandas as pd


@dataclass
class SymbolFilters:
    symbol: str
    base_asset: str
    quote_asset: str
    step_size: float
    tick_size: float
    min_qty: float
    min_notional: float

    def quantize_qty(self, qty: float) -> float:
        if self.step_size <= 0:
            return qty
        d_qty = Decimal(str(qty))
        d_step = Decimal(str(self.step_size))
        return float((d_qty // d_step) * d_step)

    def quantize_price(self, price: float) -> float:
        if self.tick_size <= 0:
            return price
        d_price = Decimal(str(price)).quantize(
            Decimal(str(self.tick_size)), rounding=ROUND_DOWN
        )
        return float(d_price)


class Exchange(Protocol):
    """Minimal interface used by the runner / order manager."""

    market_type: str  # "spot" or "futures"

    def ping(self) -> bool: ...
    def server_time(self) -> int: ...
    def get_klines(self, symbol: str, interval: str, limit: int = 500) -> pd.DataFrame: ...
    def get_price(self, symbol: str) -> float: ...
    def get_free_balance(self, asset: str) -> float: ...
    def get_symbol_filters(self, symbol: str) -> SymbolFilters: ...
    def place_market_order(self, symbol: str, side: str, quantity: float) -> dict[str, Any]: ...
    def place_limit_order(
        self, symbol: str, side: str, quantity: float, price: float, tif: str = "GTC"
    ) -> dict[str, Any]: ...
    def cancel_order(self, symbol: str, order_id: int) -> dict[str, Any]: ...
    def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]: ...
