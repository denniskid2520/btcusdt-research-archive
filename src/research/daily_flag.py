"""Daily timeframe flag pattern detection.

Detects bull flags (descending channel in uptrend) and bear flags
(ascending channel in downtrend) on the daily chart. These patterns
last ~2 months (~60 daily bars) and are clearly visible on 4h→daily.

Entry: flag breakdown/breakout with failed retest.
Exit: MACD momentum guard (don't exit while momentum confirms).

Architecture:
  4h bars → aggregate to daily → detect channel → check breakdown/breakout
  Separate from 4h bounce/breakout rules (no shared channel).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from adapters.base import MarketBar
from research.macro_cycle import aggregate_to_daily


@dataclass(frozen=True)
class DailyFlagSignal:
    """Output of daily flag detection."""
    action: str            # "short" (bear flag break), "long" (bull flag break), "hold"
    flag_type: str         # "bear_flag", "bull_flag", "none"
    channel_slope: float   # slope of the channel (positive = rising/bear flag)
    support: float         # current channel lower boundary
    resistance: float      # current channel upper boundary
    confidence: float      # 0-1
    timestamp: datetime


# ── Pivot detection (daily-scale) ────────────────────────────────


@dataclass(frozen=True)
class _DailyPivot:
    index: int
    price: float
    kind: str  # "high" or "low"


def _find_daily_pivots(
    daily_bars: list[MarketBar],
    window: int = 3,
) -> list[_DailyPivot]:
    """Find pivot highs and lows on daily bars.

    A pivot high at index i: bar[i].high >= all highs in [i-window, i+window]
    A pivot low at index i: bar[i].low <= all lows in [i-window, i+window]
    """
    pivots: list[_DailyPivot] = []
    for i in range(window, len(daily_bars) - window):
        # Check pivot high
        is_high = all(
            daily_bars[i].high >= daily_bars[j].high
            for j in range(i - window, i + window + 1)
            if j != i
        )
        if is_high:
            pivots.append(_DailyPivot(index=i, price=daily_bars[i].high, kind="high"))

        # Check pivot low
        is_low = all(
            daily_bars[i].low <= daily_bars[j].low
            for j in range(i - window, i + window + 1)
            if j != i
        )
        if is_low:
            pivots.append(_DailyPivot(index=i, price=daily_bars[i].low, kind="low"))

    return pivots


# ── Linear regression (no numpy) ────────────────────────────────


def _linreg(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Simple linear regression. Returns (slope, intercept, r_squared)."""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0, 0.0
    sx = sum(xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxx = sum(x * x for x in xs)
    syy = sum(y * y for y in ys)

    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:
        return 0.0, sy / n if n > 0 else 0.0, 0.0

    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n

    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    ss_tot = syy - sy * sy / n
    r_sq = 1.0 - ss_res / ss_tot if abs(ss_tot) > 1e-12 else 0.0

    return slope, intercept, max(r_sq, 0.0)


# ── Channel detection on daily bars ─────────────────────────────


@dataclass(frozen=True)
class _DailyChannel:
    kind: str          # "ascending" or "descending"
    upper_slope: float
    upper_intercept: float
    lower_slope: float
    lower_intercept: float
    r_squared: float   # average R² of both trendlines
    n_highs: int
    n_lows: int


def _detect_daily_channel(
    daily_bars: list[MarketBar],
    pivot_window: int = 3,
    min_pivots: int = 3,
    min_r_squared: float = 0.3,
) -> _DailyChannel | None:
    """Detect channel on daily bars using pivot-based linear regression.

    Returns channel if both trendlines have enough pivots and fit quality.
    """
    pivots = _find_daily_pivots(daily_bars, window=pivot_window)

    highs = [p for p in pivots if p.kind == "high"]
    lows = [p for p in pivots if p.kind == "low"]

    if len(highs) < min_pivots or len(lows) < min_pivots:
        return None

    # Fit upper trendline to pivot highs
    hx = [float(p.index) for p in highs]
    hy = [p.price for p in highs]
    h_slope, h_intercept, h_r2 = _linreg(hx, hy)

    # Fit lower trendline to pivot lows
    lx = [float(p.index) for p in lows]
    ly = [p.price for p in lows]
    l_slope, l_intercept, l_r2 = _linreg(lx, ly)

    avg_r2 = (h_r2 + l_r2) / 2
    if avg_r2 < min_r_squared:
        return None

    # Both trendlines should slope in the same direction
    if (h_slope > 0) != (l_slope > 0):
        return None  # diverging slopes = not a clean channel

    avg_slope = (h_slope + l_slope) / 2
    kind = "ascending" if avg_slope > 0 else "descending"

    return _DailyChannel(
        kind=kind,
        upper_slope=h_slope,
        upper_intercept=h_intercept,
        lower_slope=l_slope,
        lower_intercept=l_intercept,
        r_squared=avg_r2,
        n_highs=len(highs),
        n_lows=len(lows),
    )


# ── Flag signal detection ────────────────────────────────────────


def detect_daily_flag(
    bars_4h: list[MarketBar],
    lookback_days: int = 60,
    pivot_window: int = 3,
    min_pivots: int = 3,
    min_r_squared: float = 0.3,
    parent_trend: str | None = None,
) -> DailyFlagSignal:
    """Detect bull/bear flag on daily timeframe.

    Bear flag: ascending (rising) daily channel. Price breaks below
    the lower trendline. In a descending parent trend, this is a
    bearish continuation → short.

    Bull flag: descending (falling) daily channel. Price breaks above
    the upper trendline. In an ascending parent trend, this is a
    bullish continuation → long.

    Args:
        bars_4h: Full 4h bar history.
        lookback_days: How many daily bars to analyze (default 60 = ~2 months).
        pivot_window: Bars on each side to confirm pivot (default 3).
        min_pivots: Minimum pivot highs AND lows needed (default 3).
        min_r_squared: Minimum average R² for channel quality.
        parent_trend: "ascending" or "descending" from parent context.
                      If None, flag type alone determines signal.

    Returns:
        DailyFlagSignal with action ("short", "long", or "hold").
    """
    daily = aggregate_to_daily(bars_4h)

    _hold = DailyFlagSignal(
        action="hold", flag_type="none", channel_slope=0.0,
        support=0.0, resistance=0.0, confidence=0.0,
        timestamp=daily[-1].timestamp if daily else datetime.min,
    )

    if len(daily) < lookback_days:
        return _hold

    recent = daily[-lookback_days:]
    channel = _detect_daily_channel(
        recent,
        pivot_window=pivot_window,
        min_pivots=min_pivots,
        min_r_squared=min_r_squared,
    )
    if channel is None:
        return _hold

    # Current trendline values at the last bar index
    last_idx = float(len(recent) - 1)
    upper = channel.upper_slope * last_idx + channel.upper_intercept
    lower = channel.lower_slope * last_idx + channel.lower_intercept
    current_price = recent[-1].close
    ts = recent[-1].timestamp

    # Channel width as % of price (sanity check)
    width_pct = (upper - lower) / current_price if current_price > 0 else 0
    if width_pct < 0.02 or width_pct > 0.50:
        return _hold  # too narrow or too wide

    # ── Bear flag: ascending channel + price broke below support ──
    # The breakdown itself is the confirmation signal — no parent gate.
    # When price breaks below a rising channel, the uptrend is over
    # regardless of what the (lagging) parent context says.
    if channel.kind == "ascending" and current_price < lower:
        return DailyFlagSignal(
            action="short",
            flag_type="bear_flag",
            channel_slope=channel.lower_slope,
            support=lower,
            resistance=upper,
            confidence=min(channel.r_squared, 0.95),
            timestamp=ts,
        )

    # ── Descending channel breakdown: trend acceleration → short ──
    # Price breaks below a descending channel = decline accelerating.
    # 12萬→9萬 pattern: descending channel forms, price breaks below.
    if channel.kind == "descending" and current_price < lower:
        return DailyFlagSignal(
            action="short",
            flag_type="channel_breakdown",
            channel_slope=channel.lower_slope,
            support=lower,
            resistance=upper,
            confidence=min(channel.r_squared, 0.95),
            timestamp=ts,
        )

    # ── Bull flag: descending channel + price broke above resistance ──
    if channel.kind == "descending" and current_price > upper:
        return DailyFlagSignal(
            action="long",
            flag_type="bull_flag",
            channel_slope=channel.upper_slope,
            support=lower,
            resistance=upper,
            confidence=min(channel.r_squared, 0.95),
            timestamp=ts,
        )

    # ── Ascending channel breakout: trend acceleration → long ──
    if channel.kind == "ascending" and current_price > upper:
        return DailyFlagSignal(
            action="long",
            flag_type="channel_breakout",
            channel_slope=channel.upper_slope,
            support=lower,
            resistance=upper,
            confidence=min(channel.r_squared, 0.95),
            timestamp=ts,
        )

    return _hold
