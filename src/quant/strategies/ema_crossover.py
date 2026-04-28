"""EMA crossover with optional RSI confirmation filter."""

from __future__ import annotations

import pandas as pd

from quant.strategies.base import Signal, SignalType, Strategy
from quant.utils.indicators import ema, rsi


class EmaCrossoverStrategy(Strategy):
    name = "ema_crossover"

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        rsi_period: int = 14,
        rsi_buy_max: float = 70.0,
        rsi_sell_min: float = 30.0,
    ) -> None:
        if fast >= slow:
            raise ValueError("fast must be < slow")
        self.fast = fast
        self.slow = slow
        self.rsi_period = rsi_period
        self.rsi_buy_max = rsi_buy_max
        self.rsi_sell_min = rsi_sell_min

    def warmup_required(self) -> int:
        return max(self.slow, self.rsi_period) + 5

    def generate(self, symbol: str, frame: pd.DataFrame) -> Signal:
        close = frame["close"]
        if len(close) < self.warmup_required():
            return Signal(symbol, SignalType.HOLD, float(close.iloc[-1]), reason="warmup")

        fast_ema = ema(close, self.fast)
        slow_ema = ema(close, self.slow)
        r = rsi(close, self.rsi_period)

        prev_diff = fast_ema.iloc[-2] - slow_ema.iloc[-2]
        cur_diff = fast_ema.iloc[-1] - slow_ema.iloc[-1]
        last_price = float(close.iloc[-1])
        last_rsi = float(r.iloc[-1])

        # Bullish crossover.
        if prev_diff <= 0 < cur_diff and last_rsi <= self.rsi_buy_max:
            return Signal(
                symbol,
                SignalType.BUY,
                last_price,
                confidence=min(1.0, abs(cur_diff) / max(last_price * 1e-4, 1e-9)),
                reason=f"EMA{self.fast}>{self.slow} cross, RSI={last_rsi:.1f}",
            )
        # Bearish crossover.
        if prev_diff >= 0 > cur_diff and last_rsi >= self.rsi_sell_min:
            return Signal(
                symbol,
                SignalType.SELL,
                last_price,
                confidence=min(1.0, abs(cur_diff) / max(last_price * 1e-4, 1e-9)),
                reason=f"EMA{self.fast}<{self.slow} cross, RSI={last_rsi:.1f}",
            )
        return Signal(symbol, SignalType.HOLD, last_price, reason="no cross")
