"""Pre-trade risk checks and position sizing.

All caps are computed dynamically from the starting balance the runner
snapshots from Binance at session start (and at each UTC day roll). There
are no hard-coded dollar limits — top up the account and they scale.
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
        # Snapshot of available balance at session start / day roll. Set by the
        # runner before the first tick. Cap calculations rely on it.
        self.starting_balance: float = 0.0

    # -------------------------------------------------------- balance snapshot

    def set_starting_balance(self, amount: float) -> None:
        if amount < 0:
            raise ValueError("starting balance cannot be negative")
        self.starting_balance = float(amount)
        # Re-arm the kill switch on day roll.
        self.kill_switch = False
        log.info("Risk starting balance snapshot: %.4f", self.starting_balance)

    # -------------------------------------------------------- derived caps

    def _max_position_notional(self) -> float:
        return self.starting_balance * self.cfg.max_position_pct * self.leverage

    def _max_total_notional(self) -> float:
        return self.starting_balance * self.cfg.max_total_pct * self.leverage

    def _daily_loss_threshold(self) -> float:
        return self.starting_balance * self.cfg.daily_loss_pct

    # -------------------------------------------------------- sizing

    def size_position(self, signal: Signal, free_balance: float) -> float:
        """Size a position using the smaller of:
          (a) risk-budget sizing: lose at most risk_per_trade_pct of *current*
              free balance on a stop-out, and
          (b) the per-position margin cap derived from starting balance.
        """
        if signal.price <= 0 or self.starting_balance <= 0:
            return 0.0
        risk_capital = max(free_balance, 0.0) * self.cfg.risk_per_trade_pct
        notional_by_risk = risk_capital / max(self.cfg.stop_loss_pct, 1e-6)
        notional = min(notional_by_risk, self._max_position_notional())
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

        if self.starting_balance <= 0:
            return RiskDecision(False, 0.0, "starting balance not set / zero")

        loss_threshold = self._daily_loss_threshold()
        if portfolio.daily_pnl <= -loss_threshold:
            self.kill_switch = True
            log.warning(
                "Daily loss limit hit (pnl=%.2f, threshold=-%.2f) — kill switch engaged",
                portfolio.daily_pnl, loss_threshold,
            )
            return RiskDecision(False, 0.0, "daily loss limit hit")

        notional = qty * signal.price
        if notional <= 0:
            return RiskDecision(False, 0.0, "zero notional")

        cap_pos = self._max_position_notional()
        if notional > cap_pos + 1e-6:
            return RiskDecision(False, 0.0, f"notional {notional:.2f} > max {cap_pos:.2f}")

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
            cap_total = self._max_total_notional()
            projected = portfolio.total_notional(marks) + notional
            if projected > cap_total + 1e-6:
                return RiskDecision(
                    False, 0.0, f"projected exposure {projected:.2f} > max {cap_total:.2f}"
                )

        return RiskDecision(True, qty, "ok")
