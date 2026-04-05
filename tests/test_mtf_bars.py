"""Tests for MultiTimeframeBars — time-indexed multi-timeframe bar container.

TDD: write failing tests first, then implement.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from adapters.base import MarketBar
from data.mtf_bars import MultiTimeframeBars


def _make_bars(start: datetime, count: int, interval_hours: float) -> list[MarketBar]:
    """Generate synthetic bars at regular intervals."""
    bars = []
    for i in range(count):
        ts = start + timedelta(hours=interval_hours * i)
        price = 50000 + i * 100
        bars.append(MarketBar(
            timestamp=ts, open=price, high=price + 50,
            low=price - 50, close=price + 25, volume=1000.0,
        ))
    return bars


class TestMultiTimeframeBars:

    def test_create_from_dict(self) -> None:
        start = datetime(2024, 1, 1)
        bars_4h = _make_bars(start, 10, 4.0)
        bars_1h = _make_bars(start, 40, 1.0)
        mtf = MultiTimeframeBars({"4h": bars_4h, "1h": bars_1h})
        assert mtf.timeframes == {"4h", "1h"}

    def test_get_history_returns_correct_count(self) -> None:
        start = datetime(2024, 1, 1)
        bars_1h = _make_bars(start, 100, 1.0)
        mtf = MultiTimeframeBars({"1h": bars_1h})
        # At hour 50, ask for last 10 bars
        as_of = start + timedelta(hours=50)
        history = mtf.get_history("1h", as_of=as_of, lookback=10)
        assert len(history) == 10

    def test_get_history_no_lookahead(self) -> None:
        """Bars after as_of timestamp must NOT be included."""
        start = datetime(2024, 1, 1)
        bars_1h = _make_bars(start, 100, 1.0)
        mtf = MultiTimeframeBars({"1h": bars_1h})
        as_of = start + timedelta(hours=24)  # 2024-01-02 00:00
        history = mtf.get_history("1h", as_of=as_of, lookback=100)
        # Should get at most 25 bars (hour 0 through hour 24 inclusive)
        assert len(history) <= 25
        for bar in history:
            assert bar.timestamp <= as_of

    def test_get_history_respects_4h_1h_alignment(self) -> None:
        """When stepping through 4h bars, 1h history should align."""
        start = datetime(2024, 1, 1)
        bars_4h = _make_bars(start, 6, 4.0)  # 0h, 4h, 8h, 12h, 16h, 20h
        bars_1h = _make_bars(start, 24, 1.0)  # 0h through 23h
        mtf = MultiTimeframeBars({"4h": bars_4h, "1h": bars_1h})

        # At 4h bar timestamp=8h, get last 4 1h bars
        as_of = start + timedelta(hours=8)
        history = mtf.get_history("1h", as_of=as_of, lookback=4)
        assert len(history) == 4
        # Last bar should be at hour 8
        assert history[-1].timestamp == as_of
        # First bar should be at hour 5
        assert history[0].timestamp == start + timedelta(hours=5)

    def test_get_history_returns_less_when_not_enough(self) -> None:
        """If lookback exceeds available bars, return what's available."""
        start = datetime(2024, 1, 1)
        bars_1h = _make_bars(start, 5, 1.0)
        mtf = MultiTimeframeBars({"1h": bars_1h})
        history = mtf.get_history("1h", as_of=start + timedelta(hours=3), lookback=100)
        assert len(history) == 4  # bars at 0h, 1h, 2h, 3h

    def test_get_history_unknown_timeframe_returns_empty(self) -> None:
        mtf = MultiTimeframeBars({"4h": _make_bars(datetime(2024, 1, 1), 5, 4.0)})
        history = mtf.get_history("15m", as_of=datetime(2024, 1, 1, 8), lookback=10)
        assert history == []

    def test_get_history_before_first_bar_returns_empty(self) -> None:
        start = datetime(2024, 1, 1, 12)
        bars_1h = _make_bars(start, 10, 1.0)
        mtf = MultiTimeframeBars({"1h": bars_1h})
        history = mtf.get_history("1h", as_of=datetime(2024, 1, 1, 0), lookback=5)
        assert history == []

    def test_15m_bars_work(self) -> None:
        """15m bars should be indexable like any other timeframe."""
        start = datetime(2024, 1, 1)
        bars_15m = _make_bars(start, 96, 0.25)  # 96 bars = 24 hours of 15m
        mtf = MultiTimeframeBars({"15m": bars_15m})
        as_of = start + timedelta(hours=4)  # after 16 bars
        history = mtf.get_history("15m", as_of=as_of, lookback=8)
        assert len(history) == 8
        assert history[-1].timestamp == as_of
