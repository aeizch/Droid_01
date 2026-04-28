"""Tests for OrderManager pre-flight checks."""

from quant.config import ExecutionConfig
from quant.exchange.base import SymbolFilters
from quant.execution.order_manager import OrderManager
from quant.portfolio.portfolio import Portfolio
from quant.strategies.base import Signal, SignalType


class FakeConnector:
    """Stand-in for an exchange — only what OrderManager needs."""

    market_type = "futures"

    def __init__(self, filters: SymbolFilters) -> None:
        self._filters = filters
        self.calls: list[tuple] = []

    def get_symbol_filters(self, symbol: str) -> SymbolFilters:
        return self._filters

    def place_market_order(self, symbol, side, quantity, reduce_only=False):
        self.calls.append(("market", symbol, side, quantity, reduce_only))
        return {"symbol": symbol, "side": side, "executedQty": str(quantity)}


def _filters(min_notional: float = 20.0, step: float = 0.001, min_qty: float = 0.001):
    return SymbolFilters(
        symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
        step_size=step, tick_size=0.1, min_qty=min_qty, min_notional=min_notional,
    )


def _exec_cfg(buffer: float = 0.10) -> ExecutionConfig:
    return ExecutionConfig(
        order_type="market", limit_offset_bps=5, min_order_spacing_sec=0,
        min_notional_buffer_pct=buffer,
    )


def test_rejects_below_min_notional_with_buffer():
    conn = FakeConnector(_filters(min_notional=20.0))
    om = OrderManager(conn, _exec_cfg(buffer=0.10), Portfolio(), live_trading=True)
    # qty 0.0008 BTC at $25,000 = $20 notional, but buffer requires $22.
    sig = Signal("BTCUSDT", SignalType.BUY, price=25_000.0)
    resp = om.submit(sig, qty=0.0008)
    assert resp is None
    assert conn.calls == []


def test_accepts_above_min_notional_with_buffer():
    conn = FakeConnector(_filters(min_notional=20.0))
    om = OrderManager(conn, _exec_cfg(buffer=0.10), Portfolio(), live_trading=True)
    # qty 0.001 BTC at $25,000 = $25 notional, well above $22 threshold.
    sig = Signal("BTCUSDT", SignalType.BUY, price=25_000.0)
    resp = om.submit(sig, qty=0.001)
    assert resp is not None
    assert len(conn.calls) == 1


def test_dryrun_also_rejects_below_min_notional():
    """Dry-run should warn — the whole point is to surface what would fail live."""
    conn = FakeConnector(_filters(min_notional=20.0))
    om = OrderManager(conn, _exec_cfg(buffer=0.10), Portfolio(), live_trading=False)
    sig = Signal("BTCUSDT", SignalType.BUY, price=25_000.0)
    resp = om.submit(sig, qty=0.0005)
    assert resp is None


def test_reduce_only_skips_min_notional_check():
    """Closing a position must not be blocked by min_notional, even on dust."""
    conn = FakeConnector(_filters(min_notional=20.0))
    om = OrderManager(conn, _exec_cfg(buffer=0.10), Portfolio(allow_short=False),
                      live_trading=True)
    om.portfolio.on_fill("BTCUSDT", "BUY", qty=0.001, price=25_000.0)
    sig = Signal("BTCUSDT", SignalType.SELL, price=25_000.0, reason="stop_loss")
    resp = om.submit(sig, qty=0.001, reduce_only=True)
    assert resp is not None  # not blocked
