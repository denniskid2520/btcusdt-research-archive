"""Multi-timeframe sweep: 4h structure + 1h entry + 15m stop.

Tests the impact of adding 1h entry confirmation and 15m stop refinement
on top of the best known 4h-only config.

Run with: PYTHONPATH=src python -m research.mtf_sweep
"""

from __future__ import annotations

import logging
from pathlib import Path

from adapters.futures_data import StaticFuturesProvider
from data.backfill import load_bars_from_csv
from data.mtf_bars import MultiTimeframeBars
from execution.paper_broker import PaperBroker
from research.backtest import BacktestResult, run_backtest
from risk.limits import RiskLimits
from strategies.trend_breakout import TrendBreakoutConfig, TrendBreakoutStrategy

logging.getLogger("research.backtest").setLevel(logging.WARNING)

SYMBOL = "BTCUSDT"
DATA_DIR = Path("src/data")
INITIAL_CASH = 10_000.0
LEVERAGE = 3


def _best_config(**overrides) -> TrendBreakoutConfig:
    """Best known 4h config as baseline."""
    defaults = dict(
        impulse_lookback=12,
        structure_lookback=24,
        secondary_structure_lookback=48,
        pivot_window=2,
        min_pivot_highs=2,
        min_pivot_lows=2,
        impulse_threshold_pct=0.02,
        entry_buffer_pct=0.30,
        stop_buffer_pct=0.08,
        min_r_squared=0.0,
        min_stop_atr_multiplier=1.5,
        time_stop_bars=168,
        enable_ascending_channel_resistance_rejection=True,
        enable_descending_channel_breakout_long=True,
        enable_ascending_channel_breakdown_short=True,
        rsi_filter=True,
        rsi_period=3,
        adx_filter=True,
        adx_threshold=25.0,
        adx_mode="smart",
        oi_divergence_lookback=48,
        oi_divergence_threshold=-0.10,
        use_trailing_exit=True,
        trailing_stop_atr=3.5,
        top_ls_contrarian=True,
        top_ls_threshold=1.5,
    )
    defaults.update(overrides)
    return TrendBreakoutConfig(**defaults)


def _run(config, bars, fp, mtf=None) -> BacktestResult:
    broker = PaperBroker(
        initial_cash=INITIAL_CASH,
        fee_rate=0.001,
        slippage_rate=0.0005,
        leverage=LEVERAGE,
        margin_mode="isolated",
    )
    limits = RiskLimits(max_position_pct=0.90, risk_per_trade_pct=0.05, leverage=LEVERAGE)
    return run_backtest(
        bars=bars, symbol=SYMBOL,
        strategy=TrendBreakoutStrategy(config),
        broker=broker, limits=limits,
        futures_provider=fp,
        mtf_bars=mtf,
    )


def main() -> None:
    bars_4h = load_bars_from_csv(str(DATA_DIR / "btcusdt_4h_5year.csv"))

    # Load 1h and 15m if available
    bars_1h_path = DATA_DIR / "btcusdt_1h_5year.csv"
    bars_15m_path = DATA_DIR / "btcusdt_15m_5year.csv"

    mtf_data = {"4h": bars_4h}
    if bars_1h_path.exists():
        bars_1h = load_bars_from_csv(str(bars_1h_path))
        mtf_data["1h"] = bars_1h
        print(f"1h bars: {len(bars_1h)}")
    else:
        print("WARNING: 1h data not found, skipping 1h entry confirmation tests")

    if bars_15m_path.exists():
        bars_15m = load_bars_from_csv(str(bars_15m_path))
        mtf_data["15m"] = bars_15m
        print(f"15m bars: {len(bars_15m)}")
    else:
        print("WARNING: 15m data not found, skipping 15m stop refinement tests")

    mtf = MultiTimeframeBars(mtf_data)

    fp = StaticFuturesProvider.from_coinglass_csvs(
        oi_csv=str(DATA_DIR / "coinglass_oi_1d.csv"),
        funding_csv=str(DATA_DIR / "coinglass_funding_1d.csv"),
        top_ls_csv=str(DATA_DIR / "coinglass_top_ls_1d.csv"),
    )

    print(f"4h bars: {len(bars_4h)}, {bars_4h[0].timestamp} to {bars_4h[-1].timestamp}")
    print(f"Initial: ${INITIAL_CASH:,.0f}, {LEVERAGE}x leverage, isolated\n")

    configs = []

    # 0. Baseline (4h only, no MTF)
    configs.append(("Baseline (4h only)", _best_config(), None))

    # 1. Best 15m-only (proven best from previous sweep)
    if "15m" in mtf_data:
        configs.append(("15m t=0.30 only", _best_config(
            mtf_stop_refinement=True,
            mtf_15m_lookback=16,
            mtf_stop_max_tighten_pct=0.30,
        ), mtf))

    # ── 1h Scale Mode (confidence sizing, NOT blocking) ──────────
    if "1h" in mtf_data:
        for wick, conf in [(0.3, 0.5), (0.3, 0.6), (0.3, 0.7), (0.4, 0.5), (0.4, 0.6)]:
            configs.append((
                f"1h scale w={wick} c={conf}",
                _best_config(
                    mtf_entry_confirmation=True,
                    mtf_1h_sizing_mode="scale",
                    mtf_1h_lookback=4,
                    mtf_1h_min_wick_ratio=wick,
                    mtf_1h_no_confirm_confidence=conf,
                ),
                mtf,
            ))

    # ── 3-TF Combined: 1h Scale + 15m Stop ──────────────────────
    if "1h" in mtf_data and "15m" in mtf_data:
        for conf in [0.6, 0.7, 0.75, 0.8, 0.85, 0.9]:
            configs.append((
                f"3TF c={conf}",
                _best_config(
                    mtf_entry_confirmation=True,
                    mtf_1h_sizing_mode="scale",
                    mtf_1h_lookback=4,
                    mtf_1h_min_wick_ratio=0.3,
                    mtf_1h_no_confirm_confidence=conf,
                    mtf_stop_refinement=True,
                    mtf_15m_lookback=16,
                    mtf_stop_max_tighten_pct=0.30,
                ),
                mtf,
            ))

    print(f"Running {len(configs)} configs...\n")
    print(f"{'Config':<32} {'Trades':>6} {'WR%':>6} {'Return':>10} {'$Final':>10} {'MaxDD':>8} {'Ret/DD':>8}")
    print("-" * 87)

    results = []
    for label, cfg, mtf_arg in configs:
        r = _run(cfg, bars_4h, fp, mtf_arg)
        wr = sum(1 for t in r.trades if t.pnl > 0) / max(len(r.trades), 1) * 100
        ratio = r.total_return_pct / r.max_drawdown_pct if r.max_drawdown_pct > 0 else 0
        results.append((label, r, ratio))
        print(
            f"{label:<32} {r.total_trades:>6} {wr:>5.1f}% "
            f"{r.total_return_pct:>+9.1f}% ${r.final_equity:>9,.0f} "
            f"{r.max_drawdown_pct:>7.1f}% {ratio:>7.2f}"
        )

    print("\n" + "=" * 85)
    print("TOP 5 by Return:")
    for label, r, ratio in sorted(results, key=lambda x: x[1].total_return_pct, reverse=True)[:5]:
        wr = sum(1 for t in r.trades if t.pnl > 0) / max(len(r.trades), 1) * 100
        print(f"  {label:<28} {r.total_trades:>3}T, {wr:.0f}%WR, {r.total_return_pct:+.1f}%, DD={r.max_drawdown_pct:.1f}%")

    print("\nTOP 5 Risk-Adjusted (Ret/DD):")
    for label, r, ratio in sorted(results, key=lambda x: x[2], reverse=True)[:5]:
        print(f"  {label:<28} Ratio={ratio:.2f}, {r.total_trades:>3}T, {r.total_return_pct:+.1f}%")


if __name__ == "__main__":
    main()
