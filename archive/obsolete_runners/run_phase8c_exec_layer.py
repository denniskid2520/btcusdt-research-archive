"""Phase 8C — D1 execution-layer trade-count lift.

Runs the execution-layer backtest on 1h bars using the 4h D1 RSI(20)
regime as the gate. Tests pullback and breakout re-entry logic at
various thresholds, cooldowns, and max-entries-per-zone settings.

Two bases:
  - Row 2: 3x, alpha=1.25%, catastrophe=2.5%, frac=2.0 (avg) / 3.0 (max)
  - Row 4: 4x, alpha=1.25%, catastrophe=2.5%, frac=3.0 (avg) / 4.0 (max)

Goal: lift trade count toward 100+ while preserving PF and survival.
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, "src")

from research.strategy_c_v2_backtest import V2Trade
from research.strategy_c_v2_execution_layer import (
    ExecLayerConfig,
    ExecLayerResult,
    run_execution_layer_backtest,
)
from research.strategy_c_v2_runner import (
    build_funding_per_bar,
    combined_profit_factor,
    load_funding_csv,
    load_klines_csv,
    load_timeframe_data,
)

KLINES_4H = "src/data/btcusdt_4h_6year.csv"
KLINES_1H = "src/data/btcusdt_1h_6year.csv"
FUNDING_CSV = "src/data/btcusdt_funding_5year.csv"
STARTING_EQUITY = 10_000.0


def compute_metrics(result: ExecLayerResult, label: str, frac: float) -> dict:
    trades = result.trades
    pnls = [t.net_pnl for t in trades]
    n = len(trades)
    if n == 0:
        return {"label": label, "n": 0, "wr": 0, "pf": 0, "ret": 0,
                "end_usd": STARTING_EQUITY, "dd": 0, "dd_usd": 0,
                "worst": 0, "worst_usd": 0, "stops": 0, "stop_frac": 0,
                "base": result.num_base_entries, "reentry": result.num_reentries,
                "zones": result.num_zones_used}
    wins = sum(1 for p in pnls if p > 0)
    eq = result.equity_curve
    ret = (eq[-1] - 1.0) if eq else 0.0
    peak = eq[0] if eq else 1.0
    dd = 0.0
    for e in eq:
        if e > peak: peak = e
        if peak > 0:
            d = (peak - e) / peak
            if d > dd: dd = d
    dd_usd = 0.0
    peak_usd = STARTING_EQUITY
    for e in eq:
        q = STARTING_EQUITY * e
        if q > peak_usd: peak_usd = q
        drop = peak_usd - q
        if drop > dd_usd: dd_usd = drop
    worst = min(pnls)
    pf = combined_profit_factor(pnls)
    stops = sum(1 for t in trades if t.exit_reason.startswith(
        ("alpha_stop", "catastrophe_stop", "stop_loss")))
    return {
        "label": label,
        "n": n,
        "wr": wins / n,
        "pf": pf,
        "ret": ret,
        "end_usd": STARTING_EQUITY * (1 + ret),
        "dd": dd,
        "dd_usd": dd_usd,
        "worst": worst,
        "worst_usd": worst * STARTING_EQUITY,
        "stops": stops,
        "stop_frac": stops / n,
        "base_entries": result.num_base_entries,
        "reentries": result.num_reentries,
        "zones": result.num_zones_used,
        "frac": frac,
    }


def main() -> None:
    print("=" * 78)
    print("Phase 8C - D1 execution-layer trade-count lift (1h resolution)")
    print("=" * 78)

    print("\nLoading data...")
    t0 = time.time()
    funding_records = load_funding_csv(FUNDING_CSV)
    tf_4h = load_timeframe_data("4h", KLINES_4H, 4.0, funding_records)
    bars_1h = load_klines_csv(KLINES_1H)
    funding_1h = build_funding_per_bar(bars_1h, funding_records)
    print(f"  4h: {len(tf_4h.bars):,} bars, 1h: {len(bars_1h):,} bars ({time.time()-t0:.1f}s)")

    # Search grid
    bases = [
        ("Row2_3x", 2.0, 0.0125, 0.025),   # frac, alpha, cat
        ("Row4_4x", 3.0, 0.0125, 0.025),
    ]
    entry_types = ["pullback", "breakout"]
    thresholds = {
        "pullback": [0.005, 0.010, 0.015, 0.020, 0.025],
        "breakout": [0.003, 0.005, 0.010],
    }
    max_entries_list = [1, 2, 3]
    cooldowns = [4, 8, 12, 24]
    hold_4h_list = [6, 8, 11]

    all_results: list[dict] = []
    total_configs = 0

    for base_label, frac, alpha, cat in bases:
        for entry_type in entry_types:
            for thresh in thresholds[entry_type]:
                for max_ent in max_entries_list:
                    for cd in cooldowns:
                        for hold_4h in hold_4h_list:
                            total_configs += 1

    print(f"\nTotal configs to test: {total_configs}")

    count = 0
    t1 = time.time()
    for base_label, frac, alpha, cat in bases:
        for entry_type in entry_types:
            for thresh in thresholds[entry_type]:
                for max_ent in max_entries_list:
                    for cd in cooldowns:
                        for hold_4h in hold_4h_list:
                            config = ExecLayerConfig(
                                entry_type=entry_type,
                                threshold_pct=thresh,
                                max_entries_per_zone=max_ent,
                                cooldown_1h_bars=cd,
                                hold_4h_equiv=hold_4h,
                                alpha_stop_pct=alpha,
                                catastrophe_stop_pct=cat,
                            )
                            result = run_execution_layer_backtest(
                                bars_4h=tf_4h.bars,
                                features_4h=tf_4h.features,
                                bars_1h=bars_1h,
                                funding_1h=funding_1h,
                                config=config,
                                position_frac=frac,
                            )
                            label = (
                                f"{base_label} {entry_type[:4]} "
                                f"th={thresh*100:.1f}% "
                                f"mx={max_ent} cd={cd} h={hold_4h}"
                            )
                            m = compute_metrics(result, label, frac)
                            m["entry_type"] = entry_type
                            m["threshold"] = thresh
                            m["max_entries"] = max_ent
                            m["cooldown"] = cd
                            m["hold_4h"] = hold_4h
                            m["base"] = base_label
                            all_results.append(m)
                            count += 1
                            if count % 50 == 0 or count == total_configs:
                                elapsed = time.time() - t1
                                rate = count / elapsed if elapsed > 0 else 0
                                eta = (total_configs - count) / rate if rate > 0 else 0
                                print(f"  [{count}/{total_configs}] "
                                      f"{elapsed:.0f}s {rate:.1f}/s eta={eta:.0f}s")

    # Filter and sort
    print(f"\n{'=' * 78}")
    print("RESULTS — sorted by trade count then by return")
    print(f"{'=' * 78}")

    # Show top 30 by trade count (with PF >= 1.5 filter)
    viable = [r for r in all_results if r["pf"] >= 1.5 and r["n"] >= 20]
    viable.sort(key=lambda r: (-r["n"], -r["ret"]))

    print(f"\nViable configs (PF>=1.5, n>=20): {len(viable)}/{len(all_results)}")
    print(f"\n{'Label':<45} | {'n':>4} {'base':>4} {'re':>3} | "
          f"{'WR':>5} {'PF':>5} {'Return':>8} {'End$':>8} | "
          f"{'DD%':>5} {'Worst%':>6} {'StpFr':>5}")
    print("-" * 120)
    for r in viable[:40]:
        print(
            f"{r['label']:<45} | "
            f"{r['n']:>4} {r['base_entries']:>4} {r['reentries']:>3} | "
            f"{r['wr']*100:>4.1f}% {r['pf']:>5.2f} "
            f"{r['ret']*100:>+7.1f}% ${r['end_usd']:>7,.0f} | "
            f"{r['dd']*100:>4.1f}% {r['worst']*100:>+5.1f}% "
            f"{r['stop_frac']*100:>4.1f}%"
        )

    # Show configs that hit 100+ trades
    hundred_plus = [r for r in all_results if r["n"] >= 100]
    print(f"\n100+ trade configs: {len(hundred_plus)}")
    if hundred_plus:
        hundred_plus.sort(key=lambda r: -r["ret"])
        print("\nTop 100+ trade configs by return (any PF):")
        for r in hundred_plus[:20]:
            print(
                f"  {r['label']:<45} n={r['n']:>4} WR={r['wr']*100:>4.1f}% "
                f"PF={r['pf']:>5.2f} ret={r['ret']*100:>+7.1f}% "
                f"DD={r['dd']*100:>4.1f}% base={r['base_entries']} re={r['reentries']}"
            )

    # Show configs with PF >= 2.0
    high_pf = [r for r in all_results if r["pf"] >= 2.0 and r["n"] >= 40]
    high_pf.sort(key=lambda r: (-r["n"], -r["ret"]))
    print(f"\nPF >= 2.0 configs (n>=40): {len(high_pf)}")
    if high_pf:
        print("\nTop PF>=2.0 configs by trade count:")
        for r in high_pf[:20]:
            print(
                f"  {r['label']:<45} n={r['n']:>4} WR={r['wr']*100:>4.1f}% "
                f"PF={r['pf']:>5.2f} ret={r['ret']*100:>+7.1f}% "
                f"DD={r['dd']*100:>4.1f}% base={r['base_entries']} re={r['reentries']}"
            )

    # Summary
    print(f"\n{'=' * 78}")
    print("SUMMARY")
    print(f"{'=' * 78}")
    max_trades = max(r["n"] for r in all_results) if all_results else 0
    max_trades_pf2 = max((r["n"] for r in all_results if r["pf"] >= 2.0), default=0)
    best_ret_100 = max((r["ret"] for r in hundred_plus), default=0) if hundred_plus else 0
    print(f"Max trade count (any PF): {max_trades}")
    print(f"Max trade count (PF>=2.0): {max_trades_pf2}")
    print(f"Best return @ 100+ trades: {best_ret_100*100:+.1f}%")
    print(f"100+ trades achievable: {'YES' if hundred_plus else 'NO'}")
    has_target = any(r["n"] >= 100 and r["pf"] >= 2.0 for r in all_results)
    print(f"100+ trades AND PF>=2.0: {'YES' if has_target else 'NO'}")


if __name__ == "__main__":
    main()
