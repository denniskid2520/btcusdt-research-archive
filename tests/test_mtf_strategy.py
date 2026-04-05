"""Tests for multi-timeframe strategy integration.

TDD: 1h entry confirmation + 15m stop refinement.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from adapters.base import MarketBar, Position
from data.mtf_bars import MultiTimeframeBars
from strategies.trend_breakout import TrendBreakoutConfig, TrendBreakoutStrategy
from tests.fixtures_synthetic_bars import ascending_channel_support_long_bars


def _make_bars_at(base_bars: list[MarketBar], interval_hours: float, count_per_4h: int) -> list[MarketBar]:
    """Generate sub-bars for each 4h bar interval.

    Creates `count_per_4h` bars within each 4h window using the 4h bar's
    price range to create realistic sub-bar movement.
    """
    result = []
    for bar in base_bars:
        ts = bar.timestamp
        step = interval_hours
        for j in range(count_per_4h):
            sub_ts = ts + timedelta(hours=step * j)
            # Create realistic sub-bars within the 4h range
            pct = j / max(count_per_4h - 1, 1)
            price = bar.open + (bar.close - bar.open) * pct
            result.append(MarketBar(
                timestamp=sub_ts,
                open=price - 20,
                high=price + 50,
                low=price - 80,
                close=price,
                volume=bar.volume / count_per_4h,
            ))
    return result


def _make_rejection_1h_bars(base_bars: list[MarketBar]) -> list[MarketBar]:
    """Create 1h bars where the last few show a rejection wick (bounce signal)."""
    bars_1h = _make_bars_at(base_bars, 1.0, 4)
    if len(bars_1h) >= 2:
        # Make the last 1h bar show a bullish rejection (long lower wick)
        last = bars_1h[-1]
        bars_1h[-1] = MarketBar(
            timestamp=last.timestamp,
            open=last.close - 30,
            high=last.close + 10,
            low=last.close - 200,  # long lower wick = rejection at support
            close=last.close,
            volume=last.volume * 3,  # high volume
        )
    return bars_1h


def _make_no_rejection_1h_bars(base_bars: list[MarketBar]) -> list[MarketBar]:
    """Create 1h bars with no clear rejection signal.

    Override the bars near the as_of timestamp (the 4h bar timestamps)
    to have bearish bodies with no lower wick — the opposite of a bounce.
    """
    result = []
    for bar in base_bars:
        ts = bar.timestamp
        for j in range(4):
            sub_ts = ts + timedelta(hours=j)
            price = bar.open + (bar.close - bar.open) * (j / 3)
            # Bearish doji: close near low, no lower wick
            result.append(MarketBar(
                timestamp=sub_ts,
                open=price + 40,
                high=price + 50,  # small upper wick
                low=price,  # close == low → no lower wick
                close=price,
                volume=bar.volume / 4,
            ))
    return result


def test_mtf_entry_confirmation_passes_with_rejection() -> None:
    """1h rejection wick at support confirms long entry."""
    bars_4h = ascending_channel_support_long_bars()
    bars_1h = _make_rejection_1h_bars(bars_4h)

    strategy = TrendBreakoutStrategy(TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        impulse_threshold_pct=0.03,
        entry_buffer_pct=0.35,
        stop_buffer_pct=0.08,
        allow_shorts=False,
        require_parent_confirmation=False,
        mtf_entry_confirmation=True,
        mtf_1h_lookback=4,
    ))

    mtf = MultiTimeframeBars({"4h": bars_4h, "1h": bars_1h})
    result = strategy.evaluate(
        symbol="BTCUSDT",
        bars=bars_4h,
        position=Position(symbol="BTCUSDT"),
        mtf_bars=mtf,
    )
    # With rejection, entry should be confirmed
    assert result.signal.action == "buy"


def test_mtf_entry_confirmation_blocks_without_rejection() -> None:
    """No 1h rejection at support → defer entry (hold)."""
    bars_4h = ascending_channel_support_long_bars()
    bars_1h = _make_no_rejection_1h_bars(bars_4h)

    strategy = TrendBreakoutStrategy(TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        impulse_threshold_pct=0.03,
        entry_buffer_pct=0.35,
        stop_buffer_pct=0.08,
        allow_shorts=False,
        require_parent_confirmation=False,
        mtf_entry_confirmation=True,
        mtf_1h_lookback=4,
    ))

    mtf = MultiTimeframeBars({"4h": bars_4h, "1h": bars_1h})
    result = strategy.evaluate(
        symbol="BTCUSDT",
        bars=bars_4h,
        position=Position(symbol="BTCUSDT"),
        mtf_bars=mtf,
    )
    # Without rejection, entry should be deferred
    assert result.signal.action == "hold"
    assert result.signal.reason == "mtf_1h_no_confirmation"


def test_mtf_disabled_passes_signal_through() -> None:
    """When mtf_entry_confirmation=False, signal passes through unchanged."""
    bars_4h = ascending_channel_support_long_bars()
    bars_1h = _make_no_rejection_1h_bars(bars_4h)

    strategy = TrendBreakoutStrategy(TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        impulse_threshold_pct=0.03,
        entry_buffer_pct=0.35,
        stop_buffer_pct=0.08,
        allow_shorts=False,
        require_parent_confirmation=False,
        mtf_entry_confirmation=False,  # disabled
    ))

    mtf = MultiTimeframeBars({"4h": bars_4h, "1h": bars_1h})
    result = strategy.evaluate(
        symbol="BTCUSDT",
        bars=bars_4h,
        position=Position(symbol="BTCUSDT"),
        mtf_bars=mtf,
    )
    # Should still produce buy (no MTF filter)
    assert result.signal.action == "buy"


def test_mtf_stop_refinement_tightens_stop() -> None:
    """15m swing low provides tighter stop than 4h."""
    bars_4h = ascending_channel_support_long_bars()
    # Create 15m bars with a clear swing low above the 4h stop
    bars_15m = _make_bars_at(bars_4h, 0.25, 16)

    strategy = TrendBreakoutStrategy(TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        impulse_threshold_pct=0.03,
        entry_buffer_pct=0.35,
        stop_buffer_pct=0.08,
        allow_shorts=False,
        require_parent_confirmation=False,
        mtf_stop_refinement=True,
        mtf_15m_lookback=16,
    ))

    mtf = MultiTimeframeBars({"4h": bars_4h, "15m": bars_15m})

    # Get baseline without MTF
    baseline_strategy = TrendBreakoutStrategy(TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        impulse_threshold_pct=0.03,
        entry_buffer_pct=0.35,
        stop_buffer_pct=0.08,
        allow_shorts=False,
        require_parent_confirmation=False,
        mtf_stop_refinement=False,
    ))

    baseline = baseline_strategy.evaluate(
        symbol="BTCUSDT",
        bars=bars_4h,
        position=Position(symbol="BTCUSDT"),
    )
    refined = strategy.evaluate(
        symbol="BTCUSDT",
        bars=bars_4h,
        position=Position(symbol="BTCUSDT"),
        mtf_bars=mtf,
    )

    assert baseline.signal.action == "buy"
    assert refined.signal.action == "buy"
    # Refined stop should be >= baseline stop (tighter for longs = higher)
    if refined.signal.stop_price is not None and baseline.signal.stop_price is not None:
        assert refined.signal.stop_price >= baseline.signal.stop_price


def test_mtf_stop_refinement_respects_max_tighten() -> None:
    """15m stop cannot tighten beyond max_tighten_pct of original distance.

    If 4h stop = $48000 and entry ~$50000 (distance=2000), with max_tighten=0.50
    the refined stop must stay <= $49000 (can only halve the distance).
    """
    bars_4h = ascending_channel_support_long_bars()
    bars_15m = _make_bars_at(bars_4h, 0.25, 16)

    # Get baseline stop first
    baseline_strategy = TrendBreakoutStrategy(TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        impulse_threshold_pct=0.03,
        entry_buffer_pct=0.35,
        stop_buffer_pct=0.08,
        allow_shorts=False,
        require_parent_confirmation=False,
        mtf_stop_refinement=False,
    ))
    baseline = baseline_strategy.evaluate(
        symbol="BTCUSDT",
        bars=bars_4h,
        position=Position(symbol="BTCUSDT"),
    )
    assert baseline.signal.action == "buy"
    assert baseline.signal.stop_price is not None

    entry_price = bars_4h[-1].close
    original_distance = entry_price - baseline.signal.stop_price

    # Now test with max_tighten_pct=0.50
    strategy = TrendBreakoutStrategy(TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        impulse_threshold_pct=0.03,
        entry_buffer_pct=0.35,
        stop_buffer_pct=0.08,
        allow_shorts=False,
        require_parent_confirmation=False,
        mtf_stop_refinement=True,
        mtf_15m_lookback=16,
        mtf_stop_max_tighten_pct=0.50,
    ))
    mtf = MultiTimeframeBars({"4h": bars_4h, "15m": bars_15m})
    refined = strategy.evaluate(
        symbol="BTCUSDT",
        bars=bars_4h,
        position=Position(symbol="BTCUSDT"),
        mtf_bars=mtf,
    )
    assert refined.signal.action == "buy"
    assert refined.signal.stop_price is not None

    # Refined distance should be at least 50% of original
    refined_distance = entry_price - refined.signal.stop_price
    assert refined_distance >= original_distance * 0.50, (
        f"Stop too tight: refined_distance={refined_distance:.2f}, "
        f"min_allowed={original_distance * 0.50:.2f}"
    )


def test_mtf_1h_scale_mode_full_confidence_with_rejection() -> None:
    """1h rejection → confidence=1.0, trade still executes."""
    bars_4h = ascending_channel_support_long_bars()
    bars_1h = _make_rejection_1h_bars(bars_4h)

    strategy = TrendBreakoutStrategy(TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        impulse_threshold_pct=0.03,
        entry_buffer_pct=0.35,
        stop_buffer_pct=0.08,
        allow_shorts=False,
        require_parent_confirmation=False,
        mtf_entry_confirmation=True,
        mtf_1h_sizing_mode="scale",
        mtf_1h_lookback=4,
    ))

    mtf = MultiTimeframeBars({"4h": bars_4h, "1h": bars_1h})
    result = strategy.evaluate(
        symbol="BTCUSDT",
        bars=bars_4h,
        position=Position(symbol="BTCUSDT"),
        mtf_bars=mtf,
    )
    assert result.signal.action == "buy"
    assert result.signal.confidence == 1.0


def test_mtf_1h_scale_mode_half_confidence_without_rejection() -> None:
    """No 1h rejection → confidence=0.5, trade NOT blocked (unlike 'block' mode)."""
    bars_4h = ascending_channel_support_long_bars()
    bars_1h = _make_no_rejection_1h_bars(bars_4h)

    strategy = TrendBreakoutStrategy(TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        impulse_threshold_pct=0.03,
        entry_buffer_pct=0.35,
        stop_buffer_pct=0.08,
        allow_shorts=False,
        require_parent_confirmation=False,
        mtf_entry_confirmation=True,
        mtf_1h_sizing_mode="scale",
        mtf_1h_lookback=4,
        mtf_1h_no_confirm_confidence=0.5,
    ))

    mtf = MultiTimeframeBars({"4h": bars_4h, "1h": bars_1h})
    result = strategy.evaluate(
        symbol="BTCUSDT",
        bars=bars_4h,
        position=Position(symbol="BTCUSDT"),
        mtf_bars=mtf,
    )
    # NOT hold — trade passes through with reduced confidence
    assert result.signal.action == "buy"
    assert result.signal.confidence == 0.5


def test_mtf_three_timeframe_combined() -> None:
    """4h signal + 1h confidence scaling + 15m stop refinement all work together."""
    bars_4h = ascending_channel_support_long_bars()
    bars_1h = _make_rejection_1h_bars(bars_4h)
    bars_15m = _make_bars_at(bars_4h, 0.25, 16)

    strategy = TrendBreakoutStrategy(TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        impulse_threshold_pct=0.03,
        entry_buffer_pct=0.35,
        stop_buffer_pct=0.08,
        allow_shorts=False,
        require_parent_confirmation=False,
        # 1h: scale mode
        mtf_entry_confirmation=True,
        mtf_1h_sizing_mode="scale",
        mtf_1h_lookback=4,
        # 15m: stop refinement
        mtf_stop_refinement=True,
        mtf_15m_lookback=16,
        mtf_stop_max_tighten_pct=0.30,
    ))

    mtf = MultiTimeframeBars({"4h": bars_4h, "1h": bars_1h, "15m": bars_15m})
    result = strategy.evaluate(
        symbol="BTCUSDT",
        bars=bars_4h,
        position=Position(symbol="BTCUSDT"),
        mtf_bars=mtf,
    )
    assert result.signal.action == "buy"
    assert result.signal.confidence == 1.0  # 1h confirmed
    assert result.signal.stop_price is not None  # 15m refined


def test_confidence_multiplier_scales_position_size() -> None:
    """calculate_order_quantity with confidence_multiplier=0.5 gives half size."""
    from risk.limits import RiskLimits, calculate_order_quantity

    limits = RiskLimits(max_position_pct=0.90, risk_per_trade_pct=0.05, leverage=3)
    full = calculate_order_quantity(
        cash=10_000, market_price=50_000, limits=limits,
        stop_distance_pct=0.05, confidence_multiplier=1.0,
    )
    half = calculate_order_quantity(
        cash=10_000, market_price=50_000, limits=limits,
        stop_distance_pct=0.05, confidence_multiplier=0.5,
    )
    assert full > 0
    assert abs(half - full * 0.5) < 1e-10


def test_mtf_no_mtf_bars_skips_refinement() -> None:
    """When mtf_bars is None, MTF features are silently skipped."""
    bars_4h = ascending_channel_support_long_bars()

    strategy = TrendBreakoutStrategy(TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        impulse_threshold_pct=0.03,
        entry_buffer_pct=0.35,
        stop_buffer_pct=0.08,
        allow_shorts=False,
        require_parent_confirmation=False,
        mtf_entry_confirmation=True,  # enabled but no mtf_bars
    ))

    result = strategy.evaluate(
        symbol="BTCUSDT",
        bars=bars_4h,
        position=Position(symbol="BTCUSDT"),
        mtf_bars=None,  # no MTF data
    )
    # Should still produce buy (graceful degradation)
    assert result.signal.action == "buy"
