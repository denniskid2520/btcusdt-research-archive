from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from quant_trading.config import BinanceConfig
from quant_trading.models import Candle


class BinanceAPIError(RuntimeError):
    pass


class BinanceClient:
    def __init__(self, config: BinanceConfig | None = None) -> None:
        self.config = config or BinanceConfig()
        self.base_url = (
            "https://testnet.binance.vision" if self.config.use_testnet else self.config.base_url
        )
        self.api_key = os.getenv(self.config.api_key_env, "")
        self.api_secret = os.getenv(self.config.api_secret_env, "")

    def get_klines(
        self,
        symbol: str | None = None,
        interval: str | None = None,
        limit: int | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[Candle]:
        params: dict[str, Any] = {
            "symbol": symbol or self.config.symbol,
            "interval": interval or self.config.interval,
            "limit": limit or self.config.limit,
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time

        payload = self._request("GET", "/api/v3/klines", params=params)
        return [self._parse_kline(row) for row in payload]

    def get_ticker_price(self, symbol: str | None = None) -> float:
        payload = self._request("GET", "/api/v3/ticker/price", params={"symbol": symbol or self.config.symbol})
        return float(payload["price"])

    def create_test_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
    ) -> dict[str, Any]:
        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type,
            "quantity": self._format_quantity(quantity),
            "timestamp": self._timestamp_ms(),
        }
        return self._signed_request("POST", "/api/v3/order/test", params=params)

    def create_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
    ) -> dict[str, Any]:
        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type,
            "quantity": self._format_quantity(quantity),
            "timestamp": self._timestamp_ms(),
        }
        return self._signed_request("POST", "/api/v3/order", params=params)

    def _signed_request(self, method: str, path: str, params: dict[str, Any]) -> Any:
        if not self.api_key or not self.api_secret:
            raise BinanceAPIError(
                f"Missing credentials. Set {self.config.api_key_env} and {self.config.api_secret_env}."
            )

        query = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed_params = dict(params)
        signed_params["signature"] = signature
        return self._request(method, path, params=signed_params, api_key=self.api_key)

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        api_key: str | None = None,
    ) -> Any:
        query = urlencode(params or {})
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"

        request = Request(url=url, method=method)
        request.add_header("Accept", "application/json")
        if api_key:
            request.add_header("X-MBX-APIKEY", api_key)

        try:
            with urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise BinanceAPIError(f"Binance HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise BinanceAPIError(f"Binance request failed: {error.reason}") from error

    @staticmethod
    def _parse_kline(row: list[Any]) -> Candle:
        return Candle(
            timestamp=datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC).replace(tzinfo=None),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )

    @staticmethod
    def _format_quantity(quantity: float) -> str:
        return f"{quantity:.6f}".rstrip("0").rstrip(".")

    @staticmethod
    def _timestamp_ms() -> int:
        return int(time.time() * 1000)
