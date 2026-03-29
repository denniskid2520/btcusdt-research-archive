from __future__ import annotations

from quant_trading.config import MovingAverageConfig
from quant_trading.models import Candle, Position, Signal
from quant_trading.strategies.base import Strategy


class MovingAverageCrossStrategy(Strategy):
    def __init__(self, config: MovingAverageConfig | None = None) -> None:
        self.config = config or MovingAverageConfig()
        if self.config.short_window >= self.config.long_window:
            raise ValueError("short_window must be smaller than long_window.")

    def on_candle(self, history: list[Candle], position: Position) -> Signal:
        if len(history) < self.config.long_window:
            return Signal(action="hold", confidence=0.0)

        short_ma = self._average_close(history[-self.config.short_window :])
        long_ma = self._average_close(history[-self.config.long_window :])

        previous_short_ma = self._average_close(
            history[-self.config.short_window - 1 : -1]
        )
        previous_long_ma = self._average_close(history[-self.config.long_window - 1 : -1])

        bullish_cross = previous_short_ma <= previous_long_ma and short_ma > long_ma
        bearish_cross = previous_short_ma >= previous_long_ma and short_ma < long_ma

        if bullish_cross and not position.is_open:
            return Signal(action="buy", confidence=1.0)
        if bearish_cross and position.is_long:
            return Signal(action="sell", confidence=1.0)
        return Signal(action="hold", confidence=0.0)

    @staticmethod
    def _average_close(candles: list[Candle]) -> float:
        return sum(item.close for item in candles) / len(candles)
