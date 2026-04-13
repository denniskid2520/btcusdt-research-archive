"""Tests for coin-margined (inverse) contract support.

TDD: all tests written first, then implementation.

Inverse contract mechanics:
- Cash/margin is in BTC (not USDT)
- Long PnL (BTC) = qty * (exit - entry) / exit_price
- Short PnL (BTC) = qty * (entry - exit) / exit_price
- Margin (BTC) = qty / leverage  (not qty * price / leverage)
- Fee (BTC) = qty * price * fee_rate / price = qty * fee_rate
"""
from __future__ import annotations

from datetime import datetime

from adapters.base import OrderRequest
from execution.paper_broker import PaperBroker


TS = datetime(2025, 1, 1)


# ── Step 1: PaperBroker inverse mode — margin & PnL ───────────────────


def test_inverse_buy_deducts_btc_margin() -> None:
    """Inverse: margin = quantity / leverage (BTC), not quantity * price / leverage."""
    broker = PaperBroker(
        initial_cash=1.0, fee_rate=0.0, slippage_rate=0.0,
        leverage=3, contract_type="inverse",
    )
    # Buy 0.15 BTC equivalent at $60,000 → margin = 0.15 / 3 = 0.05 BTC
    fill = broker.submit_order(
        OrderRequest(symbol="BTCUSD", side="buy", quantity=0.15, timestamp=TS),
        market_price=60_000.0,
    )
    assert fill is not None
    assert abs(broker.get_cash() - (1.0 - 0.05)) < 1e-9  # 0.95 BTC left
    pos = broker.get_position("BTCUSD")
    assert abs(pos.reserved_margin - 0.05) < 1e-9


def test_inverse_long_profit_in_btc() -> None:
    """Inverse long: price up 10% → PnL = qty * (exit - entry) / exit."""
    broker = PaperBroker(
        initial_cash=1.0, fee_rate=0.0, slippage_rate=0.0,
        leverage=3, contract_type="inverse",
    )
    # Buy 0.3 BTC at $50,000
    broker.submit_order(
        OrderRequest(symbol="BTCUSD", side="buy", quantity=0.3, timestamp=TS),
        market_price=50_000.0,
    )
    # margin = 0.3 / 3 = 0.1 BTC, cash = 0.9
    # Sell at $55,000: PnL = 0.3 * (55000 - 50000) / 55000 = 0.3 * 5000/55000 = 0.02727 BTC
    broker.submit_order(
        OrderRequest(symbol="BTCUSD", side="sell", quantity=0.3, timestamp=TS),
        market_price=55_000.0,
    )
    expected_pnl = 0.3 * (55000 - 50000) / 55000  # 0.02727...
    expected_cash = 1.0 + expected_pnl  # margin returned + pnl
    assert abs(broker.get_cash() - expected_cash) < 1e-6


def test_inverse_long_loss_in_btc() -> None:
    """Inverse long: price down → loss in BTC (larger loss due to 1/price effect)."""
    broker = PaperBroker(
        initial_cash=1.0, fee_rate=0.0, slippage_rate=0.0,
        leverage=3, contract_type="inverse",
    )
    broker.submit_order(
        OrderRequest(symbol="BTCUSD", side="buy", quantity=0.3, timestamp=TS),
        market_price=60_000.0,
    )
    broker.submit_order(
        OrderRequest(symbol="BTCUSD", side="sell", quantity=0.3, timestamp=TS),
        market_price=54_000.0,
    )
    # PnL = 0.3 * (54000 - 60000) / 54000 = 0.3 * (-6000/54000) = -0.03333 BTC
    expected_pnl = 0.3 * (54000 - 60000) / 54000
    assert expected_pnl < 0
    assert abs(broker.get_cash() - (1.0 + expected_pnl)) < 1e-6


def test_inverse_short_profit_in_btc() -> None:
    """Inverse short: price down → profit in BTC."""
    broker = PaperBroker(
        initial_cash=1.0, fee_rate=0.0, slippage_rate=0.0,
        leverage=3, contract_type="inverse",
    )
    broker.submit_order(
        OrderRequest(symbol="BTCUSD", side="short", quantity=0.3, timestamp=TS),
        market_price=60_000.0,
    )
    broker.submit_order(
        OrderRequest(symbol="BTCUSD", side="cover", quantity=0.3, timestamp=TS),
        market_price=54_000.0,
    )
    # PnL = 0.3 * (60000 - 54000) / 54000 = 0.3 * 6000/54000 = 0.03333 BTC
    expected_pnl = 0.3 * (60000 - 54000) / 54000
    assert expected_pnl > 0
    assert abs(broker.get_cash() - (1.0 + expected_pnl)) < 1e-6


def test_inverse_short_loss_in_btc() -> None:
    """Inverse short: price up → loss in BTC."""
    broker = PaperBroker(
        initial_cash=1.0, fee_rate=0.0, slippage_rate=0.0,
        leverage=3, contract_type="inverse",
    )
    broker.submit_order(
        OrderRequest(symbol="BTCUSD", side="short", quantity=0.3, timestamp=TS),
        market_price=50_000.0,
    )
    broker.submit_order(
        OrderRequest(symbol="BTCUSD", side="cover", quantity=0.3, timestamp=TS),
        market_price=55_000.0,
    )
    # PnL = 0.3 * (50000 - 55000) / 55000 = 0.3 * (-5000/55000) = -0.02727 BTC
    expected_pnl = 0.3 * (50000 - 55000) / 55000
    assert expected_pnl < 0
    assert abs(broker.get_cash() - (1.0 + expected_pnl)) < 1e-6


def test_inverse_fee_in_btc() -> None:
    """Inverse fees: fee = quantity * fee_rate (BTC), not quantity * price * fee_rate."""
    broker = PaperBroker(
        initial_cash=1.0, fee_rate=0.001, slippage_rate=0.0,
        leverage=3, contract_type="inverse",
    )
    fill = broker.submit_order(
        OrderRequest(symbol="BTCUSD", side="buy", quantity=0.3, timestamp=TS),
        market_price=60_000.0,
    )
    assert fill is not None
    # Fee = 0.3 * 0.001 = 0.0003 BTC (not 0.3 * 60000 * 0.001 = 18 USDT)
    assert abs(fill.fee - 0.0003) < 1e-9
    # Cash = 1.0 - margin(0.1) - fee(0.0003) = 0.8997
    assert abs(broker.get_cash() - (1.0 - 0.1 - 0.0003)) < 1e-9


# ── Step 2: Mark-to-market & Liquidation ─────────────────────────────


def test_inverse_mark_to_market() -> None:
    """MTM equity should use inverse PnL formula."""
    broker = PaperBroker(
        initial_cash=1.0, fee_rate=0.0, slippage_rate=0.0,
        leverage=3, contract_type="inverse",
    )
    broker.submit_order(
        OrderRequest(symbol="BTCUSD", side="buy", quantity=0.3, timestamp=TS),
        market_price=60_000.0,
    )
    # Cash=0.9, margin=0.1, price at 66000:
    # unrealized = 0.3 * (66000 - 60000) / 66000 = 0.02727 BTC
    equity = broker.mark_to_market("BTCUSD", 66_000.0)
    unrealized = 0.3 * (66000 - 60000) / 66000
    assert abs(equity - (0.9 + 0.1 + unrealized)) < 1e-6


def test_inverse_liquidation() -> None:
    """Inverse: liquidation when unrealized loss >= margin (in BTC)."""
    broker = PaperBroker(
        initial_cash=1.0, fee_rate=0.0, slippage_rate=0.0,
        leverage=10, contract_type="inverse",
    )
    # Buy 1.0 BTC at $50,000, margin = 1.0/10 = 0.1 BTC
    broker.submit_order(
        OrderRequest(symbol="BTCUSD", side="buy", quantity=1.0, timestamp=TS),
        market_price=50_000.0,
    )
    # Price drops: unrealized = 1.0 * (new_price - 50000) / new_price
    # Need unrealized <= -0.1 BTC
    # 1.0 * (P - 50000) / P = -0.1 → P - 50000 = -0.1P → 1.1P = 50000 → P = 45454.5
    liquidated = broker.check_liquidation("BTCUSD", 45_000.0, TS)
    assert liquidated is True
    assert broker.get_position("BTCUSD").side == "flat"


def test_inverse_no_liquidation_when_solvent() -> None:
    """Position survives when loss < margin."""
    broker = PaperBroker(
        initial_cash=1.0, fee_rate=0.0, slippage_rate=0.0,
        leverage=10, contract_type="inverse",
    )
    broker.submit_order(
        OrderRequest(symbol="BTCUSD", side="buy", quantity=1.0, timestamp=TS),
        market_price=50_000.0,
    )
    # At 48000: unrealized = 1.0 * (48000-50000)/48000 = -0.04167 BTC, margin=0.1 → safe
    liquidated = broker.check_liquidation("BTCUSD", 48_000.0, TS)
    assert liquidated is False
    assert broker.get_position("BTCUSD").side == "long"


# ── Step 3: Scale-in on inverse ─────────────────────────────────────


def test_inverse_scale_in_long() -> None:
    """Scale into inverse long: margin adds in BTC, weighted avg price."""
    broker = PaperBroker(
        initial_cash=1.0, fee_rate=0.0, slippage_rate=0.0,
        leverage=3, contract_type="inverse",
    )
    # Entry: 0.15 BTC at $60k → margin = 0.05 BTC
    broker.submit_order(
        OrderRequest(symbol="BTCUSD", side="buy", quantity=0.15, timestamp=TS),
        market_price=60_000.0,
    )
    # Scale-in: 0.10 BTC at $62k → margin = 0.10/3 = 0.03333 BTC
    broker.submit_order(
        OrderRequest(symbol="BTCUSD", side="buy", quantity=0.10, timestamp=TS,
                     metadata={"scale_in": True}),
        market_price=62_000.0,
    )
    pos = broker.get_position("BTCUSD")
    assert abs(pos.quantity - 0.25) < 1e-9
    # Weighted avg: (0.15 * 60000 + 0.10 * 62000) / 0.25 = 60800
    assert abs(pos.average_price - 60_800.0) < 1.0
    # Total margin = 0.05 + 0.03333 = 0.08333 BTC
    assert abs(pos.reserved_margin - (0.15/3 + 0.10/3)) < 1e-6


# ── Step 4: Existing linear tests still work ────────────────────────


def test_linear_default_unchanged() -> None:
    """Default contract_type='linear' behaves exactly as before."""
    broker = PaperBroker(
        initial_cash=10_000.0, fee_rate=0.0, slippage_rate=0.0, leverage=10,
    )
    fill = broker.submit_order(
        OrderRequest(symbol="BTCUSDT", side="buy", quantity=1.0, timestamp=TS),
        market_price=10_000.0,
    )
    assert fill is not None
    # Linear: margin = 1.0 * 10000 / 10 = 1000 USDT
    assert broker.get_cash() == 9_000.0
    assert broker.get_position("BTCUSDT").reserved_margin == 1_000.0


# ── Step 5: Position sizing with BTC cash ────────────────────────────


def test_inverse_position_sizing() -> None:
    """calculate_order_quantity with inverse: cash_btc * price gives USD equiv."""
    from risk.limits import RiskLimits, calculate_order_quantity

    limits = RiskLimits(
        max_position_pct=0.05,
        risk_per_trade_pct=0.02,
        leverage=3,
    )
    # Inverse: cash is 1.0 BTC, price = $60,000 → USD equiv = $60,000
    # Pass cash_btc * price to get correct USD-based sizing
    cash_usd_equiv = 1.0 * 60_000
    quantity = calculate_order_quantity(
        cash=cash_usd_equiv,
        market_price=60_000.0,
        limits=limits,
    )
    # Same as if we had $60k USDT — quantity should be in BTC
    assert quantity > 0
    # Margin check: quantity * price / leverage should not exceed cash * max_pos * leverage
    margin_btc = quantity / 3  # inverse margin
    assert margin_btc <= 1.0 * 0.05 * 3  # within budget


# ── Step 6: Backtest trade record for inverse ────────────────────────


def test_inverse_backtest_trade_pnl_in_btc() -> None:
    """TradeRecord.pnl should be in BTC (fractional) for inverse contracts."""
    from research.backtest import _build_trade_record

    entry = {
        "symbol": "BTCUSD",
        "entry_rule": "ascending_channel_support_bounce",
        "side": "buy",
        "entry_time": TS,
        "entry_price": 50_000.0,
        "entry_fee": 0.0003,  # BTC fee
        "entry_index": 0,
    }
    from adapters.base import FillReport
    exit_fill = FillReport(
        order_id="test-1",
        symbol="BTCUSD",
        side="sell",
        quantity=0.3,
        fill_price=55_000.0,
        fee=0.0003,
        timestamp=TS,
    )
    trade = _build_trade_record(entry, exit_fill, "target_hit", contract_type="inverse")
    # PnL (BTC) = 0.3 * (55000-50000)/55000 - 0.0003 - 0.0003 = 0.02727 - 0.0006
    expected = 0.3 * (55000 - 50000) / 55000 - 0.0006
    assert abs(trade.pnl - expected) < 1e-6
    # return_pct still tracks price-based % (same as linear)
    assert abs(trade.return_pct - 10.0) < 0.1
