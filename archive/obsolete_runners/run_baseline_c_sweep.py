"""Strategy C Baseline C — return/frequency-balanced sweep.

Pipeline:
    1. Load feature bars from the chosen CSV (47-day pair_cvd by default,
       or 83-day no-cvd via --nocvd).
    2. Temporal split: first 70% train, last 30% holdout.
    3. For each mode in {reversal, continuation, hybrid}:
         compute long_scores / short_scores on TRAIN ONLY (no lookahead).
         For each percentile in 60..95 step 5:
           long_threshold  = percentile of train long_scores
           short_threshold = percentile of train short_scores
           For each (hold, cooldown) grid cell:
             emit signals on the full series with the train-derived thresholds
             run the backtest on the train slice and the holdout slice
             record the 12-metric dict for both
    4. Dump every cell into a CSV.
    5. Print three tables:
         - Reversal best holdout rows
         - Continuation best holdout rows
         - Hybrid best holdout rows
       Ranked by holdout compounded_return, min-trade filter applied.
    6. Print the trade-off frontier: for each mode, the Pareto-front between
       holdout trade count and holdout compounded_return.
    7. Print the single best overall config for the user's goal
       ("balance trades + return, cap DD, honest holdout sample").

Usage:
    python run_baseline_c_sweep.py              # 47-day pair_cvd (default)
    python run_baseline_c_sweep.py --nocvd      # 83-day no-cvd fallback

The CSV dump is the artifact we want ChatGPT Pro to review — it's
deterministic, long-form, and contains every train and holdout metric.
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

sys.path.insert(0, "src")

from data.strategy_c_dataset import load_strategy_c_csv
from data.strategy_c_features import StrategyCFeatureBar, compute_features
from research.backtest_strategy_c import run_strategy_c_backtest
from research.strategy_c_sweep import (
    passes_min_trades,
    percentile_threshold,
    temporal_split,
)
from strategies.strategy_c_baseline_c import (
    baseline_c_signals,
    long_scores,
    short_scores,
)


# ── Config ───────────────────────────────────────────────────────────

DATASET_CSV_CVD = "src/data/strategy_c_btcusdt_15m.csv"        # 47 days, with pair_cvd
DATASET_CSV_NOCVD = "src/data/strategy_c_btcusdt_15m_nocvd.csv"  # 83 days, no pair_cvd

TRAIN_FRAC = 0.70
PERCENTILES = (60.0, 65.0, 70.0, 75.0, 80.0, 85.0, 90.0, 95.0)
HOLDS = (1, 2, 4)
COOLDOWNS = (0, 1, 2)
STRESS_THRESHOLDS = (0.5, 1.0, 1.5)   # hybrid only
MODES = ("reversal", "continuation", "hybrid")

FEE_PER_SIDE = 0.0005       # 5 bps Binance USDT-M taker
SLIP_PER_SIDE = 0.0001      # 1 bp slippage
ROUND_TRIP_COST = 2 * (FEE_PER_SIDE + SLIP_PER_SIDE)

# Honesty guardrails: enforce minimum trade counts so the sweep can't hand us
# "best" cells built on 8 lucky trades.
MIN_TRAIN_TRADES = 30
MIN_HOLDOUT_TRADES = 15

METRIC_KEYS = (
    "num_trades",
    "compounded_return",
    "net_pnl",
    "avg_pnl",
    "profit_factor",
    "win_rate",
    "max_dd",
    "trade_sharpe",
    "trade_sortino",
    "avg_hold_bars",
    "exposure_time",
    "turnover",
)


# ── Sweep execution ──────────────────────────────────────────────────


@dataclass(frozen=True)
class SweepRow:
    mode: str
    include_cvd: bool
    percentile: float
    hold: int
    cooldown: int
    stress_threshold: float
    long_threshold: float
    short_threshold: float
    train: dict[str, float]
    holdout: dict[str, float]


def _run_one_cell(
    feats: Sequence[StrategyCFeatureBar],
    cut: int,
    *,
    mode: str,
    percentile: float,
    hold: int,
    cooldown: int,
    stress_threshold: float,
    include_cvd: bool,
) -> SweepRow:
    """Generate signals + run train + holdout backtests for one config cell."""
    train_feats = feats[:cut]
    hold_feats = feats[cut:]

    # 1. Compute scores on TRAIN only → percentile → concrete threshold.
    l_train = long_scores(
        train_feats,
        mode=mode,
        stress_threshold=stress_threshold,
        include_cvd=include_cvd,
    )
    s_train = short_scores(
        train_feats,
        mode=mode,
        stress_threshold=stress_threshold,
        include_cvd=include_cvd,
    )
    long_thr = percentile_threshold(l_train, percentile)
    short_thr = percentile_threshold(s_train, percentile)

    # 2. Generate signals on the FULL series using those thresholds.
    full_sigs = baseline_c_signals(
        feats,
        mode=mode,
        long_threshold=long_thr,
        short_threshold=short_thr,
        stress_threshold=stress_threshold,
        include_cvd=include_cvd,
    )

    # 3. Backtest train and holdout slices independently.
    train_res = run_strategy_c_backtest(
        train_feats,
        full_sigs[:cut],
        hold_bars=hold,
        cooldown_bars=cooldown,
        fee_per_side=FEE_PER_SIDE,
        slippage_per_side=SLIP_PER_SIDE,
    )
    hold_res = run_strategy_c_backtest(
        hold_feats,
        full_sigs[cut:],
        hold_bars=hold,
        cooldown_bars=cooldown,
        fee_per_side=FEE_PER_SIDE,
        slippage_per_side=SLIP_PER_SIDE,
    )

    return SweepRow(
        mode=mode,
        include_cvd=include_cvd,
        percentile=percentile,
        hold=hold,
        cooldown=cooldown,
        stress_threshold=stress_threshold,
        long_threshold=long_thr,
        short_threshold=short_thr,
        train=dict(train_res.metrics),
        holdout=dict(hold_res.metrics),
    )


def run_sweep(
    feats: Sequence[StrategyCFeatureBar],
    *,
    include_cvd: bool,
) -> list[SweepRow]:
    """Execute the full Baseline C sweep over MODES × PCTS × HOLDS × CDs."""
    cut = int(len(feats) * TRAIN_FRAC)
    rows: list[SweepRow] = []

    for mode in MODES:
        stresses = STRESS_THRESHOLDS if mode == "hybrid" else (1.0,)
        for stress in stresses:
            for pct in PERCENTILES:
                for hold in HOLDS:
                    for cd in COOLDOWNS:
                        rows.append(
                            _run_one_cell(
                                feats,
                                cut,
                                mode=mode,
                                percentile=pct,
                                hold=hold,
                                cooldown=cd,
                                stress_threshold=stress,
                                include_cvd=include_cvd,
                            )
                        )

    return rows


# ── Reporting helpers ────────────────────────────────────────────────


def _row_to_flat_dict(r: SweepRow) -> dict[str, float]:
    """Flatten a SweepRow for CSV export and filtering."""
    out: dict[str, float] = {
        "mode": r.mode,
        "include_cvd": 1 if r.include_cvd else 0,
        "percentile": r.percentile,
        "hold": r.hold,
        "cooldown": r.cooldown,
        "stress_threshold": r.stress_threshold,
        "long_threshold": r.long_threshold,
        "short_threshold": r.short_threshold,
    }
    for k in METRIC_KEYS:
        out[f"train_{k}"] = r.train.get(k, 0.0)
        out[f"holdout_{k}"] = r.holdout.get(k, 0.0)
    return out


def _dump_csv(rows: Sequence[SweepRow], path: str) -> None:
    flat = [_row_to_flat_dict(r) for r in rows]
    if not flat:
        return
    keys = list(flat[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(flat)


def _best_rows(
    rows: Sequence[SweepRow],
    *,
    mode: str,
    sort_key: str,
    top: int,
) -> list[SweepRow]:
    """Return the top-N rows for a mode filtered by min-trade guardrails."""
    candidates = [
        r for r in rows
        if r.mode == mode
        and passes_min_trades(
            {
                "train_num_trades": r.train["num_trades"],
                "holdout_num_trades": r.holdout["num_trades"],
            },
            min_train=MIN_TRAIN_TRADES,
            min_holdout=MIN_HOLDOUT_TRADES,
        )
    ]
    candidates.sort(key=lambda r: r.holdout[sort_key], reverse=True)
    return candidates[:top]


def _pareto_frontier(
    rows: Sequence[SweepRow], *, mode: str,
) -> list[SweepRow]:
    """Trade-off frontier: rows for which no other row has BOTH higher
    holdout compounded_return AND higher holdout num_trades. Filtered by
    min-trade guardrails first."""
    candidates = [
        r for r in rows
        if r.mode == mode
        and passes_min_trades(
            {
                "train_num_trades": r.train["num_trades"],
                "holdout_num_trades": r.holdout["num_trades"],
            },
            min_train=MIN_TRAIN_TRADES,
            min_holdout=MIN_HOLDOUT_TRADES,
        )
    ]

    front: list[SweepRow] = []
    for r in candidates:
        dominated = False
        for other in candidates:
            if other is r:
                continue
            if (
                other.holdout["compounded_return"] >= r.holdout["compounded_return"]
                and other.holdout["num_trades"] >= r.holdout["num_trades"]
                and (
                    other.holdout["compounded_return"] > r.holdout["compounded_return"]
                    or other.holdout["num_trades"] > r.holdout["num_trades"]
                )
            ):
                dominated = True
                break
        if not dominated:
            front.append(r)

    front.sort(key=lambda r: r.holdout["num_trades"])
    return front


def _print_row(tag: str, r: SweepRow) -> None:
    cfg = (
        f"{r.mode[:4]:<5} pct={r.percentile:>4.1f} h={r.hold} cd={r.cooldown}"
        f" stress={r.stress_threshold:.1f}"
    )
    t = r.train
    h = r.holdout
    print(
        f"  {tag} {cfg}"
        f"  TRAIN n={int(t['num_trades']):>4}"
        f" cmp={t['compounded_return']*100:>+7.2f}%"
        f" avg={t['avg_pnl']*100:>+6.3f}%"
        f" pf={t['profit_factor']:>5.2f}"
        f" dd={t['max_dd']*100:>5.2f}%"
        f" | HOLD n={int(h['num_trades']):>4}"
        f" cmp={h['compounded_return']*100:>+7.2f}%"
        f" avg={h['avg_pnl']*100:>+6.3f}%"
        f" pf={h['profit_factor']:>5.2f}"
        f" dd={h['max_dd']*100:>5.2f}%"
        f" exp={h['exposure_time']*100:>4.1f}%"
    )


def _print_table(title: str, rows: Sequence[SweepRow]) -> None:
    print(title)
    print("-" * 78)
    if not rows:
        print("  (no rows cleared min-trade guardrails)")
        return
    for r in rows:
        _print_row("  ", r)


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--nocvd",
        action="store_true",
        help="Use the 83-day no-cvd dataset instead of the 47-day pair_cvd one",
    )
    parser.add_argument(
        "--csv-out",
        default=None,
        help="Optional output CSV path. Defaults to baseline_c_sweep_{cvd|nocvd}.csv",
    )
    args = parser.parse_args()

    include_cvd = not args.nocvd
    dataset_csv = DATASET_CSV_CVD if include_cvd else DATASET_CSV_NOCVD
    csv_out = args.csv_out or (
        "baseline_c_sweep_cvd.csv" if include_cvd else "baseline_c_sweep_nocvd.csv"
    )

    print("=" * 78)
    print("Strategy C - Baseline C sweep (return/frequency balanced)")
    print("=" * 78)
    print(f"Dataset        : {dataset_csv}")
    print(f"include_cvd    : {include_cvd}")
    print(f"Train fraction : {TRAIN_FRAC}")
    print(f"Percentiles    : {PERCENTILES}")
    print(f"Hold bars      : {HOLDS}")
    print(f"Cooldown bars  : {COOLDOWNS}")
    print(f"Hybrid stress  : {STRESS_THRESHOLDS}")
    print(f"Modes          : {MODES}")
    print(f"Round-trip cost: {ROUND_TRIP_COST*100:.3f}%")
    print(f"Min trades     : train>={MIN_TRAIN_TRADES}, holdout>={MIN_HOLDOUT_TRADES}")
    print()

    bars = load_strategy_c_csv(dataset_csv)
    feats = compute_features(bars)
    print(f"Loaded {len(bars)} bars -> {len(feats)} feature bars (post-warmup)")
    print(
        f"Range: {feats[0].timestamp.isoformat()}"
        f" -> {feats[-1].timestamp.isoformat()}"
    )
    cut = int(len(feats) * TRAIN_FRAC)
    train = feats[:cut]
    holdout = feats[cut:]
    print(
        f"Train  : {len(train):>5} bars"
        f" ({train[0].timestamp.date()} -> {train[-1].timestamp.date()})"
    )
    print(
        f"Holdout: {len(holdout):>5} bars"
        f" ({holdout[0].timestamp.date()} -> {holdout[-1].timestamp.date()})"
    )

    # Report holdout buy-and-hold as a baseline
    bh_start = holdout[0].open
    bh_end = holdout[-1].close
    bh_ret = (bh_end / bh_start - 1.0) * 100
    print(f"Holdout B&H return: {bh_ret:+.2f}% (start {bh_start:.1f} -> close {bh_end:.1f})")
    print()

    total_cells = (
        # reversal + continuation: 8 * 3 * 3 = 72 each
        72 * 2
        # hybrid: 3 stress * 72 = 216
        + 216
    )
    print(f"Running {total_cells} config cells...")
    print()

    rows = run_sweep(feats, include_cvd=include_cvd)
    print(f"Completed {len(rows)} cells. Dumping to {csv_out}")
    _dump_csv(rows, csv_out)
    print()

    # ── Top-N tables per mode ────────────────────────────────────────
    print("=" * 78)
    print("TOP 10 PER MODE by holdout compounded_return (min-trade guardrail on)")
    print("=" * 78)
    for mode in MODES:
        _print_table(
            f"\n[{mode.upper()}] top 10 by holdout compounded_return",
            _best_rows(rows, mode=mode, sort_key="compounded_return", top=10),
        )
    print()

    # ── Pareto frontier: trade-off between return and trade count ───
    print("=" * 78)
    print("PARETO FRONTIER per mode (holdout compounded_return vs holdout trade count)")
    print("=" * 78)
    for mode in MODES:
        front = _pareto_frontier(rows, mode=mode)
        _print_table(f"\n[{mode.upper()}] Pareto frontier", front)
    print()

    # ── Final recommendation ────────────────────────────────────────
    print("=" * 78)
    print("BEST OVERALL CELL (highest holdout compounded_return, min-trade guardrail)")
    print("=" * 78)
    all_qualified = [
        r for r in rows
        if passes_min_trades(
            {
                "train_num_trades": r.train["num_trades"],
                "holdout_num_trades": r.holdout["num_trades"],
            },
            min_train=MIN_TRAIN_TRADES,
            min_holdout=MIN_HOLDOUT_TRADES,
        )
    ]
    if all_qualified:
        best = max(all_qualified, key=lambda r: r.holdout["compounded_return"])
        _print_row("BEST", best)
        print()
        print(
            f"  Holdout B&H: {bh_ret:+.2f}%  |"
            f"  best holdout compounded: {best.holdout['compounded_return']*100:+.2f}%"
        )
    else:
        print("  (no cells cleared min-trade guardrails)")
    print()
    print("=" * 78)
    print("Done. CSV for external review:", csv_out)
    print("=" * 78)


if __name__ == "__main__":
    main()
