"""Coinglass data backfill — fetch historical derivatives data to CSV.

Usage:
    python -m data.coinglass_backfill --api-key KEY --output-dir src/data
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

from adapters.coinglass_client import (
    CoinglassClient,
    FundingRateBar,
    LiquidationBar,
    OIBar,
    TakerVolumeBar,
)


def save_oi_csv(bars: list[OIBar], path: str | Path) -> Path:
    p = Path(path)
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close"])
        for b in bars:
            writer.writerow([b.timestamp.isoformat(), b.open, b.high, b.low, b.close])
    return p


def load_oi_csv(path: str | Path) -> list[OIBar]:
    bars = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(OIBar(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            ))
    return bars


def save_funding_csv(bars: list[FundingRateBar], path: str | Path) -> Path:
    p = Path(path)
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close"])
        for b in bars:
            writer.writerow([b.timestamp.isoformat(), b.open, b.high, b.low, b.close])
    return p


def load_funding_csv(path: str | Path) -> list[FundingRateBar]:
    bars = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(FundingRateBar(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            ))
    return bars


def save_liquidation_csv(bars: list[LiquidationBar], path: str | Path) -> Path:
    p = Path(path)
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "long_usd", "short_usd"])
        for b in bars:
            writer.writerow([b.timestamp.isoformat(), b.long_usd, b.short_usd])
    return p


def load_liquidation_csv(path: str | Path) -> list[LiquidationBar]:
    bars = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(LiquidationBar(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                long_usd=float(row["long_usd"]),
                short_usd=float(row["short_usd"]),
            ))
    return bars


def save_taker_volume_csv(bars: list[TakerVolumeBar], path: str | Path) -> Path:
    p = Path(path)
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "buy_usd", "sell_usd"])
        for b in bars:
            writer.writerow([b.timestamp.isoformat(), b.buy_usd, b.sell_usd])
    return p


def load_taker_volume_csv(path: str | Path) -> list[TakerVolumeBar]:
    bars = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(TakerVolumeBar(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                buy_usd=float(row["buy_usd"]),
                sell_usd=float(row["sell_usd"]),
            ))
    return bars


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Coinglass derivatives data to CSV")
    parser.add_argument("--api-key", required=True, help="Coinglass API key")
    parser.add_argument("--symbol", default="BTC", help="Symbol (default: BTC)")
    parser.add_argument("--interval", default="4h", help="Interval (default: 4h)")
    parser.add_argument("--output-dir", default="src/data", help="Output directory")
    parser.add_argument("--exchange-list", default="Binance", help="Exchange for liquidation/taker volume")
    args = parser.parse_args()

    client = CoinglassClient(api_key=args.api_key)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print(f"Backfilling {args.symbol} {args.interval} data from Coinglass...")

    # 1. OI history
    print("\n[1/4] Fetching OI history...")
    oi_bars = client.fetch_oi_history(symbol=args.symbol, interval=args.interval)
    if oi_bars:
        path = save_oi_csv(oi_bars, out / "coinglass_oi_4h.csv")
        print(f"  Saved {len(oi_bars)} bars to {path}")
        print(f"  Range: {oi_bars[0].timestamp} to {oi_bars[-1].timestamp}")
    else:
        print("  No OI data returned")

    # 2. Funding rate history
    print("\n[2/4] Fetching funding rate history...")
    funding_bars = client.fetch_funding_rate_history(symbol=args.symbol, interval=args.interval)
    if funding_bars:
        path = save_funding_csv(funding_bars, out / "coinglass_funding_4h.csv")
        print(f"  Saved {len(funding_bars)} bars to {path}")
        print(f"  Range: {funding_bars[0].timestamp} to {funding_bars[-1].timestamp}")
    else:
        print("  No funding rate data returned")

    # 3. Liquidation history
    print("\n[3/4] Fetching liquidation history...")
    liq_bars = client.fetch_liquidation_history(
        symbol=args.symbol, interval=args.interval, exchange_list=args.exchange_list,
    )
    if liq_bars:
        path = save_liquidation_csv(liq_bars, out / "coinglass_liquidation_4h.csv")
        print(f"  Saved {len(liq_bars)} bars to {path}")
        print(f"  Range: {liq_bars[0].timestamp} to {liq_bars[-1].timestamp}")
    else:
        print("  No liquidation data returned")

    # 4. Taker buy/sell volume
    print("\n[4/4] Fetching taker buy/sell volume history...")
    taker_bars = client.fetch_taker_volume_history(
        symbol=args.symbol, interval=args.interval, exchange_list=args.exchange_list,
    )
    if taker_bars:
        path = save_taker_volume_csv(taker_bars, out / "coinglass_taker_volume_4h.csv")
        print(f"  Saved {len(taker_bars)} bars to {path}")
        print(f"  Range: {taker_bars[0].timestamp} to {taker_bars[-1].timestamp}")
    else:
        print("  No taker volume data returned")

    print("\nBackfill complete!")


if __name__ == "__main__":
    main()
