from quant.strategies.base import Signal, SignalType, Strategy
from quant.strategies.ema_crossover import EmaCrossoverStrategy
from quant.strategies.mean_reversion import MeanReversionStrategy

REGISTRY: dict[str, type[Strategy]] = {
    "ema_crossover": EmaCrossoverStrategy,
    "mean_reversion": MeanReversionStrategy,
}


def build_strategy(name: str, params: dict) -> Strategy:
    if name not in REGISTRY:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(REGISTRY)}")
    return REGISTRY[name](**params)


__all__ = [
    "Signal",
    "SignalType",
    "Strategy",
    "EmaCrossoverStrategy",
    "MeanReversionStrategy",
    "REGISTRY",
    "build_strategy",
]
