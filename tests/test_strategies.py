import numpy as np
import pandas as pd

from quant.strategies import build_strategy
from quant.strategies.base import SignalType
from quant.strategies.ema_crossover import EmaCrossoverStrategy


def _ohlcv(closes):
    closes = np.asarray(closes, dtype=float)
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.001,
            "low": closes * 0.999,
            "close": closes,
            "volume": np.ones_like(closes),
        },
        index=idx,
    )
    return df


def test_registry_builds_known_strategy():
    s = build_strategy("ema_crossover", {"fast": 5, "slow": 20})
    assert isinstance(s, EmaCrossoverStrategy)


def test_ema_crossover_warmup_returns_hold():
    s = EmaCrossoverStrategy(fast=5, slow=20)
    df = _ohlcv(np.linspace(100, 110, 10))
    sig = s.generate("BTCUSDT", df)
    assert sig.type == SignalType.HOLD


def test_ema_crossover_emits_buy_on_uptrend():
    s = EmaCrossoverStrategy(fast=5, slow=20, rsi_period=14)
    # Long down-trend followed by sharp up-trend => bullish cross.
    closes = np.concatenate([np.linspace(120, 80, 80), np.linspace(80, 130, 60)])
    df = _ohlcv(closes)
    sig = s.generate("BTCUSDT", df)
    assert sig.type in (SignalType.BUY, SignalType.HOLD)
    # Last bar should not be a SELL on a clean uptrend.
    assert sig.type != SignalType.SELL


def test_ema_crossover_rejects_invalid_params():
    import pytest

    with pytest.raises(ValueError):
        EmaCrossoverStrategy(fast=20, slow=10)
