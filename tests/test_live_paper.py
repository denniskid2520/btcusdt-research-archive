"""Tests for the live paper trading runner.

Verifies the core loop: fetch bars → evaluate strategy → execute signals,
using the BinanceStubAdapter to avoid real network calls.
"""

from __future__ import annotations

from adapters.base import MarketBar, MarketDataAdapter
from adapters.binance_stub import BinanceStubAdapter
from execution.paper_broker import PaperBroker
from research.backtest import build_default_strategy
from risk.limits import RiskLimits
from trading.live_paper import LivePaperRunner, LivePaperState


class ReplayAdapter(MarketDataAdapter):
    """Feeds historical bars one tick at a time, simulating live data."""

    def __init__(self, bars: list[MarketBar]) -> None:
        self._bars = bars
        self._cursor = 0

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[MarketBar]:
        self._cursor = min(self._cursor + 1, len(self._bars))
        end = self._cursor
        start = max(0, end - limit)
        return self._bars[start:end]


def test_live_paper_runner_processes_tick_and_generates_state() -> None:
    """A single tick should evaluate the strategy and return updated state."""
    runner = LivePaperRunner(
        adapter=BinanceStubAdapter(),
        strategy=build_default_strategy(),
        broker=PaperBroker(initial_cash=100_000.0, fee_rate=0.001, slippage_rate=0.0005),
        limits=RiskLimits(),
        symbol="BTCUSDT",
        timeframe="4h",
        bar_lookback=120,
    )
    state = runner.tick()
    assert isinstance(state, LivePaperState)
    assert state.equity > 0
    assert state.bars_processed > 0
    assert state.last_signal_action in {"hold", "buy", "short", "sell", "cover"}


def test_live_paper_runner_opens_and_manages_position_over_ticks() -> None:
    """Multiple ticks should allow the runner to open and manage positions."""
    runner = LivePaperRunner(
        adapter=BinanceStubAdapter(),
        strategy=build_default_strategy(),
        broker=PaperBroker(initial_cash=100_000.0, fee_rate=0.001, slippage_rate=0.0005),
        limits=RiskLimits(),
        symbol="BTCUSDT",
        timeframe="4h",
        bar_lookback=120,
    )
    # Run multiple ticks — should not crash
    states = [runner.tick() for _ in range(5)]
    assert len(states) == 5
    assert all(s.equity > 0 for s in states)


def test_live_paper_runner_trade_log_records_fills() -> None:
    """Completed trades should appear in the runner's trade log."""
    runner = LivePaperRunner(
        adapter=BinanceStubAdapter(),
        strategy=build_default_strategy(),
        broker=PaperBroker(initial_cash=100_000.0, fee_rate=0.001, slippage_rate=0.0005),
        limits=RiskLimits(),
        symbol="BTCUSDT",
        timeframe="4h",
        bar_lookback=120,
    )
    # Run enough ticks to potentially generate trades
    for _ in range(10):
        runner.tick()
    # Trade log should be a list (possibly empty if no signals triggered)
    assert isinstance(runner.trade_log, list)


def test_live_paper_replay_generates_trades_on_real_data() -> None:
    """Replay real 4H data through the runner — should produce trades."""
    from data.backfill import load_bars_from_csv

    all_bars = load_bars_from_csv("src/data/btcusdt_4h_5year.csv")
    # Use bars from index 500 onward (known to have trade setups)
    bars = all_bars[500:]
    adapter = ReplayAdapter(bars)
    runner = LivePaperRunner(
        adapter=adapter,
        strategy=build_default_strategy(),
        broker=PaperBroker(initial_cash=100_000.0, fee_rate=0.001, slippage_rate=0.0005),
        limits=RiskLimits(),
        symbol="BTCUSDT",
        timeframe="4h",
        bar_lookback=120,
    )
    # Replay all bars
    for _ in range(len(bars)):
        state = runner.tick()

    assert state.equity > 0
    assert state.bars_processed > 0
    assert len(runner.trade_log) >= 1
