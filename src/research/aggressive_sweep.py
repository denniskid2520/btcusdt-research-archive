"""Aggressive sizing sweep: find the path to 200%+ return on $10k/3x leverage.

Key insight: risk_per_trade_pct=0.02 limits effective leverage to ~1.2x even with 3x.
Need higher risk per trade to utilize full leverage.

Run with: PYTHONPATH=src python -m research.aggressive_sweep
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from adapters.futures_data import StaticFuturesProvider
from data.backfill import load_bars_from_csv
from execution.paper_broker import PaperBroker
from research.backtest import BacktestResult, run_backtest
from risk.limits import RiskLimits
from strategies.trend_breakout import TrendBreakoutConfig, TrendBreakoutStrategy


# Suppress fill logs for cleaner output
logging.getLogger("research.backtest").setLevel(logging.WARNING)

SYMBOL = "BTCUSDT"
DATA_DIR = Path("src/data")
INITIAL_CASH = 10_000.0
LEVERAGE = 3


def _config(**overrides) -> TrendBreakoutConfig:
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


def _run(config, limits, bars, fp) -> BacktestResult:
    broker = PaperBroker(
        initial_cash=INITIAL_CASH,
        fee_rate=0.001,
        slippage_rate=0.0005,
        leverage=LEVERAGE,
        margin_mode="isolated",
    )
    return run_backtest(
        bars=bars, symbol=SYMBOL,
        strategy=TrendBreakoutStrategy(config),
        broker=broker, limits=limits,
        futures_provider=fp,
    )


def main() -> None:
    bars = load_bars_from_csv(str(DATA_DIR / "btcusdt_4h_5year.csv"))
    fp = StaticFuturesProvider.from_coinglass_csvs(
        oi_csv=str(DATA_DIR / "coinglass_oi_1d.csv"),
        funding_csv=str(DATA_DIR / "coinglass_funding_1d.csv"),
    )

    print(f"Bars: {len(bars)}, {bars[0].timestamp} to {bars[-1].timestamp}")
    print(f"Initial: ${INITIAL_CASH:,.0f}, {LEVERAGE}x leverage, isolated\n")

    configs = []

    # ── Section 1: Position sizing sweep ──────────────────────────
    # Current: risk_per_trade=0.02, max_position=0.90
    # With 5% stop distance: notional = risk_amount / 0.05
    # risk=0.02 → notional=$4k (1.2x eff leverage)
    # risk=0.05 → $10k (3x eff)
    # risk=0.10 → $20k (limited by max_position cap to $27k)
    # risk=0.15 → capped at $27k

    for risk_pct in [0.02, 0.05, 0.08, 0.10, 0.15]:
        configs.append((
            f"Risk={risk_pct:.0%} Fixed",
            _config(),
            RiskLimits(max_position_pct=0.90, risk_per_trade_pct=risk_pct, leverage=LEVERAGE),
        ))

    # ── Section 2: Risk sizing + Trailing stop ────────────────────
    for risk_pct in [0.05, 0.08, 0.10, 0.15]:
        for trail in [3.0, 3.5, 4.0]:
            configs.append((
                f"Risk={risk_pct:.0%} Trail={trail}",
                _config(
                    use_trailing_exit=True,
                    trailing_stop_atr=trail,
                    time_stop_bars=168,
                ),
                RiskLimits(max_position_pct=0.90, risk_per_trade_pct=risk_pct, leverage=LEVERAGE),
            ))

    # ── Section 3: Full aggressive + scale-in ─────────────────────
    for risk_pct in [0.08, 0.10, 0.15]:
        for trail in [3.0, 3.5, 4.0]:
            configs.append((
                f"Risk={risk_pct:.0%} Trail={trail} SI",
                _config(
                    use_trailing_exit=True,
                    trailing_stop_atr=trail,
                    time_stop_bars=168,
                    scale_in_enabled=True,
                    scale_in_min_profit_pct=0.02,
                ),
                RiskLimits(
                    max_position_pct=0.90,
                    risk_per_trade_pct=risk_pct,
                    leverage=LEVERAGE,
                    scale_in_max_adds=2,
                    scale_in_position_pct=0.30,
                ),
            ))

    # ── Section 4: ADX=30 combos (best risk-adj) ─────────────────
    for risk_pct in [0.08, 0.10, 0.15]:
        configs.append((
            f"ADX30 Risk={risk_pct:.0%} Trail=4",
            _config(
                adx_threshold=30.0,
                use_trailing_exit=True,
                trailing_stop_atr=4.0,
                time_stop_bars=168,
            ),
            RiskLimits(max_position_pct=0.90, risk_per_trade_pct=risk_pct, leverage=LEVERAGE),
        ))

    # ── Section 5: No OI div (check if it's hurting with daily tolerance) ───
    for risk_pct in [0.05, 0.10, 0.15]:
        configs.append((
            f"NoOI Risk={risk_pct:.0%} Trail=4",
            _config(
                oi_divergence_lookback=0,  # disable OI
                use_trailing_exit=True,
                trailing_stop_atr=4.0,
                time_stop_bars=168,
            ),
            RiskLimits(max_position_pct=0.90, risk_per_trade_pct=risk_pct, leverage=LEVERAGE),
        ))

    # ── Section 6: Ultra-aggressive: wider entry zone + more trades ───
    for risk_pct in [0.10, 0.15]:
        configs.append((
            f"Wide Risk={risk_pct:.0%} Trail=4",
            _config(
                entry_buffer_pct=0.35,  # wider entry zone
                impulse_threshold_pct=0.01,  # lower impulse bar
                use_trailing_exit=True,
                trailing_stop_atr=4.0,
                time_stop_bars=168,
                oi_divergence_lookback=0,  # no OI
            ),
            RiskLimits(max_position_pct=0.90, risk_per_trade_pct=risk_pct, leverage=LEVERAGE),
        ))

    # ── Section 7: No filters at all (pure channel + trailing) ───────
    for risk_pct in [0.10, 0.15]:
        configs.append((
            f"NoFilter Risk={risk_pct:.0%} Trail=4",
            _config(
                rsi_filter=False,
                adx_filter=False,
                oi_divergence_lookback=0,
                use_trailing_exit=True,
                trailing_stop_atr=4.0,
                time_stop_bars=168,
            ),
            RiskLimits(max_position_pct=0.90, risk_per_trade_pct=risk_pct, leverage=LEVERAGE),
        ))

    # ── Section 8: Compounding test with no trailing stop ──────────
    for risk_pct in [0.10, 0.15]:
        configs.append((
            f"NoTrail Risk={risk_pct:.0%}",
            _config(),
            RiskLimits(max_position_pct=0.90, risk_per_trade_pct=risk_pct, leverage=LEVERAGE),
        ))

    print(f"Running {len(configs)} configs...\n")
    print(f"{'Config':<35} {'Trades':>6} {'WR%':>6} {'Return':>10} {'$Final':>10} {'MaxDD':>8} {'$/DD':>8}")
    print("-" * 90)

    results = []
    for label, cfg, lim in configs:
        r = _run(cfg, lim, bars, fp)
        wr = sum(1 for t in r.trades if t.pnl > 0) / max(len(r.trades), 1) * 100
        ratio = r.total_return_pct / r.max_drawdown_pct if r.max_drawdown_pct > 0 else 0
        results.append((label, r, ratio))
        print(
            f"{label:<35} {r.total_trades:>6} {wr:>5.1f}% "
            f"{r.total_return_pct:>+9.1f}% ${r.final_equity:>9,.0f} "
            f"{r.max_drawdown_pct:>7.1f}% {ratio:>7.2f}"
        )

    # Top 10 by return
    print("\n" + "=" * 90)
    print("TOP 10 by Return:")
    for label, r, ratio in sorted(results, key=lambda x: x[1].total_return_pct, reverse=True)[:10]:
        wr = sum(1 for t in r.trades if t.pnl > 0) / max(len(r.trades), 1) * 100
        avg_win = sum(t.pnl for t in r.trades if t.pnl > 0) / max(sum(1 for t in r.trades if t.pnl > 0), 1)
        avg_loss = sum(t.pnl for t in r.trades if t.pnl < 0) / max(sum(1 for t in r.trades if t.pnl < 0), 1)
        print(
            f"  {label:<33} {r.total_trades:>3}T, {wr:.0f}%WR, "
            f"{r.total_return_pct:+.1f}%, ${r.final_equity:,.0f}, "
            f"DD={r.max_drawdown_pct:.1f}%, "
            f"avgW=${avg_win:,.0f} avgL=${avg_loss:,.0f}"
        )

    # Top 5 by ratio
    print("\nTOP 5 Risk-Adjusted (Return/DD):")
    for label, r, ratio in sorted(results, key=lambda x: x[2], reverse=True)[:5]:
        wr = sum(1 for t in r.trades if t.pnl > 0) / max(len(r.trades), 1) * 100
        print(
            f"  {label:<33} Ratio={ratio:.2f}, {r.total_trades:>3}T, "
            f"{r.total_return_pct:+.1f}%, DD={r.max_drawdown_pct:.1f}%"
        )


if __name__ == "__main__":
    main()
