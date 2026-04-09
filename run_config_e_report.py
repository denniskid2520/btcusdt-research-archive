#!/usr/bin/env python
"""Config [E] report — user's exact format."""

from __future__ import annotations
import sys
from datetime import datetime
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

    config = BBConfig(
        bb_period=20, bb_k=2.5, bb_type="sma", target_mode="middle",
        stop_loss_pct=0.035, risk_per_trade=0.10,
        use_ma200_filter=True, use_trailing_stop=True,
        trailing_activation_pct=0.03, trailing_atr_multiplier=2.0,
        max_hold_bars=180, use_15m_confirmation=True, confirm_max_wait_bars=6,
    )

    r = run_bb_backtest(
        bars_4h=bars, config=config, daily_bars=daily,
        margin_type="linear", initial_capital=10000, leverage=5,
    )

    trades = r["trades"]
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]

    # Long / Short breakdown
    longs = [t for t in trades if t["side"] == "long"]
    shorts = [t for t in trades if t["side"] == "short"]
    long_wins = [t for t in longs if t["pnl"] > 0]
    short_wins = [t for t in shorts if t["pnl"] > 0]

    # Exit reasons
    exits = r.get("exit_reasons", {})
    n_target = exits.get("target_middle", 0)
    n_trail = exits.get("trailing_stop", 0)
    n_stop = exits.get("stop_loss", 0)
    n_time = exits.get("time_stop", 0)
    n_forced = exits.get("forced_end", 0)
    total = r["total_trades"]

    print()
    print("=" * 60)
    print("  Strategy D — Config [E] 回測報告")
    print("  BB(20,2.5) SMA | 3.5% stop | 10% risk | 5x | trail+15m")
    print("  $10,000 USDT-M | 2021-04 to 2026-04 (5年)")
    print("=" * 60)

    # ── 【交易統計】 ──
    print()
    print("  【交易統計】")
    print(f"  總交易: {total} 筆  |  勝率: {r['win_rate']:.1f}%  |  盈虧比 PF: {r['profit_factor']:.2f}")
    print(f"  Long:   {len(longs):>2d} 筆 ({len(long_wins)}W/{len(longs)-len(long_wins)}L)")
    print(f"  Short:  {len(shorts):>2d} 筆 ({len(short_wins)}W/{len(shorts)-len(short_wins)}L)")
    print(f"  最大回撤: {r['max_drawdown_pct']:.1f}%  |  報酬/回撤: {r['r_dd']:.2f}")
    print(f"  Sharpe: {r['sharpe']:.2f}  |  平均持倉: {r['avg_duration_days']:.1f} 天")
    print(f"  平均獲利: {r['avg_win_pct']:+.1f}%  |  平均虧損: {r['avg_loss_pct']:+.1f}%")
    print()
    print("  出場分佈:")
    if n_target:
        print(f"  \u2705 回中軌止盈:  {n_target:>2d} 筆 ({n_target/total*100:.0f}%)")
    if n_trail:
        print(f"  \U0001F4C8 移動止盈:    {n_trail:>2d} 筆 ({n_trail/total*100:.0f}%)")
    if n_stop:
        print(f"  \u274C 固定止損:    {n_stop:>2d} 筆 ({n_stop/total*100:.0f}%)")
    if n_time:
        print(f"  \u23F0 時間止損:    {n_time:>2d} 筆 ({n_time/total*100:.0f}%)")
    if n_forced:
        print(f"  \U0001F6D1 強制平倉:    {n_forced:>2d} 筆 ({n_forced/total*100:.0f}%)")

    # ── 【年度明細】 ──
    print()
    print("=" * 60)
    print()
    print("  【年度明細】")
    years = sorted(set(t["entry_ts"].year for t in trades if t["entry_ts"]))
    for year in years:
        yt = [t for t in trades if t["entry_ts"] and t["entry_ts"].year == year]
        yw = [t for t in yt if t["pnl"] > 0]
        ypnl = sum(t["pnl"] for t in yt)
        ywr = len(yw) / len(yt) * 100 if yt else 0
        print(f"  {year}:  {len(yt):>2d} 筆  勝率 {ywr:>4.0f}%  PnL  {'+' if ypnl >= 0 else ''}${abs(ypnl):,.0f}")

    # Best / worst trade
    best = max(trades, key=lambda t: t["pnl"])
    worst = min(trades, key=lambda t: t["pnl"])
    best_pct = best["pnl"] / 10000 * 100  # approx
    worst_pct = worst["pnl"] / 10000 * 100
    # Calculate actual return % at time of trade
    cap = 10000.0
    for t in trades:
        if t is best:
            best_pct = t["pnl"] / cap * 100
        if t is worst:
            worst_pct = t["pnl"] / cap * 100
        cap += t["pnl"]

    print()
    print(f"  最大單筆獲利: {best['entry_ts'].strftime('%Y-%m-%d')}  +${best['pnl']:,.0f} ({best_pct:+.1f}%)")
    print(f"  最大單筆虧損: {worst['entry_ts'].strftime('%Y-%m-%d')}  -${abs(worst['pnl']):,.0f} ({worst_pct:+.1f}%)")

    # ── 【市場階段表現】 ──
    print()
    print("=" * 60)
    print()
    print("  【市場階段表現】")

    # Define market phases based on BTC price history
    phases = [
        ("2021 牛市尾聲", "\U0001F4C8", "2021-04-01", "2021-12-31"),
        ("2022 熊市", "\U0001F4C9", "2022-01-01", "2022-12-31"),
        ("2023 築底反彈", "\U0001F4CA", "2023-01-01", "2023-12-31"),
        ("2024 主升段", "\U0001F680", "2024-01-01", "2024-12-31"),
        ("2025 高檔震盪", "\U0001F4C8", "2025-01-01", "2025-12-31"),
        ("2026 回檔", "\U0001F4C9", "2026-01-01", "2026-12-31"),
    ]

    for label, emoji, start_str, end_str in phases:
        start = datetime.strptime(start_str, "%Y-%m-%d")
        end = datetime.strptime(end_str, "%Y-%m-%d")
        phase_trades = [
            t for t in trades
            if t["entry_ts"] and start <= t["entry_ts"] <= end
        ]
        if not phase_trades:
            continue
        phase_pnl = sum(t["pnl"] for t in phase_trades)
        phase_wins = sum(1 for t in phase_trades if t["pnl"] > 0)
        phase_wr = phase_wins / len(phase_trades) * 100
        n_long = sum(1 for t in phase_trades if t["side"] == "long")
        n_short = sum(1 for t in phase_trades if t["side"] == "short")
        if n_long > 0 and n_short == 0:
            side_note = "全做多"
        elif n_short > 0 and n_long == 0:
            side_note = "全做空"
        else:
            side_note = f"{n_long}多/{n_short}空"
        print(f"  {emoji} {label}:  {'+' if phase_pnl >= 0 else '-'}${abs(phase_pnl):>7,.0f}  "
              f"({len(phase_trades)}筆，{phase_wr:.0f}%勝率，{side_note})")

    # ── Final ──
    print()
    print("=" * 60)
    print(f"  最終資金: ${r.get('final_capital', 0):,.2f}  (回報 {r['total_return_pct']:+.1f}%)")
    print("=" * 60)
    print()

    # Save
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path("reports") / f"strategy_d_config_e_{ts}.txt"
    out_path.parent.mkdir(exist_ok=True)

    # Re-run print to file (capture output)
    import io
    buf = io.StringIO()
    # Just save the key data
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"Strategy D Config [E] Report - {ts}\n")
        f.write(f"Return: {r['total_return_pct']:+.1f}%\n")
        f.write(f"Final: ${r.get('final_capital', 0):,.2f}\n")
        f.write(f"DD: {r['max_drawdown_pct']:.1f}%\n")
        f.write(f"R/DD: {r['r_dd']:.2f}\n")
        f.write(f"Trades: {total}\n")
        f.write(f"WR: {r['win_rate']:.1f}%\n")
        f.write(f"PF: {r['profit_factor']:.2f}\n")
        f.write(f"Sharpe: {r['sharpe']:.2f}\n")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
