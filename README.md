# Crypto Quant Trading System

An automated quantitative trading system for crypto, with execution on
**Binance Spot** (testnet by default). Built in Python, with a clean
strategy / risk / execution split, a backtester, and safety rails so you
can iterate without losing real money.

> **WARNING — CRYPTO TRADING CARRIES SUBSTANTIAL FINANCIAL RISK.** This
> code is provided for educational and research purposes. You are solely
> responsible for any orders sent from your account. Always validate on
> testnet, then with small amounts, before scaling.

---

## Features

- **Binance Spot connector** (REST) with testnet support, symbol filters
  (LOT_SIZE, PRICE_FILTER, MIN_NOTIONAL), and Decimal-safe quantisation.
- **Strategy framework** with two reference strategies:
  - `ema_crossover` — EMA fast/slow crossover with RSI confirmation.
  - `mean_reversion` — Bollinger-band mean reversion with RSI filter.
- **Risk manager** — per-trade sizing, max position notional, max total
  exposure, max open positions, daily loss kill-switch, stop-loss /
  take-profit.
- **Order manager** — market or limit orders, anti-flap throttling,
  dry-run mode that never hits the wire.
- **Backtester** — bar-by-bar replay with next-open fills (no
  look-ahead), commissions, equity curve, Sharpe / drawdown / win-rate.
- **CLI**: `quant run`, `quant backtest`, `quant doctor`.
- **Tests** — indicators, strategies, risk, portfolio, backtester.

## Layout

```
src/quant/
  cli.py                  # click entry point: run / backtest / doctor
  config.py               # YAML + .env loaders (pydantic-validated)
  runner.py               # live loop: data -> signals -> risk -> orders
  exchange/binance_client.py
  data/market_data.py
  strategies/             # base, ema_crossover, mean_reversion, registry
  execution/risk_manager.py
  execution/order_manager.py
  portfolio/portfolio.py
  backtest/backtester.py
  utils/indicators.py
  utils/logging.py
config.yaml               # strategy + risk + execution config
.env.example              # copy to .env and add your API keys
tests/                    # pytest suite
```

## Quickstart

### 1. Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .          # exposes the `quant` CLI
```

### 2. Configure

```bash
cp .env.example .env
# edit .env: set BINANCE_API_KEY / BINANCE_API_SECRET
# leave BINANCE_TESTNET=true and LIVE_TRADING=false to start
```

Get free testnet API keys at <https://testnet.binance.vision/>.

Tweak strategy and risk in `config.yaml`.

### 3. Smoke-test connectivity

```bash
quant doctor
```

### 4. Backtest

```bash
quant backtest --symbol BTCUSDT --days 30 --cash 10000
```

Equity curve is written to `logs/equity_BTCUSDT.csv`.

### 5. Run (dry-run by default)

```bash
quant run
```

You'll see lines like:

```
[DRY-RUN] BUY BTCUSDT qty=0.00120000 @ 65432.1000 (EMA12>26 cross, RSI=58.4)
```

No orders are sent to the exchange.

### 6. Trade on testnet (safe)

In `.env`:

```
BINANCE_TESTNET=true
LIVE_TRADING=true
```

Now `quant run` will submit real orders to the **Binance testnet**, which
uses fake balances — perfect for shaking out integration bugs.

### 7. Trade live (real money)

```
BINANCE_TESTNET=false
LIVE_TRADING=true
```

`quant run` will require an interactive `y` confirmation, or pass
`--yes-live` for automation. Start with the smallest possible
`max_position_notional`.

## Safety model

The system has three layers of protection, each independently configurable.

| Layer        | Setting                                   | What it does                                      |
| ------------ | ----------------------------------------- | ------------------------------------------------- |
| Mode gate    | `LIVE_TRADING` env var                    | Master kill: when `false`, no orders are sent.    |
| Network gate | `BINANCE_TESTNET` env var                 | Routes orders to testnet vs. real exchange.       |
| Risk gate    | `risk.*` in `config.yaml`                 | Per-trade sizing, exposure caps, daily loss stop. |

The risk manager's daily loss limit auto-engages a kill switch — once
hit, no further orders are placed until the process restarts.

## Adding a strategy

1. Create `src/quant/strategies/my_strategy.py` subclassing `Strategy`.
2. Implement `generate(symbol, frame) -> Signal` and `warmup_required()`.
3. Register in `src/quant/strategies/__init__.py`:

   ```python
   REGISTRY = {
       "ema_crossover": EmaCrossoverStrategy,
       "mean_reversion": MeanReversionStrategy,
       "my_strategy": MyStrategy,
   }
   ```

4. Set `strategy.name: my_strategy` in `config.yaml` with your params.

## Tests

```bash
PYTHONPATH=src pytest -q
```

## Roadmap (good places to extend)

- WebSocket kline streaming (replace REST polling for sub-minute bars).
- Futures (USDT-M) connector with leverage and funding-rate awareness.
- Persistence: SQLite for trades and equity to survive restarts.
- Portfolio-level optimiser (volatility targeting, correlation caps).
- Walk-forward parameter search and out-of-sample validation.
- Slack / Telegram alert hooks on fills, stops, and kill-switch events.

## License

MIT.
