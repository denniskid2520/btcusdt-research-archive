from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

from adapters.base import MarketBar, MarketDataAdapter
from adapters.binance_stub import BinanceStubAdapter


def backfill_to_csv(
    adapter: MarketDataAdapter,
    symbol: str,
    timeframe: str,
    limit: int,
    output_path: str | Path,
) -> Path:
    bars = adapter.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for bar in bars:
            writer.writerow(
                [
                    bar.timestamp.isoformat(),
                    f"{bar.open:.6f}",
                    f"{bar.high:.6f}",
                    f"{bar.low:.6f}",
                    f"{bar.close:.6f}",
                    f"{bar.volume:.6f}",
                ]
            )
    return destination


def load_bars_from_csv(path: str | Path) -> list[MarketBar]:
    source = Path(path)
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        bars: list[MarketBar] = []
        for row in reader:
            bars.append(
                MarketBar(
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
    if not bars:
        raise ValueError(f"No bars found in CSV: {source}")
    return bars


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill stub market data to CSV.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=180)
    parser.add_argument("--output", default="data/sample_bars.csv")
    args = parser.parse_args()

    output = backfill_to_csv(
        adapter=BinanceStubAdapter(),
        symbol=args.symbol,
        timeframe=args.timeframe,
        limit=args.limit,
        output_path=args.output,
    )
    print(f"Wrote {args.limit} bars to {output}")


if __name__ == "__main__":
    main()
