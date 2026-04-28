#!/usr/bin/env python
"""Convenience: `python scripts/run_backtest.py --symbol BTCUSDT`."""

import sys

from quant.cli import main

if __name__ == "__main__":
    sys.argv.insert(1, "backtest")
    main()
