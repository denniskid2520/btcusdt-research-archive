"""Tests for channel swing strategy — SHORT at highs, LONG at lows.

State machine:
    SCANNING → detect channel → active
    Flat + HIGH ★★★ + near resistance → SHORT
    Flat + LOW ★★★ + near support → LONG (buy)
    Short + LOW ★★★ → COVER → pending flip → BUY
    Long + HIGH ★★★ → SELL → pending flip → SHORT
    Any + channel break → emergency exit → SCANNING
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from strategies.channel_detector import (
    ChannelDetectorConfig,
    DailyIndicators,
    DetectedChannel,
)
from strategies.channel_swing import (
    ChannelSwingConfig,
    ChannelSwingStrategy,
)
from adapters.base import MarketBar, Position


# ── Helpers ──────────────────────────────────────────────────────

BASE = datetime(2025, 1, 1)


def _bar(day: int, o: float, h: float, l: float, c: float) -> MarketBar:
    return MarketBar(
        timestamp=BASE + timedelta(days=day),
        open=o, high=h, low=l, close=c, volume=1000,
    )


def _ind(**kw) -> DailyIndicators:
    defaults = dict(
        oi=50e9, funding_pct=0.3, ls_ratio=1.5, long_liq_usd=5e6,
        short_liq_usd=10e6, cvd=-200e9, taker_buy_usd=1e9,
        taker_sell_usd=0.9e9, rsi3=50.0, rsi7=50.0, rsi14=50.0,
    )
    defaults.update(kw)
    return DailyIndicators(**defaults)


def _high_ind() -> DailyIndicators:
    """All 7 HIGH ★★★ conditions met (score=7)."""
    return _ind(
        funding_pct=0.5, ls_ratio=1.3,
        long_liq_usd=3e6, short_liq_usd=8e6,
        taker_buy_usd=1.1e9, taker_sell_usd=1.0e9,
        rsi3=75.0, rsi7=62.0, rsi14=55.0, cvd=-195e9,
    )


def _low_ind() -> DailyIndicators:
    """All 9 LOW ★★★ conditions met (score=9)."""
    return _ind(
        funding_pct=0.1, ls_ratio=1.2,
        long_liq_usd=15e6, short_liq_usd=5e6,
        taker_buy_usd=0.85e9, taker_sell_usd=1.0e9,
        rsi3=18.0, rsi7=28.0, rsi14=38.0, cvd=-210e9,
    )


def _channel() -> DetectedChannel:
    """Ascending channel: support=60k+100/day, resistance=68k+100/day, width=8k.

    At day 45: support=64500, resistance=72500, mid=68500.
    """
    return DetectedChannel(
        kind="ascending",
        support_slope=100.0, support_intercept=60000.0,
        resistance_slope=100.0, resistance_intercept=68000.0,
        support_r2=0.90, resistance_r2=0.90,
        width=8000.0, duration_days=90,
        confirmed_highs=[], confirmed_lows=[],
    )


def _flat() -> Position:
    return Position(symbol="BTC")


def _long_pos() -> Position:
    return Position(symbol="BTC", side="long", quantity=1.0, average_price=65000)


def _short_pos() -> Position:
    return Position(symbol="BTC", side="short", quantity=1.0, average_price=72000)


def _setup(
    state: str = "in_channel",
    prev_cvd: float = -198e9,
    prev_oi: float = 49e9,
) -> ChannelSwingStrategy:
    """Strategy with pre-set channel and previous indicators.

    prev defaults → HIGH scoring: CVD rising (-195 > -198), OI rising (50 > 49).
    For LOW scoring, override with prev_cvd=-205e9, prev_oi=52e9.
    """
    s = ChannelSwingStrategy(ChannelSwingConfig())
    s._channel = _channel()
    s._channel_start_date = BASE
    s._state = state
    s._prev_indicators = _ind(cvd=prev_cvd, oi=prev_oi)
    return s


# ══════════════════════════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════════════════════════

class TestChannelSwingConfig:

    def test_defaults(self):
        cfg = ChannelSwingConfig()
        assert cfg.min_high_score == 3
        assert cfg.min_low_score == 3
        assert cfg.resistance_zone_pct == 0.70
        assert cfg.support_zone_pct == 0.30
        assert cfg.stop_buffer_pct == 0.02
        assert cfg.channel_break_buffer_pct == 0.02
        assert cfg.ascending_only is True

    def test_custom(self):
        cfg = ChannelSwingConfig(min_high_score=5, support_zone_pct=0.20)
        assert cfg.min_high_score == 5
        assert cfg.support_zone_pct == 0.20


# ══════════════════════════════════════════════════════════════════
# No channel → hold
# ══════════════════════════════════════════════════════════════════

class TestNoChannel:

    def test_hold_when_scanning(self):
        s = ChannelSwingStrategy(ChannelSwingConfig())
        sig = s.on_daily_close(
            _bar(0, 65000, 65500, 64500, 65000), _ind(), _flat(),
        )
        assert sig.action == "hold"

    def test_descending_channel_rejected(self):
        """Descending channel ignored when ascending_only=True."""
        s = ChannelSwingStrategy(ChannelSwingConfig())
        # Inject a descending channel — strategy should reject it
        desc = DetectedChannel(
            kind="descending",
            support_slope=-100.0, support_intercept=70000.0,
            resistance_slope=-100.0, resistance_intercept=78000.0,
            support_r2=0.90, resistance_r2=0.90,
            width=8000.0, duration_days=90,
            confirmed_highs=[], confirmed_lows=[],
        )
        s._channel = desc
        s._channel_start_date = BASE
        s._state = "in_channel"
        s._prev_indicators = _ind()

        # Near "resistance" with high score — should still hold (channel rejected)
        sig = s.on_daily_close(
            _bar(45, 72000, 72500, 71800, 72200), _high_ind(), _flat(),
        )
        assert sig.action == "hold"
        assert s._state == "scanning"
        assert s._channel is None

    def test_descending_accepted_when_flag_off(self):
        """Descending channel accepted when ascending_only=False."""
        s = ChannelSwingStrategy(ChannelSwingConfig(ascending_only=False))
        desc = DetectedChannel(
            kind="descending",
            support_slope=-100.0, support_intercept=70000.0,
            resistance_slope=-100.0, resistance_intercept=78000.0,
            support_r2=0.90, resistance_r2=0.90,
            width=8000.0, duration_days=90,
            confirmed_highs=[], confirmed_lows=[],
        )
        s._channel = desc
        s._channel_start_date = BASE
        s._state = "in_channel"
        s._prev_indicators = _ind(cvd=-198e9, oi=49e9)

        # Near resistance with high indicators — should short
        # Day 45: res = -100*45 + 78000 = 73500
        # pos_pct for close 73200: (73200 - 65500) / (73500 - 65500) = 7700/8000 = 0.96
        sig = s.on_daily_close(
            _bar(45, 73000, 73500, 72800, 73200), _high_ind(), _flat(),
        )
        assert sig.action == "short"


# ══════════════════════════════════════════════════════════════════
# Entry signals (from flat position)
# ══════════════════════════════════════════════════════════════════

class TestEntrySignals:

    def test_short_at_resistance_with_high_score(self):
        """Flat + near resistance + HIGH ★★★ → short."""
        s = _setup()
        # Day 45: res=72500. Close 72200 → pos_pct≈0.96 (>0.70)
        sig = s.on_daily_close(
            _bar(45, 72000, 72500, 71800, 72200), _high_ind(), _flat(),
        )
        assert sig.action == "short"

    def test_long_at_support_with_low_score(self):
        """Flat + near support + LOW ★★★ → buy."""
        s = _setup(prev_cvd=-205e9, prev_oi=52e9)
        # Day 45: sup=64500. Close 64800 → pos_pct≈0.04 (<0.30)
        sig = s.on_daily_close(
            _bar(45, 65000, 65200, 64600, 64800), _low_ind(), _flat(),
        )
        assert sig.action == "buy"

    def test_hold_mid_channel(self):
        """Flat + mid-channel → hold (no zone)."""
        s = _setup()
        # Day 45: mid≈68500. pos_pct≈0.50
        sig = s.on_daily_close(
            _bar(45, 68400, 68700, 68200, 68500), _ind(), _flat(),
        )
        assert sig.action == "hold"

    def test_no_entry_low_indicator_score(self):
        """Near resistance but bad indicators → hold."""
        s = _setup()
        # Counter-indicators: funding<0, L/S<1, liq wrong, taker wrong
        bad = _ind(
            funding_pct=-0.1, ls_ratio=0.9,
            long_liq_usd=10e6, short_liq_usd=5e6,
            taker_buy_usd=0.9e9, taker_sell_usd=1.0e9, cvd=-201e9,
        )
        sig = s.on_daily_close(
            _bar(45, 72000, 72500, 71800, 72200), bad, _flat(),
        )
        assert sig.action == "hold"

    def test_high_score_but_wrong_zone(self):
        """HIGH score met but price near support → no short."""
        s = _setup()
        sig = s.on_daily_close(
            _bar(45, 65000, 65200, 64600, 64800), _high_ind(), _flat(),
        )
        assert sig.action != "short"


# ══════════════════════════════════════════════════════════════════
# Exit signals (from open position)
# ══════════════════════════════════════════════════════════════════

class TestExitSignals:

    def test_cover_short_at_low(self):
        """Short + LOW conditions at support → cover."""
        s = _setup(state="short", prev_cvd=-205e9, prev_oi=52e9)
        sig = s.on_daily_close(
            _bar(45, 65000, 65200, 64600, 64800), _low_ind(), _short_pos(),
        )
        assert sig.action == "cover"

    def test_sell_long_at_high(self):
        """Long + HIGH conditions at resistance → sell."""
        s = _setup(state="long")
        sig = s.on_daily_close(
            _bar(45, 72000, 72500, 71800, 72200), _high_ind(), _long_pos(),
        )
        assert sig.action == "sell"

    def test_hold_short_mid_channel(self):
        """Short + mid-channel → hold."""
        s = _setup(state="short")
        sig = s.on_daily_close(
            _bar(45, 68400, 68700, 68200, 68500), _ind(), _short_pos(),
        )
        assert sig.action == "hold"

    def test_hold_long_mid_channel(self):
        """Long + mid-channel → hold."""
        s = _setup(state="long")
        sig = s.on_daily_close(
            _bar(45, 68400, 68700, 68200, 68500), _ind(), _long_pos(),
        )
        assert sig.action == "hold"


# ══════════════════════════════════════════════════════════════════
# Flip sequences: close → pending → reenter opposite
# ══════════════════════════════════════════════════════════════════

class TestFlipSequence:

    def test_short_to_long_flip(self):
        """Cover short at low → next bar buy (flip to long)."""
        s = _setup(state="short", prev_cvd=-205e9, prev_oi=52e9)

        # Step 1: cover
        sig1 = s.on_daily_close(
            _bar(45, 65000, 65200, 64600, 64800), _low_ind(), _short_pos(),
        )
        assert sig1.action == "cover"
        assert s._pending_entry == "buy"

        # Step 2: flip to long (position now flat)
        sig2 = s.on_daily_close(
            _bar(46, 64900, 65300, 64700, 65000), _low_ind(), _flat(),
        )
        assert sig2.action == "buy"
        assert s._state == "long"
        assert s._pending_entry is None

    def test_long_to_short_flip(self):
        """Sell long at high → next bar short (flip to short)."""
        s = _setup(state="long")

        # Step 1: sell
        sig1 = s.on_daily_close(
            _bar(45, 72000, 72500, 71800, 72200), _high_ind(), _long_pos(),
        )
        assert sig1.action == "sell"
        assert s._pending_entry == "short"

        # Step 2: flip to short
        sig2 = s.on_daily_close(
            _bar(46, 72100, 72400, 71900, 72000), _high_ind(), _flat(),
        )
        assert sig2.action == "short"
        assert s._state == "short"
        assert s._pending_entry is None


# ══════════════════════════════════════════════════════════════════
# Channel break → emergency exit
# ══════════════════════════════════════════════════════════════════

class TestChannelBreak:

    def test_break_above_covers_short(self):
        """Price > resistance+buffer while short → cover (stop loss)."""
        s = _setup(state="short")
        # Day 45: res=72500, break threshold=72500*1.02=73950, close=74000
        sig = s.on_daily_close(
            _bar(45, 73000, 74500, 73000, 74000), _ind(), _short_pos(),
        )
        assert sig.action == "cover"
        assert "break" in sig.reason

    def test_break_below_sells_long(self):
        """Price < support-buffer while long → sell (stop loss)."""
        s = _setup(state="long")
        # Day 45: sup=64500, break threshold=64500*0.98=63210, close=63100
        sig = s.on_daily_close(
            _bar(45, 64000, 64200, 63000, 63100), _ind(), _long_pos(),
        )
        assert sig.action == "sell"
        assert "break" in sig.reason

    def test_break_above_sells_long(self):
        """Price > resistance+buffer while long → sell (channel invalid)."""
        s = _setup(state="long")
        sig = s.on_daily_close(
            _bar(45, 73000, 74500, 73000, 74000), _ind(), _long_pos(),
        )
        assert sig.action == "sell"
        assert "break" in sig.reason

    def test_break_resets_state(self):
        """Channel break clears channel and returns to scanning."""
        s = _setup(state="short")
        s.on_daily_close(
            _bar(45, 73000, 74500, 73000, 74000), _ind(), _short_pos(),
        )
        assert s._state == "scanning"
        assert s._channel is None

    def test_break_clears_pending_entry(self):
        """Channel break after cover clears pending flip."""
        s = _setup(state="short", prev_cvd=-205e9, prev_oi=52e9)

        # Cover at low → pending buy
        s.on_daily_close(
            _bar(45, 65000, 65200, 64600, 64800), _low_ind(), _short_pos(),
        )
        assert s._pending_entry == "buy"

        # Break below before flip executes
        # Day 46: sup=64600, break=64600*0.98=63308, close=61500
        s.on_daily_close(
            _bar(46, 62000, 62500, 61000, 61500), _ind(), _flat(),
        )
        assert s._pending_entry is None
        assert s._state == "scanning"


# ══════════════════════════════════════════════════════════════════
# Stop prices
# ══════════════════════════════════════════════════════════════════

class TestStopPrices:

    def test_short_stop_above_resistance(self):
        """Short stop = resistance * (1 + buffer)."""
        s = _setup()
        sig = s.on_daily_close(
            _bar(45, 72000, 72500, 71800, 72200), _high_ind(), _flat(),
        )
        # Day 45 res=72500. stop = 72500 * 1.02 = 73950
        assert sig.stop_price == pytest.approx(73950, rel=0.01)

    def test_long_stop_below_support(self):
        """Long stop = support * (1 - buffer)."""
        s = _setup(prev_cvd=-205e9, prev_oi=52e9)
        sig = s.on_daily_close(
            _bar(45, 65000, 65200, 64600, 64800), _low_ind(), _flat(),
        )
        # Day 45 sup=64500. stop = 64500 * 0.98 = 63210
        assert sig.stop_price == pytest.approx(63210, rel=0.01)


# ══════════════════════════════════════════════════════════════════
# Internal state tracking
# ══════════════════════════════════════════════════════════════════

class TestStateTracking:

    def test_initial_state_scanning(self):
        s = ChannelSwingStrategy(ChannelSwingConfig())
        assert s._state == "scanning"
        assert s._channel is None

    def test_state_after_short_entry(self):
        s = _setup()
        s.on_daily_close(
            _bar(45, 72000, 72500, 71800, 72200), _high_ind(), _flat(),
        )
        assert s._state == "short"

    def test_state_after_long_entry(self):
        s = _setup(prev_cvd=-205e9, prev_oi=52e9)
        s.on_daily_close(
            _bar(45, 65000, 65200, 64600, 64800), _low_ind(), _flat(),
        )
        assert s._state == "long"

    def test_prev_indicators_updated(self):
        """_prev_indicators updates after each on_daily_close call."""
        s = _setup()
        ind = _high_ind()
        s.on_daily_close(_bar(45, 72000, 72500, 71800, 72200), ind, _flat())
        assert s._prev_indicators is ind
