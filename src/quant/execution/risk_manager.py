"""Pre-trade risk checks and position sizing."""

from __future__ import annotations

from dataclasses import dataclass

from quant.config import RiskConfig
from quant.portfolio.portfolio import Portfolio
from quant.strategies.base import Signal, SignalType
from quant.utils.logging import get_logger

log = get_logger("execution.risk")


@dataclass
class RiskDecision:
    approved: bool
    qty: float
    reason: str


class RiskManager:
    """Enforces hard limits and computes position size."""

    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg
        self.kill_switch = False

    # -------------------------------------------------------- sizing

    def size_position(self, signal: Signal, free_quote_balance: float) -> float:
        """Notional sized to risk_per_trade_pct of free balance, capped by max_position_notional."""
        notional = min(
            free_quote_balance * self.cfg.risk_per_trade_pct
            / max(self.cfg.stop_loss_pct, 1e-6),
            self.cfg.max_position_notional,
        )
        if signal.price <= 0:
            return 0.0
        return notional / signal.price

    # -------------------------------------------------------- gating

    def evaluate(
        self,
        signal: Signal,
        qty: float,
        portfolio: Portfolio,
        marks: dict[str, float],
    ) -> RiskDecision:
        if self.kill_switch:
            return RiskDecision(False, 0.0, "kill switch active")

        if signal.type == SignalType.HOLD:
            return RiskDecision(False, 0.0, "hold signal")

        if portfolio.daily_pnl <= -abs(self.cfg.daily_loss_limit):
            self.kill_switch = True
            log.warning("Daily loss limit hit (%.2f) — kill switch engaged", portfolio.daily_pnl)
            return RiskDecision(False, 0.0, "daily loss limit hit")

        notional = qty * signal.price
        if notional <= 0:
            return RiskDecision(False, 0.0, "zero notional")

        if notional > self.cfg.max_position_notional:
            return RiskDecision(False, 0.0, f"notional {notional:.2f} > max_position_notional")

        # SELL is only allowed if we have a position (spot, no short).
        if signal.type == SignalType.SELL and not portfolio.has_position(signal.symbol):
            return RiskDecision(False, 0.0, "no position to sell")

        if signal.type == SignalType.BUY:
            if portfolio.has_position(signal.symbol):
                return RiskDecision(False, 0.0, "already in position")
            if portfolio.open_count() >= self.cfg.max_open_positions:
                return RiskDecision(False, 0.0, "max_open_positions reached")
            projected = portfolio.total_notional(marks) + notional
            if projected > self.cfg.max_total_notional:
                return RiskDecision(False, 0.0, f"projected exposure {projected:.2f} > max_total")

        return RiskDecision(True, qty, "ok")
