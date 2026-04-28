"""Configuration loading and validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


class ExchangeConfig(BaseModel):
    name: str = "binance"
    market_type: str = "spot"           # "spot" | "futures"
    quote_asset: str = "USDT"
    recv_window_ms: int = 5000
    leverage: int = 1                   # futures only
    margin_type: str = "ISOLATED"       # futures only: ISOLATED | CROSSED

    @field_validator("market_type")
    @classmethod
    def _mt(cls, v: str) -> str:
        v = v.lower()
        if v not in ("spot", "futures"):
            raise ValueError("market_type must be 'spot' or 'futures'")
        return v

    @field_validator("margin_type")
    @classmethod
    def _mgn(cls, v: str) -> str:
        v = v.upper()
        if v not in ("ISOLATED", "CROSSED"):
            raise ValueError("margin_type must be 'ISOLATED' or 'CROSSED'")
        return v


class StrategyConfig(BaseModel):
    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class RiskConfig(BaseModel):
    max_position_notional: float
    max_total_notional: float
    max_open_positions: int
    risk_per_trade_pct: float
    daily_loss_limit: float
    stop_loss_pct: float
    take_profit_pct: float
    max_leverage: int = 1               # hard cap, even if exchange allows more

    @field_validator("risk_per_trade_pct")
    @classmethod
    def _frac(cls, v: float) -> float:
        if not 0 < v <= 1:
            raise ValueError("risk_per_trade_pct must be in (0, 1]")
        return v

    @field_validator("max_leverage")
    @classmethod
    def _lev(cls, v: int) -> int:
        if v < 1 or v > 125:
            raise ValueError("max_leverage must be in [1, 125]")
        return v


class ExecutionConfig(BaseModel):
    order_type: str = "market"
    limit_offset_bps: int = 5
    min_order_spacing_sec: int = 60
    # Extra cushion above the exchange's MIN_NOTIONAL filter, as a fraction.
    # 0.10 = require target notional to be at least 110% of the exchange minimum,
    # so step-size quantisation can't push us under the line.
    min_notional_buffer_pct: float = 0.10


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str | None = "logs/quant.log"


class Config(BaseModel):
    exchange: ExchangeConfig
    universe: list[str]
    interval: str
    warmup_bars: int = 300
    poll_interval_sec: int = 30
    strategy: StrategyConfig
    risk: RiskConfig
    execution: ExecutionConfig
    logging: LoggingConfig = LoggingConfig()


class Secrets(BaseModel):
    api_key: str
    api_secret: str
    testnet: bool = True
    live_trading: bool = False


def load_config(path: str | Path = "config.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text())
    return Config.model_validate(raw)


def load_secrets(env_path: str | Path | None = None) -> Secrets:
    if env_path is not None:
        load_dotenv(env_path)
    else:
        load_dotenv()

    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    api_secret = os.getenv("BINANCE_API_SECRET", "").strip()
    testnet = os.getenv("BINANCE_TESTNET", "true").lower() == "true"
    live = os.getenv("LIVE_TRADING", "false").lower() == "true"

    if not api_key or not api_secret:
        raise RuntimeError(
            "BINANCE_API_KEY / BINANCE_API_SECRET not set. Copy .env.example to .env."
        )
    return Secrets(api_key=api_key, api_secret=api_secret, testnet=testnet, live_trading=live)
