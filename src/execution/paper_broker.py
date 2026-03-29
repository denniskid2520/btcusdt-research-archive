from __future__ import annotations

from dataclasses import dataclass
from itertools import count

from adapters.base import BrokerAdapter, FillReport, OrderRequest, Position


@dataclass
class PaperPosition(Position):
    stop_price: float | None = None
    target_price: float | None = None
    second_target_price: float | None = None
    entry_reason: str = ""


class PaperBroker(BrokerAdapter):
    def __init__(
        self,
        initial_cash: float = 100_000.0,
        fee_rate: float = 0.001,
        slippage_rate: float = 0.0005,
        fill_ratio: float = 1.0,
    ) -> None:
        self._cash = initial_cash
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.fill_ratio = fill_ratio
        self._positions: dict[str, PaperPosition] = {}
        self._order_ids = count(1)

    def get_cash(self) -> float:
        return self._cash

    def get_position(self, symbol: str) -> Position:
        return self._positions.get(symbol, PaperPosition(symbol=symbol))

    def submit_order(self, order: OrderRequest, market_price: float) -> FillReport | None:
        if order.side == "hold" or order.quantity <= 0:
            return None

        position = self._positions.get(order.symbol, PaperPosition(symbol=order.symbol))
        fill_price = self._apply_slippage(market_price, order.side)
        filled_quantity = order.quantity * self.fill_ratio
        if filled_quantity <= 0:
            return None

        notional = fill_price * filled_quantity
        fee = notional * self.fee_rate
        if order.side in {"buy", "short"} and position.is_open:
            raise ValueError("PaperBroker supports one open position per symbol.")

        if order.side == "buy":
            if notional + fee > self._cash:
                return None
            self._cash -= notional + fee
            self._positions[order.symbol] = PaperPosition(
                symbol=order.symbol,
                side="long",
                quantity=filled_quantity,
                average_price=fill_price,
                reserved_margin=notional,
                stop_price=order.metadata.get("stop_price"),
                target_price=order.metadata.get("target_price"),
                second_target_price=order.metadata.get("second_target_price"),
                entry_reason=order.metadata.get("reason", ""),
            )
        elif order.side == "short":
            if notional + fee > self._cash:
                return None
            self._cash -= notional + fee
            self._positions[order.symbol] = PaperPosition(
                symbol=order.symbol,
                side="short",
                quantity=filled_quantity,
                average_price=fill_price,
                reserved_margin=notional,
                stop_price=order.metadata.get("stop_price"),
                target_price=order.metadata.get("target_price"),
                second_target_price=order.metadata.get("second_target_price"),
                entry_reason=order.metadata.get("reason", ""),
            )
        elif order.side in {"sell", "cover"}:
            if not position.is_open:
                return None
            if order.side == "sell" and position.side != "long":
                return None
            if order.side == "cover" and position.side != "short":
                return None

            exit_quantity = min(filled_quantity, position.quantity)
            released_margin = position.reserved_margin * (exit_quantity / position.quantity)
            pnl = (
                (fill_price - position.average_price) * exit_quantity
                if position.side == "long"
                else (position.average_price - fill_price) * exit_quantity
            )
            self._cash += released_margin + pnl - fee
            remaining_quantity = position.quantity - exit_quantity
            remaining_margin = position.reserved_margin - released_margin
            if remaining_quantity <= 0:
                self._positions.pop(order.symbol, None)
            else:
                self._positions[order.symbol] = PaperPosition(
                    symbol=position.symbol,
                    side=position.side,
                    quantity=remaining_quantity,
                    average_price=position.average_price,
                    reserved_margin=remaining_margin,
                    stop_price=position.stop_price,
                    target_price=position.target_price,
                    second_target_price=position.second_target_price,
                    entry_reason=position.entry_reason,
                )

        return FillReport(
            order_id=f"paper-{next(self._order_ids)}",
            symbol=order.symbol,
            side=order.side,
            quantity=filled_quantity,
            fill_price=fill_price,
            fee=fee,
            timestamp=order.timestamp,
        )

    def mark_to_market(self, symbol: str, market_price: float) -> float:
        position = self._positions.get(symbol)
        if position is None or not position.is_open:
            return self._cash
        unrealized = (
            (market_price - position.average_price) * position.quantity
            if position.side == "long"
            else (position.average_price - market_price) * position.quantity
        )
        return self._cash + position.reserved_margin + unrealized

    def _apply_slippage(self, market_price: float, side: str) -> float:
        if side in {"buy", "cover"}:
            return market_price * (1 + self.slippage_rate)
        return market_price * (1 - self.slippage_rate)
