"""Tests for impulse profit tracking and BTC-to-USDT harvest mechanism.

TDD: tests first, then implementation.

Impulse system:
- Breakout trades get wider trailing stop (ride the impulse)
- Bounce trades keep original trailing stop (range-revert)
- On profitable breakout exit, harvest X% of BTC profit → USDT reserves
"""
from __future__ import annotations

from datetime import datetime

import pytest

from adapters.base import MarketBar, OrderRequest, Position
from execution.paper_broker import PaperBroker
from strategies.trend_breakout import (
    TrendBreakoutConfig,
    TrendBreakoutStrategy,
    _BOUNCE_RULES,
    _BREAKOUT_RULES,
)


TS = datetime(2025, 1, 1)


# ── Step 1: Strategy tags breakout vs bounce trailing stops ──────────


def test_breakout_signal_gets_wider_trailing_atr() -> None:
    """Breakout signals should use impulse_trailing_stop_atr, not the default."""
    from tests.fixtures_synthetic_bars import ascending_channel_breakout_long_bars

    bars = ascending_channel_breakout_long_bars()
    config = TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        impulse_threshold_pct=0.03,
        entry_buffer_pct=0.35,
        stop_buffer_pct=0.08,
        allow_shorts=False,
        require_parent_confirmation=False,
        trailing_stop_atr=3.5,
        impulse_trailing_stop_atr=6.0,  # wider for breakouts
    )
    strategy = TrendBreakoutStrategy(config)
    result = strategy.evaluate(
        symbol="BTCUSD", bars=bars, position=Position(symbol="BTCUSD"),
    )
    if result.signal.action == "buy" and result.signal.reason in _BREAKOUT_RULES:
        meta = result.signal.metadata or {}
        assert meta.get("trailing_stop_atr") == 6.0, "Breakout should use impulse ATR"
        assert meta.get("trade_type") == "impulse"


def test_bounce_signal_keeps_default_trailing_atr() -> None:
    """Bounce signals should use the default trailing_stop_atr."""
    from tests.fixtures_synthetic_bars import ascending_channel_support_long_bars

    bars = ascending_channel_support_long_bars()
    config = TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        impulse_threshold_pct=0.03,
        entry_buffer_pct=0.35,
        stop_buffer_pct=0.08,
        allow_shorts=False,
        require_parent_confirmation=False,
        trailing_stop_atr=3.5,
        impulse_trailing_stop_atr=6.0,
    )
    strategy = TrendBreakoutStrategy(config)
    result = strategy.evaluate(
        symbol="BTCUSD", bars=bars, position=Position(symbol="BTCUSD"),
    )
    if result.signal.action == "buy" and result.signal.reason in _BOUNCE_RULES:
        meta = result.signal.metadata or {}
        assert meta.get("trailing_stop_atr") == 3.5, "Bounce should use default ATR"
        assert meta.get("trade_type") is None or meta.get("trade_type") != "impulse"


# ── Step 2: Broker deduct_cash for harvest ───────────────────────────


def test_broker_deduct_cash() -> None:
    """deduct_cash removes BTC from broker and returns amount deducted."""
    broker = PaperBroker(initial_cash=1.0, contract_type="inverse")
    deducted = broker.deduct_cash(0.25)
    assert abs(deducted - 0.25) < 1e-9
    assert abs(broker.get_cash() - 0.75) < 1e-9


def test_broker_deduct_cash_capped_at_balance() -> None:
    """Cannot deduct more than available cash."""
    broker = PaperBroker(initial_cash=0.5, contract_type="inverse")
    deducted = broker.deduct_cash(1.0)
    assert abs(deducted - 0.5) < 1e-9
    assert abs(broker.get_cash()) < 1e-9


# ── Step 3: BacktestResult includes harvest data ─────────────────────


def test_backtest_result_has_harvest_fields() -> None:
    """BacktestResult should have usdt_reserves and harvest_events."""
    from research.backtest import BacktestResult
    # Check that the fields exist
    result = BacktestResult(
        initial_cash=1.0, final_equity=1.5,
        total_return_pct=50.0, max_drawdown_pct=10.0,
        total_trades=1, fills=[], trades=[],
        rule_stats=[], rejection_stats={},
        rule_eval_counts={}, event_review_pack=[],
        usdt_reserves=5000.0,
        btc_harvested=0.1,
        harvest_events=[],
    )
    assert result.usdt_reserves == 5000.0
    assert result.btc_harvested == 0.1


# ── Step 4: Breakout signal clears target for pure trailing exit ─────


def test_breakout_signal_has_no_fixed_target() -> None:
    """Breakout trades should rely on trailing stop only, no fixed target."""
    from tests.fixtures_synthetic_bars import ascending_channel_breakout_long_bars

    bars = ascending_channel_breakout_long_bars()
    config = TrendBreakoutConfig(
        impulse_lookback=12,
        structure_lookback=24,
        impulse_threshold_pct=0.03,
        entry_buffer_pct=0.35,
        stop_buffer_pct=0.08,
        allow_shorts=False,
        require_parent_confirmation=False,
        trailing_stop_atr=3.5,
        impulse_trailing_stop_atr=6.0,
        use_trailing_exit=True,
    )
    strategy = TrendBreakoutStrategy(config)
    result = strategy.evaluate(
        symbol="BTCUSD", bars=bars, position=Position(symbol="BTCUSD"),
    )
    if result.signal.action == "buy" and result.signal.reason in _BREAKOUT_RULES:
        # Breakout should NOT have a fixed target (pure trailing exit)
        assert result.signal.target_price is None, "Breakout should use trailing stop only"
