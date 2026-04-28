"""Bollinger-band mean reversion strategy."""

from __future__ import annotations

import pandas as pd

from quant.strategies.base import Signal, SignalType, Strategy
from quant.utils.indicators import bollinger, rsi


class MeanReversionStrategy(Strategy):
    name = "mean_reversion"

    def __init__(
        self,
        period: int = 20,
        num_std: float = 2.0,
        rsi_period: int = 14,
        rsi_buy_max: float = 35.0,
        rsi_sell_min: float = 65.0,
    ) -> None:
        self.period = period
        self.num_std = num_std
        self.rsi_period = rsi_period
        self.rsi_buy_max = rsi_buy_max
        self.rsi_sell_min = rsi_sell_min

    def warmup_required(self) -> int:
        return max(self.period, self.rsi_period) + 5

    def generate(self, symbol: str, frame: pd.DataFrame) -> Signal:
        close = frame["close"]
        if len(close) < self.warmup_required():
            return Signal(symbol, SignalType.HOLD, float(close.iloc[-1]), reason="warmup")

        bb = bollinger(close, self.period, self.num_std)
        r = rsi(close, self.rsi_period)
        last_price = float(close.iloc[-1])
        last_rsi = float(r.iloc[-1])
        upper = float(bb["upper"].iloc[-1])
        lower = float(bb["lower"].iloc[-1])

        if last_price <= lower and last_rsi <= self.rsi_buy_max:
            return Signal(
                symbol, SignalType.BUY, last_price, confidence=0.7,
                reason=f"price<lower BB, RSI={last_rsi:.1f}",
            )
        if last_price >= upper and last_rsi >= self.rsi_sell_min:
            return Signal(
                symbol, SignalType.SELL, last_price, confidence=0.7,
                reason=f"price>upper BB, RSI={last_rsi:.1f}",
            )
        return Signal(symbol, SignalType.HOLD, last_price, reason="in band")
