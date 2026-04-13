"""Tests for the 3 Codex-flagged deployment fixes.

1) Entry order must be submitted before internal state flips to OPEN
2) Startup must restore persisted live-position fields
3) reduceOnly detection must handle both boolean and string
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime
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

        with patch("execution.live_service.cancel_all_orders"):
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

        with patch("execution.live_service.cancel_all_orders"):
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

        with patch("execution.live_service.cancel_all_orders"):
            svc._handle_entry(_bar(price=50000.0))

        # Must be marked as live (naked) for reconciliation
        assert svc.has_live_position is True
        assert svc.live_quantity == 0.1

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

        with patch("execution.live_service.cancel_all_orders"):
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
        """reduceOnly=False must NOT be recognized as catastrophe stop."""
        svc = _make_service(tmp_path)
        svc._log_tick = MagicMock()
        svc._log_event = MagicMock()
        svc.has_live_position = True
        svc.live_catastrophe_level = 48000.0
        svc.live_quantity = 0.3

        mock_orders = [
            {"type": "STOP_MARKET", "reduceOnly": False, "orderId": "333"},
        ]
        mock_position = {"symbol": "BTCUSDT", "positionAmt": "0.3"}

        with patch("execution.live_service.fetch_position", return_value=mock_position):
            with patch("execution.live_service.fetch_open_orders", return_value=mock_orders):
                with patch("execution.live_service.place_catastrophe_stop") as mock_place:
                    mock_place.return_value = MagicMock(event_type="ack")
                    with patch("execution.live_service.log_stop_event"):
                        svc._reconcile()

        # Should detect missing stop and try to re-place
        # (the STOP_MARKET with reduceOnly=False is not our catastrophe stop)
