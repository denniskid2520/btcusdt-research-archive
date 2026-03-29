from __future__ import annotations

from quant_trading.config import BacktestConfig
from quant_trading.metrics import (
    calculate_max_drawdown,
    calculate_sharpe_ratio,
    calculate_win_rate,
)
from quant_trading.models import BacktestResult, Candle, Position, Trade
from quant_trading.risk import calculate_position_size
from quant_trading.strategies.base import Strategy


class BacktestEngine:
    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    def run(self, candles: list[Candle], strategy: Strategy) -> tuple[BacktestResult, list[Trade]]:
        cash = self.config.initial_cash
        position = Position()
        trades: list[Trade] = []
        equity_curve: list[float] = [cash]
        entry_time = None

        for index in range(1, len(candles)):
            history = candles[: index + 1]
            current_candle = candles[index]
            signal = strategy.on_candle(history, position)

            if signal.action in {"buy", "short"} and not position.is_open:
                position, cash, entry_time = self._open_position(
                    signal=signal,
                    current_candle=current_candle,
                    cash=cash,
                    position=position,
                )

            elif signal.action in {"sell", "cover"} and position.is_open and entry_time is not None:
                trade, cash = self._close_position(
                    signal=signal,
                    current_candle=current_candle,
                    cash=cash,
                    position=position,
                    entry_time=entry_time,
                )
                trades.append(trade)
                position = Position()
                entry_time = None

            current_equity = self._mark_to_market_equity(cash, position, current_candle.close)
            equity_curve.append(current_equity)

        if position.is_open and entry_time is not None:
            final_candle = candles[-1]
            exit_action = "sell" if position.is_long else "cover"
            trade, cash = self._close_position(
                signal=type("SignalProxy", (), {"action": exit_action})(),
                current_candle=final_candle,
                cash=cash,
                position=position,
                entry_time=entry_time,
            )
            trades.append(trade)
            equity_curve[-1] = cash

        final_equity = equity_curve[-1]
        result = BacktestResult(
            initial_cash=self.config.initial_cash,
            final_equity=final_equity,
            total_return_pct=((final_equity - self.config.initial_cash) / self.config.initial_cash) * 100,
            max_drawdown_pct=calculate_max_drawdown(equity_curve),
            win_rate_pct=calculate_win_rate(trades),
            total_trades=len(trades),
            sharpe_ratio=calculate_sharpe_ratio(equity_curve),
        )
        return result, trades

    def _open_position(
        self,
        signal,
        current_candle: Candle,
        cash: float,
        position: Position,
    ) -> tuple[Position, float, object]:
        is_long_entry = signal.action == "buy"
        execution_price = current_candle.close * (
            1 + self.config.slippage_rate if is_long_entry else 1 - self.config.slippage_rate
        )
        quantity = calculate_position_size(
            cash=cash,
            price=execution_price,
            risk_per_trade=self.config.risk_per_trade,
            max_position_pct=self.config.max_position_pct,
        )
        margin = quantity * execution_price
        fee = margin * self.config.fee_rate
        total_required = margin + fee
        if quantity <= 0 or total_required > cash:
            return position, cash, None

        cash -= total_required
        return (
            Position(
                side="long" if is_long_entry else "short",
                quantity=quantity,
                entry_price=execution_price,
                stop_price=getattr(signal, "stop_price", None),
                target_price=getattr(signal, "target_price", None),
                margin=margin,
            ),
            cash,
            current_candle.timestamp,
        )

    def _close_position(
        self,
        signal,
        current_candle: Candle,
        cash: float,
        position: Position,
        entry_time,
    ) -> tuple[Trade, float]:
        is_long_exit = signal.action == "sell"
        execution_price = current_candle.close * (
            1 - self.config.slippage_rate if is_long_exit else 1 + self.config.slippage_rate
        )
        exit_value = position.quantity * execution_price
        exit_fee = exit_value * self.config.fee_rate
        gross_pnl = (
            (execution_price - position.entry_price) * position.quantity
            if position.is_long
            else (position.entry_price - execution_price) * position.quantity
        )
        realized_pnl = gross_pnl - exit_fee
        cash += position.margin + realized_pnl
        return_pct = (
            ((execution_price - position.entry_price) / position.entry_price) * 100
            if position.is_long
            else ((position.entry_price - execution_price) / position.entry_price) * 100
        )
        trade = Trade(
            side="long" if position.is_long else "short",
            entry_time=entry_time,
            exit_time=current_candle.timestamp,
            entry_price=position.entry_price,
            exit_price=execution_price,
            quantity=position.quantity,
            pnl=realized_pnl - (position.margin * self.config.fee_rate),
            return_pct=return_pct,
        )
        return trade, cash

    def _mark_to_market_equity(self, cash: float, position: Position, current_price: float) -> float:
        if not position.is_open:
            return cash

        unrealized_pnl = (
            (current_price - position.entry_price) * position.quantity
            if position.is_long
            else (position.entry_price - current_price) * position.quantity
        )
        return cash + position.margin + unrealized_pnl
