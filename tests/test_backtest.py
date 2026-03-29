from adapters.binance_stub import BinanceStubAdapter
from execution.paper_broker import PaperBroker
from research.backtest import (
    build_baseline_strategy,
    build_default_strategy,
    compare_baseline_enhanced,
    run_backtest,
)
from risk.limits import RiskLimits
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
