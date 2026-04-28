"""Tests for futures-specific behaviour: shorts, leverage caps, position flips."""

import pytest

from quant.config import RiskConfig
from quant.execution.risk_manager import RiskManager
from quant.portfolio.portfolio import Portfolio
from quant.strategies.base import Signal, SignalType


def _cfg(**overrides):
    base = dict(
        max_position_notional=100.0,
        max_total_notional=500.0,
        max_open_positions=2,
        risk_per_trade_pct=0.01,
        daily_loss_limit=50.0,
        stop_loss_pct=0.02,
        take_profit_pct=0.04,
        max_leverage=5,
    )
    base.update(overrides)
    return RiskConfig(**base)


# ----------------------------------------------------------- portfolio shorts

def test_short_portfolio_open_close_pnl():
    pf = Portfolio(allow_short=True)
    pf.on_fill("BTCUSDT", "SELL", qty=1.0, price=100.0)   # open short
    pos = pf.positions["BTCUSDT"]
    assert pos.qty == -1.0
    assert pos.avg_price == 100.0

    pf.on_fill("BTCUSDT", "BUY", qty=1.0, price=90.0)     # close short at lower price
    assert "BTCUSDT" not in pf.positions
    # short profits when price falls: (100 - 90) * 1 = 10
    assert pf.realised_pnl == pytest.approx(10.0)


def test_position_flip_long_to_short():
    pf = Portfolio(allow_short=True)
    pf.on_fill("BTCUSDT", "BUY", qty=1.0, price=100.0)
    pf.on_fill("BTCUSDT", "SELL", qty=2.0, price=110.0)   # close +1 long, open -1 short
    pos = pf.positions["BTCUSDT"]
    assert pos.qty == -1.0
    assert pos.avg_price == 110.0
    assert pf.realised_pnl == pytest.approx(10.0)


def test_short_disallowed_when_flag_off():
    pf = Portfolio(allow_short=False)
    pf.on_fill("BTCUSDT", "SELL", qty=1.0, price=100.0)
    assert "BTCUSDT" not in pf.positions  # ignored


# ----------------------------------------------------------- risk: leverage

def test_leverage_above_cap_raises():
    with pytest.raises(ValueError):
        RiskManager(_cfg(max_leverage=3), allow_short=True, leverage=5)


def test_leverage_scales_max_notional():
    # Without leverage, max notional is 100. With 3x, effective cap is 300.
    rm = RiskManager(_cfg(max_leverage=5), allow_short=True, leverage=3)
    sig = Signal("BTCUSDT", SignalType.BUY, price=100.0)
    qty = rm.size_position(sig, free_quote_balance=10_000_000.0)
    assert qty * sig.price <= 300.0 + 1e-6


def test_short_signal_approved_on_futures():
    rm = RiskManager(_cfg(), allow_short=True, leverage=2)
    pf = Portfolio(allow_short=True)
    sig = Signal("BTCUSDT", SignalType.SELL, price=100.0)
    decision = rm.evaluate(sig, qty=1.0, portfolio=pf, marks={"BTCUSDT": 100.0})
    assert decision.approved


def test_already_short_blocks_another_short():
    rm = RiskManager(_cfg(), allow_short=True, leverage=2)
    pf = Portfolio(allow_short=True)
    pf.on_fill("BTCUSDT", "SELL", qty=1.0, price=100.0)
    sig = Signal("BTCUSDT", SignalType.SELL, price=100.0)
    decision = rm.evaluate(sig, qty=0.5, portfolio=pf, marks={"BTCUSDT": 100.0})
    assert not decision.approved
    assert "already short" in decision.reason
