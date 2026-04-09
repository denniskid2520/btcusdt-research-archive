"""Authenticated Binance USDT-M Futures broker for live order execution.

Handles: market orders, stop-market orders, position queries, balance.
Used by BBLiveEngine in live_mode=True.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import math
import os
import time
from typing import Any
from urllib.parse import urlencode

import requests

LOGGER = logging.getLogger("binance_broker")


class BinanceFuturesBroker:
    """Authenticated Binance USDT-M Futures broker."""

    BASE_URL = "https://fapi.binance.com"

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("BINANCE_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("BINANCE_API_SECRET", "")
        self._time_offset: int = 0
        if not self.api_key or not self.api_secret:
            raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET required")

    # ── Time sync ──

    def _sync_time(self) -> None:
        """Sync local clock with Binance server to avoid -1021 timestamp errors."""
        try:
            resp = requests.get(f"{self.BASE_URL}/fapi/v1/time", timeout=5)
            server_ts = resp.json()["serverTime"]
            local_ts = int(time.time() * 1000)
            self._time_offset = server_ts - local_ts
        except Exception as e:
            LOGGER.warning("Time sync failed: %s", e)

    # ── Request helpers ──

    def _sign(self, params: dict) -> dict:
        """Add timestamp and HMAC-SHA256 signature."""
        params["timestamp"] = int(time.time() * 1000) + self._time_offset
        query = urlencode(params)
        sig = hmac.new(
            self.api_secret.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = sig
        return params

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": self.api_key}

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
    ) -> Any:
        """Send authenticated request to Binance."""
        params = dict(params) if params else {}
        self._sync_time()
        params = self._sign(params)

        url = f"{self.BASE_URL}{path}"
        headers = self._headers()

        if method == "GET":
            resp = requests.get(url, params=params, headers=headers, timeout=10)
        elif method == "POST":
            resp = requests.post(url, params=params, headers=headers, timeout=10)
        elif method == "DELETE":
            resp = requests.delete(url, params=params, headers=headers, timeout=10)
        else:
            raise ValueError(f"Unsupported method: {method}")

        if resp.status_code != 200:
            LOGGER.error("API %s %s → %d: %s", method, path, resp.status_code, resp.text)
            resp.raise_for_status()
        return resp.json()

    # ── Account setup ──

    def ensure_leverage(self, symbol: str, leverage: int) -> None:
        """Verify and set leverage + isolated margin on the exchange."""
        # Set margin type to ISOLATED (ignore error if already set)
        try:
            self._request("POST", "/fapi/v1/marginType", {
                "symbol": symbol, "marginType": "ISOLATED",
            })
            LOGGER.info("Set %s margin to ISOLATED", symbol)
        except Exception:
            pass  # Already ISOLATED

        # Set leverage
        result = self._request("POST", "/fapi/v1/leverage", {
            "symbol": symbol, "leverage": leverage,
        })
        actual = result.get("leverage", leverage)
        LOGGER.info("Set %s leverage to %sx (confirmed: %s)", symbol, leverage, actual)
        if int(actual) != leverage:
            raise ValueError(
                f"Leverage mismatch: requested {leverage}x but got {actual}x"
            )

    def get_balance(self) -> dict:
        """Get USDT balance info."""
        data = self._request("GET", "/fapi/v2/account")
        for asset in data.get("assets", []):
            if asset["asset"] == "USDT":
                return {
                    "wallet": float(asset["walletBalance"]),
                    "available": float(asset["availableBalance"]),
                    "unrealized_pnl": float(asset["unrealizedProfit"]),
                }
        return {"wallet": 0.0, "available": 0.0, "unrealized_pnl": 0.0}

    def get_position(self, symbol: str = "BTCUSDT") -> dict:
        """Get current position for symbol."""
        data = self._request("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
        for pos in data:
            if pos["symbol"] == symbol:
                qty = float(pos["positionAmt"])
                return {
                    "symbol": symbol,
                    "side": "long" if qty > 0 else ("short" if qty < 0 else "flat"),
                    "qty": abs(qty),
                    "entry_price": float(pos["entryPrice"]),
                    "unrealized_pnl": float(pos["unRealizedProfit"]),
                    "leverage": int(pos["leverage"]),
                    "margin_type": pos.get("marginType", ""),
                }
        return {"symbol": symbol, "side": "flat", "qty": 0.0, "entry_price": 0.0}

    # ── Orders ──

    def place_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        """Place MARKET order. side: 'BUY' or 'SELL'.

        Quantity is rounded down to 0.001 (Binance BTCUSDT step size).
        """
        qty = math.floor(quantity * 1000) / 1000
        if qty < 0.001:
            raise ValueError(f"Quantity too small after rounding: {quantity} → {qty}")

        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "MARKET",
            "quantity": f"{qty:.3f}",
        }
        result = self._request("POST", "/fapi/v1/order", params)
        LOGGER.info(
            "MARKET %s %s %.3f → orderId=%s status=%s avgPrice=%s",
            side, symbol, qty,
            result.get("orderId"), result.get("status"), result.get("avgPrice"),
        )
        return result

    def place_stop_market(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
    ) -> dict:
        """Place STOP_MARKET order (for stop loss protection)."""
        qty = math.floor(quantity * 1000) / 1000
        if qty < 0.001:
            raise ValueError(f"Quantity too small: {qty}")

        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "STOP_MARKET",
            "quantity": f"{qty:.3f}",
            "stopPrice": f"{stop_price:.1f}",
            "workingType": "MARK_PRICE",
        }
        result = self._request("POST", "/fapi/v1/order", params)
        LOGGER.info(
            "STOP_MARKET %s %s %.3f @ $%.1f → orderId=%s",
            side, symbol, qty, stop_price, result.get("orderId"),
        )
        return result

    def cancel_all_orders(self, symbol: str) -> dict | None:
        """Cancel all open orders for symbol. Returns None if no orders."""
        try:
            return self._request("DELETE", "/fapi/v1/allOpenOrders", {"symbol": symbol})
        except Exception as e:
            LOGGER.warning("Cancel orders failed (may be empty): %s", e)
            return None

    def get_open_orders(self, symbol: str) -> list[dict]:
        """Get open orders for symbol."""
        return self._request("GET", "/fapi/v1/openOrders", {"symbol": symbol})

    def get_recent_trades(self, symbol: str, limit: int = 5) -> list[dict]:
        """Get recent account trades to find fill prices."""
        return self._request("GET", "/fapi/v1/userTrades", {
            "symbol": symbol,
            "limit": limit,
        })

    @staticmethod
    def round_qty(qty: float) -> float:
        """Round down to Binance BTCUSDT step size (0.001)."""
        return math.floor(qty * 1000) / 1000
