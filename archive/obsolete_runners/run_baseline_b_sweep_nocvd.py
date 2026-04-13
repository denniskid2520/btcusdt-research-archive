"""Strategy C Baseline B sweep on the 83-day NO-CVD extended dataset.

Same temporal 70/30 holdout + percentile grid as run_baseline_b_sweep.py,
but on 2x more data and with include_cvd=False (since the dataset has no
pair_cvd column — cvd field is filled with 0.0).

This is the fallback path specified by the user: if the 47-day dataset
doesn't show a positive-edge set of events, rerun on the longer dataset
without pair_cvd.
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


DATASET_CSV = "src/data/strategy_c_btcusdt_15m_nocvd.csv"
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


def _fmt(label: str, m: dict[str, float]) -> str:
    n = int(m["num_trades"])
    return (
        f"  {label:<8}"
        f" n={n:>4}"
        f"  win={m['win_rate'] * 100:>5.1f}%"
        f"  avg={m['avg_pnl'] * 100:>+7.4f}%"
        f"  net={m['net_pnl'] * 100:>+7.2f}%"
        f"  dd={m['max_dd'] * 100:>5.2f}%"
    )


def main() -> None:
    print("=" * 78)
    print("Strategy C - Baseline B sweep on 83-day NO-CVD dataset")
    print("=" * 78)

    bars = load_strategy_c_csv(DATASET_CSV)
    feats = compute_features(bars)
    cut = int(len(feats) * TRAIN_FRAC)
    train_feats = feats[:cut]
    hold_feats = feats[cut:]
    print(f"Total feature bars: {len(feats)}")
    print(f"Train: {len(train_feats)} bars ({train_feats[0].timestamp.date()} -> {train_feats[-1].timestamp.date()})")
    print(f"Hold : {len(hold_feats)} bars ({hold_feats[0].timestamp.date()} -> {hold_feats[-1].timestamp.date()})")
    print()

    l_train = [s for s in long_scores(train_feats, include_cvd=False) if s is not None]
    s_train = [s for s in short_scores(train_feats, include_cvd=False) if s is not None]
    print(f"Train long_scores:  {len(l_train)} non-None, range [{min(l_train):.2f}, {max(l_train):.2f}]")
    print(f"Train short_scores: {len(s_train)} non-None, range [{min(s_train):.2f}, {max(s_train):.2f}]")
    print()

    best_rows: list[tuple[float, dict, dict, int, int, float]] = []

    print("=" * 78)
    header_shown = False
    for pct in PERCENTILES:
        long_thr = percentile(l_train, pct)
        short_thr = percentile(s_train, pct)

        for hold in HOLDS:
            for cooldown in COOLDOWNS:
                full_sigs = baseline_b_signals(
                    feats,
                    long_threshold=long_thr, short_threshold=short_thr,
                    include_cvd=False,
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

                best_rows.append((
                    hold_res.metrics["avg_pnl"],
                    train_res.metrics, hold_res.metrics,
                    hold, cooldown, pct,
                ))

                if header_shown:
                    print("-" * 78)
                print(f"pct={pct:<5} hold={hold} cd={cooldown}  L>={long_thr:.2f} S>={short_thr:.2f}")
                header_shown = True
                print(_fmt("TRAIN", train_res.metrics))
                print(_fmt("HOLDOUT", hold_res.metrics))

    print()
    print("=" * 78)
    print("Best holdout rows (by avg_pnl, min 20 trades):")
    print("=" * 78)
    eligible = [r for r in best_rows if r[2]["num_trades"] >= 20]
    top = sorted(eligible, key=lambda r: -r[0])[:5]
    for avg, tm, hm, hold, cd, pct in top:
        print(
            f"  pct={pct} h={hold} cd={cd}:  "
            f"HOLDOUT n={int(hm['num_trades'])} win={hm['win_rate']*100:.1f}% "
            f"avg={hm['avg_pnl']*100:+.3f}% net={hm['net_pnl']*100:+.2f}%  | "
            f"TRAIN n={int(tm['num_trades'])} win={tm['win_rate']*100:.1f}% "
            f"avg={tm['avg_pnl']*100:+.3f}%"
        )


if __name__ == "__main__":
    main()
