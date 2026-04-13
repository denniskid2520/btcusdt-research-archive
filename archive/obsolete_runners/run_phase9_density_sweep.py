"""Phase 9 — D1 execution density optimization.

Push trade count from 136 toward 150-220+ while preserving edge.
"""
from __future__ import annotations

import sys
import time
from bisect import bisect_left, bisect_right

sys.path.insert(0, "src")

from research.strategy_c_v2_backtest import V2Trade
from research.strategy_c_v2_circuit_breaker import _compute_max_adverse_intrabar
from research.strategy_c_v2_execution_layer import (
    ExecLayerConfig,
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
KLINES_15M = "src/data/btcusdt_15m_6year.csv"
FUNDING_CSV = "src/data/btcusdt_funding_5year.csv"
STARTING_EQUITY = 10_000.0

# Enhanced cost: extra 0.02% slip per side on re-entries
REENTRY_EXTRA_COST = 2 * 0.0002  # round-trip extra per trade


def compute_metrics(trades, eq_curve, frac, extra_cost=0.0):
    pnls = [t.net_pnl - extra_cost for t in trades]
    n = len(trades)
    if n == 0:
        return {"n": 0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    eq = 1.0
    peak = 1.0
    dd = 0.0
    for p in pnls:
        eq *= (1.0 + p)
        if eq > peak: peak = eq
        if peak > 0:
            d = (peak - eq) / peak
            if d > dd: dd = d
    alpha_stops = sum(1 for t in trades if t.exit_reason.startswith("alpha_stop"))
    cat_stops = sum(1 for t in trades if t.exit_reason.startswith("catastrophe_stop"))
    total_stops = alpha_stops + cat_stops
    stopped = [p for t, p in zip(trades, pnls)
               if t.exit_reason.startswith(("alpha_stop", "catastrophe_stop"))]
    return {
        "n": n,
        "wr": len(wins) / n,
        "pf": combined_profit_factor(pnls),
        "comp_ret": eq - 1.0,
        "simp_ret": sum(pnls),
        "avg_pnl": sum(pnls) / n,
        "avg_win": sum(wins) / len(wins) if wins else 0,
        "avg_loss": sum(losses) / len(losses) if losses else 0,
        "dd": dd,
        "worst": min(pnls),
        "alpha_stops": alpha_stops,
        "cat_stops": cat_stops,
        "stop_frac": total_stops / n,
        "avg_stopped": sum(stopped) / len(stopped) if stopped else 0,
    }


def main():
    print("=" * 78)
    print("Phase 9 -- D1 execution density optimization")
    print("=" * 78)

    print("\nLoading data...")
    t0 = time.time()
    funding_records = load_funding_csv(FUNDING_CSV)
    tf_4h = load_timeframe_data("4h", KLINES_4H, 4.0, funding_records)
    bars_1h = load_klines_csv(KLINES_1H)
    bars_15m = load_klines_csv(KLINES_15M)
    funding_1h = build_funding_per_bar(bars_1h, funding_records)
    funding_15m = build_funding_per_bar(bars_15m, funding_records)
    ts_15m = [b.timestamp for b in bars_15m]
    print(f"  4h={len(tf_4h.bars):,}  1h={len(bars_1h):,}  15m={len(bars_15m):,}  ({time.time()-t0:.1f}s)")

    # Grid
    # 1h sweep first (fast). 15m only on top configs if 1h ceiling is binding.
    exec_tfs = [
        ("1h", 1.0, bars_1h, funding_1h, None, None),
    ]
    entry_modes = ["pullback", "breakout", "hybrid"]
    pullback_pcts = [0.0025, 0.005, 0.0075, 0.010, 0.0125]
    breakout_pcts = [0.0025, 0.005, 0.0075, 0.010]
    max_entries_list = [3, 4, 5, 6]
    cooldowns = [0, 2, 4, 8]
    hold_hours_list = [8, 12, 16, 24]
    frac_row4 = 3.0

    # Build config list
    configs = []
    for tf_label, tf_hours, b1h, f1h, b15m, f15m in exec_tfs:
        for mode in entry_modes:
            pb_list = pullback_pcts if mode in ("pullback", "hybrid") else [0.01]
            bk_list = breakout_pcts if mode in ("breakout", "hybrid") else [0.005]
            for pb in pb_list:
                for bk in bk_list:
                    if mode == "pullback" and bk != 0.005:
                        continue  # skip breakout variation for pure pullback
                    if mode == "breakout" and pb != 0.01:
                        continue
                    for mx in max_entries_list:
                        for cd in cooldowns:
                            for hh in hold_hours_list:
                                configs.append({
                                    "tf_label": tf_label,
                                    "tf_hours": tf_hours,
                                    "b1h": b1h, "f1h": f1h,
                                    "b15m": b15m, "f15m": f15m,
                                    "mode": mode,
                                    "pb": pb, "bk": bk,
                                    "mx": mx, "cd": cd, "hh": hh,
                                })

    print(f"\nGrid size: {len(configs)} configs")

    results = []
    t1 = time.time()
    for i, cfg in enumerate(configs):
        ec = ExecLayerConfig(
            entry_type=cfg["mode"],
            pullback_pct=cfg["pb"],
            breakout_pct=cfg["bk"],
            max_entries_per_zone=cfg["mx"],
            cooldown_bars=cfg["cd"],
            hold_hours=cfg["hh"],
            alpha_stop_pct=0.0125,
            catastrophe_stop_pct=0.025,
            reentry_after_alpha_stop=True,
            reentry_after_cat_stop=True,
            exec_tf_hours=cfg["tf_hours"],
        )
        result = run_execution_layer_backtest(
            bars_4h=tf_4h.bars,
            features_4h=tf_4h.features,
            bars_1h=cfg["b1h"],
            bars_15m=cfg["b15m"],
            funding_1h=cfg["f1h"],
            funding_15m=cfg["f15m"],
            config=ec,
            position_frac=frac_row4,
        )
        m = compute_metrics(result.trades, result.equity_curve, frac_row4, REENTRY_EXTRA_COST)
        m["label"] = (f"{cfg['tf_label']} {cfg['mode'][:4]} "
                      f"pb={cfg['pb']*100:.2f} bk={cfg['bk']*100:.2f} "
                      f"mx={cfg['mx']} cd={cfg['cd']} hh={cfg['hh']}")
        m["tf"] = cfg["tf_label"]
        m["mode"] = cfg["mode"]
        m["pb"] = cfg["pb"]
        m["bk"] = cfg["bk"]
        m["mx"] = cfg["mx"]
        m["cd"] = cfg["cd"]
        m["hh"] = cfg["hh"]
        m["base"] = result.num_base_entries
        m["reentry"] = result.num_reentries
        m["zones"] = result.num_zones_used
        results.append(m)

        if (i + 1) % 200 == 0 or (i + 1) == len(configs):
            elapsed = time.time() - t1
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(configs) - (i + 1)) / rate if rate > 0 else 0
            best_n = max(r["n"] for r in results)
            print(f"  [{i+1}/{len(configs)}] {elapsed:.0f}s {rate:.1f}/s "
                  f"eta={eta:.0f}s best_n={best_n}")

    # Analysis
    print(f"\n{'='*78}")
    print("TRADE COUNT DISTRIBUTION")
    print(f"{'='*78}")
    trade_counts = sorted(set(r["n"] for r in results))
    for threshold in [100, 150, 200, 250, 300]:
        count = sum(1 for r in results if r["n"] >= threshold)
        print(f"  configs with trades >= {threshold}: {count}/{len(results)}")

    # Shortlist: trades >= 200, WR >= 60%, PF >= 3.0
    print(f"\n{'='*78}")
    print("SHORTLIST (trades>=200, WR>=60%, PF>=3.0)")
    print(f"{'='*78}")
    shortlist = [r for r in results
                 if r["n"] >= 200 and r["wr"] >= 0.60 and r["pf"] >= 3.0]
    shortlist.sort(key=lambda r: (-r["n"], -r["simp_ret"]))
    print(f"\nShortlist pass: {len(shortlist)}/{len(results)}")
    if shortlist:
        print(f"\n{'Label':<55} | {'n':>4} {'WR':>5} {'PF':>5} "
              f"{'SimpRet':>8} {'AvgPnL':>6} {'DD':>5} {'Worst':>6} "
              f"{'StpFr':>5} {'Base':>4} {'Re':>3}")
        print("-" * 120)
        for r in shortlist[:30]:
            print(f"{r['label']:<55} | "
                  f"{r['n']:>4} {r['wr']*100:>4.1f}% {r['pf']:>5.2f} "
                  f"{r['simp_ret']*100:>+7.1f}% {r['avg_pnl']*100:>5.2f}% "
                  f"{r['dd']*100:>4.1f}% {r['worst']*100:>+5.1f}% "
                  f"{r['stop_frac']*100:>4.1f}% {r['base']:>4} {r['reentry']:>3}")

    # Stretch: trades >= 300, WR >= 65%, PF >= 4.0
    stretch = [r for r in results
               if r["n"] >= 300 and r["wr"] >= 0.65 and r["pf"] >= 4.0]
    print(f"\nStretch (trades>=300, WR>=65%, PF>=4.0): {len(stretch)}/{len(results)}")
    if stretch:
        stretch.sort(key=lambda r: -r["simp_ret"])
        for r in stretch[:10]:
            print(f"  {r['label']:<55} n={r['n']} WR={r['wr']*100:.1f}% "
                  f"PF={r['pf']:.2f} simp={r['simp_ret']*100:+.1f}%")

    # Top by simple return (any filter)
    print(f"\n{'='*78}")
    print("TOP 20 BY SIMPLE RETURN (n>=150, PF>=2.5)")
    print(f"{'='*78}")
    top_ret = [r for r in results if r["n"] >= 150 and r["pf"] >= 2.5]
    top_ret.sort(key=lambda r: -r["simp_ret"])
    for r in top_ret[:20]:
        print(f"  {r['label']:<55} n={r['n']:>4} WR={r['wr']*100:>4.1f}% "
              f"PF={r['pf']:>5.2f} simp={r['simp_ret']*100:>+7.1f}% "
              f"DD={r['dd']*100:>4.1f}% base={r['base']} re={r['reentry']}")

    # Density ceiling
    print(f"\n{'='*78}")
    print("DENSITY CEILING")
    print(f"{'='*78}")
    max_n = max(r["n"] for r in results)
    max_n_good = max((r["n"] for r in results if r["pf"] >= 2.0 and r["wr"] >= 0.55), default=0)
    print(f"Max trade count (any): {max_n}")
    print(f"Max trade count (PF>=2.0, WR>=55%): {max_n_good}")
    can_200 = any(r["n"] >= 200 and r["pf"] >= 2.0 for r in results)
    can_300 = any(r["n"] >= 300 and r["pf"] >= 2.0 for r in results)
    print(f"200+ trades at PF>=2.0: {'YES' if can_200 else 'NO'}")
    print(f"300+ trades at PF>=2.0: {'YES' if can_300 else 'NO'}")
    if not can_200:
        # Identify the blocker
        high_n = [r for r in results if r["n"] >= 180]
        if high_n:
            best_hn = max(high_n, key=lambda r: r["pf"])
            print(f"\nNearest 200: n={best_hn['n']} PF={best_hn['pf']:.2f} "
                  f"WR={best_hn['wr']*100:.1f}% {best_hn['label']}")
        print("\nBlocker: 138 regime zones with single-position constraint")
        print("  caps max executed entries. Shorter holds and lower cooldowns")
        print("  help but can't exceed zone count * max_entries_per_zone")


if __name__ == "__main__":
    main()
