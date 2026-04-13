"""Tests for daily channel detector with indicator-confirmed pivots."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from strategies.channel_detector import (
    ChannelDetectorConfig,
    ConfirmedPivot,
    DailyIndicators,
    DetectedChannel,
    ChannelDetector,
)
from adapters.base import MarketBar


# ── Helpers ──

def _bar(day_offset: int, o: float, h: float, l: float, c: float, base_date: str = "2025-01-01") -> MarketBar:
    dt = datetime.fromisoformat(base_date) + timedelta(days=day_offset)
    return MarketBar(timestamp=dt, open=o, high=h, low=l, close=c, volume=1000)


def _indicators(
    oi: float = 50e9,
    funding: float = 0.3,
    ls_ratio: float = 1.5,
    long_liq: float = 5e6,
    short_liq: float = 10e6,
    cvd: float = -200e9,
    taker_buy: float = 1e9,
    taker_sell: float = 0.9e9,
    rsi3: float = 50.0,
    rsi7: float = 50.0,
    rsi14: float = 50.0,
) -> DailyIndicators:
    return DailyIndicators(
        oi=oi,
        funding_pct=funding,
        ls_ratio=ls_ratio,
        long_liq_usd=long_liq,
        short_liq_usd=short_liq,
        cvd=cvd,
        taker_buy_usd=taker_buy,
        taker_sell_usd=taker_sell,
        rsi3=rsi3,
        rsi7=rsi7,
        rsi14=rsi14,
    )


def _high_indicators(cvd_delta: float = 1e9) -> DailyIndicators:
    """Indicators typical of a channel HIGH (★★★ conditions)."""
    return _indicators(
        funding=0.5,       # Fund>0 ★★★
        ls_ratio=1.3,      # L/S>1.0 ★★★, L/S>1.1 ★★★
        long_liq=3e6,
        short_liq=8e6,     # LiqR<1 ★★★ (shorts squeezed)
        taker_buy=1.1e9,
        taker_sell=1.0e9,  # Tkr>1.0 ★★★
        rsi3=75.0,
        rsi7=62.0,
        rsi14=55.0,
        cvd=-195e9,        # CVD rising from prev
    )


def _low_indicators() -> DailyIndicators:
    """Indicators typical of a channel LOW (★★★ conditions)."""
    return _indicators(
        funding=0.1,
        ls_ratio=1.2,      # L/S>1.0 ★★★
        long_liq=15e6,
        short_liq=5e6,     # LiqR>1.0 ★★★ (longs washed)
        taker_buy=0.85e9,
        taker_sell=1.0e9,  # Tkr<1.0 ★★★
        rsi3=18.0,         # R3<35 ★★★, R3<30 ★★★
        rsi7=28.0,         # R7<40 ★★★
        rsi14=38.0,        # R14<45 ★★★
        cvd=-210e9,        # CVD declining ★★★
    )


def _build_ascending_channel(
    n_days: int = 90,
    start_low: float = 60000,
    slope_per_day: float = 100,
    channel_width: float = 8000,
    swing_period: int = 14,
) -> tuple[list[MarketBar], list[tuple[int, DailyIndicators]]]:
    """Build a synthetic ascending channel with realistic indicator data.

    Returns bars and a list of (day_index, indicators) for each day.
    """
    bars = []
    indicators = []
    prev_cvd = -200e9

    for d in range(n_days):
        # Support line
        support = start_low + slope_per_day * d
        # Swing within channel: sine wave
        phase = 2 * math.pi * d / swing_period
        swing = (math.sin(phase) + 1) / 2  # 0 to 1
        mid = support + channel_width * swing

        noise = (d % 7 - 3) * 50  # small noise
        c = mid + noise
        h = c + abs(noise) + 200
        l = c - abs(noise) - 200
        o = c - noise

        bars.append(_bar(d, o, h, l, c))

        # Near top of swing (sin > 0.8)
        is_near_high = swing > 0.8
        # Near bottom of swing (sin < 0.2)
        is_near_low = swing < 0.2

        if is_near_high:
            ind = _high_indicators()
            prev_cvd += 1.5e9  # CVD rising at highs
        elif is_near_low:
            ind = _low_indicators()
            ind = DailyIndicators(
                oi=ind.oi, funding_pct=ind.funding_pct, ls_ratio=ind.ls_ratio,
                long_liq_usd=ind.long_liq_usd, short_liq_usd=ind.short_liq_usd,
                cvd=prev_cvd, taker_buy_usd=ind.taker_buy_usd,
                taker_sell_usd=ind.taker_sell_usd,
                rsi3=ind.rsi3, rsi7=ind.rsi7, rsi14=ind.rsi14,
            )
            prev_cvd -= 2e9  # CVD falling at lows
        else:
            ind = _indicators(cvd=prev_cvd)

        indicators.append((d, ind))

    return bars, indicators


# ══════════════════════════════════════════════════════════
# Tests: DailyIndicators
# ══════════════════════════════════════════════════════════

class TestDailyIndicators:

    def test_liq_ratio(self):
        ind = _indicators(long_liq=10e6, short_liq=5e6)
        assert ind.liq_ratio == pytest.approx(2.0)

    def test_liq_ratio_zero_short(self):
        ind = _indicators(long_liq=10e6, short_liq=0)
        assert ind.liq_ratio == 0.0

    def test_taker_ratio(self):
        ind = _indicators(taker_buy=1.1e9, taker_sell=1.0e9)
        assert ind.taker_ratio == pytest.approx(1.1)

    def test_taker_ratio_zero_sell(self):
        ind = _indicators(taker_buy=1.0e9, taker_sell=0)
        assert ind.taker_ratio == 0.0


# ══════════════════════════════════════════════════════════
# Tests: Pivot Confirmation
# ══════════════════════════════════════════════════════════

class TestPivotConfirmation:

    def test_high_pivot_confirmed_with_all_conditions(self):
        """HIGH pivot with all ★★★ indicators should confirm."""
        cfg = ChannelDetectorConfig()
        detector = ChannelDetector(cfg)
        ind = _high_indicators()
        prev_ind = _indicators(cvd=-198e9)  # CVD was lower before
        score = detector.score_high_pivot(ind, prev_ind)
        assert score >= cfg.min_high_score

    def test_low_pivot_confirmed_with_all_conditions(self):
        """LOW pivot with all ★★★ indicators should confirm."""
        cfg = ChannelDetectorConfig()
        detector = ChannelDetector(cfg)
        ind = _low_indicators()
        prev_ind = _indicators(cvd=-205e9)  # CVD was higher before
        score = detector.score_low_pivot(ind, prev_ind)
        assert score >= cfg.min_low_score

    def test_high_pivot_rejected_with_no_conditions(self):
        """HIGH pivot with counter-indicators should NOT confirm."""
        cfg = ChannelDetectorConfig()
        detector = ChannelDetector(cfg)
        # Opposite of high conditions
        ind = _indicators(
            funding=-0.5, ls_ratio=0.8, long_liq=15e6, short_liq=2e6,
            taker_buy=0.8e9, taker_sell=1.1e9, rsi3=20, rsi7=25, rsi14=30,
        )
        prev_ind = _indicators(cvd=-200e9)
        score = detector.score_high_pivot(ind, prev_ind)
        assert score < cfg.min_high_score

    def test_low_pivot_rejected_with_no_conditions(self):
        """LOW pivot with counter-indicators should NOT confirm."""
        cfg = ChannelDetectorConfig()
        detector = ChannelDetector(cfg)
        ind = _indicators(
            funding=1.0, ls_ratio=0.8, long_liq=2e6, short_liq=15e6,
            taker_buy=1.2e9, taker_sell=0.8e9, rsi3=80, rsi7=75, rsi14=65,
        )
        prev_ind = _indicators(cvd=-200e9)
        score = detector.score_low_pivot(ind, prev_ind)
        assert score < cfg.min_low_score


# ══════════════════════════════════════════════════════════
# Tests: Channel Detection
# ══════════════════════════════════════════════════════════

class TestChannelDetection:

    def test_ascending_channel_detected(self):
        """90-day ascending channel should be detected with positive slope."""
        bars, ind_list = _build_ascending_channel(n_days=90, slope_per_day=100)
        ind_map = {bars[i].timestamp.strftime("%Y-%m-%d"): ind for i, (_, ind) in enumerate(ind_list)}

        cfg = ChannelDetectorConfig(pivot_window=5, min_confirmed_highs=2, min_confirmed_lows=2)
        detector = ChannelDetector(cfg)
        channel = detector.detect(bars, ind_map)

        assert channel is not None
        assert channel.kind == "ascending"
        assert channel.support_slope > 0
        assert channel.resistance_slope > 0

    def test_channel_slope_positive_for_ascending(self):
        """Ascending channel slope should be positive and approximately correct."""
        bars, ind_list = _build_ascending_channel(n_days=90, slope_per_day=100)
        ind_map = {bars[i].timestamp.strftime("%Y-%m-%d"): ind for i, (_, ind) in enumerate(ind_list)}

        cfg = ChannelDetectorConfig(pivot_window=5, min_confirmed_highs=2, min_confirmed_lows=2)
        detector = ChannelDetector(cfg)
        channel = detector.detect(bars, ind_map)

        assert channel is not None
        # Slope should be roughly $100/day
        assert 50 < channel.support_slope < 200

    def test_channel_has_width(self):
        """Channel should report width close to actual width."""
        width = 8000
        bars, ind_list = _build_ascending_channel(n_days=90, channel_width=width)
        ind_map = {bars[i].timestamp.strftime("%Y-%m-%d"): ind for i, (_, ind) in enumerate(ind_list)}

        cfg = ChannelDetectorConfig(pivot_window=5, min_confirmed_highs=2, min_confirmed_lows=2)
        detector = ChannelDetector(cfg)
        channel = detector.detect(bars, ind_map)

        assert channel is not None
        # Width should be in range
        assert channel.width > width * 0.3

    def test_channel_has_r_squared(self):
        """Channel should have reasonable R² values."""
        bars, ind_list = _build_ascending_channel(n_days=90)
        ind_map = {bars[i].timestamp.strftime("%Y-%m-%d"): ind for i, (_, ind) in enumerate(ind_list)}

        cfg = ChannelDetectorConfig(pivot_window=5, min_confirmed_highs=2, min_confirmed_lows=2)
        detector = ChannelDetector(cfg)
        channel = detector.detect(bars, ind_map)

        assert channel is not None
        assert channel.support_r2 >= 0
        assert channel.resistance_r2 >= 0

    def test_channel_contains_confirmed_pivots(self):
        """Detected channel should contain confirmed pivot points."""
        bars, ind_list = _build_ascending_channel(n_days=90)
        ind_map = {bars[i].timestamp.strftime("%Y-%m-%d"): ind for i, (_, ind) in enumerate(ind_list)}

        cfg = ChannelDetectorConfig(pivot_window=5, min_confirmed_highs=2, min_confirmed_lows=2)
        detector = ChannelDetector(cfg)
        channel = detector.detect(bars, ind_map)

        assert channel is not None
        assert len(channel.confirmed_highs) >= 2
        assert len(channel.confirmed_lows) >= 2

    def test_no_channel_with_flat_data(self):
        """Flat price data should not produce a channel."""
        bars = [_bar(d, 50000, 50200, 49800, 50000) for d in range(90)]
        ind_map = {b.timestamp.strftime("%Y-%m-%d"): _indicators() for b in bars}

        cfg = ChannelDetectorConfig(pivot_window=5)
        detector = ChannelDetector(cfg)
        channel = detector.detect(bars, ind_map)

        # Flat data has no meaningful pivots
        assert channel is None

    def test_no_channel_with_insufficient_bars(self):
        """Too few bars should return None."""
        bars = [_bar(d, 50000 + d * 100, 50200 + d * 100, 49800 + d * 100, 50000 + d * 100) for d in range(10)]
        ind_map = {b.timestamp.strftime("%Y-%m-%d"): _indicators() for b in bars}

        cfg = ChannelDetectorConfig(pivot_window=5)
        detector = ChannelDetector(cfg)
        channel = detector.detect(bars, ind_map)

        assert channel is None


# ══════════════════════════════════════════════════════════
# Tests: Channel Properties
# ══════════════════════════════════════════════════════════

class TestDetectedChannel:

    def test_support_at(self):
        ch = DetectedChannel(
            kind="ascending",
            support_slope=100.0, support_intercept=60000.0,
            resistance_slope=100.0, resistance_intercept=68000.0,
            support_r2=0.95, resistance_r2=0.90,
            width=8000.0, duration_days=90,
            confirmed_highs=[], confirmed_lows=[],
        )
        assert ch.support_at(0) == 60000.0
        assert ch.support_at(30) == 63000.0

    def test_resistance_at(self):
        ch = DetectedChannel(
            kind="ascending",
            support_slope=100.0, support_intercept=60000.0,
            resistance_slope=100.0, resistance_intercept=68000.0,
            support_r2=0.95, resistance_r2=0.90,
            width=8000.0, duration_days=90,
            confirmed_highs=[], confirmed_lows=[],
        )
        assert ch.resistance_at(0) == 68000.0
        assert ch.resistance_at(30) == 71000.0

    def test_slope_per_day(self):
        ch = DetectedChannel(
            kind="ascending",
            support_slope=100.0, support_intercept=60000.0,
            resistance_slope=120.0, resistance_intercept=68000.0,
            support_r2=0.95, resistance_r2=0.90,
            width=8000.0, duration_days=90,
            confirmed_highs=[], confirmed_lows=[],
        )
        # Average slope per day
        assert ch.avg_slope_per_day == pytest.approx(110.0)

    def test_slope_pct_per_day(self):
        ch = DetectedChannel(
            kind="ascending",
            support_slope=100.0, support_intercept=60000.0,
            resistance_slope=100.0, resistance_intercept=68000.0,
            support_r2=0.95, resistance_r2=0.90,
            width=8000.0, duration_days=90,
            confirmed_highs=[], confirmed_lows=[],
        )
        # 100/64000 midpoint ~ 0.156% per day
        assert ch.slope_pct_per_day > 0

    def test_descending_channel_negative_slope(self):
        ch = DetectedChannel(
            kind="descending",
            support_slope=-50.0, support_intercept=70000.0,
            resistance_slope=-50.0, resistance_intercept=78000.0,
            support_r2=0.90, resistance_r2=0.85,
            width=8000.0, duration_days=60,
            confirmed_highs=[], confirmed_lows=[],
        )
        assert ch.avg_slope_per_day < 0
        assert ch.slope_pct_per_day < 0

    def test_position_in_channel(self):
        ch = DetectedChannel(
            kind="ascending",
            support_slope=0.0, support_intercept=60000.0,
            resistance_slope=0.0, resistance_intercept=70000.0,
            support_r2=0.95, resistance_r2=0.90,
            width=10000.0, duration_days=60,
            confirmed_highs=[], confirmed_lows=[],
        )
        # At support
        assert ch.position_pct(60000, 0) == pytest.approx(0.0, abs=0.01)
        # At resistance
        assert ch.position_pct(70000, 0) == pytest.approx(1.0, abs=0.01)
        # Mid channel
        assert ch.position_pct(65000, 0) == pytest.approx(0.5, abs=0.01)
