"""Archived: 1h signal generation within 4h channel zones.

Tested in backtests: adds trades (26 → 85 raw, 32 filtered) but
the extra trades are low quality (28-41% WR vs 46% baseline).
Net effect: HURTS returns (-18% to +183% vs +260% baseline).

Root cause: 1h pattern detection (rejection wick, engulfing, higher low)
is too loose as a signal generator. The 4h rules' strict entry zone
requirement is what makes them work.

Preserved for future research. Potential improvements:
  - Use 1h for entry TIMING within a 4h signal window (not new signals)
  - Add volume confirmation to 1h patterns
  - Require 2+ patterns to agree before signaling
  - Use ML to learn which 1h patterns at which channel positions work

Pattern detection functions:
  _detect_1h_rejection_wick: Long lower wick, close in upper half
  _detect_1h_bullish_engulfing: Current body engulfs previous body
  _detect_1h_higher_low: N bars with ascending lows (or descending highs)
"""

from __future__ import annotations

from adapters.base import MarketBar


def detect_1h_rejection_wick(
    bars: list[MarketBar],
    min_wick_ratio: float = 0.4,
    direction: str = "long",
) -> MarketBar | None:
    """Detect rejection wick in recent bars.

    For longs: bullish rejection = long lower wick, close in upper half.
    For shorts: bearish rejection = long upper wick, close in lower half.
    """
    for bar in reversed(bars):
        bar_range = bar.high - bar.low
        if bar_range <= 0:
            continue
        if direction == "long":
            lower_wick = min(bar.open, bar.close) - bar.low
            if lower_wick / bar_range >= min_wick_ratio:
                return bar
        else:
            upper_wick = bar.high - max(bar.open, bar.close)
            if upper_wick / bar_range >= min_wick_ratio:
                return bar
    return None


def detect_1h_bullish_engulfing(
    bars: list[MarketBar],
    min_body_ratio: float = 0.5,
    direction: str = "long",
) -> MarketBar | None:
    """Detect engulfing pattern in last two bars."""
    if len(bars) < 2:
        return None
    prev, curr = bars[-2], bars[-1]
    curr_range = curr.high - curr.low
    if curr_range <= 0:
        return None

    if direction == "long":
        curr_body = curr.close - curr.open
        if curr_body <= 0 or curr_body / curr_range < min_body_ratio:
            return None
        prev_lo = min(prev.open, prev.close)
        prev_hi = max(prev.open, prev.close)
        if curr.open <= prev_lo and curr.close >= prev_hi:
            return curr
    else:
        curr_body = curr.open - curr.close
        if curr_body <= 0 or curr_body / curr_range < min_body_ratio:
            return None
        prev_lo = min(prev.open, prev.close)
        prev_hi = max(prev.open, prev.close)
        if curr.close <= prev_lo and curr.open >= prev_hi:
            return curr
    return None


def detect_1h_higher_low(
    bars: list[MarketBar],
    n_bars: int = 3,
    direction: str = "long",
) -> bool:
    """Detect higher-low (longs) or lower-high (shorts) sequence."""
    if len(bars) < n_bars:
        return False
    recent = bars[-n_bars:]
    if direction == "long":
        return all(recent[i].low > recent[i - 1].low for i in range(1, len(recent)))
    else:
        return all(recent[i].high < recent[i - 1].high for i in range(1, len(recent)))
