"""Strategy C Baseline B FADE — test whether the signal is predictive backwards.

The confirm-mode sweep showed train+holdout win rates of 15-40%, consistently
below 50%. If the score is systematically wrong, the inverse is systematically
right. This script sweeps the same grid with signals FLIPPED:

    high long_score  → SHORT
    high short_score → LONG

Everything else (temporal split, percentile grid, hold/cooldown) is identical.
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
    print("Strategy C - Baseline B FADE sweep (flip signals, same grid)")
    print("=" * 78)

    bars = load_strategy_c_csv(DATASET_CSV)
    feats = compute_features(bars)
    cut = int(len(feats) * TRAIN_FRAC)
    train_feats = feats[:cut]
    hold_feats = feats[cut:]
    print(f"Train: {len(train_feats)} bars    Holdout: {len(hold_feats)} bars")
    print(f"Cost : {2*(FEE_PER_SIDE + SLIP_PER_SIDE)*100:.3f}% round-trip")
    print()

    l_train = [s for s in long_scores(train_feats) if s is not None]
    s_train = [s for s in short_scores(train_feats) if s is not None]

    print("=" * 78)
    header_shown = False
    for pct in PERCENTILES:
        long_thr = percentile(l_train, pct)
        short_thr = percentile(s_train, pct)

        for hold in HOLDS:
            for cooldown in COOLDOWNS:
                raw_sigs = baseline_b_signals(
                    feats, long_threshold=long_thr, short_threshold=short_thr,
                )
                # FADE: flip the sign so long_score hits produce SHORTS.
                fade_sigs = [-s for s in raw_sigs]

                train_sigs = fade_sigs[:cut]
                hold_sigs = fade_sigs[cut:]

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
                    f"L>={long_thr:.2f} S>={short_thr:.2f}  (FADED)"
                )
                header_shown = True
                print(_fmt_metric_row("TRAIN", train_res.metrics))
                print(_fmt_metric_row("HOLDOUT", hold_res.metrics))

    print()
    print("=" * 78)
    print("If FADE shows positive avg on holdout, the score is predictive backwards.")
    print("=" * 78)


if __name__ == "__main__":
    main()
