"""Pre-trade risk checks and position sizing.

Works for both spot and futures. For futures, set `allow_short=True` and
`leverage` so sizing accounts for margin instead of full notional.
"""

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
    def __init__(
        self,
        cfg: RiskConfig,
        allow_short: bool = False,
        leverage: int = 1,
    ) -> None:
        self.cfg = cfg
        self.allow_short = allow_short
        self.leverage = max(1, int(leverage))
        if self.leverage > self.cfg.max_leverage:
            raise ValueError(
                f"leverage={self.leverage} exceeds max_leverage={self.cfg.max_leverage}"
            )
        self.kill_switch = False

    # -------------------------------------------------------- sizing

    def size_position(self, signal: Signal, free_quote_balance: float) -> float:
        """Size a position so that a stop-out costs at most risk_per_trade_pct of free balance.

        For futures, leverage multiplies notional for the same margin, so we
        scale the cap by leverage.
        """
        risk_capital = free_quote_balance * self.cfg.risk_per_trade_pct
        notional_by_risk = risk_capital / max(self.cfg.stop_loss_pct, 1e-6)
        max_notional = self.cfg.max_position_notional * self.leverage
        notional = min(notional_by_risk, max_notional)
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

        max_notional = self.cfg.max_position_notional * self.leverage
        if notional > max_notional + 1e-6:
            return RiskDecision(False, 0.0, f"notional {notional:.2f} > max {max_notional:.2f}")

        # On spot, SELL is only allowed to close a long.
        if signal.type == SignalType.SELL and not self.allow_short:
            if not portfolio.has_position(signal.symbol):
                return RiskDecision(False, 0.0, "no position to sell")

        # Don't double-up an existing position in the same direction.
        existing = portfolio.positions.get(signal.symbol)
        if existing is not None:
            if signal.type == SignalType.BUY and existing.qty > 0:
                return RiskDecision(False, 0.0, "already long")
            if signal.type == SignalType.SELL and existing.qty < 0:
                return RiskDecision(False, 0.0, "already short")

        # New-position checks (no existing exposure on this symbol).
        if existing is None:
            if portfolio.open_count() >= self.cfg.max_open_positions:
                return RiskDecision(False, 0.0, "max_open_positions reached")
            cap_total = self.cfg.max_total_notional * self.leverage
            projected = portfolio.total_notional(marks) + notional
            if projected > cap_total + 1e-6:
                return RiskDecision(
                    False, 0.0, f"projected exposure {projected:.2f} > max {cap_total:.2f}"
                )

        return RiskDecision(True, qty, "ok")
