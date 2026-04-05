"""Phase 2 sweep: Liquidation cascade + Taker imbalance filters.

Uses 4h Coinglass data (Oct 2025 - Apr 2026, ~6 months overlap).
Runs on the overlapping portion only to test these filters fairly.

Run with: PYTHONPATH=src python -m research.liq_taker_sweep
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
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


def _base_config(**overrides) -> TrendBreakoutConfig:
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


def _run(config, bars, futures_provider) -> BacktestResult:
    broker = PaperBroker(
        initial_cash=INITIAL_CASH,
        fee_rate=0.001,
        slippage_rate=0.0005,
        leverage=LEVERAGE,
        margin_mode="isolated",
    )
    limits = RiskLimits(max_position_pct=0.90, risk_per_trade_pct=0.02, leverage=LEVERAGE)
    return run_backtest(
        bars=bars, symbol=SYMBOL,
        strategy=TrendBreakoutStrategy(config),
        broker=broker, limits=limits,
        futures_provider=futures_provider,
    )


def main() -> None:
    bars = load_bars_from_csv(str(DATA_DIR / "btcusdt_4h_5year.csv"))

    # Build 4h provider with all Coinglass CSVs (liq + taker only available at 4h)
    provider = StaticFuturesProvider.from_coinglass_csvs(
        oi_csv=str(DATA_DIR / "coinglass_oi_4h.csv"),
        funding_csv=str(DATA_DIR / "coinglass_funding_4h.csv"),
        liquidation_csv=str(DATA_DIR / "coinglass_liquidation_4h.csv"),
        taker_csv=str(DATA_DIR / "coinglass_taker_volume_4h.csv"),
    )

    # Also load daily OI data for the OI divergence filter (covers full range)
    daily_provider = StaticFuturesProvider.from_coinglass_csvs(
        oi_csv=str(DATA_DIR / "coinglass_oi_1d.csv"),
        funding_csv=str(DATA_DIR / "coinglass_funding_1d.csv"),
    )

    print(f"Bars: {len(bars)}, range: {bars[0].timestamp} to {bars[-1].timestamp}")
    print(f"Testing liq/taker filters (4h Coinglass data, ~6mo overlap)\n")

    configs = [
        ("Base (no liq/taker)", _base_config(), daily_provider),
        # Liquidation cascade filter
        ("Liq cascade 500K", _base_config(liq_cascade_filter=True, liq_cascade_min_usd=500_000), provider),
        ("Liq cascade 1M", _base_config(liq_cascade_filter=True, liq_cascade_min_usd=1_000_000), provider),
        ("Liq cascade 2M", _base_config(liq_cascade_filter=True, liq_cascade_min_usd=2_000_000), provider),
        ("Liq cascade 5M", _base_config(liq_cascade_filter=True, liq_cascade_min_usd=5_000_000), provider),
        # Taker imbalance filter
        ("Taker ratio 1.05", _base_config(taker_imbalance_filter=True, taker_imbalance_min_ratio=1.05), provider),
        ("Taker ratio 1.10", _base_config(taker_imbalance_filter=True, taker_imbalance_min_ratio=1.10), provider),
        ("Taker ratio 1.20", _base_config(taker_imbalance_filter=True, taker_imbalance_min_ratio=1.20), provider),
        # Combined
        ("Liq 1M + Taker 1.1", _base_config(
            liq_cascade_filter=True, liq_cascade_min_usd=1_000_000,
            taker_imbalance_filter=True, taker_imbalance_min_ratio=1.10,
        ), provider),
        ("Liq 2M + Taker 1.05", _base_config(
            liq_cascade_filter=True, liq_cascade_min_usd=2_000_000,
            taker_imbalance_filter=True, taker_imbalance_min_ratio=1.05,
        ), provider),
    ]

    print(f"{'Config':<30} {'Trades':>6} {'WR%':>6} {'Return':>10} {'$Final':>10} {'MaxDD':>8}")
    print("-" * 74)

    for label, config, prov in configs:
        result = _run(config, bars, prov)
        wr = sum(1 for t in result.trades if t.pnl > 0) / max(len(result.trades), 1) * 100
        print(
            f"{label:<30} {result.total_trades:>6} {wr:>5.1f}% "
            f"{result.total_return_pct:>+9.1f}% ${result.final_equity:>9,.0f} "
            f"{result.max_drawdown_pct:>7.1f}%"
        )


if __name__ == "__main__":
    main()
