#!/usr/bin/env python
"""Comprehensive BB Strategy D optimization sweep.

Tests academic paper findings:
  - BB period: 20 / 40 / 60 (Hsu & Chiang 2022: BB(60) outperforms on BTC)
  - BB type: SMA / EMA (HBEM 2024: EMA Sharpe 3.22)
  - Entry mode: symmetric / asymmetric (Beluska & Vojtko 2024: long-only)
  - Target: middle / opposite band
  - Stop: 3% / 4% / 5%
  - Trail: off / on (2.0 ATR after 3%)
  - With/without 15m confirmation

Usage:
    PYTHONPATH=src python run_bb_optimization.py
    PYTHONPATH=src python run_bb_optimization.py --quick     # fewer combos
    PYTHONPATH=src python run_bb_optimization.py --top 20    # show top N
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from itertools import product
from pathlib import Path

# Ensure src/ is on path
_src = str(Path(__file__).resolve().parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

sys.stdout.reconfigure(encoding="utf-8")

from research.bb_swing_backtest import (
    BBConfig,
    fetch_binance_native_daily,
    load_real_4h_data,
    run_bb_backtest,
)


def build_sweep_configs(quick: bool = False) -> list[BBConfig]:
    """Build all parameter combinations."""
    if quick:
        # Quick: key dimensions only
        bb_periods = [20, 60]
        bb_ks = [2.0, 2.5]
        bb_types = ["sma", "ema"]
        targets = ["middle", "opposite"]
        stops = [0.03, 0.04]
        trails = [False, True]
        asymmetrics = [False, True]
        confirms = [False, True]
    else:
        # Full sweep
        bb_periods = [20, 40, 60]
        bb_ks = [2.0, 2.5, 3.0]
        bb_types = ["sma", "ema"]
        targets = ["middle", "opposite"]
        stops = [0.03, 0.04, 0.05]
        trails = [False, True]
        asymmetrics = [False, True]
        confirms = [False, True]

    configs = []
    for period, kk, bbtype, target, stop, trail, asym, confirm in product(
        bb_periods, bb_ks, bb_types, targets, stops, trails, asymmetrics, confirms,
    ):
        # Skip unreasonable combos:
        # - opposite target + trailing (conflict: trail overrides target)
        if target == "opposite" and trail:
            continue
        # - asymmetric (long-only) + opposite target (shorts don't fire anyway)
        if asym and target == "opposite":
            continue

        label = (
            f"BB({period},{kk}){bbtype[0].upper()} "
            f"{'opp' if target == 'opposite' else 'mid'} "
            f"s{int(stop * 100)}% "
            f"{'trail' if trail else 'notr'} "
            f"{'asym' if asym else 'sym'} "
            f"{'15m' if confirm else 'no15m'}"
        )

        configs.append(BBConfig(
            bb_period=period,
            bb_k=kk,
            bb_type=bbtype,
            target_mode=target,
            stop_loss_pct=stop,
            use_trailing_stop=trail,
            trailing_activation_pct=0.03,
            trailing_atr_multiplier=2.0,
            max_hold_bars=180 if trail else 120,
            asymmetric_entry=asym,
            use_15m_confirmation=confirm,
            confirm_max_wait_bars=6,
            use_ma200_filter=True,
            label=label,
        ))

    return configs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Fewer combos")
    parser.add_argument("--top", type=int, default=30, help="Show top N results")
    parser.add_argument("--linear", action="store_true", help="USDT-M linear mode")
    parser.add_argument("--leverage", type=int, default=5, help="Leverage (default 5)")
    parser.add_argument("--initial", type=float, default=10000, help="Initial capital USDT")
    args = parser.parse_args()

    print("Loading BTC 4h data...")
    bars = load_real_4h_data()
    print(f"  {len(bars)} bars: {bars[0]['timestamp']} to {bars[-1]['timestamp']}")
    span_days = (bars[-1]["timestamp"] - bars[0]["timestamp"]).total_seconds() / 86400
    print(f"  Span: {span_days:.0f} days ({span_days / 365.25:.1f} years)")

    print("\nFetching Binance native daily bars...")
    daily_bars = fetch_binance_native_daily(
        symbol="BTCUSDT", start=bars[0]["timestamp"],
    )
    print(f"  {len(daily_bars)} daily bars")

    configs = build_sweep_configs(quick=args.quick)
    print(f"\nSweeping {len(configs)} configurations...")
    print(f"  Mode: {'USDT-M linear' if args.linear else 'COIN-M inverse'}")
    print(f"  Leverage: {args.leverage}x")
    if args.linear:
        print(f"  Initial: ${args.initial:,.0f}")
    print()

    results = []
    t0 = time.time()

    for i, config in enumerate(configs, 1):
        if args.linear:
            r = run_bb_backtest(
                bars_4h=bars, config=config, daily_bars=daily_bars,
                margin_type="linear", initial_capital=args.initial,
                leverage=args.leverage,
            )
        else:
            r = run_bb_backtest(
                bars_4h=bars, config=config, daily_bars=daily_bars,
                initial_btc=1.0, leverage=args.leverage,
            )
        r["_config"] = config
        results.append(r)

        if i % 50 == 0 or i == len(configs):
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            print(f"  [{i:>4d}/{len(configs)}] {rate:.1f} configs/sec, "
                  f"elapsed {elapsed:.0f}s", flush=True)

    elapsed = time.time() - t0
    print(f"\nDone. {len(configs)} configs in {elapsed:.1f}s")

    # ── Sort and display ──

    # Filter out configs with < 10 trades
    valid = [r for r in results if r["total_trades"] >= 10]
    print(f"\nValid configs (>=10 trades): {len(valid)} / {len(results)}")

    # Sort by different criteria
    by_return = sorted(valid, key=lambda r: r["total_return_pct"], reverse=True)
    by_rdd = sorted(valid, key=lambda r: r["r_dd"], reverse=True)
    by_sharpe = sorted(valid, key=lambda r: r["sharpe"], reverse=True)

    def _print_table(title: str, rows: list[dict], n: int) -> None:
        print(f"\n{'=' * 140}")
        print(f"  {title} (top {n})")
        print(f"{'=' * 140}")
        header = (
            f"{'#':>3s}  {'Config':>45s}  {'Return%':>8s}  {'DD%':>6s}  {'R/DD':>5s}  "
            f"{'Trades':>6s}  {'WR%':>5s}  {'PF':>5s}  {'Sharpe':>6s}  "
            f"{'AvgWin%':>8s}  {'AvgLoss%':>8s}"
        )
        print(header)
        print("-" * 140)
        for i, r in enumerate(rows[:n], 1):
            label = r.get("config_label", "?")
            final = r.get("final_capital", r.get("final_btc", 0))
            print(
                f"{i:>3d}  {label:>45s}  {r['total_return_pct']:>+7.1f}%  "
                f"{r['max_drawdown_pct']:>5.1f}%  {r['r_dd']:>5.2f}  "
                f"{r['total_trades']:>6d}  {r['win_rate']:>4.1f}%  "
                f"{r['profit_factor']:>5.2f}  {r['sharpe']:>6.2f}  "
                f"{r['avg_win_pct']:>+7.2f}%  {r['avg_loss_pct']:>+7.2f}%"
            )

    top_n = args.top
    _print_table("TOP by RETURN %", by_return, top_n)
    _print_table("TOP by R/DD (risk-adjusted)", by_rdd, top_n)
    _print_table("TOP by SHARPE", by_sharpe, top_n)

    # ── Best config summary ──
    if by_return:
        best = by_return[0]
        print(f"\n{'=' * 140}")
        print(f"  BEST OVERALL: {best.get('config_label', '?')}")
        print(f"  Return: {best['total_return_pct']:+.1f}%")
        print(f"  Max DD: {best['max_drawdown_pct']:.1f}%")
        print(f"  R/DD: {best['r_dd']:.2f}")
        print(f"  Trades: {best['total_trades']} | WR: {best['win_rate']:.1f}%")
        print(f"  Sharpe: {best['sharpe']:.2f} | PF: {best['profit_factor']:.2f}")
        if args.linear:
            print(f"  Final capital: ${best.get('final_capital', 0):,.0f}")
        else:
            print(f"  Final BTC: {best.get('final_btc', 0):.4f}")
        print(f"  Exit reasons: {best.get('exit_reasons', {})}")
        print(f"{'=' * 140}")

    # ── Dimension analysis: which parameters help? ──
    print(f"\n{'=' * 140}")
    print("  DIMENSION ANALYSIS — Average return by parameter value")
    print(f"{'=' * 140}")

    def _avg_return(configs_list: list[dict]) -> float:
        if not configs_list:
            return 0.0
        return sum(r["total_return_pct"] for r in configs_list) / len(configs_list)

    # BB period
    for period in [20, 40, 60]:
        subset = [r for r in valid if r["_config"].bb_period == period]
        print(f"  BB period={period:>3d}: avg return {_avg_return(subset):>+7.1f}% ({len(subset)} configs)")

    # BB type
    for bbt in ["sma", "ema"]:
        subset = [r for r in valid if r["_config"].bb_type == bbt]
        print(f"  BB type={bbt:>4s}: avg return {_avg_return(subset):>+7.1f}% ({len(subset)} configs)")

    # BB k
    for kk in [2.0, 2.5, 3.0]:
        subset = [r for r in valid if r["_config"].bb_k == kk]
        if subset:
            print(f"  BB k={kk:>4.1f}:    avg return {_avg_return(subset):>+7.1f}% ({len(subset)} configs)")

    # Target mode
    for tgt in ["middle", "opposite"]:
        subset = [r for r in valid if r["_config"].target_mode == tgt]
        print(f"  target={tgt:>8s}: avg return {_avg_return(subset):>+7.1f}% ({len(subset)} configs)")

    # Stop loss
    for stop in [0.03, 0.04, 0.05]:
        subset = [r for r in valid if r["_config"].stop_loss_pct == stop]
        print(f"  stop={int(stop*100):>2d}%:      avg return {_avg_return(subset):>+7.1f}% ({len(subset)} configs)")

    # Trail
    for trail in [False, True]:
        subset = [r for r in valid if r["_config"].use_trailing_stop == trail]
        label = "on " if trail else "off"
        print(f"  trail={label:>3s}:     avg return {_avg_return(subset):>+7.1f}% ({len(subset)} configs)")

    # Asymmetric
    for asym in [False, True]:
        subset = [r for r in valid if r["_config"].asymmetric_entry == asym]
        label = "asym" if asym else "sym "
        print(f"  entry={label:>4s}:    avg return {_avg_return(subset):>+7.1f}% ({len(subset)} configs)")

    # 15m confirm
    for conf in [False, True]:
        subset = [r for r in valid if r["_config"].use_15m_confirmation == conf]
        label = "15m " if conf else "no15"
        print(f"  confirm={label:>4s}:  avg return {_avg_return(subset):>+7.1f}% ({len(subset)} configs)")

    print()


if __name__ == "__main__":
    main()
