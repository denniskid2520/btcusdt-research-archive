"""Run the event study on the 83-day NO-CVD dataset.

Same design as run_event_study.py but against the longer extended dataset.
The cvd_delta bucket is removed (no pair_cvd data available).
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


DATASET_CSV = "src/data/strategy_c_btcusdt_15m_nocvd.csv"
HORIZONS = (1, 2, 4)
Z_THRESHOLDS = (2.0, 2.5, 3.0)
FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001
COST_ROUND_TRIP = 2.0 * (FEE_PER_SIDE + SLIP_PER_SIDE)


def bucket_taker_sign(f: StrategyCFeatureBar) -> str:
    return "pos" if f.taker_delta_norm >= 0 else "neg"


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
        return "calm"
    if abs(z) < 2.0:
        return "warm"
    return "hot"


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
    ("taker sign",       bucket_taker_sign),
    ("basis_chg sign",   bucket_basis_change_sign),
    ("oi_z32 sign",      bucket_oi_sign),
    ("fr_spread regime", bucket_fr_spread_regime),
    ("taker_z strength", bucket_taker_z_strength),
]


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


def _print_base_rate(results: Sequence[EventResult]) -> None:
    print(f"  {'h':>3}  {'n':>4}  {'avg%':>8}  {'med%':>8}  {'win':>6}")
    print(f"  {'-'*3}  {'-'*4}  {'-'*8}  {'-'*8}  {'-'*6}")
    for h in HORIZONS:
        br = _base_rate(results, h)
        print(
            f"  {h:>3}  {int(br['count']):>4}  "
            f"{br['avg'] * 100:>+8.3f}  {br['median'] * 100:>+8.3f}  "
            f"{br['win_rate'] * 100:>5.1f}%"
        )


def _print_bucket(
    results: Sequence[EventResult],
    feats_by_idx: dict[int, StrategyCFeatureBar],
    bucket_name: str,
    key_fn: Callable[[StrategyCFeatureBar], str],
    horizon: int,
) -> None:
    buckets = bucket_events(results, feats_by_idx, key_fn=key_fn, horizon=horizon, cost=0.0)
    if not buckets:
        return
    print(f"    {bucket_name} (h={horizon}):")
    items = sorted(buckets.items(), key=lambda kv: (-kv[1]["win_rate"], -kv[1]["count"]))
    for key, stats in items:
        print(
            f"      {key:<12} n={int(stats['count']):>4}  "
            f"avg={stats['avg'] * 100:>+7.3f}%  "
            f"med={stats['median'] * 100:>+7.3f}%  "
            f"win={stats['win_rate'] * 100:>5.1f}%"
        )


def main() -> None:
    print("=" * 78)
    print("Strategy C - Event Study on 83-day NO-CVD dataset")
    print("=" * 78)
    print()

    bars = load_strategy_c_csv(DATASET_CSV)
    feats = compute_features(bars)
    print(f"  {len(bars)} raw bars   -> {len(feats)} feature bars")
    print(f"  {feats[0].timestamp.isoformat()} -> {feats[-1].timestamp.isoformat()}")
    print(f"  Round-trip cost: {COST_ROUND_TRIP * 100:.3f}%")
    print()

    feats_by_idx = {i: f for i, f in enumerate(feats)}

    for side, side_name in [(1, "LONG "), (-1, "SHORT")]:
        for z_thr in Z_THRESHOLDS:
            events = find_events(feats, side=side, z_threshold=z_thr)
            results = measure_forward_returns(
                feats, events,
                horizons=HORIZONS,
                fee_per_side=FEE_PER_SIDE,
                slippage_per_side=SLIP_PER_SIDE,
            )

            header = f"{side_name}  side={side:+d}  z>{z_thr:.1f}"
            print("-" * 78)
            print(f"  {header}  raw={len(events)} usable={len(results)}")
            print("-" * 78)

            if not results:
                print("  (no events)")
                print()
                continue

            _print_base_rate(results)
            print()

            focus_h = 2
            for bucket_name, key_fn in BUCKETERS:
                _print_bucket(results, feats_by_idx, bucket_name, key_fn, focus_h)
                print()


if __name__ == "__main__":
    main()
