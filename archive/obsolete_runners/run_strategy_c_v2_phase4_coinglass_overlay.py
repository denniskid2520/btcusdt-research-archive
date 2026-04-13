"""Strategy C v2 Phase 4 — Coinglass overlay test on 4h candidates.

Per Phase 4 brief: test Coinglass only on top of the best Track A
candidates. Use the 4h execution frame (not 15m — Phase 3 showed 15m
with persistent signals is cost-dominated). Aggregate the 15m Coinglass
features up to 4h buckets via time-window grouping, then layer overlays
on Candidate A's signal stream.

Honest caveats:
- Coinglass data only covers 2026-01-11 → 2026-04-03 (83 days, ~498 4h
  bars). This is a single-slice point estimate, NOT an OOS measurement.
- A 24m train / 6m test walk-forward cannot run on 83 days. We compute
  metrics over the full slice as a single window.
- Results below are directional evidence for the final recommendation,
  not proof of lift.

Overlays tested (all applied at the 4h bar level):
    1. block_short if 4h avg(liq_imbalance) > 0.3
    2. block_long  if 4h avg(funding_oi_weighted) > 0.0005
    3. block_short if 4h avg(funding_oi_weighted) < -0.0005
       (mirror of the Phase 3 short-funding veto)
    4. block_long  if 4h sum(taker_delta_usd) < 0 (sellers in control)
    5. asymmetric: #1 + #3 (the Phase 3 short-veto pattern)

For each overlay we report: trade count, compounded return, DD, and the
delta vs the unfiltered baseline.
"""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, "src")

from adapters.base import MarketBar
from data.strategy_c_v2_features import compute_features_v2, rsi_series
from research.strategy_c_v2_backtest import (
    NO_LOSS_PROFIT_FACTOR,
    run_v2_backtest,
)
from research.strategy_c_v2_runner import (
    build_funding_per_bar,
    combined_profit_factor,
    load_funding_csv,
    load_klines_csv,
    max_dd_of,
)
from strategies.strategy_c_v2_literature import rsi_only_signals


KLINES_4H = "src/data/btcusdt_4h_6year.csv"
FUNDING_CSV = "src/data/btcusdt_funding_5year.csv"
TRACK_B_15M = "src/data/strategy_c_btcusdt_15m_nocvd.csv"
OUTPUT_CSV = Path("strategy_c_v2_phase4_coinglass_overlay.csv")

FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001


# ── Coinglass 15m → 4h aggregation ──────────────────────────────────


@dataclass
class Coinglass4hBar:
    """Aggregated Coinglass features over a 4h bar period."""
    timestamp: datetime  # 4h bar open time
    avg_oi_pct_change: float
    avg_funding_oi_weighted: float
    avg_liq_imbalance: float
    sum_long_liq_usd: float
    sum_short_liq_usd: float
    sum_taker_delta_usd: float
    stablecoin_oi_pct_change: float  # close-to-close over the 4h


def load_coinglass_15m_aggregated_to_4h(path: str) -> list[Coinglass4hBar]:
    """Load the 15m Coinglass CSV and bucket it into 4h aggregates.

    4h buckets align to 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC
    (matching Binance 4h kline boundaries). Each bucket contains up to
    16 consecutive 15m rows.
    """
    buckets: dict[datetime, list[dict]] = {}
    with open(path, "r") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ts = datetime.fromisoformat(row["timestamp"])
            # Floor to 4h boundary
            bucket_hour = (ts.hour // 4) * 4
            bucket = ts.replace(hour=bucket_hour, minute=0, second=0, microsecond=0)
            buckets.setdefault(bucket, []).append(row)

    out: list[Coinglass4hBar] = []
    for bucket_ts in sorted(buckets):
        rows = buckets[bucket_ts]
        if len(rows) < 4:  # need at least a few 15m rows for a meaningful aggregate
            continue
        oi_pct = sum(float(r["oi_pct_change"]) for r in rows) / len(rows)
        fund_oiw = sum(float(r["funding_oi_weighted"]) for r in rows) / len(rows)
        liq_imb = sum(float(r["liq_imbalance"]) for r in rows) / len(rows)
        long_liq = sum(float(r["long_liq_usd"]) for r in rows)
        short_liq = sum(float(r["short_liq_usd"]) for r in rows)
        taker_d = sum(float(r["taker_delta_usd"]) for r in rows)
        stable_open = float(rows[0]["stablecoin_oi"])
        stable_close = float(rows[-1]["stablecoin_oi"])
        stable_pct = (
            (stable_close - stable_open) / stable_open if stable_open > 0 else 0.0
        )
        out.append(
            Coinglass4hBar(
                timestamp=bucket_ts,
                avg_oi_pct_change=oi_pct,
                avg_funding_oi_weighted=fund_oiw,
                avg_liq_imbalance=liq_imb,
                sum_long_liq_usd=long_liq,
                sum_short_liq_usd=short_liq,
                sum_taker_delta_usd=taker_d,
                stablecoin_oi_pct_change=stable_pct,
            )
        )
    return out


# ── Candidate A rule for the 4h slice ───────────────────────────────


def candidate_a_signals(features) -> list[int]:
    closes = [f.close for f in features]
    rsi_21 = rsi_series(closes, 21)
    return rsi_only_signals(
        features,
        rsi_period=21,
        upper=70.0,
        lower=30.0,
        rsi_override=rsi_21,
    )


def apply_overlay(
    signals: list[int],
    cg_bars: list[Coinglass4hBar | None],
    *,
    block_short_if_liq_imb_above: float | None = None,
    block_long_if_fund_oiw_above: float | None = None,
    block_short_if_fund_oiw_below: float | None = None,
    block_long_if_taker_delta_negative: bool = False,
) -> list[int]:
    """Apply Coinglass overlay vetoes on an existing 4h signal stream."""
    assert len(signals) == len(cg_bars)
    out: list[int] = []
    for s, cg in zip(signals, cg_bars):
        if s == 0 or cg is None:
            out.append(s)
            continue
        blocked = False
        if s > 0:
            if (
                block_long_if_fund_oiw_above is not None
                and cg.avg_funding_oi_weighted > block_long_if_fund_oiw_above
            ):
                blocked = True
            if block_long_if_taker_delta_negative and cg.sum_taker_delta_usd < 0:
                blocked = True
        else:
            if (
                block_short_if_liq_imb_above is not None
                and cg.avg_liq_imbalance > block_short_if_liq_imb_above
            ):
                blocked = True
            if (
                block_short_if_fund_oiw_below is not None
                and cg.avg_funding_oi_weighted < block_short_if_fund_oiw_below
            ):
                blocked = True
        out.append(0 if blocked else s)
    return out


# ── align Coinglass 4h buckets to the 4h OHLC bar stream ────────────


def align_coinglass_to_bars(
    bars_4h: list[MarketBar],
    cg_4h: list[Coinglass4hBar],
) -> list[Coinglass4hBar | None]:
    cg_by_ts = {c.timestamp: c for c in cg_4h}
    return [cg_by_ts.get(b.timestamp) for b in bars_4h]


# ── backtest wrapper ────────────────────────────────────────────────


def run_cell(
    label: str,
    bars: list[MarketBar],
    signals: list[int],
    funding_per_bar: list[float],
    *,
    hold_bars: int = 12,
) -> dict:
    bt = run_v2_backtest(
        bars=bars,
        signals=signals,
        funding_per_bar=funding_per_bar,
        hold_bars=hold_bars,
        fee_per_side=FEE_PER_SIDE,
        slip_per_side=SLIP_PER_SIDE,
    )
    curve = bt.equity_curve
    ret = (curve[-1] - 1.0) if curve else 0.0
    dd = max_dd_of(curve)
    pnls = [t.net_pnl for t in bt.trades]
    pf = combined_profit_factor(pnls)
    return {
        "label": label,
        "trades": len(bt.trades),
        "return": ret,
        "max_dd": dd,
        "profit_factor": pf if pf < NO_LOSS_PROFIT_FACTOR else float("inf"),
    }


# ── main ────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 78)
    print("Strategy C v2 Phase 4 — Coinglass overlay on 4h Candidate A")
    print("=" * 78)
    print("HONEST CAVEAT: 83-day single-slice point estimate on 4h. NOT an OOS measurement.")
    print("               Compare only against the baseline 4h slice, not against the 5-year walk-forward.")
    print("=" * 78)

    # Load Coinglass aggregates
    cg_4h = load_coinglass_15m_aggregated_to_4h(TRACK_B_15M)
    print(f"\nCoinglass 4h aggregated buckets: {len(cg_4h)}")
    if cg_4h:
        print(f"  range: {cg_4h[0].timestamp} → {cg_4h[-1].timestamp}")

    # Load full 6-year 4h data and funding
    funding_records = load_funding_csv(FUNDING_CSV)
    bars_full = load_klines_csv(KLINES_4H)
    print(f"4h bars (full): {len(bars_full)}")

    # Slice to the Coinglass window
    cg_start = cg_4h[0].timestamp
    cg_end = cg_4h[-1].timestamp + timedelta(hours=4)
    bars_slice = [b for b in bars_full if cg_start <= b.timestamp < cg_end]
    print(f"4h bars (sliced to Coinglass window): {len(bars_slice)}")
    print(f"  {bars_slice[0].timestamp} → {bars_slice[-1].timestamp}")

    # Compute features on the SLICE (causal, consistent with Phase 3)
    features = compute_features_v2(bars_slice, funding_records=funding_records, bar_hours=4.0)

    # Build funding_per_bar aligned to the 4h bars
    funding_per_bar = build_funding_per_bar(bars_slice, funding_records)

    # Align Coinglass 4h aggregates to the bar list (may have gaps)
    cg_aligned = align_coinglass_to_bars(bars_slice, cg_4h)
    n_with_cg = sum(1 for c in cg_aligned if c is not None)
    print(f"Bars with Coinglass coverage: {n_with_cg} / {len(bars_slice)}")

    # Baseline: Candidate A rule on the 4h slice
    base_signals = candidate_a_signals(features)
    print(f"\nBaseline Candidate A (rsi_only_21 h=12, no overlay)")
    results: list[dict] = []
    row = run_cell("baseline", bars_slice, base_signals, funding_per_bar, hold_bars=12)
    results.append(row)
    print(
        f"  baseline: trades={row['trades']} ret={row['return']*100:+7.2f}% "
        f"dd={row['max_dd']*100:>5.2f}% pf={row['profit_factor']:>5.2f}"
    )

    # Overlay sweeps
    overlays = [
        ("block_short_liqimb>0.3", dict(block_short_if_liq_imb_above=0.3)),
        ("block_long_fundOI>5e-4", dict(block_long_if_fund_oiw_above=0.0005)),
        ("block_short_fundOI<-5e-4", dict(block_short_if_fund_oiw_below=-0.0005)),
        ("block_long_taker_delta<0", dict(block_long_if_taker_delta_negative=True)),
        ("asymmetric_short_veto_only", dict(
            block_short_if_liq_imb_above=0.3,
            block_short_if_fund_oiw_below=-0.0005,
        )),
    ]

    print("\nOverlays:")
    for label, kwargs in overlays:
        ov_signals = apply_overlay(base_signals, cg_aligned, **kwargs)
        row = run_cell(label, bars_slice, ov_signals, funding_per_bar, hold_bars=12)
        # Count delta vs baseline
        base_return = results[0]["return"]
        row["delta_vs_baseline"] = row["return"] - base_return
        row["delta_trades"] = row["trades"] - results[0]["trades"]
        results.append(row)
        print(
            f"  {label:<35} trades={row['trades']:>3} ret={row['return']*100:+7.2f}% "
            f"dd={row['max_dd']*100:>5.2f}%  Δret={row['delta_vs_baseline']*100:+6.2f}pp "
            f"Δtrades={row['delta_trades']:+d}"
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


if __name__ == "__main__":
    main()
