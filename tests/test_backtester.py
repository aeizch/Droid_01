import numpy as np
import pandas as pd

from quant.backtest.backtester import Backtester
from quant.strategies.ema_crossover import EmaCrossoverStrategy


def _ohlcv(closes):
    closes = np.asarray(closes, dtype=float)
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.001,
            "low": closes * 0.999,
            "close": closes,
            "volume": np.ones_like(closes),
        },
        index=idx,
    )


def test_backtester_runs_and_produces_metrics():
    closes = np.concatenate([
        np.linspace(100, 80, 80),
        np.linspace(80, 130, 80),
        np.linspace(130, 110, 80),
    ])
    df = _ohlcv(closes)
    strat = EmaCrossoverStrategy(fast=5, slow=20)
    bt = Backtester(strategy=strat, initial_cash=10_000.0, fee_bps=5.0)
    result = bt.run(df, "BTCUSDT")

    assert len(result.equity_curve) == len(df)
    assert "n_trades" in result.metrics
    assert "max_drawdown" in result.metrics
    assert result.equity_curve.iloc[0] > 0
