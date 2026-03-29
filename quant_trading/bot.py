from __future__ import annotations

import time
from dataclasses import dataclass

from quant_trading.binance import BinanceClient
from quant_trading.config import BacktestConfig, BinanceConfig, PaperTradingConfig
from quant_trading.models import Candle, Position, Signal, Trade
from quant_trading.risk import calculate_position_size
from quant_trading.strategies.base import Strategy


@dataclass(frozen=True)
class BotSnapshot:
    timestamp: str
    price: float
    action: str
    reason: str
    cash: float
    equity: float
    position_side: str
    position_qty: float
    stop_price: float | None
    target_price: float | None


class PaperTradingBot:
    def __init__(
        self,
        strategy: Strategy,
        backtest_config: BacktestConfig | None = None,
        binance_config: BinanceConfig | None = None,
        paper_config: PaperTradingConfig | None = None,
        client: BinanceClient | None = None,
    ) -> None:
        self.strategy = strategy
        self.backtest_config = backtest_config or BacktestConfig()
        self.binance_config = binance_config or BinanceConfig()
        self.paper_config = paper_config or PaperTradingConfig()
        self.client = client or BinanceClient(self.binance_config)
        self.cash = self.backtest_config.initial_cash
        self.position = Position()
        self.entry_time = None
        self.trades: list[Trade] = []

    def run_once(self) -> BotSnapshot:
        candles = self.client.get_klines(
            symbol=self.binance_config.symbol,
            interval=self.binance_config.interval,
            limit=self.binance_config.limit,
        )
        signal = self.strategy.on_candle(candles, self.position)
        current_candle = candles[-1]
        action = "hold"

        if signal.action in {"buy", "short"} and not self.position.is_open:
            opened = self._open_position(signal, current_candle)
            if opened:
                action = signal.action

        elif signal.action in {"sell", "cover"} and self.position.is_open and self.entry_time is not None:
            self._close_position(signal, current_candle)
            action = signal.action

        equity = self._current_equity(current_candle.close)
        return BotSnapshot(
            timestamp=current_candle.timestamp.isoformat(),
            price=current_candle.close,
            action=action,
            reason=signal.reason,
            cash=self.cash,
            equity=equity,
            position_side=self.position.side,
            position_qty=self.position.quantity,
            stop_price=self.position.stop_price,
            target_price=self.position.target_price,
        )

    def run_loop(self) -> list[BotSnapshot]:
        iterations = self.paper_config.max_iterations
        snapshots: list[BotSnapshot] = []
        count = 0

        while True:
            snapshots.append(self.run_once())
            count += 1
            if iterations and count >= iterations:
                break
            time.sleep(self.paper_config.poll_seconds)

        return snapshots

    def _open_position(self, signal: Signal, candle: Candle) -> bool:
        is_long = signal.action == "buy"
        execution_price = candle.close * (
            1 + self.backtest_config.slippage_rate if is_long else 1 - self.backtest_config.slippage_rate
        )
        quantity = calculate_position_size(
            cash=self.cash,
            price=execution_price,
            risk_per_trade=self.backtest_config.risk_per_trade,
            max_position_pct=self.backtest_config.max_position_pct,
        )
        margin = quantity * execution_price
        fee = margin * self.backtest_config.fee_rate
        if quantity <= 0 or margin + fee > self.cash:
            return False

        self.cash -= margin + fee
        self.position = Position(
            side="long" if is_long else "short",
            quantity=quantity,
            entry_price=execution_price,
            stop_price=signal.stop_price,
            target_price=signal.target_price,
            margin=margin,
        )
        self.entry_time = candle.timestamp
        return True

    def _close_position(self, signal: Signal, candle: Candle) -> None:
        is_long_exit = signal.action == "sell"
        execution_price = candle.close * (
            1 - self.backtest_config.slippage_rate if is_long_exit else 1 + self.backtest_config.slippage_rate
        )
        exit_value = self.position.quantity * execution_price
        exit_fee = exit_value * self.backtest_config.fee_rate
        gross_pnl = (
            (execution_price - self.position.entry_price) * self.position.quantity
            if self.position.is_long
            else (self.position.entry_price - execution_price) * self.position.quantity
        )
        realized_pnl = gross_pnl - exit_fee - (self.position.margin * self.backtest_config.fee_rate)
        self.cash += self.position.margin + realized_pnl
        self.trades.append(
            Trade(
                side="long" if self.position.is_long else "short",
                entry_time=self.entry_time,
                exit_time=candle.timestamp,
                entry_price=self.position.entry_price,
                exit_price=execution_price,
                quantity=self.position.quantity,
                pnl=realized_pnl,
                return_pct=(
                    ((execution_price - self.position.entry_price) / self.position.entry_price) * 100
                    if self.position.is_long
                    else ((self.position.entry_price - execution_price) / self.position.entry_price) * 100
                ),
            )
        )
        self.position = Position()
        self.entry_time = None

    def _current_equity(self, current_price: float) -> float:
        if not self.position.is_open:
            return self.cash
        unrealized = (
            (current_price - self.position.entry_price) * self.position.quantity
            if self.position.is_long
            else (self.position.entry_price - current_price) * self.position.quantity
        )
        return self.cash + self.position.margin + unrealized
