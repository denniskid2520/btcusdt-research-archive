"""Thin Coinglass API v4 client for fetching derivatives data.

Supports: OI history, funding rate, liquidation, taker buy/sell volume.
Rate-limited to 30 req/min (Hobbyist plan).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class OIBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class FundingRateBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class LiquidationBar:
    timestamp: datetime
    long_usd: float
    short_usd: float


@dataclass(frozen=True)
class TakerVolumeBar:
    timestamp: datetime
    buy_usd: float
    sell_usd: float


class CoinglassClient:
    """Coinglass API v4 client with rate limiting."""

    BASE_URL = "https://open-api-v4.coinglass.com"
    MAX_LIMIT = 4500
    MIN_REQUEST_INTERVAL = 2.1  # 30 req/min → ~2s between requests

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._base_url = base_url or self.BASE_URL
        self._last_request_time = 0.0

    def fetch_oi_history(
        self,
        symbol: str = "BTC",
        interval: str = "4h",
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[OIBar]:
        """Fetch aggregated OI OHLC history (cross-exchange)."""
        all_bars: list[OIBar] = []
        current_end = end_time

        while True:
            params = {"symbol": symbol, "interval": interval, "limit": self.MAX_LIMIT}
            if start_time is not None:
                params["startTime"] = start_time
            if current_end is not None:
                params["endTime"] = current_end

            data = self._get_json("/api/futures/open-interest/aggregated-history", params)
            if not data:
                break

            bars = [
                OIBar(
                    timestamp=datetime.fromtimestamp(d["time"] / 1000, tz=timezone.utc).replace(tzinfo=None),
                    open=float(d["open"]),
                    high=float(d["high"]),
                    low=float(d["low"]),
                    close=float(d["close"]),
                )
                for d in data
            ]
            all_bars.extend(bars)

            if len(data) < self.MAX_LIMIT:
                break
            # Paginate backward: next page ends before earliest bar
            current_end = int(bars[0].timestamp.replace(tzinfo=timezone.utc).timestamp()) - 1
            if start_time is not None and current_end < start_time:
                break

        # Deduplicate and sort by time
        seen = set()
        unique = []
        for b in all_bars:
            if b.timestamp not in seen:
                seen.add(b.timestamp)
                unique.append(b)
        unique.sort(key=lambda b: b.timestamp)
        return unique

    def fetch_funding_rate_history(
        self,
        symbol: str = "BTC",
        interval: str = "4h",
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[FundingRateBar]:
        """Fetch OI-weighted funding rate history (cross-exchange)."""
        all_bars: list[FundingRateBar] = []
        current_end = end_time

        while True:
            params = {"symbol": symbol, "interval": interval, "limit": self.MAX_LIMIT}
            if start_time is not None:
                params["startTime"] = start_time
            if current_end is not None:
                params["endTime"] = current_end

            data = self._get_json("/api/futures/funding-rate/oi-weight-history", params)
            if not data:
                break

            bars = [
                FundingRateBar(
                    timestamp=datetime.fromtimestamp(d["time"] / 1000, tz=timezone.utc).replace(tzinfo=None),
                    open=float(d["open"]),
                    high=float(d["high"]),
                    low=float(d["low"]),
                    close=float(d["close"]),
                )
                for d in data
            ]
            all_bars.extend(bars)

            if len(data) < self.MAX_LIMIT:
                break
            current_end = int(bars[0].timestamp.replace(tzinfo=timezone.utc).timestamp()) - 1
            if start_time is not None and current_end < start_time:
                break

        seen = set()
        unique = []
        for b in all_bars:
            if b.timestamp not in seen:
                seen.add(b.timestamp)
                unique.append(b)
        unique.sort(key=lambda b: b.timestamp)
        return unique

    def fetch_liquidation_history(
        self,
        symbol: str = "BTC",
        interval: str = "4h",
        exchange_list: str = "Binance",
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[LiquidationBar]:
        """Fetch aggregated liquidation history."""
        all_bars: list[LiquidationBar] = []
        current_end = end_time

        while True:
            params = {
                "symbol": symbol,
                "interval": interval,
                "exchange_list": exchange_list,
                "limit": self.MAX_LIMIT,
            }
            if start_time is not None:
                params["startTime"] = start_time
            if current_end is not None:
                params["endTime"] = current_end

            data = self._get_json("/api/futures/liquidation/aggregated-history", params)
            if not data:
                break

            bars = [
                LiquidationBar(
                    timestamp=datetime.fromtimestamp(d["time"] / 1000, tz=timezone.utc).replace(tzinfo=None),
                    long_usd=float(d.get("aggregated_long_liquidation_usd", 0)),
                    short_usd=float(d.get("aggregated_short_liquidation_usd", 0)),
                )
                for d in data
            ]
            all_bars.extend(bars)

            if len(data) < self.MAX_LIMIT:
                break
            current_end = int(bars[0].timestamp.replace(tzinfo=timezone.utc).timestamp()) - 1
            if start_time is not None and current_end < start_time:
                break

        seen = set()
        unique = []
        for b in all_bars:
            if b.timestamp not in seen:
                seen.add(b.timestamp)
                unique.append(b)
        unique.sort(key=lambda b: b.timestamp)
        return unique

    def fetch_taker_volume_history(
        self,
        symbol: str = "BTC",
        interval: str = "4h",
        exchange_list: str = "Binance",
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[TakerVolumeBar]:
        """Fetch aggregated taker buy/sell volume history."""
        all_bars: list[TakerVolumeBar] = []
        current_end = end_time

        while True:
            params = {
                "symbol": symbol,
                "interval": interval,
                "exchange_list": exchange_list,
                "limit": self.MAX_LIMIT,
            }
            if start_time is not None:
                params["startTime"] = start_time
            if current_end is not None:
                params["endTime"] = current_end

            data = self._get_json("/api/futures/aggregated-taker-buy-sell-volume/history", params)
            if not data:
                break

            bars = [
                TakerVolumeBar(
                    timestamp=datetime.fromtimestamp(d["time"] / 1000, tz=timezone.utc).replace(tzinfo=None),
                    buy_usd=float(d.get("aggregated_buy_volume_usd", 0)),
                    sell_usd=float(d.get("aggregated_sell_volume_usd", 0)),
                )
                for d in data
            ]
            all_bars.extend(bars)

            if len(data) < self.MAX_LIMIT:
                break
            current_end = int(bars[0].timestamp.replace(tzinfo=timezone.utc).timestamp()) - 1
            if start_time is not None and current_end < start_time:
                break

        seen = set()
        unique = []
        for b in all_bars:
            if b.timestamp not in seen:
                seen.add(b.timestamp)
                unique.append(b)
        unique.sort(key=lambda b: b.timestamp)
        return unique

    def _get_json(self, path: str, params: dict | None = None) -> list | dict:
        """Make a rate-limited GET request."""
        # Rate limiting
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)

        query_parts = []
        for k, v in (params or {}).items():
            query_parts.append(f"{k}={v}")
        query = "&".join(query_parts)
        url = f"{self._base_url}{path}"
        if query:
            url = f"{url}?{query}"

        req = Request(url, method="GET")
        req.add_header("CG-API-KEY", self._api_key)
        req.add_header("Accept", "application/json")

        self._last_request_time = time.time()
        with urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        if result.get("code") != "0":
            raise RuntimeError(f"Coinglass API error: {result.get('msg', 'unknown')}")

        return result.get("data", [])
