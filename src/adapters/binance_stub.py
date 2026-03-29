from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from adapters.base import MarketBar, MarketDataAdapter


@dataclass(frozen=True)
class BinanceStubConfig:
    seed_price: float = 70000.0


class BinanceStubAdapter(MarketDataAdapter):
    """Deterministic impulse + channel stub for research and tests."""

    def __init__(self, config: BinanceStubConfig | None = None) -> None:
        self.config = config or BinanceStubConfig()

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[MarketBar]:
        del symbol
        hours = _timeframe_to_hours(timeframe)
        start = datetime(2025, 1, 1)
        bars: list[MarketBar] = []
        impulse_cutoff = max(12, limit // 8)
        wave_pattern = [0.0, 550.0, 1100.0, 550.0, 0.0, -550.0, -1100.0, -550.0]
        previous_close = self.config.seed_price

        for index in range(limit):
            timestamp = start + timedelta(hours=index * hours)
            if index < impulse_cutoff:
                close_price = max(5000.0, self.config.seed_price - ((index + 1) * 620.0))
            else:
                step = index - impulse_cutoff
                trend_component = step * -175.0
                wave_component = wave_pattern[step % len(wave_pattern)]
                base_price = self.config.seed_price - (impulse_cutoff * 620.0)
                close_price = max(5000.0, base_price + trend_component + wave_component)

            open_price = previous_close
            high_price = max(open_price, close_price) + 140
            low_price = min(open_price, close_price) - 140
            bars.append(
                MarketBar(
                    timestamp=timestamp,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    volume=1000 + (index * 15),
                )
            )
            previous_close = close_price

        return bars


def _timeframe_to_hours(timeframe: str) -> int:
    if timeframe.endswith("h"):
        return int(timeframe[:-1])
    if timeframe.endswith("d"):
        return int(timeframe[:-1]) * 24
    raise ValueError(f"Unsupported timeframe for stub: {timeframe}")
