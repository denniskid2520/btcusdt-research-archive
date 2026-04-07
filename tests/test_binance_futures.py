"""Tests for Binance Futures data adapter."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from adapters.binance_futures import BinanceFuturesAdapter


# Sample kline response from Binance fapi
_SAMPLE_KLINE = [
    1609459200000,   # open time (2021-01-01 00:00 UTC)
    "29000.00",      # open
    "29500.00",      # high
    "28800.00",      # low
    "29300.00",      # close
    "12345.678",     # volume
    1609473599999,   # close time
    "361111111.11",  # quote volume
    5000,            # trades
    "6000.123",      # taker buy volume
    "175555555.55",  # taker buy quote volume
    "0",             # ignore
]


def _make_klines(n: int, start_ms: int = 1609459200000, interval_ms: int = 14400000) -> list[list]:
    """Generate n sample klines starting from start_ms."""
    rows = []
    for i in range(n):
        open_ms = start_ms + i * interval_ms
        rows.append([
            open_ms,
            str(29000 + i * 100),
            str(29500 + i * 100),
            str(28800 + i * 100),
            str(29300 + i * 100),
            str(1000 + i),
            open_ms + interval_ms - 1,
            "0", 0, "0", "0", "0",
        ])
    return rows


class TestBinanceFuturesAdapter:

    def test_base_url_is_futures(self):
        adapter = BinanceFuturesAdapter()
        assert "fapi" in adapter.base_url

    def test_parse_kline_to_marketbar(self):
        adapter = BinanceFuturesAdapter()
        bar = adapter._parse(_SAMPLE_KLINE)
        assert bar.open == 29000.0
        assert bar.high == 29500.0
        assert bar.low == 28800.0
        assert bar.close == 29300.0
        assert bar.volume == 12345.678
        assert bar.timestamp == datetime(2021, 1, 1, 0, 0, 0)

    @patch("adapters.binance_futures.urlopen")
    def test_fetch_ohlcv_calls_fapi_endpoint(self, mock_urlopen):
        klines = _make_klines(5)
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(klines).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        adapter = BinanceFuturesAdapter()
        bars = adapter.fetch_ohlcv("BTCUSDT", "4h", 5)

        assert len(bars) == 5
        call_url = mock_urlopen.call_args[0][0].full_url
        assert "/fapi/v1/klines" in call_url
        assert "BTCUSDT" in call_url

    @patch("adapters.binance_futures.urlopen")
    def test_fetch_ohlcv_returns_sorted_bars(self, mock_urlopen):
        klines = _make_klines(3)
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(klines).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        adapter = BinanceFuturesAdapter()
        bars = adapter.fetch_ohlcv("BTCUSDT", "4h", 3)

        assert bars[0].timestamp < bars[1].timestamp < bars[2].timestamp

    @patch("adapters.binance_futures.urlopen")
    def test_fetch_multi_timeframe(self, mock_urlopen):
        """fetch_multi returns dict of timeframe -> bars."""
        klines_4h = _make_klines(10, interval_ms=14400000)
        klines_1d = _make_klines(5, interval_ms=86400000)

        responses = [
            MagicMock(
                read=MagicMock(return_value=json.dumps(klines_4h).encode()),
                __enter__=lambda s: s,
                __exit__=MagicMock(return_value=False),
            ),
            MagicMock(
                read=MagicMock(return_value=json.dumps(klines_1d).encode()),
                __enter__=lambda s: s,
                __exit__=MagicMock(return_value=False),
            ),
        ]
        mock_urlopen.side_effect = responses

        adapter = BinanceFuturesAdapter()
        result = adapter.fetch_multi("BTCUSDT", {"4h": 10, "1d": 5})

        assert "4h" in result
        assert "1d" in result
        assert len(result["4h"]) == 10
        assert len(result["1d"]) == 5

    def test_unsupported_timeframe_raises(self):
        adapter = BinanceFuturesAdapter()
        with pytest.raises(ValueError, match="Unsupported"):
            adapter.fetch_ohlcv("BTCUSDT", "7h", 10)
