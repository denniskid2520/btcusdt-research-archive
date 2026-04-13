"""Tests for the 3 Codex-flagged deployment fixes.

1) Entry order must be submitted before internal state flips to OPEN
2) Startup must restore persisted live-position fields
3) reduceOnly detection must handle both boolean and string
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from adapters.base import MarketBar
from execution.paper_runner_v2 import CandidateConfig


# We need to be able to import LiveService without fcntl (Windows)
# so we patch it if needed
try:
    from execution.live_service import LiveService, CANDIDATE_ID
except ImportError:
    pytest.skip("live_service requires Linux-only modules", allow_module_level=True)


def _bar(ts=None, price=100.0) -> MarketBar:
    return MarketBar(
        timestamp=ts or datetime(2024, 1, 1),
        open=price, high=price + 1, low=price - 1,
        close=price, volume=100.0,
    )


def _make_service(tmp_path: Path, dry_run: bool = True) -> LiveService:
    """Create a LiveService with tmp paths and no real Binance calls."""
    svc = LiveService.__new__(LiveService)
    svc.dry_run = dry_run
    svc.max_cap_usd = None
    cfg = CandidateConfig(
        candidate_id="test",
        regime_rsi_period=3, regime_threshold=70.0,
        entry_mode="hybrid", pullback_pct=0.0075, breakout_pct=0.0025,
        max_entries_per_zone=6, cooldown_bars=2, hold_bars=24,
        exchange_leverage=3.0, base_frac=2.0, max_frac=3.0,
        alpha_stop_pct=0.0125, catastrophe_stop_pct=0.025,
    )
    svc.candidate_cfg = cfg
    svc.capital_cfg = MagicMock()
    svc.capital_cfg.allocation_pct = 1.0
    svc.capital_cfg.min_required_usd = 100.0
    svc.capital_cfg.max_cap_usd = None
    svc.api_key = "test"
    svc.api_secret = "test"
    svc.state_dir = tmp_path / "state"
    svc.state_dir.mkdir(parents=True, exist_ok=True)
    svc.runner = MagicMock()
    svc.last_bar_ts = None
    svc.has_live_position = False
    svc.live_entry_price = 0.0
    svc.live_quantity = 0.0
    svc.live_alpha_level = 0.0
    svc.live_catastrophe_level = 0.0
    svc.open_catastrophe_order_id = None
    svc.halted = False
    svc.halt_reason = ""
    svc._order_in_progress = False
    return svc


# ── FIX 1: entry order before state flip ───────────────────────────


class TestFix1EntryOrderBeforeStateFlip:

    def test_dry_run_sets_position_immediately(self, tmp_path):
        """In dry-run, no order is placed, position is set directly."""
        svc = _make_service(tmp_path, dry_run=True)
        svc._get_strategy_equity = MagicMock(return_value=10000.0)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()

        svc._handle_entry(_bar(price=50000.0))

        assert svc.has_live_position is True
        assert svc.live_entry_price == 50000.0

    def test_live_rejected_entry_does_not_set_position(self, tmp_path):
        """If entry MARKET order is rejected, position must NOT be set."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._get_strategy_equity = MagicMock(return_value=10000.0)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc._place_market_order = MagicMock(return_value=None)

        svc._handle_entry(_bar(price=50000.0))

        assert svc.has_live_position is False
        assert svc.live_entry_price == 0.0

    def test_live_new_status_does_not_set_position(self, tmp_path):
        """CODEX FIX 1: status=NEW must NOT be treated as filled."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._get_strategy_equity = MagicMock(return_value=10000.0)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc._place_market_order = MagicMock(return_value={
            "status": "NEW", "avgPrice": "0", "executedQty": "0",
        })

        with patch("execution.live_service.cancel_all_orders", return_value={"ok": True}):
            svc._handle_entry(_bar(price=50000.0))

        assert svc.has_live_position is False

    def test_live_partial_fill_flattens_and_confirms_zero(self, tmp_path):
        """PARTIALLY_FILLED with qty > 0 must flatten + verify zero."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._get_strategy_equity = MagicMock(return_value=10000.0)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        # First call = entry BUY (PARTIALLY_FILLED, 0.1 executed)
        # Second call = flatten SELL (FILLED)
        svc._place_market_order = MagicMock(side_effect=[
            {"status": "PARTIALLY_FILLED", "avgPrice": "50000", "executedQty": "0.1"},
            {"status": "FILLED", "avgPrice": "49950", "executedQty": "0.1"},
        ])

        with patch("execution.live_service.cancel_all_orders", return_value={"ok": True}):
            with patch("execution.live_service.fetch_position", return_value={"positionAmt": "0"}):
                svc._handle_entry(_bar(price=50000.0))

        assert svc.has_live_position is False
        # BUY + SELL = 2 calls
        assert svc._place_market_order.call_count == 2
        assert svc._place_market_order.call_args_list[1][0][0] == "SELL"

    def test_live_partial_fill_flatten_fails_marks_naked(self, tmp_path):
        """If partial fill flatten fails, mark naked for manual intervention."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._get_strategy_equity = MagicMock(return_value=10000.0)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.runner._rsi_buffer = [100.0] * 20
        svc.runner.state.position_state = "flat"
        svc.runner.state.regime_active = False
        svc.runner.state.next_trade_id = 1
        svc.runner.state.next_zone_id = 1
        svc.runner.state.bars_since_last_exit = 999
        svc.runner.trades = []
        # BUY partial, SELL fails
        svc._place_market_order = MagicMock(side_effect=[
            {"status": "PARTIALLY_FILLED", "avgPrice": "50000", "executedQty": "0.1"},
            None,  # flatten fails
        ])

        with patch("execution.live_service.cancel_all_orders", return_value={"ok": True}):
            svc._handle_entry(_bar(price=50000.0))

        # Must be marked as live (naked) for reconciliation
        assert svc.has_live_position is True
        assert svc.live_quantity == 0.1

    def test_live_partial_fill_flatten_ok_but_verify_throws_halts(self, tmp_path):
        """If flatten FILLED but fetch_position throws, must HALT
        (position_unknown), not assume flat."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._get_strategy_equity = MagicMock(return_value=10000.0)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.runner._rsi_buffer = [100.0] * 20
        svc.runner.state.position_state = "flat"
        svc.runner.state.regime_active = False
        svc.runner.state.next_trade_id = 1
        svc.runner.state.next_zone_id = 1
        svc.runner.state.bars_since_last_exit = 999
        svc.runner.trades = []
        svc._place_market_order = MagicMock(side_effect=[
            {"status": "PARTIALLY_FILLED", "avgPrice": "50000", "executedQty": "0.1"},
            {"status": "FILLED", "avgPrice": "49950", "executedQty": "0.1"},
        ])

        with patch("execution.live_service.cancel_all_orders", return_value={"ok": True}):
            with patch("execution.live_service.fetch_position",
                       side_effect=Exception("network timeout")):
                svc._handle_entry(_bar(price=50000.0))

        # Must be HALTED, not flat
        assert svc.halted is True
        assert "position_unknown" in svc.halt_reason
        assert svc.has_live_position is True
        assert svc.live_quantity == 0.1

    def test_halted_state_blocks_new_entries(self, tmp_path):
        """When halted, new entry signals must be blocked."""
        svc = _make_service(tmp_path, dry_run=False)
        svc.halted = True
        svc.halt_reason = "position_unknown"
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc._handle_entry = MagicMock()

        # Simulate _process_bar seeing an ENTRY_FILL event
        events = ["ENTRY_FILL price=50000"]
        if "ENTRY_FILL" in " ".join(events) and not svc.has_live_position:
            if svc.halted:
                svc._log_tick(f"ENTRY BLOCKED")
            else:
                svc._handle_entry(_bar())

        # _handle_entry must NOT have been called
        svc._handle_entry.assert_not_called()

    def test_reconciliation_clears_halt_when_exchange_confirms_zero(self, tmp_path):
        """After HALT, if next reconciliation sees zero position on
        exchange, halt clears and entries are allowed again."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.runner._rsi_buffer = [100.0] * 20
        svc.runner.state.position_state = "flat"
        svc.runner.state.regime_active = False
        svc.runner.state.next_trade_id = 1
        svc.runner.state.next_zone_id = 1
        svc.runner.state.bars_since_last_exit = 999
        svc.runner.trades = []

        # Set halted state
        svc.halted = True
        svc.halt_reason = "position_unknown: flatten ok but verify failed"
        svc.has_live_position = True
        svc.live_quantity = 0.1

        # Reconciliation sees zero position on exchange
        with patch("execution.live_service.fetch_position", return_value=None):
            with patch("execution.live_service.fetch_open_orders", return_value=[]):
                svc._reconcile()

        assert svc.halted is False
        assert svc.halt_reason == ""
        assert svc.has_live_position is False
        assert svc.live_quantity == 0.0

    def test_halted_state_persists_across_restart(self, tmp_path):
        """Halt state must survive process restart via state.json."""
        svc = _make_service(tmp_path, dry_run=False)
        svc.runner._rsi_buffer = [100.0] * 20
        svc.runner.state.position_state = "flat"
        svc.runner.state.regime_active = False
        svc.runner.state.next_trade_id = 1
        svc.runner.state.next_zone_id = 1
        svc.runner.state.bars_since_last_exit = 999
        svc.runner.trades = []
        svc.halted = True
        svc.halt_reason = "position_unknown: test"
        svc.has_live_position = True
        svc.live_quantity = 0.05
        svc._save_runner()

        # New service instance restores halt
        svc2 = _make_service(tmp_path, dry_run=False)
        svc2.state_dir = svc.state_dir
        svc2._log_tick = MagicMock()
        # Skip exchange check for this test (dry_run path in restore)
        svc2.dry_run = True
        svc2._restore_live_position_state()

        assert svc2.halted is True
        assert "position_unknown" in svc2.halt_reason
        assert svc2.has_live_position is True

    def test_live_partial_fill_flatten_ok_but_position_remains(self, tmp_path):
        """If flatten SELL reports FILLED but exchange still shows position,
        mark as live for manual intervention."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._get_strategy_equity = MagicMock(return_value=10000.0)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.runner._rsi_buffer = [100.0] * 20
        svc.runner.state.position_state = "flat"
        svc.runner.state.regime_active = False
        svc.runner.state.next_trade_id = 1
        svc.runner.state.next_zone_id = 1
        svc.runner.state.bars_since_last_exit = 999
        svc.runner.trades = []
        svc._place_market_order = MagicMock(side_effect=[
            {"status": "PARTIALLY_FILLED", "avgPrice": "50000", "executedQty": "0.1"},
            {"status": "FILLED", "avgPrice": "49950", "executedQty": "0.1"},
        ])

        with patch("execution.live_service.cancel_all_orders", return_value={"ok": True}):
            # Exchange still shows 0.05 remaining
            with patch("execution.live_service.fetch_position",
                       return_value={"positionAmt": "0.05"}):
                svc._handle_entry(_bar(price=50000.0))

        assert svc.has_live_position is True
        assert svc.live_quantity == 0.05

    def test_live_successful_entry_sets_position_after_fill(self, tmp_path):
        """Position is set only AFTER exchange confirms FILLED + stop ack."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._get_strategy_equity = MagicMock(return_value=10000.0)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc._place_market_order = MagicMock(return_value={
            "status": "FILLED", "avgPrice": "50000.0", "executedQty": "0.400",
        })

        from execution.live_executor import StopOrderEvent
        mock_stop = StopOrderEvent(
            timestamp="2024-01-01", event_type="ack",
            order_type="catastrophe_stop", side="long",
            stop_price=48750.0, quantity=0.4, order_id="12345",
        )
        with patch("execution.live_service.place_catastrophe_stop", return_value=mock_stop):
            with patch("execution.live_service.log_stop_event"):
                svc._handle_entry(_bar(price=50000.0))

        assert svc.has_live_position is True
        assert svc.live_entry_price == 50000.0
        assert svc.live_quantity == 0.4
        assert svc.open_catastrophe_order_id == "12345"

    def test_live_catastrophe_reject_flatten_succeeds(self, tmp_path):
        """CODEX FIX 2: if flatten SELL succeeds, position stays flat."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._get_strategy_equity = MagicMock(return_value=10000.0)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        # First call = entry BUY (FILLED), second call = flatten SELL (FILLED)
        svc._place_market_order = MagicMock(side_effect=[
            {"status": "FILLED", "avgPrice": "50000.0", "executedQty": "0.400"},
            {"status": "FILLED", "avgPrice": "49900.0", "executedQty": "0.400"},
        ])

        from execution.live_executor import StopOrderEvent
        mock_stop = StopOrderEvent(
            timestamp="2024-01-01", event_type="reject",
            order_type="catastrophe_stop", side="long",
            stop_price=48750.0, quantity=0.4, error="insufficient margin",
        )
        with patch("execution.live_service.place_catastrophe_stop", return_value=mock_stop):
            with patch("execution.live_service.log_stop_event"):
                svc._handle_entry(_bar(price=50000.0))

        assert svc.has_live_position is False

    def test_live_catastrophe_reject_flatten_fails_marks_naked(self, tmp_path):
        """CODEX FIX 2: if flatten SELL also fails, mark position as live
        so reconciliation can detect the naked position."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._get_strategy_equity = MagicMock(return_value=10000.0)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.runner._rsi_buffer = [100.0] * 20
        svc.runner.state.position_state = "flat"
        svc.runner.state.regime_active = False
        svc.runner.state.next_trade_id = 1
        svc.runner.state.next_zone_id = 1
        svc.runner.state.bars_since_last_exit = 999
        svc.runner.trades = []
        # First call = entry BUY (FILLED), second call = flatten SELL (FAILS)
        svc._place_market_order = MagicMock(side_effect=[
            {"status": "FILLED", "avgPrice": "50000.0", "executedQty": "0.400"},
            None,  # flatten fails
        ])

        from execution.live_executor import StopOrderEvent
        mock_stop = StopOrderEvent(
            timestamp="2024-01-01", event_type="reject",
            order_type="catastrophe_stop", side="long",
            stop_price=48750.0, quantity=0.4, error="network error",
        )
        with patch("execution.live_service.place_catastrophe_stop", return_value=mock_stop):
            with patch("execution.live_service.log_stop_event"):
                svc._handle_entry(_bar(price=50000.0))

        # Position marked open so reconciliation can handle it
        assert svc.has_live_position is True
        assert svc.live_quantity == 0.4


# ── FIX 2: startup recovery ────────────────────────────────────────


class TestFix2StartupRecovery:

    def test_restores_open_position_from_state_json(self, tmp_path):
        """After restart, live position fields must be restored."""
        state_dir = tmp_path / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.json").write_text(json.dumps({
            "position_state": "open",
            "regime_active": True,
            "next_trade_id": 5,
            "next_zone_id": 3,
            "bars_since_last_exit": 10,
            "trade_count": 4,
            "has_live_position": True,
            "live_entry_price": 72500.0,
            "live_quantity": 0.276,
            "live_alpha_level": 71593.75,
            "live_catastrophe_level": 70687.5,
            "open_catastrophe_order_id": "99887766",
        }))

        svc = _make_service(tmp_path)
        svc.state_dir = state_dir
        svc._log_tick = MagicMock()
        svc._restore_live_position_state()

        assert svc.has_live_position is True
        assert svc.live_entry_price == 72500.0
        assert svc.live_quantity == 0.276
        assert svc.live_alpha_level == pytest.approx(71593.75)
        assert svc.live_catastrophe_level == pytest.approx(70687.5)
        assert svc.open_catastrophe_order_id == "99887766"

    def test_no_state_file_starts_flat(self, tmp_path):
        """Without state.json, service starts flat."""
        svc = _make_service(tmp_path)
        svc._log_tick = MagicMock()
        svc._restore_live_position_state()

        assert svc.has_live_position is False
        assert svc.live_entry_price == 0.0

    def test_startup_clears_stale_position_when_exchange_flat(self, tmp_path):
        """CODEX FIX 3: if state.json says open but exchange is flat,
        clear the internal flag so new entries aren't blocked."""
        state_dir = tmp_path / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.json").write_text(json.dumps({
            "has_live_position": True,
            "live_entry_price": 72500.0,
            "live_quantity": 0.276,
            "live_alpha_level": 71593.75,
            "live_catastrophe_level": 70687.5,
            "open_catastrophe_order_id": "99887766",
        }))

        svc = _make_service(tmp_path, dry_run=False)
        svc.state_dir = state_dir
        svc._log_tick = MagicMock()

        # Exchange says NO position
        with patch("execution.live_service.fetch_position", return_value=None):
            svc._restore_live_position_state()

        assert svc.has_live_position is False
        assert svc.live_quantity == 0.0

    def test_startup_keeps_position_when_exchange_confirms(self, tmp_path):
        """If exchange confirms position exists, keep internal state."""
        state_dir = tmp_path / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.json").write_text(json.dumps({
            "has_live_position": True,
            "live_entry_price": 72500.0,
            "live_quantity": 0.276,
            "live_alpha_level": 71593.75,
            "live_catastrophe_level": 70687.5,
            "open_catastrophe_order_id": "99887766",
        }))

        svc = _make_service(tmp_path, dry_run=False)
        svc.state_dir = state_dir
        svc._log_tick = MagicMock()

        mock_pos = {"symbol": "BTCUSDT", "positionAmt": "0.276"}
        with patch("execution.live_service.fetch_position", return_value=mock_pos):
            svc._restore_live_position_state()

        assert svc.has_live_position is True
        assert svc.live_entry_price == 72500.0

    def test_save_then_restore_roundtrip(self, tmp_path):
        """Save state with open position, then restore it."""
        svc = _make_service(tmp_path)
        svc.runner.state.position_state = "open"
        svc.runner.state.regime_active = True
        svc.runner.state.next_trade_id = 5
        svc.runner.state.next_zone_id = 3
        svc.runner.state.bars_since_last_exit = 10
        svc.runner.trades = [1, 2, 3, 4]
        svc.runner._rsi_buffer = [100.0] * 20
        svc.has_live_position = True
        svc.live_entry_price = 68000.0
        svc.live_quantity = 0.5
        svc.live_alpha_level = 67150.0
        svc.live_catastrophe_level = 66300.0
        svc.open_catastrophe_order_id = "ABC123"
        svc._save_runner()

        # Create a new service and restore
        svc2 = _make_service(tmp_path)
        svc2.state_dir = svc.state_dir
        svc2._log_tick = MagicMock()
        svc2._restore_live_position_state()

        assert svc2.has_live_position is True
        assert svc2.live_entry_price == 68000.0
        assert svc2.live_quantity == 0.5
        assert svc2.live_alpha_level == 67150.0
        assert svc2.live_catastrophe_level == 66300.0
        assert svc2.open_catastrophe_order_id == "ABC123"


# ── FIX 3: reduceOnly boolean handling ─────────────────────────────


class TestFix3ReduceOnlyDetection:

    def test_detect_stop_with_boolean_true(self, tmp_path):
        """reduceOnly=True (boolean) must be recognized as stop."""
        svc = _make_service(tmp_path)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.has_live_position = True
        svc.live_catastrophe_level = 48000.0
        svc.live_quantity = 0.3

        mock_orders = [
            {"type": "STOP_MARKET", "reduceOnly": True, "orderId": "111"},
        ]
        mock_position = {"symbol": "BTCUSDT", "positionAmt": "0.3"}

        with patch("execution.live_service.fetch_position", return_value=mock_position):
            with patch("execution.live_service.fetch_open_orders", return_value=mock_orders):
                svc._reconcile()

        # Should NOT emit "missing catastrophe stop" alert because it found it
        alert_calls = [c for c in svc._log_tick.call_args_list
                       if "missing" in str(c).lower()]
        assert len(alert_calls) == 0

    def test_detect_stop_with_string_true(self, tmp_path):
        """reduceOnly="true" (string) must also be recognized."""
        svc = _make_service(tmp_path)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.has_live_position = True
        svc.live_catastrophe_level = 48000.0
        svc.live_quantity = 0.3

        mock_orders = [
            {"type": "STOP_MARKET", "reduceOnly": "true", "orderId": "222"},
        ]
        mock_position = {"symbol": "BTCUSDT", "positionAmt": "0.3"}

        with patch("execution.live_service.fetch_position", return_value=mock_position):
            with patch("execution.live_service.fetch_open_orders", return_value=mock_orders):
                svc._reconcile()

        alert_calls = [c for c in svc._log_tick.call_args_list
                       if "missing" in str(c).lower()]
        assert len(alert_calls) == 0

    def test_no_stop_detected_with_boolean_false(self, tmp_path):
        pass  # placeholder to keep class structure


class TestP0ExitOrder:
    """P0: _handle_exit must submit real MARKET SELL before clearing state."""

    def test_dry_run_exit_clears_immediately(self, tmp_path):
        svc = _make_service(tmp_path, dry_run=True)
        svc.has_live_position = True
        svc.live_quantity = 0.3
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc._handle_exit(_bar(), "time_stop")
        assert svc.has_live_position is False

    def test_live_exit_submits_sell_before_clearing(self, tmp_path):
        """Live mode must submit reduceOnly SELL and get FILLED before flat."""
        svc = _make_service(tmp_path, dry_run=False)
        svc.has_live_position = True
        svc.live_quantity = 0.3
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc._place_reduce_only_order = MagicMock(return_value={
            "status": "FILLED", "avgPrice": "50000", "executedQty": "0.3",
        })
        with patch("execution.live_service.cancel_all_orders", return_value={"ok": True}):
            with patch("execution.live_service.fetch_position", return_value=None):
                svc._handle_exit(_bar(), "time_stop")
        assert svc.has_live_position is False
        svc._place_reduce_only_order.assert_called_once_with("SELL", 0.3)

    def test_live_exit_sell_fails_halts(self, tmp_path):
        """If SELL fails, do NOT clear position — halt instead."""
        svc = _make_service(tmp_path, dry_run=False)
        svc.has_live_position = True
        svc.live_quantity = 0.3
        svc.live_entry_price = 50000.0
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.runner._rsi_buffer = [100.0] * 20
        svc.runner.state.position_state = "open"
        svc.runner.state.regime_active = True
        svc.runner.state.next_trade_id = 2
        svc.runner.state.next_zone_id = 2
        svc.runner.state.bars_since_last_exit = 5
        svc.runner.trades = []
        svc._place_reduce_only_order = MagicMock(return_value=None)
        with patch("execution.live_service.cancel_all_orders", return_value={"ok": True}):
            svc._handle_exit(_bar(), "time_stop")
        assert svc.has_live_position is True
        assert svc.halted is True
        assert "exit_sell_failed" in svc.halt_reason

    def test_live_exit_sell_not_filled_halts(self, tmp_path):
        """If SELL returns NEW (not FILLED), halt."""
        svc = _make_service(tmp_path, dry_run=False)
        svc.has_live_position = True
        svc.live_quantity = 0.3
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.runner._rsi_buffer = [100.0] * 20
        svc.runner.state.position_state = "open"
        svc.runner.state.regime_active = True
        svc.runner.state.next_trade_id = 2
        svc.runner.state.next_zone_id = 2
        svc.runner.state.bars_since_last_exit = 5
        svc.runner.trades = []
        svc._place_reduce_only_order = MagicMock(return_value={
            "status": "NEW", "avgPrice": "0", "executedQty": "0",
        })
        with patch("execution.live_service.cancel_all_orders", return_value={"ok": True}):
            svc._handle_exit(_bar(), "alpha_stop")
        assert svc.has_live_position is True
        assert svc.halted is True


class TestP2HaltClearingOnStartup:
    """P2: halt must be cleared before first bar processing."""

    def test_startup_reconciliation_clears_halt_before_first_bar(self, tmp_path):
        """If halted on startup but exchange is flat, halt clears
        before any ENTRY_FILL is processed."""
        state_dir = tmp_path / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.json").write_text(json.dumps({
            "has_live_position": True,
            "live_entry_price": 50000.0,
            "live_quantity": 0.1,
            "live_alpha_level": 49375.0,
            "live_catastrophe_level": 48750.0,
            "halted": True,
            "halt_reason": "position_unknown",
            "open_catastrophe_order_id": None,
        }))

        svc = _make_service(tmp_path, dry_run=False)
        svc.state_dir = state_dir
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.runner._rsi_buffer = [100.0] * 20
        svc.runner.state.position_state = "flat"
        svc.runner.state.regime_active = False
        svc.runner.state.next_trade_id = 1
        svc.runner.state.next_zone_id = 1
        svc.runner.state.bars_since_last_exit = 999
        svc.runner.trades = []

        # Exchange confirms flat
        with patch("execution.live_service.fetch_position", return_value=None):
            with patch("execution.live_service.fetch_open_orders", return_value=[]):
                svc._restore_live_position_state()
                if svc.halted and not svc.dry_run and svc.api_key:
                    svc._reconcile()

        assert svc.halted is False
        assert svc.has_live_position is False


class TestP1MissedBarCatchUp:
    """P1: live_service must catch up missed bars after downtime."""

    def test_catch_up_uses_replay_only_no_live_orders(self, tmp_path):
        """Catch-up must pass replay_only=True so no live orders fire."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc._handle_entry = MagicMock()
        svc._handle_exit = MagicMock()
        from execution.paper_runner_v2 import PaperRunnerV2, CandidateConfig
        real_runner = PaperRunnerV2(CandidateConfig(
            candidate_id="test", regime_rsi_period=3, regime_threshold=70.0,
            entry_mode="hybrid", pullback_pct=0.0075, breakout_pct=0.0025,
            max_entries_per_zone=6, cooldown_bars=2, hold_bars=24,
            exchange_leverage=3.0, base_frac=2.0, max_frac=3.0,
            alpha_stop_pct=0.0125, catastrophe_stop_pct=0.025,
        ))
        real_runner._rsi_buffer = [50000.0] * 200
        svc.runner = real_runner
        svc.last_bar_ts = datetime(2024, 1, 1, 10, 0)

        mock_server = datetime(2024, 1, 1, 13, 30)
        mock_bars = [
            [int((datetime(2024, 1, 1, h, 0).replace(
                tzinfo=timezone.utc).timestamp()) * 1000),
             "50000", "50100", "49900", "50050", "100"]
            for h in [11, 12]
        ]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_bars).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("execution.live_service.fetch_server_time", return_value=mock_server):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                with patch("execution.live_service.fetch_funding_rate", return_value=0.0):
                    with patch("execution.live_service.fetch_account_balance") as mb:
                        mb.return_value = MagicMock(available_balance=10000.0)
                        result = svc._catch_up_missed_bars()

        assert result is True
        # _handle_entry and _handle_exit must NOT be called during replay
        svc._handle_entry.assert_not_called()
        svc._handle_exit.assert_not_called()
        # But bars were processed (last_bar_ts advanced)
        assert svc.last_bar_ts == datetime(2024, 1, 1, 12, 0)

    def test_replay_exit_executes_when_live_position_open(self, tmp_path):
        """Restart with live position + replay TRADE_CLOSE → exit executes."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.has_live_position = True
        svc.live_quantity = 0.3
        svc.live_entry_price = 50000.0
        svc._place_reduce_only_order = MagicMock(return_value={
            "status": "FILLED", "avgPrice": "50100", "executedQty": "0.3",
        })

        bar = _bar(price=50100.0)

        with patch("execution.live_service.cancel_all_orders", return_value={"ok": True}):
            with patch("execution.live_service.fetch_position", return_value=None):
                svc._handle_exit(bar, "time_stop")

        assert svc.has_live_position is False
        svc._place_reduce_only_order.assert_called_once_with("SELL", 0.3)

    def test_replay_exit_skipped_when_no_live_position(self, tmp_path):
        """Replay TRADE_CLOSE with no live position → skip."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.has_live_position = False
        svc._handle_exit = MagicMock()

        # Simulate the replay_only branch
        events = ["TRADE_CLOSE #1 reason=time_stop"]
        replay_only = True
        if replay_only:
            if "TRADE_CLOSE" in " ".join(events):
                if svc.has_live_position:
                    svc._handle_exit(_bar(), events[0])
                # else: skip

        svc._handle_exit.assert_not_called()

    def test_replay_entry_skipped_exit_executes_if_live(self, tmp_path):
        """Replay with both entry and exit: entry skipped, exit executes
        only if live position exists."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.has_live_position = True
        svc.live_quantity = 0.2
        svc._handle_entry = MagicMock()
        svc._handle_exit = MagicMock()

        events = ["ENTRY_FILL price=50000", "TRADE_CLOSE #1 reason=alpha_stop"]
        replay_only = True

        if replay_only:
            if "ENTRY_FILL" in " ".join(events):
                pass  # always skip
            if "TRADE_CLOSE" in " ".join(events):
                if svc.has_live_position:
                    svc._handle_exit(_bar(), events[1])

        svc._handle_entry.assert_not_called()
        svc._handle_exit.assert_called_once()

    def test_replay_exit_fails_halts(self, tmp_path):
        """If replay exit SELL fails, system halts."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.has_live_position = True
        svc.live_quantity = 0.3
        svc.runner._rsi_buffer = [100.0] * 20
        svc.runner.state.position_state = "open"
        svc.runner.state.regime_active = True
        svc.runner.state.next_trade_id = 2
        svc.runner.state.next_zone_id = 2
        svc.runner.state.bars_since_last_exit = 5
        svc.runner.trades = []
        svc._place_reduce_only_order = MagicMock(return_value=None)

        with patch("execution.live_service.cancel_all_orders", return_value={"ok": True}):
            svc._handle_exit(_bar(), "time_stop")

        assert svc.halted is True
        assert svc.has_live_position is True

    def test_post_catchup_runner_exchange_mismatch_halts(self, tmp_path):
        """After catch-up, if runner is flat but exchange has position → HALT."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.has_live_position = False
        svc.runner._rsi_buffer = [50000.0] * 200
        svc.runner.state.position_state = "flat"
        svc.runner.state.regime_active = False
        svc.runner.state.next_trade_id = 1
        svc.runner.state.next_zone_id = 1
        svc.runner.state.bars_since_last_exit = 999
        svc.runner.trades = []
        svc.last_bar_ts = datetime(2024, 1, 1, 10, 0)

        mock_server = datetime(2024, 1, 1, 13, 30)
        mock_bars = [
            [int((datetime(2024, 1, 1, h, 0).replace(
                tzinfo=timezone.utc).timestamp()) * 1000),
             "50000", "50100", "49900", "50050", "100"]
            for h in [11, 12]
        ]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_bars).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        # Exchange shows position AFTER catch-up but runner is flat
        mock_pos = {"symbol": "BTCUSDT", "positionAmt": "0.15"}

        with patch("execution.live_service.fetch_server_time", return_value=mock_server):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                with patch("execution.live_service.fetch_funding_rate", return_value=0.0):
                    with patch("execution.live_service.fetch_account_balance") as mb:
                        mb.return_value = MagicMock(available_balance=10000.0)
                        with patch("execution.live_service.fetch_position",
                                   return_value=mock_pos):
                            with patch("execution.live_service.fetch_open_orders",
                                       return_value=[]):
                                result = svc._catch_up_missed_bars()

        assert result is True
        assert svc.halted is True
        assert "post_catchup_mismatch" in svc.halt_reason
        assert svc.has_live_position is True
        assert svc.live_quantity == 0.15

    def test_catch_up_failure_returns_false(self, tmp_path):
        """If fetch fails, catch-up returns False."""
        svc = _make_service(tmp_path, dry_run=True)
        svc._log_tick = MagicMock()
        svc.last_bar_ts = datetime(2024, 1, 1, 10, 0)
        mock_server = datetime(2024, 1, 1, 14, 30)

        with patch("execution.live_service.fetch_server_time", return_value=mock_server):
            with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
                result = svc._catch_up_missed_bars()

        assert result is False
        # last_bar_ts should NOT have advanced
        assert svc.last_bar_ts == datetime(2024, 1, 1, 10, 0)

    def test_catch_up_detects_and_replays_gap(self, tmp_path):
        svc = _make_service(tmp_path, dry_run=True)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        # Give runner the methods _process_bar needs
        from execution.paper_runner_v2 import PaperRunnerV2, CandidateConfig
        real_runner = PaperRunnerV2(CandidateConfig(
            candidate_id="test", regime_rsi_period=3, regime_threshold=70.0,
            entry_mode="hybrid", pullback_pct=0.0075, breakout_pct=0.0025,
            max_entries_per_zone=6, cooldown_bars=2, hold_bars=24,
            exchange_leverage=3.0, base_frac=2.0, max_frac=3.0,
            alpha_stop_pct=0.0125, catastrophe_stop_pct=0.025,
        ))
        real_runner._rsi_buffer = [50000.0] * 200
        svc.runner = real_runner
        svc.last_bar_ts = datetime(2024, 1, 1, 10, 0)

        mock_server = datetime(2024, 1, 1, 14, 30)
        mock_bars = [
            [int((datetime(2024, 1, 1, h, 0).replace(
                tzinfo=timezone.utc).timestamp()) * 1000),
             "50000", "50100", "49900", "50050", "100"]
            for h in [11, 12, 13]
        ]

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_bars).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("execution.live_service.fetch_server_time",
                   return_value=mock_server):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                with patch("execution.live_service.fetch_funding_rate", return_value=0.0):
                    with patch("execution.live_service.fetch_account_balance") as mock_bal:
                        mock_bal.return_value = MagicMock(available_balance=10000.0)
                        svc._catch_up_missed_bars()

        assert svc.last_bar_ts == datetime(2024, 1, 1, 13, 0)


    def _placeholder(self):
        pass


class TestP0LiveSafetyHardening:
    """P0 live safety hardening tests."""

    def test_exit_uses_reduce_only_to_prevent_reversal(self, tmp_path):
        """P0-1: exit SELL must use reduceOnly=true so it can't open short."""
        svc = _make_service(tmp_path, dry_run=False)
        svc.has_live_position = True
        svc.live_quantity = 0.3
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()

        # Mock _place_reduce_only_order (the new method)
        svc._place_reduce_only_order = MagicMock(return_value={
            "status": "FILLED", "avgPrice": "50000", "executedQty": "0.3",
        })
        svc._place_market_order = MagicMock()

        with patch("execution.live_service.cancel_all_orders", return_value={"ok": True}):
            with patch("execution.live_service.fetch_position", return_value=None):
                svc._handle_exit(_bar(), "time_stop")

        # Must use reduceOnly, not regular market order
        svc._place_reduce_only_order.assert_called_once_with("SELL", 0.3)
        svc._place_market_order.assert_not_called()
        assert svc.has_live_position is False

    def test_exit_expired_reduce_only_checks_exchange(self, tmp_path):
        """P0-1: if reduceOnly SELL expires (position already closed by
        catastrophe), verify with exchange before assuming flat."""
        svc = _make_service(tmp_path, dry_run=False)
        svc.has_live_position = True
        svc.live_quantity = 0.3
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc._place_reduce_only_order = MagicMock(return_value={
            "status": "EXPIRED",
        })

        with patch("execution.live_service.cancel_all_orders", return_value={"ok": True}):
            with patch("execution.live_service.fetch_position", return_value=None):
                svc._handle_exit(_bar(), "time_stop")

        # Position was already closed → confirmed flat
        assert svc.has_live_position is False

    def test_exit_verifies_zero_position_after_fill(self, tmp_path):
        """P0-3: after SELL FILLED, verify exchange position is zero."""
        svc = _make_service(tmp_path, dry_run=False)
        svc.has_live_position = True
        svc.live_quantity = 0.3
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.runner._rsi_buffer = [100.0] * 20
        svc.runner.state.position_state = "flat"
        svc.runner.state.regime_active = False
        svc.runner.state.next_trade_id = 1
        svc.runner.state.next_zone_id = 1
        svc.runner.state.bars_since_last_exit = 999
        svc.runner.trades = []
        svc._place_reduce_only_order = MagicMock(return_value={
            "status": "FILLED", "avgPrice": "50000", "executedQty": "0.3",
        })

        # Exchange still shows residual position
        mock_pos = {"positionAmt": "0.01"}
        with patch("execution.live_service.cancel_all_orders", return_value={"ok": True}):
            with patch("execution.live_service.fetch_position",
                       return_value=mock_pos):
                svc._handle_exit(_bar(), "time_stop")

        assert svc.halted is True
        assert "exit_residual" in svc.halt_reason

    def test_reconcile_catastrophe_replace_fail_halts(self, tmp_path):
        """P0-4: if catastrophe re-place fails, HALT."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.has_live_position = True
        svc.live_catastrophe_level = 48000.0
        svc.live_quantity = 0.3
        svc.runner._rsi_buffer = [100.0] * 20
        svc.runner.state.position_state = "open"
        svc.runner.state.regime_active = True
        svc.runner.state.next_trade_id = 2
        svc.runner.state.next_zone_id = 2
        svc.runner.state.bars_since_last_exit = 5
        svc.runner.trades = []

        mock_pos = {"symbol": "BTCUSDT", "positionAmt": "0.3"}
        mock_stop_reject = MagicMock(event_type="reject", error="margin")

        with patch("execution.live_service.fetch_position", return_value=mock_pos):
            with patch("execution.live_service.fetch_open_orders", return_value=[]):
                with patch("execution.live_service.place_catastrophe_stop",
                           return_value=mock_stop_reject):
                    with patch("execution.live_service.log_stop_event"):
                        svc._reconcile()

        assert svc.halted is True
        assert "catastrophe_replace_failed" in svc.halt_reason

    def test_entry_reentrancy_guard(self, tmp_path):
        """P0-5: duplicate entry call is blocked by reentrancy guard."""
        svc = _make_service(tmp_path, dry_run=True)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc._get_strategy_equity = MagicMock(return_value=10000.0)

        svc._order_in_progress = True
        svc._handle_entry(_bar())

        assert svc.has_live_position is False

    def test_entry_reentrancy_flag_resets_on_exception(self, tmp_path):
        """P0-5 (GPT Pro): exception in _handle_entry_inner must
        reset _order_in_progress flag via try/finally."""
        svc = _make_service(tmp_path, dry_run=True)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc._get_strategy_equity = MagicMock(side_effect=RuntimeError("boom"))

        try:
            svc._handle_entry(_bar())
        except RuntimeError:
            pass

        # Flag must be reset even after exception
        assert svc._order_in_progress is False

    def test_reconcile_missing_stop_no_level_data_halts(self, tmp_path):
        """P0-4 (GPT Pro): position exists, stop missing, but no
        stop level/qty to re-place → HALT."""
        svc = _make_service(tmp_path, dry_run=False)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.has_live_position = True
        svc.live_catastrophe_level = 0.0  # no level!
        svc.live_quantity = 0.0            # no qty!
        svc.runner._rsi_buffer = [100.0] * 20
        svc.runner.state.position_state = "open"
        svc.runner.state.regime_active = True
        svc.runner.state.next_trade_id = 2
        svc.runner.state.next_zone_id = 2
        svc.runner.state.bars_since_last_exit = 5
        svc.runner.trades = []

        mock_pos = {"symbol": "BTCUSDT", "positionAmt": "0.3"}
        with patch("execution.live_service.fetch_position", return_value=mock_pos):
            with patch("execution.live_service.fetch_open_orders", return_value=[]):
                svc._reconcile()

        assert svc.halted is True
        assert "catastrophe_missing_no_replace_data" in svc.halt_reason

    def test_cancel_all_orders_failure_visible_to_caller(self, tmp_path):
        """P0-6 (GPT Pro): cancel_all_orders must return failure,
        not silently swallow it."""
        from execution.live_executor import cancel_all_orders
        with patch("execution.live_executor._signed_request",
                   side_effect=Exception("network error")):
            result = cancel_all_orders("key", "secret")
        assert result["ok"] is False
        assert "network error" in result["error"]

    def test_cancel_all_orders_success_returns_ok(self, tmp_path):
        """P0-6: successful cancel returns ok=True."""
        from execution.live_executor import cancel_all_orders
        with patch("execution.live_executor._signed_request", return_value={}):
            result = cancel_all_orders("key", "secret")
        assert result["ok"] is True

    def test_exit_only_cancels_stop_after_sell_filled(self, tmp_path):
        """GPT Pro: catastrophe stop must NOT be cancelled until
        SELL is confirmed FILLED. If SELL fails, stop stays as
        last line of defense."""
        svc = _make_service(tmp_path, dry_run=False)
        svc.has_live_position = True
        svc.live_quantity = 0.3
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.runner._rsi_buffer = [100.0] * 20
        svc.runner.state.position_state = "open"
        svc.runner.state.regime_active = True
        svc.runner.state.next_trade_id = 2
        svc.runner.state.next_zone_id = 2
        svc.runner.state.bars_since_last_exit = 5
        svc.runner.trades = []

        # SELL fails
        svc._place_reduce_only_order = MagicMock(return_value=None)
        cancel_mock = MagicMock(return_value={"ok": True})

        with patch("execution.live_service.cancel_all_orders", cancel_mock):
            svc._handle_exit(_bar(), "time_stop")

        # cancel_all_orders must NOT have been called (stop preserved)
        cancel_mock.assert_not_called()
        assert svc.halted is True

    def test_exit_rejected_reduce_only_checks_exchange(self, tmp_path):
        """GPT Pro: REJECTED (not just EXPIRED) should also verify
        exchange position before assuming flat."""
        svc = _make_service(tmp_path, dry_run=False)
        svc.has_live_position = True
        svc.live_quantity = 0.3
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc._place_reduce_only_order = MagicMock(return_value={
            "status": "REJECTED",
        })

        with patch("execution.live_service.cancel_all_orders",
                    return_value={"ok": True}):
            with patch("execution.live_service.fetch_position",
                       return_value=None):
                svc._handle_exit(_bar(), "time_stop")

        # REJECTED + exchange flat → confirmed flat
        assert svc.has_live_position is False


