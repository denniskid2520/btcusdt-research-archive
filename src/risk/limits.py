from __future__ import annotations

from dataclasses import dataclass

from adapters.base import OrderRequest, Position


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 0.90
    risk_per_trade_pct: float = 0.02
    max_open_positions: int = 1
    leverage: int = 1


def calculate_order_quantity(
    cash: float,
    market_price: float,
    limits: RiskLimits,
    stop_distance_pct: float = 0.0,
) -> float:
    """Calculate position size.

    If ``stop_distance_pct`` is provided (e.g. 0.05 for 5%), size is based on
    risking ``risk_per_trade_pct`` of cash at that stop distance.  Otherwise
    falls back to a simple capital-cap approach.
    """
    if cash <= 0 or market_price <= 0:
        return 0.0
    leverage = max(limits.leverage, 1)
    margin_cap = cash * limits.max_position_pct * leverage

    if stop_distance_pct > 0:
        # Risk-based: risk_amount / (price * stop_distance) = quantity
        risk_amount = cash * limits.risk_per_trade_pct
        notional = risk_amount / stop_distance_pct
    else:
        risk_budget = cash * limits.risk_per_trade_pct
        notional = risk_budget / 0.02

    notional = min(notional, margin_cap)
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
        leverage = max(limits.leverage, 1)
        margin = (order.quantity * market_price) / leverage
        return margin <= (cash * limits.max_position_pct)
    if order.side == "sell":
        return existing_position.side == "long"
    if order.side == "cover":
        return existing_position.side == "short"
    return False
