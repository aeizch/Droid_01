from quant.config import RiskConfig
from quant.execution.risk_manager import RiskManager
from quant.portfolio.portfolio import Portfolio
from quant.strategies.base import Signal, SignalType


def _cfg(**overrides):
    base = dict(
        max_position_pct=0.50,
        max_total_pct=1.00,
        max_open_positions=2,
        risk_per_trade_pct=0.01,
        daily_loss_pct=0.10,
        stop_loss_pct=0.02,
        take_profit_pct=0.04,
        max_leverage=1,
    )
    base.update(overrides)
    return RiskConfig(**base)


def _rm(cfg=None, starting=100.0, **kwargs) -> RiskManager:
    rm = RiskManager(cfg or _cfg(), **kwargs)
    rm.set_starting_balance(starting)
    return rm


def test_size_position_caps_at_max_position_pct():
    # starting=200, pct=0.5, lev=1 -> cap notional = 100
    rm = _rm(_cfg(max_position_pct=0.50), starting=200.0)
    sig = Signal("BTCUSDT", SignalType.BUY, price=100.0)
    qty = rm.size_position(sig, free_balance=100_000.0)
    assert qty * sig.price <= 100.0 + 1e-9


def test_size_position_uses_current_balance_for_risk_budget():
    # risk-budget sizing = free_balance * risk_pct / stop_pct
    # 50 * 0.01 / 0.02 = 25 notional, below the 100 cap -> chooses 25.
    rm = _rm(_cfg(max_position_pct=0.50, risk_per_trade_pct=0.01, stop_loss_pct=0.02),
             starting=200.0)
    sig = Signal("BTCUSDT", SignalType.BUY, price=100.0)
    qty = rm.size_position(sig, free_balance=50.0)
    assert abs(qty * sig.price - 25.0) < 1e-6


def test_size_position_zero_when_no_starting_balance():
    rm = RiskManager(_cfg())  # starting_balance defaults to 0
    sig = Signal("BTCUSDT", SignalType.BUY, price=100.0)
    assert rm.size_position(sig, free_balance=1_000.0) == 0.0


def test_evaluate_rejects_when_already_in_position():
    rm = _rm(starting=100.0)
    pf = Portfolio()
    pf.on_fill("BTCUSDT", "BUY", qty=0.01, price=100.0)
    sig = Signal("BTCUSDT", SignalType.BUY, price=100.0)
    decision = rm.evaluate(sig, qty=0.5, portfolio=pf, marks={"BTCUSDT": 100.0})
    assert not decision.approved
    assert "already" in decision.reason


def test_evaluate_rejects_max_open_positions():
    rm = _rm(_cfg(max_open_positions=1), starting=1_000.0)
    pf = Portfolio()
    pf.on_fill("BTCUSDT", "BUY", qty=0.01, price=100.0)
    sig = Signal("ETHUSDT", SignalType.BUY, price=200.0)
    decision = rm.evaluate(sig, qty=0.1, portfolio=pf,
                           marks={"BTCUSDT": 100.0, "ETHUSDT": 200.0})
    assert not decision.approved


def test_evaluate_kills_on_daily_loss_pct():
    rm = _rm(_cfg(daily_loss_pct=0.10), starting=100.0)  # threshold = $10
    pf = Portfolio()
    pf.daily_pnl = -15.0
    sig = Signal("BTCUSDT", SignalType.BUY, price=100.0)
    decision = rm.evaluate(sig, qty=0.5, portfolio=pf, marks={"BTCUSDT": 100.0})
    assert not decision.approved
    assert rm.kill_switch is True


def test_evaluate_rejects_sell_without_position():
    rm = _rm(starting=100.0)
    pf = Portfolio()
    sig = Signal("BTCUSDT", SignalType.SELL, price=100.0)
    decision = rm.evaluate(sig, qty=0.1, portfolio=pf, marks={"BTCUSDT": 100.0})
    assert not decision.approved


def test_evaluate_approves_normal_buy():
    rm = _rm(starting=100.0)
    pf = Portfolio()
    sig = Signal("BTCUSDT", SignalType.BUY, price=100.0)
    decision = rm.evaluate(sig, qty=0.5, portfolio=pf, marks={"BTCUSDT": 100.0})
    assert decision.approved


def test_caps_scale_with_starting_balance():
    """Doubling balance doubles caps. That's the whole point of going dynamic."""
    rm_small = _rm(_cfg(max_position_pct=0.5), starting=50.0)
    rm_big = _rm(_cfg(max_position_pct=0.5), starting=500.0)
    assert rm_big._max_position_notional() == rm_small._max_position_notional() * 10


def test_set_starting_balance_resets_kill_switch():
    rm = _rm(_cfg(daily_loss_pct=0.10), starting=100.0)
    pf = Portfolio()
    pf.daily_pnl = -50.0
    sig = Signal("BTCUSDT", SignalType.BUY, price=100.0)
    rm.evaluate(sig, qty=0.5, portfolio=pf, marks={"BTCUSDT": 100.0})
    assert rm.kill_switch is True

    # Day roll: re-snapshot balance, kill switch re-arms.
    rm.set_starting_balance(120.0)
    assert rm.kill_switch is False
