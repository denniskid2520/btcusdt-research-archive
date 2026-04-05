"""Live paper trading runner.

Fetches real-time bars, evaluates the strategy, and executes signals
through a paper broker.  Each call to ``tick()`` represents one bar cycle.

Usage (CLI):
    python -m trading.live_paper --symbol BTCUSDT --timeframe 4h

Usage (programmatic):
    runner = LivePaperRunner(adapter, strategy, broker, limits, symbol, timeframe)
    state = runner.tick()
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from adapters.base import MarketBar, MarketDataAdapter, OrderRequest, Position
from execution.paper_broker import PaperBroker
from monitoring.logging_utils import configure_logger
from risk.limits import RiskLimits, allow_order, calculate_order_quantity
from strategies.base import Strategy, StrategySignal

logger = configure_logger(__name__)


@dataclass(frozen=True)
class LivePaperState:
    """Snapshot of the runner's state after a tick."""

    timestamp: datetime
    equity: float
    cash: float
    bars_processed: int
    last_signal_action: str
    last_signal_reason: str
    position_side: str
    position_quantity: float
    trade_count: int


@dataclass
class TradeRecord:
    """One completed round-trip trade."""

    entry_time: datetime
    exit_time: datetime
    entry_rule: str
    exit_reason: str
    entry_price: float
    exit_price: float
    side: str
    quantity: float
    pnl: float


class LivePaperRunner:
    """Orchestrates the fetch → evaluate → execute loop for paper trading."""

    def __init__(
        self,
        adapter: MarketDataAdapter,
        strategy: Strategy,
        broker: PaperBroker,
        limits: RiskLimits,
        symbol: str = "BTCUSDT",
        timeframe: str = "4h",
        bar_lookback: int = 120,
    ) -> None:
        self.adapter = adapter
        self.strategy = strategy
        self.broker = broker
        self.limits = limits
        self.symbol = symbol
        self.timeframe = timeframe
        self.bar_lookback = bar_lookback
        self.trade_log: list[TradeRecord] = []
        self._tick_count = 0
        self._pending_entry: dict[str, Any] | None = None

    def tick(self) -> LivePaperState:
        """Run one cycle: fetch bars → evaluate → execute."""
        self._tick_count += 1

        bars = self.adapter.fetch_ohlcv(
            symbol=self.symbol,
            timeframe=self.timeframe,
            limit=self.bar_lookback,
        )
        if not bars:
            return self._build_state(bars=[], signal_action="hold", signal_reason="no_bars")

        current_bar = bars[-1]
        market_price = current_bar.close
        position = self.broker.get_position(self.symbol)

        # Check stop/target for open positions
        exit_signal = self._check_exits(position, current_bar)
        if exit_signal is not None and exit_signal.action in {"sell", "cover"}:
            self._execute_exit(exit_signal, position, current_bar)
            position = self.broker.get_position(self.symbol)

        # Evaluate strategy
        signal = self.strategy.generate_signal(
            symbol=self.symbol,
            bars=bars,
            position=position,
        )

        # Execute signal
        if signal.action in {"buy", "short"}:
            self._execute_entry(signal, market_price, current_bar.timestamp)
        elif signal.action in {"sell", "cover"}:
            self._execute_exit(signal, position, current_bar)

        return self._build_state(bars=bars, signal_action=signal.action, signal_reason=signal.reason)

    def _check_exits(self, position: Position, bar: MarketBar) -> StrategySignal | None:
        """Check stop-loss and take-profit on the current bar."""
        if not position.is_open:
            return None

        stop_price = getattr(position, "stop_price", None)
        target_price = getattr(position, "target_price", None)

        if position.side == "long":
            if stop_price is not None and bar.low <= stop_price:
                return StrategySignal(action="sell", confidence=1.0, reason="long_structure_stop")
            if target_price is not None and bar.high >= target_price:
                return StrategySignal(action="sell", confidence=1.0, reason="long_target_hit")
        elif position.side == "short":
            if stop_price is not None and bar.high >= stop_price:
                return StrategySignal(action="cover", confidence=1.0, reason="short_structure_stop")
            if target_price is not None and bar.low <= target_price:
                return StrategySignal(action="cover", confidence=1.0, reason="short_target_hit")

        return None

    def _execute_entry(self, signal: StrategySignal, market_price: float, timestamp: datetime) -> None:
        """Submit an entry order through the paper broker."""
        position = self.broker.get_position(self.symbol)
        if position.is_open:
            return

        cash = self.broker.get_cash()
        quantity = calculate_order_quantity(cash, market_price, self.limits)
        if quantity <= 0:
            return

        order = OrderRequest(
            symbol=self.symbol,
            side=signal.action,
            quantity=quantity,
            order_type="market",
            timestamp=timestamp,
            metadata={
                "stop_price": signal.stop_price,
                "target_price": signal.target_price,
                "second_target_price": signal.metadata.get("second_target_price") if signal.metadata else None,
                "reason": signal.reason,
            },
        )

        if not allow_order(cash, order, market_price, 0, self.limits, position):
            return

        fill = self.broker.submit_order(order, market_price)
        if fill is not None:
            logger.info(
                "ENTRY %s %s qty=%.6f price=%.2f rule=%s",
                fill.side, fill.symbol, fill.quantity, fill.fill_price, signal.reason,
            )
            self._pending_entry = {
                "entry_time": timestamp,
                "entry_rule": signal.reason,
                "entry_price": fill.fill_price,
                "side": fill.side,
                "quantity": fill.quantity,
            }

    def _execute_exit(self, signal: StrategySignal, position: Position, bar: MarketBar) -> None:
        """Submit an exit order and record the completed trade."""
        if not position.is_open:
            return

        order = OrderRequest(
            symbol=self.symbol,
            side=signal.action,
            quantity=position.quantity,
            order_type="market",
            timestamp=bar.timestamp,
            metadata={},
        )

        fill = self.broker.submit_order(order, bar.close)
        if fill is not None:
            logger.info(
                "EXIT  %s %s qty=%.6f price=%.2f reason=%s",
                fill.side, fill.symbol, fill.quantity, fill.fill_price, signal.reason,
            )
            if self._pending_entry is not None:
                pnl = (
                    (fill.fill_price - self._pending_entry["entry_price"]) * fill.quantity
                    if self._pending_entry["side"] in {"buy", "long"}
                    else (self._pending_entry["entry_price"] - fill.fill_price) * fill.quantity
                )
                self.trade_log.append(TradeRecord(
                    entry_time=self._pending_entry["entry_time"],
                    exit_time=bar.timestamp,
                    entry_rule=self._pending_entry["entry_rule"],
                    exit_reason=signal.reason,
                    entry_price=self._pending_entry["entry_price"],
                    exit_price=fill.fill_price,
                    side=self._pending_entry["side"],
                    quantity=fill.quantity,
                    pnl=pnl,
                ))
                self._pending_entry = None

    def _build_state(self, bars: list[MarketBar], signal_action: str, signal_reason: str) -> LivePaperState:
        """Build a state snapshot."""
        position = self.broker.get_position(self.symbol)
        market_price = bars[-1].close if bars else 0.0
        equity = self.broker.mark_to_market(self.symbol, market_price) if bars else self.broker.get_cash()

        return LivePaperState(
            timestamp=bars[-1].timestamp if bars else datetime.now(timezone.utc).replace(tzinfo=None),
            equity=equity,
            cash=self.broker.get_cash(),
            bars_processed=len(bars),
            last_signal_action=signal_action,
            last_signal_reason=signal_reason,
            position_side=position.side if position.is_open else "flat",
            position_quantity=position.quantity if position.is_open else 0.0,
            trade_count=len(self.trade_log),
        )

    def save_state(self, path: str | Path) -> None:
        """Persist current state and trade log to JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "tick_count": self._tick_count,
            "cash": self.broker.get_cash(),
            "trades": [
                {
                    "entry_time": t.entry_time.isoformat(),
                    "exit_time": t.exit_time.isoformat(),
                    "entry_rule": t.entry_rule,
                    "exit_reason": t.exit_reason,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "side": t.side,
                    "quantity": t.quantity,
                    "pnl": t.pnl,
                }
                for t in self.trade_log
            ],
        }
        path.write_text(json.dumps(data, indent=2))
        logger.info("State saved to %s", path)


def main() -> None:
    """CLI entry point for live paper trading."""
    parser = argparse.ArgumentParser(description="Live paper trading runner")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--lookback", type=int, default=120)
    parser.add_argument("--initial-cash", type=float, default=100_000.0)
    parser.add_argument("--interval-seconds", type=int, default=60, help="Poll interval between ticks")
    parser.add_argument("--max-ticks", type=int, default=0, help="Stop after N ticks (0=forever)")
    parser.add_argument("--state-file", default="data/reports/live_paper_state.json")
    args = parser.parse_args()

    from adapters.binance_live import BinanceLiveAdapter
    from research.backtest import build_default_strategy

    runner = LivePaperRunner(
        adapter=BinanceLiveAdapter(),
        strategy=build_default_strategy(),
        broker=PaperBroker(initial_cash=args.initial_cash, fee_rate=0.001, slippage_rate=0.0005),
        limits=RiskLimits(),
        symbol=args.symbol,
        timeframe=args.timeframe,
        bar_lookback=args.lookback,
    )

    tick_count = 0
    print(f"Starting live paper trading: {args.symbol} {args.timeframe}")
    print(f"Initial cash: ${args.initial_cash:,.0f}")
    print(f"Poll interval: {args.interval_seconds}s")
    print()

    try:
        while True:
            state = runner.tick()
            tick_count += 1

            pos_str = f"{state.position_side} qty={state.position_quantity:.6f}" if state.position_side != "flat" else "flat"
            print(
                f"[{state.timestamp}] equity=${state.equity:,.0f} "
                f"pos={pos_str} signal={state.last_signal_action}({state.last_signal_reason}) "
                f"trades={state.trade_count}"
            )

            runner.save_state(args.state_file)

            if args.max_ticks > 0 and tick_count >= args.max_ticks:
                print(f"\nReached max ticks ({args.max_ticks}). Stopping.")
                break

            time.sleep(args.interval_seconds)

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        runner.save_state(args.state_file)
        print(f"\nFinal equity: ${state.equity:,.0f}")
        print(f"Total trades: {len(runner.trade_log)}")
        if runner.trade_log:
            total_pnl = sum(t.pnl for t in runner.trade_log)
            wins = sum(1 for t in runner.trade_log if t.pnl > 0)
            print(f"Win rate: {wins/len(runner.trade_log)*100:.1f}%")
            print(f"Total PnL: ${total_pnl:+,.0f}")


if __name__ == "__main__":
    main()
