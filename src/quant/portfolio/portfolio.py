"""Lightweight portfolio tracker.

Tracks open positions, realised PnL, and provides notional/exposure helpers.
The exchange is the source of truth for balances; this layer is a local view
used by the strategy and risk manager between order events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Position:
    symbol: str
    qty: float
    avg_price: float
    opened_at: datetime
    stop_loss: float | None = None
    take_profit: float | None = None

    def notional(self, mark_price: float) -> float:
        return abs(self.qty) * mark_price

    def unrealised_pnl(self, mark_price: float) -> float:
        return (mark_price - self.avg_price) * self.qty


@dataclass
class Portfolio:
    quote_asset: str = "USDT"
    allow_short: bool = False
    positions: dict[str, Position] = field(default_factory=dict)
    realised_pnl: float = 0.0
    daily_pnl: float = 0.0
    _day: str = field(default_factory=lambda: datetime.now(timezone.utc).date().isoformat())

    def roll_day(self) -> bool:
        """Reset daily PnL if the UTC date has changed. Returns True on roll."""
        today = datetime.now(timezone.utc).date().isoformat()
        if today != self._day:
            self._day = today
            self.daily_pnl = 0.0
            return True
        return False

    # Back-compat alias used internally.
    _roll_day = roll_day

    def on_fill(self, symbol: str, side: str, qty: float, price: float) -> None:
        self.roll_day()
        side = side.upper()
        signed_qty = qty if side == "BUY" else -qty
        pos = self.positions.get(symbol)
        if pos is None:
            if side == "SELL" and not self.allow_short:
                # Spot can't short; ignore stray sells.
                return
            self.positions[symbol] = Position(
                symbol=symbol,
                qty=signed_qty,
                avg_price=price,
                opened_at=datetime.now(timezone.utc),
            )
            return

        new_qty = pos.qty + signed_qty
        # Position increase (same direction).
        if pos.qty * signed_qty > 0:
            total_cost = pos.qty * pos.avg_price + signed_qty * price
            pos.qty = new_qty
            pos.avg_price = total_cost / new_qty if new_qty != 0 else 0.0
            return

        # Position decrease / close / flip (opposite direction).
        closed_qty = min(abs(signed_qty), abs(pos.qty))
        pnl = (price - pos.avg_price) * (closed_qty if pos.qty > 0 else -closed_qty)
        self.realised_pnl += pnl
        self.daily_pnl += pnl
        if abs(new_qty) < 1e-12:
            self.positions.pop(symbol, None)
        elif (pos.qty > 0) != (new_qty > 0) and self.allow_short:
            # Position flipped: residual qty opens a fresh leg at the fill price.
            pos.qty = new_qty
            pos.avg_price = price
            pos.opened_at = datetime.now(timezone.utc)
        else:
            pos.qty = new_qty

    def total_notional(self, marks: dict[str, float]) -> float:
        return sum(p.notional(marks.get(s, p.avg_price)) for s, p in self.positions.items())

    def open_count(self) -> int:
        return len(self.positions)

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions
