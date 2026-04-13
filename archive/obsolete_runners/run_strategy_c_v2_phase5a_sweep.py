"""Strategy C v2 Phase 5A — stop-loss × leverage × risk-sizing sweep.

Per the Phase 5A brief: add fixed stop-loss and leverage/risk overlay
research on top of promoted candidates. Identify the highest-return
version that still preserves survival and robust OOS behavior.

Candidates:
    A_both: 4h rsi_only_21 hold=12 both
    A_long: 4h rsi_only_21 hold=12 long-only
    C_long: 4h rsi_and_macd_14 hold=4 long-only
    D1 (shadow): 4h rsi_only_20 hold=11 both (Phase 4 highest-return neighbor)
    D2 (shadow): 4h rsi_only_28 hold=18 both (Phase 4 best-risk-adjusted neighbor)

Research grid (per candidate):
    stop_loss_pct  ∈ {0.015, 0.020, 0.025, 0.030}
    stop_trigger   ∈ {"wick" (CONTRACT_PRICE-like), "close" (MARK_PRICE-like)}
    risk_per_trade ∈ {0.010, 0.015, 0.020}
    effective_leverage ∈ {1.0, 2.0, 3.0}  (exploratory: 5.0)

    Plus a "baseline / no stop" row per candidate for reference.

Per cell we report the full metric set:
    agg_compounded_return, combined_max_dd, combined_profit_factor,
    total_oos_trades, avg_exposure_time, total_funding_pnl,
    total_cost_pnl, exit_stop_loss_frac, avg_stopped_loss,
    worst_trade_pnl, worst_adverse_move, liq_safety_{1,2,3,5}x.

Liquidation-safety convention:
    positive = safe at that leverage
    negative = would have been liquidated on the worst adverse move

Output:
    strategy_c_v2_phase5a_stop_loss_leverage.csv

Run:
    python run_strategy_c_v2_phase5a_sweep.py
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
    TimeframeData,
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

OUTPUT_CSV = Path("strategy_c_v2_phase5a_stop_loss_leverage.csv")

FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001

STOP_LOSS_PCTS = (0.015, 0.020, 0.025, 0.030)
STOP_TRIGGERS = ("wick", "close")
RISK_PER_TRADE = (0.010, 0.015, 0.020)
EFFECTIVE_LEVERAGES = (1.0, 2.0, 3.0, 5.0)  # 5x exploratory


# ── signal factories (reuse Phase 3/4 approach) ──────────────────────


_RSI_CACHE: dict[tuple[int, int], list[float | None]] = {}


def _get_rsi_override(features, period: int) -> list[float | None] | None:
    if period in (14, 30):
        return None
    key = (id(features), period)
    if key not in _RSI_CACHE:
        closes = [f.close for f in features]
        _RSI_CACHE[key] = rsi_series(closes, period)
    return _RSI_CACHE[key]


def make_rsi_only_fn(*, period: int, side: str = "both") -> Callable:
    def fn(features):
        override = _get_rsi_override(features, period)
        sigs = rsi_only_signals(features, rsi_period=period, rsi_override=override)
        return apply_side_filter(sigs, side=side)  # type: ignore[arg-type]
    return fn


def make_rsi_and_macd_fn(*, period: int, side: str = "both") -> Callable:
    def fn(features):
        override = _get_rsi_override(features, period)
        sigs = rsi_and_macd_signals(features, rsi_period=period, rsi_override=override)
        return apply_side_filter(sigs, side=side)  # type: ignore[arg-type]
    return fn


# ── candidate specs ──────────────────────────────────────────────────


CANDIDATES = [
    {
        "label": "A_both",
        "name": "rsi_only_21_h12_both",
        "period": 21,
        "hold": 12,
        "side": "both",
        "shadow": False,
        "fn": make_rsi_only_fn(period=21, side="both"),
    },
    {
        "label": "A_long",
        "name": "rsi_only_21_h12_long",
        "period": 21,
        "hold": 12,
        "side": "long",
        "shadow": False,
        "fn": make_rsi_only_fn(period=21, side="long"),
    },
    {
        "label": "C_long",
        "name": "rsi_and_macd_14_h4_long",
        "period": 14,
        "hold": 4,
        "side": "long",
        "shadow": False,
        "fn": make_rsi_and_macd_fn(period=14, side="long"),
    },
    {
        "label": "D1_shadow",
        "name": "rsi_only_20_h11_both",
        "period": 20,
        "hold": 11,
        "side": "both",
        "shadow": True,
        "fn": make_rsi_only_fn(period=20, side="both"),
    },
    {
        "label": "D2_shadow",
        "name": "rsi_only_28_h18_both",
        "period": 28,
        "hold": 18,
        "side": "both",
        "shadow": True,
        "fn": make_rsi_only_fn(period=28, side="both"),
    },
]


# ── sweep builders ──────────────────────────────────────────────────


def build_baseline_rows(tf: TimeframeData) -> list[dict]:
    """No-stop baseline per candidate for reference (uses Phase 4 config)."""
    rows = []
    print("\n[Baseline — no stop-loss, full equity]")
    for c in CANDIDATES:
        extras = {
            "label": c["label"],
            "shadow": c["shadow"],
            "stop_loss_pct": None,
            "stop_trigger": None,
            "risk_per_trade": None,
            "effective_leverage": 1.0,
            "position_frac": 1.0,
        }
        row = run_cell(
            name=c["name"],
            tf=tf,
            signal_fn=c["fn"],
            hold_bars=c["hold"],
            fee_per_side=FEE_PER_SIDE,
            slip_per_side=SLIP_PER_SIDE,
            extra_fields=extras,
        )
        rows.append(row)
        print(format_row(row))
    return rows


def build_sweep_rows(tf: TimeframeData) -> list[dict]:
    """Full stop × trigger × risk × leverage sweep per candidate."""
    rows = []
    for c in CANDIDATES:
        print(f"\n[{c['label']}]  {c['name']}  hold={c['hold']}")
        for sl in STOP_LOSS_PCTS:
            for trig in STOP_TRIGGERS:
                for risk in RISK_PER_TRADE:
                    for lev in EFFECTIVE_LEVERAGES:
                        # Compute effective position_frac for reporting
                        raw_frac = risk / sl
                        actual_frac = min(raw_frac, lev)
                        # Skip infeasible: if raw_frac > lev and we cap,
                        # the effective risk is < requested
                        # (still run but note in the label)
                        extras = {
                            "label": c["label"],
                            "shadow": c["shadow"],
                            "stop_loss_pct": sl,
                            "stop_trigger": trig,
                            "risk_per_trade": risk,
                            "effective_leverage": lev,
                            "raw_position_frac": raw_frac,
                            "position_frac": actual_frac,
                            "capped_by_leverage": raw_frac > lev,
                        }
                        row = run_cell(
                            name=c["name"],
                            tf=tf,
                            signal_fn=c["fn"],
                            hold_bars=c["hold"],
                            fee_per_side=FEE_PER_SIDE,
                            slip_per_side=SLIP_PER_SIDE,
                            stop_loss_pct=sl,
                            stop_trigger=trig,
                            risk_per_trade=risk,
                            effective_leverage=lev,
                            extra_fields=extras,
                        )
                        rows.append(row)
                        print(
                            f"  sl={sl * 100:>4.1f}% {trig:<5} "
                            f"r={risk * 100:>4.1f}% L={lev:>3.1f}  "
                            f"frac={actual_frac:>5.3f}  "
                            f"n={int(row['total_oos_trades']):>4d}  "
                            f"ret={row['agg_compounded_return'] * 100:>+7.2f}%  "
                            f"dd={row['combined_max_dd'] * 100:>5.2f}%  "
                            f"wt={row['worst_trade_pnl'] * 100:>+6.2f}%  "
                            f"stop%={row['exit_stop_loss_frac'] * 100:>5.1f}%  "
                            f"liq3x={row['liq_safety_3x'] * 100:>+6.2f}%"
                        )
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    keys: list[str] = []
    seen = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"\nWrote {path} ({len(rows)} rows)")


def main() -> None:
    print("=" * 78)
    print("Strategy C v2 Phase 5A — stop-loss × leverage × risk sweep")
    print(f"Cost: fee={FEE_PER_SIDE * 100:.3f}% slip={SLIP_PER_SIDE * 100:.3f}%"
          f"  (round-trip {2 * (FEE_PER_SIDE + SLIP_PER_SIDE) * 100:.3f}%)")
    print("=" * 78)

    funding_records = load_funding_csv(FUNDING_CSV)
    print(f"funding records: {len(funding_records)}")

    t0 = time.time()
    print("\nLoading 4h data...")
    tf4h = load_timeframe_data("4h", KLINES_4H, 4.0, funding_records)
    print(f"  4h bars: {len(tf4h.bars):,}  features: {len(tf4h.features):,}  "
          f"splits: {len(tf4h.splits)}  ({time.time() - t0:.1f}s)")

    baseline_rows = build_baseline_rows(tf4h)
    sweep_rows = build_sweep_rows(tf4h)
    all_rows = baseline_rows + sweep_rows
    write_csv(OUTPUT_CSV, all_rows)

    # Top cells by OOS return with survival (liq_safety_3x > 0)
    print(f"\n{'=' * 78}")
    print("TOP 15 — enough_trades, safe at 3x (liq_safety_3x > 0)")
    print("=" * 78)
    ranked = sorted(
        [
            r for r in all_rows
            if r["enough_trades"] and r.get("liq_safety_3x", 0) > 0
            and r.get("stop_loss_pct") is not None
        ],
        key=lambda r: r["agg_compounded_return"],
        reverse=True,
    )[:15]
    for r in ranked:
        print(
            f"  {r['label']:<10} sl={r['stop_loss_pct'] * 100:>4.1f}% "
            f"{r['stop_trigger']:<5} r={r['risk_per_trade'] * 100:>4.1f}% "
            f"L={r['effective_leverage']:>3.1f}  "
            f"ret={r['agg_compounded_return'] * 100:>+7.2f}%  "
            f"dd={r['combined_max_dd'] * 100:>5.2f}%  "
            f"n={int(r['total_oos_trades']):>4d}  "
            f"stop%={r['exit_stop_loss_frac'] * 100:>5.1f}%  "
            f"liq2x={r['liq_safety_2x'] * 100:>+5.2f}%  "
            f"liq3x={r['liq_safety_3x'] * 100:>+5.2f}%"
        )

    print(f"\n{'=' * 78}")
    print("TOP 15 — at 2x (the realistic near-term deployment target)")
    print("=" * 78)
    ranked_2x = sorted(
        [
            r for r in all_rows
            if r["enough_trades"] and r.get("effective_leverage") == 2.0
            and r.get("stop_loss_pct") is not None
        ],
        key=lambda r: r["agg_compounded_return"],
        reverse=True,
    )[:15]
    for r in ranked_2x:
        print(
            f"  {r['label']:<10} sl={r['stop_loss_pct'] * 100:>4.1f}% "
            f"{r['stop_trigger']:<5} r={r['risk_per_trade'] * 100:>4.1f}%  "
            f"ret={r['agg_compounded_return'] * 100:>+7.2f}%  "
            f"dd={r['combined_max_dd'] * 100:>5.2f}%  "
            f"pf={r['combined_profit_factor']:>5.2f}  "
            f"n={int(r['total_oos_trades']):>4d}  "
            f"wt={r['worst_trade_pnl'] * 100:>+6.2f}%  "
            f"liq2x={r['liq_safety_2x'] * 100:>+5.2f}%"
        )


if __name__ == "__main__":
    main()
