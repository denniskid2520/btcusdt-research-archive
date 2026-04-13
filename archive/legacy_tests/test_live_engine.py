"""Tests for live paper trading engine."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from adapters.base import MarketBar
from execution.live_engine import LiveEngine, LiveState, LiveConfig
from research.daily_flag import DailyFlagSignal
from strategies.base import StrategySignal
from strategies.trend_breakout import StrategyEvaluation


def _bar(ts: str, o: float, h: float, l: float, c: float, v: float = 1000) -> MarketBar:
    return MarketBar(
        timestamp=datetime.fromisoformat(ts),
        open=o, high=h, low=l, close=c, volume=v,
    )


class TestLiveState:

    def test_save_and_load_roundtrip(self):
        state = LiveState(
            btc_balance=1.5,
            position_side="long",
            position_qty=0.5,
            entry_price=60000.0,
            entry_rule="descending_channel_support_bounce",
            trailing_stop_atr=3.5,
            best_price=62000.0,
            stop_price=58000.0,
            entry_time="2025-01-01T00:00:00",
            trades=[{"pnl": 0.05}],
        )
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = Path(f.name)
        state.save(path)
        loaded = LiveState.load(path)
        assert loaded.btc_balance == 1.5
        assert loaded.position_side == "long"
        assert loaded.position_qty == 0.5
        assert loaded.entry_price == 60000.0
        assert loaded.best_price == 62000.0
        assert loaded.entry_rule == "descending_channel_support_bounce"
        assert len(loaded.trades) == 1
        path.unlink()

    def test_load_missing_file_returns_default(self):
        state = LiveState.load(Path("/nonexistent/state.json"))
        assert state.btc_balance == 1.0
        assert state.position_side == "flat"
        assert state.position_qty == 0.0

    def test_state_has_position_open(self):
        state = LiveState(position_side="long", position_qty=0.5)
        assert state.is_position_open
        state2 = LiveState(position_side="flat", position_qty=0.0)
        assert not state2.is_position_open


class TestLiveConfig:

    def test_default_config(self):
        cfg = LiveConfig()
        assert cfg.symbol == "BTCUSDT"
        assert cfg.leverage == 3
        assert cfg.timeframe == "4h"
        assert cfg.risk_per_trade_pct == 0.05
        assert cfg.fee_rate == 0.001


class TestLiveEngine:

    def test_engine_initializes_with_state(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = Path(f.name)
        engine = LiveEngine(state_path=path)
        assert engine.state.btc_balance == 1.0
        assert not engine.state.is_position_open
        path.unlink()

    def test_trailing_stop_long_triggers(self):
        """When price drops below trailing stop, should generate sell signal."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = Path(f.name)
        engine = LiveEngine(state_path=path)
        engine.state.position_side = "long"
        engine.state.position_qty = 0.5
        engine.state.entry_price = 60000.0
        engine.state.trailing_stop_atr = 3.5
        engine.state.best_price = 65000.0

        # Simulate ATR of ~1000 → stop at 65000 - 3.5*1000 = 61500
        bars = [_bar(f"2025-01-{i+1:02d}T00:00:00", 60000+i*100, 60500+i*100, 59500+i*100, 60000+i*100) for i in range(20)]
        atr = engine._compute_atr(bars, 14)
        assert atr > 0

        stop = engine.state.best_price - engine.state.trailing_stop_atr * atr
        assert stop < engine.state.best_price
        path.unlink()

    def test_trailing_stop_short_triggers(self):
        """When price rises above trailing stop, should generate cover signal."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = Path(f.name)
        engine = LiveEngine(state_path=path)
        engine.state.position_side = "short"
        engine.state.position_qty = 0.5
        engine.state.entry_price = 60000.0
        engine.state.trailing_stop_atr = 3.5
        engine.state.best_price = 55000.0

        bars = [_bar(f"2025-01-{i+1:02d}T00:00:00", 56000+i*100, 56500+i*100, 55500+i*100, 56000+i*100) for i in range(20)]
        atr = engine._compute_atr(bars, 14)
        stop = engine.state.best_price + engine.state.trailing_stop_atr * atr
        assert stop > engine.state.best_price
        path.unlink()

    def test_process_bar_updates_best_price_long(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = Path(f.name)
        engine = LiveEngine(state_path=path)
        engine.state.position_side = "long"
        engine.state.position_qty = 0.5
        engine.state.entry_price = 60000.0
        engine.state.best_price = 62000.0
        engine.state.trailing_stop_atr = 3.5

        bar = _bar("2025-01-15T00:00:00", 63000, 64000, 62500, 63500)
        engine._update_best_price(bar)
        assert engine.state.best_price == 64000.0  # updated to bar high
        path.unlink()

    def test_process_bar_updates_best_price_short(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = Path(f.name)
        engine = LiveEngine(state_path=path)
        engine.state.position_side = "short"
        engine.state.position_qty = 0.5
        engine.state.entry_price = 60000.0
        engine.state.best_price = 58000.0
        engine.state.trailing_stop_atr = 3.5

        bar = _bar("2025-01-15T00:00:00", 57000, 57500, 56000, 57200)
        engine._update_best_price(bar)
        assert engine.state.best_price == 56000.0  # updated to bar low
        path.unlink()


def _make_bars(n: int = 500, base_price: float = 60000) -> list[MarketBar]:
    """Create N 4h bars with gentle oscillation across multiple months."""
    bars = []
    for i in range(n):
        day = (i // 6) + 1
        hour = (i % 6) * 4
        month = min(((day - 1) // 28) + 1, 12)
        d = ((day - 1) % 28) + 1
        ts = f"2025-{month:02d}-{d:02d}T{hour:02d}:00:00"
        p = base_price + (i % 20 - 10) * 100
        bars.append(_bar(ts, p - 200, p + 300, p - 500, p))
    return bars


def _hold_eval() -> StrategyEvaluation:
    """Strategy evaluation that returns 'hold'."""
    return StrategyEvaluation(
        signal=StrategySignal(action="hold", confidence=0, reason="no_signal"),
        rule_evaluations=[],
        parent_context=None,
    )


class TestLiveEngineDailyFlag:
    """Tests for daily flag overlay and MTF bar support in live engine."""

    def _make_engine(self) -> tuple[LiveEngine, Path]:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = Path(f.name)
        engine = LiveEngine(state_path=path)
        return engine, path

    def test_tick_accepts_mtf_bars_and_futures_provider(self):
        """tick() accepts mtf_bars and futures_provider keyword args."""
        engine, path = self._make_engine()
        try:
            bars = _make_bars(200)
            # Should not raise TypeError for unknown kwargs
            engine.tick(bars, mtf_bars=None, futures_provider=None)
        finally:
            path.unlink()

    def test_tick_passes_mtf_bars_to_strategy(self):
        """Strategy.evaluate() receives mtf_bars when provided to tick()."""
        engine, path = self._make_engine()
        try:
            bars = _make_bars(200)
            calls = []
            original_evaluate = engine.strategy.evaluate

            def spy_evaluate(**kwargs):
                calls.append(kwargs)
                return original_evaluate(**kwargs)

            engine.strategy.evaluate = spy_evaluate
            from data.mtf_bars import MultiTimeframeBars
            mtf = MultiTimeframeBars({"4h": bars})
            engine.tick(bars, mtf_bars=mtf)

            assert len(calls) >= 1
            assert calls[0].get("mtf_bars") is mtf
        finally:
            path.unlink()

    def test_daily_flag_short_overrides_hold(self):
        """When 4h strategy holds but daily flag fires, engine opens short."""
        engine, path = self._make_engine()
        engine.state.tick_count = 5  # Next tick = 6th → daily flag check
        try:
            bars = _make_bars(500)

            flag = DailyFlagSignal(
                action="short", flag_type="bear_flag",
                channel_slope=0.5, support=58000, resistance=62000,
                confidence=0.8, timestamp=bars[-1].timestamp,
            )

            with patch.object(engine.strategy, "evaluate", return_value=_hold_eval()):
                with patch("execution.live_engine.detect_daily_flag", return_value=flag):
                    action = engine.tick(bars)

            assert action is not None
            assert action["side"] == "short"
            assert "daily_bear_flag" in action["rule"]
            assert engine.state.position_side == "short"
        finally:
            path.unlink()

    def test_daily_flag_long_overrides_hold(self):
        """When 4h strategy holds but daily flag fires long, engine opens long."""
        engine, path = self._make_engine()
        engine.state.tick_count = 5
        try:
            bars = _make_bars(500)

            flag = DailyFlagSignal(
                action="long", flag_type="bull_flag",
                channel_slope=-0.3, support=58000, resistance=62000,
                confidence=0.7, timestamp=bars[-1].timestamp,
            )

            with patch.object(engine.strategy, "evaluate", return_value=_hold_eval()):
                with patch("execution.live_engine.detect_daily_flag", return_value=flag):
                    action = engine.tick(bars)

            assert action is not None
            assert action["side"] == "long"
            assert "daily_bull_flag" in action.get("rule", "")
        finally:
            path.unlink()

    def test_daily_flag_not_checked_every_tick(self):
        """Daily flag only checked every 6th tick, not every tick."""
        engine, path = self._make_engine()
        engine.state.tick_count = 2  # Not a 6th-tick boundary
        try:
            bars = _make_bars(500)

            with patch.object(engine.strategy, "evaluate", return_value=_hold_eval()):
                with patch("execution.live_engine.detect_daily_flag") as mock_flag:
                    engine.tick(bars)
                    mock_flag.assert_not_called()
        finally:
            path.unlink()

    def test_daily_flag_skipped_when_position_open(self):
        """Daily flag is not checked when a position is already open."""
        engine, path = self._make_engine()
        try:
            bars = _make_bars(500)
            # Set up a position that won't trigger any exits
            engine.state.position_side = "short"
            engine.state.position_qty = 0.5
            engine.state.entry_price = 60000
            engine.state.trailing_stop_atr = 100.0  # Very wide → won't trigger
            engine.state.best_price = bars[-1].low
            engine.state.stop_price = 0.0
            engine.state.entry_time = bars[-5].timestamp.isoformat()  # Recent → no time stop
            engine.state.tick_count = 5

            with patch("execution.live_engine.detect_daily_flag") as mock_flag:
                engine.tick(bars)
                mock_flag.assert_not_called()
        finally:
            path.unlink()

    def test_tick_count_increments(self):
        """tick_count increments each call and persists in state."""
        engine, path = self._make_engine()
        assert engine.state.tick_count == 0
        try:
            bars = _make_bars(200)
            with patch.object(engine.strategy, "evaluate", return_value=_hold_eval()):
                engine.tick(bars)
            assert engine.state.tick_count == 1
            with patch.object(engine.strategy, "evaluate", return_value=_hold_eval()):
                engine.tick(bars)
            assert engine.state.tick_count == 2
        finally:
            path.unlink()

    def test_daily_flag_does_not_override_4h_signal(self):
        """When 4h strategy fires a signal, daily flag does NOT override it."""
        engine, path = self._make_engine()
        engine.state.tick_count = 5
        try:
            bars = _make_bars(500)

            # 4h strategy fires long
            long_eval = StrategyEvaluation(
                signal=StrategySignal(
                    action="buy", confidence=0.8,
                    reason="descending_channel_support_bounce",
                    stop_price=58000, target_price=65000,
                    metadata={"trailing_stop_atr": 3.5},
                ),
                rule_evaluations=[],
                parent_context=None,
            )
            # Daily flag fires short (conflicting)
            flag = DailyFlagSignal(
                action="short", flag_type="bear_flag",
                channel_slope=0.5, support=58000, resistance=62000,
                confidence=0.8, timestamp=bars[-1].timestamp,
            )

            with patch.object(engine.strategy, "evaluate", return_value=long_eval):
                with patch("execution.live_engine.detect_daily_flag", return_value=flag):
                    action = engine.tick(bars)

            # 4h signal wins — daily flag only overrides "hold"
            assert action is not None
            assert action["side"] == "long"
        finally:
            path.unlink()


class TestLiveEngineMacroSell:
    """Tests for macro cycle top-sell in live engine."""

    def _make_engine(self) -> tuple[LiveEngine, Path]:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = Path(f.name)
        engine = LiveEngine(state_path=path)
        return engine, path

    def test_state_has_usdt_reserves(self):
        """LiveState tracks USDT reserves and macro sell flag."""
        state = LiveState()
        assert state.usdt_reserves == 0.0
        assert state.macro_daily_sold is False

    def test_macro_sell_triggers_on_high_rsi(self):
        """When D-RSI>=75, W-RSI>=70, M-RSI>=65, sell 45% of BTC."""
        engine, path = self._make_engine()
        engine.state.btc_balance = 3.70
        try:
            # Mock RSI values: daily=80, weekly=72, monthly=68
            with patch.object(engine, "_get_macro_rsi", return_value=(80.0, 72.0, 68.0)):
                bars = _make_bars(200, base_price=120000)
                result = engine.check_macro_sell(bars[-1])

            assert result is not None
            assert result["action"] == "macro_sell"
            # 45% of 3.70 = 1.665, but capped by min_btc_reserve=1.0
            # sellable = 3.70 - 1.0 = 2.70, sell = min(3.70*0.45, 2.70) = 1.665
            assert abs(result["btc_sold"] - 1.665) < 0.01
            assert engine.state.usdt_reserves > 0
            assert engine.state.macro_daily_sold is True
        finally:
            path.unlink()

    def test_macro_sell_respects_min_btc_reserve(self):
        """Never sell below min_btc_reserve (1.0 BTC)."""
        engine, path = self._make_engine()
        engine.state.btc_balance = 1.5  # 45% = 0.675, but reserve=1.0 → only sell 0.5
        try:
            with patch.object(engine, "_get_macro_rsi", return_value=(80.0, 72.0, 68.0)):
                bars = _make_bars(200, base_price=120000)
                result = engine.check_macro_sell(bars[-1])

            assert result is not None
            assert abs(result["btc_sold"] - 0.5) < 0.01
            assert engine.state.btc_balance >= 1.0
        finally:
            path.unlink()

    def test_macro_sell_skips_when_rsi_too_low(self):
        """No sell when RSI conditions not met."""
        engine, path = self._make_engine()
        engine.state.btc_balance = 3.70
        try:
            with patch.object(engine, "_get_macro_rsi", return_value=(60.0, 50.0, 55.0)):
                bars = _make_bars(200, base_price=120000)
                result = engine.check_macro_sell(bars[-1])

            assert result is None
            assert engine.state.usdt_reserves == 0.0
        finally:
            path.unlink()

    def test_macro_sell_only_once(self):
        """Macro sell only triggers once (flag prevents re-sell)."""
        engine, path = self._make_engine()
        engine.state.btc_balance = 3.70
        engine.state.macro_daily_sold = True  # already sold
        try:
            with patch.object(engine, "_get_macro_rsi", return_value=(80.0, 72.0, 68.0)):
                bars = _make_bars(200, base_price=120000)
                result = engine.check_macro_sell(bars[-1])

            assert result is None
        finally:
            path.unlink()

    def test_macro_sell_skips_when_position_open(self):
        """Don't sell BTC while a trade position is open."""
        engine, path = self._make_engine()
        engine.state.btc_balance = 3.70
        engine.state.position_side = "short"
        engine.state.position_qty = 1.0
        try:
            with patch.object(engine, "_get_macro_rsi", return_value=(80.0, 72.0, 68.0)):
                bars = _make_bars(200, base_price=120000)
                result = engine.check_macro_sell(bars[-1])

            assert result is None
        finally:
            path.unlink()
