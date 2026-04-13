"""Strategy C v2 Phase 3 — Track B Coinglass overlay test.

Purpose: does adding Coinglass features as an ENTRY VETO on top of a
Track A candidate produce measurable lift on the 83-day overlap window?

Per Phase 3 brief:
    "Use Coinglass only as an overlay on top of the best Track A
    candidates. Use them as entry veto / regime veto / exit refinement,
    not as the primary trigger."

Honest caveats up front:
- The Strategy C nocvd dataset is 83 days of 15m bars (7,967 rows,
  2026-01-11 → 2026-04-03). This is ~1/8 of one 6-month walk-forward
  window and cannot support the 24m/6m rolling validation Track A uses.
- All results below are SINGLE-SLICE point estimates on the 83-day
  window, split 70/30 temporally. Treat as directional evidence, not
  as OOS lift measurement.
- The dataset has open+close but no high/low, so we synthesize
  high=max(open,close)*1.001, low=min(open,close)*0.999. That's enough
  for the backtester (which uses open for entry/exit).
- The 4h rule families (Phase 2/3 winners) don't fit on 83 days of 15m
  cleanly, so we use 1h-derived signals (RSI on 1h-resampled closes)
  for the baseline and apply Coinglass vetoes on top.

Overlay filters tested (all applied at the 15m bar level):
    - `liq_imbalance > 0.3` blocks shorts (lots of short-liqs → likely
      long squeeze up, skip shorts)
    - `liq_imbalance < -0.3` blocks longs (lots of long-liqs → likely
      short cascade down, skip longs)
    - `funding_oi_weighted > 0.0005` blocks longs (hot funding regime)
    - `taker_delta_usd < 0` blocks longs (sellers in control)
    - Combinations of the above

Outputs:
    strategy_c_v2_phase3_track_b.csv
    Printed summary on stdout
"""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "src")

from adapters.base import MarketBar
from data.strategy_c_v2_features import compute_features_v2, rsi_series
from research.strategy_c_v2_backtest import (
    NO_LOSS_PROFIT_FACTOR,
    run_v2_backtest,
)
from research.strategy_c_v2_runner import combined_profit_factor, max_dd_of
from research.strategy_c_sweep import temporal_split
from strategies.strategy_c_v2_literature import rsi_only_signals
from strategies.strategy_c_v2_filters import apply_side_filter


TRACK_B_CSV = "src/data/strategy_c_btcusdt_15m_nocvd.csv"
OUTPUT_CSV = Path("strategy_c_v2_phase3_track_b.csv")

FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001

HOLD_BARS_CHOICES = (32, 64, 128)  # 8h, 16h, 32h at 15m cadence


@dataclass
class TrackBBar:
    """Joint OHLCV + Coinglass feature row for the 83-day dataset."""
    timestamp: datetime
    open: float
    close: float
    high: float
    low: float
    volume: float
    oi_pct_change: float
    funding: float
    long_liq_usd: float
    short_liq_usd: float
    liq_imbalance: float
    taker_delta_usd: float
    basis: float
    funding_oi_weighted: float
    stablecoin_oi: float


def load_track_b(path: str) -> list[TrackBBar]:
    out: list[TrackBBar] = []
    with open(path, "r") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            o = float(row["open"])
            c = float(row["close"])
            out.append(
                TrackBBar(
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    open=o,
                    close=c,
                    high=max(o, c) * 1.001,  # synthesized
                    low=min(o, c) * 0.999,
                    volume=float(row["volume"]),
                    oi_pct_change=float(row["oi_pct_change"]),
                    funding=float(row["funding"]),
                    long_liq_usd=float(row["long_liq_usd"]),
                    short_liq_usd=float(row["short_liq_usd"]),
                    liq_imbalance=float(row["liq_imbalance"]),
                    taker_delta_usd=float(row["taker_delta_usd"]),
                    basis=float(row["basis"]),
                    funding_oi_weighted=float(row["funding_oi_weighted"]),
                    stablecoin_oi=float(row["stablecoin_oi"]),
                )
            )
    return out


def to_market_bars(rows: list[TrackBBar]) -> list[MarketBar]:
    return [
        MarketBar(
            timestamp=r.timestamp,
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            volume=r.volume,
        )
        for r in rows
    ]


# ── overlay filter ──────────────────────────────────────────────────


def apply_coinglass_overlay(
    signals: list[int],
    rows: list[TrackBBar],
    *,
    block_long_if_liq_imbalance_below: float | None = None,
    block_short_if_liq_imbalance_above: float | None = None,
    block_long_if_funding_oi_w_above: float | None = None,
    block_long_if_taker_delta_negative: bool = False,
) -> list[int]:
    """Apply Coinglass-based vetoes on an existing signal stream."""
    if len(signals) != len(rows):
        raise ValueError("length mismatch")
    out: list[int] = []
    for s, r in zip(signals, rows):
        if s == 0:
            out.append(0)
            continue
        blocked = False
        if s > 0:  # long veto checks
            if (
                block_long_if_liq_imbalance_below is not None
                and r.liq_imbalance < block_long_if_liq_imbalance_below
            ):
                blocked = True
            if (
                block_long_if_funding_oi_w_above is not None
                and r.funding_oi_weighted > block_long_if_funding_oi_w_above
            ):
                blocked = True
            if block_long_if_taker_delta_negative and r.taker_delta_usd < 0:
                blocked = True
        else:  # short veto checks
            if (
                block_short_if_liq_imbalance_above is not None
                and r.liq_imbalance > block_short_if_liq_imbalance_above
            ):
                blocked = True
        out.append(0 if blocked else s)
    return out


# ── backtest wrapper ────────────────────────────────────────────────


def run_cell(
    label: str,
    bars: list[MarketBar],
    signals: list[int],
    *,
    hold_bars: int,
    extra: dict | None = None,
) -> dict:
    funding_per_bar = [0.0] * len(bars)  # 83-day Track B ignores funding aligner — see caveats
    bt = run_v2_backtest(
        bars=bars,
        signals=signals,
        funding_per_bar=funding_per_bar,
        hold_bars=hold_bars,
        fee_per_side=FEE_PER_SIDE,
        slip_per_side=SLIP_PER_SIDE,
    )
    trades = bt.trades
    pnls = [t.net_pnl for t in trades]
    curve = bt.equity_curve
    combined_return = (curve[-1] - 1.0) if curve else 0.0
    dd = max_dd_of(curve)
    pf = combined_profit_factor(pnls)
    row = {
        "label": label,
        "hold_bars": hold_bars,
        "num_trades": len(trades),
        "return": combined_return,
        "max_dd": dd,
        "profit_factor": pf if pf < NO_LOSS_PROFIT_FACTOR else float("inf"),
    }
    if extra:
        row.update(extra)
    return row


# ── main ────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 78)
    print("Strategy C v2 Phase 3 — Track B Coinglass overlay test")
    print("=" * 78)
    print("HONEST CAVEAT: 83-day single-slice point estimate. NOT an OOS measurement.")
    print("               Use as directional evidence for the primary recommendation, not as proof.")
    print("=" * 78)

    rows = load_track_b(TRACK_B_CSV)
    print(f"\nLoaded {len(rows)} rows from {TRACK_B_CSV}")
    print(f"  range: {rows[0].timestamp} → {rows[-1].timestamp}")
    print(f"  days:  {(rows[-1].timestamp - rows[0].timestamp).days}")

    # Temporal 70/30 split for "test" estimation
    train_rows, test_rows = temporal_split(rows, train_frac=0.7)
    print(f"\nTrain slice: {len(train_rows)} bars  ({train_rows[0].timestamp} → {train_rows[-1].timestamp})")
    print(f"Test slice:  {len(test_rows)} bars  ({test_rows[0].timestamp} → {test_rows[-1].timestamp})")

    # Compute features on the test slice only (we're not fitting anything — just running rules)
    test_bars = to_market_bars(test_rows)
    features = compute_features_v2(test_bars, bar_hours=0.25)

    # Baseline rule: rsi_only_14 long-only on 15m execution
    base_signals = rsi_only_signals(features, rsi_period=14, upper=70.0, lower=30.0)
    base_long = apply_side_filter(base_signals, side="long")
    base_both = base_signals
    base_short = apply_side_filter(base_signals, side="short")

    results: list[dict] = []

    print("\n[Baseline: rsi_only_14 on 15m execution, test slice of 83-day window]")
    for side_label, sigs in [("both", base_both), ("long", base_long), ("short", base_short)]:
        for hold in HOLD_BARS_CHOICES:
            row = run_cell(
                f"baseline_rsi14_{side_label}",
                test_bars,
                sigs,
                hold_bars=hold,
                extra={"side": side_label, "overlay": "none"},
            )
            results.append(row)
            print(
                f"  baseline rsi14 {side_label:<5} hold={hold:>3}  "
                f"n={row['num_trades']:>4}  ret={row['return'] * 100:>+7.2f}%  "
                f"dd={row['max_dd'] * 100:>5.2f}%  pf={row['profit_factor']:>6.2f}"
            )

    # Overlay 1: block shorts when liq_imbalance > 0.3
    print("\n[Overlay: block shorts when liq_imbalance > 0.3 (short-side cascade)]")
    ov_signals = apply_coinglass_overlay(
        base_both,
        test_rows,
        block_short_if_liq_imbalance_above=0.3,
    )
    for hold in HOLD_BARS_CHOICES:
        row = run_cell(
            "overlay_short_liqimb>0.3",
            test_bars,
            ov_signals,
            hold_bars=hold,
            extra={"side": "both", "overlay": "short_liqimb>0.3"},
        )
        results.append(row)
        print(
            f"  overlay block_short_liq>0.3   hold={hold:>3}  "
            f"n={row['num_trades']:>4}  ret={row['return'] * 100:>+7.2f}%  "
            f"dd={row['max_dd'] * 100:>5.2f}%  pf={row['profit_factor']:>6.2f}"
        )

    # Overlay 2: block longs when liq_imbalance < -0.3
    print("\n[Overlay: block longs when liq_imbalance < -0.3 (long-side cascade)]")
    ov_signals = apply_coinglass_overlay(
        base_both,
        test_rows,
        block_long_if_liq_imbalance_below=-0.3,
    )
    for hold in HOLD_BARS_CHOICES:
        row = run_cell(
            "overlay_long_liqimb<-0.3",
            test_bars,
            ov_signals,
            hold_bars=hold,
            extra={"side": "both", "overlay": "long_liqimb<-0.3"},
        )
        results.append(row)
        print(
            f"  overlay block_long_liq<-0.3   hold={hold:>3}  "
            f"n={row['num_trades']:>4}  ret={row['return'] * 100:>+7.2f}%  "
            f"dd={row['max_dd'] * 100:>5.2f}%  pf={row['profit_factor']:>6.2f}"
        )

    # Overlay 3: block longs when funding_oi_weighted > 0.0005
    print("\n[Overlay: block longs when funding_oi_weighted > 0.0005 (hot funding)]")
    ov_signals = apply_coinglass_overlay(
        base_both,
        test_rows,
        block_long_if_funding_oi_w_above=0.0005,
    )
    for hold in HOLD_BARS_CHOICES:
        row = run_cell(
            "overlay_long_fundOI>0.0005",
            test_bars,
            ov_signals,
            hold_bars=hold,
            extra={"side": "both", "overlay": "long_fundOI>0.0005"},
        )
        results.append(row)
        print(
            f"  overlay block_long_fundOI>5e-4 hold={hold:>3}  "
            f"n={row['num_trades']:>4}  ret={row['return'] * 100:>+7.2f}%  "
            f"dd={row['max_dd'] * 100:>5.2f}%  pf={row['profit_factor']:>6.2f}"
        )

    # Overlay 4: combined asymmetric veto
    print("\n[Overlay: asymmetric — block short on liq_imb>0.3 AND long on fundOI>0.0005]")
    ov_signals = apply_coinglass_overlay(
        base_both,
        test_rows,
        block_short_if_liq_imbalance_above=0.3,
        block_long_if_funding_oi_w_above=0.0005,
    )
    for hold in HOLD_BARS_CHOICES:
        row = run_cell(
            "overlay_asymmetric",
            test_bars,
            ov_signals,
            hold_bars=hold,
            extra={"side": "both", "overlay": "asymmetric"},
        )
        results.append(row)
        print(
            f"  overlay asymmetric             hold={hold:>3}  "
            f"n={row['num_trades']:>4}  ret={row['return'] * 100:>+7.2f}%  "
            f"dd={row['max_dd'] * 100:>5.2f}%  pf={row['profit_factor']:>6.2f}"
        )

    # Write CSV
    if results:
        keys: list[str] = []
        seen = set()
        for r in results:
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
        with OUTPUT_CSV.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=keys)
            writer.writeheader()
            for row in results:
                writer.writerow(row)
        print(f"\nWrote {OUTPUT_CSV} ({len(results)} rows)")

    # Summary: baseline vs each overlay at hold=64 (middle value)
    print("\n" + "=" * 78)
    print("DELTA SUMMARY (hold=64, test slice only, baseline = rsi_only_14 both sides)")
    print("=" * 78)
    bh = 64
    base_both_h = next(r for r in results if r["label"] == "baseline_rsi14_both" and r["hold_bars"] == bh)
    print(f"  baseline both            ret={base_both_h['return'] * 100:>+7.2f}%  n={base_both_h['num_trades']:>4}  dd={base_both_h['max_dd'] * 100:>5.2f}%")
    for label_prefix in ("overlay_short_liqimb", "overlay_long_liqimb", "overlay_long_fundOI", "overlay_asymmetric"):
        ov = next((r for r in results if r["label"].startswith(label_prefix) and r["hold_bars"] == bh), None)
        if ov:
            delta = (ov["return"] - base_both_h["return"]) * 100
            print(
                f"  {ov['label']:<30} ret={ov['return'] * 100:>+7.2f}%  "
                f"n={ov['num_trades']:>4}  dd={ov['max_dd'] * 100:>5.2f}%  "
                f"Δ={delta:>+6.2f}pp"
            )


if __name__ == "__main__":
    main()
