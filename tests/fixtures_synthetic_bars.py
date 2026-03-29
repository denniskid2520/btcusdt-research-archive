from __future__ import annotations

from datetime import datetime, timedelta

from adapters.base import MarketBar


def make_bar(index: int, close: float, high_pad: float = 80.0, low_pad: float = 80.0, volume: float | None = None) -> MarketBar:
    timestamp = datetime(2025, 1, 1) + timedelta(hours=index)
    return MarketBar(
        timestamp=timestamp,
        open=close - 40,
        high=close + high_pad,
        low=close - low_pad,
        close=close,
        volume=volume if volume is not None else 1000 + index,
    )


def ascending_channel_support_long_bars() -> list[MarketBar]:
    closes = [
        50000, 50600, 51200, 51800, 52400, 53000, 53600, 54200, 54800, 55400, 56000, 56600,
        56000, 55400, 56000, 56600, 57200, 56800, 56400, 57000, 57600, 58200, 57800, 57400,
        58000, 57750,
    ]
    return [make_bar(index, close) for index, close in enumerate(closes)]


def ascending_channel_breakout_long_bars() -> list[MarketBar]:
    closes = [
        50000, 50600, 51200, 51800, 52400, 53000, 53600, 54200, 54800, 55400, 56000, 56600,
        56000, 55400, 56000, 56600, 57200, 56800, 56400, 57000, 57600, 58200, 57800, 57400,
        58000, 59250,
    ]
    return [make_bar(index, close) for index, close in enumerate(closes)]


def descending_channel_rejection_short_bars() -> list[MarketBar]:
    closes = [
        70000, 69300, 68600, 67900, 67200, 66500, 65800, 65100, 64400, 63700, 63000, 62300,
        62900, 63500, 64100, 63500, 62900, 62300, 61700, 61100, 61500, 62100, 62700, 62100,
        61500, 60900, 61300, 61900, 62500, 61300,
    ]
    return [make_bar(index, close) for index, close in enumerate(closes)]


def descending_channel_breakdown_short_bars() -> list[MarketBar]:
    closes = [
        70000, 69300, 68600, 67900, 67200, 66500, 65800, 65100, 64400, 63700, 63000, 62300,
        62900, 63500, 64100, 63500, 62900, 62300, 61700, 61100, 61500, 62100, 62700, 62100,
        61500, 60900, 61300, 61900, 62500, 59500,
    ]
    return [make_bar(index, close) for index, close in enumerate(closes)]


def rising_channel_retest_short_bars() -> list[MarketBar]:
    closes = [
        70000, 69100, 68200, 67300, 66400, 65500, 64600, 63700, 62800, 61900, 61000, 60100,
        60600, 61200, 61800, 62400, 62000, 61600, 62200, 62800, 63400, 63000, 62600, 63200,
        63800, 63550,
    ]
    return [make_bar(index, close) for index, close in enumerate(closes)]


def rising_channel_continuation_short_bars() -> list[MarketBar]:
    closes = [
        70000, 69100, 68200, 67300, 66400, 65500, 64600, 63700, 62800, 61900, 61000, 60100,
        60600, 61200, 61800, 62400, 62000, 61600, 62200, 62800, 63400, 63000, 62600, 63200,
        63800, 62900,
    ]
    return [make_bar(index, close) for index, close in enumerate(closes)]


def realistic_comparison_dataset_bars() -> list[MarketBar]:
    segments = [
        descending_channel_breakdown_short_bars(),
        rising_channel_retest_short_bars(),
        rising_channel_continuation_short_bars(),
        descending_channel_rejection_short_bars(),
    ]
    closes: list[float] = [bar.close for bar in segments[0]]
    for segment in segments[1:]:
        seg_closes = [bar.close for bar in segment]
        bridge_step = (closes[-1] - 350.0 - seg_closes[0]) / 4
        bridge_start = closes[-1]
        for i in range(1, 5):
            closes.append(bridge_start - (bridge_step * i))
        offset = closes[-1] - seg_closes[0]
        closes.extend((value + offset) for value in seg_closes)
    return [make_bar(index, close) for index, close in enumerate(closes)]
