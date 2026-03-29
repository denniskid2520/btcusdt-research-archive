from adapters.base import Position
from strategies.trend_breakout import TrendBreakoutConfig, TrendBreakoutStrategy
from tests.fixtures_synthetic_bars import (
    ascending_channel_breakout_long_bars,
    ascending_channel_support_long_bars,
    descending_channel_breakdown_short_bars,
    descending_channel_rejection_short_bars,
    rising_channel_continuation_short_bars,
    rising_channel_retest_short_bars,
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
        )
    )
    signal = strategy.generate_signal("BTCUSDT", rising_channel_continuation_short_bars(), Position(symbol="BTCUSDT"))
    assert signal.action == "short"
    assert signal.reason == "rising_channel_breakdown_continuation_short"
    assert signal.stop_price is not None
    assert signal.target_price is not None
