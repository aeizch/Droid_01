"""Binance USDT-M Futures connector.

Uses python-binance's futures_* methods. Supports:
  - per-symbol leverage configuration
  - per-symbol margin type (ISOLATED / CROSSED)
  - market and limit orders, both BUY and SELL (i.e. shorts)
  - position read-back via futures_position_information
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException

from quant.exchange.base import SymbolFilters
from quant.utils.logging import get_logger

log = get_logger("exchange.binance_fut")


class BinanceFuturesConnector:
    """USDT-M Futures (perpetuals)."""

    market_type = "futures"

    INTERVAL_MAP = {
        "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1d",
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
            # python-binance routes futures_* to FUTURES_URL; force testnet endpoint.
            self.client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
            self.client.FUTURES_DATA_URL = "https://testnet.binancefuture.com/futures/data"
        self._filters_cache: dict[str, SymbolFilters] = {}
        log.info("Binance Futures connector ready (testnet=%s)", testnet)

    # --------------------------------------------------------- market data

    def get_klines(self, symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
        if interval not in self.INTERVAL_MAP:
            raise ValueError(f"Unsupported interval: {interval}")
        raw = self.client.futures_klines(
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
        return float(self.client.futures_symbol_ticker(symbol=symbol)["price"])

    def get_mark_price(self, symbol: str) -> float:
        return float(self.client.futures_mark_price(symbol=symbol)["markPrice"])

    # --------------------------------------------------------- account

    def get_account(self) -> dict[str, Any]:
        return self.client.futures_account(recvWindow=self.recv_window)

    def get_free_balance(self, asset: str) -> float:
        for b in self.client.futures_account_balance(recvWindow=self.recv_window):
            if b["asset"] == asset:
                # `availableBalance` excludes initial margin already in use.
                return float(b.get("availableBalance", b.get("balance", 0.0)))
        return 0.0

    def get_position(self, symbol: str) -> dict[str, Any] | None:
        positions = self.client.futures_position_information(
            symbol=symbol, recvWindow=self.recv_window
        )
        for p in positions:
            if p["symbol"] == symbol:
                return p
        return None

    # --------------------------------------------------------- leverage / margin

    def set_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        if leverage < 1 or leverage > 125:
            raise ValueError(f"leverage out of range: {leverage}")
        return self.client.futures_change_leverage(
            symbol=symbol, leverage=int(leverage), recvWindow=self.recv_window
        )

    def set_margin_type(self, symbol: str, margin_type: str) -> dict[str, Any] | None:
        margin_type = margin_type.upper()
        if margin_type not in ("ISOLATED", "CROSSED"):
            raise ValueError(f"margin_type must be ISOLATED or CROSSED, got {margin_type}")
        try:
            return self.client.futures_change_margin_type(
                symbol=symbol, marginType=margin_type, recvWindow=self.recv_window
            )
        except BinanceAPIException as e:
            # -4046 = "No need to change margin type." (already set). Treat as success.
            if e.code == -4046:
                return None
            raise

    # --------------------------------------------------------- filters

    def get_symbol_filters(self, symbol: str) -> SymbolFilters:
        if symbol in self._filters_cache:
            return self._filters_cache[symbol]
        info = self.client.futures_exchange_info()
        match = next((s for s in info["symbols"] if s["symbol"] == symbol), None)
        if match is None:
            raise ValueError(f"Unknown futures symbol {symbol}")
        step_size = tick_size = min_qty = min_notional = 0.0
        for f in match["filters"]:
            if f["filterType"] == "LOT_SIZE":
                step_size = float(f["stepSize"])
                min_qty = float(f["minQty"])
            elif f["filterType"] == "PRICE_FILTER":
                tick_size = float(f["tickSize"])
            elif f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
                min_notional = float(f.get("notional", f.get("minNotional", 0.0)))
        sf = SymbolFilters(
            symbol=symbol,
            base_asset=match["baseAsset"],
            quote_asset=match["quoteAsset"],
            step_size=step_size,
            tick_size=tick_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )
        self._filters_cache[symbol] = sf
        return sf

    # --------------------------------------------------------- trading

    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        sf = self.get_symbol_filters(symbol)
        qty = sf.quantize_qty(quantity)
        if qty < sf.min_qty or qty <= 0:
            raise ValueError(f"Qty {qty} below min_qty {sf.min_qty} for {symbol}")
        params: dict[str, Any] = dict(
            symbol=symbol,
            side=side.upper(),
            type="MARKET",
            quantity=self._fmt_qty(qty, sf.step_size),
            recvWindow=self.recv_window,
        )
        if reduce_only:
            params["reduceOnly"] = "true"
        try:
            return self.client.futures_create_order(**params)
        except BinanceAPIException as e:
            log.error("Futures market order failed %s %s %s: %s",
                      side, qty, symbol, e.message)
            raise

    def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        tif: str = "GTC",
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        sf = self.get_symbol_filters(symbol)
        qty = sf.quantize_qty(quantity)
        px = sf.quantize_price(price)
        if qty < sf.min_qty or qty <= 0:
            raise ValueError(f"Qty {qty} below min_qty {sf.min_qty} for {symbol}")
        params: dict[str, Any] = dict(
            symbol=symbol,
            side=side.upper(),
            type="LIMIT",
            timeInForce=tif,
            quantity=self._fmt_qty(qty, sf.step_size),
            price=self._fmt_price(px, sf.tick_size),
            recvWindow=self.recv_window,
        )
        if reduce_only:
            params["reduceOnly"] = "true"
        try:
            return self.client.futures_create_order(**params)
        except BinanceAPIException as e:
            log.error("Futures limit order failed %s %s @ %s %s: %s",
                      side, qty, px, symbol, e.message)
            raise

    def cancel_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        return self.client.futures_cancel_order(
            symbol=symbol, orderId=order_id, recvWindow=self.recv_window
        )

    def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"recvWindow": self.recv_window}
        if symbol:
            kwargs["symbol"] = symbol
        return self.client.futures_get_open_orders(**kwargs)

    # --------------------------------------------------------- helpers

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
        return int(self.client.futures_time()["serverTime"])

    def ping(self) -> bool:
        try:
            self.client.futures_ping()
            return True
        except Exception:
            return False
