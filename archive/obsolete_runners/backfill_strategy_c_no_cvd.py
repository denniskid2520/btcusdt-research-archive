"""Backfill BTCUSDT 15m data WITHOUT pair_cvd — max available 90-day window.

pair_cvd is the limiting factor on history length (it clips the dataset to
~47 days because of exchange-side retention). The event study + sweep
comparison showed that dropping cvd improves holdout metrics across the
board, so we rebuild the dataset without it and get ~2x more history to
validate on.

Run:
    python backfill_strategy_c_no_cvd.py
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src")

from adapters.coinglass_client import CoinglassClient
from data.strategy_c_dataset import (
    fetch_strategy_c_bars,
    save_strategy_c_csv,
)


API_KEY = os.environ.get("COINGLASS_API_KEY", "bcb3fec01f95440e9c4d635d4ded79ab")

START = datetime(2026, 1, 11, 0, 0)
END = datetime(2026, 4, 4, 0, 0)

PRICE_CSV = "src/data/btcusdt_15m_5year.csv"
OUTPUT_CSV = "src/data/strategy_c_btcusdt_15m_nocvd.csv"


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
    print(f"Window: {START.isoformat()} -> {END.isoformat()} UTC")
    print(f"Expected: ~{days * 96} bars ({days} days x 96 bars/day)")
    print()

    print(f"Loading price from {PRICE_CSV}...")
    price_bars = load_price_window(PRICE_CSV, START, END)
    print(f"  {len(price_bars)} price bars loaded")
    print()

    if not price_bars:
        print("ERROR: No price bars found in CSV for this window.")
        return

    start_unix = int(START.replace(tzinfo=timezone.utc).timestamp())
    end_unix = int(END.replace(tzinfo=timezone.utc).timestamp())

    print("Fetching Coinglass data (7 endpoints, pair_cvd SKIPPED)...")
    client = CoinglassClient(api_key=API_KEY)
    bars = fetch_strategy_c_bars(
        client=client,
        price_bars=price_bars,
        exchange="Binance",
        symbol="BTCUSDT",
        interval="15m",
        start_time=start_unix,
        end_time=end_unix,
        include_cvd=False,
    )
    print(f"  Aligned: {len(bars)} unified bars")
    print()

    if not bars:
        print("ERROR: No aligned bars produced.")
        return

    save_strategy_c_csv(bars, OUTPUT_CSV)
    print(f"Saved: {OUTPUT_CSV}")
    print()

    print("=" * 70)
    first = bars[0]
    last = bars[-1]
    print(f"Coverage: {first.timestamp.isoformat()} -> {last.timestamp.isoformat()}")
    span_days = (last.timestamp - first.timestamp).total_seconds() / 86400
    print(f"Span:     {span_days:.1f} days ({len(bars)} bars)")
    print(f"Price:    ${first.close:,.0f} -> ${last.close:,.0f}")
    print(f"OI:       ${first.oi_close/1e9:.2f}B -> ${last.oi_close/1e9:.2f}B")


if __name__ == "__main__":
    main()
