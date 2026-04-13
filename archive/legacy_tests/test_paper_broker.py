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


# ── Scale-in (加倉) Tests ──────────────────────────────────────────────


def test_scale_in_adds_to_existing_long_position() -> None:
    """Scale-in: buying more when already long should increase quantity and average price."""
    broker = PaperBroker(initial_cash=10_000.0, fee_rate=0.0, slippage_rate=0.0, leverage=3)
    ts = datetime(2025, 1, 1)

    # Initial entry: buy 0.1 BTC at $60k → margin = $2,000
    broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.1, timestamp=ts),
        market_price=60_000.0,
    )
    pos = broker.get_position("BTCUSDT")
    assert pos.quantity == 0.1
    assert pos.average_price == 60_000.0
    assert broker.get_cash() == 8_000.0  # 10k - 2k margin

    # Scale-in: buy 0.05 more at $62k → margin += $1,033.33
    fill = broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.05, timestamp=ts,
                     metadata={"scale_in": True}),
        market_price=62_000.0,
    )
    assert fill is not None
    pos = broker.get_position("BTCUSDT")
    assert abs(pos.quantity - 0.15) < 1e-9  # 0.1 + 0.05
    # Weighted avg: (0.1 * 60000 + 0.05 * 62000) / 0.15 = 60666.67
    assert abs(pos.average_price - 60_666.67) < 1.0
    # Margin: 2000 + (0.05 * 62000 / 3) = 2000 + 1033.33 = 3033.33
    assert abs(pos.reserved_margin - 3_033.33) < 1.0


def test_scale_in_adds_to_existing_short_position() -> None:
    """Scale-in: shorting more when already short should increase quantity."""
    broker = PaperBroker(initial_cash=10_000.0, fee_rate=0.0, slippage_rate=0.0, leverage=5)
    ts = datetime(2025, 1, 1)

    # Initial short: 0.1 BTC at $60k → margin = $1,200
    broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="short", quantity=0.1, timestamp=ts),
        market_price=60_000.0,
    )
    assert broker.get_cash() == 8_800.0

    # Scale-in short: 0.05 more at $58k → margin += $580
    fill = broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="short", quantity=0.05, timestamp=ts,
                     metadata={"scale_in": True}),
        market_price=58_000.0,
    )
    assert fill is not None
    pos = broker.get_position("BTCUSDT")
    assert abs(pos.quantity - 0.15) < 1e-9
    # Weighted avg: (0.1 * 60000 + 0.05 * 58000) / 0.15 = 59333.33
    assert abs(pos.average_price - 59_333.33) < 1.0


def test_scale_in_full_exit_returns_correct_pnl() -> None:
    """After scale-in, closing the full position should compute PnL on weighted avg price."""
    broker = PaperBroker(initial_cash=10_000.0, fee_rate=0.0, slippage_rate=0.0, leverage=3)
    ts = datetime(2025, 1, 1)

    # Entry at $60k, scale-in at $62k
    broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.1, timestamp=ts),
        market_price=60_000.0,
    )
    broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.05, timestamp=ts,
                     metadata={"scale_in": True}),
        market_price=62_000.0,
    )
    # Close at $65k: PnL = 0.15 * (65000 - 60666.67) = $650
    broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="sell", quantity=0.15, timestamp=ts),
        market_price=65_000.0,
    )
    assert broker.get_position("BTCUSDT").side == "flat"
    # Cash = 10000 - 2000 (margin1) - 1033.33 (margin2) + 3033.33 (margin back) + 650 (pnl) = 10650
    assert abs(broker.get_cash() - 10_650.0) < 1.0
