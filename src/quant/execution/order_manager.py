"""Order routing layer.

Sits between the strategy/risk decisions and the exchange. In dry-run mode
it logs intent and updates the local portfolio at the signal price; in live
mode it submits the order to Binance and reconciles fills.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from quant.config import ExecutionConfig
from quant.exchange.base import Exchange
from quant.portfolio.portfolio import Portfolio
from quant.strategies.base import Signal, SignalType
from quant.utils.logging import get_logger

log = get_logger("execution.order")


class OrderManager:
    def __init__(
        self,
        connector: Exchange,
        cfg: ExecutionConfig,
        portfolio: Portfolio,
        live_trading: bool,
    ) -> None:
        self.connector = connector
        self.cfg = cfg
        self.portfolio = portfolio
        self.live_trading = live_trading
        self.is_futures = getattr(connector, "market_type", "spot") == "futures"
        self._last_order_ts: dict[str, float] = {}

    # ---------------------------------------------------------- public

    def submit(self, signal: Signal, qty: float, reduce_only: bool = False) -> dict | None:
        """Place an order if anti-flap allows. Returns exchange response or None."""
        if not self._allowed_now(signal.symbol):
            log.info("Skipping %s %s: anti-flap (min_order_spacing_sec)",
                     signal.type, signal.symbol)
            return None

        side = "BUY" if signal.type == SignalType.BUY else "SELL"

        if not self.live_trading:
            return self._simulate(signal, qty, side)

        try:
            if self.cfg.order_type == "limit":
                px = self._limit_price(signal, side)
                if self.is_futures:
                    resp = self.connector.place_limit_order(  # type: ignore[call-arg]
                        signal.symbol, side, qty, px, reduce_only=reduce_only
                    )
                else:
                    resp = self.connector.place_limit_order(signal.symbol, side, qty, px)
            else:
                if self.is_futures:
                    resp = self.connector.place_market_order(  # type: ignore[call-arg]
                        signal.symbol, side, qty, reduce_only=reduce_only
                    )
                else:
                    resp = self.connector.place_market_order(signal.symbol, side, qty)
        except Exception as e:
            log.exception("Order submit failed: %s", e)
            return None

        self._last_order_ts[signal.symbol] = time.time()
        self._reconcile(resp, signal, side)
        return resp

    # ---------------------------------------------------------- helpers

    def _simulate(self, signal: Signal, qty: float, side: str) -> dict:
        log.info(
            "[DRY-RUN] %s %s qty=%.8f @ %.4f (%s)",
            side, signal.symbol, qty, signal.price, signal.reason,
        )
        self.portfolio.on_fill(signal.symbol, side, qty, signal.price)
        self._last_order_ts[signal.symbol] = time.time()
        return {
            "status": "DRY_RUN",
            "symbol": signal.symbol,
            "side": side,
            "executedQty": qty,
            "price": signal.price,
            "transactTime": int(datetime.now(timezone.utc).timestamp() * 1000),
        }

    def _reconcile(self, resp: dict, signal: Signal, side: str) -> None:
        executed_qty = float(resp.get("executedQty", 0.0) or 0.0)
        if executed_qty <= 0:
            log.info("Order accepted but not filled yet: %s", resp.get("orderId"))
            return
        # Pull fills if present (market orders typically include them).
        fills = resp.get("fills") or []
        if fills:
            total_qty = sum(float(f["qty"]) for f in fills)
            avg = sum(float(f["price"]) * float(f["qty"]) for f in fills) / max(total_qty, 1e-12)
        else:
            total_qty = executed_qty
            avg = signal.price
        self.portfolio.on_fill(signal.symbol, side, total_qty, avg)
        log.info(
            "FILL %s %s qty=%.8f avg=%.4f (orderId=%s)",
            side, signal.symbol, total_qty, avg, resp.get("orderId"),
        )

    def _allowed_now(self, symbol: str) -> bool:
        last = self._last_order_ts.get(symbol)
        if last is None:
            return True
        return (time.time() - last) >= self.cfg.min_order_spacing_sec

    def _limit_price(self, signal: Signal, side: str) -> float:
        bps = self.cfg.limit_offset_bps / 10_000.0
        if side == "BUY":
            return signal.price * (1 - bps)
        return signal.price * (1 + bps)
