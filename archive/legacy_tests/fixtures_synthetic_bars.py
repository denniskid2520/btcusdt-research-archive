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


def noisy_descending_channel_bars() -> list[MarketBar]:
    """Descending-ish shape where pivot highs/lows are scattered — R² should be low.

    The key trick: pivot highs alternate between much-higher and lower values,
    pivot lows alternate between much-lower and higher values, so the linear
    fit through each set has poor R².
    """
    bars: list[MarketBar] = []
    # Base prices that produce scattered pivot highs and lows.
    # Pattern: valleys at indices 3,9,15,21,27 (lows scatter: 62k,59k,63k,58k,61k)
    #          peaks   at indices 6,12,18,24   (highs scatter: 71k,66k,70k,64k)
    base = [
        69000, 68000, 66000, 62000, 64000, 67000, 71000,  # 0-6  peak@6=71k, valley@3=62k
        68000, 65000, 59000, 61000, 63000, 66000, 64000,  # 7-13 peak@12=66k, valley@9=59k
        65000, 63000, 64000, 67000, 70000, 68000, 65000,  # 14-20 peak@18=70k, valley@15=63k
        58000, 60000, 62000, 64000, 63000, 62000, 61000,  # 21-27 peak@24=64k, valley@21=58k
        60500, 60300,                                       # 28-29
    ]
    for i, close in enumerate(base):
        bars.append(make_bar(i, close, high_pad=200, low_pad=200))
    return bars


def narrow_descending_channel_bars() -> list[MarketBar]:
    """Descending channel with very small width relative to price (~0.5%).

    At price ~65000, a width of ~350 is only 0.5% — this should be rejected
    by min_channel_width_pct=0.02 (2%).
    """
    closes = [
        65300, 65250, 65200, 65150, 65100, 65050, 65000, 64950, 64900, 64850,
        64800, 64750, 64850, 64900, 64800, 64750, 64700, 64650, 64600, 64550,
        64650, 64700, 64600, 64550, 64500, 64450, 64400, 64350, 64300, 64450,
    ]
    return [make_bar(index, close, high_pad=30, low_pad=30) for index, close in enumerate(closes)]


def descending_channel_support_bounce_long_bars() -> list[MarketBar]:
    """Descending channel where the last bar is near support.

    Same channel as rejection fixture, only the last bar is pushed down into the
    support zone (~60258-60582).  No impulse requirement for oscillation trades.
    """
    closes = [
        70000, 69300, 68600, 67900, 67200, 66500, 65800, 65100, 64400, 63700, 63000, 62300,
        62900, 63500, 64100, 63500, 62900, 62300, 61700, 61100, 61500, 62100, 62700, 62100,
        61500, 60900, 61300, 61900, 62500, 60400,
    ]
    return [make_bar(index, close) for index, close in enumerate(closes)]


def ascending_channel_resistance_rejection_short_bars() -> list[MarketBar]:
    """Ascending channel where the last bar is near resistance.

    Same channel as support-bounce fixture, only the last bar is pushed up into
    the resistance zone.  No impulse requirement for oscillation trades.
    """
    closes = [
        50000, 50600, 51200, 51800, 52400, 53000, 53600, 54200, 54800, 55400, 56000, 56600,
        56000, 55400, 56000, 56600, 57200, 56800, 56400, 57000, 57600, 58200, 57800, 57400,
        58000, 58700,
    ]
    return [make_bar(index, close) for index, close in enumerate(closes)]


def descending_channel_breakout_long_bars() -> list[MarketBar]:
    """Descending channel where the last bar breaks above resistance with bullish impulse."""
    closes = [
        70000, 69300, 68600, 67900, 67200, 66500, 65800, 65100, 64400, 63700, 63000, 62300,
        62900, 63500, 64100, 63500, 62900, 62300, 61700, 61100, 61500, 62100, 62700, 62100,
        61500, 60900, 61300, 61900, 62500, 64500,
    ]
    return [make_bar(index, close) for index, close in enumerate(closes)]


def ascending_channel_breakdown_short_bars() -> list[MarketBar]:
    """Ascending channel where the last bar breaks below support with bearish impulse."""
    closes = [
        50000, 50600, 51200, 51800, 52400, 53000, 53600, 54200, 54800, 55400, 56000, 56600,
        56000, 55400, 56000, 56600, 57200, 56800, 56400, 57000, 57600, 58200, 57800, 57400,
        58000, 55500,
    ]
    return [make_bar(index, close) for index, close in enumerate(closes)]


def wide_lookback_descending_channel_bars() -> list[MarketBar]:
    """48 bars where the first 24 form clear descending pivots but the last 24
    alone are too flat/noisy to detect a channel with pivot_window=2.

    A 48-bar lookback should detect a descending channel; a 24-bar lookback should NOT.
    The last bar sits near resistance → descending_channel_rejection short trigger.
    """
    # First half: clear descending channel with wide spread (~4000 gap between R and S)
    # Pivot highs: ~70000@5, ~68500@10, ~67000@15, ~65500@20 (slope ~ -300/bar)
    # Pivot lows:  ~66000@3, ~64500@8, ~63000@13, ~61500@18 (slope ~ -300/bar)
    first_half = [
        68000, 67500, 67000, 66000,  # 0-3 drop → pivot low @3
        67500, 70000,                  # 4-5 rally → pivot high @5
        68500, 66500, 64500,          # 6-8 drop → pivot low @8
        66500, 68500,                  # 9-10 rally → pivot high @10
        67000, 65500, 63000,          # 11-13 drop → pivot low @13
        64500, 67000,                  # 14-15 rally → pivot high @15
        65500, 63500, 61500,          # 16-18 drop → pivot low @18
        63000, 65500,                  # 19-20 rally → pivot high @20
        64000, 62500, 61000,          # 21-23 drop
    ]
    # Second half: strictly monotonic decrease → no pivot highs or lows with window=2
    # Ends near the resistance line of the descending channel
    second_half = [round(61000 - i * 30) for i in range(24)]
    closes = first_half + second_half
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
