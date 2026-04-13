"""Strategy C Baseline B — temporal holdout sweep.

Pipeline:
    1. Load 4500-bar dataset and compute features.
    2. Temporal split: first 70% train, last 30% holdout.
    3. Compute long_scores and short_scores on TRAIN ONLY.
    4. For each percentile in (80, 85, 90, 95, 97.5):
        - Long threshold  = that percentile of long_scores (train).
        - Short threshold = same percentile of short_scores (train).
        - Emit signals over the FULL series (lookahead-free: thresholds come
          from train only, but the signals still respect per-bar causality).
        - Backtest the train slice AND the holdout slice independently.
    5. Report train vs holdout metrics for each (percentile, hold, cooldown).

We want to see whether the precision we tune on train survives out of sample.
That's the real signal test — everything else is noise chasing.

Usage:
    python run_baseline_b_sweep.py
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
    """Simple percentile via linear interpolation — like numpy.percentile."""
    if not vals:
        raise ValueError("cannot compute percentile of empty list")
    s = sorted(vals)
    k = (len(s) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _fmt_metric_row(label: str, m: dict[str, float]) -> str:
    n = int(m["num_trades"])
    return (
        f"  {label:<10}"
        f" n={n:>4}"
        f"  win={m['win_rate'] * 100:>5.1f}%"
        f"  avg={m['avg_pnl'] * 100:>+7.4f}%"
        f"  net={m['net_pnl'] * 100:>+7.2f}%"
        f"  dd={m['max_dd'] * 100:>5.2f}%"
        f"  sharpe={m['trade_sharpe']:>+5.2f}"
    )


def main() -> None:
    print("=" * 78)
    print("Strategy C - Baseline B threshold sweep (temporal 70/30 holdout)")
    print("=" * 78)

    # 1. Load and compute features
    bars = load_strategy_c_csv(DATASET_CSV)
    feats = compute_features(bars)
    print(f"Total feature bars: {len(feats)}")
    print(f"Range: {feats[0].timestamp.isoformat()} -> {feats[-1].timestamp.isoformat()}")

    # 2. Split
    cut = int(len(feats) * TRAIN_FRAC)
    train_feats = feats[:cut]
    hold_feats = feats[cut:]
    print(f"Train: {len(train_feats)} bars ({train_feats[0].timestamp.date()} -> {train_feats[-1].timestamp.date()})")
    print(f"Hold : {len(hold_feats)} bars ({hold_feats[0].timestamp.date()} -> {hold_feats[-1].timestamp.date()})")
    print(f"Cost : {2*(FEE_PER_SIDE + SLIP_PER_SIDE)*100:.3f}% round-trip")
    print()

    # 3. Scores on train only
    l_train = [s for s in long_scores(train_feats) if s is not None]
    s_train = [s for s in short_scores(train_feats) if s is not None]
    print(f"Train long_scores:  {len(l_train)} non-None, range [{min(l_train):.2f}, {max(l_train):.2f}]")
    print(f"Train short_scores: {len(s_train)} non-None, range [{min(s_train):.2f}, {max(s_train):.2f}]")
    print()

    # 4. Sweep
    print("=" * 78)
    header_shown = False
    for pct in PERCENTILES:
        long_thr = percentile(l_train, pct)
        short_thr = percentile(s_train, pct)

        for hold in HOLDS:
            for cooldown in COOLDOWNS:
                # Generate signals on the full series so that train and
                # holdout are both evaluated with the same signal stream.
                # (Thresholds still come ONLY from the train slice.)
                full_sigs = baseline_b_signals(
                    feats, long_threshold=long_thr, short_threshold=short_thr,
                )

                train_sigs = full_sigs[:cut]
                hold_sigs = full_sigs[cut:]

                train_res = run_strategy_c_backtest(
                    train_feats, train_sigs,
                    hold_bars=hold, cooldown_bars=cooldown,
                    fee_per_side=FEE_PER_SIDE, slippage_per_side=SLIP_PER_SIDE,
                )
                hold_res = run_strategy_c_backtest(
                    hold_feats, hold_sigs,
                    hold_bars=hold, cooldown_bars=cooldown,
                    fee_per_side=FEE_PER_SIDE, slippage_per_side=SLIP_PER_SIDE,
                )

                if header_shown:
                    print("-" * 78)
                print(
                    f"pct={pct:<5} hold={hold} cd={cooldown}  "
                    f"L>={long_thr:.2f} S>={short_thr:.2f}"
                )
                header_shown = True
                print(_fmt_metric_row("TRAIN", train_res.metrics))
                print(_fmt_metric_row("HOLDOUT", hold_res.metrics))

    print()
    print("=" * 78)
    print("Legend: 'win' = raw win rate after cost, 'avg' = avg net return per trade,")
    print("        'net' = sum of trade returns (not compounded), 'dd' = max drawdown,")
    print("        'sharpe' = trade-level mean/std. Positive 'avg' on HOLDOUT is the goal.")
    print("=" * 78)


if __name__ == "__main__":
    main()
