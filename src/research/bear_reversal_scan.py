"""Bear Bottom Reversal Combo — Full history scan.

Scan all daily bars to find how many trades the combo would generate.
Phase 0: Bear context
Phase 1: Capitulation (RSI<28 + Vol spike + below VA)
Phase 2: Reversal confirmed (VAL reclaim + RSI recovery) → ENTRY
Phase 3: Trend (VAH breakout) → HOLD
Exit: RSI momentum fade or 90d timeout
"""
from __future__ import annotations

from datetime import datetime
from data.backfill import load_bars_from_csv


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
        return 100
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


def main() -> None:
    bars_1d = load_bars_from_csv("src/data/btcusdt_1d_6year.csv")
    print(f"Daily bars: {len(bars_1d)}, {bars_1d[0].timestamp} to {bars_1d[-1].timestamp}")

    VP_LOOKBACK = 60
    MIN_BARS = 250

    phase = 0
    phase1_bar = 0
    phase1_details: dict = {}
    trades: list[dict] = []
    current_trade: dict | None = None

    for i in range(MIN_BARS, len(bars_1d)):
        bar = bars_1d[i]
        prev = bars_1d[i - 1]
        hist = bars_1d[: i + 1]
        closes = [b.close for b in hist]
        volumes = [b.volume for b in hist]

        rsi_14 = _rsi(closes, 14)
        prev_rsi = _rsi(closes[:-1], 14)
        ema_50 = _ema(closes, 50)
        ema_200 = _ema(closes, 200)
        vol_sma = _sma(volumes, 20)
        vol_ratio = bar.volume / vol_sma if vol_sma and vol_sma > 0 else 0

        vp = _compute_vp(hist[-VP_LOOKBACK:])
        prev_vp = _compute_vp(hist[-VP_LOOKBACK - 1 : -1])
        if not vp or not rsi_14 or not ema_200:
            continue

        # Recent RSI minimum (last 10 days)
        recent_rsis = []
        for j in range(max(MIN_BARS, i - 10), i + 1):
            r = _rsi([b.close for b in bars_1d[: j + 1]], 14)
            if r is not None:
                recent_rsis.append(r)
        rsi_min_recent = min(recent_rsis) if recent_rsis else 50

        # ── Phase 0 → 1: Capitulation ──
        if phase == 0:
            if rsi_14 < 28 and vol_ratio >= 1.5 and bar.close < vp["val"]:
                phase = 1
                phase1_bar = i
                phase1_details = {
                    "date": bar.timestamp,
                    "price": bar.close,
                    "rsi": rsi_14,
                    "vol_ratio": vol_ratio,
                    "vp_val": vp["val"],
                }

        # ── Phase 1 → 2: Reversal → ENTRY ──
        elif phase == 1:
            if i - phase1_bar > 30:
                phase = 0
                continue

            is_val_reclaim = (
                prev_vp is not None
                and prev.close < prev_vp["val"]
                and bar.close > vp["val"]
                and rsi_14 > 33
                and rsi_min_recent < 28
                and vol_ratio >= 1.0
            )

            is_ema_reclaim = (
                prev.close < ema_200
                and bar.close > ema_200
                and rsi_14 > 33
                and rsi_min_recent < 28
            )

            if is_val_reclaim or is_ema_reclaim:
                phase = 2
                reason = "VAL_RECLAIM" if is_val_reclaim else "EMA200_RECLAIM"
                current_trade = {
                    "entry_date": bar.timestamp,
                    "entry_price": bar.close,
                    "entry_reason": reason,
                    "phase1_date": phase1_details["date"],
                    "phase1_rsi": phase1_details["rsi"],
                    "rsi_at_entry": rsi_14,
                    "ema200": ema_200,
                    "vp_val": vp["val"],
                    "vp_vah": vp["vah"],
                    "vp_poc": vp["poc"],
                    "peak": bar.high,
                }
                print(f"\n* ENTRY: {bar.timestamp.date()} @ ${bar.close:,.0f} [{reason}]")
                print(f"  Capitulation: {phase1_details['date'].date()} RSI={phase1_details['rsi']:.1f} Vol={phase1_details['vol_ratio']:.1f}x")
                print(f"  RSI={rsi_14:.1f} EMA200=${ema_200:,.0f} VP.VAL=${vp['val']:,.0f} VP.VAH=${vp['vah']:,.0f}")

        # ── Phase 2/3: Hold or Exit ──
        elif phase in (2, 3) and current_trade is not None:
            current_trade["peak"] = max(current_trade["peak"], bar.high)

            # Phase 2 → 3: VAH breakout
            if phase == 2 and bar.close > vp["vah"]:
                phase = 3
                current_trade["vah_date"] = bar.timestamp
                print(f"  -> VAH breakout: {bar.timestamp.date()} @ ${bar.close:,.0f}")

            # Exit: RSI momentum fade
            if prev_rsi is not None and rsi_14 is not None:
                if prev_rsi > 75 and rsi_14 < 65:
                    _close_trade(current_trade, bar, "RSI_FADE", trades)
                    print(f"  X EXIT: {bar.timestamp.date()} @ ${bar.close:,.0f} PnL={current_trade['pnl_pct']:+.1f}% RSI {prev_rsi:.0f}->{rsi_14:.0f}")
                    phase = 0
                    current_trade = None
                    continue

            # Exit: 90d timeout
            days_held = (bar.timestamp - current_trade["entry_date"]).days
            if days_held > 90:
                _close_trade(current_trade, bar, "TIME_90D", trades)
                print(f"  T EXIT: {bar.timestamp.date()} @ ${bar.close:,.0f} PnL={current_trade['pnl_pct']:+.1f}% (90d)")
                phase = 0
                current_trade = None

    # Close any remaining open trade
    if current_trade is not None:
        last = bars_1d[-1]
        _close_trade(current_trade, last, "STILL_OPEN", trades)
        print(f"  ~ OPEN: {last.timestamp.date()} @ ${last.close:,.0f} PnL={current_trade['pnl_pct']:+.1f}%")

    # ── Summary ──
    print(f"\n{'=' * 100}")
    print("Summary")
    print(f"{'=' * 100}")
    print(f"Total trades: {len(trades)}")
    if not trades:
        return

    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    print(f"Win: {len(wins)} | Loss: {len(losses)} | WR: {100 * len(wins) / len(trades):.0f}%")
    if wins:
        print(f"Avg win: {sum(t['pnl_pct'] for t in wins) / len(wins):+.1f}%")
    if losses:
        print(f"Avg loss: {sum(t['pnl_pct'] for t in losses) / len(losses):+.1f}%")
    total_pnl = sum(t["pnl_pct"] for t in trades)
    print(f"Total return (1x): {total_pnl:+.1f}%")
    print(f"Total return (3x): {total_pnl * 3:+.1f}%")

    print(f"\n{'─' * 100}")
    print(f"{'#':>3} | {'Entry':>10} {'$Entry':>9} | {'Exit':>10} {'$Exit':>9} | {'PnL':>7} {'Peak':>7} | {'Days':>4} | {'Reason'}")
    print(f"{'─' * 100}")
    for idx, t in enumerate(trades):
        days = (t["exit_date"] - t["entry_date"]).days
        peak_pnl = (t["peak"] - t["entry_price"]) / t["entry_price"] * 100
        print(
            f"  {idx + 1} | {t['entry_date'].strftime('%Y-%m-%d')} ${t['entry_price']:>8,.0f}"
            f" | {t['exit_date'].strftime('%Y-%m-%d')} ${t['exit_price']:>8,.0f}"
            f" | {t['pnl_pct']:>+6.1f}% {peak_pnl:>+6.1f}%"
            f" | {days:>4}d"
            f" | {t['entry_reason']} -> {t['exit_reason']}"
        )
        print(
            f"      Cap: {t['phase1_date'].strftime('%Y-%m-%d')} RSI={t['phase1_rsi']:.1f}"
            f" | POC=${t['vp_poc']:,.0f} VAL=${t['vp_val']:,.0f} VAH=${t['vp_vah']:,.0f}"
        )


def _close_trade(trade: dict, bar, reason: str, trades: list) -> None:
    trade["exit_date"] = bar.timestamp
    trade["exit_price"] = bar.close
    trade["exit_reason"] = reason
    trade["pnl_pct"] = (bar.close - trade["entry_price"]) / trade["entry_price"] * 100
    trades.append(trade)


if __name__ == "__main__":
    main()
