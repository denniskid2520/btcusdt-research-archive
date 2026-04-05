"""Multi-timeframe bar container with as-of lookups (no lookahead bias).

Usage:
    mtf = MultiTimeframeBars({"4h": bars_4h, "1h": bars_1h, "15m": bars_15m})
    history_1h = mtf.get_history("1h", as_of=current_4h_bar.timestamp, lookback=8)
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import datetime

from adapters.base import MarketBar


class MultiTimeframeBars:
    """Time-indexed container for bars from multiple timeframes.

    Provides O(log n) as-of lookups via bisect, preventing lookahead bias.
    """

    def __init__(self, bars_by_timeframe: dict[str, list[MarketBar]]) -> None:
        self._data: dict[str, list[MarketBar]] = {}
        self._timestamps: dict[str, list[datetime]] = {}

        for tf, bars in bars_by_timeframe.items():
            sorted_bars = sorted(bars, key=lambda b: b.timestamp)
            self._data[tf] = sorted_bars
            self._timestamps[tf] = [b.timestamp for b in sorted_bars]

    @property
    def timeframes(self) -> set[str]:
        return set(self._data.keys())

    def get_history(
        self,
        timeframe: str,
        as_of: datetime,
        lookback: int,
    ) -> list[MarketBar]:
        """Return the most recent `lookback` bars with timestamp <= as_of.

        This guarantees no lookahead bias: only bars that have already
        closed (timestamp <= as_of) are returned.
        """
        if timeframe not in self._timestamps:
            return []

        ts_list = self._timestamps[timeframe]
        # bisect_right gives us the index after the last timestamp <= as_of
        right = bisect_right(ts_list, as_of)
        if right == 0:
            return []

        left = max(0, right - lookback)
        return self._data[timeframe][left:right]
