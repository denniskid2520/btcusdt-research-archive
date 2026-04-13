"""Strategy C - compare Baseline B WITH vs WITHOUT pair_cvd.

The event study showed that cvd_delta sign is IDENTICAL to taker_delta sign on
every bucket split — strong hint that pair_cvd is redundant on this dataset.

This script runs the same train/holdout sweep twice — once with the default
scoring (include_cvd=True), once with the cvd_delta_z32 term omitted — and
prints the best (least-bad) holdout metrics for each mode side by side.

If the two modes produce near-identical numbers, pair_cvd adds no signal and
we should drop it from the feature set (which unlocks longer history, since
pair_cvd was the 47-day intersection floor).
"""
from __future__ import annotations

import sys

sys.path.insert(0, "src")

from data.strategy_c_dataset import load_strategy_c_csv
from data.strategy_c_features import compute_features
from research.backtest_strategy_c import run_strategy_c_backtest
from strategies.strategy_c_baseline_b import (
    baseline_b_signals,
    long_scores,
    short_scores,
)


DATASET_CSV = "src/data/strategy_c_btcusdt_15m.csv"
TRAIN_FRAC = 0.70
PERCENTILES = (80.0, 85.0, 90.0, 95.0, 97.5)
HOLDS = (1, 2, 4)
COOLDOWNS = (0, 2)
FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001


def percentile(vals: list[float], pct: float) -> float:
    s = sorted(vals)
    k = (len(s) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def sweep(feats, train_cut, *, include_cvd: bool) -> list[dict]:
    """Return a row per (pct, hold, cd) combo with train/holdout metrics."""
    train = feats[:train_cut]
    l_tr = [s for s in long_scores(train, include_cvd=include_cvd) if s is not None]
    s_tr = [s for s in short_scores(train, include_cvd=include_cvd) if s is not None]

    rows: list[dict] = []
    for pct in PERCENTILES:
        long_thr = percentile(l_tr, pct)
        short_thr = percentile(s_tr, pct)

        full_sigs = baseline_b_signals(
            feats,
            long_threshold=long_thr, short_threshold=short_thr,
            include_cvd=include_cvd,
        )
        for hold in HOLDS:
            for cd in COOLDOWNS:
                t_res = run_strategy_c_backtest(
                    train, full_sigs[:train_cut],
                    hold_bars=hold, cooldown_bars=cd,
                    fee_per_side=FEE_PER_SIDE, slippage_per_side=SLIP_PER_SIDE,
                )
                h_res = run_strategy_c_backtest(
                    feats[train_cut:], full_sigs[train_cut:],
                    hold_bars=hold, cooldown_bars=cd,
                    fee_per_side=FEE_PER_SIDE, slippage_per_side=SLIP_PER_SIDE,
                )
                rows.append({
                    "pct": pct, "hold": hold, "cd": cd,
                    "long_thr": long_thr, "short_thr": short_thr,
                    "train": t_res.metrics, "holdout": h_res.metrics,
                })
    return rows


def _row_key(r: dict) -> tuple:
    return (r["pct"], r["hold"], r["cd"])


def main() -> None:
    print("=" * 78)
    print("Baseline B - with/without pair_cvd comparison")
    print("=" * 78)

    bars = load_strategy_c_csv(DATASET_CSV)
    feats = compute_features(bars)
    cut = int(len(feats) * TRAIN_FRAC)
    print(f"Dataset: {len(feats)} feats   train={cut}  holdout={len(feats)-cut}")
    print()

    rows_with = sweep(feats, cut, include_cvd=True)
    rows_without = sweep(feats, cut, include_cvd=False)

    # Pair rows by config
    by_key_with = {_row_key(r): r for r in rows_with}
    by_key_without = {_row_key(r): r for r in rows_without}

    print(f"{'pct':>5} {'h':>2} {'cd':>2}  "
          f"{'WITH cvd':<30}  {'WITHOUT cvd':<30}  diff")
    print(f"{'---':>5} {'--':>2} {'--':>2}  "
          f"{'n / win / avg / net':<30}  {'n / win / avg / net':<30}  avg")
    print("-" * 110)

    for key in sorted(by_key_with):
        w = by_key_with[key]["holdout"]
        wo = by_key_without[key]["holdout"]
        pct, hold, cd = key
        fmt = (
            f"n={int(w['num_trades']):>4} "
            f"w={w['win_rate']*100:>4.1f}% "
            f"a={w['avg_pnl']*100:>+6.3f}% "
            f"net={w['net_pnl']*100:>+6.2f}%"
        )
        fmt_wo = (
            f"n={int(wo['num_trades']):>4} "
            f"w={wo['win_rate']*100:>4.1f}% "
            f"a={wo['avg_pnl']*100:>+6.3f}% "
            f"net={wo['net_pnl']*100:>+6.2f}%"
        )
        diff = (wo["avg_pnl"] - w["avg_pnl"]) * 100
        print(f"{pct:>5} {hold:>2} {cd:>2}  {fmt:<30}  {fmt_wo:<30}  {diff:>+5.3f}%")

    # Find best rows in each mode (least-bad holdout avg, min 20 trades)
    def best_row(rows):
        eligible = [r for r in rows if r["holdout"]["num_trades"] >= 20]
        return max(eligible, key=lambda r: r["holdout"]["avg_pnl"]) if eligible else None

    print()
    print("=" * 78)
    print("Best HOLDOUT row in each mode (min 20 trades):")
    print("=" * 78)
    for label, rows in [("WITH pair_cvd", rows_with), ("WITHOUT pair_cvd", rows_without)]:
        r = best_row(rows)
        if r is None:
            print(f"  {label}: no eligible row")
            continue
        m = r["holdout"]
        tm = r["train"]
        print(
            f"  {label:<18} "
            f"pct={r['pct']} h={r['hold']} cd={r['cd']}  "
            f"HOLDOUT: n={int(m['num_trades'])} win={m['win_rate']*100:.1f}% "
            f"avg={m['avg_pnl']*100:+.3f}% net={m['net_pnl']*100:+.2f}%  "
            f"(TRAIN: n={int(tm['num_trades'])} win={tm['win_rate']*100:.1f}% "
            f"avg={tm['avg_pnl']*100:+.3f}%)"
        )


if __name__ == "__main__":
    main()
