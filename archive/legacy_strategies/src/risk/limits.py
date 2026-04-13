from __future__ import annotations

from dataclasses import dataclass

from adapters.base import OrderRequest, Position


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 0.90
    min_position_pct: float = 0.0  # 0 = no floor; >0 = minimum margin % per trade
    risk_per_trade_pct: float = 0.02
    max_open_positions: int = 1
    leverage: int = 1
    scale_in_max_adds: int = 0  # 0 = no scale-in, >0 = max additional entries
    scale_in_position_pct: float = 0.03  # margin % per scale-in add


def calculate_order_quantity(
    cash: float,
    market_price: float,
    limits: RiskLimits,
    stop_distance_pct: float = 0.0,
    confidence_multiplier: float = 1.0,
) -> float:
    """Calculate position size.

    If ``stop_distance_pct`` is provided (e.g. 0.05 for 5%), size is based on
    risking ``risk_per_trade_pct`` of cash at that stop distance.  Otherwise
    falls back to a simple capital-cap approach.

    ``confidence_multiplier`` scales the final quantity (e.g. 0.5 = half size
    when 1h timeframe doesn't confirm entry).
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

    # Apply floor and cap
    margin_floor = cash * limits.min_position_pct * leverage if limits.min_position_pct > 0 else 0.0
    notional = max(notional, margin_floor)
    notional = min(notional, margin_cap)
    quantity = max(notional / market_price, 0.0)
    return quantity * max(confidence_multiplier, 0.0)


def allow_order(
    cash: float,
    order: OrderRequest,
    market_price: float,
    open_positions: int,
    limits: RiskLimits,
    existing_position: Position,
    contract_type: str = "linear",
) -> bool:
    is_scale_in = order.metadata.get("scale_in", False)
    if order.side in {"buy", "short"}:
        if is_scale_in:
            # Scale-in: allow if same direction and margin fits
            same_dir = (order.side == "buy" and existing_position.side == "long") or \
                       (order.side == "short" and existing_position.side == "short")
            if not same_dir:
                return False
            leverage = max(limits.leverage, 1)
            if contract_type == "inverse":
                margin = order.quantity / leverage
            else:
                margin = (order.quantity * market_price) / leverage
            return margin <= (cash * limits.scale_in_position_pct * (cash + existing_position.reserved_margin))
        if open_positions >= limits.max_open_positions or existing_position.is_open:
            return False
        leverage = max(limits.leverage, 1)
        if contract_type == "inverse":
            margin = order.quantity / leverage
        else:
            margin = (order.quantity * market_price) / leverage
        return margin <= (cash * limits.max_position_pct)
    if order.side == "sell":
        return existing_position.side == "long"
    if order.side == "cover":
        return existing_position.side == "short"
    return False
