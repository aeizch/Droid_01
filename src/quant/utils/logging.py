"""Structured logging setup."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from rich.logging import RichHandler


def setup_logging(level: str = "INFO", file: str | None = None) -> logging.Logger:
    log_level = getattr(logging, level.upper(), logging.INFO)
    handlers: list[logging.Handler] = [
        RichHandler(rich_tracebacks=True, show_path=False, markup=False)
    ]
    if file:
        Path(file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(file)
        fh.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        handlers.append(fh)

    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )
    # Quiet noisy libs.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("binance").setLevel(logging.WARNING)

    log = logging.getLogger("quant")
    log.info("Logging initialised at %s (file=%s)", level, file)
    return log


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"quant.{name}")


# Ensure stdout doesn't buffer in containers.
try:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
except (AttributeError, OSError):
    pass
