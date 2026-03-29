from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


OrderSide = Literal["buy", "sell", "short", "cover", "hold"]
PositionSide = Literal["long", "short", "flat"]


@dataclass(frozen=True)
class MarketBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: OrderSide
    quantity: float
    timestamp: datetime
    order_type: str = "market"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FillReport:
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    fill_price: float
    fee: float
    timestamp: datetime


@dataclass
class Position:
    symbol: str
    side: PositionSide = "flat"
    quantity: float = 0.0
    average_price: float = 0.0
    reserved_margin: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.side != "flat" and self.quantity > 0


class MarketDataAdapter(ABC):
    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[MarketBar]:
        raise NotImplementedError


class BrokerAdapter(ABC):
    @abstractmethod
    def get_cash(self) -> float:
        raise NotImplementedError

    @abstractmethod
    def get_position(self, symbol: str) -> Position:
        raise NotImplementedError

    @abstractmethod
    def submit_order(self, order: OrderRequest, market_price: float) -> FillReport | None:
        raise NotImplementedError

    @abstractmethod
    def mark_to_market(self, symbol: str, market_price: float) -> float:
        raise NotImplementedError
