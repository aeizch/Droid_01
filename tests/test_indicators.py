import numpy as np
import pandas as pd

from quant.utils.indicators import atr, bollinger, ema, macd, rsi, sma


def _series(values):
    return pd.Series(values, dtype=float)


def test_sma_basic():
    s = _series([1, 2, 3, 4, 5])
    out = sma(s, 3)
    assert np.isnan(out.iloc[0])
    assert out.iloc[2] == 2.0
    assert out.iloc[4] == 4.0


def test_ema_monotonic_to_input():
    s = _series([10] * 5 + [20] * 5)
    out = ema(s, 3).dropna()
    assert out.iloc[0] <= out.iloc[-1]
    assert out.iloc[-1] < 20.0  # never reaches the new level instantly


def test_rsi_bounds():
    rng = np.random.default_rng(0)
    s = _series(rng.normal(loc=100, scale=2, size=200).cumsum())
    r = rsi(s, 14).dropna()
    assert (r >= 0).all() and (r <= 100).all()


def test_atr_positive():
    n = 50
    high = _series(np.linspace(110, 120, n))
    low = _series(np.linspace(100, 110, n))
    close = (high + low) / 2
    a = atr(high, low, close, 14).dropna()
    assert (a >= 0).all()


def test_bollinger_ordering():
    s = _series(np.linspace(100, 120, 60))
    bb = bollinger(s, 20, 2.0).dropna()
    assert (bb["upper"] >= bb["mid"]).all()
    assert (bb["mid"] >= bb["lower"]).all()


def test_macd_columns():
    s = _series(np.linspace(100, 200, 100))
    m = macd(s)
    assert {"macd", "signal", "hist"}.issubset(m.columns)
