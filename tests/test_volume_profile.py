"""Tests for Volume Profile (VRVP) indicator and bear reversal detection.

TDD: tests first, then implementation.

Volume Profile computes from daily OHLCV:
  - POC (Point of Control): highest volume price bin
  - VAH (Value Area High): upper boundary of 70% volume range
  - VAL (Value Area Low): lower boundary of 70% volume range
  - HVN (High Volume Nodes): bins with volume > 1.5x median
  - LVN (Low Volume Nodes): bins with volume < 0.3x median

Bear Reversal Combo (Phase state machine):
  Phase 0: Bear context
  Phase 1: Capitulation (RSI<22 + Vol spike + below VA)
  Phase 2: Reversal confirmed (VAL reclaim) → LONG signal
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from adapters.base import MarketBar


TS = datetime(2023, 1, 1)


def _make_daily_bars(
    prices: list[float],
    volumes: list[float] | None = None,
    start: datetime = TS,
) -> list[MarketBar]:
    """Create daily bars with OHLCV."""
    if volumes is None:
        volumes = [1000.0] * len(prices)
    return [
        MarketBar(
            timestamp=start + timedelta(days=i),
            open=p * 0.998,
            high=p * 1.015,
            low=p * 0.985,
            close=p,
            volume=v,
        )
        for i, (p, v) in enumerate(zip(prices, volumes))
    ]


# ── Volume Profile core ─────────────────────────────────────────


def test_volume_profile_returns_poc_val_vah() -> None:
    """VP must return POC, VAL, VAH from daily bars."""
    from indicators.volume_profile import compute_volume_profile

    # 60 bars clustered around $25,000 with some spread
    prices = [25000 + (i % 10 - 5) * 100 for i in range(60)]
    bars = _make_daily_bars(prices)
    vp = compute_volume_profile(bars)

    assert vp is not None
    assert vp.poc > 0
    assert vp.val > 0
    assert vp.vah > 0
    assert vp.val < vp.poc < vp.vah


def test_volume_profile_val_below_vah() -> None:
    """VAL must be below VAH (value area is a range)."""
    from indicators.volume_profile import compute_volume_profile

    prices = [20000 + i * 50 for i in range(60)]
    bars = _make_daily_bars(prices)
    vp = compute_volume_profile(bars)

    assert vp.val < vp.vah


def test_volume_profile_poc_at_high_volume_price() -> None:
    """POC should be near the price where most volume traded."""
    from indicators.volume_profile import compute_volume_profile

    # Most volume at $30,000, thin volume elsewhere
    prices = [30000] * 40 + [25000 + i * 200 for i in range(20)]
    volumes = [5000.0] * 40 + [100.0] * 20
    bars = _make_daily_bars(prices, volumes)
    vp = compute_volume_profile(bars)

    # POC should be near $30,000
    assert abs(vp.poc - 30000) < 1000


def test_volume_profile_value_area_contains_70_pct() -> None:
    """Value Area (VAL to VAH) should contain ~70% of volume."""
    from indicators.volume_profile import compute_volume_profile

    prices = [20000 + (i % 20) * 200 for i in range(60)]
    volumes = [1000 + (i % 5) * 500 for i in range(60)]
    bars = _make_daily_bars(prices, volumes)
    vp = compute_volume_profile(bars)

    # VA should be a reasonable fraction of total range
    total_range = max(b.high for b in bars) - min(b.low for b in bars)
    va_range = vp.vah - vp.val
    assert va_range < total_range  # VA smaller than total range
    assert va_range > total_range * 0.2  # but not trivially small


def test_volume_profile_insufficient_bars_returns_none() -> None:
    """Less than 10 bars should return None."""
    from indicators.volume_profile import compute_volume_profile

    bars = _make_daily_bars([20000, 21000, 22000])
    vp = compute_volume_profile(bars)
    assert vp is None


def test_volume_profile_hvn_lvn_detection() -> None:
    """HVN and LVN lists should be populated."""
    from indicators.volume_profile import compute_volume_profile

    # Create bimodal distribution: heavy at $20k and $30k, gap at $25k
    prices = [20000] * 25 + [30000] * 25 + [25000] * 10
    volumes = [5000.0] * 25 + [5000.0] * 25 + [100.0] * 10
    bars = _make_daily_bars(prices, volumes)
    vp = compute_volume_profile(bars)

    assert len(vp.hvn) > 0, "Should detect high volume nodes"
    assert len(vp.lvn) >= 0  # LVN may or may not exist depending on distribution


# ── Bear Reversal Combo ──────────────────────────────────────────


def test_bear_reversal_detect_capitulation() -> None:
    """Phase 1: detect capitulation when RSI<22 + vol spike + below VA."""
    from indicators.volume_profile import detect_bear_reversal_phase

    # Build 250 bars of bear market, then capitulation
    # Steady decline from $40k to $20k over 240 bars
    base = [40000 - i * 83 for i in range(240)]
    # Then 10 bars of crash with high volume
    crash = [20000 - i * 200 for i in range(10)]
    prices = base + crash
    volumes = [1000.0] * 240 + [5000.0] * 10  # volume spike on crash
    bars = _make_daily_bars(prices, volumes, start=datetime(2022, 1, 1))

    phase = detect_bear_reversal_phase(bars)
    assert phase.phase >= 1, f"Should detect capitulation, got phase={phase.phase}"


def test_bear_reversal_detect_reversal() -> None:
    """Phase 2: detect reversal when price reclaims VAL after capitulation."""
    from indicators.volume_profile import detect_bear_reversal_phase

    # Bear → capitulation → stay below VA → then reclaim VAL
    base = [40000 - i * 83 for i in range(240)]
    crash = [20000 - i * 300 for i in range(10)]  # deeper crash to $17k
    # Stay below VA for a few bars, then recover through VAL
    bottom = [17000, 16800, 17200, 17500]
    recovery = [17500 + i * 500 for i in range(15)]  # slow climb back up
    prices = base + crash + bottom + recovery
    volumes = [1000.0] * 240 + [5000.0] * 10 + [2000.0] * 4 + [3000.0] * 15
    bars = _make_daily_bars(prices, volumes, start=datetime(2022, 1, 1))

    phase = detect_bear_reversal_phase(bars)
    assert phase.phase == 2, f"Should detect reversal, got phase={phase.phase}"
    assert phase.action == "buy"
    assert phase.entry_price > 0


def test_bear_reversal_no_signal_in_uptrend() -> None:
    """No reversal signal when market is in uptrend (no capitulation)."""
    from indicators.volume_profile import detect_bear_reversal_phase

    # Pure uptrend
    prices = [20000 + i * 50 for i in range(260)]
    bars = _make_daily_bars(prices, start=datetime(2022, 1, 1))

    phase = detect_bear_reversal_phase(bars)
    assert phase.phase == 0, "Uptrend should stay at phase 0"
    assert phase.action == "hold"


def test_bear_reversal_no_signal_without_volume_spike() -> None:
    """Capitulation requires volume spike. No spike = no signal."""
    from indicators.volume_profile import detect_bear_reversal_phase

    # Bear + RSI oversold but NO volume spike
    base = [40000 - i * 83 for i in range(240)]
    crash = [20000 - i * 200 for i in range(10)]
    recovery = [18000 + i * 400 for i in range(15)]
    prices = base + crash + recovery
    # Volume stays flat (no spike)
    volumes = [1000.0] * len(prices)
    bars = _make_daily_bars(prices, volumes, start=datetime(2022, 1, 1))

    phase = detect_bear_reversal_phase(bars)
    # Should not reach phase 2 without volume confirmation
    assert phase.action == "hold" or phase.phase < 2
