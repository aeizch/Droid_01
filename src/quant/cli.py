"""Command-line entry point."""

from __future__ import annotations

import sys
from pathlib import Path

import click
import pandas as pd

from quant.backtest.backtester import Backtester
from quant.config import load_config, load_secrets
from quant.runner import LiveRunner
from quant.strategies import build_strategy
from quant.utils.logging import get_logger, setup_logging


@click.group()
@click.option("--config", "config_path", default="config.yaml", show_default=True,
              type=click.Path(exists=True, dir_okay=False))
@click.pass_context
def cli(ctx: click.Context, config_path: str) -> None:
    """Crypto Quant Trading System."""
    cfg = load_config(config_path)
    setup_logging(cfg.logging.level, cfg.logging.file)
    ctx.obj = {"cfg": cfg, "config_path": config_path}


@cli.command()
@click.option("--yes-live", is_flag=True,
              help="Bypass interactive confirmation when LIVE_TRADING=true and not testnet.")
@click.pass_context
def run(ctx: click.Context, yes_live: bool) -> None:
    """Start the live trading loop (dry-run / testnet / live, controlled by .env)."""
    cfg = ctx.obj["cfg"]
    secrets = load_secrets()
    log = get_logger("cli")

    if secrets.live_trading and not secrets.testnet and not yes_live:
        click.echo(click.style(
            "WARNING: LIVE_TRADING=true and BINANCE_TESTNET=false. "
            "This will trade with REAL money.", fg="red", bold=True))
        if not click.confirm("Type 'y' to proceed", default=False):
            click.echo("Aborted.")
            sys.exit(1)

    runner = LiveRunner(cfg, secrets)
    runner.run()


@cli.command()
@click.option("--symbol", required=True, help="Symbol to backtest, e.g. BTCUSDT")
@click.option("--days", default=30, show_default=True, type=int)
@click.option("--cash", default=10_000.0, show_default=True, type=float)
@click.option("--fee-bps", default=10.0, show_default=True, type=float)
@click.option("--csv", "csv_path", default=None, type=click.Path(dir_okay=False),
              help="Use a local CSV (open_time,open,high,low,close,volume) instead of the API.")
@click.pass_context
def backtest(ctx: click.Context, symbol: str, days: int, cash: float,
             fee_bps: float, csv_path: str | None) -> None:
    """Run a backtest of the configured strategy on historical klines."""
    cfg = ctx.obj["cfg"]
    log = get_logger("cli")

    if csv_path:
        df = pd.read_csv(csv_path, parse_dates=["open_time"]).set_index("open_time")
    else:
        secrets = load_secrets()
        from quant.exchange.binance_client import BinanceConnector
        conn = BinanceConnector(secrets.api_key, secrets.api_secret, testnet=secrets.testnet)
        # Approximate: fetch up to ~limit bars. Binance caps at 1000 per call.
        bars_per_day = {
            "1m": 1440, "3m": 480, "5m": 288, "15m": 96, "30m": 48,
            "1h": 24, "2h": 12, "4h": 6, "1d": 1,
        }.get(cfg.interval, 96)
        wanted = min(days * bars_per_day, 1000)
        df = conn.get_klines(symbol, cfg.interval, limit=wanted)

    strategy = build_strategy(cfg.strategy.name, cfg.strategy.params)
    bt = Backtester(strategy=strategy, initial_cash=cash, fee_bps=fee_bps)
    result = bt.run(df, symbol)

    click.echo(result.summary())
    out_dir = Path("logs")
    out_dir.mkdir(exist_ok=True)
    eq_path = out_dir / f"equity_{symbol}.csv"
    result.equity_curve.to_csv(eq_path)
    click.echo(f"Equity curve: {eq_path}")


@cli.command()
@click.pass_context
def doctor(ctx: click.Context) -> None:
    """Check connectivity and credentials."""
    secrets = load_secrets()
    from quant.exchange.binance_client import BinanceConnector
    conn = BinanceConnector(secrets.api_key, secrets.api_secret, testnet=secrets.testnet)
    click.echo(f"Testnet: {secrets.testnet}")
    click.echo(f"Ping: {'OK' if conn.ping() else 'FAIL'}")
    click.echo(f"Server time: {conn.server_time()}")
    try:
        bal = conn.get_free_balance("USDT")
        click.echo(f"Free USDT: {bal}")
    except Exception as e:
        click.echo(f"Account fetch failed: {e}")


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
