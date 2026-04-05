"""Comprehensive parameter sweep: scale-in, trailing stop, liq/taker filters, ADX/RSI tuning.

Run with: python -m research.param_sweep
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from adapters.futures_data import StaticFuturesProvider
from data.backfill import load_bars_from_csv
from execution.paper_broker import PaperBroker
from research.backtest import BacktestResult, run_backtest
from risk.limits import RiskLimits
from strategies.trend_breakout import TrendBreakoutConfig, TrendBreakoutStrategy


SYMBOL = "BTCUSDT"
DATA_DIR = Path("src/data")
INITIAL_CASH = 10_000.0
LEVERAGE = 3
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0005


@dataclass
class SweepConfig:
    label: str
    config: TrendBreakoutConfig
    limits: RiskLimits


def _base_config(**overrides) -> TrendBreakoutConfig:
    """Best known config as baseline, with overrides."""
    defaults = dict(
        impulse_lookback=12,
        structure_lookback=24,
        secondary_structure_lookback=48,
        pivot_window=2,
        min_pivot_highs=2,
        min_pivot_lows=2,
        impulse_threshold_pct=0.02,
        entry_buffer_pct=0.20,
        stop_buffer_pct=0.08,
        min_r_squared=0.0,
        min_stop_atr_multiplier=1.5,
        time_stop_bars=84,

        enable_ascending_channel_resistance_rejection=False,
        enable_descending_channel_breakout_long=False,
        enable_ascending_channel_breakdown_short=False,
        # Proven filters
        rsi_filter=True,
        rsi_period=3,
        adx_filter=True,
        adx_threshold=25.0,
        adx_mode="smart",
        oi_divergence_lookback=48,
        oi_divergence_threshold=-0.10,
    )
    defaults.update(overrides)
    return TrendBreakoutConfig(**defaults)


def _base_limits(**overrides) -> RiskLimits:
    defaults = dict(
        max_position_pct=0.90,
        risk_per_trade_pct=0.02,
        leverage=LEVERAGE,
        scale_in_max_adds=0,
        scale_in_position_pct=0.03,
    )
    defaults.update(overrides)
    return RiskLimits(**defaults)


def _run(config: TrendBreakoutConfig, limits: RiskLimits, bars, futures_provider) -> BacktestResult:
    broker = PaperBroker(
        initial_cash=INITIAL_CASH,
        fee_rate=FEE_RATE,
        slippage_rate=SLIPPAGE_RATE,
        leverage=LEVERAGE,
        margin_mode="isolated",
    )
    return run_backtest(
        bars=bars,
        symbol=SYMBOL,
        strategy=TrendBreakoutStrategy(config),
        broker=broker,
        limits=limits,
        futures_provider=futures_provider,
    )


def build_sweep_configs() -> list[SweepConfig]:
    """Build all parameter combinations to test."""
    configs: list[SweepConfig] = []

    # 0. Baseline: current best (RSI+ADX+OI div)
    configs.append(SweepConfig(
        label="Base (RSI+ADX+OI)",
        config=_base_config(),
        limits=_base_limits(),
    ))

    # ── Phase 1: Scale-in + Trailing Stop ──────────────────────────

    # 1a. Trailing stop only (no scale-in)
    for trail_atr in [2.5, 3.0, 3.5, 4.0]:
        configs.append(SweepConfig(
            label=f"Trail ATR={trail_atr}",
            config=_base_config(
                use_trailing_exit=True,
                trailing_stop_atr=trail_atr,
                time_stop_bars=168,  # longer for trend-following
            ),
            limits=_base_limits(),
        ))

    # 1b. Scale-in only (no trailing)
    for min_profit in [0.01, 0.02, 0.03]:
        for max_adds in [1, 2]:
            configs.append(SweepConfig(
                label=f"ScaleIn p={min_profit} a={max_adds}",
                config=_base_config(
                    scale_in_enabled=True,
                    scale_in_min_profit_pct=min_profit,
                ),
                limits=_base_limits(
                    scale_in_max_adds=max_adds,
                    scale_in_position_pct=0.30,
                ),
            ))

    # 1c. Scale-in + Trailing (the power combo)
    for trail_atr in [2.5, 3.0, 3.5]:
        for min_profit in [0.01, 0.02]:
            for max_adds in [1, 2]:
                configs.append(SweepConfig(
                    label=f"Trail={trail_atr}+SI p={min_profit} a={max_adds}",
                    config=_base_config(
                        use_trailing_exit=True,
                        trailing_stop_atr=trail_atr,
                        time_stop_bars=168,
                        scale_in_enabled=True,
                        scale_in_min_profit_pct=min_profit,
                    ),
                    limits=_base_limits(
                        scale_in_max_adds=max_adds,
                        scale_in_position_pct=0.30,
                    ),
                ))

    # ── Phase 3: ADX threshold + RSI period tuning ─────────────────

    for adx_th in [20, 25, 30]:
        for rsi_p in [2, 3]:
            if adx_th == 25 and rsi_p == 3:
                continue  # skip baseline duplicate
            configs.append(SweepConfig(
                label=f"ADX={adx_th} RSI({rsi_p})",
                config=_base_config(
                    adx_threshold=float(adx_th),
                    rsi_period=rsi_p,
                ),
                limits=_base_limits(),
            ))

    # ── Phase 3 + Phase 1 combo: best ADX/RSI + trailing + scale-in
    for adx_th in [20, 25]:
        for rsi_p in [2, 3]:
            configs.append(SweepConfig(
                label=f"ADX={adx_th} RSI({rsi_p}) Trail+SI",
                config=_base_config(
                    adx_threshold=float(adx_th),
                    rsi_period=rsi_p,
                    use_trailing_exit=True,
                    trailing_stop_atr=3.0,
                    time_stop_bars=168,
                    scale_in_enabled=True,
                    scale_in_min_profit_pct=0.02,
                ),
                limits=_base_limits(
                    scale_in_max_adds=2,
                    scale_in_position_pct=0.30,
                ),
            ))

    return configs


def main() -> None:
    # Load data
    csv_path = DATA_DIR / "btcusdt_4h_5year.csv"
    if not csv_path.exists():
        print(f"Data file not found: {csv_path}")
        sys.exit(1)

    bars = load_bars_from_csv(str(csv_path))
    print(f"Loaded {len(bars)} bars: {bars[0].timestamp} to {bars[-1].timestamp}")

    # Load Coinglass data
    futures_provider = None
    oi_csv = DATA_DIR / "coinglass_oi_1d.csv"
    funding_csv = DATA_DIR / "coinglass_funding_1d.csv"
    if oi_csv.exists():
        futures_provider = StaticFuturesProvider.from_coinglass_csvs(
            oi_csv=str(oi_csv),
            funding_csv=str(funding_csv) if funding_csv.exists() else None,
        )
        print(f"Coinglass daily data loaded")

    sweep_configs = build_sweep_configs()
    print(f"\nRunning {len(sweep_configs)} configurations with ${INITIAL_CASH:,.0f} initial, {LEVERAGE}x leverage, isolated\n")

    # Header
    print(f"{'Config':<40} {'Trades':>6} {'WR%':>6} {'Return':>10} {'$Final':>10} {'MaxDD':>8}")
    print("-" * 84)

    results: list[tuple[str, BacktestResult]] = []

    for sc in sweep_configs:
        result = _run(sc.config, sc.limits, bars, futures_provider)
        results.append((sc.label, result))
        final_equity = result.final_equity
        print(
            f"{sc.label:<40} {result.total_trades:>6} "
            f"{(sum(1 for t in result.trades if t.pnl > 0) / max(len(result.trades), 1) * 100):>5.1f}% "
            f"{result.total_return_pct:>+9.1f}% "
            f"${final_equity:>9,.0f} "
            f"{result.max_drawdown_pct:>7.1f}%"
        )

    # Summary: top 5
    print("\n" + "=" * 84)
    print("TOP 5 by Return:")
    sorted_results = sorted(results, key=lambda x: x[1].total_return_pct, reverse=True)
    for label, result in sorted_results[:5]:
        wr = sum(1 for t in result.trades if t.pnl > 0) / max(len(result.trades), 1) * 100
        print(
            f"  {label:<38} {result.total_trades:>3} trades, {wr:.1f}% WR, "
            f"{result.total_return_pct:+.1f}%, ${result.final_equity:,.0f}, DD {result.max_drawdown_pct:.1f}%"
        )

    # TOP 5 by risk-adjusted (return / maxDD)
    print("\nTOP 5 by Return/DD ratio:")
    sorted_risk = sorted(
        [(l, r) for l, r in results if r.max_drawdown_pct > 0],
        key=lambda x: x[1].total_return_pct / x[1].max_drawdown_pct,
        reverse=True,
    )
    for label, result in sorted_risk[:5]:
        ratio = result.total_return_pct / result.max_drawdown_pct
        wr = sum(1 for t in result.trades if t.pnl > 0) / max(len(result.trades), 1) * 100
        print(
            f"  {label:<38} Ratio={ratio:.2f}, {result.total_trades:>3} trades, "
            f"{result.total_return_pct:+.1f}%, DD {result.max_drawdown_pct:.1f}%"
        )


if __name__ == "__main__":
    main()
