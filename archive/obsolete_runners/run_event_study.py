"""Run the Strategy C event study on the 4500-bar 15m dataset.

Pipeline:
    1. Load strategy_c_btcusdt_15m.csv (4500 bars, 46.9 days)
    2. Compute features (warmup drops first 95 bars → 4405 rows)
    3. For each side and z_threshold in (2.0, 2.5, 3.0):
        a. find_events on long_liq_z32 / short_liq_z32
        b. measure_forward_returns at horizons (1, 2, 4)
        c. Print base-rate summary (count, avg net, median, win rate)
        d. Bucket by each flow/context feature and print tables

Usage:
    python run_event_study.py
"""
from __future__ import annotations

import sys
from typing import Callable, Sequence

sys.path.insert(0, "src")

from data.strategy_c_dataset import load_strategy_c_csv
from data.strategy_c_features import StrategyCFeatureBar, compute_features
from research.event_study_strategy_c import (
    EventResult,
    bucket_events,
    find_events,
    measure_forward_returns,
)


DATASET_CSV = "src/data/strategy_c_btcusdt_15m.csv"
HORIZONS = (1, 2, 4)
Z_THRESHOLDS = (2.0, 2.5, 3.0)
FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001
COST_ROUND_TRIP = 2.0 * (FEE_PER_SIDE + SLIP_PER_SIDE)  # 0.12%


# ── Bucketing helpers ─────────────────────────────────────────────────


def bucket_taker_sign(f: StrategyCFeatureBar) -> str:
    return "pos" if f.taker_delta_norm >= 0 else "neg"


def bucket_cvd_sign(f: StrategyCFeatureBar) -> str:
    if f.cvd_delta is None:
        return "n/a"
    return "pos" if f.cvd_delta >= 0 else "neg"


def bucket_basis_change_sign(f: StrategyCFeatureBar) -> str:
    if f.basis_change is None:
        return "n/a"
    return "pos" if f.basis_change >= 0 else "neg"


def bucket_oi_sign(f: StrategyCFeatureBar) -> str:
    if f.oi_pct_change_z32 is None:
        return "n/a"
    return "pos" if f.oi_pct_change_z32 >= 0 else "neg"


def bucket_fr_spread_regime(f: StrategyCFeatureBar) -> str:
    z = f.fr_spread_z96
    if z is None:
        return "n/a"
    if abs(z) < 1.0:
        return "calm  (|z|<1)"
    if abs(z) < 2.0:
        return "warm  (1-2)"
    return "hot   (>2)"


def bucket_taker_z_strength(f: StrategyCFeatureBar) -> str:
    z = f.taker_delta_norm_z32
    if z is None:
        return "n/a"
    if z > 1.0:
        return "strong+"
    if z < -1.0:
        return "strong-"
    return "weak"


BUCKETERS: list[tuple[str, Callable[[StrategyCFeatureBar], str]]] = [
    ("taker sign",           bucket_taker_sign),
    ("cvd sign",             bucket_cvd_sign),
    ("basis Δ sign",         bucket_basis_change_sign),
    ("oi_z32 sign",          bucket_oi_sign),
    ("fr_spread regime",     bucket_fr_spread_regime),
    ("taker_z strength",     bucket_taker_z_strength),
]


# ── Summary printers ─────────────────────────────────────────────────


def _base_rate(results: Sequence[EventResult], horizon: int) -> dict[str, float]:
    vals = [r.fwd_returns[horizon] for r in results if horizon in r.fwd_returns]
    if not vals:
        return {"count": 0, "avg": 0.0, "median": 0.0, "win_rate": 0.0}
    n = len(vals)
    avg = sum(vals) / n
    srt = sorted(vals)
    median = srt[n // 2] if n % 2 == 1 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    wins = sum(1 for v in vals if v > 0)
    return {"count": n, "avg": avg, "median": median, "win_rate": wins / n}


def _print_base_rate_table(results: Sequence[EventResult]) -> None:
    print(f"  {'horizon':>7}  {'n':>4}  {'avg%':>8}  {'med%':>8}  {'win':>6}")
    print(f"  {'-'*7}  {'-'*4}  {'-'*8}  {'-'*8}  {'-'*6}")
    for h in HORIZONS:
        br = _base_rate(results, h)
        print(
            f"  {h:>7}  {int(br['count']):>4}  "
            f"{br['avg'] * 100:>+8.3f}  {br['median'] * 100:>+8.3f}  "
            f"{br['win_rate'] * 100:>5.1f}%"
        )


def _print_bucket_table(
    results: Sequence[EventResult],
    feats_by_idx: dict[int, StrategyCFeatureBar],
    bucket_name: str,
    key_fn: Callable[[StrategyCFeatureBar], str],
    horizon: int,
) -> None:
    buckets = bucket_events(
        results, feats_by_idx, key_fn=key_fn, horizon=horizon, cost=0.0
    )
    if not buckets:
        return
    print(f"    bucket by {bucket_name} (h={horizon}):")
    print(f"      {'key':<18} {'n':>4}  {'avg%':>8}  {'med%':>8}  {'win':>6}")
    # Sort by win rate descending for readability.
    items = sorted(
        buckets.items(),
        key=lambda kv: (-kv[1]["win_rate"], -kv[1]["count"]),
    )
    for key, stats in items:
        print(
            f"      {key:<18} {int(stats['count']):>4}  "
            f"{stats['avg'] * 100:>+8.3f}  {stats['median'] * 100:>+8.3f}  "
            f"{stats['win_rate'] * 100:>5.1f}%"
        )


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 72)
    print("Strategy C — Event Study (precision-first)")
    print("=" * 72)
    print()

    # 1. Load and compute features
    print(f"Loading dataset from {DATASET_CSV}...")
    bars = load_strategy_c_csv(DATASET_CSV)
    print(f"  {len(bars)} raw bars")
    feats = compute_features(bars)
    print(f"  {len(feats)} feature bars (warmup dropped {len(bars) - len(feats)})")
    print(f"  Range: {feats[0].timestamp.isoformat()} → {feats[-1].timestamp.isoformat()}")
    print(f"  Round-trip cost: {COST_ROUND_TRIP * 100:.3f}% (fee {FEE_PER_SIDE*100:.3f}% + slip {SLIP_PER_SIDE*100:.3f}%, ×2)")
    print()

    # feats_by_idx: index into feats list → feature bar
    feats_by_idx = {i: f for i, f in enumerate(feats)}

    # 2. Run for each side and threshold
    for side, side_name, liq_attr in [(1, "LONG ", "long_liq_z32"), (-1, "SHORT", "short_liq_z32")]:
        for z_thr in Z_THRESHOLDS:
            events = find_events(feats, side=side, z_threshold=z_thr)
            results = measure_forward_returns(
                feats, events,
                horizons=HORIZONS,
                fee_per_side=FEE_PER_SIDE,
                slippage_per_side=SLIP_PER_SIDE,
            )

            header = f"{side_name}  side={side:+d}  {liq_attr} > {z_thr:.1f}"
            print("─" * 72)
            print(f"  {header}")
            print(f"  raw events: {len(events)}    usable (horizon fits): {len(results)}")
            print("─" * 72)

            if not results:
                print("  (no events)")
                print()
                continue

            # Base rate by horizon
            _print_base_rate_table(results)
            print()

            # Bucket analyses — only for a single horizon to keep output tight.
            focus_h = 2
            for bucket_name, key_fn in BUCKETERS:
                _print_bucket_table(results, feats_by_idx, bucket_name, key_fn, focus_h)
                print()

    # 3. Final recap — show the 5 biggest "edge" slices (smallest bucket threshold)
    print("=" * 72)
    print("Summary: all events regardless of side @ z_threshold=2.0")
    print("=" * 72)
    long_events = find_events(feats, side=1, z_threshold=2.0)
    short_events = find_events(feats, side=-1, z_threshold=2.0)
    print(f"  long events (long_liq_z32 > 2.0):  {len(long_events)}")
    print(f"  short events (short_liq_z32 > 2.0): {len(short_events)}")
    print(f"  total: {len(long_events) + len(short_events)}")


if __name__ == "__main__":
    main()
