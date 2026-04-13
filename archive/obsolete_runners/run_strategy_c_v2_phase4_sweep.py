"""Strategy C v2 Phase 4 — candidate consolidation + robustness band + ATR sweep.

Runs three combined sweeps in one pass:

1. **Candidate consolidation** — the three explicit Phase 4 candidates:
   - A: 4h rsi_only_21 hold=12 (side=both)
   - B: 4h rsi_only_30 hold=16 (side=both)
   - C: 4h rsi_and_macd_14 hold=4 long-only

2. **Robustness band** — small perturbations around each candidate:
   - RSI period ±1..2 steps
   - hold ±1..2 steps
   - long-only vs both
   - time-stop vs opposite-flip (allow_opposite_flip_exit toggle)

3. **ATR trailing stop sweep** — each candidate (and a few robustness
   neighbors) run with atr_14 trailing stops at k ∈ {1.5, 2.0, 2.5, 3.0}.

Data is loaded once for 4h and reused. Output is a single combined CSV
plus printed top-10 tables for each of the three sub-sweeps.
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


# ── config ───────────────────────────────────────────────────────────

KLINES_4H = "src/data/btcusdt_4h_6year.csv"
FUNDING_CSV = "src/data/btcusdt_funding_5year.csv"

CANDIDATES_CSV = Path("strategy_c_v2_phase4_candidates.csv")
ROBUSTNESS_CSV = Path("strategy_c_v2_phase4_robustness_band.csv")
ATR_CSV = Path("strategy_c_v2_phase4_atr_sweep.csv")

FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001


# ── signal factory with RSI override for arbitrary periods ───────────


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


# ── candidate definitions ───────────────────────────────────────────


CANDIDATES: list[dict] = [
    {
        "label": "A",
        "name": "rsi_only_21_both",
        "family": "rsi_only",
        "period": 21,
        "hold": 12,
        "side": "both",
    },
    {
        "label": "B",
        "name": "rsi_only_30_both",
        "family": "rsi_only",
        "period": 30,
        "hold": 16,
        "side": "both",
    },
    {
        "label": "C",
        "name": "rsi_and_macd_14_long",
        "family": "rsi_and_macd",
        "period": 14,
        "hold": 4,
        "side": "long",
    },
]


def make_fn_for_candidate(c: dict) -> Callable:
    if c["family"] == "rsi_only":
        return make_rsi_only_fn(period=c["period"], side=c["side"])
    else:
        return make_rsi_and_macd_fn(period=c["period"], side=c["side"])


# ── sweep builders ──────────────────────────────────────────────────


def build_candidate_cells() -> list[dict]:
    """The three headline candidates, no perturbation."""
    return [
        {
            "label": c["label"],
            "name": c["name"],
            "family": c["family"],
            "period": c["period"],
            "hold": c["hold"],
            "side": c["side"],
            "exit": "time_stop+opposite_flip",
            "fn": make_fn_for_candidate(c),
            "atr_field": None,
            "atr_k": None,
        }
        for c in CANDIDATES
    ]


def build_robustness_band() -> list[dict]:
    """Perturbations around each candidate: RSI period ±, hold ±, side, exit."""
    rows: list[dict] = []
    # Candidate A: rsi_only_21 h=12 both
    A_periods = (19, 20, 21, 22, 23)
    A_holds = (10, 11, 12, 13, 14)
    for p in A_periods:
        for h in A_holds:
            for side in ("both", "long"):
                rows.append({
                    "label": f"A_band_p{p}_h{h}_{side}",
                    "name": f"rsi_only_{p}_{side}",
                    "family": "rsi_only",
                    "period": p,
                    "hold": h,
                    "side": side,
                    "exit": "time_stop+opposite_flip",
                    "fn": make_rsi_only_fn(period=p, side=side),
                    "atr_field": None,
                    "atr_k": None,
                })
    # Candidate A: exit variation (time-stop only, no opposite flip)
    for p in (21,):
        for h in (12,):
            for side in ("both", "long"):
                rows.append({
                    "label": f"A_exit_nofliph{h}_{side}",
                    "name": f"rsi_only_{p}_{side}_no_flip",
                    "family": "rsi_only",
                    "period": p,
                    "hold": h,
                    "side": side,
                    "exit": "time_stop_only",
                    "fn": make_rsi_only_fn(period=p, side=side),
                    "atr_field": None,
                    "atr_k": None,
                })

    # Candidate B: rsi_only_30 h=16 both
    B_periods = (28, 30, 32, 34)
    B_holds = (12, 14, 16, 18, 20)
    for p in B_periods:
        for h in B_holds:
            for side in ("both", "long"):
                rows.append({
                    "label": f"B_band_p{p}_h{h}_{side}",
                    "name": f"rsi_only_{p}_{side}",
                    "family": "rsi_only",
                    "period": p,
                    "hold": h,
                    "side": side,
                    "exit": "time_stop+opposite_flip",
                    "fn": make_rsi_only_fn(period=p, side=side),
                    "atr_field": None,
                    "atr_k": None,
                })

    # Candidate C: rsi_and_macd_14 h=4 long-only
    C_periods = (10, 12, 14, 16, 18)
    C_holds = (2, 3, 4, 5, 6, 8)
    for p in C_periods:
        for h in C_holds:
            for side in ("long", "both"):
                rows.append({
                    "label": f"C_band_p{p}_h{h}_{side}",
                    "name": f"rsi_and_macd_{p}_{side}",
                    "family": "rsi_and_macd",
                    "period": p,
                    "hold": h,
                    "side": side,
                    "exit": "time_stop+opposite_flip",
                    "fn": make_rsi_and_macd_fn(period=p, side=side),
                    "atr_field": None,
                    "atr_k": None,
                })
    return rows


def build_atr_sweep() -> list[dict]:
    """ATR trailing stop on each candidate + a few robust neighbors."""
    k_values = (1.5, 2.0, 2.5, 3.0)
    atr_fields = ("atr_14", "atr_30")
    rows: list[dict] = []
    for c in CANDIDATES:
        for atr_field in atr_fields:
            for k in k_values:
                rows.append({
                    "label": f"{c['label']}_atr_{atr_field[-2:]}_k{k}",
                    "name": f"{c['name']}_atr_{atr_field[-2:]}_k{k}",
                    "family": c["family"],
                    "period": c["period"],
                    "hold": c["hold"],
                    "side": c["side"],
                    "exit": f"atr_{atr_field}_k{k}",
                    "fn": make_fn_for_candidate(c),
                    "atr_field": atr_field,
                    "atr_k": k,
                })
    return rows


# ── sweep driver ────────────────────────────────────────────────────


def run_sweep(tf: TimeframeData, cells: list[dict], *, title: str) -> list[dict]:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}\n")
    rows: list[dict] = []
    for spec in cells:
        extras = {
            "label": spec["label"],
            "family": spec["family"],
            "period": spec["period"],
            "side": spec["side"],
            "exit": spec["exit"],
        }
        if spec["atr_field"]:
            extras["atr_field"] = spec["atr_field"]
            extras["atr_k"] = spec["atr_k"]
        row = run_cell(
            name=spec["name"],
            tf=tf,
            signal_fn=spec["fn"],
            hold_bars=spec["hold"],
            fee_per_side=FEE_PER_SIDE,
            slip_per_side=SLIP_PER_SIDE,
            allow_opposite_flip_exit=(spec["exit"] != "time_stop_only"),
            atr_field=spec["atr_field"],
            atr_trail_k=spec["atr_k"],
            extra_fields=extras,
        )
        rows.append(row)
        print(format_row(row))
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
    print("Strategy C v2 Phase 4 — candidate + robustness + ATR sweep")
    print(f"Cost: fee={FEE_PER_SIDE * 100:.3f}% slip={SLIP_PER_SIDE * 100:.3f}%  "
          f"(round-trip {2 * (FEE_PER_SIDE + SLIP_PER_SIDE) * 100:.3f}%)")
    print("=" * 78)

    funding_records = load_funding_csv(FUNDING_CSV)
    print(f"funding records: {len(funding_records)}")

    t0 = time.time()
    print("\nLoading 4h data...")
    tf4h = load_timeframe_data("4h", KLINES_4H, 4.0, funding_records)
    print(f"  4h bars: {len(tf4h.bars):,}  features: {len(tf4h.features):,}  "
          f"splits: {len(tf4h.splits)}  ({time.time() - t0:.1f}s)")

    # Sweep 1: candidate consolidation
    c_cells = build_candidate_cells()
    c_rows = run_sweep(tf4h, c_cells, title="CANDIDATE CONSOLIDATION (A, B, C)")
    write_csv(CANDIDATES_CSV, c_rows)

    # Sweep 2: robustness band
    rb_cells = build_robustness_band()
    print(f"\nRobustness band: {len(rb_cells)} cells")
    rb_rows = run_sweep(tf4h, rb_cells, title="ROBUSTNESS BAND")
    write_csv(ROBUSTNESS_CSV, rb_rows)

    # Sweep 3: ATR trailing stop
    atr_cells = build_atr_sweep()
    print(f"\nATR trailing stop sweep: {len(atr_cells)} cells")
    atr_rows = run_sweep(tf4h, atr_cells, title="ATR TRAILING STOP SWEEP")
    write_csv(ATR_CSV, atr_rows)

    # Summary
    print(f"\n{'=' * 78}")
    print("SUMMARY — top 15 robustness band cells by OOS return")
    print("=" * 78)
    rb_ranked = sorted(
        [r for r in rb_rows if r["enough_trades"]],
        key=lambda r: r["agg_compounded_return"],
        reverse=True,
    )[:15]
    for r in rb_ranked:
        print(format_row(r))

    print(f"\n{'=' * 78}")
    print("SUMMARY — ATR trailing stop cells by OOS return")
    print("=" * 78)
    atr_ranked = sorted(
        atr_rows, key=lambda r: r["agg_compounded_return"], reverse=True
    )
    for r in atr_ranked:
        print(format_row(r))

    print(f"\n{'=' * 78}")
    print("CANDIDATES — final numbers")
    print("=" * 78)
    for r in c_rows:
        print(format_row(r))
        print(f"    gross={r['total_gross_pnl'] * 100:+7.2f}%  "
              f"funding={r['total_funding_pnl'] * 100:+7.2f}%  "
              f"cost={r['total_cost_pnl'] * 100:+7.2f}%  "
              f"avg_hold={r['avg_hold_bars']:.1f}")


if __name__ == "__main__":
    main()
