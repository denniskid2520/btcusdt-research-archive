"""Strategy C v2 Phase 6 — tail-event stress analysis.

Post-processing script that takes the expanded sweep CSV and, for each
cell, computes synthetic tail-event survivability under three shock
scenarios:
  - 20% adverse move in 1 day
  - 30% adverse move in 2 days
  - 40% adverse move in 1 day

Analysis model (conservative):
  For shock X and actual position_frac P:
    - If X <= stop_loss_pct, the stop fires intra-bar and caps loss at
      stop_loss_pct * P (ignoring slippage).
    - If X >  stop_loss_pct, the gap-opens-below-stop scenario applies.
      The stop fires at the gap open, which is approximately at the
      shock price. Effective per-trade loss = X * P.
    - Liquidation occurs when effective per-trade loss > 1 (100% of
      equity). Maintenance margin adds a few bp of buffer.

This is a deliberately simple model. It treats the shock as a single
adverse bar and asks: "how bad does this trade get?" Reality is messier
(slippage on stop fills, partial closes, exchange maintenance margin,
cross-strategy portfolio effects), but the model captures the dominant
structural risk per cell.
"""
from __future__ import annotations

import csv
from pathlib import Path


EXPANDED_CSV = Path("strategy_c_v2_phase6_expanded_sweep.csv")
OUTPUT_CSV = Path("strategy_c_v2_phase6_tail_event_stress.csv")


SHOCK_SCENARIOS = [
    ("shock_20", 0.20),   # 20% / 1 day
    ("shock_30", 0.30),   # 30% / 2 days (2022-Luna-like)
    ("shock_40", 0.40),   # 40% / 1 day (2020-COVID-like)
]


def flt(r: dict, k: str, default: float = 0.0) -> float:
    v = r.get(k, "")
    if v in ("", "None", None):
        return default
    return float(v)


def analyze_cell(row: dict) -> dict:
    """For one sweep cell, compute tail-event stress under 3 scenarios."""
    stop = flt(row, "stop_loss_pct")
    frac = flt(row, "actual_position_frac", 1.0)
    base_ret = flt(row, "agg_compounded_return")
    base_dd = flt(row, "combined_max_dd")

    out: dict = {
        "label": row["label"],
        "stop_loss_pct": stop,
        "stop_trigger": row["stop_trigger"],
        "risk_per_trade": flt(row, "risk_per_trade"),
        "effective_leverage": flt(row, "effective_leverage"),
        "actual_position_frac": frac,
        "baseline_return": base_ret,
        "baseline_dd": base_dd,
        "baseline_worst_trade": flt(row, "worst_trade_pnl"),
    }

    for name, shock in SHOCK_SCENARIOS:
        # If the stop is tighter than the shock, the stop would
        # (attempt to) cap loss at stop * frac; otherwise the gap
        # delivers loss ~ shock * frac.
        if stop > 0 and shock <= stop:
            per_trade_loss = stop * frac
        else:
            per_trade_loss = shock * frac
        liquidated = per_trade_loss >= 1.0
        out[f"{name}_per_trade_loss"] = per_trade_loss
        out[f"{name}_liquidated"] = liquidated
        out[f"{name}_eq_impact"] = min(1.0, per_trade_loss)
    return out


def main() -> None:
    if not EXPANDED_CSV.exists():
        raise SystemExit(f"Missing {EXPANDED_CSV} — run run_strategy_c_v2_phase6_sweep.py first")

    sweep_rows = []
    with EXPANDED_CSV.open() as fh:
        for r in csv.DictReader(fh):
            sweep_rows.append(r)

    # Analyze every cell
    analyzed = [analyze_cell(r) for r in sweep_rows]

    # Write CSV
    keys = list(analyzed[0].keys())
    with OUTPUT_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for row in analyzed:
            w.writerow(row)
    print(f"Wrote {OUTPUT_CSV} ({len(analyzed)} rows)")

    # Print verdict tables per candidate
    print("\n" + "=" * 90)
    print("TAIL-EVENT STRESS — per-cell survivability table (ignoring slippage)")
    print("=" * 90)
    print(f"{'label':<10} {'sl':>6} {'trig':<5} {'r':>5} {'L':>4} {'frac':>5}  "
          f"{'base_ret':>10} "
          f"{'20%_loss':>9} {'30%_loss':>9} {'40%_loss':>9}  verdict")
    print("-" * 90)

    # Sort by label, stop, trigger, risk, leverage for readability
    def sort_key(r):
        return (r["label"], r["stop_loss_pct"], r["stop_trigger"],
                r["risk_per_trade"], r["effective_leverage"])
    analyzed_sorted = sorted(analyzed, key=sort_key)

    # Pick representative cells (frac == actual L-capped): one per
    # (label, stop, trigger, risk, L) — which is what the sweep already does
    for r in analyzed_sorted:
        if r["stop_loss_pct"] == 0:
            continue  # skip baseline rows
        # Verdict string
        v20 = "LIQ" if r["shock_20_liquidated"] else ""
        v30 = "LIQ" if r["shock_30_liquidated"] else ""
        v40 = "LIQ" if r["shock_40_liquidated"] else ""
        verdict = "/".join(v for v in (v20, v30, v40) if v) or "SURVIVE"
        # Only print interesting rows — frac >= 2 (where tail matters)
        # or liquidation-risk cells
        if r["actual_position_frac"] < 2.0 and verdict == "SURVIVE":
            continue
        print(
            f"{r['label']:<10} {r['stop_loss_pct']*100:>5.2f}% {r['stop_trigger']:<5} "
            f"{r['risk_per_trade']*100:>4.1f}% {r['effective_leverage']:>4.1f} "
            f"{r['actual_position_frac']:>5.2f}  "
            f"{r['baseline_return']*100:>+9.1f}% "
            f"{r['shock_20_eq_impact']*100:>7.1f}% "
            f"{r['shock_30_eq_impact']*100:>7.1f}% "
            f"{r['shock_40_eq_impact']*100:>7.1f}%  "
            f"{verdict}"
        )


if __name__ == "__main__":
    main()
