"""Backfill Binance USDT-M BTCUSDT funding rate history to CSV.

Uses the newly wired `BinanceFuturesAdapter.fetch_funding_rate_history` to
pull ~5 years of settled 8h funding rates from Binance's public
/fapi/v1/fundingRate endpoint. No auth required.

Output:
    src/data/btcusdt_funding_5year.csv
    Columns: timestamp (ISO naive UTC), funding_rate (float), mark_price (float)

Sanity checks post-fetch:
    - Records must be strictly ascending in time
    - Expected count ≈ (years * 365 * 3) records (3/day @ 8h cadence)
    - funding_rate values must be within plausible range [-0.01, 0.01]

Usage:
    python backfill_binance_funding.py
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "src")

from adapters.binance_futures import BinanceFuturesAdapter  # noqa: E402


SYMBOL = "BTCUSDT"
START = datetime(2020, 4, 1)
END = datetime(2026, 4, 11)

OUTPUT_PATH = Path("src/data/btcusdt_funding_5year.csv")


def main() -> None:
    print("=" * 72)
    print(f"Binance funding-rate backfill: {SYMBOL}")
    print(f"Range: {START.isoformat()} -> {END.isoformat()}")
    print("=" * 72)

    adapter = BinanceFuturesAdapter()

    print("Fetching (this will paginate ~6 times)...")
    records = adapter.fetch_funding_rate_history(SYMBOL, start=START, end=END)

    if not records:
        print("No records returned. Aborting.")
        sys.exit(1)

    print(f"Fetched {len(records)} records.")
    mark0 = f"{records[0].mark_price:,.2f}" if records[0].mark_price is not None else "None"
    markN = f"{records[-1].mark_price:,.2f}" if records[-1].mark_price is not None else "None"
    print(f"First: {records[0].timestamp.isoformat()}  rate={records[0].funding_rate:+.6f}  mark={mark0}")
    print(f"Last : {records[-1].timestamp.isoformat()}  rate={records[-1].funding_rate:+.6f}  mark={markN}")

    n_missing_mark = sum(1 for r in records if r.mark_price is None)
    if n_missing_mark:
        print(f"Note: {n_missing_mark} records have missing markPrice (early Binance quirk).")

    # Sanity: strict ascending.
    for a, b in zip(records, records[1:]):
        if not a.timestamp < b.timestamp:
            print(f"ERROR: not strictly ascending at {a.timestamp} -> {b.timestamp}")
            sys.exit(2)

    # Sanity: plausible range.
    rates = [r.funding_rate for r in records]
    r_min, r_max = min(rates), max(rates)
    print(f"Rate range: [{r_min:+.6f}, {r_max:+.6f}]")
    if r_min < -0.01 or r_max > 0.01:
        print(f"WARNING: funding rate out of [-1%, +1%] range; check data.")

    # Sanity: expected count at 8h cadence.
    span_seconds = (records[-1].timestamp - records[0].timestamp).total_seconds()
    expected = int(span_seconds / (8 * 3600)) + 1
    coverage = len(records) / expected if expected else 0.0
    print(f"Coverage: {len(records)}/{expected} expected ({coverage * 100:.1f}%)")

    # Write CSV.
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp", "funding_rate", "mark_price"])
        for rec in records:
            mark_str = f"{rec.mark_price:.2f}" if rec.mark_price is not None else ""
            writer.writerow([
                rec.timestamp.isoformat(),
                f"{rec.funding_rate:.8f}",
                mark_str,
            ])

    print(f"Wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size:,} bytes)")
    print("Done.")


if __name__ == "__main__":
    main()
