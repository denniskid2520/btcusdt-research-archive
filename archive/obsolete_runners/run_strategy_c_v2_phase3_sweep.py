"""Strategy C v2 Phase 3 — robustness, directional, and funding-filter sweeps.

Runs three sweeps on the Phase 2 winning cells:

1. **Robustness** — parameter perturbation around the winners
   - 4h rsi_only_30 hold=16: RSI length {21, 30, 34, 42} × hold {8, 12, 16, 24, 32}
   - 1h rsi_and_macd_14 hold=32: RSI length {7, 14, 21} × hold {16, 24, 32, 48}

2. **Directional decomposition** — long-only / short-only / long-short on
   each robustness cell. Answers "where does the edge come from under perp
   funding costs?"

3. **Funding-aware filter** — layer an entry veto on the best cells. Tests
   max_long_funding thresholds {0.0001, 0.0003, 0.0005} (both raw rate and
   cum_24h variants), max_short_funding mirrors, and the unfiltered base.

Data is loaded once per timeframe and reused across all three sweeps.

Outputs:
    strategy_c_v2_phase3_robustness.csv    — sweeps 1 + 2 combined
    strategy_c_v2_phase3_funding_filter.csv — sweep 3

Run:
    python run_strategy_c_v2_phase3_sweep.py
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, "src")

from data.strategy_c_v2_features import StrategyCV2Features, rsi_series
from research.strategy_c_v2_runner import (
    TimeframeData,
    format_row,
    load_funding_csv,
    load_timeframe_data,
    run_cell,
)
from strategies.strategy_c_v2_filters import (
    apply_funding_filter,
    apply_side_filter,
)
from strategies.strategy_c_v2_literature import (
    rsi_and_macd_signals,
    rsi_only_signals,
)


# ── config ──────────────────────────────────────────────────────────


TIMEFRAMES = [
    # (name, klines_csv, bar_hours)
    ("1h", "src/data/btcusdt_1h_6year.csv", 1.0),
    ("4h", "src/data/btcusdt_4h_6year.csv", 4.0),
]
FUNDING_CSV = "src/data/btcusdt_funding_5year.csv"

ROBUSTNESS_CSV = Path("strategy_c_v2_phase3_robustness.csv")
FUNDING_FILTER_CSV = Path("strategy_c_v2_phase3_funding_filter.csv")

FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001

SIDES = ("long", "short", "both")


# ── signal factories ────────────────────────────────────────────────
#
# Important: the underlying rsi_only_signals / rsi_and_macd_signals only
# read `f.rsi_14` / `f.rsi_30`. Any period outside {14, 30} must be
# supplied via `rsi_override` (pre-computed). We cache per-period RSI
# series on each TimeframeData to avoid recomputing the same series
# across sibling cells.


_RSI_CACHE: dict[tuple[int, int], list[float | None]] = {}


def _get_rsi_override(features, period: int) -> list[float | None] | None:
    """Return a cached RSI series for `period`, or None if not needed.

    Uses id(features) + period as the cache key — safe because the
    TimeframeData bundles are held for the whole sweep.
    """
    if period in (14, 30):
        return None  # strategy reads from the feature field directly
    key = (id(features), period)
    if key not in _RSI_CACHE:
        closes = [f.close for f in features]
        _RSI_CACHE[key] = rsi_series(closes, period)
    return _RSI_CACHE[key]


def make_rsi_only_fn(
    *,
    period: int,
    upper: float = 70.0,
    lower: float = 30.0,
    side: str = "both",
    funding_filter: dict | None = None,
) -> Callable:
    def fn(features):
        override = _get_rsi_override(features, period)
        sigs = rsi_only_signals(
            features,
            rsi_period=period,
            upper=upper,
            lower=lower,
            rsi_override=override,
        )
        sigs = apply_side_filter(sigs, side=side)  # type: ignore[arg-type]
        if funding_filter is not None:
            sigs = apply_funding_filter(sigs, features, **funding_filter)
        return sigs
    return fn


def make_rsi_and_macd_fn(
    *,
    period: int,
    upper: float = 70.0,
    lower: float = 30.0,
    side: str = "both",
    funding_filter: dict | None = None,
) -> Callable:
    def fn(features):
        override = _get_rsi_override(features, period)
        sigs = rsi_and_macd_signals(
            features,
            rsi_period=period,
            upper=upper,
            lower=lower,
            rsi_override=override,
        )
        sigs = apply_side_filter(sigs, side=side)  # type: ignore[arg-type]
        if funding_filter is not None:
            sigs = apply_funding_filter(sigs, features, **funding_filter)
        return sigs
    return fn


# ── sweep 1 + 2: robustness × directional ──────────────────────────


def build_robustness_cells() -> list[tuple[str, dict]]:
    """List of (tf_name, spec) cells for the robustness+directional sweep."""
    cells: list[tuple[str, dict]] = []

    # 4h: rsi_only_{period} × hold × side
    for period in (21, 30, 34, 42):
        for hold in (8, 12, 16, 24, 32):
            for side in SIDES:
                name = f"rsi_only_{period}_side_{side}"
                cells.append((
                    "4h",
                    {
                        "name": name,
                        "family": "rsi_only",
                        "period": period,
                        "hold": hold,
                        "side": side,
                        "fn": make_rsi_only_fn(period=period, side=side),
                    },
                ))

    # 1h: rsi_and_macd_{period} × hold × side
    for period in (7, 14, 21):
        for hold in (16, 24, 32, 48):
            for side in SIDES:
                name = f"rsi_and_macd_{period}_side_{side}"
                cells.append((
                    "1h",
                    {
                        "name": name,
                        "family": "rsi_and_macd",
                        "period": period,
                        "hold": hold,
                        "side": side,
                        "fn": make_rsi_and_macd_fn(period=period, side=side),
                    },
                ))

    # Also run rsi_only on 1h and rsi_and_macd on 4h for cross-family sanity
    for period in (14, 30):
        for hold in (16, 24, 32):
            for side in SIDES:
                cells.append((
                    "1h",
                    {
                        "name": f"rsi_only_{period}_side_{side}",
                        "family": "rsi_only",
                        "period": period,
                        "hold": hold,
                        "side": side,
                        "fn": make_rsi_only_fn(period=period, side=side),
                    },
                ))
    for period in (14, 30):
        for hold in (4, 8, 16):
            for side in SIDES:
                cells.append((
                    "4h",
                    {
                        "name": f"rsi_and_macd_{period}_side_{side}",
                        "family": "rsi_and_macd",
                        "period": period,
                        "hold": hold,
                        "side": side,
                        "fn": make_rsi_and_macd_fn(period=period, side=side),
                    },
                ))

    return cells


# ── sweep 3: funding filter on top of best-candidate cells ─────────


# Anchor cells to try funding filter on (chosen by hand from Phase 2)
FUNDING_BASE_CELLS = [
    # (tf, family, period, hold)
    ("4h", "rsi_only",     30, 16),
    ("4h", "rsi_only",     30,  8),
    ("4h", "rsi_and_macd", 14,  4),
    ("1h", "rsi_and_macd", 14, 32),
    ("1h", "rsi_only",     14, 32),
    ("1h", "rsi_only",     30,  8),
]

# Filter variants to sweep
FUNDING_FILTERS = [
    {"label": "none",                     "filter": None},
    {"label": "long>0.0001",              "filter": {"max_long_funding": 0.0001}},
    {"label": "long>0.0003",              "filter": {"max_long_funding": 0.0003}},
    {"label": "long>0.0005",              "filter": {"max_long_funding": 0.0005}},
    {"label": "short<-0.0001",            "filter": {"min_short_funding": -0.0001}},
    {"label": "short<-0.0003",            "filter": {"min_short_funding": -0.0003}},
    {"label": "both 0.0003",              "filter": {"max_long_funding": 0.0003, "min_short_funding": -0.0003}},
    {"label": "both 0.0001",              "filter": {"max_long_funding": 0.0001, "min_short_funding": -0.0001}},
    {"label": "cum24h long>0.0005",       "filter": {"max_long_funding": 0.0005, "use_cum_24h": True}},
    {"label": "cum24h both 0.0005",       "filter": {"max_long_funding": 0.0005, "min_short_funding": -0.0005, "use_cum_24h": True}},
]


def build_funding_filter_cells() -> list[tuple[str, dict]]:
    cells: list[tuple[str, dict]] = []
    for tf, family, period, hold in FUNDING_BASE_CELLS:
        for variant in FUNDING_FILTERS:
            label = variant["label"]
            ff = variant["filter"]
            if family == "rsi_only":
                fn = make_rsi_only_fn(period=period, side="both", funding_filter=ff)
            else:
                fn = make_rsi_and_macd_fn(period=period, side="both", funding_filter=ff)
            cells.append((
                tf,
                {
                    "name": f"{family}_{period}_filter_{label.replace(' ', '_')}",
                    "family": family,
                    "period": period,
                    "hold": hold,
                    "side": "both",
                    "filter": label,
                    "fn": fn,
                },
            ))
    return cells


# ── main ────────────────────────────────────────────────────────────


def run_sweep(
    tf_data: dict[str, TimeframeData],
    cells: list[tuple[str, dict]],
    *,
    title: str,
) -> list[dict]:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}\n")
    rows: list[dict] = []
    cur_tf = None
    for tf_name, spec in cells:
        if tf_name != cur_tf:
            cur_tf = tf_name
            print(f"\n[{tf_name}]")
        tf = tf_data[tf_name]
        extras = {
            "family": spec.get("family"),
            "period": spec.get("period"),
            "side": spec.get("side"),
        }
        if "filter" in spec:
            extras["filter"] = spec["filter"]
        row = run_cell(
            name=spec["name"],
            tf=tf,
            signal_fn=spec["fn"],
            hold_bars=spec["hold"],
            fee_per_side=FEE_PER_SIDE,
            slip_per_side=SLIP_PER_SIDE,
            extra_fields=extras,
        )
        rows.append(row)
        print(format_row(row))
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    # Collect all field names across rows
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
    print("Strategy C v2 Phase 3 — robustness + directional + funding filter")
    print(f"Cost: fee={FEE_PER_SIDE * 100:.3f}% slip={SLIP_PER_SIDE * 100:.3f}%"
          f"  (round-trip {2 * (FEE_PER_SIDE + SLIP_PER_SIDE) * 100:.3f}%)")
    print("=" * 78)

    funding_records = load_funding_csv(FUNDING_CSV)
    print(f"funding records: {len(funding_records)}")

    tf_data: dict[str, TimeframeData] = {}
    for name, path, bar_hours in TIMEFRAMES:
        t0 = time.time()
        print(f"\nLoading {name}: {path}")
        tf_data[name] = load_timeframe_data(name, path, bar_hours, funding_records)
        print(f"  bars: {len(tf_data[name].bars):,}  "
              f"features: {len(tf_data[name].features):,}  "
              f"splits: {len(tf_data[name].splits)}  "
              f"({time.time() - t0:.1f}s)")

    # Sweep 1+2: Robustness × directional
    robust_cells = build_robustness_cells()
    print(f"\nRobustness+directional sweep: {len(robust_cells)} cells")
    robust_rows = run_sweep(
        tf_data,
        robust_cells,
        title="ROBUSTNESS × DIRECTIONAL",
    )
    write_csv(ROBUSTNESS_CSV, robust_rows)

    # Sweep 3: Funding filter
    filter_cells = build_funding_filter_cells()
    print(f"\nFunding filter sweep: {len(filter_cells)} cells")
    filter_rows = run_sweep(
        tf_data,
        filter_cells,
        title="FUNDING FILTER",
    )
    write_csv(FUNDING_FILTER_CSV, filter_rows)

    # Summary
    print(f"\n{'=' * 78}")
    print("SUMMARY — top 10 robustness+directional cells by OOS return")
    print("=" * 78)
    ranked = sorted(
        [r for r in robust_rows if r["enough_trades"]],
        key=lambda r: r["agg_compounded_return"],
        reverse=True,
    )[:10]
    for r in ranked:
        print(format_row(r))

    print(f"\n{'=' * 78}")
    print("SUMMARY — top 10 funding-filter cells by OOS return")
    print("=" * 78)
    ranked_f = sorted(
        [r for r in filter_rows if r["enough_trades"]],
        key=lambda r: r["agg_compounded_return"],
        reverse=True,
    )[:10]
    for r in ranked_f:
        print(format_row(r))


if __name__ == "__main__":
    main()
