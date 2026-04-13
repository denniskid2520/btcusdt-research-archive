"""Strategy C v2 Phase 3 — multi-timeframe framework sweep.

Tests the 4h→1h→15m hierarchical framework:
    4h  = regime / direction (RSI above/below threshold)
    1h  = setup confirmation (RSI above/below threshold)
    15m = execution timing (t+1 open entry, time-stop + opposite-flip exit)

Compared against three baselines:
    - 4h-only signal (rsi_only_21 midline) on 15m execution
    - 1h-only signal (rsi_only_14 midline) on 15m execution
    - 15m execution with the MTF AND-gate rule (4h AND 1h both confirm)

All cells use the same walk-forward machinery, 0.12% round-trip, and
real funding. Execution frame is fixed at 15m — the point of Phase 3
MTF is that 15m is **execution only**, not alpha discovery.

Outputs:
    strategy_c_v2_phase3_mtf.csv
    Printed summary on stdout
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Callable

sys.path.insert(0, "src")

from adapters.base import MarketBar
from data.strategy_c_v2_features import (
    StrategyCV2Features,
    compute_features_v2,
    rsi_series,
)
from research.strategy_c_v2_backtest import run_v2_backtest
from research.strategy_c_v2_runner import (
    TimeframeData,
    build_funding_per_bar,
    combined_profit_factor,
    format_row,
    load_funding_csv,
    load_klines_csv,
    load_timeframe_data,
    max_dd_of,
    stitch_equity,
)
from research.strategy_c_v2_walk_forward import walk_forward_splits
from strategies.strategy_c_v2_mtf import (
    align_higher_to_lower,
    mtf_trend_signals,
)


# ── config ──────────────────────────────────────────────────────────


KLINES_15M = "src/data/btcusdt_15m_6year.csv"
KLINES_1H = "src/data/btcusdt_1h_6year.csv"
KLINES_4H = "src/data/btcusdt_4h_6year.csv"
FUNDING_CSV = "src/data/btcusdt_funding_5year.csv"

HOLD_BARS = (32, 64, 128)  # 8h / 16h / 32h at 15m cadence
FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001

OUTPUT_CSV = Path("strategy_c_v2_phase3_mtf.csv")


# ── helpers ─────────────────────────────────────────────────────────


def _backtest_signals_on_15m(
    label: str,
    tf15m: TimeframeData,
    signals_full: list[int],
    *,
    hold_bars: int,
    extra: dict | None = None,
) -> dict:
    """Run one signal vector on the 15m execution TimeframeData through all splits."""
    per_split_curves = []
    per_split_metrics = []
    all_pnls = []
    pos_windows = 0
    for split in tf15m.splits:
        test_bars = tf15m.bars[split.test_lo : split.test_hi]
        test_signals = signals_full[split.test_lo : split.test_hi]
        test_funding = tf15m.funding_per_bar[split.test_lo : split.test_hi]
        bt = run_v2_backtest(
            bars=test_bars,
            signals=test_signals,
            funding_per_bar=test_funding,
            hold_bars=hold_bars,
            fee_per_side=FEE_PER_SIDE,
            slip_per_side=SLIP_PER_SIDE,
        )
        per_split_curves.append(bt.equity_curve)
        per_split_metrics.append(bt.metrics)
        for t in bt.trades:
            all_pnls.append(t.net_pnl)
        if bt.metrics["compounded_return"] > 0:
            pos_windows += 1

    curve = stitch_equity(per_split_curves)
    combined_return = (curve[-1] - 1.0) if curve else 0.0
    combined_dd = max_dd_of(curve)
    num_splits = len(tf15m.splits)
    total_trades = int(sum(m["num_trades"] for m in per_split_metrics))
    pos_frac = pos_windows / num_splits if num_splits else 0.0
    avg_exposure = (
        sum(m["exposure_time"] for m in per_split_metrics) / num_splits
        if num_splits
        else 0.0
    )
    pf = combined_profit_factor(all_pnls)

    row = {
        "execution": "15m",
        "strategy": label,
        "hold_bars": hold_bars,
        "num_splits": num_splits,
        "total_oos_trades": total_trades,
        "agg_compounded_return": combined_return,
        "combined_max_dd": combined_dd,
        "combined_profit_factor": pf,
        "positive_windows_frac": pos_frac,
        "avg_exposure_time": avg_exposure,
        "enough_trades": total_trades >= 30,
    }
    if extra:
        row.update(extra)
    return row


# ── main ────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 78)
    print("Strategy C v2 Phase 3 — MTF (4h → 1h → 15m execution)")
    print("=" * 78)

    funding_records = load_funding_csv(FUNDING_CSV)
    print(f"funding records: {len(funding_records)}")

    t0 = time.time()
    print("\nLoading 15m...")
    tf15m = load_timeframe_data("15m", KLINES_15M, 0.25, funding_records)
    print(f"  15m bars: {len(tf15m.bars):,}  splits: {len(tf15m.splits)}  "
          f"({time.time() - t0:.1f}s)")

    t0 = time.time()
    print("Loading 1h...")
    bars_1h = load_klines_csv(KLINES_1H)
    features_1h = compute_features_v2(bars_1h, funding_records=funding_records, bar_hours=1.0)
    print(f"  1h bars: {len(bars_1h):,}  ({time.time() - t0:.1f}s)")

    t0 = time.time()
    print("Loading 4h...")
    bars_4h = load_klines_csv(KLINES_4H)
    features_4h = compute_features_v2(bars_4h, funding_records=funding_records, bar_hours=4.0)
    print(f"  4h bars: {len(bars_4h):,}  ({time.time() - t0:.1f}s)")

    # Compute RSI streams at the periods we want on each TF
    print("\nComputing aligned RSI streams...")
    rsi_4h_21 = rsi_series([b.close for b in bars_4h], 21)
    rsi_1h_14 = rsi_series([b.close for b in bars_1h], 14)

    # Align to 15m bar timestamps
    lower_ts = [b.timestamp for b in tf15m.bars]
    rsi_4h_aligned_21 = align_higher_to_lower(
        lower_ts,
        [b.timestamp for b in bars_4h],
        rsi_4h_21,
        higher_period=timedelta(hours=4),
    )
    rsi_1h_aligned_14 = align_higher_to_lower(
        lower_ts,
        [b.timestamp for b in bars_1h],
        rsi_1h_14,
        higher_period=timedelta(hours=1),
    )
    print("  4h/1h RSI aligned to 15m")

    rows: list[dict] = []

    # ── 4h-only baseline ─────────────────────────────────────────────
    print("\n[4h-only signal on 15m execution]")
    for hold in HOLD_BARS:
        sigs = mtf_trend_signals(
            rsi_4h_aligned_21,
            rsi_4h_aligned_21,  # using same series twice = 4h-only rule
            higher_threshold=50.0,
            lower_threshold=50.0,
        )
        row = _backtest_signals_on_15m(
            "4h_rsi21_midline",
            tf15m,
            sigs,
            hold_bars=hold,
            extra={"higher_tf": "4h", "rule": "rsi_21>50", "lower_tf": "4h_same"},
        )
        rows.append(row)
        print(format_row(row))

    # ── 1h-only baseline ─────────────────────────────────────────────
    print("\n[1h-only signal on 15m execution]")
    for hold in HOLD_BARS:
        sigs = mtf_trend_signals(
            rsi_1h_aligned_14,
            rsi_1h_aligned_14,
            higher_threshold=50.0,
            lower_threshold=50.0,
        )
        row = _backtest_signals_on_15m(
            "1h_rsi14_midline",
            tf15m,
            sigs,
            hold_bars=hold,
            extra={"higher_tf": "1h", "rule": "rsi_14>50", "lower_tf": "1h_same"},
        )
        rows.append(row)
        print(format_row(row))

    # ── MTF AND-gate: 4h rsi_21 AND 1h rsi_14 both above/below 50 ──
    print("\n[MTF AND-gate (4h rsi_21 AND 1h rsi_14) on 15m execution]")
    for hold in HOLD_BARS:
        sigs = mtf_trend_signals(
            rsi_4h_aligned_21,
            rsi_1h_aligned_14,
            higher_threshold=50.0,
            lower_threshold=50.0,
        )
        row = _backtest_signals_on_15m(
            "mtf_rsi21x14_midline",
            tf15m,
            sigs,
            hold_bars=hold,
            extra={"higher_tf": "4h", "rule": "rsi_21>50 & rsi_14>50", "lower_tf": "1h"},
        )
        rows.append(row)
        print(format_row(row))

    # ── Tighter MTF: 4h 70/30 AND 1h 50/50 ──
    print("\n[MTF tight (4h rsi_21>70 AND 1h rsi_14>50) on 15m execution]")
    for hold in HOLD_BARS:
        sigs = mtf_trend_signals(
            rsi_4h_aligned_21,
            rsi_1h_aligned_14,
            higher_threshold=70.0,
            lower_threshold=50.0,
        )
        row = _backtest_signals_on_15m(
            "mtf_rsi21(70)x14(50)",
            tf15m,
            sigs,
            hold_bars=hold,
            extra={"higher_tf": "4h", "rule": "rsi_21>70 & rsi_14>50", "lower_tf": "1h"},
        )
        rows.append(row)
        print(format_row(row))

    # ── MTF with long-only variant ──
    print("\n[MTF long-only (4h rsi_21>50 AND 1h rsi_14>50) on 15m execution]")
    for hold in HOLD_BARS:
        sigs_both = mtf_trend_signals(
            rsi_4h_aligned_21,
            rsi_1h_aligned_14,
            higher_threshold=50.0,
            lower_threshold=50.0,
        )
        sigs_long = [s if s > 0 else 0 for s in sigs_both]
        row = _backtest_signals_on_15m(
            "mtf_rsi21x14_long_only",
            tf15m,
            sigs_long,
            hold_bars=hold,
            extra={"higher_tf": "4h", "rule": "rsi_21>50 & rsi_14>50", "lower_tf": "1h", "side": "long"},
        )
        rows.append(row)
        print(format_row(row))

    # Write CSV
    if rows:
        keys: list[str] = []
        seen = set()
        for r in rows:
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
        with OUTPUT_CSV.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=keys)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        print(f"\nWrote {OUTPUT_CSV} ({len(rows)} rows)")

    # Summary
    print("\n" + "=" * 78)
    print("SUMMARY — ranked by OOS compounded return (enough trades only)")
    print("=" * 78)
    ranked = sorted(
        [r for r in rows if r["enough_trades"]],
        key=lambda r: r["agg_compounded_return"],
        reverse=True,
    )
    for r in ranked:
        print(format_row(r))


if __name__ == "__main__":
    main()
