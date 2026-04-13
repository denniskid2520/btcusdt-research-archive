#!/usr/bin/env python
"""Runner for BB Swing Strategy D — 10-configuration parameter sweep.

Usage:
    PYTHONPATH=src python run_bb_swing_backtest.py
    PYTHONPATH=src python run_bb_swing_backtest.py --config 1     # run single config
    PYTHONPATH=src python run_bb_swing_backtest.py --best-log     # full trade log for best
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

from research.bb_swing_backtest import (
    BBConfig,
    _print_result,
    fetch_binance_native_daily,
    load_real_4h_data,
    run_bb_backtest,
)


# ===========================================================================
# 10 configurations to sweep
# ===========================================================================

def build_configs() -> list[BBConfig]:
    """Build the 10 test configurations."""
    return [
        # 1. Classic BB(20,2.0) + MA200 filter, target=middle
        BBConfig(
            bb_period=20, bb_k=2.0, target_mode="middle",
            use_ma200_filter=True,
            label="#1 BB(20,2.0) middle + MA200",
        ),
        # 2. BB(20,2.0) target=opposite band (more aggressive)
        BBConfig(
            bb_period=20, bb_k=2.0, target_mode="opposite",
            use_ma200_filter=True,
            label="#2 BB(20,2.0) opposite + MA200",
        ),
        # 3. BB(30,2.0) longer period, smoother
        BBConfig(
            bb_period=30, bb_k=2.0, target_mode="middle",
            use_ma200_filter=True,
            label="#3 BB(30,2.0) middle + MA200",
        ),
        # 4. BB(20,1.5) tighter bands, more trades
        BBConfig(
            bb_period=20, bb_k=1.5, target_mode="middle",
            use_ma200_filter=True,
            label="#4 BB(20,1.5) middle + MA200",
        ),
        # 5. BB(20,2.5) wider bands, fewer but high-conviction
        BBConfig(
            bb_period=20, bb_k=2.5, target_mode="middle",
            use_ma200_filter=True,
            label="#5 BB(20,2.5) middle + MA200",
        ),
        # 6. BB(50,2.0) long-term mean reversion
        BBConfig(
            bb_period=50, bb_k=2.0, target_mode="middle",
            use_ma200_filter=True,
            label="#6 BB(50,2.0) middle + MA200",
        ),
        # 7. BB(20,2.0) + RSI(3) confirmation
        BBConfig(
            bb_period=20, bb_k=2.0, target_mode="middle",
            use_ma200_filter=True, use_rsi_filter=True,
            rsi_period=3, rsi_oversold=30, rsi_overbought=70,
            label="#7 BB(20,2.0) + RSI(3)",
        ),
        # 8. BB(20,2.0) + ADX<25 (ranging markets only)
        BBConfig(
            bb_period=20, bb_k=2.0, target_mode="middle",
            use_ma200_filter=True, use_adx_filter=True,
            adx_threshold=25,
            label="#8 BB(20,2.0) + ADX<25",
        ),
        # 9. BB(20,2.0) + RSI + ADX + MA200 (full filter stack)
        BBConfig(
            bb_period=20, bb_k=2.0, target_mode="middle",
            use_ma200_filter=True, use_rsi_filter=True, use_adx_filter=True,
            rsi_period=3, rsi_oversold=30, rsi_overbought=70,
            adx_threshold=25,
            label="#9 BB(20,2.0) full stack",
        ),
        # 10. BB(20,2.0) + trailing stop (let winners run)
        BBConfig(
            bb_period=20, bb_k=2.0, target_mode="middle",
            use_ma200_filter=True, use_trailing_stop=True,
            trailing_activation_pct=0.03, trailing_atr_multiplier=2.0,
            max_hold_bars=180,  # longer hold for trailing
            label="#10 BB(20,2.0) + trailing",
        ),
    ]


# ===========================================================================
# Output formatting
# ===========================================================================

def print_trade_log(result: dict) -> None:
    """Print full trade log for a single config."""
    trades = result["trades"]
    if not trades:
        print("  No trades.")
        return

    header = (
        f"{'Date':>12s}  {'Side':>5s}  {'Entry':>10s}  {'Exit':>10s}  "
        f"{'Reason':>16s}  {'PnL BTC':>10s}  {'PnL%':>7s}  {'Days':>5s}  "
        f"{'BB-Up':>10s}  {'BB-Mid':>10s}  {'BB-Lo':>10s}  {'BW%':>6s}"
    )
    print(header)
    print("-" * len(header))

    for t in trades:
        entry_date = t["entry_ts"].strftime("%Y-%m-%d") if t["entry_ts"] else "N/A"
        print(
            f"{entry_date:>12s}  {t['side']:>5s}  {t['entry_price']:>10,.0f}  {t['exit_price']:>10,.0f}  "
            f"{t['exit_reason']:>16s}  {t['pnl']:>+10.4f}  {t['pnl_pct']:>+6.1f}%  "
            f"{t['duration_days']:>5.1f}  "
            f"{t['bb_upper']:>10,.0f}  {t['bb_middle']:>10,.0f}  {t['bb_lower']:>10,.0f}  "
            f"{t['bb_width_pct']:>5.1f}%"
        )


def print_comparison_table(results: list[dict]) -> None:
    """Print the 10-config comparison table."""
    print("\n")
    print("=" * 130)
    print("  COMPARISON TABLE — BB Swing Strategy D — All 10 Configurations")
    print("=" * 130)
    header = (
        f"{'#':>3s}  {'Config':>35s}  {'Return%':>8s}  {'DD%':>6s}  {'R/DD':>5s}  "
        f"{'Trades':>6s}  {'WR%':>5s}  {'PF':>5s}  {'Sharpe':>6s}  "
        f"{'AvgWin%':>8s}  {'AvgLoss%':>8s}  {'Days':>5s}  {'Tr/Yr':>5s}"
    )
    print(header)
    print("-" * 130)

    for i, r in enumerate(results, 1):
        label = r.get("config_label", f"Config {i}")
        print(
            f"{i:>3d}  {label:>35s}  {r['total_return_pct']:>+7.1f}%  "
            f"{r['max_drawdown_pct']:>5.1f}%  {r['r_dd']:>5.2f}  "
            f"{r['total_trades']:>6d}  {r['win_rate']:>4.1f}%  "
            f"{r['profit_factor']:>5.2f}  {r['sharpe']:>6.2f}  "
            f"{r['avg_win_pct']:>+7.2f}%  {r['avg_loss_pct']:>+7.2f}%  "
            f"{r['avg_duration_days']:>5.1f}  {r['trades_per_year']:>5.1f}"
        )

    print("-" * 130)

    # Find best by R/DD
    best_idx = max(range(len(results)), key=lambda x: results[x]["r_dd"])
    best = results[best_idx]
    print(f"\n  BEST by R/DD: #{best_idx + 1} {best.get('config_label', '')} "
          f"-> {best['total_return_pct']:+.1f}% return, {best['max_drawdown_pct']:.1f}% DD, "
          f"R/DD {best['r_dd']:.2f}")

    # Find best by return
    best_ret_idx = max(range(len(results)), key=lambda x: results[x]["total_return_pct"])
    best_ret = results[best_ret_idx]
    print(f"  BEST by Return: #{best_ret_idx + 1} {best_ret.get('config_label', '')} "
          f"-> {best_ret['total_return_pct']:+.1f}%")

    # Find best by Sharpe
    best_sharpe_idx = max(range(len(results)), key=lambda x: results[x]["sharpe"])
    best_sharpe = results[best_sharpe_idx]
    print(f"  BEST by Sharpe: #{best_sharpe_idx + 1} {best_sharpe.get('config_label', '')} "
          f"-> {best_sharpe['sharpe']:.2f}")

    # Exit reason breakdown for each config
    print(f"\n{'=' * 130}")
    print("  EXIT REASON BREAKDOWN")
    print(f"{'=' * 130}")
    for i, r in enumerate(results, 1):
        reasons = r.get("exit_reasons", {})
        parts = ", ".join(f"{k}={v}" for k, v in sorted(reasons.items()))
        label = r.get("config_label", f"Config {i}")
        print(f"  #{i:>2d} {label:>35s}: {parts}")

    print()


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="BB Swing Strategy D — Parameter Sweep")
    parser.add_argument("--config", type=int, default=0,
                        help="Run a single config (1-10), 0=all")
    parser.add_argument("--best-log", action="store_true",
                        help="Print full trade log for best config")
    parser.add_argument("--all-logs", action="store_true",
                        help="Print trade log for every config")
    parser.add_argument("--native-daily", action="store_true",
                        help="Use Binance native 1d bars instead of 4h aggregation")
    args = parser.parse_args()

    print("Loading real BTC 4h data...")
    bars = load_real_4h_data()
    print(f"  {len(bars)} bars: {bars[0]['timestamp']} to {bars[-1]['timestamp']}")
    span_days = (bars[-1]["timestamp"] - bars[0]["timestamp"]).total_seconds() / 86400
    print(f"  Span: {span_days:.0f} days ({span_days / 365.25:.1f} years)")

    daily_bars = None
    if args.native_daily:
        print("\nFetching Binance native 1d bars...")
        start_dt = bars[0]["timestamp"]
        daily_bars = fetch_binance_native_daily(
            symbol="BTCUSDT", start=start_dt,
        )
        print(f"  {len(daily_bars)} daily bars: {daily_bars[0]['timestamp']} to {daily_bars[-1]['timestamp']}")
    print()

    configs = build_configs()
    results: list[dict] = []

    if args.config > 0:
        # Single config
        idx = args.config - 1
        if idx >= len(configs):
            print(f"Error: config {args.config} out of range (1-{len(configs)})")
            return
        config = configs[idx]
        print(f"Running config #{args.config}: {config.label}")
        result = run_bb_backtest(bars_4h=bars, config=config, initial_btc=1.0, leverage=3,
                                 daily_bars=daily_bars)
        _print_result(result)
        print("\nFull trade log:")
        print_trade_log(result)
        return

    # All configs
    for i, config in enumerate(configs, 1):
        print(f"  [{i:>2d}/{len(configs)}] {config.label} ...", end="", flush=True)
        result = run_bb_backtest(bars_4h=bars, config=config, initial_btc=1.0, leverage=3,
                                 daily_bars=daily_bars)
        results.append(result)
        print(f" {result['total_return_pct']:+.1f}% | {result['total_trades']} trades | "
              f"DD {result['max_drawdown_pct']:.1f}%")

    # Print individual summaries
    for r in results:
        _print_result(r)

    # Comparison table
    print_comparison_table(results)

    # Best config trade log
    if args.best_log or args.all_logs:
        if args.all_logs:
            for i, r in enumerate(results, 1):
                print(f"\n{'=' * 100}")
                print(f"  TRADE LOG — #{i} {r.get('config_label', '')}")
                print(f"{'=' * 100}")
                print_trade_log(r)
        else:
            best_idx = max(range(len(results)), key=lambda x: results[x]["r_dd"])
            best = results[best_idx]
            print(f"\n{'=' * 100}")
            print(f"  FULL TRADE LOG — BEST CONFIG #{best_idx + 1}: {best.get('config_label', '')}")
            print(f"{'=' * 100}")
            print_trade_log(best)


if __name__ == "__main__":
    main()
