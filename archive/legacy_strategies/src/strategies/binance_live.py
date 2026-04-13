"""Live Binance market data adapter — public API, no auth required.

Fetches real OHLCV klines from the Binance spot API with automatic
pagination for large date ranges (the API caps at 1000 candles per request).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from adapters.base import MarketBar, MarketDataAdapter


_BASE_URL = "https://api.binance.com"
_MAX_PER_REQUEST = 1000


_TIMEFRAME_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
}


class BinanceLiveAdapter(MarketDataAdapter):
    """Fetches real klines from Binance public API with pagination."""

    def __init__(self, base_url: str = _BASE_URL) -> None:
        self.base_url = base_url

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[MarketBar]:
        """Fetch the most recent *limit* bars (no date range)."""
        raw = self._get_klines(symbol=symbol, interval=timeframe, limit=min(limit, _MAX_PER_REQUEST))
        return [self._parse(row) for row in raw]

    def fetch_range(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[MarketBar]:
        """Fetch all bars in [start, end] with automatic pagination."""
        start_ms = int(start.replace(tzinfo=timezone.utc).timestamp() * 1000)
        end_ms = int(end.replace(tzinfo=timezone.utc).timestamp() * 1000)
        interval_ms = _TIMEFRAME_MS.get(timeframe)
        if interval_ms is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        all_bars: list[MarketBar] = []
        cursor = start_ms

        while cursor < end_ms:
            raw = self._get_klines(
                symbol=symbol,
                interval=timeframe,
                limit=_MAX_PER_REQUEST,
                start_time=cursor,
                end_time=end_ms,
            )
            if not raw:
                break

            for row in raw:
                bar = self._parse(row)
                all_bars.append(bar)

            last_open_ms = int(raw[-1][0])
            cursor = last_open_ms + interval_ms

            if len(raw) < _MAX_PER_REQUEST:
                break

            # polite rate limit
            time.sleep(0.3)

        return all_bars

    def _get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[list]:
        params: dict[str, str | int] = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time

        query = urlencode(params)
        url = f"{self.base_url}/api/v3/klines?{query}"
        request = Request(url=url, method="GET")
        request.add_header("Accept", "application/json")

        try:
            with urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Binance HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise RuntimeError(f"Binance request failed: {error.reason}") from error

    @staticmethod
    def _parse(row: list) -> MarketBar:
        return MarketBar(
            timestamp=datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc).replace(tzinfo=None),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
