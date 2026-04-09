#!/usr/bin/env python
"""Deep sweep around best configurations from optimization round 1.

Focus: BB(20) period, k=2.0-3.0, SMA/EMA, risk_per_trade 5-8%.
"""

from __future__ import annotations

import sys
import time
from itertools import product
from pathlib import Path

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


def main() -> None:
    print("Loading BTC data...")
    bars = load_real_4h_data()
    daily_bars = fetch_binance_native_daily(symbol="BTCUSDT", start=bars[0]["timestamp"])
    print(f"  {len(bars)} 4h bars, {len(daily_bars)} daily bars\n")

    leverage = 5
    initial = 10000

    # Deep sweep parameters
    configs = []
    for period, kk, bbtype, target, stop, trail, risk, confirm in product(
        [20, 30],                       # BB period
        [2.0, 2.25, 2.5, 2.75, 3.0],   # BB multiplier (fine grain)
        ["sma", "ema"],                  # BB type
        ["middle", "opposite"],          # target
        [0.03, 0.035, 0.04],            # stop
        [False, True],                   # trailing
        [0.05, 0.065, 0.08],            # risk per trade
        [False, True],                   # 15m confirm
    ):
        if target == "opposite" and trail:
            continue

        label = (
            f"BB({period},{kk:.2f}){bbtype[0].upper()} "
            f"{'opp' if target == 'opposite' else 'mid'} "
            f"s{stop*100:.1f}% r{risk*100:.1f}% "
            f"{'tr' if trail else '--'} "
            f"{'15m' if confirm else '---'}"
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
            use_15m_confirmation=confirm,
            confirm_max_wait_bars=6,
            use_ma200_filter=True,
            risk_per_trade=risk,
            label=label,
        ))

    print(f"Sweeping {len(configs)} configurations (5x leverage, $10K)...")
    results = []
    t0 = time.time()

    for i, config in enumerate(configs, 1):
        r = run_bb_backtest(
            bars_4h=bars, config=config, daily_bars=daily_bars,
            margin_type="linear", initial_capital=initial, leverage=leverage,
        )
        r["_config"] = config
        results.append(r)
        if i % 100 == 0 or i == len(configs):
            elapsed = time.time() - t0
            print(f"  [{i:>4d}/{len(configs)}] {elapsed:.0f}s", flush=True)

    elapsed = time.time() - t0
    print(f"\nDone. {len(configs)} in {elapsed:.1f}s")

    valid = [r for r in results if r["total_trades"] >= 10]
    print(f"Valid (>=10 trades): {len(valid)}")

    # Top 25 by return
    by_return = sorted(valid, key=lambda r: r["total_return_pct"], reverse=True)
    by_rdd = sorted(valid, key=lambda r: r["r_dd"], reverse=True)
    by_sharpe = sorted(valid, key=lambda r: r["sharpe"], reverse=True)

    def _show(title, rows, n=25):
        print(f"\n{'=' * 155}")
        print(f"  {title}")
        print(f"{'=' * 155}")
        hdr = (
            f"{'#':>3s}  {'Config':>50s}  {'Return%':>8s}  {'Final$':>9s}  {'DD%':>6s}  "
            f"{'R/DD':>5s}  {'Trades':>6s}  {'WR%':>5s}  {'PF':>5s}  {'Sharpe':>6s}"
        )
        print(hdr)
        print("-" * 155)
        for i, r in enumerate(rows[:n], 1):
            label = r.get("config_label", "?")
            final = r.get("final_capital", 0)
            print(
                f"{i:>3d}  {label:>50s}  {r['total_return_pct']:>+7.1f}%  "
                f"${final:>8,.0f}  {r['max_drawdown_pct']:>5.1f}%  "
                f"{r['r_dd']:>5.2f}  {r['total_trades']:>6d}  "
                f"{r['win_rate']:>4.1f}%  {r['profit_factor']:>5.2f}  "
                f"{r['sharpe']:>6.2f}"
            )

    _show("TOP 25 by RETURN", by_return)
    _show("TOP 25 by R/DD", by_rdd)
    _show("TOP 25 by SHARPE", by_sharpe)

    # Best overall
    if by_return:
        b = by_return[0]
        print(f"\n{'='*80}")
        print(f"  BEST: {b.get('config_label','?')}")
        print(f"  Return: {b['total_return_pct']:+.1f}% | ${b.get('final_capital',0):,.0f}")
        print(f"  DD: {b['max_drawdown_pct']:.1f}% | R/DD: {b['r_dd']:.2f} | Sharpe: {b['sharpe']:.2f}")
        print(f"  Trades: {b['total_trades']} | WR: {b['win_rate']:.1f}% | PF: {b['profit_factor']:.2f}")
        print(f"  Exits: {b.get('exit_reasons', {})}")
        print(f"{'='*80}")

    # Dimension analysis
    print(f"\n{'='*80}")
    print("  DIMENSION ANALYSIS")
    print(f"{'='*80}")

    def _dim(name, key, vals):
        for v in vals:
            sub = [r for r in valid if getattr(r["_config"], key) == v]
            if sub:
                avg_ret = sum(r["total_return_pct"] for r in sub) / len(sub)
                avg_rdd = sum(r["r_dd"] for r in sub) / len(sub)
                print(f"  {name}={str(v):>6s}: avg ret {avg_ret:>+7.1f}%, avg R/DD {avg_rdd:>5.2f} ({len(sub)} cfgs)")

    _dim("period", "bb_period", [20, 30])
    _dim("k", "bb_k", [2.0, 2.25, 2.5, 2.75, 3.0])
    _dim("type", "bb_type", ["sma", "ema"])
    _dim("target", "target_mode", ["middle", "opposite"])
    _dim("stop", "stop_loss_pct", [0.03, 0.035, 0.04])
    _dim("trail", "use_trailing_stop", [False, True])
    _dim("risk", "risk_per_trade", [0.05, 0.065, 0.08])
    _dim("15m", "use_15m_confirmation", [False, True])
    print()


if __name__ == "__main__":
    main()
