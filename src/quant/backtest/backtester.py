"""Bar-by-bar backtester.

Replays historical klines through a strategy. Trades fill at the next bar's
open to avoid look-ahead. Applies a flat fee in bps per side.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant.strategies.base import SignalType, Strategy
from quant.utils.logging import get_logger

log = get_logger("backtest")


@dataclass
class Trade:
    symbol: str
    side: str
    qty: float
    price: float
    ts: pd.Timestamp
    pnl: float = 0.0


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[Trade] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        m = self.metrics
        return (
            f"Trades: {int(m.get('n_trades', 0))} | "
            f"Win rate: {m.get('win_rate', 0):.1%} | "
            f"Total return: {m.get('total_return', 0):.2%} | "
            f"Sharpe: {m.get('sharpe', 0):.2f} | "
            f"Max DD: {m.get('max_drawdown', 0):.2%}"
        )


class Backtester:
    def __init__(
        self,
        strategy: Strategy,
        initial_cash: float = 10_000.0,
        fee_bps: float = 10.0,
        position_pct: float = 1.0,
    ) -> None:
        self.strategy = strategy
        self.initial_cash = initial_cash
        self.fee_rate = fee_bps / 10_000.0
        self.position_pct = position_pct  # fraction of cash to deploy per BUY

    def run(self, frame: pd.DataFrame, symbol: str = "SYM") -> BacktestResult:
        if "open" not in frame.columns or "close" not in frame.columns:
            raise ValueError("frame must include open/high/low/close columns")

        cash = self.initial_cash
        position_qty = 0.0
        avg_price = 0.0
        equity: list[float] = []
        trades: list[Trade] = []
        warmup = self.strategy.warmup_required()

        # Generate signal at bar i, fill at bar i+1 open.
        for i in range(len(frame) - 1):
            window = frame.iloc[: i + 1]
            if len(window) < warmup:
                equity.append(cash + position_qty * float(frame["close"].iloc[i]))
                continue

            sig = self.strategy.generate(symbol, window)
            next_open = float(frame["open"].iloc[i + 1])
            ts = frame.index[i + 1]

            if sig.type == SignalType.BUY and position_qty == 0 and cash > 0:
                spend = cash * self.position_pct
                qty = spend / next_open
                fee = spend * self.fee_rate
                cash -= spend + fee
                position_qty += qty
                avg_price = next_open
                trades.append(Trade(symbol, "BUY", qty, next_open, ts))

            elif sig.type == SignalType.SELL and position_qty > 0:
                proceeds = position_qty * next_open
                fee = proceeds * self.fee_rate
                pnl = (next_open - avg_price) * position_qty - fee
                cash += proceeds - fee
                trades.append(Trade(symbol, "SELL", position_qty, next_open, ts, pnl=pnl))
                position_qty = 0.0
                avg_price = 0.0

            equity.append(cash + position_qty * float(frame["close"].iloc[i + 1]))

        # pad first row
        if len(equity) < len(frame):
            equity.insert(0, self.initial_cash)
        equity_curve = pd.Series(equity[: len(frame)], index=frame.index, name="equity")

        return BacktestResult(
            equity_curve=equity_curve,
            trades=trades,
            metrics=self._metrics(equity_curve, trades),
        )

    @staticmethod
    def _metrics(equity: pd.Series, trades: list[Trade]) -> dict[str, float]:
        if equity.empty:
            return {}
        returns = equity.pct_change().dropna()
        # Annualisation factor — assume 15m bars by default; use 365d.
        # 365 * 24 * 4 = 35040 fifteen-minute bars per year.
        ann = np.sqrt(35040)
        sharpe = (returns.mean() / returns.std() * ann) if returns.std() > 0 else 0.0
        running_max = equity.cummax()
        dd = (equity / running_max - 1).min()
        wins = [t for t in trades if t.pnl > 0]
        sells = [t for t in trades if t.side == "SELL"]
        return {
            "n_trades": float(len(sells)),
            "win_rate": (len(wins) / len(sells)) if sells else 0.0,
            "total_return": equity.iloc[-1] / equity.iloc[0] - 1.0,
            "sharpe": float(sharpe),
            "max_drawdown": float(dd),
        }
