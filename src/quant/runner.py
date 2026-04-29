"""Live trading runner — polls market data, evaluates strategies, routes orders.

Supports both spot and futures (USDT-M perpetuals). For futures, leverage and
margin type are applied at startup for each symbol in the universe.
"""

from __future__ import annotations

import signal as os_signal
import time
from datetime import datetime, timezone

from binance.exceptions import BinanceAPIException

from quant.config import Config, Secrets
from quant.data.market_data import MarketDataCache
from quant.exchange import build_connector
from quant.exchange.binance_futures import BinanceFuturesConnector
from quant.execution.order_manager import OrderManager
from quant.execution.risk_manager import RiskManager
from quant.portfolio.portfolio import Portfolio
from quant.strategies import build_strategy
from quant.strategies.base import Signal, SignalType
from quant.utils.logging import get_logger

log = get_logger("runner")


class LiveRunner:
    def __init__(self, cfg: Config, secrets: Secrets) -> None:
        self.cfg = cfg
        self.secrets = secrets
        self._stop = False
        self.is_futures = cfg.exchange.market_type == "futures"

        if self.is_futures and cfg.exchange.leverage > cfg.risk.max_leverage:
            raise ValueError(
                f"exchange.leverage={cfg.exchange.leverage} exceeds "
                f"risk.max_leverage={cfg.risk.max_leverage}"
            )

        self.connector = build_connector(
            market_type=cfg.exchange.market_type,
            api_key=secrets.api_key,
            api_secret=secrets.api_secret,
            testnet=secrets.testnet,
            recv_window_ms=cfg.exchange.recv_window_ms,
        )
        if not self.connector.ping():
            raise RuntimeError("Binance ping failed — check network/credentials")

        self.data = MarketDataCache(self.connector, cfg.interval, cfg.warmup_bars)
        self.strategy = build_strategy(cfg.strategy.name, cfg.strategy.params)
        self.portfolio = Portfolio(
            quote_asset=cfg.exchange.quote_asset, allow_short=self.is_futures
        )
        self.risk = RiskManager(
            cfg.risk,
            allow_short=self.is_futures,
            leverage=cfg.exchange.leverage if self.is_futures else 1,
        )
        self.orders = OrderManager(
            self.connector, cfg.execution, self.portfolio, live_trading=secrets.live_trading
        )

        if self.is_futures and secrets.live_trading:
            self._configure_futures()

        # Day stamp tracked so we can re-snapshot starting balance on day roll.
        self._snapshot_day: str | None = None

        os_signal.signal(os_signal.SIGINT, self._handle_signal)
        os_signal.signal(os_signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum: int, frame) -> None:  # noqa: ARG002
        log.warning("Received signal %s — shutting down after current loop", signum)
        self._stop = True

    # ---------------------------------------------------------- futures setup

    def _configure_futures(self) -> None:
        assert isinstance(self.connector, BinanceFuturesConnector)
        for sym in self.cfg.universe:
            try:
                self.connector.set_margin_type(sym, self.cfg.exchange.margin_type)
                log.info("Set %s margin type to %s", sym, self.cfg.exchange.margin_type)
            except BinanceAPIException as e:
                log.warning("Could not set margin type on %s: %s", sym, e.message)
            try:
                self.connector.set_leverage(sym, self.cfg.exchange.leverage)
                log.info("Set %s leverage to %dx", sym, self.cfg.exchange.leverage)
            except BinanceAPIException as e:
                log.warning("Could not set leverage on %s: %s", sym, e.message)

    # ---------------------------------------------------------- main loop

    def run(self) -> None:
        mode = self._mode_str()
        log.info(
            "Starting LiveRunner | %s | market=%s | strategy=%s | symbols=%s | leverage=%dx",
            mode,
            self.cfg.exchange.market_type,
            self.strategy.name,
            self.cfg.universe,
            self.cfg.exchange.leverage if self.is_futures else 1,
        )
        self.data.warmup(self.cfg.universe)

        # Initial balance snapshot — drives every notional cap and the daily kill switch.
        self._refresh_starting_balance()

        while not self._stop:
            try:
                self._maybe_roll_day()
                self._tick()
            except Exception as e:
                log.exception("Tick failed: %s", e)
            time.sleep(self.cfg.poll_interval_sec)

        log.info(
            "Stopped. Realised PnL: %.4f %s",
            self.portfolio.realised_pnl, self.portfolio.quote_asset,
        )

    # ---------------------------------------------------------- balance / day

    def _current_balance(self) -> float:
        """Live: pulled from Binance availableBalance. Dry-run: virtual."""
        if self.secrets.live_trading:
            return self.connector.get_free_balance(self.cfg.exchange.quote_asset)
        return 10_000.0

    def _refresh_starting_balance(self) -> None:
        bal = self._current_balance()
        self.risk.set_starting_balance(bal)
        self._snapshot_day = datetime.now(timezone.utc).date().isoformat()
        log.info(
            "Starting balance for session/day: %.4f %s | "
            "max_position=%.4f | max_total=%.4f | daily_loss_threshold=-%.4f",
            bal, self.cfg.exchange.quote_asset,
            self.risk._max_position_notional(),
            self.risk._max_total_notional(),
            self.risk._daily_loss_threshold(),
        )

    def _maybe_roll_day(self) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        if self._snapshot_day != today:
            log.info("UTC day rolled (%s -> %s) — refreshing starting balance",
                     self._snapshot_day, today)
            self.portfolio.roll_day()
            self._refresh_starting_balance()

    def _tick(self) -> None:
        marks: dict[str, float] = {}
        signals = []
        for sym in self.cfg.universe:
            frame = self.data.refresh(sym)
            sig = self.strategy.generate(sym, frame)
            marks[sym] = sig.price
            signals.append(sig)
            log.debug("Signal %s: %s @ %.4f (%s)", sym, sig.type.value, sig.price, sig.reason)

        free_quote = self._current_balance()

        for sig in signals:
            if sig.type == SignalType.HOLD:
                continue
            qty = self.risk.size_position(sig, free_quote)
            decision = self.risk.evaluate(sig, qty, self.portfolio, marks)
            if not decision.approved:
                log.info("Rejected %s %s: %s", sig.type.value, sig.symbol, decision.reason)
                continue
            self.orders.submit(sig, decision.qty)

        self._check_exits(marks)

    def _check_exits(self, marks: dict[str, float]) -> None:
        """Apply stop-loss / take-profit on open positions (long or short)."""
        sl_pct = self.cfg.risk.stop_loss_pct
        tp_pct = self.cfg.risk.take_profit_pct
        for sym, pos in list(self.portfolio.positions.items()):
            mark = marks.get(sym)
            if mark is None or pos.qty == 0:
                continue
            move = (mark - pos.avg_price) / pos.avg_price
            # For shorts, profit when price falls — flip the sign.
            adj = move if pos.qty > 0 else -move
            if adj <= -sl_pct:
                log.warning("STOP-LOSS triggered on %s (move=%.2f%%, qty=%.6f)",
                            sym, move * 100, pos.qty)
                self._force_close(sym, mark, "stop_loss")
            elif adj >= tp_pct:
                log.info("TAKE-PROFIT triggered on %s (move=%.2f%%, qty=%.6f)",
                         sym, move * 100, pos.qty)
                self._force_close(sym, mark, "take_profit")

    def _force_close(self, symbol: str, mark: float, reason: str) -> None:
        pos = self.portfolio.positions.get(symbol)
        if pos is None or pos.qty == 0:
            return
        # Long -> SELL to close. Short -> BUY to close.
        side = SignalType.SELL if pos.qty > 0 else SignalType.BUY
        sig = Signal(symbol, side, mark, reason=reason)
        self.orders.submit(sig, abs(pos.qty), reduce_only=True)

    def _mode_str(self) -> str:
        if self.secrets.live_trading and not self.secrets.testnet:
            return "LIVE (REAL MONEY)"
        if self.secrets.live_trading and self.secrets.testnet:
            return "TESTNET (live orders to testnet)"
        return "DRY-RUN (no orders sent)"
