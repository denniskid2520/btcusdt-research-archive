from __future__ import annotations

from quant_trading.models import Candle, Position, Signal
from quant_trading.strategies.base import Strategy
from quant_trading.structure import current_channel_levels, detect_channel_structure, estimate_market_regime


class ChannelStructureStrategy(Strategy):
    def __init__(
        self,
        lookback: int = 30,
        pivot_window: int = 2,
        min_touches: int = 2,
        entry_buffer_pct: float = 0.01,
        stop_buffer_pct: float = 0.005,
        allow_countertrend: bool = False,
    ) -> None:
        self.lookback = lookback
        self.pivot_window = pivot_window
        self.min_touches = min_touches
        self.entry_buffer_pct = entry_buffer_pct
        self.stop_buffer_pct = stop_buffer_pct
        self.allow_countertrend = allow_countertrend

    def on_candle(self, history: list[Candle], position: Position) -> Signal:
        channel = detect_channel_structure(
            history,
            lookback=self.lookback,
            pivot_window=self.pivot_window,
            min_touches=self.min_touches,
        )
        if channel is None:
            return self._manage_open_position_without_channel(history, position)

        regime = estimate_market_regime(history, lookback=min(len(history), max(self.lookback, 40)))
        current_candle = history[-1]
        support, resistance = current_channel_levels(channel, self.lookback)
        channel_width = resistance - support
        if channel_width <= 0:
            return Signal(action="hold", confidence=0.0, reason="invalid_channel_width")

        lower_entry_zone = support + (channel_width * self.entry_buffer_pct)
        upper_entry_zone = resistance - (channel_width * self.entry_buffer_pct)
        stop_buffer = channel_width * self.stop_buffer_pct

        if position.is_open:
            return self._manage_open_position(position, current_candle.close, support, resistance, stop_buffer)

        if channel.kind == "descending_channel" and regime == "bearish":
            if current_candle.close >= upper_entry_zone:
                return Signal(
                    action="short",
                    confidence=channel.confidence,
                    stop_price=resistance + stop_buffer,
                    target_price=support,
                    reason="descending_channel_resistance_rejection",
                )

            if current_candle.close < support:
                return Signal(
                    action="short",
                    confidence=min(channel.confidence + 0.1, 1.0),
                    stop_price=support + stop_buffer,
                    target_price=channel.breakout_target,
                    reason="descending_channel_breakdown",
                )

        if channel.kind == "ascending_channel" and (regime == "bullish" or self.allow_countertrend):
            if current_candle.close <= lower_entry_zone:
                return Signal(
                    action="buy",
                    confidence=channel.confidence,
                    stop_price=support - stop_buffer,
                    target_price=resistance,
                    reason="ascending_channel_support_bounce",
                )

            if current_candle.close > resistance:
                return Signal(
                    action="buy",
                    confidence=min(channel.confidence + 0.1, 1.0),
                    stop_price=resistance - stop_buffer,
                    target_price=channel.breakout_target,
                    reason="ascending_channel_breakout",
                )

        return Signal(action="hold", confidence=0.0, reason="no_structure_trade")

    def _manage_open_position(
        self,
        position: Position,
        current_price: float,
        support: float,
        resistance: float,
        stop_buffer: float,
    ) -> Signal:
        if position.is_long:
            if position.stop_price is not None and current_price <= position.stop_price:
                return Signal(action="sell", confidence=1.0, reason="long_stop_hit")
            if position.target_price is not None and current_price >= position.target_price:
                return Signal(action="sell", confidence=1.0, reason="long_target_hit")
            if current_price < support - stop_buffer:
                return Signal(action="sell", confidence=1.0, reason="ascending_structure_failed")

        if position.is_short:
            if position.stop_price is not None and current_price >= position.stop_price:
                return Signal(action="cover", confidence=1.0, reason="short_stop_hit")
            if position.target_price is not None and current_price <= position.target_price:
                return Signal(action="cover", confidence=1.0, reason="short_target_hit")
            if current_price > resistance + stop_buffer:
                return Signal(action="cover", confidence=1.0, reason="descending_structure_failed")

        return Signal(action="hold", confidence=0.0, reason="position_active")

    def _manage_open_position_without_channel(self, history: list[Candle], position: Position) -> Signal:
        if not position.is_open:
            return Signal(action="hold", confidence=0.0, reason="no_channel")

        current_price = history[-1].close
        if position.is_long:
            if position.stop_price is not None and current_price <= position.stop_price:
                return Signal(action="sell", confidence=1.0, reason="long_stop_without_channel")
            if position.target_price is not None and current_price >= position.target_price:
                return Signal(action="sell", confidence=1.0, reason="long_target_without_channel")

        if position.is_short:
            if position.stop_price is not None and current_price >= position.stop_price:
                return Signal(action="cover", confidence=1.0, reason="short_stop_without_channel")
            if position.target_price is not None and current_price <= position.target_price:
                return Signal(action="cover", confidence=1.0, reason="short_target_without_channel")

        return Signal(action="hold", confidence=0.0, reason="channel_lost_but_position_open")
