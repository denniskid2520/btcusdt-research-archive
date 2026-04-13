#!/usr/bin/env python
"""Test leverage impact on best configs."""

from __future__ import annotations
import sys
from pathlib import Path

_src = str(Path(__file__).resolve().parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)
sys.stdout.reconfigure(encoding="utf-8")

from research.bb_swing_backtest import (
    BBConfig, fetch_binance_native_daily, load_real_4h_data, run_bb_backtest,
)


def main():
    bars = load_real_4h_data()
    daily = fetch_binance_native_daily(symbol="BTCUSDT", start=bars[0]["timestamp"])
    print(f"Data: {len(bars)} 4h bars\n")

    # Top 3 configs from round 1
    best_configs = [
        BBConfig(  # #1 best return
            bb_period=20, bb_k=2.0, bb_type="ema", target_mode="opposite",
            stop_loss_pct=0.03, use_ma200_filter=True,
            label="BB(20,2.0)E opp s3%",
        ),
        BBConfig(  # #2 best R/DD
            bb_period=20, bb_k=2.5, bb_type="sma", target_mode="middle",
            stop_loss_pct=0.03, use_ma200_filter=True,
            label="BB(20,2.5)S mid s3%",
        ),
        BBConfig(  # #3 best Sharpe
            bb_period=20, bb_k=2.5, bb_type="sma", target_mode="middle",
            stop_loss_pct=0.03, use_ma200_filter=True,
            use_trailing_stop=True, trailing_activation_pct=0.03,
            trailing_atr_multiplier=2.0, max_hold_bars=180,
            use_15m_confirmation=True, confirm_max_wait_bars=6,
            label="BB(20,2.5)S mid s3% trail+15m",
        ),
    ]

    leverages = [3, 5, 7, 10]
    risk_levels = [0.05, 0.065, 0.08, 0.10]

    print(f"{'Config':>35s} | {'Lev':>3s} | {'Risk%':>5s} | {'Return%':>8s} | {'Final$':>9s} | {'DD%':>6s} | {'R/DD':>5s} | {'Trades':>6s} | {'WR%':>5s}")
    print("-" * 120)

    for cfg in best_configs:
        for lev in leverages:
            for risk in risk_levels:
                cfg.risk_per_trade = risk
                r = run_bb_backtest(
                    bars_4h=bars, config=cfg, daily_bars=daily,
                    margin_type="linear", initial_capital=10000, leverage=lev,
                )
                final = r.get("final_capital", 0)
                print(
                    f"{cfg.label:>35s} | {lev:>3d}x | {risk*100:>4.1f}% | "
                    f"{r['total_return_pct']:>+7.1f}% | ${final:>8,.0f} | "
                    f"{r['max_drawdown_pct']:>5.1f}% | {r['r_dd']:>5.2f} | "
                    f"{r['total_trades']:>6d} | {r['win_rate']:>4.1f}%"
                )
        print()


if __name__ == "__main__":
    main()
