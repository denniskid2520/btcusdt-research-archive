from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Signal:
    action: str
    confidence: float = 1.0
    stop_price: float | None = None
    target_price: float | None = None
    reason: str = ""


@dataclass
class Position:
    side: Literal["long", "short", "flat"] = "flat"
    quantity: float = 0.0
    entry_price: float = 0.0
    stop_price: float | None = None
    target_price: float | None = None
    margin: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.side != "flat" and self.quantity > 0

    @property
    def is_long(self) -> bool:
        return self.side == "long" and self.is_open

    @property
    def is_short(self) -> bool:
        return self.side == "short" and self.is_open


@dataclass(frozen=True)
class Trade:
    side: Literal["long", "short"]
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    return_pct: float


@dataclass(frozen=True)
class BacktestResult:
    initial_cash: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    win_rate_pct: float
    total_trades: int
    sharpe_ratio: float
