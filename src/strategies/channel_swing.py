"""Channel swing strategy — SHORT at confirmed highs, LONG at confirmed lows.

Uses the ChannelDetector to identify ascending/descending channels, then
trades within the channel by scoring each daily bar against the empirically
derived ★★★ indicator conditions.

State machine:
    SCANNING        → detect channel   → IN_CHANNEL
    IN_CHANNEL/flat → HIGH ★★★ + res   → SHORT
    IN_CHANNEL/flat → LOW ★★★ + sup    → LONG (buy)
    SHORT           → LOW ★★★ + sup    → COVER  (pending flip to LONG)
    LONG            → HIGH ★★★ + res   → SELL   (pending flip to SHORT)
    PENDING_LONG    → next bar, flat   → BUY
    PENDING_SHORT   → next bar, flat   → SHORT
    ANY             → channel break    → exit + SCANNING
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from adapters.base import MarketBar, Position
from strategies.base import StrategySignal
from strategies.channel_detector import (
    ChannelDetector,
    ChannelDetectorConfig,
    DailyIndicators,
    DetectedChannel,
)


# ── Configuration ──

@dataclass
class ChannelSwingConfig:
    """Configuration for channel swing strategy."""

    # Channel detection
    detector: ChannelDetectorConfig = field(default_factory=ChannelDetectorConfig)

    # Signal scoring thresholds
    min_high_score: int = 3         # min ★★★ conditions to trigger SHORT
    min_low_score: int = 3          # min ★★★ conditions to trigger LONG

    # Zone thresholds (position_pct: 0=support, 1=resistance)
    resistance_zone_pct: float = 0.70   # >= this → near resistance
    support_zone_pct: float = 0.30      # <= this → near support

    # Channel kind filter (★★★ conditions only validated for ascending)
    ascending_only: bool = True

    # Stops & breaks
    stop_buffer_pct: float = 0.02           # stop distance beyond boundary
    channel_break_buffer_pct: float = 0.02  # buffer for declaring break


# ── Strategy ──

class ChannelSwingStrategy:
    """Trade within channels: SHORT at highs, LONG at lows, flip at extremes."""

    def __init__(self, config: ChannelSwingConfig | None = None) -> None:
        self.config = config or ChannelSwingConfig()
        self._detector = ChannelDetector(self.config.detector)

        # Channel state
        self._channel: DetectedChannel | None = None
        self._channel_start_date: datetime | None = None

        # Position state machine
        self._state: str = "scanning"       # scanning | in_channel | short | long | pending_long | pending_short
        self._pending_entry: str | None = None   # "buy" | "short" | None

        # Data buffers
        self._daily_bars: list[MarketBar] = []
        self._indicators_map: dict[str, DailyIndicators] = {}
        self._prev_indicators: DailyIndicators | None = None

    # ── Public API ──

    def on_daily_close(
        self,
        bar: MarketBar,
        indicators: DailyIndicators,
        position: Position,
    ) -> StrategySignal:
        """Process one daily bar with indicators.  Returns trading signal."""
        # Accumulate
        self._daily_bars.append(bar)
        date_str = bar.timestamp.strftime("%Y-%m-%d")
        self._indicators_map[date_str] = indicators

        signal = self._evaluate(bar, indicators, position)

        # Update prev for next call (CVD/OI delta scoring)
        self._prev_indicators = indicators
        return signal

    # ── Core evaluation ──

    def _evaluate(
        self,
        bar: MarketBar,
        indicators: DailyIndicators,
        position: Position,
    ) -> StrategySignal:
        # 1. Scanning: try to detect channel
        if self._state == "scanning":
            self._try_detect()
            if self._channel is None:
                return _hold("scanning")

        # 1b. Ascending-only gate (★★★ conditions only validated for ascending)
        if self.config.ascending_only and self._channel.kind != "ascending":
            self._channel = None
            self._channel_start_date = None
            self._state = "scanning"
            return _hold("descending_rejected")

        day_idx = self._day_index(bar)

        # 2. Channel break? (checked before anything else — safety first)
        break_dir = self._check_break(bar, day_idx)
        if break_dir is not None:
            return self._on_break(break_dir, position)

        # 3. Pending flip entry? (from previous bar's exit)
        if self._pending_entry is not None and not position.is_open:
            return self._execute_pending(day_idx)

        # 4. Score current conditions
        high_score = self._detector.score_high_pivot(
            indicators, self._prev_indicators,
        )
        low_score = self._detector.score_low_pivot(
            indicators, self._prev_indicators,
        )
        pos_pct = self._channel.position_pct(bar.close, day_idx)

        # 5. Signal based on position
        if not position.is_open:
            return self._from_flat(high_score, low_score, pos_pct, day_idx)
        if position.side == "short":
            return self._from_short(low_score, pos_pct, day_idx)
        if position.side == "long":
            return self._from_long(high_score, pos_pct, day_idx)

        return _hold("unknown_state")

    # ── Channel detection ──

    def _try_detect(self) -> None:
        if len(self._daily_bars) < self.config.detector.min_bars:
            return
        channel = self._detector.detect(self._daily_bars, self._indicators_map)
        if channel is not None:
            self._channel = channel
            self._channel_start_date = self._daily_bars[0].timestamp
            self._state = "in_channel"

    def _day_index(self, bar: MarketBar) -> int:
        if self._channel_start_date is None:
            return 0
        return (bar.timestamp - self._channel_start_date).days

    # ── Break detection ──

    def _check_break(self, bar: MarketBar, day_idx: int) -> str | None:
        assert self._channel is not None
        sup = self._channel.support_at(day_idx)
        res = self._channel.resistance_at(day_idx)
        buf = self.config.channel_break_buffer_pct

        if bar.close > res * (1 + buf):
            return "above"
        if bar.close < sup * (1 - buf):
            return "below"
        return None

    def _on_break(self, direction: str, position: Position) -> StrategySignal:
        """Handle channel break: exit position and reset to scanning."""
        self._state = "scanning"
        self._channel = None
        self._channel_start_date = None
        self._pending_entry = None

        reason = f"channel_break_{direction}"

        if position.side == "short":
            return StrategySignal(
                action="cover", confidence=1.0, reason=reason,
            )
        if position.side == "long":
            return StrategySignal(
                action="sell", confidence=1.0, reason=reason,
            )
        return _hold(reason)

    # ── Pending flip entry ──

    def _execute_pending(self, day_idx: int) -> StrategySignal:
        action = self._pending_entry
        self._pending_entry = None

        if action == "buy":
            sup = self._channel.support_at(day_idx)
            stop = sup * (1 - self.config.stop_buffer_pct)
            self._state = "long"
            return StrategySignal(
                action="buy", confidence=0.8,
                reason="channel_flip_to_long",
                stop_price=stop,
            )
        if action == "short":
            res = self._channel.resistance_at(day_idx)
            stop = res * (1 + self.config.stop_buffer_pct)
            self._state = "short"
            return StrategySignal(
                action="short", confidence=0.8,
                reason="channel_flip_to_short",
                stop_price=stop,
            )
        return _hold("no_pending")

    # ── Signal from flat ──

    def _from_flat(
        self,
        high_score: int,
        low_score: int,
        pos_pct: float,
        day_idx: int,
    ) -> StrategySignal:
        cfg = self.config

        # SHORT entry at resistance
        if high_score >= cfg.min_high_score and pos_pct >= cfg.resistance_zone_pct:
            res = self._channel.resistance_at(day_idx)
            stop = res * (1 + cfg.stop_buffer_pct)
            self._state = "short"
            return StrategySignal(
                action="short",
                confidence=high_score / 7.0,
                reason=f"channel_high_score_{high_score}",
                stop_price=stop,
                metadata={"high_score": high_score, "position_pct": pos_pct},
            )

        # LONG entry at support
        if low_score >= cfg.min_low_score and pos_pct <= cfg.support_zone_pct:
            sup = self._channel.support_at(day_idx)
            stop = sup * (1 - cfg.stop_buffer_pct)
            self._state = "long"
            return StrategySignal(
                action="buy",
                confidence=low_score / 9.0,
                reason=f"channel_low_score_{low_score}",
                stop_price=stop,
                metadata={"low_score": low_score, "position_pct": pos_pct},
            )

        return _hold("no_signal")

    # ── Signal from short position ──

    def _from_short(
        self, low_score: int, pos_pct: float, day_idx: int,
    ) -> StrategySignal:
        cfg = self.config

        if low_score >= cfg.min_low_score and pos_pct <= cfg.support_zone_pct:
            self._pending_entry = "buy"
            self._state = "pending_long"
            return StrategySignal(
                action="cover",
                confidence=low_score / 9.0,
                reason=f"channel_low_flip_score_{low_score}",
                metadata={"low_score": low_score, "flip_to": "long"},
            )
        return _hold("holding_short")

    # ── Signal from long position ──

    def _from_long(
        self, high_score: int, pos_pct: float, day_idx: int,
    ) -> StrategySignal:
        cfg = self.config

        if high_score >= cfg.min_high_score and pos_pct >= cfg.resistance_zone_pct:
            self._pending_entry = "short"
            self._state = "pending_short"
            return StrategySignal(
                action="sell",
                confidence=high_score / 7.0,
                reason=f"channel_high_flip_score_{high_score}",
                metadata={"high_score": high_score, "flip_to": "short"},
            )
        return _hold("holding_long")


# ── Helpers ──

def _hold(reason: str) -> StrategySignal:
    return StrategySignal(action="hold", confidence=0.0, reason=reason)
