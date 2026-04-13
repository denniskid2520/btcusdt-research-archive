from adapters.base import OrderRequest, Position
from datetime import datetime
from risk.limits import RiskLimits, calculate_order_quantity, allow_order


def test_position_size_with_leverage() -> None:
    """With leverage, can hold larger notional than cash allows at 1x."""
    # $10k cash, 10x leverage, risk 2% per trade
    limits = RiskLimits(max_position_pct=0.90, risk_per_trade_pct=0.02, leverage=10)
    qty = calculate_order_quantity(cash=10_000.0, market_price=60_000.0, limits=limits)
    notional = qty * 60_000.0
    margin = notional / 10
    # Margin should not exceed 90% of cash
    assert margin <= 10_000.0 * 0.90


def test_allow_order_checks_margin_not_notional() -> None:
    """allow_order should check margin (notional/leverage) against cash, not full notional."""
    limits = RiskLimits(max_position_pct=0.90, leverage=10)
    ts = datetime(2025, 1, 1)
    # $10k cash, want to buy 1 BTC at $60k → notional=$60k, margin=$6k → OK (< $9k cap)
    order = OrderRequest(symbol="BTCUSDT", side="buy", quantity=1.0, timestamp=ts)
    allowed = allow_order(
        cash=10_000.0, order=order, market_price=60_000.0,
        open_positions=0, limits=limits, existing_position=Position(symbol="BTCUSDT"),
    )
    assert allowed is True


def test_allow_order_rejects_when_margin_exceeds_cap() -> None:
    """Reject when margin > max_position_pct * cash."""
    limits = RiskLimits(max_position_pct=0.90, leverage=10)
    ts = datetime(2025, 1, 1)
    # $10k cash, want to buy 2 BTC at $60k → notional=$120k, margin=$12k → exceeds $9k cap
    order = OrderRequest(symbol="BTCUSDT", side="buy", quantity=2.0, timestamp=ts)
    allowed = allow_order(
        cash=10_000.0, order=order, market_price=60_000.0,
        open_positions=0, limits=limits, existing_position=Position(symbol="BTCUSDT"),
    )
    assert allowed is False
