"""Tests for 1h pattern detection functions (archived in experimental/).

These test the pure pattern detection functions that were tested for
1h signal generation. The feature was proven harmful, but the detection
functions are preserved for future research.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from adapters.base import MarketBar
from strategies.experimental.mtf_1h_signal_gen import (
    detect_1h_rejection_wick,
    detect_1h_bullish_engulfing,
    detect_1h_higher_low,
)


# ── Helpers ──────────────────────────────────────────────────────────
def _make_1h_bar(
    ts: datetime, open_: float, high: float, low: float, close: float,
) -> MarketBar:
    return MarketBar(timestamp=ts, open=open_, high=high, low=low, close=close, volume=100.0)


def _ts(hour: int) -> datetime:
    return datetime(2025, 1, 2) + timedelta(hours=hour)


# ── Pattern detection: rejection wick ────────────────────────────────
def test_1h_rejection_wick_detected() -> None:
    """Bullish rejection: long lower wick, close in upper half."""
    bars = [
        _make_1h_bar(_ts(0), 100, 102, 95, 101),   # normal
        _make_1h_bar(_ts(1), 101, 103, 96, 102),    # normal
        _make_1h_bar(_ts(2), 100, 101, 93, 100.5),  # long lower wick: (100-93)/(101-93)=87.5%
    ]
    result = detect_1h_rejection_wick(bars, min_wick_ratio=0.4, direction="long")
    assert result is not None


def test_1h_rejection_wick_not_detected_flat_bars() -> None:
    """No lower wick → no detection."""
    bars = [
        _make_1h_bar(_ts(0), 100, 102, 100, 101.8),  # open=low, no lower wick
        _make_1h_bar(_ts(1), 101, 103, 101, 102.5),   # open=low, no lower wick
    ]
    result = detect_1h_rejection_wick(bars, min_wick_ratio=0.4, direction="long")
    assert result is None


def test_1h_rejection_wick_short_direction() -> None:
    """Bearish rejection: long upper wick for shorts."""
    bars = [
        _make_1h_bar(_ts(0), 100, 107, 99, 99.5),  # long upper wick: (107-100)/(107-99)=87.5%
    ]
    result = detect_1h_rejection_wick(bars, min_wick_ratio=0.4, direction="short")
    assert result is not None


# ── Pattern detection: bullish engulfing ─────────────────────────────
def test_1h_bullish_engulfing_detected() -> None:
    """Current bar's body engulfs previous bar's body (bullish)."""
    bars = [
        _make_1h_bar(_ts(0), 102, 103, 99, 100),  # bearish: open 102 → close 100
        _make_1h_bar(_ts(1), 99, 104, 98, 103),   # bullish: open 99 → close 103, engulfs [100,102]
    ]
    result = detect_1h_bullish_engulfing(bars, min_body_ratio=0.5, direction="long")
    assert result is not None


def test_1h_bullish_engulfing_not_detected_small_body() -> None:
    """Small body doesn't qualify as engulfing."""
    bars = [
        _make_1h_bar(_ts(0), 101, 103, 99, 100),   # bearish body
        _make_1h_bar(_ts(1), 100, 105, 98, 100.5),  # tiny body, big wicks
    ]
    result = detect_1h_bullish_engulfing(bars, min_body_ratio=0.5, direction="long")
    assert result is None


# ── Pattern detection: higher low ────────────────────────────────────
def test_1h_higher_low_sequence_detected() -> None:
    """Three bars with ascending lows = higher low pattern."""
    bars = [
        _make_1h_bar(_ts(0), 100, 102, 95, 101),
        _make_1h_bar(_ts(1), 101, 103, 96, 102),
        _make_1h_bar(_ts(2), 102, 104, 97, 103),
    ]
    result = detect_1h_higher_low(bars, n_bars=3, direction="long")
    assert result is True


def test_1h_higher_low_not_detected_descending() -> None:
    """Descending lows = no higher low."""
    bars = [
        _make_1h_bar(_ts(0), 100, 102, 97, 101),
        _make_1h_bar(_ts(1), 101, 103, 96, 102),
        _make_1h_bar(_ts(2), 102, 104, 95, 103),
    ]
    result = detect_1h_higher_low(bars, n_bars=3, direction="long")
    assert result is False


def test_1h_lower_high_for_shorts() -> None:
    """Three bars with descending highs = lower high for shorts."""
    bars = [
        _make_1h_bar(_ts(0), 100, 105, 98, 99),
        _make_1h_bar(_ts(1), 99, 104, 97, 98),
        _make_1h_bar(_ts(2), 98, 103, 96, 97),
    ]
    result = detect_1h_higher_low(bars, n_bars=3, direction="short")
    assert result is True
