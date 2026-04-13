"""Phase 8D — Coinglass overlay ON vs OFF on last OOS window.

Tests three overlay families as entry veto on the exec-layer D1:
1. OI divergence: veto if OI falling while signal is long
2. Taker imbalance: veto if sell volume > buy volume
3. Liquidation cascade: veto if large long liquidations recently

Sample: 2025-10-05 to 2026-04-04 (the only window with 4h CG data).
This is a ~20-trade challenger test, NOT a full validation.
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime

sys.path.insert(0, "src")

from research.strategy_c_v2_backtest import run_v2_backtest
from research.strategy_c_v2_runner import (
    build_funding_per_bar,
    combined_profit_factor,
    load_funding_csv,
    load_klines_csv,
    load_timeframe_data,
)
from research.strategy_c_v2_execution_layer import (
    ExecLayerConfig,
    run_execution_layer_backtest,
)


def load_cg_map(path: str) -> dict[datetime, dict]:
    rows = list(csv.DictReader(open(path)))
    return {datetime.fromisoformat(r["timestamp"]): r for r in rows}


def main() -> None:
    print("=" * 78)
    print("Phase 8D — Coinglass overlay test (last OOS window only)")
    print("=" * 78)

    funding_records = load_funding_csv("src/data/btcusdt_funding_5year.csv")
    tf_4h = load_timeframe_data(
        "4h", "src/data/btcusdt_4h_6year.csv", 4.0, funding_records
    )
    bars_1h = load_klines_csv("src/data/btcusdt_1h_6year.csv")
    funding_1h = build_funding_per_bar(bars_1h, funding_records)

    oi_map = load_cg_map("src/data/coinglass_oi_4h.csv")
    liq_map = load_cg_map("src/data/coinglass_liquidation_4h.csv")
    taker_map = load_cg_map("src/data/coinglass_taker_volume_4h.csv")

    # Restrict to last OOS window
    last_split = tf_4h.splits[-1]
    lo, hi = last_split.test_lo, last_split.test_hi
    window_bars_4h = tf_4h.bars[lo:hi]
    window_features_4h = tf_4h.features[lo:hi]

    # Find 1h bars within the window
    from bisect import bisect_left, bisect_right
    ts_1h = [b.timestamp for b in bars_1h]
    lo_1h = bisect_left(ts_1h, window_bars_4h[0].timestamp)
    hi_1h = bisect_right(ts_1h, window_bars_4h[-1].timestamp)
    window_bars_1h = bars_1h[lo_1h:hi_1h]
    window_funding_1h = funding_1h[lo_1h:hi_1h]

    print(f"Window: {window_bars_4h[0].timestamp} to {window_bars_4h[-1].timestamp}")
    print(f"  4h bars: {len(window_bars_4h)}, 1h bars: {len(window_bars_1h)}")

    # Best exec-layer config from Phase 8C
    exec_config = ExecLayerConfig(
        entry_type="pullback",
        threshold_pct=0.01,
        max_entries_per_zone=3,
        cooldown_1h_bars=4,
        hold_4h_equiv=6,
        alpha_stop_pct=0.0125,
        catastrophe_stop_pct=0.025,
    )
    frac = 3.0  # Row 4 base

    # ── BASELINE: no overlay ──
    print("\n--- BASELINE (no overlay) ---")
    base_result = run_execution_layer_backtest(
        bars_4h=window_bars_4h,
        features_4h=window_features_4h,
        bars_1h=window_bars_1h,
        funding_1h=window_funding_1h,
        config=exec_config,
        position_frac=frac,
    )
    base_pnls = [t.net_pnl for t in base_result.trades]
    base_n = len(base_result.trades)
    base_wins = sum(1 for p in base_pnls if p > 0)
    base_ret = (base_result.equity_curve[-1] - 1.0) if base_result.equity_curve else 0.0
    base_pf = combined_profit_factor(base_pnls)
    print(f"  trades={base_n} WR={base_wins/base_n*100:.1f}% PF={base_pf:.2f} "
          f"ret={base_ret*100:+.1f}%")

    # Build a 4h-bar-indexed map of CG features for overlay filters
    def get_oi_divergence(bar_ts: datetime) -> bool:
        """True if OI is falling (bearish divergence) — VETO signal."""
        row = oi_map.get(bar_ts)
        if not row:
            return False
        try:
            oi_open = float(row.get("open", 0))
            oi_close = float(row.get("close", 0))
            return oi_close < oi_open * 0.995  # OI dropped > 0.5%
        except (ValueError, TypeError):
            return False

    def get_taker_sell_dominant(bar_ts: datetime) -> bool:
        """True if sell volume > buy volume — VETO signal."""
        row = taker_map.get(bar_ts)
        if not row:
            return False
        try:
            buy = float(row.get("buy_usd", 0))
            sell = float(row.get("sell_usd", 0))
            return sell > buy * 1.05  # sell > buy by 5%
        except (ValueError, TypeError):
            return False

    def get_high_long_liquidation(bar_ts: datetime) -> bool:
        """True if long liquidation is high — VETO signal."""
        row = liq_map.get(bar_ts)
        if not row:
            return False
        try:
            long_usd = float(row.get("long_usd", 0))
            return long_usd > 5_000_000  # $5M+ long liquidations
        except (ValueError, TypeError):
            return False

    # For each overlay, modify the exec-layer signal vector
    # by vetoing signals where the overlay says "don't enter"
    # This requires running the exec layer WITH a modified signal

    # Since I can't easily inject overlays into the exec-layer module
    # without refactoring, I'll use a simpler approach: check which
    # of the baseline trades' entry bars had overlay vetoes, and
    # compute the "what if we skipped those trades" metrics.

    overlays = {
        "OI_divergence_veto": get_oi_divergence,
        "taker_sell_veto": get_taker_sell_dominant,
        "liq_cascade_veto": get_high_long_liquidation,
    }

    print(f"\n--- OVERLAY RESULTS (window-only, {base_n} baseline trades) ---\n")
    print(f"{'Overlay':<25} | {'Vetoed':>6} {'Kept':>4} {'WR':>5} {'PF':>5} "
          f"{'Return':>8} | {'vs base':>8}")
    print("-" * 80)

    # Baseline row
    print(f"{'BASELINE (no overlay)':<25} | {'0':>6} {base_n:>4} "
          f"{base_wins/base_n*100:>4.1f}% {base_pf:>5.2f} "
          f"{base_ret*100:>+7.1f}% | {'--':>8}")

    for name, veto_fn in overlays.items():
        # For each trade, find the nearest 4h bar timestamp and check veto
        kept_pnls = []
        vetoed_count = 0
        for t in base_result.trades:
            # Find the 4h bar that contains this trade's entry time
            # Round down to nearest 4h boundary
            entry = t.entry_time
            hour = entry.hour
            bar_hour = (hour // 4) * 4
            bar_ts = entry.replace(hour=bar_hour, minute=0, second=0, microsecond=0)

            if veto_fn(bar_ts):
                vetoed_count += 1
            else:
                kept_pnls.append(t.net_pnl)

        if kept_pnls:
            kept_n = len(kept_pnls)
            kept_wins = sum(1 for p in kept_pnls if p > 0)
            kept_pf = combined_profit_factor(kept_pnls)
            eq = 1.0
            for p in kept_pnls:
                eq *= (1.0 + p)
            kept_ret = eq - 1.0
            delta = (kept_ret - base_ret) * 100
            print(f"{name:<25} | {vetoed_count:>6} {kept_n:>4} "
                  f"{kept_wins/kept_n*100:>4.1f}% {kept_pf:>5.2f} "
                  f"{kept_ret*100:>+7.1f}% | {delta:>+7.1f}pp")
        else:
            print(f"{name:<25} | {vetoed_count:>6} {'0':>4} "
                  f"{'N/A':>5} {'N/A':>5} {'N/A':>8} | {'N/A':>8}")

    # Combined: all three overlays applied together
    combined_pnls = []
    combined_vetoed = 0
    for t in base_result.trades:
        entry = t.entry_time
        hour = entry.hour
        bar_hour = (hour // 4) * 4
        bar_ts = entry.replace(hour=bar_hour, minute=0, second=0, microsecond=0)
        any_veto = any(fn(bar_ts) for fn in overlays.values())
        if any_veto:
            combined_vetoed += 1
        else:
            combined_pnls.append(t.net_pnl)
    if combined_pnls:
        cn = len(combined_pnls)
        cw = sum(1 for p in combined_pnls if p > 0)
        cpf = combined_profit_factor(combined_pnls)
        eq = 1.0
        for p in combined_pnls:
            eq *= (1.0 + p)
        cret = eq - 1.0
        delta = (cret - base_ret) * 100
        print(f"{'ALL_COMBINED':<25} | {combined_vetoed:>6} {cn:>4} "
              f"{cw/cn*100:>4.1f}% {cpf:>5.2f} "
              f"{cret*100:>+7.1f}% | {delta:>+7.1f}pp")

    print(f"\n--- VERDICT ---")
    print(f"Sample size: {base_n} trades in ~6 months")
    print(f"Statistical power: INSUFFICIENT for overlay acceptance")
    print(f"  (need 100+ trades minimum for meaningful A/B, have {base_n})")
    if base_n < 30:
        print(f"  Even directional conclusions are unreliable at n={base_n}")
    print(f"\nCoinglass overlay: REJECTED for final strategy")
    print(f"Reason: 4h history covers only last OOS window (~180 days)")
    print(f"  Cannot validate across 4-year walk-forward")
    print(f"  Sample too small for statistically meaningful overlay test")
    print(f"  Keep Binance-only D1 as the final strategy")


if __name__ == "__main__":
    main()
