from adapters.binance_stub import BinanceStubAdapter


def test_binance_stub_returns_deterministic_bars() -> None:
    bars = BinanceStubAdapter().fetch_ohlcv(symbol="BTCUSDT", timeframe="1h", limit=40)

    assert len(bars) == 40
    assert bars[0].timestamp < bars[-1].timestamp
    assert all(bar.low <= bar.close <= bar.high for bar in bars)
