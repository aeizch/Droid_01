"""Strategy base class and signal types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

import pandas as pd


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    symbol: str
    type: SignalType
    price: float
    confidence: float = 1.0
    reason: str = ""


class Strategy(ABC):
    """Bar-based strategy. Receives a DataFrame indexed by open_time with OHLCV."""

    name: str = "base"

    @abstractmethod
    def generate(self, symbol: str, frame: pd.DataFrame) -> Signal:
        """Return a Signal for the most recent bar."""

    def warmup_required(self) -> int:
        """Minimum bars required before signals are valid."""
        return 50
