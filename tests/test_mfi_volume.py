"""TDD tests for MFI (Money Flow Index) and volume confirmation.

MFI = 100 - 100 / (1 + positive_flow / negative_flow)
Typical Price = (H + L + C) / 3
Raw Money Flow = Typical Price × Volume
If TP > prev TP → positive flow, else → negative flow

Bollinger's system: %B + MFI
  %B < 0.2 + MFI < 20 → oversold (long confirmation)
  %B > 0.8 + MFI > 80 → overbought (short confirmation)
"""

import pytest


# ── Helper to build bars with volume ──

def make_bars(data: list[dict]) -> list[dict]:
    """Build bars from list of {h, l, c, v} dicts."""
    from datetime import datetime, timedelta
    base = datetime(2025, 1, 1)
    bars = []
    for i, d in enumerate(data):
        bars.append({
            "timestamp": base + timedelta(hours=i),
            "open": d.get("o", d["c"]),
            "high": d["h"],
            "low": d["l"],
            "close": d["c"],
            "volume": d["v"],
        })
    return bars


# ═══════════════════════════════════════════════════════════
# Test: MFI calculation
# ═══════════════════════════════════════════════════════════

class TestCalculateMFI:
    """Money Flow Index calculation."""

    def test_basic_mfi(self):
        """MFI with clear up/down bars."""
        from research.bb_swing_backtest import calculate_mfi
        # 15 bars: first 10 up, last 4 down → MFI should be moderate-high
        bars = make_bars([
            {"h": 101, "l": 99, "c": 100, "v": 1000},
            {"h": 103, "l": 100, "c": 102, "v": 1200},  # up
            {"h": 105, "l": 101, "c": 104, "v": 1100},  # up
            {"h": 107, "l": 103, "c": 106, "v": 1300},  # up
            {"h": 109, "l": 105, "c": 108, "v": 1000},  # up
            {"h": 111, "l": 107, "c": 110, "v": 1100},  # up
            {"h": 113, "l": 109, "c": 112, "v": 1200},  # up
            {"h": 115, "l": 111, "c": 114, "v": 1000},  # up
            {"h": 117, "l": 113, "c": 116, "v": 1100},  # up
            {"h": 119, "l": 115, "c": 118, "v": 1200},  # up
            {"h": 120, "l": 116, "c": 117, "v": 1300},  # down
            {"h": 118, "l": 114, "c": 115, "v": 1400},  # down
            {"h": 116, "l": 112, "c": 113, "v": 1500},  # down
            {"h": 114, "l": 110, "c": 111, "v": 1600},  # down
            {"h": 112, "l": 108, "c": 109, "v": 1000},  # down
        ])
        mfi = calculate_mfi(bars, period=14)
        assert mfi is not None
        assert 0 <= mfi <= 100

    def test_all_up_bars_mfi_near_100(self):
        """All prices rising → MFI near 100."""
        from research.bb_swing_backtest import calculate_mfi
        bars = make_bars([
            {"h": 100 + i * 2 + 1, "l": 100 + i * 2 - 1, "c": 100 + i * 2, "v": 1000}
            for i in range(16)
        ])
        mfi = calculate_mfi(bars, period=14)
        assert mfi is not None
        assert mfi > 90

    def test_all_down_bars_mfi_near_0(self):
        """All prices falling → MFI near 0."""
        from research.bb_swing_backtest import calculate_mfi
        bars = make_bars([
            {"h": 200 - i * 2 + 1, "l": 200 - i * 2 - 1, "c": 200 - i * 2, "v": 1000}
            for i in range(16)
        ])
        mfi = calculate_mfi(bars, period=14)
        assert mfi is not None
        assert mfi < 10

    def test_not_enough_bars_returns_none(self):
        """Need at least period+1 bars."""
        from research.bb_swing_backtest import calculate_mfi
        bars = make_bars([
            {"h": 101, "l": 99, "c": 100, "v": 1000}
            for _ in range(5)
        ])
        mfi = calculate_mfi(bars, period=14)
        assert mfi is None

    def test_mfi_period_14_default(self):
        """Default period is 14."""
        from research.bb_swing_backtest import calculate_mfi
        bars = make_bars([
            {"h": 100 + i, "l": 98 + i, "c": 99 + i, "v": 1000}
            for i in range(20)
        ])
        mfi_default = calculate_mfi(bars)
        mfi_14 = calculate_mfi(bars, period=14)
        assert mfi_default == mfi_14

    def test_zero_volume_handled(self):
        """Bars with zero volume shouldn't cause division by zero."""
        from research.bb_swing_backtest import calculate_mfi
        bars = make_bars([
            {"h": 100 + i, "l": 98 + i, "c": 99 + i, "v": 0}
            for i in range(16)
        ])
        mfi = calculate_mfi(bars, period=14)
        assert mfi is not None  # should not crash


# ═══════════════════════════════════════════════════════════
# Test: %B + MFI Bollinger system
# ═══════════════════════════════════════════════════════════

class TestPercentBMFI:
    """%B + MFI confirmation per Bollinger's method."""

    def test_oversold_confirmed(self):
        """%B < 0.2 + MFI < 20 → long confirmed."""
        from research.bb_swing_backtest import check_bb_mfi_confirmation
        assert check_bb_mfi_confirmation(pct_b=0.1, mfi=15, side="long") is True

    def test_overbought_confirmed(self):
        """%B > 0.8 + MFI > 80 → short confirmed."""
        from research.bb_swing_backtest import check_bb_mfi_confirmation
        assert check_bb_mfi_confirmation(pct_b=0.9, mfi=85, side="short") is True

    def test_oversold_mfi_too_high_rejects(self):
        """%B < 0.2 but MFI > 20 → NOT confirmed (volume not confirming)."""
        from research.bb_swing_backtest import check_bb_mfi_confirmation
        assert check_bb_mfi_confirmation(pct_b=0.1, mfi=50, side="long") is False

    def test_overbought_mfi_too_low_rejects(self):
        """%B > 0.8 but MFI < 80 → NOT confirmed."""
        from research.bb_swing_backtest import check_bb_mfi_confirmation
        assert check_bb_mfi_confirmation(pct_b=0.9, mfi=60, side="short") is False

    def test_wrong_side_rejects(self):
        """Oversold conditions but asking for short → rejected."""
        from research.bb_swing_backtest import check_bb_mfi_confirmation
        assert check_bb_mfi_confirmation(pct_b=0.1, mfi=15, side="short") is False

    def test_neutral_zone_rejects_both(self):
        """%B and MFI both in neutral zone → no signal."""
        from research.bb_swing_backtest import check_bb_mfi_confirmation
        assert check_bb_mfi_confirmation(pct_b=0.5, mfi=50, side="long") is False
        assert check_bb_mfi_confirmation(pct_b=0.5, mfi=50, side="short") is False

    def test_boundary_values(self):
        """Exact boundary: %B=0.2, MFI=20 → NOT confirmed (need strict < / >)."""
        from research.bb_swing_backtest import check_bb_mfi_confirmation
        assert check_bb_mfi_confirmation(pct_b=0.2, mfi=20, side="long") is False
        assert check_bb_mfi_confirmation(pct_b=0.8, mfi=80, side="short") is False

    def test_custom_thresholds(self):
        """Custom MFI thresholds should be respected (P2 fix)."""
        from research.bb_swing_backtest import check_bb_mfi_confirmation
        # Default 20/80 would reject MFI=25 for long, but custom 30 allows it
        assert check_bb_mfi_confirmation(pct_b=0.1, mfi=25, side="long") is False
        assert check_bb_mfi_confirmation(pct_b=0.1, mfi=25, side="long", mfi_oversold=30) is True
        # Default 80 would reject MFI=75 for short, but custom 70 rejects even more
        assert check_bb_mfi_confirmation(pct_b=0.9, mfi=75, side="short") is False
        assert check_bb_mfi_confirmation(pct_b=0.9, mfi=75, side="short", mfi_overbought=70) is True


# ═══════════════════════════════════════════════════════════
# Test: Volume spike detection
# ═══════════════════════════════════════════════════════════

class TestVolumeSpike:
    """Volume spike at BB band touch adds conviction."""

    def test_spike_detected(self):
        """Volume > 2x average → spike."""
        from research.bb_swing_backtest import detect_volume_spike
        volumes = [100, 110, 90, 105, 95, 100, 108, 92, 103, 97, 250]
        assert detect_volume_spike(volumes, multiplier=2.0) is True

    def test_no_spike(self):
        """Normal volume → no spike."""
        from research.bb_swing_backtest import detect_volume_spike
        volumes = [100, 110, 90, 105, 95, 100, 108, 92, 103, 97, 105]
        assert detect_volume_spike(volumes, multiplier=2.0) is False

    def test_empty_volumes(self):
        from research.bb_swing_backtest import detect_volume_spike
        assert detect_volume_spike([], multiplier=2.0) is False

    def test_single_volume(self):
        from research.bb_swing_backtest import detect_volume_spike
        assert detect_volume_spike([100], multiplier=2.0) is False

    def test_custom_multiplier(self):
        """1.5x multiplier is more sensitive."""
        from research.bb_swing_backtest import detect_volume_spike
        volumes = [100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 160]
        assert detect_volume_spike(volumes, multiplier=1.5) is True
        assert detect_volume_spike(volumes, multiplier=2.0) is False
