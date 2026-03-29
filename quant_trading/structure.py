from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean

from quant_trading.models import Candle


@dataclass(frozen=True)
class Pivot:
    index: int
    price: float
    kind: str


@dataclass(frozen=True)
class ChannelBoundary:
    slope: float
    intercept: float

    def value_at(self, index: int) -> float:
        return (self.slope * index) + self.intercept


@dataclass(frozen=True)
class ChannelStructure:
    kind: str
    support: ChannelBoundary
    resistance: ChannelBoundary
    width: float
    support_touches: int
    resistance_touches: int
    confidence: float
    breakout_target: float
    regime: str


def detect_pivots(candles: list[Candle], window: int = 2) -> list[Pivot]:
    pivots: list[Pivot] = []
    if len(candles) < (window * 2) + 1:
        return pivots

    for index in range(window, len(candles) - window):
        segment = candles[index - window : index + window + 1]
        high = candles[index].high
        low = candles[index].low
        if high == max(item.high for item in segment):
            pivots.append(Pivot(index=index, price=high, kind="high"))
        if low == min(item.low for item in segment):
            pivots.append(Pivot(index=index, price=low, kind="low"))
    return pivots


def detect_channel_structure(
    candles: list[Candle],
    lookback: int = 30,
    pivot_window: int = 2,
    min_touches: int = 2,
    tolerance_ratio: float = 0.015,
) -> ChannelStructure | None:
    if len(candles) < lookback:
        return None

    recent = candles[-lookback:]
    pivots = detect_pivots(recent, window=pivot_window)
    highs = [pivot for pivot in pivots if pivot.kind == "high"]
    lows = [pivot for pivot in pivots if pivot.kind == "low"]
    if len(highs) < min_touches or len(lows) < min_touches:
        return None

    resistance = _fit_boundary(highs)
    support = _fit_boundary(lows)
    if resistance is None or support is None:
        return None

    if resistance.slope >= 0 and support.slope >= 0:
        kind = "ascending_channel"
        regime = "bullish"
    elif resistance.slope <= 0 and support.slope <= 0:
        kind = "descending_channel"
        regime = "bearish"
    else:
        return None

    slope_gap = abs(resistance.slope - support.slope)
    avg_slope = (abs(resistance.slope) + abs(support.slope)) / 2 or 1.0
    if slope_gap / avg_slope > 0.8:
        return None

    last_index = lookback - 1
    resistance_value = resistance.value_at(last_index)
    support_value = support.value_at(last_index)
    width = resistance_value - support_value
    if width <= 0:
        return None

    support_touches = _count_touches(lows, support, width * tolerance_ratio)
    resistance_touches = _count_touches(highs, resistance, width * tolerance_ratio)
    if support_touches < min_touches or resistance_touches < min_touches:
        return None

    confidence = _calculate_confidence(
        support_touches=support_touches,
        resistance_touches=resistance_touches,
        slope_gap_ratio=slope_gap / avg_slope,
    )
    breakout_target = resistance_value + width if kind == "ascending_channel" else support_value - width

    return ChannelStructure(
        kind=kind,
        support=support,
        resistance=resistance,
        width=width,
        support_touches=support_touches,
        resistance_touches=resistance_touches,
        confidence=confidence,
        breakout_target=breakout_target,
        regime=regime,
    )


def current_channel_levels(
    channel: ChannelStructure,
    history_length: int,
) -> tuple[float, float]:
    relative_index = history_length - 1
    return (
        channel.support.value_at(relative_index),
        channel.resistance.value_at(relative_index),
    )


def estimate_market_regime(candles: list[Candle], lookback: int = 40) -> str:
    if len(candles) < max(lookback, 5):
        return "neutral"

    recent = candles[-lookback:]
    closes = [candle.close for candle in recent]
    slope = _linear_regression(range(len(closes)), closes)
    if slope is None:
        return "neutral"

    pivot_points = detect_pivots(recent, window=2)
    highs = [pivot.price for pivot in pivot_points if pivot.kind == "high"][-2:]
    lows = [pivot.price for pivot in pivot_points if pivot.kind == "low"][-2:]

    if slope > 0 and _is_rising(highs) and _is_rising(lows):
        return "bullish"
    if slope < 0 and _is_falling(highs) and _is_falling(lows):
        return "bearish"
    return "neutral"


def _fit_boundary(pivots: list[Pivot]) -> ChannelBoundary | None:
    x_values = [pivot.index for pivot in pivots]
    y_values = [pivot.price for pivot in pivots]
    slope = _linear_regression(x_values, y_values)
    if slope is None:
        return None
    intercept = mean(y_values) - (slope * mean(x_values))
    return ChannelBoundary(slope=slope, intercept=intercept)


def _linear_regression(x_values: list[int] | range, y_values: list[float]) -> float | None:
    x_list = list(x_values)
    if len(x_list) != len(y_values) or len(x_list) < 2:
        return None

    x_mean = mean(x_list)
    y_mean = mean(y_values)
    denominator = sum((x - x_mean) ** 2 for x in x_list)
    if denominator == 0:
        return None
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_list, y_values))
    return numerator / denominator


def _count_touches(pivots: list[Pivot], boundary: ChannelBoundary, tolerance: float) -> int:
    touches = 0
    for pivot in pivots:
        expected = boundary.value_at(pivot.index)
        if abs(pivot.price - expected) <= tolerance:
            touches += 1
    return touches


def _calculate_confidence(
    support_touches: int,
    resistance_touches: int,
    slope_gap_ratio: float,
) -> float:
    touch_score = min((support_touches + resistance_touches) / 8, 1.0)
    parallel_score = max(0.0, 1.0 - slope_gap_ratio)
    return round((touch_score * 0.6) + (parallel_score * 0.4), 3)


def _is_rising(values: list[float]) -> bool:
    return len(values) >= 2 and values[-1] > values[-2]


def _is_falling(values: list[float]) -> bool:
    return len(values) >= 2 and values[-1] < values[-2]
