#!/usr/bin/env python3
"""Backtest for ChannelSwingStrategy on daily bars + Coinglass indicators.

Loads daily OHLCV + all available Coinglass data, computes RSI(3,7,14),
feeds each day through the strategy, and tracks trades/PnL.

Usage:
    python run_swing_backtest.py [--start 2022-01-01] [--end 2022-12-31] [--leverage 3]
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

from adapters.base import MarketBar, Position
from strategies.channel_detector import DailyIndicators, ChannelDetectorConfig
from strategies.channel_swing import ChannelSwingConfig, ChannelSwingStrategy


DATA_DIR = Path(__file__).parent / "src" / "data"


# ── Data loading ─────────────────────────────────────────

def load_daily_bars(start: str, end: str) -> list[MarketBar]:
    path = DATA_DIR / "btcusdt_1d_6year.csv"
    bars = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = datetime.fromisoformat(row["timestamp"])
            if ts < datetime.fromisoformat(start):
                continue
            if ts > datetime.fromisoformat(end):
                break
            bars.append(MarketBar(
                timestamp=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            ))
    return bars


def _load_csv_map(path: Path, value_cols: list[str]) -> dict[str, dict]:
    """Load CSV into {date_str: {col: value}} map."""
    result = {}
    if not path.exists():
        return result
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row["timestamp"][:10]  # "2022-05-16"
            vals = {}
            for col in value_cols:
                try:
                    vals[col] = float(row[col])
                except (ValueError, KeyError):
                    vals[col] = 0.0
            result[ts] = vals
    return result


def load_coinglass_data() -> dict[str, dict]:
    """Load all Coinglass daily data into {date: {oi, funding, ls_ratio, cvd, ...}}."""
    merged: dict[str, dict] = {}

    # OI daily (close)
    oi = _load_csv_map(DATA_DIR / "coinglass_oi_1d.csv", ["close"])
    for d, v in oi.items():
        merged.setdefault(d, {})["oi"] = v["close"]

    # Funding daily (close = settlement %)
    fund = _load_csv_map(DATA_DIR / "coinglass_funding_1d.csv", ["close"])
    for d, v in fund.items():
        merged.setdefault(d, {})["funding_pct"] = v["close"]

    # L/S ratio daily
    ls = _load_csv_map(DATA_DIR / "coinglass_top_ls_1d.csv", ["ratio"])
    for d, v in ls.items():
        merged.setdefault(d, {})["ls_ratio"] = v["ratio"]

    # CVD daily
    cvd = _load_csv_map(DATA_DIR / "coinglass_cvd_1d.csv", ["cvd"])
    for d, v in cvd.items():
        merged.setdefault(d, {})["cvd"] = v["cvd"]

    # Liquidation 4h → aggregate to daily
    liq_4h = _load_csv_map(DATA_DIR / "coinglass_liquidation_4h.csv", ["long_usd", "short_usd"])
    daily_liq: dict[str, dict] = {}
    for ts_str, v in liq_4h.items():
        daily_liq.setdefault(ts_str, {"long": 0.0, "short": 0.0})
        daily_liq[ts_str]["long"] += v["long_usd"]
        daily_liq[ts_str]["short"] += v["short_usd"]
    for d, v in daily_liq.items():
        merged.setdefault(d, {})["long_liq_usd"] = v["long"]
        merged.setdefault(d, {})["short_liq_usd"] = v["short"]

    # Taker volume 4h → aggregate to daily
    tkr_4h = _load_csv_map(DATA_DIR / "coinglass_taker_volume_4h.csv", ["buy_usd", "sell_usd"])
    daily_tkr: dict[str, dict] = {}
    for ts_str, v in tkr_4h.items():
        daily_tkr.setdefault(ts_str, {"buy": 0.0, "sell": 0.0})
        daily_tkr[ts_str]["buy"] += v["buy_usd"]
        daily_tkr[ts_str]["sell"] += v["sell_usd"]
    for d, v in daily_tkr.items():
        merged.setdefault(d, {})["taker_buy_usd"] = v["buy"]
        merged.setdefault(d, {})["taker_sell_usd"] = v["sell"]

    return merged


# ── RSI computation ──────────────────────────────────────

def compute_rsi_series(closes: list[float], period: int) -> list[float | None]:
    """Compute RSI for each bar, returning list same length as closes."""
    result: list[float | None] = [None] * len(closes)
    if len(closes) < period + 1:
        return result

    gains = []
    losses = []
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - 100.0 / (1 + rs)

    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0)
        loss = max(-delta, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - 100.0 / (1 + rs)

    return result


# ── Build DailyIndicators ───────────────────────────────

def build_indicator_map(
    bars: list[MarketBar],
    coinglass: dict[str, dict],
) -> dict[str, DailyIndicators]:
    """Build DailyIndicators for each bar date."""
    closes = [b.close for b in bars]
    rsi3 = compute_rsi_series(closes, 3)
    rsi7 = compute_rsi_series(closes, 7)
    rsi14 = compute_rsi_series(closes, 14)

    ind_map: dict[str, DailyIndicators] = {}
    for i, bar in enumerate(bars):
        d = bar.timestamp.strftime("%Y-%m-%d")
        cg = coinglass.get(d, {})
        ind_map[d] = DailyIndicators(
            oi=cg.get("oi", 0.0),
            funding_pct=cg.get("funding_pct", 0.0),
            ls_ratio=cg.get("ls_ratio", 0.0),
            long_liq_usd=cg.get("long_liq_usd", 0.0),
            short_liq_usd=cg.get("short_liq_usd", 0.0),
            cvd=cg.get("cvd", 0.0),
            taker_buy_usd=cg.get("taker_buy_usd", 0.0),
            taker_sell_usd=cg.get("taker_sell_usd", 0.0),
            rsi3=rsi3[i] if rsi3[i] is not None else 50.0,
            rsi7=rsi7[i] if rsi7[i] is not None else 50.0,
            rsi14=rsi14[i] if rsi14[i] is not None else 50.0,
        )
    return ind_map


# ── Trade tracking ───────────────────────────────────────

@dataclass
class SwingTrade:
    side: str               # "long" or "short"
    entry_date: str
    entry_price: float
    exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl_pct: float = 0.0   # return % (before leverage)
    high_score: int = 0
    low_score: int = 0


def compute_pnl_pct(side: str, entry: float, exit_price: float) -> float:
    if entry <= 0:
        return 0.0
    if side == "long":
        return (exit_price - entry) / entry
    else:  # short
        return (entry - exit_price) / entry


# ── Backtest engine ──────────────────────────────────────

def run_backtest(
    bars: list[MarketBar],
    ind_map: dict[str, DailyIndicators],
    leverage: float = 3.0,
    config: ChannelSwingConfig | None = None,
) -> tuple[list[SwingTrade], list[float]]:
    """Run channel swing backtest. Returns (trades, equity_curve)."""
    cfg = config or ChannelSwingConfig(
        detector=ChannelDetectorConfig(
            pivot_window=5,
            min_confirmed_highs=2,
            min_confirmed_lows=2,
            min_bars=30,
            min_high_score=3,
            min_low_score=3,
        ),
    )
    strategy = ChannelSwingStrategy(cfg)

    trades: list[SwingTrade] = []
    open_trade: SwingTrade | None = None
    equity = 1.0  # normalized to 1.0
    equity_curve = [equity]
    position = Position(symbol="BTCUSD")
    peak_equity = 1.0
    max_dd = 0.0

    for bar in bars:
        d = bar.timestamp.strftime("%Y-%m-%d")
        ind = ind_map.get(d)
        if ind is None:
            equity_curve.append(equity)
            continue

        signal = strategy.on_daily_close(bar, ind, position)

        # Process signal
        if signal.action == "short" and not position.is_open:
            position = Position(
                symbol="BTCUSD", side="short",
                quantity=1.0, average_price=bar.close,
            )
            open_trade = SwingTrade(
                side="short", entry_date=d, entry_price=bar.close,
                high_score=signal.metadata.get("high_score", 0),
            )

        elif signal.action == "buy" and not position.is_open:
            position = Position(
                symbol="BTCUSD", side="long",
                quantity=1.0, average_price=bar.close,
            )
            open_trade = SwingTrade(
                side="long", entry_date=d, entry_price=bar.close,
                low_score=signal.metadata.get("low_score", 0),
            )

        elif signal.action == "cover" and position.side == "short":
            if open_trade is not None:
                pnl = compute_pnl_pct("short", open_trade.entry_price, bar.close)
                open_trade.exit_date = d
                open_trade.exit_price = bar.close
                open_trade.exit_reason = signal.reason
                open_trade.pnl_pct = pnl
                equity *= (1 + pnl * leverage)
                trades.append(open_trade)
                open_trade = None
            position = Position(symbol="BTCUSD")

        elif signal.action == "sell" and position.side == "long":
            if open_trade is not None:
                pnl = compute_pnl_pct("long", open_trade.entry_price, bar.close)
                open_trade.exit_date = d
                open_trade.exit_price = bar.close
                open_trade.exit_reason = signal.reason
                open_trade.pnl_pct = pnl
                equity *= (1 + pnl * leverage)
                trades.append(open_trade)
                open_trade = None
            position = Position(symbol="BTCUSD")

        # Mark to market for equity curve
        if position.is_open and open_trade is not None:
            unrealized = compute_pnl_pct(
                open_trade.side, open_trade.entry_price, bar.close,
            )
            curve_eq = equity * (1 + unrealized * leverage)
        else:
            curve_eq = equity

        equity_curve.append(curve_eq)

        # Max drawdown
        peak_equity = max(peak_equity, curve_eq)
        dd = (peak_equity - curve_eq) / peak_equity
        max_dd = max(max_dd, dd)

    # Close any open trade at end
    if position.is_open and open_trade is not None:
        last_bar = bars[-1]
        pnl = compute_pnl_pct(open_trade.side, open_trade.entry_price, last_bar.close)
        open_trade.exit_date = last_bar.timestamp.strftime("%Y-%m-%d")
        open_trade.exit_price = last_bar.close
        open_trade.exit_reason = "backtest_end"
        open_trade.pnl_pct = pnl
        equity *= (1 + pnl * leverage)
        trades.append(open_trade)

    return trades, equity_curve


# ── Output ───────────────────────────────────────────────

def print_results(
    trades: list[SwingTrade],
    equity_curve: list[float],
    leverage: float,
    start: str,
    end: str,
) -> None:
    print(f"\n{'='*72}")
    print(f"  CHANNEL SWING BACKTEST: {start} to {end}  (leverage={leverage}x)")
    print(f"{'='*72}\n")

    if not trades:
        print("  No trades generated.\n")
        return

    # Summary
    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
    total_return = equity_curve[-1] - 1.0
    peak = max(equity_curve)
    max_dd = max((peak - eq) / peak for eq in equity_curve) if peak > 0 else 0
    avg_pnl = sum(t.pnl_pct for t in trades) / len(trades)
    avg_win = sum(t.pnl_pct for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.pnl_pct for t in losses) / len(losses) if losses else 0

    longs = [t for t in trades if t.side == "long"]
    shorts = [t for t in trades if t.side == "short"]

    print(f"  Total trades:   {len(trades)}")
    print(f"  Longs:          {len(longs)}   |  Shorts:  {len(shorts)}")
    print(f"  Wins:           {len(wins)}   |  Losses:  {len(losses)}")
    print(f"  Win rate:       {len(wins)/len(trades)*100:.1f}%")
    print(f"  Avg PnL/trade:  {avg_pnl*100:+.2f}%  (before leverage)")
    print(f"  Avg win:        {avg_win*100:+.2f}%  |  Avg loss:  {avg_loss*100:.2f}%")
    print(f"  Total return:   {total_return*100:+.1f}%  ({leverage}x leverage)")
    print(f"  Max drawdown:   {max_dd*100:.1f}%")
    print(f"  Final equity:   {equity_curve[-1]:.4f}")

    # Trade table
    print(f"\n{'─'*72}")
    print(f"  {'#':>3}  {'Side':<6} {'Entry':>10} {'Exit':>10} {'Entry$':>9} {'Exit$':>9} {'PnL%':>7} {'Reason'}")
    print(f"{'─'*72}")
    for i, t in enumerate(trades, 1):
        pnl_str = f"{t.pnl_pct*100:+.2f}%"
        marker = "W" if t.pnl_pct > 0 else "L"
        reason = t.exit_reason[:28]
        print(f"  {i:>3}  {t.side:<6} {t.entry_date:>10} {t.exit_date:>10} "
              f"{t.entry_price:>9.0f} {t.exit_price:>9.0f} {pnl_str:>7} {marker} {reason}")
    print(f"{'─'*72}")

    # Channel detection info
    print(f"\n  Strategy states observed:")
    channel_entries = [t for t in trades if "channel" in t.exit_reason.lower() or "flip" in t.exit_reason.lower()]
    break_exits = [t for t in trades if "break" in t.exit_reason.lower()]
    print(f"    Channel swing trades: {len(trades) - len(break_exits)}")
    print(f"    Channel break exits:  {len(break_exits)}")
    print()


# ── Main ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Channel swing backtest")
    parser.add_argument("--start", default="2022-04-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default="2022-10-31", help="End date YYYY-MM-DD")
    parser.add_argument("--leverage", type=float, default=3.0, help="Leverage multiplier")
    args = parser.parse_args()

    print(f"Loading daily bars {args.start} to {args.end}...")
    bars = load_daily_bars(args.start, args.end)
    print(f"  {len(bars)} daily bars loaded")

    print("Loading Coinglass indicator data...")
    coinglass = load_coinglass_data()
    available_dates = set(coinglass.keys())
    bar_dates = {b.timestamp.strftime("%Y-%m-%d") for b in bars}
    overlap = available_dates & bar_dates
    print(f"  Coinglass data available for {len(overlap)}/{len(bars)} bar dates")

    print("Computing RSI(3,7,14) and building indicators...")
    ind_map = build_indicator_map(bars, coinglass)

    print(f"Running backtest (leverage={args.leverage}x)...")
    trades, equity_curve = run_backtest(bars, ind_map, args.leverage)
    print_results(trades, equity_curve, args.leverage, args.start, args.end)


if __name__ == "__main__":
    main()
