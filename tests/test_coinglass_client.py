"""Tests for Coinglass client — new data types: Top L/S Ratio, CVD, Basis.

TDD: write failing tests first, then implement.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from unittest.mock import patch

import pytest

from adapters.coinglass_client import (
    CoinglassClient,
    TopLSRatioBar,
    CVDBar,
    BasisBar,
)


# ── Data classes ──────────────────────────────────────────────────────


def test_top_ls_ratio_bar_fields() -> None:
    bar = TopLSRatioBar(
        timestamp=datetime(2026, 1, 1),
        long_percent=60.5,
        short_percent=39.5,
        ratio=1.53,
    )
    assert bar.long_percent == 60.5
    assert bar.short_percent == 39.5
    assert bar.ratio == 1.53


def test_cvd_bar_fields() -> None:
    bar = CVDBar(
        timestamp=datetime(2026, 1, 1),
        buy_vol=280_504_501.21,
        sell_vol=247_025_969.49,
        cvd=10_975_605.00,
    )
    assert bar.buy_vol == 280_504_501.21
    assert bar.sell_vol == 247_025_969.49
    assert bar.cvd == 10_975_605.00


def test_basis_bar_fields() -> None:
    bar = BasisBar(
        timestamp=datetime(2026, 1, 1),
        open_basis=0.0512,
        close_basis=0.0495,
    )
    assert bar.open_basis == 0.0512
    assert bar.close_basis == 0.0495


# ── Mock HTTP server for client tests ────────────────────────────────

MOCK_TOP_LS_RESPONSE = {
    "code": "0",
    "data": [
        {
            "time": 1704067200000,  # 2024-01-01 00:00 UTC
            "top_position_long_percent": 55.2,
            "top_position_short_percent": 44.8,
            "top_position_long_short_ratio": 1.232,
        },
        {
            "time": 1704081600000,  # 2024-01-01 04:00 UTC
            "top_position_long_percent": 58.1,
            "top_position_short_percent": 41.9,
            "top_position_long_short_ratio": 1.387,
        },
    ],
}

MOCK_CVD_RESPONSE = {
    "code": "0",
    "data": [
        {
            "time": 1704067200000,
            "agg_taker_buy_vol": 280504501.21,
            "agg_taker_sell_vol": 247025969.49,
            "cum_vol_delta": 10975605.00,
        },
        {
            "time": 1704081600000,
            "agg_taker_buy_vol": 300000000.00,
            "agg_taker_sell_vol": 310000000.00,
            "cum_vol_delta": -5000000.00,
        },
    ],
}

MOCK_BASIS_RESPONSE = {
    "code": "0",
    "data": [
        {
            "time": 1704067200000,
            "open_basis": 0.0512,
            "close_basis": 0.0495,
            "open_change": 34.29,
            "close_change": 33.08,
        },
        {
            "time": 1704081600000,
            "open_basis": 0.0495,
            "close_basis": 0.0530,
            "open_change": 33.08,
            "close_change": 35.42,
        },
    ],
}


class _MockHandler(BaseHTTPRequestHandler):
    """Serve mock Coinglass API responses."""

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        responses = {
            "/api/futures/top-long-short-position-ratio/history": MOCK_TOP_LS_RESPONSE,
            "/api/futures/aggregated-cvd/history": MOCK_CVD_RESPONSE,
            "/api/futures/basis/history": MOCK_BASIS_RESPONSE,
        }
        body = responses.get(path, {"code": "0", "data": []})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args):
        pass  # suppress log output


@pytest.fixture(scope="module")
def mock_server():
    server = HTTPServer(("127.0.0.1", 0), _MockHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture
def client(mock_server):
    c = CoinglassClient(api_key="test-key", base_url=mock_server)
    c.MIN_REQUEST_INTERVAL = 0  # no rate limiting in tests
    return c


# ── Client fetch tests ───────────────────────────────────────────────


def test_fetch_top_ls_ratio_history(client: CoinglassClient) -> None:
    bars = client.fetch_top_ls_ratio_history(
        exchange="Binance", symbol="BTCUSDT", interval="4h",
    )
    assert len(bars) == 2
    assert bars[0].long_percent == 55.2
    assert bars[0].short_percent == 44.8
    assert bars[0].ratio == 1.232
    assert bars[0].timestamp == datetime(2024, 1, 1, 0, 0)
    assert bars[1].timestamp == datetime(2024, 1, 1, 4, 0)


def test_fetch_cvd_history(client: CoinglassClient) -> None:
    bars = client.fetch_cvd_history(
        symbol="BTC", exchange_list="Binance", interval="4h",
    )
    assert len(bars) == 2
    assert bars[0].buy_vol == 280504501.21
    assert bars[0].sell_vol == 247025969.49
    assert bars[0].cvd == 10975605.00
    assert bars[1].cvd == -5000000.00


def test_fetch_basis_history(client: CoinglassClient) -> None:
    bars = client.fetch_basis_history(
        exchange="Binance", symbol="BTCUSDT", interval="4h",
    )
    assert len(bars) == 2
    assert bars[0].open_basis == 0.0512
    assert bars[0].close_basis == 0.0495
    assert bars[1].close_basis == 0.0530
