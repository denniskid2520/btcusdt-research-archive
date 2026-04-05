"""Sweep: Top L/S contrarian, CVD divergence, Basis extreme filters.

Tests new Coinglass data filters against the best known 4h config.
Run with: PYTHONPATH=src python -m research.new_filter_sweep
"""

from __future__ import annotations

import logging
from pathlib import Path

from adapters.futures_data import StaticFuturesProvider
from data.backfill import load_bars_from_csv
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
    )
    defaults.update(overrides)
    return TrendBreakoutConfig(**defaults)


def _run(config, bars, fp) -> BacktestResult:
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
    )


def main() -> None:
    bars = load_bars_from_csv(str(DATA_DIR / "btcusdt_4h_5year.csv"))

    # Load all daily Coinglass data (including new types)
    fp = StaticFuturesProvider.from_coinglass_csvs(
        oi_csv=str(DATA_DIR / "coinglass_oi_1d.csv"),
        funding_csv=str(DATA_DIR / "coinglass_funding_1d.csv"),
        top_ls_csv=str(DATA_DIR / "coinglass_top_ls_1d.csv"),
        cvd_csv=str(DATA_DIR / "coinglass_cvd_1d.csv"),
        basis_csv=str(DATA_DIR / "coinglass_basis_1d.csv"),
    )

    print(f"Bars: {len(bars)}, {bars[0].timestamp} to {bars[-1].timestamp}")
    print(f"Initial: ${INITIAL_CASH:,.0f}, {LEVERAGE}x leverage, isolated\n")

    configs = []

    # 0. Baseline (best known config, no new filters)
    configs.append(("Baseline (best 4h)", _best_config()))

    # ── Top L/S Contrarian ────────────────────────────────────────
    for threshold in [1.3, 1.5, 1.8, 2.0]:
        configs.append((
            f"TopLS th={threshold}",
            _best_config(top_ls_contrarian=True, top_ls_threshold=threshold),
        ))

    # ── CVD Divergence ────────────────────────────────────────────
    for lookback in [6, 12, 24, 48]:
        configs.append((
            f"CVD lb={lookback}",
            _best_config(cvd_divergence_filter=True, cvd_divergence_lookback=lookback),
        ))

    # ── Basis Extreme ─────────────────────────────────────────────
    for threshold in [0.05, 0.08, 0.10, 0.15]:
        configs.append((
            f"Basis th={threshold}",
            _best_config(basis_extreme_filter=True, basis_extreme_threshold=threshold),
        ))

    # ── Combos: best of each ──────────────────────────────────────
    for ls_th in [1.5, 2.0]:
        for cvd_lb in [12, 24]:
            configs.append((
                f"TopLS={ls_th}+CVD={cvd_lb}",
                _best_config(
                    top_ls_contrarian=True, top_ls_threshold=ls_th,
                    cvd_divergence_filter=True, cvd_divergence_lookback=cvd_lb,
                ),
            ))

    for ls_th in [1.5, 2.0]:
        configs.append((
            f"TopLS={ls_th}+Basis=0.10",
            _best_config(
                top_ls_contrarian=True, top_ls_threshold=ls_th,
                basis_extreme_filter=True, basis_extreme_threshold=0.10,
            ),
        ))

    # All three combined
    configs.append((
        "All3: LS=1.5 CVD=12 B=0.10",
        _best_config(
            top_ls_contrarian=True, top_ls_threshold=1.5,
            cvd_divergence_filter=True, cvd_divergence_lookback=12,
            basis_extreme_filter=True, basis_extreme_threshold=0.10,
        ),
    ))
    configs.append((
        "All3: LS=2.0 CVD=24 B=0.10",
        _best_config(
            top_ls_contrarian=True, top_ls_threshold=2.0,
            cvd_divergence_filter=True, cvd_divergence_lookback=24,
            basis_extreme_filter=True, basis_extreme_threshold=0.10,
        ),
    ))

    print(f"Running {len(configs)} configs...\n")
    print(f"{'Config':<35} {'Trades':>6} {'WR%':>6} {'Return':>10} {'$Final':>10} {'MaxDD':>8} {'Ret/DD':>8}")
    print("-" * 90)

    results = []
    for label, cfg in configs:
        r = _run(cfg, bars, fp)
        wr = sum(1 for t in r.trades if t.pnl > 0) / max(len(r.trades), 1) * 100
        ratio = r.total_return_pct / r.max_drawdown_pct if r.max_drawdown_pct > 0 else 0
        results.append((label, r, ratio))
        print(
            f"{label:<35} {r.total_trades:>6} {wr:>5.1f}% "
            f"{r.total_return_pct:>+9.1f}% ${r.final_equity:>9,.0f} "
            f"{r.max_drawdown_pct:>7.1f}% {ratio:>7.2f}"
        )

    # Top 5 by return
    print("\n" + "=" * 90)
    print("TOP 5 by Return:")
    for label, r, ratio in sorted(results, key=lambda x: x[1].total_return_pct, reverse=True)[:5]:
        wr = sum(1 for t in r.trades if t.pnl > 0) / max(len(r.trades), 1) * 100
        print(
            f"  {label:<33} {r.total_trades:>3}T, {wr:.0f}%WR, "
            f"{r.total_return_pct:+.1f}%, ${r.final_equity:,.0f}, "
            f"DD={r.max_drawdown_pct:.1f}%, Ret/DD={ratio:.2f}"
        )

    # Top 5 by risk-adjusted
    print("\nTOP 5 Risk-Adjusted (Return/DD):")
    for label, r, ratio in sorted(results, key=lambda x: x[2], reverse=True)[:5]:
        wr = sum(1 for t in r.trades if t.pnl > 0) / max(len(r.trades), 1) * 100
        print(
            f"  {label:<33} Ratio={ratio:.2f}, {r.total_trades:>3}T, "
            f"{r.total_return_pct:+.1f}%, DD={r.max_drawdown_pct:.1f}%"
        )


if __name__ == "__main__":
    main()
