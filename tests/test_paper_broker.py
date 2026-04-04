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


def test_leverage_only_deducts_margin_not_full_notional() -> None:
    """With 10x leverage, opening a $10,000 notional position should only reserve $1,000 margin."""
    broker = PaperBroker(initial_cash=10_000.0, fee_rate=0.0, slippage_rate=0.0, leverage=10)
    timestamp = datetime(2025, 1, 1)

    fill = broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="buy", quantity=1.0, timestamp=timestamp),
        market_price=10_000.0,
    )
    assert fill is not None
    # Margin = 10,000 / 10 = 1,000.  Cash left = 10,000 - 1,000 = 9,000
    assert broker.get_cash() == 9_000.0
    pos = broker.get_position("BTCUSDT")
    assert pos.reserved_margin == 1_000.0


def test_leverage_pnl_on_full_notional() -> None:
    """PnL should be computed on full notional, not just margin."""
    broker = PaperBroker(initial_cash=10_000.0, fee_rate=0.0, slippage_rate=0.0, leverage=10)
    timestamp = datetime(2025, 1, 1)

    broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="buy", quantity=1.0, timestamp=timestamp),
        market_price=10_000.0,
    )
    # Price goes up 5%: PnL = 1.0 * 500 = $500 on full notional
    broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="sell", quantity=1.0, timestamp=timestamp),
        market_price=10_500.0,
    )
    # Cash = 9,000 (remaining) + 1,000 (margin back) + 500 (pnl) = 10,500
    assert broker.get_cash() == 10_500.0


def test_leverage_short_pnl() -> None:
    """Short with leverage: margin reserved, PnL on full notional."""
    broker = PaperBroker(initial_cash=10_000.0, fee_rate=0.0, slippage_rate=0.0, leverage=5)
    timestamp = datetime(2025, 1, 1)

    broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="short", quantity=1.0, timestamp=timestamp),
        market_price=10_000.0,
    )
    # Margin = 10,000 / 5 = 2,000.  Cash = 10,000 - 2,000 = 8,000
    assert broker.get_cash() == 8_000.0

    # Price drops 10%: PnL = 1.0 * 1,000 = $1,000 profit
    broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="cover", quantity=1.0, timestamp=timestamp),
        market_price=9_000.0,
    )
    # Cash = 8,000 + 2,000 (margin) + 1,000 (pnl) = 11,000
    assert broker.get_cash() == 11_000.0


def test_leverage_mark_to_market() -> None:
    """Mark-to-market equity should reflect unrealized PnL on full notional."""
    broker = PaperBroker(initial_cash=10_000.0, fee_rate=0.0, slippage_rate=0.0, leverage=10)
    timestamp = datetime(2025, 1, 1)

    broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="buy", quantity=1.0, timestamp=timestamp),
        market_price=10_000.0,
    )
    # Cash = 9,000, margin = 1,000, price up 10% → unrealized = +1,000
    equity = broker.mark_to_market("BTCUSDT", 11_000.0)
    assert equity == 11_000.0  # 9,000 + 1,000 (margin) + 1,000 (unrealized)


def test_liquidation_wipes_position() -> None:
    """When unrealized loss >= margin, position should be liquidated."""
    broker = PaperBroker(initial_cash=10_000.0, fee_rate=0.0, slippage_rate=0.0, leverage=10)
    timestamp = datetime(2025, 1, 1)

    broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="buy", quantity=1.0, timestamp=timestamp),
        market_price=10_000.0,
    )
    # Margin = 1,000. Price drops 10% → loss = 1,000 = margin → liquidated
    liquidated = broker.check_liquidation("BTCUSDT", 9_000.0, timestamp)
    assert liquidated is True
    assert broker.get_position("BTCUSDT").side == "flat"
    # Margin is lost entirely
    assert broker.get_cash() == 9_000.0  # started with 10k, lost 1k margin


def test_no_liquidation_when_solvent() -> None:
    """Position should not be liquidated when loss < margin."""
    broker = PaperBroker(initial_cash=10_000.0, fee_rate=0.0, slippage_rate=0.0, leverage=10)
    timestamp = datetime(2025, 1, 1)

    broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="buy", quantity=1.0, timestamp=timestamp),
        market_price=10_000.0,
    )
    # Margin = 1,000. Price drops 5% → loss = 500 < margin → safe
    liquidated = broker.check_liquidation("BTCUSDT", 9_500.0, timestamp)
    assert liquidated is False
    assert broker.get_position("BTCUSDT").side == "long"


def test_leverage_default_is_1x() -> None:
    """Default leverage should be 1x (spot-equivalent behavior)."""
    broker = PaperBroker(initial_cash=10_000.0, fee_rate=0.0, slippage_rate=0.0)
    timestamp = datetime(2025, 1, 1)

    fill = broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="buy", quantity=1.0, timestamp=timestamp),
        market_price=10_000.0,
    )
    assert fill is not None
    # 1x leverage: margin = full notional = 10,000
    assert broker.get_cash() == 0.0
    assert broker.get_position("BTCUSDT").reserved_margin == 10_000.0
