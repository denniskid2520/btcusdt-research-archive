"""Tests for daily flag pattern detection (TDD: tests first).

Bear flag = ascending (rising) daily channel in downtrend → breakdown → short
Bull flag = descending (falling) daily channel in uptrend → breakout → long
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from adapters.base import MarketBar


TS = datetime(2022, 1, 1)


def _make_bars_4h(
    prices: list[float],
    start: datetime = TS,
) -> list[MarketBar]:
    """Create 4h bars from close prices."""
    return [
        MarketBar(
            timestamp=start + timedelta(hours=i * 4),
            open=p * 0.998,
            high=p * 1.005,
            low=p * 0.995,
            close=p,
            volume=100.0,
        )
        for i, p in enumerate(prices)
    ]


# ── 1. Daily pivot detection ────────────────────────────────────


def test_find_daily_pivots_basic() -> None:
    """Find pivot highs and lows on daily bars."""
    from research.daily_flag import _find_daily_pivots
    from research.macro_cycle import aggregate_to_daily

    # Create a clear wave pattern: up → down → up → down → up
    prices: list[float] = []
    for day in range(30):
        wave = 40000 + 3000 * (1 if (day // 5) % 2 == 0 else -1) * ((day % 5) / 5)
        for _ in range(6):  # 6 bars per day
            prices.append(wave)
    bars = _make_bars_4h(prices, start=TS)
    daily = aggregate_to_daily(bars)

    pivots = _find_daily_pivots(daily, window=2)
    highs = [p for p in pivots if p.kind == "high"]
    lows = [p for p in pivots if p.kind == "low"]
    assert len(highs) >= 1, "Should find at least one pivot high"
    assert len(lows) >= 1, "Should find at least one pivot low"


# ── 2. Linear regression ────────────────────────────────────────


def test_linreg_perfect_uptrend() -> None:
    """Perfect linear data → R²=1.0, positive slope."""
    from research.daily_flag import _linreg

    xs = [float(i) for i in range(10)]
    ys = [100 + 5 * x for x in xs]
    slope, intercept, r_sq = _linreg(xs, ys)
    assert slope == pytest.approx(5.0, abs=0.01)
    assert intercept == pytest.approx(100.0, abs=0.01)
    assert r_sq == pytest.approx(1.0, abs=0.01)


def test_linreg_perfect_downtrend() -> None:
    """Perfect descending data → R²=1.0, negative slope."""
    from research.daily_flag import _linreg

    xs = [float(i) for i in range(10)]
    ys = [100 - 3 * x for x in xs]
    slope, intercept, r_sq = _linreg(xs, ys)
    assert slope == pytest.approx(-3.0, abs=0.01)
    assert r_sq == pytest.approx(1.0, abs=0.01)


# ── 3. Daily channel detection ──────────────────────────────────


def test_detect_ascending_daily_channel() -> None:
    """Rising channel on daily bars → ascending channel detected."""
    from research.daily_flag import _detect_daily_channel
    from research.macro_cycle import aggregate_to_daily

    # 60 days of rising channel: higher highs + higher lows with oscillation
    prices: list[float] = []
    for day in range(60):
        base = 40000 + day * 200  # rising trend
        osc = 2000 * (1 if (day % 8 < 4) else -1)  # oscillation
        for h in range(6):
            prices.append(base + osc * (h / 6))
    bars = _make_bars_4h(prices, start=TS)
    daily = aggregate_to_daily(bars)

    ch = _detect_daily_channel(daily, pivot_window=2, min_pivots=2, min_r_squared=0.1)
    assert ch is not None, "Should detect ascending channel"
    assert ch.kind == "ascending"
    assert ch.upper_slope > 0
    assert ch.lower_slope > 0


def test_detect_descending_daily_channel() -> None:
    """Falling channel on daily bars → descending channel detected."""
    from research.daily_flag import _detect_daily_channel
    from research.macro_cycle import aggregate_to_daily

    prices: list[float] = []
    for day in range(60):
        base = 60000 - day * 200  # falling trend
        osc = 2000 * (1 if (day % 8 < 4) else -1)
        for h in range(6):
            prices.append(base + osc * (h / 6))
    bars = _make_bars_4h(prices, start=TS)
    daily = aggregate_to_daily(bars)

    ch = _detect_daily_channel(daily, pivot_window=2, min_pivots=2, min_r_squared=0.1)
    assert ch is not None, "Should detect descending channel"
    assert ch.kind == "descending"
    assert ch.upper_slope < 0
    assert ch.lower_slope < 0


# ── 4. Bear flag detection ──────────────────────────────────────


def test_bear_flag_breakdown_signal() -> None:
    """Bear flag: rising channel → price breaks below → short signal.

    Pattern: initial impulse drop, then rising channel (flag), then breakdown.
    """
    from research.daily_flag import detect_daily_flag

    prices: list[float] = []

    # Phase 1: stable high (30 days)
    for day in range(30):
        for _ in range(6):
            prices.append(60000.0)

    # Phase 2: impulse drop (5 days)
    for day in range(5):
        for h in range(6):
            idx = day * 6 + h
            prices.append(60000 - idx * 200)
    # Now at ~54000

    # Phase 3: rising channel / bear flag (50 days)
    for day in range(50):
        base = 54000 + day * 100  # slowly rising
        osc = 1500 * (1 if (day % 7 < 3) else -1)
        for h in range(6):
            prices.append(base + osc)
    # Flag top ~59000, flag bottom ~56000

    # Phase 4: strong breakdown below channel (10 days, sharp drop)
    last_p = prices[-1]
    for day in range(10):
        for h in range(6):
            prices.append(last_p - (day * 6 + h) * 150)
    # Broke well below the rising channel support

    bars = _make_bars_4h(prices, start=TS)
    signal = detect_daily_flag(
        bars, lookback_days=60, pivot_window=2, min_pivots=2,
        min_r_squared=0.1, parent_trend="descending",
    )
    assert signal.action == "short", f"Expected short, got {signal.action} ({signal.flag_type})"
    assert signal.flag_type == "bear_flag"
    assert signal.confidence > 0


# ── 5. Bull flag detection ──────────────────────────────────────


def test_bull_flag_breakout_signal() -> None:
    """Bull flag: descending channel → price breaks above → long signal."""
    from research.daily_flag import detect_daily_flag

    prices: list[float] = []

    # Phase 1: stable low (30 days)
    for day in range(30):
        for _ in range(6):
            prices.append(30000.0)

    # Phase 2: impulse rally (5 days)
    for day in range(5):
        for h in range(6):
            idx = day * 6 + h
            prices.append(30000 + idx * 200)
    # Now at ~36000

    # Phase 3: descending channel / bull flag (50 days)
    for day in range(50):
        base = 36000 - day * 80  # slowly declining
        osc = 1200 * (1 if (day % 7 < 3) else -1)
        for h in range(6):
            prices.append(base + osc)
    # Flag roughly 32000-34000

    # Phase 4: strong breakout above channel (10 days, sharp rally)
    last_p = prices[-1]
    for day in range(10):
        for h in range(6):
            prices.append(last_p + (day * 6 + h) * 150)

    bars = _make_bars_4h(prices, start=TS)
    signal = detect_daily_flag(
        bars, lookback_days=55, pivot_window=2, min_pivots=2,
        min_r_squared=0.1, parent_trend="ascending",
    )
    assert signal.action == "long", f"Expected long, got {signal.action} ({signal.flag_type})"
    assert signal.flag_type == "bull_flag"


# ── 6. No signal in flat/wrong conditions ────────────────────────


def test_no_flag_flat_market() -> None:
    """Flat market → hold (no flag pattern)."""
    from research.daily_flag import detect_daily_flag

    import random
    random.seed(77)
    prices = [40000 + random.uniform(-500, 500) for _ in range(90 * 6)]
    bars = _make_bars_4h(prices, start=TS)

    signal = detect_daily_flag(bars, lookback_days=60)
    assert signal.action == "hold"


def test_no_signal_when_price_inside_channel() -> None:
    """Price stays inside channel (no breakdown/breakout) → hold."""
    from research.daily_flag import detect_daily_flag

    # Rising channel, price stays within channel (no breakdown)
    prices: list[float] = []
    for day in range(70):
        base = 40000 + day * 200
        osc = 2000 * (1 if (day % 8 < 4) else -1)
        for h in range(6):
            prices.append(base + osc)

    # No breakdown, price stays in channel
    bars = _make_bars_4h(prices, start=TS)
    signal = detect_daily_flag(
        bars, lookback_days=60, pivot_window=2, min_pivots=2,
        min_r_squared=0.1, parent_trend="ascending",
    )
    assert signal.action == "hold", "Price inside channel should NOT trigger"


def test_insufficient_data_returns_hold() -> None:
    """Too few bars → hold."""
    from research.daily_flag import detect_daily_flag

    prices = [40000.0] * (20 * 6)  # only 20 days
    bars = _make_bars_4h(prices, start=TS)
    signal = detect_daily_flag(bars, lookback_days=60)
    assert signal.action == "hold"
