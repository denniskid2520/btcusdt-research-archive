"""Strategy C v2 Phase 6 — D1 promotion + expanded risk budget + stop-slippage.

Runs three sub-sweeps in one pass, all on the 4h walk-forward:

1. **D1 robustness band** — no stops, tests whether D1 is a broad or
   sharp optimum across RSI period × hold × side × exit type.

2. **Expanded risk-budget sweep** — risk 2.0-4.0%, stop 1.0-2.0%, L=2/3/5.
   Applied to A_both, A_long, C_long, D1_both, D1_long, D2_both.
   Reports actual position_frac per cell (not just L).

3. **Stop-slippage stress** — top cells from #2 rerun with stop-fill
   slippage mild/medium/severe (0.10 / 0.30 / 1.00%).

Outputs:
    strategy_c_v2_phase6_d1_robustness.csv
    strategy_c_v2_phase6_expanded_sweep.csv
    strategy_c_v2_phase6_slippage_stress.csv
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

D1_ROBUSTNESS_CSV = Path("strategy_c_v2_phase6_d1_robustness.csv")
EXPANDED_CSV = Path("strategy_c_v2_phase6_expanded_sweep.csv")
SLIPPAGE_CSV = Path("strategy_c_v2_phase6_slippage_stress.csv")

FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001

STOP_LOSS_PCTS = (0.010, 0.0125, 0.015, 0.020)
STOP_TRIGGERS = ("wick", "close")
RISK_PER_TRADE = (0.020, 0.025, 0.030, 0.040)
EFFECTIVE_LEVERAGES = (2.0, 3.0, 5.0)
SLIPPAGE_LEVELS = (0.0, 0.001, 0.003, 0.010)  # none / mild / medium / severe


# ── signal factories ────────────────────────────────────────────────


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


# ── Phase 6 candidate specs ─────────────────────────────────────────


CANDIDATES = [
    {
        "label": "A_both", "name": "rsi_only_21_h12_both",
        "period": 21, "hold": 12, "side": "both", "family": "rsi_only",
        "shadow": False,
    },
    {
        "label": "A_long", "name": "rsi_only_21_h12_long",
        "period": 21, "hold": 12, "side": "long", "family": "rsi_only",
        "shadow": False,
    },
    {
        "label": "C_long", "name": "rsi_and_macd_14_h4_long",
        "period": 14, "hold": 4, "side": "long", "family": "rsi_and_macd",
        "shadow": False,
    },
    {
        "label": "D1_both", "name": "rsi_only_20_h11_both",
        "period": 20, "hold": 11, "side": "both", "family": "rsi_only",
        "shadow": False,  # promoted from shadow
    },
    {
        "label": "D1_long", "name": "rsi_only_20_h11_long",
        "period": 20, "hold": 11, "side": "long", "family": "rsi_only",
        "shadow": False,
    },
    {
        "label": "D2_shadow", "name": "rsi_only_28_h18_both",
        "period": 28, "hold": 18, "side": "both", "family": "rsi_only",
        "shadow": True,
    },
]


def make_fn_for_candidate(c: dict) -> Callable:
    if c["family"] == "rsi_only":
        return make_rsi_only_fn(period=c["period"], side=c["side"])
    return make_rsi_and_macd_fn(period=c["period"], side=c["side"])


# ── Sweep 1: D1 robustness band (no stops) ───────────────────────────


def build_d1_robustness_cells() -> list[dict]:
    """Parameter perturbation around D1 (rsi_only_20 h=11 both).

    Grid: period ∈ {18, 19, 20, 21, 22} × hold ∈ {9, 10, 11, 12, 13}
          × side ∈ {both, long} × allow_flip ∈ {True, False}
    """
    rows: list[dict] = []
    for p in (18, 19, 20, 21, 22):
        for h in (9, 10, 11, 12, 13):
            for side in ("both", "long"):
                for allow_flip in (True, False):
                    rows.append({
                        "label": f"D1_band_p{p}_h{h}_{side}_{'flip' if allow_flip else 'nopflip'}",
                        "name": f"rsi_only_{p}_h{h}_{side}",
                        "family": "rsi_only",
                        "period": p, "hold": h, "side": side,
                        "allow_flip": allow_flip,
                        "fn": make_rsi_only_fn(period=p, side=side),
                    })
    return rows


# ── Sweep 2: expanded risk budget ───────────────────────────────────


def build_expanded_cells() -> list[dict]:
    """All candidates × expanded (stop, trigger, risk, leverage) grid."""
    rows: list[dict] = []
    for c in CANDIDATES:
        for sl in STOP_LOSS_PCTS:
            for trig in STOP_TRIGGERS:
                for risk in RISK_PER_TRADE:
                    for lev in EFFECTIVE_LEVERAGES:
                        raw = risk / sl
                        actual = min(raw, lev)
                        rows.append({
                            "label": c["label"],
                            "name": c["name"],
                            "period": c["period"],
                            "hold": c["hold"],
                            "side": c["side"],
                            "family": c["family"],
                            "shadow": c["shadow"],
                            "stop_loss_pct": sl,
                            "stop_trigger": trig,
                            "risk_per_trade": risk,
                            "effective_leverage": lev,
                            "raw_frac": raw,
                            "actual_frac": actual,
                            "capped": raw > lev,
                            "fn": make_fn_for_candidate(c),
                        })
    return rows


# ── Sweep 3: slippage stress on pre-selected top cells ─────────────
#
# Once the expanded sweep completes, pick the top non-shadow cells and
# rerun them under the 4 slippage levels. Because this is sequential
# (runs after sweep 2), it's called from main().


# ── runners ─────────────────────────────────────────────────────────


def run_d1_robustness(tf: TimeframeData) -> list[dict]:
    print(f"\n{'=' * 78}\nSWEEP 1 — D1 ROBUSTNESS BAND (no stops)\n{'=' * 78}")
    cells = build_d1_robustness_cells()
    print(f"  {len(cells)} cells")
    rows: list[dict] = []
    cur_side = None
    for spec in cells:
        if spec["side"] != cur_side:
            cur_side = spec["side"]
            print(f"\n[side={cur_side}]")
        extras = {
            "label": spec["label"],
            "family": spec["family"],
            "period": spec["period"],
            "hold_bars_cfg": spec["hold"],
            "side": spec["side"],
            "allow_flip": spec["allow_flip"],
        }
        row = run_cell(
            name=spec["name"],
            tf=tf,
            signal_fn=spec["fn"],
            hold_bars=spec["hold"],
            fee_per_side=FEE_PER_SIDE,
            slip_per_side=SLIP_PER_SIDE,
            allow_opposite_flip_exit=spec["allow_flip"],
            extra_fields=extras,
        )
        rows.append(row)
    return rows


def run_expanded_sweep(tf: TimeframeData) -> list[dict]:
    print(f"\n{'=' * 78}\nSWEEP 2 — EXPANDED RISK-BUDGET × LEVERAGE (no slip)\n{'=' * 78}")
    cells = build_expanded_cells()
    print(f"  {len(cells)} cells")
    rows: list[dict] = []
    cur_label = None
    for spec in cells:
        if spec["label"] != cur_label:
            cur_label = spec["label"]
            print(f"\n[{cur_label}]")
        extras = {
            "label": spec["label"],
            "family": spec["family"],
            "period": spec["period"],
            "side": spec["side"],
            "shadow": spec["shadow"],
            "stop_loss_pct": spec["stop_loss_pct"],
            "stop_trigger": spec["stop_trigger"],
            "risk_per_trade": spec["risk_per_trade"],
            "effective_leverage": spec["effective_leverage"],
            "raw_position_frac": spec["raw_frac"],
            "actual_position_frac": spec["actual_frac"],
            "capped_by_leverage": spec["capped"],
            "stop_slip_pct": 0.0,
        }
        row = run_cell(
            name=spec["name"],
            tf=tf,
            signal_fn=spec["fn"],
            hold_bars=spec["hold"],
            fee_per_side=FEE_PER_SIDE,
            slip_per_side=SLIP_PER_SIDE,
            stop_loss_pct=spec["stop_loss_pct"],
            stop_trigger=spec["stop_trigger"],
            risk_per_trade=spec["risk_per_trade"],
            effective_leverage=spec["effective_leverage"],
            extra_fields=extras,
        )
        rows.append(row)
    return rows


def run_slippage_stress(tf: TimeframeData, expanded_rows: list[dict]) -> list[dict]:
    """Rerun the top 20 non-shadow cells under 4 slippage levels."""
    print(f"\n{'=' * 78}\nSWEEP 3 — STOP-SLIPPAGE STRESS (top 20 cells × 4 slip levels)\n{'=' * 78}")

    # Select top 20 non-shadow cells by OOS return, enough_trades only
    ranked = sorted(
        [r for r in expanded_rows if r["enough_trades"] and not r.get("shadow", False)],
        key=lambda r: r["agg_compounded_return"],
        reverse=True,
    )[:20]

    rows: list[dict] = []
    for r in ranked:
        # Re-resolve the signal fn from label + family + period + side
        lab = r["label"]
        c = next(x for x in CANDIDATES if x["label"] == lab)
        fn = make_fn_for_candidate(c)
        for slip in SLIPPAGE_LEVELS:
            extras = {
                "label": r["label"],
                "family": r["family"],
                "period": r["period"],
                "side": r["side"],
                "shadow": r["shadow"],
                "stop_loss_pct": r["stop_loss_pct"],
                "stop_trigger": r["stop_trigger"],
                "risk_per_trade": r["risk_per_trade"],
                "effective_leverage": r["effective_leverage"],
                "stop_slip_pct": slip,
                "raw_position_frac": r["raw_position_frac"],
                "actual_position_frac": r["actual_position_frac"],
            }
            row = run_cell(
                name=r["strategy"],
                tf=tf,
                signal_fn=fn,
                hold_bars=c["hold"],
                fee_per_side=FEE_PER_SIDE,
                slip_per_side=SLIP_PER_SIDE,
                stop_loss_pct=r["stop_loss_pct"],
                stop_trigger=r["stop_trigger"],
                stop_slip_pct=slip,
                risk_per_trade=r["risk_per_trade"],
                effective_leverage=r["effective_leverage"],
                extra_fields=extras,
            )
            rows.append(row)
    return rows


# ── output ──────────────────────────────────────────────────────────


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
    print(f"Wrote {path} ({len(rows)} rows)")


def main() -> None:
    print("=" * 78)
    print("Strategy C v2 Phase 6 — D1 promotion + expanded risk + slippage")
    print("=" * 78)

    funding_records = load_funding_csv(FUNDING_CSV)
    print(f"funding records: {len(funding_records)}")

    t0 = time.time()
    print("\nLoading 4h data...")
    tf4h = load_timeframe_data("4h", KLINES_4H, 4.0, funding_records)
    print(f"  4h bars: {len(tf4h.bars):,}  features: {len(tf4h.features):,}  "
          f"splits: {len(tf4h.splits)}  ({time.time() - t0:.1f}s)")

    # Sweep 1: D1 robustness band (fast, no stops)
    t0 = time.time()
    d1_rows = run_d1_robustness(tf4h)
    write_csv(D1_ROBUSTNESS_CSV, d1_rows)
    print(f"  D1 robustness runtime: {time.time() - t0:.1f}s")

    # Sweep 2: expanded risk-budget (the big one)
    t0 = time.time()
    expanded_rows = run_expanded_sweep(tf4h)
    write_csv(EXPANDED_CSV, expanded_rows)
    print(f"  Expanded sweep runtime: {time.time() - t0:.1f}s")

    # Sweep 3: slippage stress on top 20 cells
    t0 = time.time()
    slip_rows = run_slippage_stress(tf4h, expanded_rows)
    write_csv(SLIPPAGE_CSV, slip_rows)
    print(f"  Slippage stress runtime: {time.time() - t0:.1f}s")

    # Headline summaries
    print(f"\n{'=' * 78}\nTOP 15 — D1 robustness band (no stops)\n{'=' * 78}")
    for r in sorted(
        [r for r in d1_rows if r["enough_trades"]],
        key=lambda r: r["agg_compounded_return"],
        reverse=True,
    )[:15]:
        print(format_row(r))

    print(f"\n{'=' * 78}\nTOP 20 — Expanded sweep (all candidates, any leverage)\n{'=' * 78}")
    for r in sorted(
        [r for r in expanded_rows if r["enough_trades"]],
        key=lambda r: r["agg_compounded_return"],
        reverse=True,
    )[:20]:
        print(
            f"  {r['label']:<10} sl={r['stop_loss_pct'] * 100:>4.2f}% "
            f"{r['stop_trigger']:<5} r={r['risk_per_trade'] * 100:>4.1f}% "
            f"L={r['effective_leverage']:>3.1f} frac={r['actual_position_frac']:>5.3f}  "
            f"ret={r['agg_compounded_return'] * 100:>+8.2f}%  "
            f"dd={r['combined_max_dd'] * 100:>5.2f}%  "
            f"n={int(r['total_oos_trades']):>4d}  "
            f"wt={r['worst_trade_pnl'] * 100:>+6.2f}%  "
            f"liq={r['liq_safety_2x'] * 100:>+5.2f}%"
        )

    print(f"\n{'=' * 78}\nTOP 15 non-shadow @ L<=3x, enough trades\n{'=' * 78}")
    for r in sorted(
        [
            r for r in expanded_rows
            if r["enough_trades"] and not r.get("shadow", False)
            and r["effective_leverage"] <= 3.0
        ],
        key=lambda r: r["agg_compounded_return"],
        reverse=True,
    )[:15]:
        print(
            f"  {r['label']:<10} sl={r['stop_loss_pct'] * 100:>4.2f}% "
            f"{r['stop_trigger']:<5} r={r['risk_per_trade'] * 100:>4.1f}% "
            f"L={r['effective_leverage']:>3.1f} frac={r['actual_position_frac']:>5.3f}  "
            f"ret={r['agg_compounded_return'] * 100:>+8.2f}%  "
            f"dd={r['combined_max_dd'] * 100:>5.2f}%  "
            f"n={int(r['total_oos_trades']):>4d}  "
            f"wt={r['worst_trade_pnl'] * 100:>+6.2f}%"
        )


if __name__ == "__main__":
    main()
