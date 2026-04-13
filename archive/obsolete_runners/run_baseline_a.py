"""Run Strategy C Baseline A on the aligned 15m dataset and print the report.

Pipeline:
    1. Load strategy_c_btcusdt_15m.csv      (4500 bars, 46.9 days)
    2. Compute minimal features              (5 features + warmup drop)
    3. Generate Baseline A signals           (4 conditions per side)
    4. Simulate trade-by-trade               (hold=3 bars, opposite-signal exit)
    5. Report 9 metrics + signal/trade breakdown

Usage:
    python run_baseline_a.py
"""
from __future__ import annotations

import sys
from collections import Counter

sys.path.insert(0, "src")

from data.strategy_c_dataset import load_strategy_c_csv
from data.strategy_c_features import compute_features
from strategies.strategy_c_baseline_a import baseline_a_signals
from research.backtest_strategy_c import run_strategy_c_backtest


DATASET_CSV = "src/data/strategy_c_btcusdt_15m.csv"


def main() -> None:
    print("=" * 70)
    print("Strategy C — Baseline A")
    print("=" * 70)
    print()

    # 1. Load aligned dataset
    print(f"Loading dataset from {DATASET_CSV}...")
    bars = load_strategy_c_csv(DATASET_CSV)
    print(f"  {len(bars)} bars loaded")
    print(f"  Range: {bars[0].timestamp.isoformat()} → {bars[-1].timestamp.isoformat()}")
    span_days = (bars[-1].timestamp - bars[0].timestamp).total_seconds() / 86400
    print(f"  Span:  {span_days:.1f} days")
    print(f"  Price: ${bars[0].close:,.0f} → ${bars[-1].close:,.0f}")
    print()

    # 2. Compute features (warmup drops the first 95 bars for z_96)
    print("Computing features...")
    feats = compute_features(bars)  # warmup=True drops incomplete rows
    print(f"  {len(feats)} feature bars (warmup dropped {len(bars) - len(feats)} bars)")
    print()

    # 3. Generate signals
    print("Generating Baseline A signals...")
    signals = baseline_a_signals(feats)
    counts = Counter(signals)
    total = len(signals)
    print(f"  Long  signals: {counts[1]:>5}  ({100 * counts[1] / total:5.2f}%)")
    print(f"  Short signals: {counts[-1]:>5}  ({100 * counts[-1] / total:5.2f}%)")
    print(f"  Flat:          {counts[0]:>5}  ({100 * counts[0] / total:5.2f}%)")
    print()

    # 4. Backtest
    print("Running backtest (hold=3, fee=0.05%/side, slip=0.01%/side)...")
    result = run_strategy_c_backtest(
        feats, signals,
        hold_bars=3,
        fee_per_side=0.0005,
        slippage_per_side=0.0001,
    )
    print(f"  {len(result.trades)} trades executed")
    print()

    # 5. Report
    print("=" * 70)
    print("Baseline A Metrics")
    print("=" * 70)
    m = result.metrics
    print(f"  Trades       : {int(m['num_trades']):>10d}")
    print(f"  Net PnL      : {m['net_pnl'] * 100:>+9.2f}%")
    print(f"  Avg PnL/trd  : {m['avg_pnl'] * 100:>+9.4f}%")
    print(f"  Win rate     : {m['win_rate'] * 100:>9.2f}%")
    print(f"  Max DD       : {m['max_dd'] * 100:>9.2f}%")
    print(f"  Trade Sharpe : {m['trade_sharpe']:>10.4f}")
    print(f"  Trade Sortino: {m['trade_sortino']:>10.4f}")
    print(f"  Turnover     : {m['turnover']:>10.0f}")
    print(f"  Avg hold bars: {m['avg_hold_bars']:>10.2f}")
    print()

    if result.trades:
        longs = [t for t in result.trades if t.side == 1]
        shorts = [t for t in result.trades if t.side == -1]
        print(f"  Long  trades : {len(longs):>4}   "
              f"net {sum(t.pnl_net for t in longs) * 100:>+6.2f}%   "
              f"win {sum(1 for t in longs if t.pnl_net > 0) / max(len(longs), 1) * 100:>5.1f}%")
        print(f"  Short trades : {len(shorts):>4}   "
              f"net {sum(t.pnl_net for t in shorts) * 100:>+6.2f}%   "
              f"win {sum(1 for t in shorts if t.pnl_net > 0) / max(len(shorts), 1) * 100:>5.1f}%")
        print()
        print(f"  Equity final : {result.equity_curve[-1]:.4f}  ({(result.equity_curve[-1] - 1) * 100:+.2f}%)")


if __name__ == "__main__":
    main()
