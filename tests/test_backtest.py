from adapters.binance_stub import BinanceStubAdapter
from execution.paper_broker import PaperBroker
from research.backtest import (
    _cluster_event_markers,
    build_baseline_strategy,
    build_default_strategy,
    compare_baseline_enhanced,
    run_backtest,
)
from risk.limits import RiskLimits
from strategies.trend_breakout import TrendBreakoutConfig, TrendBreakoutStrategy
from strategies.trend_breakout import TrendBreakoutConfig, TrendBreakoutStrategy
from tests.fixtures_synthetic_bars import (
    realistic_comparison_dataset_bars,
    rising_channel_continuation_short_bars,
    rising_channel_retest_short_bars,
)


def test_backtest_runs_end_to_end_with_stub_data() -> None:
    bars = BinanceStubAdapter().fetch_ohlcv(symbol="BTCUSDT", timeframe="1h", limit=120)
    result = run_backtest(
        bars=bars,
        symbol="BTCUSDT",
        strategy=build_default_strategy(),
        broker=PaperBroker(initial_cash=100_000.0, fee_rate=0.001, slippage_rate=0.0005),
        limits=RiskLimits(),
    )

    assert result.initial_cash == 100_000.0
    assert result.final_equity > 0
    assert result.total_trades >= 0
    assert result.rule_eval_counts
    assert result.rejection_stats is not None


def test_backtest_trade_log_records_entry_rule_and_exit_reason() -> None:
    result = run_backtest(
        bars=rising_channel_retest_short_bars(),
        symbol="BTCUSDT",
        strategy=TrendBreakoutStrategy(
            TrendBreakoutConfig(
                impulse_lookback=12,
                structure_lookback=24,
                entry_buffer_pct=0.35,
                stop_buffer_pct=0.08,
                allow_longs=False,
                require_parent_confirmation=False,
            )
        ),
        broker=PaperBroker(initial_cash=100_000.0, fee_rate=0.0, slippage_rate=0.0),
        limits=RiskLimits(),
    )

    assert result.trades
    first_trade = result.trades[0]
    assert first_trade.entry_rule == "rising_channel_breakdown_retest_short"
    assert first_trade.exit_reason
    assert first_trade.entry_price > 0
    assert first_trade.exit_price > 0


def test_backtest_rule_stats_include_new_short_rules_on_synthetic_bars() -> None:
    retest_result = run_backtest(
        bars=rising_channel_retest_short_bars(),
        symbol="BTCUSDT",
        strategy=TrendBreakoutStrategy(
            TrendBreakoutConfig(
                impulse_lookback=12,
                structure_lookback=24,
                entry_buffer_pct=0.35,
                stop_buffer_pct=0.08,
                allow_longs=False,
                require_parent_confirmation=False,
            )
        ),
        broker=PaperBroker(initial_cash=100_000.0, fee_rate=0.0, slippage_rate=0.0),
        limits=RiskLimits(),
    )
    continuation_result = run_backtest(
        bars=rising_channel_continuation_short_bars(),
        symbol="BTCUSDT",
        strategy=TrendBreakoutStrategy(
            TrendBreakoutConfig(
                impulse_lookback=12,
                structure_lookback=24,
                entry_buffer_pct=0.25,
                continuation_buffer_pct=0.45,
                stop_buffer_pct=0.08,
                allow_longs=False,
                enable_rising_channel_breakdown_retest_short=False,
                require_parent_confirmation=False,
            )
        ),
        broker=PaperBroker(initial_cash=100_000.0, fee_rate=0.0, slippage_rate=0.0),
        limits=RiskLimits(),
    )

    retest_stat = next(stat for stat in retest_result.rule_stats if stat.signal_name == "rising_channel_breakdown_retest_short")
    continuation_stat = next(
        stat for stat in continuation_result.rule_stats if stat.signal_name == "rising_channel_breakdown_continuation_short"
    )
    assert retest_stat.trigger_count >= 1
    assert retest_stat.filled_entries >= 1
    assert continuation_stat.trigger_count >= 1
    assert continuation_stat.filled_entries >= 1


def test_backtest_rejection_funnel_has_reasons() -> None:
    bars = realistic_comparison_dataset_bars()
    result = run_backtest(
        bars=bars,
        symbol="BTCUSDT",
        strategy=build_default_strategy(),
        broker=PaperBroker(initial_cash=100_000.0, fee_rate=0.001, slippage_rate=0.0005),
        limits=RiskLimits(),
    )

    assert result.rule_eval_counts
    assert any(result.rule_eval_counts.values())
    flattened = [reason for reasons in result.rejection_stats.values() for reason in reasons]
    assert flattened


def test_backtest_rule_contribution_uses_total_realized_pnl_denominator() -> None:
    result = run_backtest(
        bars=rising_channel_retest_short_bars(),
        symbol="BTCUSDT",
        strategy=TrendBreakoutStrategy(
            TrendBreakoutConfig(
                impulse_lookback=12,
                structure_lookback=24,
                entry_buffer_pct=0.35,
                stop_buffer_pct=0.08,
                allow_longs=False,
                require_parent_confirmation=False,
            )
        ),
        broker=PaperBroker(initial_cash=100_000.0, fee_rate=0.0, slippage_rate=0.0),
        limits=RiskLimits(),
    )

    total_trade_pnl = sum(trade.pnl for trade in result.trades)
    total_contribution = sum(stat.contribution_pct for stat in result.rule_stats)
    if total_trade_pnl != 0:
        assert round(total_contribution, 6) == 100.0
    else:
        assert total_contribution == 0.0


def test_backtest_baseline_vs_enhanced_comparison_path_on_realistic_dataset() -> None:
    bars = realistic_comparison_dataset_bars()
    comparison_config = TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        pivot_window=2,
        min_pivot_highs=2,
        min_pivot_lows=2,
        impulse_threshold_pct=0.03,
        entry_buffer_pct=0.35,
        continuation_buffer_pct=0.45,
        stop_buffer_pct=0.08,
        allow_longs=False,
        require_parent_confirmation=False,
    )
    comparison = compare_baseline_enhanced(
        bars=bars,
        symbol="BTCUSDT",
        limits=RiskLimits(),
        config=comparison_config,
    )

    assert comparison.baseline.total_trades > 0
    assert comparison.enhanced.total_trades > 0
    assert comparison.enhanced.total_trades > comparison.baseline.total_trades

    baseline_rules = {stat.signal_name for stat in comparison.baseline.rule_stats}
    enhanced_rules = {stat.signal_name for stat in comparison.enhanced.rule_stats}
    assert "rising_channel_breakdown_retest_short" not in baseline_rules
    assert "rising_channel_breakdown_continuation_short" not in baseline_rules
    assert "rising_channel_breakdown_retest_short" in enhanced_rules
    assert "rising_channel_breakdown_continuation_short" in enhanced_rules
    rising_fills = [
        stat.filled_entries
        for stat in comparison.enhanced.rule_stats
        if stat.signal_name in {"rising_channel_breakdown_retest_short", "rising_channel_breakdown_continuation_short"}
    ]
    assert sum(rising_fills) > 0


def test_event_markers_are_clustered_at_event_level() -> None:
    markers = [
        {
            "timestamp": BinanceStubAdapter().fetch_ohlcv("BTCUSDT", "1h", 3)[0].timestamp,
            "rule_name": "rising_channel_breakdown_retest_short",
            "first_failed_condition": "parent_context_conflict",
            "parent_structure_type": "descending_channel",
            "parent_position_in_channel": "near_lower_boundary",
            "parent_event_type": "normal",
            "event_label": "major_descending_channel_lower_boundary_support_context",
        },
        {
            "timestamp": BinanceStubAdapter().fetch_ohlcv("BTCUSDT", "1h", 3)[1].timestamp,
            "rule_name": "rising_channel_breakdown_continuation_short",
            "first_failed_condition": "parent_context_conflict",
            "parent_structure_type": "descending_channel",
            "parent_position_in_channel": "near_lower_boundary",
            "parent_event_type": "normal",
            "event_label": "major_descending_channel_lower_boundary_support_context",
        },
        {
            "timestamp": BinanceStubAdapter().fetch_ohlcv("BTCUSDT", "1h", 3)[2].timestamp,
            "rule_name": "rising_channel_breakdown_retest_short",
            "first_failed_condition": "shock_override_active",
            "parent_structure_type": "ascending_channel",
            "parent_position_in_channel": "below_lower_boundary",
            "parent_event_type": "shock_break_reclaim",
            "event_label": "shock_break_reclaim_context",
        },
    ]
    clustered = _cluster_event_markers(markers)
    assert len(clustered) == 2
    assert clustered[0].bars == 2
    assert clustered[0].event_label == "major_descending_channel_lower_boundary_support_context"
    assert clustered[1].event_label == "shock_break_reclaim_context"


def test_build_default_strategy_includes_quality_filters() -> None:
    """Default strategy must include quality filters and tuned parameters."""
    strategy = build_default_strategy()
    config: TrendBreakoutConfig = strategy.config
    assert config.min_r_squared >= 0, "R² filter configurable"
    assert config.min_stop_atr_multiplier >= 1.0, "ATR stop floor should prevent noise stop-outs"
    assert config.impulse_threshold_pct <= 0.03, "Lower impulse threshold captures more setups"
    assert config.time_stop_bars is not None and config.time_stop_bars > 0, "Time stop cuts losing trades"
    assert config.secondary_structure_lookback is not None, "Dual lookback captures more regimes"


def test_risk_limits_use_futures_leverage() -> None:
    """Perpetual futures should use higher position size than spot."""
    limits = RiskLimits()
    assert limits.max_position_pct >= 0.5, "Futures should use at least 50% position sizing"
