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
        leverage: int = 1,
        margin_mode: str = "isolated",
        contract_type: str = "linear",
    ) -> None:
        self._cash = initial_cash
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.fill_ratio = fill_ratio
        self.leverage = max(leverage, 1)
        self.margin_mode = margin_mode  # "isolated" or "cross"
        self.contract_type = contract_type  # "linear" or "inverse"
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

        if self.contract_type == "inverse":
            margin = filled_quantity / self.leverage
            fee = filled_quantity * self.fee_rate
        else:
            notional = fill_price * filled_quantity
            margin = notional / self.leverage
            fee = notional * self.fee_rate
        is_scale_in = order.metadata.get("scale_in", False)

        if order.side in {"buy", "short"} and position.is_open and not is_scale_in:
            # Scale-in: allow adding to same-direction positions
            if (order.side == "buy" and position.side == "long") or (
                order.side == "short" and position.side == "short"
            ):
                is_scale_in = True
            else:
                raise ValueError("PaperBroker: cannot open opposite position while one is open.")

        if order.side == "buy":
            if margin + fee > self._cash:
                return None
            self._cash -= margin + fee
            if is_scale_in and position.is_open and position.side == "long":
                # Scale-in: weighted average price, add quantity and margin
                new_qty = position.quantity + filled_quantity
                new_avg = (position.average_price * position.quantity + fill_price * filled_quantity) / new_qty
                new_margin = position.reserved_margin + margin
                self._positions[order.symbol] = PaperPosition(
                    symbol=order.symbol, side="long", quantity=new_qty,
                    average_price=new_avg, reserved_margin=new_margin,
                    stop_price=position.stop_price, target_price=position.target_price,
                    second_target_price=position.second_target_price,
                    entry_reason=position.entry_reason,
                )
            else:
                self._positions[order.symbol] = PaperPosition(
                    symbol=order.symbol, side="long", quantity=filled_quantity,
                    average_price=fill_price, reserved_margin=margin,
                    stop_price=order.metadata.get("stop_price"),
                    target_price=order.metadata.get("target_price"),
                    second_target_price=order.metadata.get("second_target_price"),
                    entry_reason=order.metadata.get("reason", ""),
                )
        elif order.side == "short":
            if margin + fee > self._cash:
                return None
            self._cash -= margin + fee
            if is_scale_in and position.is_open and position.side == "short":
                new_qty = position.quantity + filled_quantity
                new_avg = (position.average_price * position.quantity + fill_price * filled_quantity) / new_qty
                new_margin = position.reserved_margin + margin
                self._positions[order.symbol] = PaperPosition(
                    symbol=order.symbol, side="short", quantity=new_qty,
                    average_price=new_avg, reserved_margin=new_margin,
                    stop_price=position.stop_price, target_price=position.target_price,
                    second_target_price=position.second_target_price,
                    entry_reason=position.entry_reason,
                )
            else:
                self._positions[order.symbol] = PaperPosition(
                    symbol=order.symbol, side="short", quantity=filled_quantity,
                    average_price=fill_price, reserved_margin=margin,
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
            if self.contract_type == "inverse":
                # Inverse PnL (BTC) = qty * (exit - entry) / exit for longs
                pnl = (
                    exit_quantity * (fill_price - position.average_price) / fill_price
                    if position.side == "long"
                    else exit_quantity * (position.average_price - fill_price) / fill_price
                )
            else:
                pnl = (
                    (fill_price - position.average_price) * exit_quantity
                    if position.side == "long"
                    else (position.average_price - fill_price) * exit_quantity
                )
            self._cash += released_margin + pnl - fee
            remaining_quantity = position.quantity - exit_quantity
            remaining_margin = position.reserved_margin - released_margin
            if remaining_quantity <= 1e-12:
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
        if self.contract_type == "inverse":
            unrealized = (
                position.quantity * (market_price - position.average_price) / market_price
                if position.side == "long"
                else position.quantity * (position.average_price - market_price) / market_price
            )
        else:
            unrealized = (
                (market_price - position.average_price) * position.quantity
                if position.side == "long"
                else (position.average_price - market_price) * position.quantity
            )
        return self._cash + position.reserved_margin + unrealized

    def check_liquidation(self, symbol: str, market_price: float, timestamp: datetime) -> bool:
        """Check if position should be liquidated (unrealized loss >= margin)."""
        position = self._positions.get(symbol)
        if position is None or not position.is_open:
            return False
        if self.contract_type == "inverse":
            unrealized = (
                position.quantity * (market_price - position.average_price) / market_price
                if position.side == "long"
                else position.quantity * (position.average_price - market_price) / market_price
            )
        else:
            unrealized = (
                (market_price - position.average_price) * position.quantity
                if position.side == "long"
                else (position.average_price - market_price) * position.quantity
            )
        if unrealized <= -position.reserved_margin:
            # Liquidation: margin is lost entirely
            self._positions.pop(symbol, None)
            return True
        return False

    def deduct_cash(self, amount: float) -> float:
        """Deduct from cash (for profit harvesting). Returns actual amount deducted."""
        actual = min(amount, self._cash)
        self._cash -= actual
        return actual

    def add_cash(self, amount: float) -> None:
        """Add cash (for macro cycle BTC buying from USDT reserves)."""
        self._cash += amount

    def _apply_slippage(self, market_price: float, side: str) -> float:
        if side in {"buy", "cover"}:
            return market_price * (1 + self.slippage_rate)
        return market_price * (1 - self.slippage_rate)
