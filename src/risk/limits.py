from __future__ import annotations

from dataclasses import dataclass

from adapters.base import OrderRequest, Position


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 0.25
    risk_per_trade_pct: float = 0.02
    max_open_positions: int = 1


def calculate_order_quantity(cash: float, market_price: float, limits: RiskLimits) -> float:
    if cash <= 0 or market_price <= 0:
        return 0.0
    capital_cap = cash * limits.max_position_pct
    risk_budget = cash * limits.risk_per_trade_pct
    notional = min(capital_cap, risk_budget / 0.02)
    return max(notional / market_price, 0.0)


def allow_order(
    cash: float,
    order: OrderRequest,
    market_price: float,
    open_positions: int,
    limits: RiskLimits,
    existing_position: Position,
) -> bool:
    if order.side in {"buy", "short"}:
        if open_positions >= limits.max_open_positions or existing_position.is_open:
            return False
        return (order.quantity * market_price) <= (cash * limits.max_position_pct)
    if order.side == "sell":
        return existing_position.side == "long"
    if order.side == "cover":
        return existing_position.side == "short"
    return False
