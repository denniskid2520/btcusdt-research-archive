from __future__ import annotations


def calculate_position_size(
    cash: float,
    price: float,
    risk_per_trade: float,
    max_position_pct: float,
) -> float:
    if cash <= 0 or price <= 0:
        return 0.0

    risk_budget = cash * risk_per_trade
    capital_cap = cash * max_position_pct
    allocation = min(risk_budget / 0.02, capital_cap)
    return max(allocation / price, 0.0)
