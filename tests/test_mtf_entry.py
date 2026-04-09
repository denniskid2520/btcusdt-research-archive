"""TDD tests for multi-timeframe entry confirmation.

Flow: Daily BB signal → 4h MA200 filter → 15m entry confirmation
The 15m confirmation prevents entering on false touches by waiting
for a micro-timeframe reversal pattern.

15m confirmation rules:
  Long:  15m close > previous 15m high  (bullish micro-breakout)
  Short: 15m close < previous 15m low   (bearish micro-breakout)
  + Optional: 15m RSI reversal from oversold/overbought zone

Pending signal expires after max_wait_bars (default 16 = 4 hours of 15m bars).
"""

import pytest
from datetime import datetime, timedelta


# ── Helper to build synthetic 15m bars ──

def make_15m_bars(data: list[dict]) -> list[dict]:
    """Build 15m bars from list of {o, h, l, c} dicts."""
    base = datetime(2025, 1, 1)
    bars = []
    for i, d in enumerate(data):
        bars.append({
            "timestamp": base + timedelta(minutes=15 * i),
            "open": d.get("o", d["c"]),
            "high": d.get("h", d["c"]),
            "low": d.get("l", d["c"]),
            "close": d["c"],
            "volume": d.get("v", 100),
        })
    return bars


# ═══════════════════════════════════════════════════════════
# Test: 15m confirmation detection
# ═══════════════════════════════════════════════════════════

class TestConfirmLong:
    """15m long confirmation: close > previous bar's high."""

    def test_bullish_breakout_confirms(self):
        """Close above prev high → confirmed."""
        from research.bb_swing_backtest import check_15m_confirmation
        bars = make_15m_bars([
            {"o": 100, "h": 102, "l": 99, "c": 101},   # bar 0
            {"o": 101, "h": 103, "l": 100, "c": 103},   # bar 1: close 103 > prev high 102 ✓
        ])
        assert check_15m_confirmation(bars, "long") is True

    def test_no_breakout_rejects(self):
        """Close below prev high → not confirmed."""
        from research.bb_swing_backtest import check_15m_confirmation
        bars = make_15m_bars([
            {"o": 100, "h": 102, "l": 99, "c": 101},
            {"o": 101, "h": 101.5, "l": 100, "c": 101},  # close 101 < prev high 102 ✗
        ])
        assert check_15m_confirmation(bars, "long") is False

    def test_needs_at_least_two_bars(self):
        """Single bar → not enough data."""
        from research.bb_swing_backtest import check_15m_confirmation
        bars = make_15m_bars([{"o": 100, "h": 105, "l": 99, "c": 104}])
        assert check_15m_confirmation(bars, "long") is False

    def test_uses_last_two_bars(self):
        """Should check only the last two bars, ignoring earlier ones."""
        from research.bb_swing_backtest import check_15m_confirmation
        bars = make_15m_bars([
            {"o": 90, "h": 95, "l": 88, "c": 92},      # old bar (ignored)
            {"o": 100, "h": 102, "l": 99, "c": 101},    # prev bar
            {"o": 101, "h": 104, "l": 100, "c": 103},   # last bar: 103 > 102 ✓
        ])
        assert check_15m_confirmation(bars, "long") is True


class TestConfirmShort:
    """15m short confirmation: close < previous bar's low."""

    def test_bearish_breakout_confirms(self):
        """Close below prev low → confirmed."""
        from research.bb_swing_backtest import check_15m_confirmation
        bars = make_15m_bars([
            {"o": 100, "h": 102, "l": 98, "c": 99},    # bar 0: low=98
            {"o": 99, "h": 100, "l": 97, "c": 97},      # bar 1: close 97 < prev low 98 ✓
        ])
        assert check_15m_confirmation(bars, "short") is True

    def test_no_breakdown_rejects(self):
        """Close above prev low → not confirmed."""
        from research.bb_swing_backtest import check_15m_confirmation
        bars = make_15m_bars([
            {"o": 100, "h": 102, "l": 98, "c": 99},
            {"o": 99, "h": 100, "l": 98.5, "c": 99},   # close 99 > prev low 98 ✗
        ])
        assert check_15m_confirmation(bars, "short") is False


class TestConfirmEdgeCases:
    """Edge cases for 15m confirmation."""

    def test_empty_bars_returns_false(self):
        from research.bb_swing_backtest import check_15m_confirmation
        assert check_15m_confirmation([], "long") is False

    def test_invalid_side_returns_false(self):
        from research.bb_swing_backtest import check_15m_confirmation
        bars = make_15m_bars([
            {"o": 100, "h": 105, "l": 99, "c": 104},
            {"o": 104, "h": 110, "l": 103, "c": 109},
        ])
        assert check_15m_confirmation(bars, "invalid") is False

    def test_exact_equal_not_confirmed(self):
        """Close == prev high is NOT a breakout (need strict >)."""
        from research.bb_swing_backtest import check_15m_confirmation
        bars = make_15m_bars([
            {"o": 100, "h": 102, "l": 99, "c": 101},
            {"o": 101, "h": 102, "l": 100, "c": 102},  # close == prev high
        ])
        assert check_15m_confirmation(bars, "long") is False


# ═══════════════════════════════════════════════════════════
# Test: Pending signal management
# ═══════════════════════════════════════════════════════════

class TestPendingSignal:
    """Pending signal: created on daily BB touch, expires if no 15m confirm."""

    def test_create_pending_signal(self):
        """Daily BB touch creates a pending signal."""
        from research.bb_swing_backtest import PendingSignal
        sig = PendingSignal(side="long", trigger_price=60000, bar_idx=100, max_wait=16)
        assert sig.side == "long"
        assert sig.trigger_price == 60000
        assert sig.is_expired(100) is False
        assert sig.is_expired(116) is False
        assert sig.is_expired(117) is True

    def test_expires_after_max_wait(self):
        """Signal expires after max_wait bars."""
        from research.bb_swing_backtest import PendingSignal
        sig = PendingSignal(side="short", trigger_price=70000, bar_idx=50, max_wait=16)
        assert sig.is_expired(50) is False
        assert sig.is_expired(66) is False  # exactly at limit
        assert sig.is_expired(67) is True   # one past limit

    def test_default_max_wait_is_16(self):
        """Default max_wait = 16 (4 hours of 15m bars)."""
        from research.bb_swing_backtest import PendingSignal
        sig = PendingSignal(side="long", trigger_price=60000, bar_idx=0)
        assert sig.max_wait == 16


# ═══════════════════════════════════════════════════════════
# Test: Entry price uses 15m close (not 4h close)
# ═══════════════════════════════════════════════════════════

class TestEntryPrice:
    """When 15m confirms, entry should use 15m close price, not 4h."""

    def test_entry_uses_15m_close(self):
        """Confirmed entry uses the 15m bar's close as entry price."""
        from research.bb_swing_backtest import get_confirmed_entry_price
        bars_15m = make_15m_bars([
            {"o": 100, "h": 102, "l": 99, "c": 101},
            {"o": 101, "h": 104, "l": 100, "c": 103},  # confirmed bar
        ])
        price = get_confirmed_entry_price(bars_15m, "long")
        assert price == 103  # last 15m close

    def test_no_confirmation_returns_none(self):
        """If not confirmed, return None."""
        from research.bb_swing_backtest import get_confirmed_entry_price
        bars_15m = make_15m_bars([
            {"o": 100, "h": 102, "l": 99, "c": 101},
            {"o": 101, "h": 101.5, "l": 100, "c": 101},  # no breakout
        ])
        price = get_confirmed_entry_price(bars_15m, "long")
        assert price is None


# ═══════════════════════════════════════════════════════════
# Test: Stop loss based on 15m swing (tighter stop)
# ═══════════════════════════════════════════════════════════

class TestMicroStop:
    """Stop loss from 15m swing low/high instead of fixed %."""

    def test_long_stop_at_15m_swing_low(self):
        """Long stop = lowest low of last N 15m bars."""
        from research.bb_swing_backtest import calc_micro_stop
        bars_15m = make_15m_bars([
            {"o": 100, "h": 102, "l": 97, "c": 101},
            {"o": 101, "h": 103, "l": 99, "c": 102},
            {"o": 102, "h": 105, "l": 100, "c": 104},
        ])
        stop = calc_micro_stop(bars_15m, "long", lookback=3)
        assert stop == 97  # lowest low across 3 bars

    def test_short_stop_at_15m_swing_high(self):
        """Short stop = highest high of last N 15m bars."""
        from research.bb_swing_backtest import calc_micro_stop
        bars_15m = make_15m_bars([
            {"o": 105, "h": 108, "l": 103, "c": 104},
            {"o": 104, "h": 106, "l": 101, "c": 102},
            {"o": 102, "h": 104, "l": 100, "c": 101},
        ])
        stop = calc_micro_stop(bars_15m, "short", lookback=3)
        assert stop == 108  # highest high across 3 bars

    def test_micro_stop_respects_max_pct(self):
        """Micro stop should not exceed max stop % from entry."""
        from research.bb_swing_backtest import calc_micro_stop
        bars_15m = make_15m_bars([
            {"o": 100, "h": 102, "l": 85, "c": 101},   # very wide bar
            {"o": 101, "h": 103, "l": 99, "c": 102},
        ])
        # Without cap: stop = 85 (15% from entry ~102)
        # With 4% max cap from entry 102: stop = 102 * 0.96 = 97.92
        stop = calc_micro_stop(bars_15m, "long", lookback=2, entry_price=102, max_pct=0.04)
        assert stop >= 102 * 0.96  # capped at 4%
