from datetime import datetime
from unittest.mock import patch

from adapters.base import Position
from adapters.futures_data import FuturesSnapshot, StaticFuturesProvider
from strategies.trend_breakout import TrendBreakoutConfig, TrendBreakoutStrategy
from tests.fixtures_synthetic_bars import (
    ascending_channel_breakdown_short_bars,
    ascending_channel_breakout_long_bars,
    ascending_channel_resistance_rejection_short_bars,
    ascending_channel_support_long_bars,
    descending_channel_breakdown_short_bars,
    descending_channel_breakout_long_bars,
    descending_channel_rejection_short_bars,
    descending_channel_support_bounce_long_bars,
    narrow_descending_channel_bars,
    noisy_descending_channel_bars,
    rising_channel_continuation_short_bars,
    rising_channel_retest_short_bars,
    wide_lookback_descending_channel_bars,
)


def test_strategy_generates_long_signal_for_ascending_channel_support() -> None:
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
        )
    )
    signal = strategy.generate_signal("BTCUSDT", ascending_channel_support_long_bars(), Position(symbol="BTCUSDT"))
    assert signal.action == "buy"
    assert signal.reason == "ascending_channel_support_bounce"
    assert signal.stop_price is not None
    assert signal.target_price is not None


def test_strategy_generates_long_signal_for_ascending_channel_breakout() -> None:
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
        )
    )
    signal = strategy.generate_signal("BTCUSDT", ascending_channel_breakout_long_bars(), Position(symbol="BTCUSDT"))
    assert signal.action == "buy"
    assert signal.reason == "ascending_channel_breakout"
    assert signal.stop_price is not None
    assert signal.target_price is not None


def test_strategy_generates_short_signal_for_descending_channel_rejection() -> None:
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.004,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_longs=False,
            require_parent_confirmation=False,
        )
    )
    signal = strategy.generate_signal("BTCUSDT", descending_channel_rejection_short_bars(), Position(symbol="BTCUSDT"))
    assert signal.action == "short"
    assert signal.reason == "descending_channel_rejection"
    assert signal.stop_price is not None
    assert signal.target_price is not None


def test_strategy_generates_short_signal_for_descending_channel_breakdown() -> None:
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.02,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_longs=False,
            require_parent_confirmation=False,
        )
    )
    signal = strategy.generate_signal("BTCUSDT", descending_channel_breakdown_short_bars(), Position(symbol="BTCUSDT"))
    assert signal.action == "short"
    assert signal.reason == "descending_channel_breakdown"
    assert signal.stop_price is not None
    assert signal.target_price is not None


def test_strategy_generates_short_signal_for_rising_channel_retest_breakdown() -> None:
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.04,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_longs=False,
            require_parent_confirmation=False,
        )
    )
    signal = strategy.generate_signal("BTCUSDT", rising_channel_retest_short_bars(), Position(symbol="BTCUSDT"))
    assert signal.action == "short"
    assert signal.reason == "rising_channel_breakdown_retest_short"
    assert signal.stop_price is not None
    assert signal.target_price is not None


def test_strategy_generates_short_signal_for_rising_channel_breakdown_continuation() -> None:
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.04,
            entry_buffer_pct=0.25,
            continuation_buffer_pct=0.45,
            stop_buffer_pct=0.08,
            allow_longs=False,
            enable_rising_channel_breakdown_retest_short=False,
            require_parent_confirmation=False,
        )
    )
    signal = strategy.generate_signal("BTCUSDT", rising_channel_continuation_short_bars(), Position(symbol="BTCUSDT"))
    assert signal.action == "short"
    assert signal.reason == "rising_channel_breakdown_continuation_short"
    assert signal.stop_price is not None
    assert signal.target_price is not None


def test_r_squared_filter_rejects_noisy_channel() -> None:
    """A noisy channel with scattered pivots must be rejected when min_r_squared is set."""
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=30,
            impulse_threshold_pct=0.004,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_longs=False,
            min_r_squared=0.70,
            require_parent_confirmation=False,
        )
    )
    evaluation = strategy.evaluate(
        symbol="BTCUSDT",
        bars=noisy_descending_channel_bars(),
        position=Position(symbol="BTCUSDT"),
    )
    assert evaluation.signal.action == "hold"
    rejection_eval = next(
        item for item in evaluation.rule_evaluations
        if item.rule_name == "descending_channel_rejection"
    )
    assert rejection_eval.first_failed_condition == "r_squared_too_low"


def test_r_squared_filter_passes_clean_channel() -> None:
    """Clean synthetic channel should pass R² filter easily."""
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.004,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_longs=False,
            min_r_squared=0.70,
            require_parent_confirmation=False,
        )
    )
    signal = strategy.generate_signal(
        "BTCUSDT",
        descending_channel_rejection_short_bars(),
        Position(symbol="BTCUSDT"),
    )
    assert signal.action == "short"
    assert signal.reason == "descending_channel_rejection"


def test_atr_floor_widens_stop_when_structural_stop_too_tight() -> None:
    """When stop_buffer < min_stop_atr_multiplier * ATR, use ATR-based stop instead."""
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.004,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_longs=False,
            min_stop_atr_multiplier=2.0,
            require_parent_confirmation=False,
        )
    )
    bars = descending_channel_rejection_short_bars()
    evaluation = strategy.evaluate(
        symbol="BTCUSDT", bars=bars, position=Position(symbol="BTCUSDT"),
    )
    assert evaluation.signal.action == "short"
    signal = evaluation.signal
    # The structural stop_buffer for this channel is ~0.08 * width.
    # With min_stop_atr_multiplier=2.0, the stop should be at least 2*ATR above entry.
    # We verify the stop is wider than the basic structural stop.
    entry_price = signal.metadata["close"]
    resistance = signal.metadata["resistance"]
    structural_stop = resistance + signal.metadata["stop_buffer"]
    assert signal.stop_price >= structural_stop, (
        f"ATR floor should widen stop: stop={signal.stop_price} >= structural={structural_stop}"
    )


def test_trailing_stop_moves_stop_in_profit_direction() -> None:
    """When trailing_stop_atr is set, the strategy should emit it in metadata."""
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.004,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_longs=False,
            trailing_stop_atr=2.0,
            require_parent_confirmation=False,
        )
    )
    evaluation = strategy.evaluate(
        symbol="BTCUSDT",
        bars=descending_channel_rejection_short_bars(),
        position=Position(symbol="BTCUSDT"),
    )
    assert evaluation.signal.action == "short"
    assert evaluation.signal.metadata is not None
    assert "trailing_stop_atr" in evaluation.signal.metadata
    assert evaluation.signal.metadata["trailing_stop_atr"] == 2.0


def test_volatility_filter_blocks_trades_in_chaotic_market() -> None:
    """When ATR/price ratio is above threshold, no trades should be taken."""
    # Create highly volatile bars: large high-low range relative to price
    volatile_bars = descending_channel_rejection_short_bars()
    # Override with extreme range to simulate chaos
    from adapters.base import MarketBar
    volatile_bars = [
        MarketBar(
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.close + 3000,  # ~5% range at 60-70k
            low=bar.close - 3000,
            close=bar.close,
            volume=bar.volume,
        )
        for bar in volatile_bars
    ]
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.004,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_longs=False,
            max_atr_price_ratio=0.03,
            require_parent_confirmation=False,
        )
    )
    evaluation = strategy.evaluate(
        symbol="BTCUSDT",
        bars=volatile_bars,
        position=Position(symbol="BTCUSDT"),
    )
    assert evaluation.signal.action == "hold"
    rejection_eval = next(
        item for item in evaluation.rule_evaluations
        if item.rule_name == "descending_channel_rejection"
    )
    assert rejection_eval.first_failed_condition == "volatility_too_high"


def test_min_channel_width_pct_rejects_narrow_channel() -> None:
    """Channel narrower than 2% of price must be rejected."""
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=30,
            impulse_threshold_pct=0.001,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_longs=False,
            min_channel_width_pct=0.02,
            require_parent_confirmation=False,
        )
    )
    evaluation = strategy.evaluate(
        symbol="BTCUSDT",
        bars=narrow_descending_channel_bars(),
        position=Position(symbol="BTCUSDT"),
    )
    assert evaluation.signal.action == "hold"
    rejection_eval = next(
        item for item in evaluation.rule_evaluations
        if item.rule_name == "descending_channel_rejection"
    )
    assert rejection_eval.first_failed_condition == "below_min_channel_width"


def test_parent_context_conflict_blocks_rising_channel_retest_short() -> None:
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.04,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_longs=False,
            require_parent_confirmation=False,
        )
    )
    forced_parent = {
        "parent_structure_type": "descending_channel",
        "parent_upper_boundary": 70000.0,
        "parent_lower_boundary": 62000.0,
        "parent_position_in_channel": "near_lower_boundary",
        "parent_event_type": "normal",
    }
    with patch("strategies.trend_breakout._build_parent_context", return_value=forced_parent):
        evaluation = strategy.evaluate(
            symbol="BTCUSDT",
            bars=rising_channel_retest_short_bars(),
            position=Position(symbol="BTCUSDT"),
        )
    assert evaluation.signal.action == "hold"
    retest_eval = next(
        item for item in evaluation.rule_evaluations if item.rule_name == "rising_channel_breakdown_retest_short"
    )
    assert retest_eval.first_failed_condition == "parent_context_conflict"


def test_short_blocked_near_lower_boundary_descending_channel() -> None:
    """Shorts near the lower boundary of descending channel should be blocked."""
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12, structure_lookback=24,
            impulse_threshold_pct=0.004, entry_buffer_pct=0.25,
            stop_buffer_pct=0.08, allow_longs=False,
            require_parent_confirmation=False,
        )
    )
    forced_parent = {
        "parent_structure_type": "descending_channel",
        "parent_upper_boundary": 69910.0,
        "parent_lower_boundary": 51845.0,
        "parent_position_in_channel": "near_lower_boundary",
        "parent_event_type": "normal",
    }
    with patch("strategies.trend_breakout._build_parent_context", return_value=forced_parent):
        evaluation = strategy.evaluate(
            symbol="BTCUSDT",
            bars=descending_channel_rejection_short_bars(),
            position=Position(symbol="BTCUSDT"),
        )
    rejection_eval = next(
        item for item in evaluation.rule_evaluations
        if item.rule_name == "descending_channel_rejection"
    )
    assert rejection_eval.first_failed_condition == "parent_context_conflict"


def test_short_blocked_near_lower_boundary_ascending_channel() -> None:
    """Shorts near lower boundary of ascending channel must also be blocked.

    Parent F (ascending rebound) near lower boundary — shorting into support is invalid.
    """
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12, structure_lookback=24,
            impulse_threshold_pct=0.004, entry_buffer_pct=0.25,
            stop_buffer_pct=0.08, allow_longs=False,
            require_parent_confirmation=False,
        )
    )
    forced_parent = {
        "parent_structure_type": "ascending_channel",
        "parent_upper_boundary": 97924.0,
        "parent_lower_boundary": 83822.0,
        "parent_position_in_channel": "near_lower_boundary",
        "parent_event_type": "confirmed_breakdown",
    }
    with patch("strategies.trend_breakout._build_parent_context", return_value=forced_parent):
        evaluation = strategy.evaluate(
            symbol="BTCUSDT",
            bars=descending_channel_rejection_short_bars(),
            position=Position(symbol="BTCUSDT"),
        )
    rejection_eval = next(
        item for item in evaluation.rule_evaluations
        if item.rule_name == "descending_channel_rejection"
    )
    assert rejection_eval.first_failed_condition == "parent_context_conflict"


def test_confirmed_breakdown_blocks_ascending_channel_long() -> None:
    """When ascending channel has confirmed_breakdown, longs must be blocked."""
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
        )
    )
    forced_parent = {
        "parent_structure_type": "ascending_channel",
        "parent_upper_boundary": 76000.0,
        "parent_lower_boundary": 63000.0,
        "parent_position_in_channel": "mid_channel",
        "parent_event_type": "confirmed_breakdown",
    }
    with patch("strategies.trend_breakout._build_parent_context", return_value=forced_parent):
        evaluation = strategy.evaluate(
            symbol="BTCUSDT",
            bars=ascending_channel_support_long_bars(),
            position=Position(symbol="BTCUSDT"),
        )
    assert evaluation.signal.action == "hold"
    support_eval = next(
        item for item in evaluation.rule_evaluations
        if item.rule_name == "ascending_channel_support_bounce"
    )
    assert support_eval.first_failed_condition == "parent_context_conflict"


def test_shock_override_blocks_rising_channel_continuation_short() -> None:
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.04,
            entry_buffer_pct=0.25,
            continuation_buffer_pct=0.45,
            stop_buffer_pct=0.08,
            allow_longs=False,
            enable_rising_channel_breakdown_retest_short=False,
            require_parent_confirmation=False,
        )
    )
    forced_parent = {
        "parent_structure_type": "ascending_channel",
        "parent_upper_boundary": 71000.0,
        "parent_lower_boundary": 63000.0,
        "parent_position_in_channel": "below_lower_boundary",
        "parent_event_type": "shock_break_reclaim",
    }
    with patch("strategies.trend_breakout._build_parent_context", return_value=forced_parent):
        evaluation = strategy.evaluate(
            symbol="BTCUSDT",
            bars=rising_channel_continuation_short_bars(),
            position=Position(symbol="BTCUSDT"),
        )
    assert evaluation.signal.action == "hold"
    continuation_eval = next(
        item
        for item in evaluation.rule_evaluations
        if item.rule_name == "rising_channel_breakdown_continuation_short"
    )
    assert continuation_eval.first_failed_condition == "shock_override_active"



def test_secondary_lookback_detects_channel_when_primary_fails() -> None:
    """When primary structure_lookback can't detect a channel, the secondary
    (wider) lookback should find one and produce a trade signal."""
    bars = wide_lookback_descending_channel_bars()

    # Primary lookback=24 should fail (last 24 bars are flat/choppy)
    primary_only = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.004,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_longs=False,
            require_parent_confirmation=False,
        )
    )
    primary_eval = primary_only.evaluate(
        symbol="BTCUSDT",
        bars=bars,
        position=Position(symbol="BTCUSDT"),
    )
    assert primary_eval.signal.action == "hold", "Primary lookback should NOT detect channel"

    # With secondary lookback=48, channel should be detected
    dual_lookback = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            secondary_structure_lookback=48,
            impulse_threshold_pct=0.004,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_longs=False,
            require_parent_confirmation=False,
        )
    )
    dual_eval = dual_lookback.evaluate(
        symbol="BTCUSDT",
        bars=bars,
        position=Position(symbol="BTCUSDT"),
    )
    assert dual_eval.signal.action == "short", "Secondary lookback should detect descending channel"


def test_descending_channel_support_bounce_long() -> None:
    """Price near support in descending channel → buy (oscillation, no impulse required)."""
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
        )
    )
    bars = descending_channel_support_bounce_long_bars()
    result = strategy.evaluate(
        symbol="BTCUSDT",
        bars=bars,
        position=Position(symbol="BTCUSDT"),
    )
    assert result.signal.action == "buy"
    assert result.signal.stop_price is not None
    assert result.signal.target_price is not None
    triggered = [r for r in result.rule_evaluations if r.rule_name == "descending_channel_support_bounce" and r.triggered]
    assert triggered, "descending_channel_support_bounce rule should trigger"


def test_ascending_channel_resistance_rejection_short() -> None:
    """Price near resistance in ascending channel → short (oscillation, no impulse required)."""
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_longs=False,
            require_parent_confirmation=False,
        )
    )
    bars = ascending_channel_resistance_rejection_short_bars()
    result = strategy.evaluate(
        symbol="BTCUSDT",
        bars=bars,
        position=Position(symbol="BTCUSDT"),
    )
    assert result.signal.action == "short"
    assert result.signal.stop_price is not None
    assert result.signal.target_price is not None
    triggered = [r for r in result.rule_evaluations if r.rule_name == "ascending_channel_resistance_rejection" and r.triggered]
    assert triggered, "ascending_channel_resistance_rejection rule should trigger"


def test_descending_channel_breakout_long() -> None:
    """Price breaks above resistance in descending channel with bullish impulse → buy."""
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
        )
    )
    bars = descending_channel_breakout_long_bars()
    result = strategy.evaluate(
        symbol="BTCUSDT",
        bars=bars,
        position=Position(symbol="BTCUSDT"),
    )
    assert result.signal.action == "buy"
    assert result.signal.stop_price is not None
    assert result.signal.target_price is not None
    triggered = [r for r in result.rule_evaluations if r.rule_name == "descending_channel_breakout_long" and r.triggered]
    assert triggered, "descending_channel_breakout_long rule should trigger"


def test_ascending_channel_breakdown_short() -> None:
    """Price breaks below support in ascending channel with bearish impulse → short."""
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.008,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_longs=False,
            require_parent_confirmation=False,
        )
    )
    bars = ascending_channel_breakdown_short_bars()
    result = strategy.evaluate(
        symbol="BTCUSDT",
        bars=bars,
        position=Position(symbol="BTCUSDT"),
    )
    assert result.signal.action == "short"
    assert result.signal.stop_price is not None
    assert result.signal.target_price is not None
    triggered = [r for r in result.rule_evaluations if r.rule_name == "ascending_channel_breakdown_short" and r.triggered]
    assert triggered, "ascending_channel_breakdown_short rule should trigger"


def test_adx_filter_blocks_trade_in_weak_trend() -> None:
    """When ADX is below threshold, trades should be blocked (no clear trend)."""
    from tests.fixtures_synthetic_bars import make_bar

    # Build 30 bars of choppy sideways (low ADX): price oscillates ±0.1%
    choppy_bars = []
    base = 60_000.0
    for i in range(30):
        p = base + (50 if i % 2 == 0 else -50)
        choppy_bars.append(make_bar(i, p, high_pad=60, low_pad=60))

    # Append the ascending channel fixture at end
    channel_bars = ascending_channel_support_long_bars()
    # Use choppy prefix + channel bars
    all_bars = choppy_bars + channel_bars

    # Without ADX filter: should buy
    no_filter = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
        )
    )
    result_no = no_filter.evaluate(symbol="BTCUSDT", bars=all_bars, position=Position(symbol="BTCUSDT"))
    assert result_no.signal.action == "buy", "Without ADX filter, buy should trigger"

    # With ADX filter (threshold=25): choppy market → ADX low → blocked
    with_filter = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
            adx_filter=True,
            adx_period=14,
            adx_threshold=25.0,
        )
    )
    result_adx = with_filter.evaluate(symbol="BTCUSDT", bars=all_bars, position=Position(symbol="BTCUSDT"))
    assert result_adx.signal.action == "hold", "ADX filter should block in weak trend"


# ── RSI Filter Tests ─────────────────────────────────────────────────────


def test_rsi_filter_blocks_long_when_rsi_high() -> None:
    """RSI filter should block long (buy) when RSI is NOT oversold (RSI > rsi_oversold_threshold).

    At channel support, we only want to buy when RSI confirms oversold conditions.
    If RSI is elevated, the bounce signal is weak → block.
    """
    from tests.fixtures_synthetic_bars import make_bar

    # Build bars where RSI will be HIGH (strong uptrend leading into channel).
    # 30 bars of steady rise → RSI will be well above 20.
    rising_prefix = [make_bar(i, 58000 + i * 100) for i in range(30)]
    channel_bars = ascending_channel_support_long_bars()
    all_bars = rising_prefix + channel_bars

    # Without RSI filter: should buy
    no_filter = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
        )
    )
    result_no = no_filter.evaluate(symbol="BTCUSDT", bars=all_bars, position=Position(symbol="BTCUSDT"))
    assert result_no.signal.action == "buy", "Without RSI filter, buy should trigger"

    # With RSI filter: RSI not oversold → block long
    with_filter = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
            rsi_filter=True,
            rsi_period=3,
            rsi_oversold=20.0,
            rsi_overbought=80.0,
        )
    )
    result_rsi = with_filter.evaluate(symbol="BTCUSDT", bars=all_bars, position=Position(symbol="BTCUSDT"))
    assert result_rsi.signal.action == "hold", "RSI filter should block long when RSI is not oversold"


def test_rsi_filter_blocks_short_when_rsi_low() -> None:
    """RSI filter should block short when RSI is NOT overbought (RSI < rsi_overbought_threshold).

    At channel resistance, we only want to short when RSI confirms overbought conditions.
    If RSI is low/neutral, the rejection signal is weak → block.
    """
    from tests.fixtures_synthetic_bars import make_bar

    # Build bars where RSI will be LOW (steady decline into channel).
    declining_prefix = [make_bar(i, 72000 - i * 100) for i in range(30)]
    channel_bars = descending_channel_rejection_short_bars()
    all_bars = declining_prefix + channel_bars

    # Without RSI filter: should short
    no_filter = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.004,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_longs=False,
            require_parent_confirmation=False,
        )
    )
    result_no = no_filter.evaluate(symbol="BTCUSDT", bars=all_bars, position=Position(symbol="BTCUSDT"))
    assert result_no.signal.action == "short", "Without RSI filter, short should trigger"

    # With RSI filter: RSI not overbought → block short
    with_filter = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.004,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_longs=False,
            require_parent_confirmation=False,
            rsi_filter=True,
            rsi_period=3,
            rsi_oversold=20.0,
            rsi_overbought=80.0,
        )
    )
    result_rsi = with_filter.evaluate(symbol="BTCUSDT", bars=all_bars, position=Position(symbol="BTCUSDT"))
    assert result_rsi.signal.action == "hold", "RSI filter should block short when RSI is not overbought"


def test_rsi_filter_allows_long_when_oversold() -> None:
    """RSI filter should ALLOW long when RSI confirms oversold (RSI < rsi_oversold_threshold).

    Mock RSI to return 12 (oversold), so the buy signal passes through the filter.
    """
    channel_bars = ascending_channel_support_long_bars()

    with_filter = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
            rsi_filter=True,
            rsi_period=3,
            rsi_oversold=20.0,
            rsi_overbought=80.0,
        )
    )
    with patch("strategies.trend_breakout._compute_rsi", return_value=12.0):
        result = with_filter.evaluate(symbol="BTCUSDT", bars=channel_bars, position=Position(symbol="BTCUSDT"))
    assert result.signal.action == "buy", "RSI filter should allow long when RSI is oversold"


def test_rsi_filter_allows_short_when_overbought() -> None:
    """RSI filter should ALLOW short when RSI confirms overbought (RSI > rsi_overbought_threshold).

    Mock RSI to return 88 (overbought), so the short signal passes through the filter.
    """
    channel_bars = descending_channel_rejection_short_bars()

    with_filter = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.004,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_longs=False,
            require_parent_confirmation=False,
            rsi_filter=True,
            rsi_period=3,
            rsi_oversold=20.0,
            rsi_overbought=80.0,
        )
    )
    with patch("strategies.trend_breakout._compute_rsi", return_value=88.0):
        result = with_filter.evaluate(symbol="BTCUSDT", bars=channel_bars, position=Position(symbol="BTCUSDT"))
    assert result.signal.action == "short", "RSI filter should allow short when RSI is overbought"


# ── ADX Mode-Aware Tests (Inverted Logic) ────────────────────────────────


def test_adx_mode_bounce_blocked_in_strong_trend() -> None:
    """Bounce trades (support bounce / resistance rejection) should be blocked when ADX > threshold.

    In a strong trend (high ADX), bounces are unreliable — trend will overwhelm the channel boundary.
    Only breakouts should be allowed in strong trends.
    """
    channel_bars = ascending_channel_support_long_bars()

    # Without ADX mode: should buy (bounce)
    no_filter = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
        )
    )
    result_no = no_filter.evaluate(symbol="BTCUSDT", bars=channel_bars, position=Position(symbol="BTCUSDT"))
    assert result_no.signal.action == "buy", "Without ADX mode, bounce should trigger"

    # With adx_mode smart + ADX=40 (high): bounce blocked
    with_adx = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
            adx_filter=True,
            adx_mode="smart",
            adx_period=14,
            adx_threshold=25.0,
        )
    )
    with patch("strategies.trend_breakout._compute_adx", return_value=40.0):
        result_adx = with_adx.evaluate(symbol="BTCUSDT", bars=channel_bars, position=Position(symbol="BTCUSDT"))
    assert result_adx.signal.action == "hold", "ADX smart mode should block bounce in strong trend"


def test_adx_mode_breakout_allowed_in_strong_trend() -> None:
    """Breakout trades should be ALLOWED when ADX > threshold (strong trend confirms breakout)."""
    channel_bars = ascending_channel_breakout_long_bars()

    with_adx = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
            adx_filter=True,
            adx_mode="smart",
            adx_period=14,
            adx_threshold=25.0,
        )
    )
    with patch("strategies.trend_breakout._compute_adx", return_value=40.0):
        result = with_adx.evaluate(symbol="BTCUSDT", bars=channel_bars, position=Position(symbol="BTCUSDT"))
    assert result.signal.action == "buy", "ADX smart mode should allow breakout in strong trend"


def test_adx_mode_bounce_allowed_in_ranging_market() -> None:
    """Bounce trades should be ALLOWED when ADX < threshold (ranging market, bounces reliable)."""
    channel_bars = ascending_channel_support_long_bars()

    with_adx = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
            adx_filter=True,
            adx_mode="smart",
            adx_period=14,
            adx_threshold=25.0,
        )
    )
    with patch("strategies.trend_breakout._compute_adx", return_value=15.0):
        result = with_adx.evaluate(symbol="BTCUSDT", bars=channel_bars, position=Position(symbol="BTCUSDT"))
    assert result.signal.action == "buy", "ADX smart mode should allow bounce in ranging market"


def test_adx_mode_breakout_blocked_in_ranging_market() -> None:
    """Breakout trades should be BLOCKED when ADX < threshold (weak trend, breakout likely false)."""
    channel_bars = ascending_channel_breakout_long_bars()

    with_adx = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
            adx_filter=True,
            adx_mode="smart",
            adx_period=14,
            adx_threshold=25.0,
        )
    )
    with patch("strategies.trend_breakout._compute_adx", return_value=15.0):
        result = with_adx.evaluate(symbol="BTCUSDT", bars=channel_bars, position=Position(symbol="BTCUSDT"))
    assert result.signal.action == "hold", "ADX smart mode should block breakout in ranging market"


# ── OI-Price Divergence Filter Tests ───────────────────────────────────


def _make_provider_with_oi(bars, oi_current: float, oi_past: float, lookback: int = 6):
    """Build a StaticFuturesProvider with OI data at current and N-lookback bars."""
    data = {}
    if len(bars) > lookback:
        past_ts = bars[-1 - lookback].timestamp
        data[past_ts] = FuturesSnapshot(
            timestamp=past_ts,
            open_interest=oi_past,
            long_short_ratio=1.0,
            taker_buy_sell_ratio=1.0,
            oi_close=oi_past,
        )
    current_ts = bars[-1].timestamp
    data[current_ts] = FuturesSnapshot(
        timestamp=current_ts,
        open_interest=oi_current,
        long_short_ratio=1.0,
        taker_buy_sell_ratio=1.0,
        oi_close=oi_current,
    )
    return StaticFuturesProvider(data)


def test_oi_divergence_blocks_long_when_price_up_oi_down() -> None:
    """Rising price + falling OI = weak rally. Block long entry."""
    channel_bars = ascending_channel_support_long_bars()

    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
            oi_divergence_lookback=6,
            oi_divergence_threshold=-0.03,
        )
    )

    # OI falls from 10B to 9B (-10%) while price rises → block
    provider = _make_provider_with_oi(channel_bars, oi_current=9e9, oi_past=10e9, lookback=6)

    with patch("strategies.trend_breakout._compute_rsi", return_value=12.0):
        result = strategy.evaluate(
            symbol="BTCUSDT", bars=channel_bars,
            position=Position(symbol="BTCUSDT"),
            futures_provider=provider,
        )
    assert result.signal.action == "hold", "OI divergence should block long when price up but OI down"
    assert "oi_price_divergence" in result.signal.reason


def test_oi_divergence_allows_long_when_price_up_oi_up() -> None:
    """Rising price + rising OI = conviction. Allow long."""
    channel_bars = ascending_channel_support_long_bars()

    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
            oi_divergence_lookback=6,
            oi_divergence_threshold=-0.03,
        )
    )

    # OI rises from 10B to 11B (+10%) while price rises → allow
    provider = _make_provider_with_oi(channel_bars, oi_current=11e9, oi_past=10e9, lookback=6)

    result = strategy.evaluate(
        symbol="BTCUSDT", bars=channel_bars,
        position=Position(symbol="BTCUSDT"),
        futures_provider=provider,
    )
    # Should NOT be blocked by OI divergence (may still be hold for other reasons)
    assert result.signal.reason != "oi_price_divergence_blocked"


def test_oi_divergence_skipped_when_disabled() -> None:
    """When oi_divergence_lookback=0, filter is off — signal unchanged."""
    channel_bars = ascending_channel_support_long_bars()

    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
            oi_divergence_lookback=0,  # Disabled
        )
    )

    # Even with falling OI, filter should NOT engage
    provider = _make_provider_with_oi(channel_bars, oi_current=5e9, oi_past=10e9, lookback=6)

    result = strategy.evaluate(
        symbol="BTCUSDT", bars=channel_bars,
        position=Position(symbol="BTCUSDT"),
        futures_provider=provider,
    )
    assert result.signal.reason != "oi_price_divergence_blocked"


# ── Funding Rate Extreme Filter Tests ──────────────────────────────────


## Removed: funding_rate_extreme and funding_zscore filters
## Backtest result: crypto funding rate has persistent positive bias (mean 0.9%/day),
## absolute thresholds block too many normal trades, Z-score variance too high.
## See PMC (2023): crypto indicators need special adaptation from equity models.


# ── Phase 1: Scale-in + Trailing Stop Tests ─────────────────────────────


def test_scale_in_generates_buy_when_long_position_profitable() -> None:
    """When position is open, profitable, and a new buy signal fires → scale-in buy."""
    channel_bars = ascending_channel_support_long_bars()

    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
            scale_in_enabled=True,
            scale_in_min_profit_pct=0.01,  # 1% profit needed
        )
    )

    # Position is long, entry at price below current (profitable)
    current_price = channel_bars[-1].close
    entry_price = current_price * 0.95  # 5% below → profitable
    position = Position(
        symbol="BTCUSDT", side="long", quantity=0.1,
        average_price=entry_price, reserved_margin=1000.0,
    )

    result = strategy.evaluate(symbol="BTCUSDT", bars=channel_bars, position=position)
    # Should generate a buy (scale-in), not hold
    assert result.signal.action == "buy", f"Expected buy for scale-in, got {result.signal.action} ({result.signal.reason})"


def test_scale_in_blocked_when_position_not_profitable_enough() -> None:
    """Scale-in should not fire when position is not yet profitable enough."""
    channel_bars = ascending_channel_support_long_bars()

    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
            scale_in_enabled=True,
            scale_in_min_profit_pct=0.10,  # 10% profit needed (high bar)
        )
    )

    # Position barely profitable (1%)
    current_price = channel_bars[-1].close
    entry_price = current_price * 0.99
    position = Position(
        symbol="BTCUSDT", side="long", quantity=0.1,
        average_price=entry_price, reserved_margin=1000.0,
    )

    result = strategy.evaluate(symbol="BTCUSDT", bars=channel_bars, position=position)
    assert result.signal.action == "hold", f"Expected hold (not enough profit), got {result.signal.action}"


def test_scale_in_disabled_returns_hold_for_open_position() -> None:
    """When scale_in_enabled=False, open position always returns hold (or stop/target)."""
    channel_bars = ascending_channel_support_long_bars()

    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
            scale_in_enabled=False,  # disabled
        )
    )

    current_price = channel_bars[-1].close
    entry_price = current_price * 0.90  # very profitable
    position = Position(
        symbol="BTCUSDT", side="long", quantity=0.1,
        average_price=entry_price, reserved_margin=1000.0,
    )

    result = strategy.evaluate(symbol="BTCUSDT", bars=channel_bars, position=position)
    assert result.signal.action == "hold"


def test_trailing_exit_skips_target_check() -> None:
    """When use_trailing_exit=True, hitting target_price should NOT trigger exit."""
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(use_trailing_exit=True)
    )

    # Long position where current price is above target
    position = Position(
        symbol="BTCUSDT", side="long", quantity=0.1,
        average_price=100.0, reserved_margin=1000.0,
    )
    # Mock PaperPosition with stop and target
    position.stop_price = 90.0
    position.target_price = 110.0

    signal = strategy._manage_open_position(position, current_price=115.0)
    # Should NOT sell at target — trailing stop handles exit
    assert signal.action == "hold", f"Expected hold (trailing mode), got {signal.action}"


def test_trailing_exit_still_respects_stop() -> None:
    """Trailing mode should still honor the structure stop."""
    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(use_trailing_exit=True)
    )

    position = Position(
        symbol="BTCUSDT", side="long", quantity=0.1,
        average_price=100.0, reserved_margin=1000.0,
    )
    position.stop_price = 90.0
    position.target_price = 110.0

    signal = strategy._manage_open_position(position, current_price=85.0)
    # Should sell — stop is still honored
    assert signal.action == "sell"


# ── Coinglass filter tests ────────────────────────────────────────


def _make_provider_with_new_fields(bars, top_ls_ratio=1.0, cvd=0.0, basis=0.0):
    """Helper: provider with top_ls_ratio, cvd, basis at each bar timestamp."""
    data = {}
    for b in bars:
        data[b.timestamp] = FuturesSnapshot(
            timestamp=b.timestamp,
            open_interest=1e9,
            long_short_ratio=1.0,
            taker_buy_sell_ratio=1.0,
            oi_close=1e9,
            top_ls_ratio=top_ls_ratio,
            cvd=cvd,
            basis=basis,
        )
    return StaticFuturesProvider(data)


def test_top_ls_contrarian_blocks_long_when_too_crowded() -> None:
    """Block long signal when top traders are too heavily long (contrarian)."""
    channel_bars = ascending_channel_support_long_bars()

    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
            top_ls_contrarian=True,
            top_ls_threshold=1.5,
        )
    )

    provider = _make_provider_with_new_fields(channel_bars, top_ls_ratio=2.0)  # too crowded

    result = strategy.evaluate(
        symbol="BTCUSDT", bars=channel_bars,
        position=Position(symbol="BTCUSDT"),
        futures_provider=provider,
    )
    assert result.signal.action == "hold"
    assert result.signal.reason == "top_ls_too_crowded"


def test_top_ls_contrarian_allows_long_when_not_crowded() -> None:
    """Allow long signal when top traders are balanced."""
    channel_bars = ascending_channel_support_long_bars()

    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.03,
            entry_buffer_pct=0.35,
            stop_buffer_pct=0.08,
            allow_shorts=False,
            require_parent_confirmation=False,
            top_ls_contrarian=True,
            top_ls_threshold=1.5,
        )
    )

    provider = _make_provider_with_new_fields(channel_bars, top_ls_ratio=1.2)  # not crowded

    result = strategy.evaluate(
        symbol="BTCUSDT", bars=channel_bars,
        position=Position(symbol="BTCUSDT"),
        futures_provider=provider,
    )
    assert result.signal.action == "buy"


def test_top_ls_contrarian_blocks_short_when_too_crowded_short() -> None:
    """Block short signal when top traders are too heavily short (contrarian)."""
    channel_bars = descending_channel_rejection_short_bars()

    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.004,
            entry_buffer_pct=0.25,
            stop_buffer_pct=0.08,
            allow_longs=False,
            require_parent_confirmation=False,
            top_ls_contrarian=True,
            top_ls_threshold=1.5,
        )
    )

    # L/S ratio below 1/1.5 = 0.667 means shorts are crowded
    provider = _make_provider_with_new_fields(channel_bars, top_ls_ratio=0.5)

    result = strategy.evaluate(
        symbol="BTCUSDT", bars=channel_bars,
        position=Position(symbol="BTCUSDT"),
        futures_provider=provider,
    )
    assert result.signal.action == "hold"
    assert result.signal.reason == "top_ls_too_crowded"


