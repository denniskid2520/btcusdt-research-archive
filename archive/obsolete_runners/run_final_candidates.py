#!/usr/bin/env python
"""Final candidate configs from optimization."""

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
    print(f"Data: {len(bars)} 4h bars, {len(daily)} daily\n")

    candidates = [
        # Original Strategy D (for comparison)
        BBConfig(
            bb_period=20, bb_k=2.5, bb_type="sma", target_mode="middle",
            stop_loss_pct=0.03, risk_per_trade=0.065,
            use_ma200_filter=True,
            label="[OLD] BB(20,2.5) r6.5% 5x",
        ),
        # Previous best with 15m confirm
        BBConfig(
            bb_period=20, bb_k=2.5, bb_type="sma", target_mode="middle",
            stop_loss_pct=0.03, risk_per_trade=0.065,
            use_ma200_filter=True,
            use_15m_confirmation=True, confirm_max_wait_bars=6,
            use_trailing_stop=True, trailing_activation_pct=0.03,
            trailing_atr_multiplier=2.0, max_hold_bars=180,
            label="[PREV BEST] +trail+15m r6.5%",
        ),
        # ── NEW CANDIDATES from optimization ──
        # A: Maximum return
        BBConfig(
            bb_period=20, bb_k=2.5, bb_type="sma", target_mode="middle",
            stop_loss_pct=0.03, risk_per_trade=0.10,
            use_ma200_filter=True,
            label="[A] MAX RETURN r10%",
        ),
        # B: Best balanced (high return + reasonable DD)
        BBConfig(
            bb_period=20, bb_k=2.5, bb_type="sma", target_mode="middle",
            stop_loss_pct=0.035, risk_per_trade=0.08,
            use_ma200_filter=True,
            use_trailing_stop=True, trailing_activation_pct=0.03,
            trailing_atr_multiplier=2.0, max_hold_bars=180,
            use_15m_confirmation=True, confirm_max_wait_bars=6,
            label="[B] BALANCED tr+15m s3.5% r8%",
        ),
        # C: Best R/DD
        BBConfig(
            bb_period=20, bb_k=2.25, bb_type="sma", target_mode="middle",
            stop_loss_pct=0.035, risk_per_trade=0.08,
            use_ma200_filter=True,
            use_trailing_stop=True, trailing_activation_pct=0.03,
            trailing_atr_multiplier=2.0, max_hold_bars=180,
            use_15m_confirmation=True, confirm_max_wait_bars=6,
            label="[C] BEST R/DD k=2.25 tr+15m",
        ),
        # D: Best Sharpe
        BBConfig(
            bb_period=20, bb_k=2.5, bb_type="sma", target_mode="middle",
            stop_loss_pct=0.035, risk_per_trade=0.065,
            use_ma200_filter=True,
            use_trailing_stop=True, trailing_activation_pct=0.03,
            trailing_atr_multiplier=2.0, max_hold_bars=180,
            use_15m_confirmation=True, confirm_max_wait_bars=6,
            label="[D] BEST SHARPE s3.5% r6.5%",
        ),
        # E: Best balanced + 10% risk
        BBConfig(
            bb_period=20, bb_k=2.5, bb_type="sma", target_mode="middle",
            stop_loss_pct=0.035, risk_per_trade=0.10,
            use_ma200_filter=True,
            use_trailing_stop=True, trailing_activation_pct=0.03,
            trailing_atr_multiplier=2.0, max_hold_bars=180,
            use_15m_confirmation=True, confirm_max_wait_bars=6,
            label="[E] BALANCED r10% tr+15m",
        ),
        # F: Simple, no trail, high risk
        BBConfig(
            bb_period=20, bb_k=2.5, bb_type="sma", target_mode="middle",
            stop_loss_pct=0.03, risk_per_trade=0.08,
            use_ma200_filter=True,
            label="[F] SIMPLE r8%",
        ),
    ]

    leverage = 5
    initial = 10000

    print(f"{'Config':>40s} | {'Return%':>8s} | {'Final$':>9s} | {'DD%':>6s} | {'R/DD':>6s} | {'Trades':>6s} | {'WR%':>5s} | {'PF':>5s} | {'Sharpe':>6s} | {'AvgW%':>7s} | {'AvgL%':>7s}")
    print("-" * 145)

    for cfg in candidates:
        r = run_bb_backtest(
            bars_4h=bars, config=cfg, daily_bars=daily,
            margin_type="linear", initial_capital=initial, leverage=leverage,
        )
        final = r.get("final_capital", 0)
        print(
            f"{cfg.label:>40s} | {r['total_return_pct']:>+7.1f}% | ${final:>8,.0f} | "
            f"{r['max_drawdown_pct']:>5.1f}% | {r['r_dd']:>5.2f} | "
            f"{r['total_trades']:>6d} | {r['win_rate']:>4.1f}% | "
            f"{r['profit_factor']:>5.2f} | {r['sharpe']:>6.2f} | "
            f"{r['avg_win_pct']:>+6.2f}% | {r['avg_loss_pct']:>+6.2f}%"
        )
        exits = r.get("exit_reasons", {})
        parts = ", ".join(f"{k}={v}" for k, v in sorted(exits.items()))
        print(f"{'':>40s}   exits: {parts}")


if __name__ == "__main__":
    main()
