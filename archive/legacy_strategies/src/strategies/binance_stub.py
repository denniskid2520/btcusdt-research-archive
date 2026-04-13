from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from adapters.base import MarketBar, MarketDataAdapter


@dataclass(frozen=True)
class BinanceStubConfig:
    seed_price: float = 70000.0
    impulse_decay_pct: float = 0.009     # per-bar decay as fraction of seed
    wave_amplitude_pct: float = 0.016    # wave height as fraction of seed
    trend_decay_pct: float = 0.0025      # post-impulse trend per bar
    wick_pct: float = 0.002              # wick size as fraction of price
    floor_pct: float = 0.07              # minimum price as fraction of seed


class BinanceStubAdapter(MarketDataAdapter):
    """Deterministic impulse + channel stub for research and tests.

    All price movements are derived from seed_price using percentages,
    so the stub works for any asset at any price level.
    """

    def __init__(self, config: BinanceStubConfig | None = None) -> None:
        self.config = config or BinanceStubConfig()

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[MarketBar]:
        del symbol
        hours = _timeframe_to_hours(timeframe)
        start = datetime(2025, 1, 1)
        bars: list[MarketBar] = []
        impulse_cutoff = max(12, limit // 8)
        c = self.config
        amp = c.seed_price * c.wave_amplitude_pct
        wave_pattern = [0.0, amp, 2*amp, amp, 0.0, -amp, -2*amp, -amp]
        decay_per_bar = c.seed_price * c.impulse_decay_pct
        trend_per_bar = c.seed_price * c.trend_decay_pct
        wick = c.seed_price * c.wick_pct
        floor = c.seed_price * c.floor_pct
        previous_close = c.seed_price

        for index in range(limit):
            timestamp = start + timedelta(hours=index * hours)
            if index < impulse_cutoff:
                close_price = max(floor, c.seed_price - ((index + 1) * decay_per_bar))
            else:
                step = index - impulse_cutoff
                trend_component = step * -trend_per_bar
                wave_component = wave_pattern[step % len(wave_pattern)]
                base_price = c.seed_price - (impulse_cutoff * decay_per_bar)
                close_price = max(floor, base_price + trend_component + wave_component)

            open_price = previous_close
            high_price = max(open_price, close_price) + wick
            low_price = min(open_price, close_price) - wick
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
