"""區域性反轉 (Regional Reversal) — Standalone coin-margined backtest.

Separate project / separate capital from the main channel strategy.
Runs on DAILY bars only. Entry via VP+RSI capitulation reversal,
exit via RSI momentum fade, VAH breakout trailing, or time stop.

Run with: PYTHONPATH=src python -m research.bear_reversal_backtest
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from data.backfill import load_bars_from_csv


# ── Helpers (self-contained, no dependency on main strategy) ──

def _ema(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    val = sum(closes[:period]) / period
    for c in closes[period:]:
        val = c * k + val * (1 - k)
    return val


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    if len(gains) < period:
        return None
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def _atr(bars_w, period: int = 14) -> float | None:
    if len(bars_w) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars_w)):
        b, pb = bars_w[i], bars_w[i - 1]
        tr = max(b.high - b.low, abs(b.high - pb.close), abs(b.low - pb.close))
        trs.append(tr)
    return sum(trs[-period:]) / period


def _compute_vp(bars_w, n_bins: int = 50) -> dict | None:
    if len(bars_w) < 10:
        return None
    lo = min(b.low for b in bars_w)
    hi = max(b.high for b in bars_w)
    if hi <= lo:
        return None
    bs = (hi - lo) / n_bins
    bins: dict[int, float] = {}
    for b in bars_w:
        b_lo = int((b.low - lo) / bs)
        b_hi = min(int((b.high - lo) / bs), n_bins - 1)
        n = max(1, b_hi - b_lo + 1)
        vpb = b.volume / n
        for j in range(b_lo, b_hi + 1):
            bins[j] = bins.get(j, 0) + vpb
    poc_bin = max(bins, key=bins.get)
    poc = lo + poc_bin * bs + bs / 2
    total = sum(bins.values())
    sv = sorted(bins.items(), key=lambda x: x[1], reverse=True)
    cumul = 0.0
    va_bins: list[int] = []
    for idx, vol in sv:
        va_bins.append(idx)
        cumul += vol
        if cumul >= total * 0.70:
            break
    val_p = lo + min(va_bins) * bs
    vah_p = lo + (max(va_bins) + 1) * bs
    return {"poc": poc, "val": val_p, "vah": vah_p}


# ── Config ──

@dataclass
class BearReversalConfig:
    initial_btc: float = 1.0
    leverage: int = 3
    risk_per_trade_pct: float = 0.05   # 5% of capital per trade
    fee_rate: float = 0.001            # 0.1% taker fee each way
    # Signal params
    vp_lookback: int = 60
    min_bars: int = 250
    capitulation_rsi: float = 28.0
    capitulation_vol_ratio: float = 1.5
    recovery_rsi: float = 33.0
    capitulation_timeout: int = 30     # days
    # Exit: RSI momentum fade (primary exit for daily timeframe)
    rsi_fade_from: float = 75.0        # exit when RSI drops from above this
    rsi_fade_to: float = 65.0          # to below this
    # Exit: structural stop — close below VAL again (reversal failed)
    structural_stop: bool = True
    # Exit: time stop
    max_hold_days: int = 90


def run_bear_reversal_backtest(
    bars_1d: list,
    cfg: BearReversalConfig | None = None,
) -> dict:
    """Run standalone bear reversal backtest on daily bars.

    Returns dict with trades, summary, equity curve.
    """
    if cfg is None:
        cfg = BearReversalConfig()

    btc = cfg.initial_btc
    phase = 0
    phase1_bar = 0
    phase1_details: dict = {}
    trades: list[dict] = []

    # Position state
    in_position = False
    entry_price = 0.0
    quantity = 0.0       # BTC-denominated contract qty
    entry_vp_val = 0.0   # VAL at entry for structural stop
    trade_info: dict = {}

    # Equity tracking
    equity_curve: list[dict] = []
    peak_btc = btc
    max_dd = 0.0

    for i in range(cfg.min_bars, len(bars_1d)):
        bar = bars_1d[i]
        prev = bars_1d[i - 1]
        hist = bars_1d[: i + 1]
        closes = [b.close for b in hist]
        volumes = [b.volume for b in hist]

        rsi_14 = _rsi(closes, 14)
        prev_rsi = _rsi(closes[:-1], 14)
        ema_200 = _ema(closes, 200)
        vol_sma = _sma(volumes, 20)
        vol_ratio = bar.volume / vol_sma if vol_sma and vol_sma > 0 else 0

        vp = _compute_vp(hist[-cfg.vp_lookback:])
        prev_vp = _compute_vp(hist[-cfg.vp_lookback - 1: -1])

        if not vp or rsi_14 is None or ema_200 is None:
            continue

        # Recent RSI minimum (last 10 days)
        recent_rsis = []
        for j in range(max(cfg.min_bars, i - 10), i + 1):
            r = _rsi([b.close for b in bars_1d[: j + 1]], 14)
            if r is not None:
                recent_rsis.append(r)
        rsi_min_recent = min(recent_rsis) if recent_rsis else 50

        # ── In Position: check exits ──
        if in_position:
            days_held = (bar.timestamp - trade_info["entry_date"]).days
            exit_reason = None
            exit_price = bar.close

            # Exit 1: Structural stop — close back below entry VAL (reversal failed)
            if cfg.structural_stop and vp and bar.close < entry_vp_val:
                exit_reason = "structural_stop"

            # Exit 2: RSI momentum fade (primary profit exit)
            elif prev_rsi is not None and prev_rsi > cfg.rsi_fade_from and rsi_14 < cfg.rsi_fade_to:
                exit_reason = "rsi_fade"

            # Exit 3: time stop
            elif days_held >= cfg.max_hold_days:
                exit_reason = "time_stop"

            if exit_reason:
                # Close trade — inverse contract PnL
                pnl_pct = (exit_price - entry_price) / entry_price
                pnl_btc = quantity * pnl_pct * cfg.leverage
                fee_btc = quantity * cfg.fee_rate  # exit fee
                pnl_btc -= fee_btc
                btc += pnl_btc

                trade_info.update({
                    "exit_date": bar.timestamp,
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "pnl_pct": pnl_pct * 100 * cfg.leverage,
                    "pnl_btc": pnl_btc,
                    "days_held": days_held,
                })
                trades.append(trade_info)
                in_position = False
                phase = 0  # reset for next signal

            # Track equity
            equity_curve.append({
                "date": bar.timestamp.isoformat(),
                "btc": btc,
                "price": bar.close,
            })
            if btc > peak_btc:
                peak_btc = btc
            dd = (peak_btc - btc) / peak_btc if peak_btc > 0 else 0
            if dd > max_dd:
                max_dd = dd
            continue

        # ── Not in Position: look for entry signals ──

        # Phase 0 → 1: Capitulation
        if phase == 0:
            if (rsi_14 < cfg.capitulation_rsi
                    and vol_ratio >= cfg.capitulation_vol_ratio
                    and bar.close < vp["val"]):
                phase = 1
                phase1_bar = i
                phase1_details = {
                    "date": bar.timestamp,
                    "price": bar.close,
                    "rsi": rsi_14,
                    "vol_ratio": vol_ratio,
                    "vp_val": vp["val"],
                }

        # Phase 1 → 2: Reversal → ENTRY
        elif phase == 1:
            if i - phase1_bar > cfg.capitulation_timeout:
                phase = 0
                equity_curve.append({
                    "date": bar.timestamp.isoformat(),
                    "btc": btc,
                    "price": bar.close,
                })
                continue

            is_val_reclaim = (
                prev_vp is not None
                and prev.close < prev_vp["val"]
                and bar.close > vp["val"]
                and rsi_14 > cfg.recovery_rsi
                and rsi_min_recent < cfg.capitulation_rsi
                and vol_ratio >= 1.0
            )

            is_ema_reclaim = (
                prev.close < ema_200
                and bar.close > ema_200
                and rsi_14 > cfg.recovery_rsi
                and rsi_min_recent < cfg.capitulation_rsi
            )

            if is_val_reclaim or is_ema_reclaim:
                # ENTRY
                entry_price = bar.close
                quantity = btc * cfg.risk_per_trade_pct
                fee_btc = quantity * cfg.fee_rate
                btc -= fee_btc  # entry fee
                entry_vp_val = vp["val"]  # structural stop level

                reason = "VAL_RECLAIM" if is_val_reclaim else "EMA200_RECLAIM"
                trade_info = {
                    "entry_date": bar.timestamp,
                    "entry_price": entry_price,
                    "entry_reason": reason,
                    "quantity": quantity,
                    "phase1_date": phase1_details["date"],
                    "phase1_rsi": phase1_details["rsi"],
                    "phase1_vol_ratio": phase1_details["vol_ratio"],
                    "rsi_at_entry": rsi_14,
                    "ema200": ema_200,
                    "vp_val": vp["val"],
                    "vp_vah": vp["vah"],
                    "vp_poc": vp["poc"],
                }
                in_position = True
                phase = 2

        # Track equity
        equity_curve.append({
            "date": bar.timestamp.isoformat(),
            "btc": btc,
            "price": bar.close,
        })
        if btc > peak_btc:
            peak_btc = btc
        dd = (peak_btc - btc) / peak_btc if peak_btc > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Close open position at last bar
    if in_position:
        last = bars_1d[-1]
        pnl_pct = (last.close - entry_price) / entry_price
        pnl_btc = quantity * pnl_pct * cfg.leverage
        fee_btc = quantity * cfg.fee_rate
        pnl_btc -= fee_btc
        btc += pnl_btc
        trade_info.update({
            "exit_date": last.timestamp,
            "exit_price": last.close,
            "exit_reason": "still_open",
            "pnl_pct": pnl_pct * 100 * cfg.leverage,
            "pnl_btc": pnl_btc,
            "days_held": (last.timestamp - trade_info["entry_date"]).days,
        })
        trades.append(trade_info)

    # Summary
    wins = [t for t in trades if t["pnl_btc"] > 0]
    losses = [t for t in trades if t["pnl_btc"] <= 0]
    n = len(trades)
    return {
        "trades": trades,
        "equity_curve": equity_curve,
        "summary": {
            "initial_btc": cfg.initial_btc,
            "final_btc": btc,
            "return_pct": (btc - cfg.initial_btc) / cfg.initial_btc * 100,
            "leverage": cfg.leverage,
            "max_drawdown_pct": max_dd * 100,
            "return_dd": ((btc - cfg.initial_btc) / cfg.initial_btc) / max_dd if max_dd > 0 else 0,
            "total_trades": n,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / n * 100 if n > 0 else 0,
            "avg_win_btc": sum(t["pnl_btc"] for t in wins) / len(wins) if wins else 0,
            "avg_loss_btc": sum(t["pnl_btc"] for t in losses) / len(losses) if losses else 0,
            "total_pnl_btc": sum(t["pnl_btc"] for t in trades),
        },
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    from datetime import datetime as _dt

    bars_1d = load_bars_from_csv("src/data/btcusdt_1d_6year.csv")
    print(f"Daily bars: {len(bars_1d)}, {bars_1d[0].timestamp} to {bars_1d[-1].timestamp}")

    cfg = BearReversalConfig()
    result = run_bear_reversal_backtest(bars_1d, cfg)
    s = result["summary"]
    trades = result["trades"]

    start_price = bars_1d[cfg.min_bars].close
    end_price = bars_1d[-1].close

    print(f"\n{'=' * 90}")
    print("區域性反轉 (Regional Reversal) — STANDALONE BACKTEST")
    print(f"{'=' * 90}")
    print(f"Capital:      {s['initial_btc']:.1f} BTC (=${s['initial_btc'] * start_price:,.0f})")
    print(f"Leverage:     {s['leverage']}x")
    print(f"Final BTC:    {s['final_btc']:.4f} BTC ({s['return_pct']:+.1f}%)")
    print(f"Final Value:  ${s['final_btc'] * end_price:,.0f}")
    print(f"Max Drawdown: {s['max_drawdown_pct']:.1f}%")
    print(f"Return/DD:    {s['return_dd']:.2f}")
    print(f"Trades:       {s['total_trades']}")
    print(f"Win Rate:     {s['win_rate']:.1f}% ({s['wins']}W/{s['losses']}L)")
    if s["wins"] > 0:
        print(f"Avg Win:      {s['avg_win_btc']:+.4f} BTC")
    if s["losses"] > 0:
        print(f"Avg Loss:     {s['avg_loss_btc']:+.4f} BTC")
    print(f"Win/Loss:     {abs(s['avg_win_btc'] / s['avg_loss_btc']):.2f}" if s["avg_loss_btc"] != 0 else "")

    print(f"\n{'─' * 90}")
    print(f"{'#':>3} | {'Entry':>10} {'$Entry':>9} | {'Exit':>10} {'$Exit':>9} | {'PnL BTC':>10} {'Ret':>7} | {'Days':>4} | Reason")
    print(f"{'─' * 90}")
    for idx, t in enumerate(trades):
        print(
            f"  {idx + 1} | {t['entry_date'].strftime('%Y-%m-%d')} ${t['entry_price']:>8,.0f}"
            f" | {t['exit_date'].strftime('%Y-%m-%d')} ${t['exit_price']:>8,.0f}"
            f" | {t['pnl_btc']:>+9.4f} {t['pnl_pct']:>+6.1f}%"
            f" | {t['days_held']:>4}d"
            f" | {t['entry_reason']} → {t['exit_reason']}"
        )
        print(
            f"      Cap: {t['phase1_date'].strftime('%Y-%m-%d')} RSI={t['phase1_rsi']:.1f}"
            f" Vol={t['phase1_vol_ratio']:.1f}x"
            f" | POC=${t['vp_poc']:,.0f} VAL=${t['vp_val']:,.0f} VAH=${t['vp_vah']:,.0f}"
        )

    # Save report
    now = _dt.now().strftime("%Y%m%d_%H%M%S")
    report_dir = Path("reports")
    report_dir.mkdir(exist_ok=True)

    json_path = report_dir / f"bear_reversal_{now}.json"
    json_data = {
        "summary": s,
        "trades": [
            {
                "entry_date": t["entry_date"].isoformat(),
                "exit_date": t["exit_date"].isoformat(),
                "entry_price": t["entry_price"],
                "exit_price": t["exit_price"],
                "entry_reason": t["entry_reason"],
                "exit_reason": t["exit_reason"],
                "pnl_btc": t["pnl_btc"],
                "pnl_pct": t["pnl_pct"],
                "days_held": t["days_held"],
                "phase1_date": t["phase1_date"].isoformat(),
                "phase1_rsi": t["phase1_rsi"],
                "vp_poc": t["vp_poc"],
                "vp_val": t["vp_val"],
                "vp_vah": t["vp_vah"],
            }
            for t in trades
        ],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    print(f"\n✅ JSON: {json_path}")


if __name__ == "__main__":
    main()
