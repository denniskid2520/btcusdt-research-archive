"""Smoke test for Strategy C dataset fetcher.

Fetches a 4-hour window of BTCUSDT 15m data from Coinglass + local CSV,
aligns them, and prints the first/last unified row to verify the schema.

Run:
    PYTHONPATH=src python smoke_strategy_c.py
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src")

from adapters.coinglass_client import CoinglassClient
from data.strategy_c_dataset import (
    CSV_HEADER,
    fetch_strategy_c_bars,
)


API_KEY = os.environ.get("COINGLASS_API_KEY", "bcb3fec01f95440e9c4d635d4ded79ab")


def load_price_window(
    csv_path: str,
    start_ts: datetime,
    end_ts: datetime,
) -> list[tuple[datetime, float, float]]:
    """Load (timestamp, close, volume) from a Binance 15m CSV within the time window."""
    out = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = datetime.fromisoformat(row["timestamp"])
            if start_ts <= ts < end_ts:
                out.append((ts, float(row["close"]), float(row["volume"])))
    return out


def main() -> None:
    # Pick a 4h window from a date present in the local 15m CSV
    # CSV ends 2026-04-04, so use 2026-04-03 20:00 → 2026-04-04 00:00
    start = datetime(2026, 4, 3, 20, 0)
    end = datetime(2026, 4, 4, 0, 0)
    start_unix = int(start.replace(tzinfo=timezone.utc).timestamp())
    end_unix = int(end.replace(tzinfo=timezone.utc).timestamp())

    print(f"Window: {start.isoformat()} → {end.isoformat()} UTC")
    print(f"Expected: 16 bars (4h × 4 bars/h)")
    print()

    # Load price from local CSV
    price_bars = load_price_window(
        "src/data/btcusdt_15m_5year.csv",
        start_ts=start,
        end_ts=end,
    )
    print(f"Loaded {len(price_bars)} price bars from CSV")

    # Fetch Coinglass data for the same window
    client = CoinglassClient(api_key=API_KEY)

    print("Fetching Coinglass data (8 endpoints)...")
    bars = fetch_strategy_c_bars(
        client=client,
        price_bars=price_bars,
        exchange="Binance",
        symbol="BTCUSDT",
        interval="15m",
        start_time=start_unix,
        end_time=end_unix,
    )
    print(f"Aligned: {len(bars)} unified bars")
    print()

    if not bars:
        print("ERROR: No aligned bars produced!")
        return

    # Print schema header + first/last row
    print("=" * 80)
    print("SCHEMA:")
    print("  " + " | ".join(CSV_HEADER))
    print()

    print("FIRST BAR:")
    b = bars[0]
    print(f"  ts={b.timestamp.isoformat()}")
    print(f"  close=${b.close:,.2f}  volume={b.volume:.2f}")
    print(f"  oi_close=${b.oi_close:,.0f}  oi_pct={b.oi_pct_change:+.4%}")
    print(f"  funding={b.funding:+.6f}  funding_w={b.funding_oi_weighted:+.6f}")
    print(f"  long_liq=${b.long_liq_usd:,.0f}  short_liq=${b.short_liq_usd:,.0f}  imb={b.liq_imbalance:+.3f}")
    print(f"  taker_buy=${b.taker_buy_usd:,.0f}  taker_sell=${b.taker_sell_usd:,.0f}  delta=${b.taker_delta_usd:+,.0f}")
    print(f"  cvd={b.cvd:+,.0f}")
    print(f"  basis={b.basis:.4f}")
    print(f"  stablecoin_oi={b.stablecoin_oi:,.0f} BTC")
    print()

    print("LAST BAR:")
    b = bars[-1]
    print(f"  ts={b.timestamp.isoformat()}")
    print(f"  close=${b.close:,.2f}")
    print(f"  oi_close=${b.oi_close:,.0f}  oi_pct={b.oi_pct_change:+.4%}")
    print(f"  funding={b.funding:+.6f}")
    print(f"  liq_imb={b.liq_imbalance:+.3f}")
    print(f"  taker_delta=${b.taker_delta_usd:+,.0f}")
    print(f"  cvd={b.cvd:+,.0f}")
    print()

    # Sanity checks
    print("=" * 80)
    print("SANITY CHECKS:")
    print(f"  All bars have non-zero close: {all(b.close > 0 for b in bars)}")
    print(f"  All bars have OI > 0: {all(b.oi_close > 0 for b in bars)}")
    print(f"  Timestamps strictly increasing: {all(bars[i].timestamp < bars[i+1].timestamp for i in range(len(bars)-1))}")
    print(f"  First bar oi_pct_change == 0: {bars[0].oi_pct_change == 0.0}")


if __name__ == "__main__":
    main()
