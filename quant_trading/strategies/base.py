from __future__ import annotations

from abc import ABC, abstractmethod

from quant_trading.models import Candle, Position, Signal


class Strategy(ABC):
    @abstractmethod
    def on_candle(self, history: list[Candle], position: Position) -> Signal:
        raise NotImplementedError
