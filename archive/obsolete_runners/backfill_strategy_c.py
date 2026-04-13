"""Backfill BTCUSDT 15m data for Strategy C — max available window.

Coinglass STANDARD plan only exposes ~90 days of 15m history. We use the
earliest allowed start (~2026-01-11) through the latest date in the local
price CSV (2026-04-04). Fetches all 8 Coinglass channels + aligns to price.
Saves to src/data/strategy_c_btcusdt_15m.csv.

Run:
    python backfill_strategy_c.py
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "src")

from adapters.coinglass_client import CoinglassClient
from data.strategy_c_dataset import (
    fetch_strategy_c_bars,
    save_strategy_c_csv,
)


API_KEY = os.environ.get("COINGLASS_API_KEY", "bcb3fec01f95440e9c4d635d4ded79ab")

# Max 15m history on STANDARD plan ≈ 90 days back from today (2026-04-10).
# Probed earliest allowed start_time = 2026-01-10 09:29 UTC across all endpoints.
# Use 2026-01-11 00:00 for a clean boundary + safety buffer.
# End at the latest timestamp in the local price CSV (2026-04-04).
START = datetime(2026, 1, 11, 0, 0)
END = datetime(2026, 4, 4, 0, 0)

PRICE_CSV = "src/data/btcusdt_15m_5year.csv"
OUTPUT_CSV = "src/data/strategy_c_btcusdt_15m.csv"


def load_price_window(csv_path: str, start_ts: datetime, end_ts: datetime) -> list[tuple[datetime, float, float, float]]:
    out = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = datetime.fromisoformat(row["timestamp"])
            if start_ts <= ts < end_ts:
                out.append((ts, float(row["open"]), float(row["close"]), float(row["volume"])))
    return out


def main() -> None:
    days = (END - START).days
    print(f"Window: {START.isoformat()} → {END.isoformat()} UTC")
    print(f"Expected: ~{days * 96} bars ({days} days × 96 bars/day)")
    print()

    # 1. Load price from local CSV
    print(f"Loading price from {PRICE_CSV}...")
    price_bars = load_price_window(PRICE_CSV, START, END)
    print(f"  {len(price_bars)} price bars loaded")
    print()

    if not price_bars:
        print("ERROR: No price bars found in CSV for this window.")
        return

    # 2. Fetch Coinglass (8 endpoints, paginated)
    start_unix = int(START.replace(tzinfo=timezone.utc).timestamp())
    end_unix = int(END.replace(tzinfo=timezone.utc).timestamp())

    print("Fetching Coinglass data (8 endpoints)...")
    print("  This takes ~15-30s due to pagination + rate limiting.")
    client = CoinglassClient(api_key=API_KEY)
    bars = fetch_strategy_c_bars(
        client=client,
        price_bars=price_bars,
        exchange="Binance",
        symbol="BTCUSDT",
        interval="15m",
        start_time=start_unix,
        end_time=end_unix,
    )
    print(f"  Aligned: {len(bars)} unified bars")
    print()

    if not bars:
        print("ERROR: No aligned bars produced.")
        return

    # 3. Save to CSV
    save_strategy_c_csv(bars, OUTPUT_CSV)
    print(f"Saved: {OUTPUT_CSV}")
    print()

    # 4. Summary
    print("=" * 70)
    first = bars[0]
    last = bars[-1]
    print(f"Coverage: {first.timestamp.isoformat()} → {last.timestamp.isoformat()}")
    span_days = (last.timestamp - first.timestamp).total_seconds() / 86400
    print(f"Span:     {span_days:.1f} days ({len(bars)} bars)")
    print(f"Price:    ${first.close:,.0f} → ${last.close:,.0f}")
    print(f"OI:       ${first.oi_close/1e9:.2f}B → ${last.oi_close/1e9:.2f}B")
    print(f"First bar liq_imbalance: {first.liq_imbalance:+.3f}")


if __name__ == "__main__":
    main()
