#!/usr/bin/env python3
"""Add RSI(3), RSI(7), RSI(14) analysis to all 6 channels using Binance daily data."""
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

from adapters.binance_futures import BinanceFuturesAdapter


def compute_rsi(closes: list[float], period: int) -> list[float]:
    """Compute RSI for a list of closes. Returns list same length, with 0 for insufficient data."""
    rsi = [0.0] * len(closes)
    if len(closes) < period + 1:
        return rsi

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    # First avg
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        if i == period:
            # First RSI value
            pass
        else:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100 - 100 / (1 + rs)

    return rsi


def main():
    adapter = BinanceFuturesAdapter()

    # Fetch daily bars from 2022-01 to 2026-04
    print("Fetching daily bars from Binance Futures...")
    start = datetime(2022, 1, 1)
    end = datetime(2026, 4, 6)
    bars = adapter.fetch_range("BTCUSDT", "1d", start, end)
    print(f"Got {len(bars)} daily bars: {bars[0].timestamp} to {bars[-1].timestamp}")

    # Build date -> index mapping
    closes = [b.close for b in bars]
    date_to_idx = {}
    for i, b in enumerate(bars):
        d = b.timestamp.strftime("%Y-%m-%d")
        date_to_idx[d] = i

    # Compute RSI
    rsi3 = compute_rsi(closes, 3)
    rsi7 = compute_rsi(closes, 7)
    rsi14 = compute_rsi(closes, 14)

    # All channel events
    CHANNELS = {
        "C": [
            ("2022-01-24", 33000, "low", "start"),
            ("2022-02-10", 45821, "high", ""),
            ("2022-02-24", 34300, "low", ""),
            ("2022-03-02", 45400, "high", ""),
            ("2022-03-09", 37000, "mid", "retest"),
            ("2022-03-28", 48189, "high", "peak"),
            ("2022-04-11", 39200, "low", ""),
            ("2022-04-18", 41500, "mid", ""),
            ("2022-04-28", 37600, "low", "broke"),
        ],
        "A": [
            ("2022-05-01", 38500, "high", ""),
            ("2022-05-05", 36000, "low", ""),
            ("2022-05-09", 34000, "low", ""),
            ("2022-05-12", 28800, "low", "broke"),
            ("2022-05-16", 31300, "mid", "retest"),
        ],
        "B": [
            ("2022-06-18", 17570, "low", "start"),
            ("2022-06-26", 21888, "high", ""),
            ("2022-06-30", 18800, "low", ""),
            ("2022-07-08", 22400, "high", ""),
            ("2022-07-13", 19200, "low", ""),
            ("2022-07-20", 24200, "high", ""),
            ("2022-07-26", 20700, "low", ""),
            ("2022-08-04", 23200, "mid", ""),
            ("2022-08-10", 24900, "high", "peak"),
            ("2022-08-15", 24400, "mid", ""),
            ("2022-08-19", 21300, "low", "broke"),
            ("2022-08-26", 21800, "mid", "retest"),
        ],
        "D": [
            ("2025-04-09", 75000, "low", "start"),
            ("2025-05-12", 104000, "high", ""),
            ("2025-06-06", 98700, "low", ""),
            ("2025-06-13", 106000, "high", ""),
            ("2025-06-20", 101500, "low", ""),
            ("2025-07-03", 109000, "high", ""),
            ("2025-08-02", 104000, "mid", ""),
            ("2025-08-18", 107000, "high", ""),
            ("2025-09-01", 109000, "high", "peak"),
            ("2025-09-16", 105000, "mid", "retest_fail"),
            ("2025-10-02", 99000, "low", "broke"),
        ],
        "E": [
            ("2025-11-21", 80600, "low", "start"),
            ("2025-11-28", 93036, "high", ""),
            ("2025-12-01", 83757, "low", ""),
            ("2025-12-03", 94164, "high", ""),
            ("2025-12-06", 89214, "mid", "retest"),
            ("2025-12-09", 94571, "high", ""),
            ("2025-12-18", 85426, "low", ""),
            ("2025-12-22", 90537, "mid", "retest_fail"),
            ("2025-12-29", 86673, "low", ""),
            ("2026-01-05", 94736, "mid", ""),
            ("2026-01-14", 97879, "high", "peak"),
            ("2026-01-20", 87695, "low", "broke"),
            ("2026-01-28", 89131, "mid", "retest_fail"),
        ],
        "F": [
            ("2026-02-05", 62749, "low", "start"),
            ("2026-02-06", 71645, "high", ""),
            ("2026-02-24", 64023, "low", ""),
            ("2026-03-04", 74041, "high", ""),
            ("2026-03-08", 65572, "low", ""),
            ("2026-03-16", 74847, "high", "peak"),
            ("2026-03-22", 67305, "low", ""),
            ("2026-03-25", 71980, "mid", "retest_fail"),
            ("2026-03-27", 65470, "low", "broke"),
            ("2026-04-04", 69600, "mid", "retesting"),
        ],
    }

    # Print per-channel RSI
    print()
    print("=" * 120)
    print("RSI ANALYSIS — ALL 6 CHANNELS")
    print("=" * 120)

    # Collect all events by type for cross-channel comparison
    all_events = {"high": [], "low": [], "mid": [], "broke": []}

    for ch_name, events in CHANNELS.items():
        print(f"\n--- Channel {ch_name} ---")
        print(f"  {'Date':<12} {'Price':>8} {'Type':<6} {'Note':<15} {'RSI(3)':>8} {'RSI(7)':>8} {'RSI(14)':>8} {'Close':>10}")
        print(f"  {'-'*85}")

        for date, price, etype, note in events:
            idx = date_to_idx.get(date)
            if idx is None:
                # Try nearby dates
                from datetime import timedelta
                dt = datetime.strptime(date, "%Y-%m-%d")
                for offset in range(-2, 3):
                    alt = (dt + timedelta(days=offset)).strftime("%Y-%m-%d")
                    if alt in date_to_idx:
                        idx = date_to_idx[alt]
                        break

            r3 = rsi3[idx] if idx is not None else 0
            r7 = rsi7[idx] if idx is not None else 0
            r14 = rsi14[idx] if idx is not None else 0
            actual_close = closes[idx] if idx is not None else 0

            print(f"  {date:<12} {price:>8} {etype:<6} {note:<15} {r3:>7.1f} {r7:>7.1f} {r14:>7.1f} {actual_close:>9.0f}")

            # Collect for cross-channel
            event_data = {
                "channel": ch_name, "date": date, "price": price,
                "rsi3": r3, "rsi7": r7, "rsi14": r14, "note": note,
            }
            if "broke" in note:
                all_events["broke"].append(event_data)
            elif etype == "high":
                all_events["high"].append(event_data)
            elif etype == "low":
                all_events["low"].append(event_data)
            elif etype == "mid":
                all_events["mid"].append(event_data)

    # Cross-channel RSI comparison
    print()
    print("=" * 100)
    print("CROSS-CHANNEL RSI COMPARISON — BY EVENT TYPE")
    print("=" * 100)

    for etype_label, etype_key in [("HIGHS", "high"), ("LOWS (non-break)", "low"), ("MIDS", "mid"), ("BREAKDOWNS", "broke")]:
        events_list = all_events[etype_key]
        if not events_list:
            continue
        print(f"\n  {etype_label}:")
        print(f"  {'Channel':<6} {'Date':<12} {'Price':>8} {'RSI(3)':>8} {'RSI(7)':>8} {'RSI(14)':>8} {'Note'}")
        print(f"  {'-'*70}")
        for e in events_list:
            print(f"  {e['channel']:<6} {e['date']:<12} {e['price']:>8} {e['rsi3']:>7.1f} {e['rsi7']:>7.1f} {e['rsi14']:>7.1f}  {e['note']}")

        # Averages
        r3_vals = [e["rsi3"] for e in events_list if e["rsi3"] > 0]
        r7_vals = [e["rsi7"] for e in events_list if e["rsi7"] > 0]
        r14_vals = [e["rsi14"] for e in events_list if e["rsi14"] > 0]
        if r3_vals:
            print(f"  {'AVG':<6} {'':12} {'':>8} {sum(r3_vals)/len(r3_vals):>7.1f} {sum(r7_vals)/len(r7_vals):>7.1f} {sum(r14_vals)/len(r14_vals):>7.1f}")
            print(f"  {'MIN':<6} {'':12} {'':>8} {min(r3_vals):>7.1f} {min(r7_vals):>7.1f} {min(r14_vals):>7.1f}")
            print(f"  {'MAX':<6} {'':12} {'':>8} {max(r3_vals):>7.1f} {max(r7_vals):>7.1f} {max(r14_vals):>7.1f}")

    # RSI at breakdown: range analysis
    print()
    print("=" * 100)
    print("BREAKDOWN RSI DEEP DIVE — Window around breakdown")
    print("=" * 100)

    for ch_name, events in CHANNELS.items():
        broke_date = None
        for date, price, etype, note in events:
            if "broke" in note:
                broke_date = date
                break
        if not broke_date:
            continue

        idx = date_to_idx.get(broke_date)
        if idx is None:
            continue

        print(f"\n  Channel {ch_name} — Breakdown: {broke_date}")
        print(f"  {'Date':<12} {'Close':>10} {'RSI(3)':>8} {'RSI(7)':>8} {'RSI(14)':>8}")
        print(f"  {'-'*50}")

        for offset in range(-7, 4):
            i = idx + offset
            if 0 <= i < len(bars):
                d = bars[i].timestamp.strftime("%Y-%m-%d")
                tag = " <--" if offset == 0 else ""
                print(f"  {d:<12} {closes[i]:>9.0f} {rsi3[i]:>7.1f} {rsi7[i]:>7.1f} {rsi14[i]:>7.1f}{tag}")


if __name__ == "__main__":
    main()
