# Crypto Quant Trading System

An automated quantitative trading system for crypto, with execution on
**Binance Spot or USDT-M Futures** (testnet by default). Built in Python,
with a clean strategy / risk / execution split, a backtester, and safety
rails so you can iterate without losing real money.

> **WARNING — CRYPTO TRADING CARRIES SUBSTANTIAL FINANCIAL RISK.** This
> code is provided for educational and research purposes. You are solely
> responsible for any orders sent from your account. Always validate on
> testnet, then with small amounts, before scaling.

---

## Features

- **Binance Spot + USDT-M Futures connectors** (REST) with testnet support,
  symbol filters (LOT_SIZE, PRICE_FILTER, MIN_NOTIONAL), and Decimal-safe
  quantisation.
- **Leverage and shorts** on futures. Per-symbol leverage and margin type
  (ISOLATED/CROSSED) applied at startup. Both long and short signals
  supported. `reduce_only` flag is set on stop-loss / take-profit exits.
- **Strategy framework** with two reference strategies:
  - `ema_crossover` — EMA fast/slow crossover with RSI confirmation.
  - `mean_reversion` — Bollinger-band mean reversion with RSI filter.
- **Risk manager** — per-trade sizing, max position notional, max total
  exposure, max open positions, daily loss kill-switch, stop-loss /
  take-profit, **hard leverage cap independent of exchange settings**.
- **Order manager** — market or limit orders, anti-flap throttling,
  dry-run mode that never hits the wire.
- **Backtester** — bar-by-bar replay with next-open fills (no
  look-ahead), commissions, equity curve, Sharpe / drawdown / win-rate.
- **CLI**: `quant run`, `quant backtest`, `quant doctor`.
- **Tests** — indicators, strategies, risk, portfolio, backtester, futures.

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

Pick spot or futures in `config.yaml` under `exchange.market_type`.
Get free testnet keys for the matching market:

- **Spot testnet**: <https://testnet.binance.vision/>
- **Futures testnet**: <https://testnet.binancefuture.com/>

> **Spot and futures testnets have separate API keys** — make sure the keys
> in your `.env` match the `market_type` in `config.yaml`.

Tweak strategy, leverage, and risk in `config.yaml`.

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

## Futures trading — small-amount live playbook

Futures multiplies both gains and losses by leverage. The recommended path:

1. **Backtest first.**
   ```bash
   quant backtest --symbol BTCUSDT --days 90
   ```
   You want a positive total return and a Sharpe > ~1 over a meaningful
   sample before risking real money.

2. **Soak on futures testnet for at least a few days.** Set
   `LIVE_TRADING=true` with `BINANCE_TESTNET=true` and futures testnet
   API keys. Watch for: order rejections from filters, runaway drawdowns,
   flapping signals.

3. **Conservative live config.** The shipped `config.yaml` is already
   tuned for a $30 USDT account on USDT-M futures at 2x leverage:

   ```yaml
   exchange:
     market_type: futures
     leverage: 2
     margin_type: ISOLATED
   universe: [BTCUSDT]                # one symbol on a tiny budget
   risk:
     max_position_notional: 14.0      # $14 margin -> $28 notional at 2x
     max_total_notional: 14.0         # one position at a time
     max_open_positions: 1
     risk_per_trade_pct: 0.02         # 2% of equity per stop-out
     daily_loss_limit: 5.0            # ~17% of $30 — hard kill switch
     stop_loss_pct: 0.02
     take_profit_pct: 0.04
     max_leverage: 2
   ```

## Tiny-account playbook ($10–$50 balance)

Binance USDT-M futures has a per-order **minimum notional of about $20**.
With leverage `L`, that means each position needs at least `$20 / L` of
margin. The system computes target notional as:

```
notional_by_risk = balance × risk_per_trade_pct / stop_loss_pct
max_notional     = max_position_notional × leverage
target_notional  = min(notional_by_risk, max_notional)
```

For an order to fly, **`target_notional × (1 + min_notional_buffer_pct)`
must clear the exchange minimum**. The order manager rejects below-min
orders pre-flight (you'll see `Reject ... below min` in the log) so they
never get bounced by the exchange.

### Worked example: $30 balance, 2x leverage

| Setting                         | Value     |
| ------------------------------- | --------- |
| `balance` (free USDT)           | 30.00     |
| `leverage`                      | 2         |
| `risk_per_trade_pct`            | 0.02      |
| `stop_loss_pct`                 | 0.02      |
| `max_position_notional` (margin)| 14.00     |
| `min_notional_buffer_pct`       | 0.10      |

- `notional_by_risk = 30 × 0.02 / 0.02 = $30` notional.
- `max_notional     = 14 × 2          = $28` notional.
- `target_notional  = min($30, $28)   = $28` notional.
- Min-notional check: `$28 ≥ $20 × 1.10 = $22` ✅
- Margin used: `$28 / 2 = $14` of `$30` (~47%) — leaves room for adverse moves.
- A stop-out costs: `$28 × 0.02 = $0.56` per trade.
- Daily kill switch trips at `-$5` (~9 stops or one nasty 17% adverse move).

### Worked example: $10 balance

This is at the practical floor and is **not recommended** for live money.
You can only run one position with effectively all of your equity tied up
as margin, leaving zero buffer. The math:

- To clear $20 min notional at 2x, you need $10 of margin — your entire
  balance. Any unrealised loss eats into that margin and risks immediate
  liquidation.
- If you must, set `max_position_notional: 10`, `max_total_notional: 10`,
  `max_open_positions: 1`, `risk_per_trade_pct: 0.05`, and accept that
  one position pinning all your margin is the design. Strongly consider
  3x leverage instead so margin is `$20 / 3 ≈ $6.67` of `$10`, leaving
  ~33% buffer — but every leverage step compounds liquidation risk.

### Things that go wrong on tiny accounts

- **Sub-min-notional rejections** — fixed by the pre-flight check, but
  the log will keep saying `Reject` until sizing produces ≥$22 notional.
  Bump `risk_per_trade_pct`, `max_position_notional`, or `leverage`.
- **Liquidation from a single 8% move** at 10x leverage. Keep leverage
  at 2x or 3x while the strategy is unproven.
- **Funding rates** on perpetuals bite harder when balance is small.
  At -0.01% funding 3×/day on a $28 notional, that's `$0.0084/day` — not
  much, but it adds up if a position lingers.

4. **Pre-flight on the live account:**
   ```bash
   quant doctor          # confirms futures account, balance > 0
   ```

5. **Start the bot:**
   ```bash
   quant run
   ```
   Confirm interactively when warned about real money. Watch the logs
   for the first few signals and fills before walking away.

### Futures-specific safety notes

- **`risk.max_leverage` is a hard cap** independent of what the exchange
  allows. If you change `exchange.leverage` above this cap, the runner
  refuses to start.
- **`ISOLATED` margin** is recommended over `CROSSED` for systematic
  strategies — a blowup on one symbol cannot drag the rest of the
  account into liquidation.
- **Stop-loss and take-profit exits** are submitted with `reduce_only=true`,
  so they can never accidentally flip a closed position into the opposite
  direction.
- **Funding rates** apply on perpetuals — the system doesn't currently
  factor funding into PnL. Long-running positions can accrue meaningful
  funding cost; check the Binance funding history occasionally.
- **Liquidation risk grows with leverage.** A 2x position with a 50%
  adverse move is liquidated; a 10x with 10%; a 25x with 4%. Keep
  leverage low until you're confident the strategy stays out of those
  moves.

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
