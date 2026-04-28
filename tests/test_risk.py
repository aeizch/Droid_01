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
    )
    base.update(overrides)
    return RiskConfig(**base)


def test_size_position_caps_at_max_notional():
    rm = RiskManager(_cfg(max_position_notional=100.0))
    sig = Signal("BTCUSDT", SignalType.BUY, price=100.0)
    qty = rm.size_position(sig, free_quote_balance=100_000_000.0)
    # notional should not exceed 100
    assert qty * sig.price <= 100.0 + 1e-9


def test_evaluate_rejects_when_already_in_position():
    rm = RiskManager(_cfg())
    pf = Portfolio()
    pf.on_fill("BTCUSDT", "BUY", qty=0.01, price=100.0)
    sig = Signal("BTCUSDT", SignalType.BUY, price=100.0)
    decision = rm.evaluate(sig, qty=0.5, portfolio=pf, marks={"BTCUSDT": 100.0})
    assert not decision.approved
    assert "already" in decision.reason


def test_evaluate_rejects_max_open_positions():
    rm = RiskManager(_cfg(max_open_positions=1))
    pf = Portfolio()
    pf.on_fill("BTCUSDT", "BUY", qty=0.01, price=100.0)
    sig = Signal("ETHUSDT", SignalType.BUY, price=200.0)
    decision = rm.evaluate(sig, qty=0.1, portfolio=pf, marks={"BTCUSDT": 100.0, "ETHUSDT": 200.0})
    assert not decision.approved


def test_evaluate_kills_on_daily_loss():
    rm = RiskManager(_cfg(daily_loss_limit=10.0))
    pf = Portfolio()
    pf.daily_pnl = -20.0
    sig = Signal("BTCUSDT", SignalType.BUY, price=100.0)
    decision = rm.evaluate(sig, qty=0.5, portfolio=pf, marks={"BTCUSDT": 100.0})
    assert not decision.approved
    assert rm.kill_switch is True


def test_evaluate_rejects_sell_without_position():
    rm = RiskManager(_cfg())
    pf = Portfolio()
    sig = Signal("BTCUSDT", SignalType.SELL, price=100.0)
    decision = rm.evaluate(sig, qty=0.1, portfolio=pf, marks={"BTCUSDT": 100.0})
    assert not decision.approved


def test_evaluate_approves_normal_buy():
    rm = RiskManager(_cfg())
    pf = Portfolio()
    sig = Signal("BTCUSDT", SignalType.BUY, price=100.0)
    decision = rm.evaluate(sig, qty=0.5, portfolio=pf, marks={"BTCUSDT": 100.0})
    assert decision.approved
