"""Trade-level analysis for diagnosing backtest results on real data.

Outputs each trade with entry/exit context so we can see exactly which
trades are losing money and why.

Usage:
    python -m research.trade_analysis --csv data/btcusdt_4h_real.csv
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

from data.backfill import load_bars_from_csv
from execution.paper_broker import PaperBroker
from research.backtest import BacktestResult, build_default_strategy, run_backtest
from risk.limits import RiskLimits


def analyze_trades(result: BacktestResult) -> None:
    print(f"\n{'='*90}")
    print(f"  TRADE-LEVEL ANALYSIS — {result.total_trades} trades")
    print(f"  Initial: ${result.initial_cash:,.0f}  Final: ${result.final_equity:,.0f}  "
          f"Return: {result.total_return_pct:+.2f}%  MaxDD: {result.max_drawdown_pct:.2f}%")
    print(f"{'='*90}\n")

    # Group trades by rule
    by_rule: dict[str, list] = {}
    for trade in result.trades:
        by_rule.setdefault(trade.entry_rule, []).append(trade)

    for rule_name in sorted(by_rule):
        trades = by_rule[rule_name]
        total_pnl = sum(t.pnl for t in trades)
        wins = sum(1 for t in trades if t.pnl > 0)
        losses = len(trades) - wins
        print(f"  ── {rule_name} ({len(trades)} trades, {wins}W/{losses}L, PnL: ${total_pnl:+,.0f}) ──")
        for i, t in enumerate(trades, 1):
            icon = "W" if t.pnl > 0 else "L"
            print(
                f"    [{icon}] {t.entry_time.strftime('%Y-%m-%d %H:%M')} → "
                f"{t.exit_time.strftime('%Y-%m-%d %H:%M')}  "
                f"{t.side} {t.entry_price:,.0f}→{t.exit_price:,.0f}  "
                f"PnL: ${t.pnl:+,.0f}  ({t.return_pct:+.2f}%)  "
                f"exit: {t.exit_reason}"
            )
        print()

    # Summary
    print(f"  {'─'*70}")
    print(f"  PnL by rule:")
    for rule_name in sorted(by_rule):
        trades = by_rule[rule_name]
        total_pnl = sum(t.pnl for t in trades)
        wins = sum(1 for t in trades if t.pnl > 0)
        wr = (wins / len(trades) * 100) if trades else 0
        print(f"    {rule_name:50s}  ${total_pnl:>+8,.0f}  ({wr:.0f}% WR)")
    total = sum(t.pnl for t in result.trades)
    print(f"    {'TOTAL':50s}  ${total:>+8,.0f}")
    print()

    # Time analysis
    print(f"  Average holding period by rule:")
    for rule_name in sorted(by_rule):
        trades = by_rule[rule_name]
        durations = [(t.exit_time - t.entry_time).total_seconds() / 3600 for t in trades]
        avg_hrs = sum(durations) / len(durations) if durations else 0
        print(f"    {rule_name:50s}  {avg_hrs:.0f}h avg")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Trade-level backtest analysis")
    parser.add_argument("--csv", required=True, help="Path to CSV with real klines")
    parser.add_argument("--symbol", default="BTCUSDT")
    args = parser.parse_args()

    bars = load_bars_from_csv(args.csv)
    print(f"Loaded {len(bars)} bars: {bars[0].timestamp} → {bars[-1].timestamp}")
    print(f"Price range: {min(b.low for b in bars):,.0f} → {max(b.high for b in bars):,.0f}")

    strategy = build_default_strategy()
    result = run_backtest(
        bars=bars,
        symbol=args.symbol,
        strategy=strategy,
        broker=PaperBroker(initial_cash=100_000.0, fee_rate=0.001, slippage_rate=0.0005),
        limits=RiskLimits(),
    )
    analyze_trades(result)


if __name__ == "__main__":
    main()
