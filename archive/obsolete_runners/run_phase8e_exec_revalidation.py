"""Phase 8E — execution-layer leverage/risk revalidation.

Re-runs the FULL validation stack on the NEW execution-layer trade
stream for Row 2 (3x), Row 4 (4x), Row 5 (5x).

Includes:
  8E base:   full OOS metrics with both simple and compounded return
  8E.1:      execution-aware cost model (old vs enhanced)
  8E.2:      stress suite (slippage + shock + intrabar replay + stop audit)
  8E.3:      shortlist filter application
"""
from __future__ import annotations

import sys
import time
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

sys.path.insert(0, "src")

from research.strategy_c_v2_backtest import V2Trade, run_v2_backtest
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
from research.strategy_c_v2_circuit_breaker import _compute_max_adverse_intrabar

KLINES_4H = "src/data/btcusdt_4h_6year.csv"
KLINES_1H = "src/data/btcusdt_1h_6year.csv"
KLINES_15M = "src/data/btcusdt_15m_6year.csv"
FUNDING_CSV = "src/data/btcusdt_funding_5year.csv"

STARTING_EQUITY = 10_000.0
BASE_FEE = 0.0005
BASE_SLIP = 0.0001

SHOCK_LEVELS = (0.10, 0.15, 0.20, 0.30, 0.40)
SLIP_LEVELS = (0.001, 0.003, 0.005, 0.010)

# Execution-aware cost model adds a penalty for:
# - pullback-entry spread widening (re-entries during dips have wider spread)
# - re-entry churn (more entries = more round-trips)
REENTRY_EXTRA_SLIP = 0.0002   # 0.02% extra slip on re-entry fills (dip conditions)
REENTRY_EXTRA_FEE = 0.0       # no extra fee (same maker/taker rate)

# The exec-layer config (frozen from Phase 8C winner)
EXEC_CONFIG = ExecLayerConfig(
    entry_type="pullback",
    threshold_pct=0.01,
    max_entries_per_zone=3,
    cooldown_1h_bars=4,
    hold_4h_equiv=6,
    alpha_stop_pct=0.0125,
    catastrophe_stop_pct=0.025,
)

# Row configs: (label, base_frac, max_frac, exchange_leverage)
ROWS = [
    ("Row2_3x", 2.0, 3.0, 3.0),
    ("Row4_4x", 3.0, 4.0, 4.0),
    ("Row5_5x", 3.33, 5.0, 5.0),
]


@dataclass
class FullMetrics:
    label: str
    cost_model: str
    # counts
    num_trades: int
    num_wins: int
    num_losses: int
    win_rate: float
    profit_factor: float
    # returns
    compounded_return: float
    simple_return: float
    ending_equity_compounded: float
    ending_equity_simple: float
    avg_pnl: float
    avg_win: float
    avg_loss: float
    # risk
    max_dd_pct: float
    max_dd_usd: float
    worst_trade_pct: float
    worst_trade_usd: float
    # stops
    alpha_stop_count: int
    catastrophe_stop_count: int
    time_stop_count: int
    other_exit_count: int
    stop_exit_fraction: float
    avg_stopped_loss: float
    # sizing
    avg_actual_frac: float
    max_actual_frac: float
    # liquidation
    exchange_leverage: float
    liq_distance: float
    worst_adverse_15m: float
    historical_liquidated: bool
    # shock verdicts
    shock_verdicts: dict
    # slippage
    slip_results: dict


def compute_full_metrics(
    trades: list[V2Trade],
    equity_curve: list[float],
    frac: float,
    exchange_leverage: float,
    worst_adverse_15m: float,
    label: str,
    cost_model: str,
    cost_adjustment: float = 0.0,
) -> FullMetrics:
    """Compute all Phase 8E required metrics."""
    pnls = [t.net_pnl - cost_adjustment for t in trades]
    n = len(trades)
    if n == 0:
        return FullMetrics(
            label=label, cost_model=cost_model,
            num_trades=0, num_wins=0, num_losses=0, win_rate=0, profit_factor=0,
            compounded_return=0, simple_return=0,
            ending_equity_compounded=STARTING_EQUITY, ending_equity_simple=STARTING_EQUITY,
            avg_pnl=0, avg_win=0, avg_loss=0,
            max_dd_pct=0, max_dd_usd=0, worst_trade_pct=0, worst_trade_usd=0,
            alpha_stop_count=0, catastrophe_stop_count=0, time_stop_count=0,
            other_exit_count=0, stop_exit_fraction=0, avg_stopped_loss=0,
            avg_actual_frac=0, max_actual_frac=0,
            exchange_leverage=exchange_leverage, liq_distance=1/exchange_leverage,
            worst_adverse_15m=0, historical_liquidated=False,
            shock_verdicts={}, slip_results={},
        )

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # Compounded equity
    eq = 1.0
    peak = 1.0
    dd = 0.0
    peak_usd = STARTING_EQUITY
    dd_usd = 0.0
    for p in pnls:
        eq *= (1.0 + p)
        if eq > peak:
            peak = eq
        if peak > 0:
            d = (peak - eq) / peak
            if d > dd:
                dd = d
        eq_usd = STARTING_EQUITY * eq
        if eq_usd > peak_usd:
            peak_usd = eq_usd
        drop = peak_usd - eq_usd
        if drop > dd_usd:
            dd_usd = drop

    compounded_ret = eq - 1.0
    simple_ret = sum(pnls)

    # Stops
    alpha_stops = sum(1 for t in trades if t.exit_reason.startswith("alpha_stop"))
    cat_stops = sum(1 for t in trades if t.exit_reason.startswith("catastrophe_stop"))
    time_stops = sum(1 for t in trades if t.exit_reason in ("time_stop", "end_of_series"))
    other_exits = n - alpha_stops - cat_stops - time_stops
    total_stops = alpha_stops + cat_stops
    stopped_losses = [p for t, p in zip(trades, pnls)
                      if t.exit_reason.startswith(("alpha_stop", "catastrophe_stop"))]
    avg_stopped = sum(stopped_losses) / len(stopped_losses) if stopped_losses else 0.0

    # Liquidation
    liq_dist = 1.0 / exchange_leverage
    hist_liq = worst_adverse_15m >= liq_dist

    # Shock verdicts
    shock_v = {}
    for s in SHOCK_LEVELS:
        combined = worst_adverse_15m + s
        if combined >= liq_dist:
            shock_v[s] = "liq"
        elif liq_dist - combined < 0.05:
            shock_v[s] = "tight"
        else:
            shock_v[s] = "surv"

    # Slippage ladder
    slip_r = {}
    for sl in SLIP_LEVELS:
        drag = total_stops * sl * frac
        adj_eq = eq * (1.0 - drag)
        adj_ret = adj_eq - 1.0
        delta_pp = (adj_ret - compounded_ret) * 100
        slip_r[sl] = {
            "adj_return": adj_ret,
            "delta_pp": delta_pp,
            "adj_equity": STARTING_EQUITY * (1 + adj_ret),
        }

    return FullMetrics(
        label=label,
        cost_model=cost_model,
        num_trades=n,
        num_wins=len(wins),
        num_losses=len(losses),
        win_rate=len(wins) / n,
        profit_factor=combined_profit_factor(pnls),
        compounded_return=compounded_ret,
        simple_return=simple_ret,
        ending_equity_compounded=STARTING_EQUITY * (1 + compounded_ret),
        ending_equity_simple=STARTING_EQUITY * (1 + simple_ret),
        avg_pnl=sum(pnls) / n,
        avg_win=sum(wins) / len(wins) if wins else 0,
        avg_loss=sum(losses) / len(losses) if losses else 0,
        max_dd_pct=dd,
        max_dd_usd=dd_usd,
        worst_trade_pct=min(pnls),
        worst_trade_usd=min(pnls) * STARTING_EQUITY,
        alpha_stop_count=alpha_stops,
        catastrophe_stop_count=cat_stops,
        time_stop_count=time_stops,
        other_exit_count=other_exits,
        stop_exit_fraction=total_stops / n,
        avg_stopped_loss=avg_stopped,
        avg_actual_frac=frac,
        max_actual_frac=frac,
        exchange_leverage=exchange_leverage,
        liq_distance=liq_dist,
        worst_adverse_15m=worst_adverse_15m,
        historical_liquidated=hist_liq,
        shock_verdicts=shock_v,
        slip_results=slip_r,
    )


def print_table(metrics_list: list[FullMetrics]) -> None:
    """Print the Phase 8F comparison table."""
    print(f"\n{'Label':<30} {'Cost':<6} | "
          f"{'n':>4} {'WR':>5} {'PF':>5} | "
          f"{'CompRet':>10} {'SimpRet':>8} {'End$comp':>10} {'End$simp':>9} | "
          f"{'AvgPnL':>6} {'AvgW':>6} {'AvgL':>6} | "
          f"{'DD%':>5} {'DD$':>7} {'Wrst%':>6} {'Wrst$':>6} | "
          f"{'aS':>3} {'cS':>3} {'tS':>3} {'StF':>5} {'AvgSL':>6} | "
          f"{'Frac':>4} {'Lev':>3} {'Adv15':>6} {'Liq?':>4} | "
          f"{'10%':>4} {'15%':>4} {'20%':>4} {'30%':>4} {'40%':>4} | "
          f"{'s.1':>6} {'s.3':>6} {'s.5':>6} {'s1':>7}")
    print("-" * 230)
    for m in metrics_list:
        sv = m.shock_verdicts
        sr = m.slip_results
        print(
            f"{m.label:<30} {m.cost_model:<6} | "
            f"{m.num_trades:>4} {m.win_rate*100:>4.1f}% {m.profit_factor:>5.2f} | "
            f"{m.compounded_return*100:>+9.1f}% {m.simple_return*100:>+7.1f}% "
            f"${m.ending_equity_compounded:>9,.0f} ${m.ending_equity_simple:>8,.0f} | "
            f"{m.avg_pnl*100:>5.2f}% {m.avg_win*100:>5.2f}% {m.avg_loss*100:>5.2f}% | "
            f"{m.max_dd_pct*100:>4.1f}% ${m.max_dd_usd:>6,.0f} "
            f"{m.worst_trade_pct*100:>+5.1f}% ${m.worst_trade_usd:>5,.0f} | "
            f"{m.alpha_stop_count:>3} {m.catastrophe_stop_count:>3} "
            f"{m.time_stop_count:>3} {m.stop_exit_fraction*100:>4.1f}% "
            f"{m.avg_stopped_loss*100:>+5.2f}% | "
            f"{m.avg_actual_frac:>4.1f} {m.exchange_leverage:>3.0f}x "
            f"{m.worst_adverse_15m*100:>5.2f}% {'YES' if m.historical_liquidated else 'NO':>4} | "
            f"{sv.get(0.10,'?'):>4} {sv.get(0.15,'?'):>4} "
            f"{sv.get(0.20,'?'):>4} {sv.get(0.30,'?'):>4} "
            f"{sv.get(0.40,'?'):>4} | "
            f"{sr.get(0.001,{}).get('delta_pp',0):>+5.0f}p "
            f"{sr.get(0.003,{}).get('delta_pp',0):>+5.0f}p "
            f"{sr.get(0.005,{}).get('delta_pp',0):>+5.0f}p "
            f"{sr.get(0.010,{}).get('delta_pp',0):>+6.0f}p"
        )


def main() -> None:
    print("=" * 78)
    print("Phase 8E — Execution-layer leverage/risk revalidation")
    print("=" * 78)

    print("\nLoading data...")
    t0 = time.time()
    funding_records = load_funding_csv(FUNDING_CSV)
    tf_4h = load_timeframe_data("4h", KLINES_4H, 4.0, funding_records)
    bars_1h = load_klines_csv(KLINES_1H)
    bars_15m = load_klines_csv(KLINES_15M)
    funding_1h = build_funding_per_bar(bars_1h, funding_records)
    ts_15m = [b.timestamp for b in bars_15m]
    print(f"  4h={len(tf_4h.bars):,}  1h={len(bars_1h):,}  15m={len(bars_15m):,}  ({time.time()-t0:.1f}s)")

    all_metrics: list[FullMetrics] = []

    for label, base_frac, max_frac, lev in ROWS:
        print(f"\n{'='*60}")
        print(f"Running {label} (frac={base_frac}, max={max_frac}, lev={lev}x)")
        print(f"{'='*60}")

        # Run execution-layer backtest
        result = run_execution_layer_backtest(
            bars_4h=tf_4h.bars,
            features_4h=tf_4h.features,
            bars_1h=bars_1h,
            funding_1h=funding_1h,
            config=EXEC_CONFIG,
            position_frac=base_frac,
        )
        trades = result.trades
        eq_curve = result.equity_curve
        print(f"  trades={len(trades)} base={result.num_base_entries} "
              f"re={result.num_reentries} zones={result.num_zones_used}")

        # 8E.2: intrabar adverse replay on 15m
        print(f"  Scanning 15m intrabar adverse on non-stop trades...")
        worst_adv_15m = 0.0
        non_stop_trades = [t for t in trades
                           if not t.exit_reason.startswith(("alpha_stop", "catastrophe_stop", "stop_loss"))]
        for t in non_stop_trades:
            lo = bisect_left(ts_15m, t.entry_time)
            hi = bisect_right(ts_15m, t.exit_time)
            adv, _, _ = _compute_max_adverse_intrabar(bars_15m, lo, hi, t.entry_price, t.side)
            if adv > worst_adv_15m:
                worst_adv_15m = adv
        print(f"  Worst 15m adverse (non-stop): {worst_adv_15m*100:.2f}%")

        # A) Old simple cost model
        m_old = compute_full_metrics(
            trades, eq_curve, base_frac, lev, worst_adv_15m,
            label=f"{label} exec", cost_model="old",
        )
        all_metrics.append(m_old)

        # B) Execution-aware cost model
        # Extra cost per re-entry trade: REENTRY_EXTRA_SLIP * base_frac (round-trip)
        # We approximate by adding extra cost to ALL trades (base + re-entry)
        # since even base entries are at 1h resolution (slightly wider spread than 4h)
        extra_cost = 2 * REENTRY_EXTRA_SLIP * base_frac  # round-trip extra
        m_new = compute_full_metrics(
            trades, eq_curve, base_frac, lev, worst_adv_15m,
            label=f"{label} exec", cost_model="new",
            cost_adjustment=extra_cost,
        )
        all_metrics.append(m_new)

    # Print comparison table
    print("\n" + "=" * 78)
    print("PHASE 8F COMPARISON TABLE")
    print("=" * 78)
    print_table(all_metrics)

    # Shortlist filter
    print("\n" + "=" * 78)
    print("SHORTLIST FILTER (8E.3)")
    print("=" * 78)
    for m in all_metrics:
        passes = []
        fails = []
        if m.num_trades >= 100:
            passes.append(f"trades={m.num_trades}>=100")
        else:
            fails.append(f"trades={m.num_trades}<100")
        if m.win_rate >= 0.60:
            passes.append(f"WR={m.win_rate*100:.1f}%>=60%")
        else:
            fails.append(f"WR={m.win_rate*100:.1f}%<60%")
        if m.profit_factor >= 2.0:
            passes.append(f"PF={m.profit_factor:.2f}>=2.0")
        else:
            fails.append(f"PF={m.profit_factor:.2f}<2.0")
        if not m.historical_liquidated:
            passes.append("no hist liq")
        else:
            fails.append("HIST LIQUIDATED")
        sv15 = m.shock_verdicts.get(0.15, "?")
        if sv15 in ("surv", "tight"):
            passes.append(f"15%shk={sv15}")
        else:
            fails.append(f"15%shk={sv15}")

        verdict = "PASS" if not fails else "FAIL"
        print(f"\n  {m.label} [{m.cost_model}]: {verdict}")
        if passes:
            print(f"    PASS: {'; '.join(passes)}")
        if fails:
            print(f"    FAIL: {'; '.join(fails)}")

    # Ranking by simple return (among shortlist-passing, new cost model)
    print("\n" + "=" * 78)
    print("RANKING (shortlist-passing, new cost model, by simple return)")
    print("=" * 78)
    passing = [m for m in all_metrics
               if m.cost_model == "new"
               and m.num_trades >= 100
               and m.win_rate >= 0.60
               and m.profit_factor >= 2.0
               and not m.historical_liquidated]
    passing.sort(key=lambda m: m.simple_return, reverse=True)
    for i, m in enumerate(passing):
        sv = m.shock_verdicts
        print(f"  #{i+1} {m.label}: "
              f"simple={m.simple_return*100:+.1f}% comp={m.compounded_return*100:+.1f}% "
              f"n={m.num_trades} WR={m.win_rate*100:.1f}% PF={m.profit_factor:.2f} "
              f"DD={m.max_dd_pct*100:.1f}% "
              f"shk15={sv.get(0.15,'?')} shk20={sv.get(0.20,'?')}")
    if not passing:
        print("  NO candidates pass all shortlist filters")
        # Show near-misses
        near = [m for m in all_metrics if m.cost_model == "new"]
        near.sort(key=lambda m: m.simple_return, reverse=True)
        print("\n  Near-misses (new cost, sorted by simple return):")
        for m in near:
            sv = m.shock_verdicts
            print(f"    {m.label}: "
                  f"simple={m.simple_return*100:+.1f}% "
                  f"n={m.num_trades} WR={m.win_rate*100:.1f}% PF={m.profit_factor:.2f} "
                  f"DD={m.max_dd_pct*100:.1f}% "
                  f"shk15={sv.get(0.15,'?')} shk20={sv.get(0.20,'?')}")

    # Feasibility verdicts
    print("\n" + "=" * 78)
    print("FEASIBILITY VERDICTS")
    print("=" * 78)
    for label, _, _, lev in ROWS:
        candidates = [m for m in all_metrics
                      if m.label.startswith(label) and m.cost_model == "new"]
        if not candidates:
            continue
        m = candidates[0]
        sv = m.shock_verdicts
        print(f"\n  {label} ({lev:.0f}x leverage):")
        print(f"    trades={m.num_trades} WR={m.win_rate*100:.1f}% PF={m.profit_factor:.2f}")
        print(f"    simple_return={m.simple_return*100:+.1f}% "
              f"compounded={m.compounded_return*100:+.1f}%")
        print(f"    DD={m.max_dd_pct*100:.1f}% worst_trade={m.worst_trade_pct*100:+.1f}%")
        print(f"    worst_15m_adverse={m.worst_adverse_15m*100:.2f}% "
              f"liq_distance={m.liq_distance*100:.1f}%")
        print(f"    shocks: 10%={sv.get(0.10)} 15%={sv.get(0.15)} "
              f"20%={sv.get(0.20)} 30%={sv.get(0.30)} 40%={sv.get(0.40)}")
        sr = m.slip_results
        print(f"    slip: 0.1%={sr.get(0.001,{}).get('delta_pp',0):+.0f}pp "
              f"0.3%={sr.get(0.003,{}).get('delta_pp',0):+.0f}pp "
              f"0.5%={sr.get(0.005,{}).get('delta_pp',0):+.0f}pp "
              f"1.0%={sr.get(0.010,{}).get('delta_pp',0):+.0f}pp")
        feasible = (
            m.num_trades >= 100
            and m.win_rate >= 0.60
            and m.profit_factor >= 2.0
            and not m.historical_liquidated
            and sv.get(0.15) in ("surv", "tight")
        )
        print(f"    FEASIBLE: {'YES' if feasible else 'NO'}")
        if m.simple_return >= 5.0:
            print(f"    500% simple return: YES ({m.simple_return*100:+.1f}%)")
        else:
            print(f"    500% simple return: NO ({m.simple_return*100:+.1f}%)")
        if m.simple_return >= 10.0:
            print(f"    1000% simple return: YES")
        else:
            print(f"    1000% simple return: NO ({m.simple_return*100:+.1f}%)")


if __name__ == "__main__":
    main()
