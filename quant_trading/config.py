from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 100_000.0
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    risk_per_trade: float = 0.02
    max_position_pct: float = 0.95


@dataclass(frozen=True)
class MovingAverageConfig:
    short_window: int = 5
    long_window: int = 20


@dataclass(frozen=True)
class ChannelStrategyConfig:
    lookback: int = 30
    pivot_window: int = 2
    min_touches: int = 2
    entry_buffer_pct: float = 0.01
    stop_buffer_pct: float = 0.005
    allow_countertrend: bool = False


@dataclass(frozen=True)
class BinanceConfig:
    base_url: str = "https://api.binance.com"
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    limit: int = 200
    use_testnet: bool = True
    api_key_env: str = "BINANCE_API_KEY"
    api_secret_env: str = "BINANCE_API_SECRET"


@dataclass(frozen=True)
class PaperTradingConfig:
    poll_seconds: int = 60
    max_iterations: int = 0
