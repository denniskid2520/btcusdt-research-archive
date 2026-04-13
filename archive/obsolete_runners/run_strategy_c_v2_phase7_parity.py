"""Strategy C v2 Phase 7 — stop-semantics parity study.

For D1_long and C_long (the deployment set), run the full 5-year
walk-forward under BOTH stop semantics and compare:

    strategy_close_stop     — stop evaluated at bar close, fill at
                              next-bar open
    exchange_intrabar_stop  — stop evaluated intrabar (wick), fill at
                              the stop level (resting order semantics)

Compare on: trade count, stop count, PnL, drawdown, realized slippage.

The parity study uses 5-year walk-forward data. The 30-day retrospective
simulation is a separate runner (run_strategy_c_v2_phase7_retrospective.py).

Output:
    strategy_c_v2_phase7_stop_semantics_parity.csv
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, "src")

from data.strategy_c_v2_features import rsi_series
from research.strategy_c_v2_runner import (
    format_row,
    load_funding_csv,
    load_timeframe_data,
    run_cell,
)
from strategies.strategy_c_v2_filters import apply_side_filter
from strategies.strategy_c_v2_literature import (
    rsi_and_macd_signals,
    rsi_only_signals,
)


KLINES_4H = "src/data/btcusdt_4h_6year.csv"
FUNDING_CSV = "src/data/btcusdt_funding_5year.csv"
OUTPUT_CSV = Path("strategy_c_v2_phase7_stop_semantics_parity.csv")

FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001


_RSI_CACHE: dict[tuple[int, int], list[float | None]] = {}


def _get_rsi_override(features, period: int) -> list[float | None] | None:
    if period in (14, 30):
        return None
    key = (id(features), period)
    if key not in _RSI_CACHE:
        closes = [f.close for f in features]
        _RSI_CACHE[key] = rsi_series(closes, period)
    return _RSI_CACHE[key]


def make_D1_long(features):
    override = _get_rsi_override(features, 20)
    sigs = rsi_only_signals(features, rsi_period=20, rsi_override=override)
    return apply_side_filter(sigs, side="long")


def make_C_long(features):
    sigs = rsi_and_macd_signals(features, rsi_period=14)
    return apply_side_filter(sigs, side="long")


def make_D1_long_frac2(features):
    override = _get_rsi_override(features, 20)
    sigs = rsi_only_signals(features, rsi_period=20, rsi_override=override)
    return apply_side_filter(sigs, side="long")


CELLS = [
    {
        "label": "D1_long_primary",
        "name": "rsi_only_20_h11_long_primary",
        "fn": make_D1_long,
        "hold": 11,
        "stop_loss_pct": 0.015,
        "risk_per_trade": 0.02,
        "effective_leverage": 2.0,
        "actual_frac": 1.333,
    },
    {
        "label": "C_long_backup",
        "name": "rsi_and_macd_14_h4_long_backup",
        "fn": make_C_long,
        "hold": 4,
        "stop_loss_pct": 0.02,
        "risk_per_trade": 0.02,
        "effective_leverage": 2.0,
        "actual_frac": 1.0,
    },
    {
        "label": "D1_long_frac2_shadow",
        "name": "rsi_only_20_h11_long_frac2_shadow",
        "fn": make_D1_long_frac2,
        "hold": 11,
        "stop_loss_pct": 0.0125,
        "risk_per_trade": 0.025,
        "effective_leverage": 2.0,
        "actual_frac": 2.0,
    },
]


def main() -> None:
    print("=" * 78)
    print("Strategy C v2 Phase 7 — stop-semantics parity study")
    print("=" * 78)

    funding_records = load_funding_csv(FUNDING_CSV)
    t0 = time.time()
    print("\nLoading 4h data...")
    tf = load_timeframe_data("4h", KLINES_4H, 4.0, funding_records)
    print(f"  bars: {len(tf.bars):,}  splits: {len(tf.splits)}  ({time.time() - t0:.1f}s)")

    rows: list[dict] = []
    for cell in CELLS:
        print(f"\n[{cell['label']}]  hold={cell['hold']}  sl={cell['stop_loss_pct'] * 100:.2f}% "
              f"r={cell['risk_per_trade'] * 100:.1f}%  L={cell['effective_leverage']:.1f} "
              f"frac={cell['actual_frac']:.3f}")

        for semantics in ("strategy_close_stop", "exchange_intrabar_stop"):
            extras = {
                "label": cell["label"],
                "stop_semantics": semantics,
                "stop_loss_pct": cell["stop_loss_pct"],
                "risk_per_trade": cell["risk_per_trade"],
                "effective_leverage": cell["effective_leverage"],
                "actual_frac": cell["actual_frac"],
            }
            row = run_cell(
                name=cell["name"],
                tf=tf,
                signal_fn=cell["fn"],
                hold_bars=cell["hold"],
                fee_per_side=FEE_PER_SIDE,
                slip_per_side=SLIP_PER_SIDE,
                stop_loss_pct=cell["stop_loss_pct"],
                stop_semantics=semantics,
                risk_per_trade=cell["risk_per_trade"],
                effective_leverage=cell["effective_leverage"],
                extra_fields=extras,
            )
            rows.append(row)
            print(
                f"  {semantics:<24}  "
                f"ret={row['agg_compounded_return'] * 100:>+7.2f}%  "
                f"dd={row['combined_max_dd'] * 100:>5.2f}%  "
                f"pf={row['combined_profit_factor']:>5.2f}  "
                f"n={int(row['total_oos_trades']):>4d}  "
                f"stop%={row['exit_stop_loss_frac'] * 100:>5.1f}%  "
                f"wt={row['worst_trade_pnl'] * 100:>+6.2f}%"
            )

    # Compute deltas per cell
    print(f"\n{'=' * 78}\nDELTA TABLE — intrabar minus close_stop\n{'=' * 78}")
    print(f"{'cell':<24} {'Δret':>8} {'Δdd':>8} {'Δn':>6} {'Δstops':>8} {'Δwt':>8}")
    for cell in CELLS:
        close_r = next(r for r in rows if r["label"] == cell["label"] and r["stop_semantics"] == "strategy_close_stop")
        intra_r = next(r for r in rows if r["label"] == cell["label"] and r["stop_semantics"] == "exchange_intrabar_stop")
        d_ret = (intra_r["agg_compounded_return"] - close_r["agg_compounded_return"]) * 100
        d_dd = (intra_r["combined_max_dd"] - close_r["combined_max_dd"]) * 100
        d_n = int(intra_r["total_oos_trades"] - close_r["total_oos_trades"])
        d_stops = (intra_r["exit_stop_loss_frac"] - close_r["exit_stop_loss_frac"]) * 100
        d_wt = (intra_r["worst_trade_pnl"] - close_r["worst_trade_pnl"]) * 100
        print(
            f"{cell['label']:<24} "
            f"{d_ret:>+7.2f}% {d_dd:>+7.2f}% {d_n:>+6d} {d_stops:>+7.2f}% {d_wt:>+7.2f}%"
        )

    # Write CSV
    keys: list[str] = []
    seen = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with OUTPUT_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nWrote {OUTPUT_CSV} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
