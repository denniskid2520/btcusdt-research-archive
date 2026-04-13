from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from adapters.base import MarketBar, OrderSide, Position

if TYPE_CHECKING:
    from data.mtf_bars import MultiTimeframeBars


@dataclass(frozen=True)
class StrategySignal:
    action: OrderSide
    confidence: float
    reason: str
    stop_price: float | None = None
    target_price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Strategy(ABC):
    @abstractmethod
    def generate_signal(
        self,
        symbol: str,
        bars: list[MarketBar],
        position: Position,
        mtf_bars: MultiTimeframeBars | None = None,
    ) -> StrategySignal:
        raise NotImplementedError
