"""Macro cycle detection: bull market tops and bear market bottoms.

Two-layer sell mechanism:

  Layer 1 — D+W RSI sell (D>=75 + W>=70, monthly guard):
    Daily RSI >= 75 AND Weekly RSI >= 70: sell 20% of BTC
    Monthly RSI guard: only sell when M-RSI >= 65 (confirmed hot market)
    NEVER sell below min_btc_reserve (1 BTC)
    Wait for low point to buy back with USDT reserves.

  Layer 2 — Weekly RSI divergence (structural weakness):
    Bearish divergence: price higher high + RSI lower high → sell
    Bullish divergence: price lower low + RSI higher low → buy
    Severity scales the sell/buy percentage.
    Catches weakening momentum that absolute thresholds miss.

Fallback (when insufficient peaks for divergence analysis):
  Extreme RSI + Mayer Multiple thresholds (very strict) → signal

Integration with inverse (coin-margined) backtest:
  - Channel trading is the CORE profit engine
  - Macro cycle overlay makes the core more efficient by selling high, buying low
  - At tops: sell BTC → accumulate USDT reserves
  - At bottoms: spend USDT → buy BTC back at discount

References:
  - RSI divergence: classical technical analysis (Murphy, Edwards & Magee)
  - Mayer Multiple (price/200dMA): well-established BTC cycle indicator
  - Monthly/Weekly RSI: macro overbought/oversold identification
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from adapters.base import MarketBar


@dataclass
class MacroCycleConfig:
    """Configuration for macro cycle detection and position management."""

    weekly_rsi_period: int = 14

    # ── Divergence detection (primary method) ──
    divergence_pivot_window: int = 4    # Weekly bars to confirm peak/trough
    divergence_min_rsi_drop: float = 5.0  # Min RSI difference for divergence

    # ── Divergence-scaled selling ──
    sell_pct_per_rsi_point: float = 0.01  # 1% per RSI point of divergence
    sell_pct_min: float = 0.10            # floor 10%
    sell_pct_max: float = 0.40            # cap 40%

    # ── Divergence-scaled buying (bear bottom) ──
    buy_pct_per_rsi_point: float = 0.02   # 2% per RSI point of divergence
    buy_pct_min: float = 0.20            # floor 20%
    buy_pct_max: float = 0.60            # cap 60%

    # ── Monthly RSI progressive selling (Layer 1) ──
    monthly_rsi_sell_start: float = 70.0   # First sell when monthly RSI >= 70
    monthly_rsi_sell_step: float = 7.0     # Sell again every +7 RSI above start
    monthly_rsi_sell_pct: float = 0.10     # Base sell pct; actual = level * base
    min_btc_reserve: float = 1.0           # NEVER sell below this (initial capital)

    # ── Weekly RSI bottom buying ──
    weekly_rsi_buy_trigger: float = 25.0   # Buy when weekly RSI <= 25
    weekly_rsi_buy_pct: float = 0.40       # Spend 40% of USDT reserves per trigger

    # ── Monthly RSI (legacy, used for divergence guard) ──
    monthly_rsi_buy_trigger: float = 30.0  # Legacy: keep for guard function
    monthly_rsi_buy_pct: float = 0.40      # Legacy

    # ── Daily+Weekly RSI dual-condition sell ──
    daily_rsi_sell_trigger: float = 75.0   # Daily RSI >= 75 required
    weekly_rsi_sell_confirm: float = 70.0  # Weekly RSI >= 70 required (confirms trend)
    daily_rsi_sell_pct: float = 0.20       # 20% of current BTC holdings
    dw_sell_min_monthly_rsi: float = 65.0  # Guard: block sell if monthly RSI < 65

    # ── Daily+Weekly RSI dual-condition buy ──
    daily_rsi_buy_trigger: float = 27.0    # Daily RSI < 27 required
    weekly_rsi_buy_confirm: float = 47.0   # Weekly RSI < 47 required (confirms bear)
    daily_rsi_buy_pct: float = 0.20        # Spend 20% of USDT reserves
    dw_buy_bounce_pct: float = 0.05        # Bottom confirm: buy when price bounces 5% from low

    # ── Divergence guard: only sell at divergence if market is hot ──
    divergence_sell_min_monthly_rsi: float = 65.0  # Block false tops when RSI below hot zone
    divergence_buy_max_monthly_rsi: float = 40.0   # Block false bottoms in rally

    # ── Cooldown ──
    cooldown_bars_4h: int = 168           # 4 weeks between macro actions

    # ── Fallback thresholds (when too few peaks for divergence) ──
    # With Coinglass confirmation
    weekly_rsi_overbought: float = 85.0
    weekly_rsi_oversold: float = 28.0
    sma200_hot_ratio: float = 1.50
    sma200_cold_ratio: float = 0.70
    funding_hot: float = 0.001
    funding_cold: float = 0.0
    ls_hot: float = 1.05
    ls_cold: float = 0.95
    # Without Coinglass (strict)
    fallback_rsi_overbought: float = 92.0
    fallback_rsi_oversold: float = 22.0
    fallback_sma200_hot: float = 1.60
    fallback_sma200_cold: float = 0.60
    # Legacy fields (backward compat)
    sell_drawdown_pct: float = 0.12
    buy_bounce_pct: float = 0.12
    sell_pct: float = 0.25
    buy_pct: float = 0.60


@dataclass(frozen=True)
class MacroCycleSignal:
    """Output of macro cycle detection for a single evaluation."""
    action: str             # "sell_top", "buy_bottom", "neutral"
    weekly_rsi: float | None
    sma200_ratio: float | None
    funding_rate: float | None
    top_ls_ratio: float | None
    timestamp: datetime
    divergence_score: float = 0.0  # RSI points of divergence
    sell_pct: float = 0.0          # Recommended sell % for sell_top (0-1)
    buy_pct: float = 0.0           # Recommended buy % for buy_bottom (0-1)
    peak_count: int = 0            # Total confirmed peaks
    trough_count: int = 0          # Total confirmed troughs


@dataclass(frozen=True)
class MacroCycleRecord:
    """Record of a macro cycle buy/sell event for reporting."""
    timestamp: datetime
    action: str             # "sell_top" or "buy_bottom"
    btc_price: float
    weekly_rsi: float
    sma200_ratio: float
    funding_rate: float | None
    top_ls_ratio: float | None
    btc_amount: float       # BTC sold or bought
    usdt_amount: float      # USDT gained or spent
    btc_balance_after: float
    usdt_balance_after: float
    divergence_score: float = 0.0


# ── Bar aggregation ───────────────────────────────────────────────


def aggregate_to_weekly(bars_4h: list[MarketBar]) -> list[MarketBar]:
    """Aggregate 4h bars into weekly bars (grouped by ISO week)."""
    if not bars_4h:
        return []

    weeks: dict[tuple[int, int], list[MarketBar]] = {}
    order: list[tuple[int, int]] = []
    for bar in bars_4h:
        iso = bar.timestamp.isocalendar()
        key = (iso[0], iso[1])  # (year, week_number)
        if key not in weeks:
            weeks[key] = []
            order.append(key)
        weeks[key].append(bar)

    result: list[MarketBar] = []
    for key in order:
        group = weeks[key]
        result.append(MarketBar(
            timestamp=group[-1].timestamp,
            open=group[0].open,
            high=max(b.high for b in group),
            low=min(b.low for b in group),
            close=group[-1].close,
            volume=sum(b.volume for b in group),
        ))
    return result


def aggregate_to_daily(bars_4h: list[MarketBar]) -> list[MarketBar]:
    """Aggregate 4h bars into daily bars (grouped by date)."""
    if not bars_4h:
        return []

    days: dict[object, list[MarketBar]] = {}
    order: list[object] = []
    for bar in bars_4h:
        key = bar.timestamp.date()
        if key not in days:
            days[key] = []
            order.append(key)
        days[key].append(bar)

    result: list[MarketBar] = []
    for key in order:
        group = days[key]
        result.append(MarketBar(
            timestamp=group[-1].timestamp,
            open=group[0].open,
            high=max(b.high for b in group),
            low=min(b.low for b in group),
            close=group[-1].close,
            volume=sum(b.volume for b in group),
        ))
    return result


def aggregate_to_monthly(bars_4h: list[MarketBar]) -> list[MarketBar]:
    """Aggregate 4h bars into monthly bars (grouped by year-month)."""
    if not bars_4h:
        return []

    months: dict[tuple[int, int], list[MarketBar]] = {}
    order: list[tuple[int, int]] = []
    for bar in bars_4h:
        key = (bar.timestamp.year, bar.timestamp.month)
        if key not in months:
            months[key] = []
            order.append(key)
        months[key].append(bar)

    result: list[MarketBar] = []
    for key in order:
        group = months[key]
        result.append(MarketBar(
            timestamp=group[-1].timestamp,
            open=group[0].open,
            high=max(b.high for b in group),
            low=min(b.low for b in group),
            close=group[-1].close,
            volume=sum(b.volume for b in group),
        ))
    return result


# ── Indicator computation ─────────────────────────────────────────


def compute_weekly_rsi(
    weekly_bars: list[MarketBar],
    period: int = 14,
) -> float | None:
    """RSI using Wilder's smoothing over ALL bars. Returns 0-100 or None.

    Uses full history: first *period* changes as SMA seed, then Wilder's
    EMA for every subsequent change. This gives stable, path-dependent
    readings that match charting platforms (TradingView, Binance, etc.).
    """
    needed = period + 1
    if len(weekly_bars) < needed:
        return None

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(weekly_bars)):
        delta = weekly_bars[i].close - weekly_bars[i - 1].close
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    if not gains:
        return None

    # Seed: SMA of first *period* changes
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Wilder's EMA for all subsequent changes
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _ema(values: list[float], period: int) -> list[float]:
    """Exponential Moving Average. Returns list same length as input.

    First *period* values use SMA as seed, then standard EMA.
    """
    if len(values) < period:
        return []
    result: list[float] = []
    sma = sum(values[:period]) / period
    result.extend([0.0] * (period - 1))
    result.append(sma)
    k = 2.0 / (period + 1)
    for i in range(period, len(values)):
        sma = values[i] * k + result[-1] * (1 - k)
        result.append(sma)
    return result


def compute_macd(
    daily_bars: list[MarketBar],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[float | None, float | None, float | None]:
    """MACD on daily bars. Returns (macd_line, signal_line, histogram).

    Standard MACD(12,26,9):
      macd_line = EMA(12) - EMA(26)
      signal_line = EMA(9) of macd_line
      histogram = macd_line - signal_line

    Returns (None, None, None) if insufficient data.
    """
    min_bars = slow + signal_period
    if len(daily_bars) < min_bars:
        return None, None, None

    closes = [b.close for b in daily_bars]
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    if not ema_fast or not ema_slow:
        return None, None, None

    # MACD line starts where both EMAs are valid (from index slow-1)
    macd_values: list[float] = []
    start = slow - 1
    for i in range(start, len(closes)):
        macd_values.append(ema_fast[i] - ema_slow[i])

    if len(macd_values) < signal_period:
        return None, None, None

    signal_values = _ema(macd_values, signal_period)
    if not signal_values:
        return None, None, None

    macd_line = macd_values[-1]
    signal_line = signal_values[-1]
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def macd_momentum_hold(
    daily_bars: list[MarketBar],
    position_side: str,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
    lookback: int = 3,
) -> bool:
    """Check if daily MACD confirms impulse momentum — should hold position.

    Used to detect the "profit window" of large impulse moves.
    Daily timeframe only — not for smaller timeframes.

    Bear momentum (hold shorts):
      MACD 在正值死叉 → 跌破零軸 → 快線加速放大
      = MACD line < 0 AND still declining (not recovering yet)
    Bull momentum (hold longs):
      MACD 在負值金叉 → 突破零軸 → 快線加速放大
      = MACD line > 0 AND still rising (not fading yet)

    Checks that MACD line is STILL expanding compared to *lookback* bars ago.
    """
    min_bars = slow + signal_period + lookback + 1
    if len(daily_bars) < min_bars:
        return False

    closes = [b.close for b in daily_bars]
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    if not ema_fast or not ema_slow:
        return False

    start = slow - 1
    macd_values: list[float] = []
    for i in range(start, len(closes)):
        macd_values.append(ema_fast[i] - ema_slow[i])

    if len(macd_values) < lookback + 1:
        return False

    macd_now = macd_values[-1]
    macd_prev = macd_values[-1 - lookback]

    # MACD must be consistently on the same side for the full lookback
    # period — filters out random noise in flat markets.
    recent_macd = macd_values[-lookback - 1 :]

    if position_side == "short":
        # Bear: all recent MACD negative AND still declining
        return all(v < 0 for v in recent_macd) and macd_now < macd_prev
    elif position_side == "long":
        # Bull: all recent MACD positive AND still rising
        return all(v > 0 for v in recent_macd) and macd_now > macd_prev
    return False


def compute_sma200_ratio(daily_bars: list[MarketBar]) -> float | None:
    """Price / SMA(200) ratio (a.k.a. Mayer Multiple).

    > 1.0 = above average, < 1.0 = below.
    Historically BTC bull tops reach 2.0-2.4, bear bottoms reach 0.5-0.7.
    """
    if len(daily_bars) < 200:
        return None
    sma = sum(b.close for b in daily_bars[-200:]) / 200
    if sma == 0:
        return None
    return daily_bars[-1].close / sma


# ── Monthly RSI progressive selling ──────────────────────────────


def check_monthly_rsi_sell(
    bars_4h: list[MarketBar],
    config: MacroCycleConfig,
    last_sold_level: int,
) -> tuple[bool, int, float]:
    """Check if a new monthly RSI sell level has been reached.

    Monthly RSI progressive selling:
      Level 1 = RSI >= 70 (sell_start)
      Level 2 = RSI >= 77 (+7)
      Level 3 = RSI >= 84 (+14)
      ...

    Each level triggers once. Returns (should_sell, new_level, monthly_rsi).
    """
    monthly = aggregate_to_monthly(bars_4h)
    if len(monthly) < config.weekly_rsi_period + 1:
        return False, last_sold_level, 0.0

    rsi = compute_weekly_rsi(monthly, config.weekly_rsi_period)
    if rsi is None:
        return False, last_sold_level, 0.0

    if rsi < config.monthly_rsi_sell_start:
        return False, last_sold_level, rsi

    # Current RSI level: 1 + how many full steps above start
    current_level = 1 + int(
        (rsi - config.monthly_rsi_sell_start) / config.monthly_rsi_sell_step,
    )

    if current_level > last_sold_level:
        return True, current_level, rsi

    return False, last_sold_level, rsi


def check_monthly_rsi_buy(
    bars_4h: list[MarketBar],
    config: MacroCycleConfig,
) -> tuple[bool, float]:
    """Check if monthly RSI is low enough to trigger bear bottom buy.

    Returns (should_buy, monthly_rsi).
    """
    monthly = aggregate_to_monthly(bars_4h)
    if len(monthly) < config.weekly_rsi_period + 1:
        return False, 0.0

    rsi = compute_weekly_rsi(monthly, config.weekly_rsi_period)
    if rsi is None:
        return False, 0.0

    return rsi <= config.monthly_rsi_buy_trigger, rsi


def check_weekly_rsi_buy(
    bars_4h: list[MarketBar],
    config: MacroCycleConfig,
) -> tuple[bool, float]:
    """Check if weekly RSI is low enough to trigger bear bottom buy.

    Weekly RSI <= 25 is a strong oversold signal for BTC accumulation.
    Returns (should_buy, weekly_rsi).
    """
    weekly = aggregate_to_weekly(bars_4h)
    if len(weekly) < config.weekly_rsi_period + 1:
        return False, 0.0

    rsi = compute_weekly_rsi(weekly, config.weekly_rsi_period)
    if rsi is None:
        return False, 0.0

    return rsi <= config.weekly_rsi_buy_trigger, rsi


def check_daily_rsi_sell(
    bars_4h: list[MarketBar],
    config: MacroCycleConfig,
) -> tuple[bool, float, float]:
    """Check dual-condition sell: daily RSI >= 75 AND weekly RSI >= 70.

    Both conditions must be met simultaneously:
      - Daily RSI >= 75: short-term overbought (price stretched)
      - Weekly RSI >= 70: medium-term trend confirmed hot

    Note: caller should also guard with monthly RSI >= dw_sell_min_monthly_rsi
    to avoid selling too early in a bull cycle.

    Returns (should_sell, daily_rsi, weekly_rsi).
    """
    daily = aggregate_to_daily(bars_4h)
    weekly = aggregate_to_weekly(bars_4h)

    if len(daily) < config.weekly_rsi_period + 1:
        return False, 0.0, 0.0
    if len(weekly) < config.weekly_rsi_period + 1:
        return False, 0.0, 0.0

    d_rsi = compute_weekly_rsi(daily, config.weekly_rsi_period)
    w_rsi = compute_weekly_rsi(weekly, config.weekly_rsi_period)

    if d_rsi is None or w_rsi is None:
        return False, 0.0, 0.0

    triggered = d_rsi >= config.daily_rsi_sell_trigger and w_rsi >= config.weekly_rsi_sell_confirm
    return triggered, d_rsi, w_rsi


def check_daily_rsi_buy(
    bars_4h: list[MarketBar],
    config: MacroCycleConfig,
) -> tuple[bool, float, float]:
    """Check dual-condition buy: daily RSI < 27 AND weekly RSI < 47.

    Both conditions must be met simultaneously:
      - Daily RSI < 27: short-term deeply oversold
      - Weekly RSI < 47: medium-term trend confirms bear market

    Prevents false buys on brief dips when weekly trend is still bullish.

    Returns (should_buy, daily_rsi, weekly_rsi).
    """
    daily = aggregate_to_daily(bars_4h)
    weekly = aggregate_to_weekly(bars_4h)

    if len(daily) < config.weekly_rsi_period + 1:
        return False, 0.0, 0.0
    if len(weekly) < config.weekly_rsi_period + 1:
        return False, 0.0, 0.0

    d_rsi = compute_weekly_rsi(daily, config.weekly_rsi_period)
    w_rsi = compute_weekly_rsi(weekly, config.weekly_rsi_period)

    if d_rsi is None or w_rsi is None:
        return False, 0.0, 0.0

    triggered = d_rsi < config.daily_rsi_buy_trigger and w_rsi < config.weekly_rsi_buy_confirm
    return triggered, d_rsi, w_rsi


def get_monthly_rsi(
    bars_4h: list[MarketBar],
    config: MacroCycleConfig,
) -> float:
    """Get current monthly RSI value (for divergence guard).

    Returns 50.0 (neutral) when insufficient data.
    """
    monthly = aggregate_to_monthly(bars_4h)
    if len(monthly) < config.weekly_rsi_period + 1:
        return 50.0

    rsi = compute_weekly_rsi(monthly, config.weekly_rsi_period)
    return rsi if rsi is not None else 50.0


# ── Native bar support (use Binance 1d/1w directly) ────────────


def aggregate_daily_to_monthly(daily_bars: list[MarketBar]) -> list[MarketBar]:
    """Aggregate native daily bars into monthly bars (grouped by year-month)."""
    if not daily_bars:
        return []

    months: dict[tuple[int, int], list[MarketBar]] = {}
    order: list[tuple[int, int]] = []
    for bar in daily_bars:
        key = (bar.timestamp.year, bar.timestamp.month)
        if key not in months:
            months[key] = []
            order.append(key)
        months[key].append(bar)

    result: list[MarketBar] = []
    for key in order:
        group = months[key]
        result.append(MarketBar(
            timestamp=group[-1].timestamp,
            open=group[0].open,
            high=max(b.high for b in group),
            low=min(b.low for b in group),
            close=group[-1].close,
            volume=sum(b.volume for b in group),
        ))
    return result


def check_daily_rsi_sell_native(
    daily_bars: list[MarketBar],
    weekly_bars: list[MarketBar],
    config: MacroCycleConfig,
) -> tuple[bool, float, float]:
    """D+W sell using native Binance daily+weekly bars (no 4h aggregation).

    Same logic as check_daily_rsi_sell but skips the aggregation step.
    Use when native 1d/1w candles are available for higher accuracy.
    """
    if len(daily_bars) < config.weekly_rsi_period + 1:
        return False, 0.0, 0.0
    if len(weekly_bars) < config.weekly_rsi_period + 1:
        return False, 0.0, 0.0

    d_rsi = compute_weekly_rsi(daily_bars, config.weekly_rsi_period)
    w_rsi = compute_weekly_rsi(weekly_bars, config.weekly_rsi_period)

    if d_rsi is None or w_rsi is None:
        return False, 0.0, 0.0

    triggered = (
        d_rsi >= config.daily_rsi_sell_trigger
        and w_rsi >= config.weekly_rsi_sell_confirm
    )
    return triggered, d_rsi, w_rsi


def check_daily_rsi_buy_native(
    daily_bars: list[MarketBar],
    weekly_bars: list[MarketBar],
    config: MacroCycleConfig,
) -> tuple[bool, float, float]:
    """D+W buy using native Binance daily+weekly bars (no 4h aggregation)."""
    if len(daily_bars) < config.weekly_rsi_period + 1:
        return False, 0.0, 0.0
    if len(weekly_bars) < config.weekly_rsi_period + 1:
        return False, 0.0, 0.0

    d_rsi = compute_weekly_rsi(daily_bars, config.weekly_rsi_period)
    w_rsi = compute_weekly_rsi(weekly_bars, config.weekly_rsi_period)

    if d_rsi is None or w_rsi is None:
        return False, 0.0, 0.0

    triggered = (
        d_rsi < config.daily_rsi_buy_trigger
        and w_rsi < config.weekly_rsi_buy_confirm
    )
    return triggered, d_rsi, w_rsi


def check_weekly_rsi_buy_native(
    weekly_bars: list[MarketBar],
    config: MacroCycleConfig,
) -> tuple[bool, float]:
    """Weekly RSI buy using native Binance weekly bars."""
    if len(weekly_bars) < config.weekly_rsi_period + 1:
        return False, 0.0

    rsi = compute_weekly_rsi(weekly_bars, config.weekly_rsi_period)
    if rsi is None:
        return False, 0.0

    return rsi <= config.weekly_rsi_buy_trigger, rsi


def get_monthly_rsi_native(
    daily_bars: list[MarketBar],
    config: MacroCycleConfig,
) -> float:
    """Monthly RSI from native daily bars (aggregate daily -> monthly -> RSI).

    More accurate than 4h->monthly because daily OHLC from Binance is
    the actual exchange-reported candle, not re-aggregated from sub-bars.
    """
    monthly = aggregate_daily_to_monthly(daily_bars)
    if len(monthly) < config.weekly_rsi_period + 1:
        return 50.0

    rsi = compute_weekly_rsi(monthly, config.weekly_rsi_period)
    return rsi if rsi is not None else 50.0


# ── Peak / trough detection ──────────────────────────────────────


def find_weekly_peaks(
    weekly_bars: list[MarketBar],
    pivot_window: int = 4,
) -> list[int]:
    """Find confirmed weekly price peaks (local maxima).

    A peak at index i is confirmed when bar[i].high is the highest
    among all bars within [i - pivot_window, i + pivot_window].
    Requires pivot_window bars after the peak for confirmation.
    """
    peaks: list[int] = []
    for i in range(pivot_window, len(weekly_bars) - pivot_window):
        is_peak = all(
            weekly_bars[i].high >= weekly_bars[j].high
            for j in range(i - pivot_window, i + pivot_window + 1)
            if j != i
        )
        if is_peak:
            peaks.append(i)
    return peaks


def find_weekly_troughs(
    weekly_bars: list[MarketBar],
    pivot_window: int = 4,
) -> list[int]:
    """Find confirmed weekly price troughs (local minima).

    A trough at index i is confirmed when bar[i].low is the lowest
    among all bars within [i - pivot_window, i + pivot_window].
    """
    troughs: list[int] = []
    for i in range(pivot_window, len(weekly_bars) - pivot_window):
        is_trough = all(
            weekly_bars[i].low <= weekly_bars[j].low
            for j in range(i - pivot_window, i + pivot_window + 1)
            if j != i
        )
        if is_trough:
            troughs.append(i)
    return troughs


# ── Composite signal detection ────────────────────────────────────


def detect_cycle_signal(
    bars_4h: list[MarketBar],
    config: MacroCycleConfig,
    funding_rate: float | None = None,
    top_ls_ratio: float | None = None,
    *,
    native_daily: list[MarketBar] | None = None,
    native_weekly: list[MarketBar] | None = None,
) -> MacroCycleSignal:
    """Detect bull top or bear bottom from 4h bars + optional Coinglass data.

    Primary: Weekly RSI divergence at confirmed peaks/troughs.
      - Bearish divergence: higher price high + lower RSI high → sell_top
      - Bullish divergence: lower price low + higher RSI low → buy_bottom
      - Sell/buy percentage scales with divergence severity.

    Fallback: When too few peaks/troughs for divergence analysis,
    uses strict RSI + Mayer thresholds (with optional Coinglass).

    When native_daily / native_weekly are provided, uses them directly
    instead of aggregating from 4h bars (more accurate with Binance data).

    Returns neutral if insufficient data or no signal detected.
    """
    if not bars_4h and not native_weekly:
        return MacroCycleSignal(
            action="neutral", weekly_rsi=None, sma200_ratio=None,
            funding_rate=funding_rate, top_ls_ratio=top_ls_ratio,
            timestamp=datetime.min,
        )

    # Use native bars when provided, otherwise aggregate from 4h
    weekly = native_weekly if native_weekly is not None else aggregate_to_weekly(bars_4h)
    daily = native_daily if native_daily is not None else aggregate_to_daily(bars_4h)

    rsi = compute_weekly_rsi(weekly, config.weekly_rsi_period)
    ratio = compute_sma200_ratio(daily)

    ts = bars_4h[-1].timestamp if bars_4h else weekly[-1].timestamp
    peaks = find_weekly_peaks(weekly, config.divergence_pivot_window)
    troughs = find_weekly_troughs(weekly, config.divergence_pivot_window)

    _neutral = MacroCycleSignal(
        action="neutral", weekly_rsi=rsi, sma200_ratio=ratio,
        funding_rate=funding_rate, top_ls_ratio=top_ls_ratio,
        timestamp=ts, peak_count=len(peaks), trough_count=len(troughs),
    )

    # ── Primary: divergence detection ──

    # Bearish divergence at peaks (sell_top)
    if len(peaks) >= 2:
        curr_peak_idx = peaks[-1]
        prev_peak_idx = peaks[-2]
        curr_rsi = compute_weekly_rsi(
            weekly[: curr_peak_idx + 1], config.weekly_rsi_period,
        )
        prev_rsi = compute_weekly_rsi(
            weekly[: prev_peak_idx + 1], config.weekly_rsi_period,
        )
        curr_price = weekly[curr_peak_idx].high
        prev_price = weekly[prev_peak_idx].high

        if (
            curr_rsi is not None
            and prev_rsi is not None
            and curr_price > prev_price
            and prev_rsi > curr_rsi
        ):
            rsi_drop = prev_rsi - curr_rsi
            if rsi_drop >= config.divergence_min_rsi_drop:
                pct = rsi_drop * config.sell_pct_per_rsi_point
                pct = max(config.sell_pct_min, min(config.sell_pct_max, pct))
                return MacroCycleSignal(
                    action="sell_top",
                    weekly_rsi=rsi,
                    sma200_ratio=ratio,
                    funding_rate=funding_rate,
                    top_ls_ratio=top_ls_ratio,
                    timestamp=ts,
                    divergence_score=rsi_drop,
                    sell_pct=pct,
                    peak_count=len(peaks),
                    trough_count=len(troughs),
                )

    # Bullish divergence at troughs (buy_bottom)
    if len(troughs) >= 2:
        curr_trough_idx = troughs[-1]
        prev_trough_idx = troughs[-2]
        curr_rsi = compute_weekly_rsi(
            weekly[: curr_trough_idx + 1], config.weekly_rsi_period,
        )
        prev_rsi = compute_weekly_rsi(
            weekly[: prev_trough_idx + 1], config.weekly_rsi_period,
        )
        curr_price = weekly[curr_trough_idx].low
        prev_price = weekly[prev_trough_idx].low

        if (
            curr_rsi is not None
            and prev_rsi is not None
            and curr_price < prev_price
            and curr_rsi > prev_rsi
        ):
            rsi_rise = curr_rsi - prev_rsi
            if rsi_rise >= config.divergence_min_rsi_drop:
                pct = rsi_rise * config.buy_pct_per_rsi_point
                pct = max(config.buy_pct_min, min(config.buy_pct_max, pct))
                return MacroCycleSignal(
                    action="buy_bottom",
                    weekly_rsi=rsi,
                    sma200_ratio=ratio,
                    funding_rate=funding_rate,
                    top_ls_ratio=top_ls_ratio,
                    timestamp=ts,
                    divergence_score=rsi_rise,
                    buy_pct=pct,
                    peak_count=len(peaks),
                    trough_count=len(troughs),
                )

    # ── Fallback: threshold-based (only when too few peaks for divergence) ──

    if rsi is None or ratio is None:
        return _neutral

    has_enough_structure = len(peaks) >= 2 or len(troughs) >= 2
    if has_enough_structure:
        # Divergence analysis was possible but found nothing → neutral
        return _neutral

    # Not enough structure for divergence → use strict thresholds
    has_coinglass = funding_rate is not None or top_ls_ratio is not None

    # Bull top fallback
    if has_coinglass:
        coinglass_hot = (
            (funding_rate is not None and funding_rate > config.funding_hot)
            or (top_ls_ratio is not None and top_ls_ratio > config.ls_hot)
        )
        if (
            rsi > config.weekly_rsi_overbought
            and ratio > config.sma200_hot_ratio
            and coinglass_hot
        ):
            return MacroCycleSignal(
                action="sell_top", weekly_rsi=rsi, sma200_ratio=ratio,
                funding_rate=funding_rate, top_ls_ratio=top_ls_ratio,
                timestamp=ts, sell_pct=config.sell_pct,
                peak_count=len(peaks), trough_count=len(troughs),
            )
    else:
        if (
            rsi > config.fallback_rsi_overbought
            and ratio > config.fallback_sma200_hot
        ):
            return MacroCycleSignal(
                action="sell_top", weekly_rsi=rsi, sma200_ratio=ratio,
                funding_rate=None, top_ls_ratio=None,
                timestamp=ts, sell_pct=config.sell_pct,
                peak_count=len(peaks), trough_count=len(troughs),
            )

    # Bear bottom fallback
    if has_coinglass:
        coinglass_cold = (
            (funding_rate is not None and funding_rate < config.funding_cold)
            or (top_ls_ratio is not None and top_ls_ratio < config.ls_cold)
        )
        if (
            rsi < config.weekly_rsi_oversold
            and ratio < config.sma200_cold_ratio
            and coinglass_cold
        ):
            return MacroCycleSignal(
                action="buy_bottom", weekly_rsi=rsi, sma200_ratio=ratio,
                funding_rate=funding_rate, top_ls_ratio=top_ls_ratio,
                timestamp=ts, buy_pct=config.buy_pct,
                peak_count=len(peaks), trough_count=len(troughs),
            )
    else:
        if (
            rsi < config.fallback_rsi_oversold
            and ratio < config.fallback_sma200_cold
        ):
            return MacroCycleSignal(
                action="buy_bottom", weekly_rsi=rsi, sma200_ratio=ratio,
                funding_rate=None, top_ls_ratio=None,
                timestamp=ts, buy_pct=config.buy_pct,
                peak_count=len(peaks), trough_count=len(troughs),
            )

    return _neutral
