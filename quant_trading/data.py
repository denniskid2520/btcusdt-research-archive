from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from quant_trading.models import Candle


REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


def load_ohlcv_csv(path: str | Path) -> list[Candle]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Data file not found: {file_path}")

    with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file has no header row.")

        missing = [name for name in REQUIRED_COLUMNS if name not in reader.fieldnames]
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")

        candles: list[Candle] = []
        for row in reader:
            candles.append(
                Candle(
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )

    if len(candles) < 2:
        raise ValueError("At least two rows of market data are required.")

    return candles
