from datetime import datetime

from adapters.base import OrderRequest
from execution.paper_broker import PaperBroker


def test_paper_broker_applies_fee_and_round_trip_long() -> None:
    broker = PaperBroker(initial_cash=10_000.0, fee_rate=0.001, slippage_rate=0.0)
    timestamp = datetime(2025, 1, 1)

    buy_fill = broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="buy", quantity=1.0, timestamp=timestamp),
        market_price=100.0,
    )
    assert buy_fill is not None
    assert broker.get_position("BTCUSDT").side == "long"

    sell_fill = broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="sell", quantity=1.0, timestamp=timestamp),
        market_price=110.0,
    )
    assert sell_fill is not None
    assert broker.get_position("BTCUSDT").side == "flat"
    assert broker.get_cash() > 10_000.0
