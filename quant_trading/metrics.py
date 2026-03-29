from __future__ import annotations

import math

from quant_trading.models import Trade


def calculate_max_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0

    peak = equity_curve[0]
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak == 0:
            continue
        drawdown = (peak - equity) / peak
        max_drawdown = max(max_drawdown, drawdown)
    return max_drawdown * 100


def calculate_win_rate(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    winners = sum(1 for trade in trades if trade.pnl > 0)
    return (winners / len(trades)) * 100


def calculate_sharpe_ratio(equity_curve: list[float]) -> float:
    if len(equity_curve) < 3:
        return 0.0

    returns: list[float] = []
    for previous, current in zip(equity_curve, equity_curve[1:]):
        if previous == 0:
            continue
        returns.append((current - previous) / previous)

    if len(returns) < 2:
        return 0.0

    average_return = sum(returns) / len(returns)
    variance = sum((value - average_return) ** 2 for value in returns) / (len(returns) - 1)
    std_dev = math.sqrt(variance)
    if std_dev == 0:
        return 0.0

    return (average_return / std_dev) * math.sqrt(252)
