"""Thin Binance Spot connector built on python-binance.

All numerical I/O uses Decimal-friendly strings to avoid float rounding,
then converts to float for the rest of the system.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException

from quant.utils.logging import get_logger

log = get_logger("exchange.binance")


@dataclass
class SymbolFilters:
    symbol: str
    base_asset: str
    quote_asset: str
    step_size: float       # LOT_SIZE
    tick_size: float       # PRICE_FILTER
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
        d_price = Decimal(str(price)).quantize(Decimal(str(self.tick_size)), rounding=ROUND_DOWN)
        return float(d_price)


class BinanceConnector:
    """Wraps python-binance for spot market data + trading."""

    INTERVAL_MAP = {
        "1m": Client.KLINE_INTERVAL_1MINUTE,
        "3m": Client.KLINE_INTERVAL_3MINUTE,
        "5m": Client.KLINE_INTERVAL_5MINUTE,
        "15m": Client.KLINE_INTERVAL_15MINUTE,
        "30m": Client.KLINE_INTERVAL_30MINUTE,
        "1h": Client.KLINE_INTERVAL_1HOUR,
        "2h": Client.KLINE_INTERVAL_2HOUR,
        "4h": Client.KLINE_INTERVAL_4HOUR,
        "1d": Client.KLINE_INTERVAL_1DAY,
    }

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
        recv_window_ms: int = 5000,
    ) -> None:
        self.testnet = testnet
        self.recv_window = recv_window_ms
        self.client = Client(api_key, api_secret, testnet=testnet)
        if testnet:
            self.client.API_URL = "https://testnet.binance.vision/api"
        self._filters_cache: dict[str, SymbolFilters] = {}
        log.info("Binance connector ready (testnet=%s)", testnet)

    # ------------------------------------------------------------------ market data

    def get_klines(self, symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
        if interval not in self.INTERVAL_MAP:
            raise ValueError(f"Unsupported interval: {interval}")
        raw = self.client.get_klines(
            symbol=symbol, interval=self.INTERVAL_MAP[interval], limit=limit
        )
        cols = [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tbav", "tqav", "ignore",
        ]
        df = pd.DataFrame(raw, columns=cols)
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        df = df.set_index("open_time")
        return df[["open", "high", "low", "close", "volume", "close_time"]]

    def get_price(self, symbol: str) -> float:
        return float(self.client.get_symbol_ticker(symbol=symbol)["price"])

    # ------------------------------------------------------------------ account

    def get_account(self) -> dict[str, Any]:
        return self.client.get_account(recvWindow=self.recv_window)

    def get_free_balance(self, asset: str) -> float:
        for b in self.get_account()["balances"]:
            if b["asset"] == asset:
                return float(b["free"])
        return 0.0

    # ------------------------------------------------------------------ filters

    def get_symbol_filters(self, symbol: str) -> SymbolFilters:
        if symbol in self._filters_cache:
            return self._filters_cache[symbol]
        info = self.client.get_symbol_info(symbol)
        if info is None:
            raise ValueError(f"Unknown symbol {symbol}")
        step_size = tick_size = min_qty = min_notional = 0.0
        for f in info["filters"]:
            if f["filterType"] == "LOT_SIZE":
                step_size = float(f["stepSize"])
                min_qty = float(f["minQty"])
            elif f["filterType"] == "PRICE_FILTER":
                tick_size = float(f["tickSize"])
            elif f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
                min_notional = float(f.get("minNotional", f.get("notional", 0.0)))
        sf = SymbolFilters(
            symbol=symbol,
            base_asset=info["baseAsset"],
            quote_asset=info["quoteAsset"],
            step_size=step_size,
            tick_size=tick_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )
        self._filters_cache[symbol] = sf
        return sf

    # ------------------------------------------------------------------ trading

    def place_market_order(self, symbol: str, side: str, quantity: float) -> dict[str, Any]:
        sf = self.get_symbol_filters(symbol)
        qty = sf.quantize_qty(quantity)
        if qty < sf.min_qty or qty <= 0:
            raise ValueError(
                f"Qty {qty} below min_qty {sf.min_qty} for {symbol}"
            )
        try:
            return self.client.create_order(
                symbol=symbol,
                side=side.upper(),
                type="MARKET",
                quantity=self._fmt_qty(qty, sf.step_size),
                recvWindow=self.recv_window,
            )
        except BinanceAPIException as e:
            log.error("Market order failed %s %s %s: %s", side, qty, symbol, e.message)
            raise

    def place_limit_order(
        self, symbol: str, side: str, quantity: float, price: float, tif: str = "GTC"
    ) -> dict[str, Any]:
        sf = self.get_symbol_filters(symbol)
        qty = sf.quantize_qty(quantity)
        px = sf.quantize_price(price)
        if qty < sf.min_qty or qty <= 0:
            raise ValueError(f"Qty {qty} below min_qty {sf.min_qty} for {symbol}")
        try:
            return self.client.create_order(
                symbol=symbol,
                side=side.upper(),
                type="LIMIT",
                timeInForce=tif,
                quantity=self._fmt_qty(qty, sf.step_size),
                price=self._fmt_price(px, sf.tick_size),
                recvWindow=self.recv_window,
            )
        except BinanceAPIException as e:
            log.error("Limit order failed %s %s @ %s %s: %s", side, qty, px, symbol, e.message)
            raise

    def cancel_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        return self.client.cancel_order(symbol=symbol, orderId=order_id, recvWindow=self.recv_window)

    def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        if symbol:
            return self.client.get_open_orders(symbol=symbol, recvWindow=self.recv_window)
        return self.client.get_open_orders(recvWindow=self.recv_window)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _fmt_qty(qty: float, step: float) -> str:
        if step <= 0:
            return f"{qty}"
        decimals = max(0, -int(round(math.log10(step))))
        return f"{qty:.{decimals}f}"

    @staticmethod
    def _fmt_price(price: float, tick: float) -> str:
        if tick <= 0:
            return f"{price}"
        decimals = max(0, -int(round(math.log10(tick))))
        return f"{price:.{decimals}f}"

    def server_time(self) -> int:
        return int(self.client.get_server_time()["serverTime"])

    def ping(self) -> bool:
        try:
            self.client.ping()
            return True
        except Exception:
            return False
