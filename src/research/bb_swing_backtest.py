"""Bollinger Bands swing trading backtest — Strategy D.

Standalone, self-contained backtest for mean-reversion on BTC inverse perpetual.

Run: PYTHONPATH=src python -m research.bb_swing_backtest
Or use the runner: PYTHONPATH=src python run_bb_swing_backtest.py
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


# ===========================================================================
# Data structures
# ===========================================================================

@dataclass(frozen=True)
class BBState:
    """Bollinger Band state at a point in time."""
    middle: float
    upper: float
    lower: float
    width_pct: float


@dataclass
class BBConfig:
    """All configurable parameters for the BB swing strategy."""
    # Bollinger Bands
    bb_period: int = 20
    bb_k: float = 2.0

    # Entry
    band_touch_pct: float = 0.01  # within 1% of band counts as "touch"
    cooldown_days: int = 1

    # Exit
    target_mode: str = "middle"  # "middle" or "opposite"
    stop_loss_pct: float = 0.03  # close X% beyond entry → stop
    max_hold_bars: int = 120  # 20 days * 6 bars/day (4h)
    use_trailing_stop: bool = False
    trailing_activation_pct: float = 0.03  # activate after 3% profit
    trailing_atr_multiplier: float = 2.0

    # Filters
    use_ma200_filter: bool = False
    use_rsi_filter: bool = False
    rsi_period: int = 3
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    use_adx_filter: bool = False
    adx_period: int = 14
    adx_threshold: float = 25.0
    min_band_width_pct: float = 3.0
    max_band_width_pct: float = 30.0

    # Position sizing
    risk_per_trade: float = 0.05
    max_margin_pct: float = 0.90

    # Fee
    fee_rate: float = 0.001  # 0.1% per trade (entry + exit)

    # Label (for sweep output)
    label: str = ""


@dataclass
class TradeRecord:
    """One completed trade."""
    entry_ts: datetime
    exit_ts: datetime
    side: str
    entry_price: float
    exit_price: float
    exit_reason: str
    qty_btc: float
    pnl_btc: float
    pnl_pct: float
    duration_days: float
    bb_upper: float
    bb_lower: float
    bb_middle: float
    bb_width_pct: float


# ===========================================================================
# Indicator calculations
# ===========================================================================

def calculate_bb(prices: list[float], period: int, k: float) -> BBState | None:
    """Compute Bollinger Bands from a list of close prices.

    Returns None if insufficient data.
    """
    if len(prices) < period:
        return None
    window = prices[-period:]
    middle = statistics.mean(window)
    if period < 2:
        return BBState(middle=middle, upper=middle, lower=middle, width_pct=0.0)
    std = statistics.stdev(window)
    upper = middle + k * std
    lower = middle - k * std
    width_pct = (upper - lower) / middle * 100 if middle != 0 else 0.0
    return BBState(middle=middle, upper=upper, lower=lower, width_pct=width_pct)


def calculate_rsi(prices: list[float], period: int) -> float | None:
    """Wilder RSI on close prices. Returns None if insufficient data."""
    if len(prices) < period + 1:
        return None
    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

    # Seed with SMA
    gains = [max(c, 0) for c in changes[:period]]
    losses = [max(-c, 0) for c in changes[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # Smoothed (Wilder)
    for c in changes[period:]:
        avg_gain = (avg_gain * (period - 1) + max(c, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-c, 0)) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_adx(bars: list[dict], period: int = 14) -> float | None:
    """ADX (Average Directional Index). bars must have high/low/close keys."""
    if len(bars) < period * 2 + 1:
        return None

    tr_list = []
    plus_dm_list = []
    minus_dm_list = []

    for i in range(1, len(bars)):
        high = bars[i]["high"]
        low = bars[i]["low"]
        prev_close = bars[i - 1]["close"]
        prev_high = bars[i - 1]["high"]
        prev_low = bars[i - 1]["low"]

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)

        up_move = high - prev_high
        down_move = prev_low - low
        plus_dm_list.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm_list.append(down_move if down_move > up_move and down_move > 0 else 0)

    if len(tr_list) < period:
        return None

    # Wilder smoothing
    atr = sum(tr_list[:period]) / period
    plus_dm_smooth = sum(plus_dm_list[:period]) / period
    minus_dm_smooth = sum(minus_dm_list[:period]) / period

    dx_list = []
    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
        plus_dm_smooth = (plus_dm_smooth * (period - 1) + plus_dm_list[i]) / period
        minus_dm_smooth = (minus_dm_smooth * (period - 1) + minus_dm_list[i]) / period

        if atr == 0:
            continue
        plus_di = 100 * plus_dm_smooth / atr
        minus_di = 100 * minus_dm_smooth / atr
        denom = plus_di + minus_di
        if denom == 0:
            dx_list.append(0)
        else:
            dx_list.append(100 * abs(plus_di - minus_di) / denom)

    if len(dx_list) < period:
        return None

    adx = sum(dx_list[:period]) / period
    for dx in dx_list[period:]:
        adx = (adx * (period - 1) + dx) / period

    return adx


def calculate_atr(bars: list[dict], period: int = 14) -> float | None:
    """Average True Range. Returns None if insufficient data."""
    if len(bars) < period + 1:
        return None
    tr_list = []
    for i in range(1, len(bars)):
        high = bars[i]["high"]
        low = bars[i]["low"]
        prev_close = bars[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)

    if len(tr_list) < period:
        return None

    atr = sum(tr_list[:period]) / period
    for tr in tr_list[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def calculate_sma(prices: list[float], period: int) -> float | None:
    """Simple Moving Average. Returns None if insufficient data."""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


# ===========================================================================
# Entry / exit logic
# ===========================================================================

def check_entry_signal(
    close: float,
    bb: BBState,
    ma200: float | None,
    rsi3: float | None,
    adx: float | None,
    config: BBConfig,
    last_exit_ts: datetime | None,
    current_ts: datetime,
) -> str | None:
    """Return 'long', 'short', or None."""
    # Cooldown check
    if last_exit_ts is not None:
        delta = current_ts - last_exit_ts
        if delta < timedelta(days=config.cooldown_days):
            return None

    # Band width filters
    if bb.width_pct < config.min_band_width_pct:
        return None
    if bb.width_pct > config.max_band_width_pct:
        return None

    # ADX filter: block in trending markets
    if config.use_adx_filter and adx is not None and adx > config.adx_threshold:
        return None

    # Determine signal direction
    signal: str | None = None
    touch_margin_lower = bb.lower * (1 + config.band_touch_pct)
    touch_margin_upper = bb.upper * (1 - config.band_touch_pct)

    if close <= touch_margin_lower:
        signal = "long"
    elif close >= touch_margin_upper:
        signal = "short"
    else:
        return None

    # MA200 filter
    if config.use_ma200_filter and ma200 is not None:
        if signal == "long" and close < ma200:
            return None
        if signal == "short" and close > ma200:
            return None

    # RSI filter
    if config.use_rsi_filter and rsi3 is not None:
        if signal == "long" and rsi3 > config.rsi_oversold:
            return None
        if signal == "short" and rsi3 < config.rsi_overbought:
            return None

    return signal


def check_exit_signal(
    side: str,
    entry_price: float,
    close: float,
    bb: BBState,
    bars_held: int,
    atr: float,
    max_profit_pct: float,
    config: BBConfig,
) -> str | None:
    """Return exit reason string or None."""
    # Stop loss
    if side == "long":
        stop_price = entry_price * (1 - config.stop_loss_pct)
        if close <= stop_price:
            return "stop_loss"
    else:
        stop_price = entry_price * (1 + config.stop_loss_pct)
        if close >= stop_price:
            return "stop_loss"

    # Target: middle band
    if config.target_mode == "middle":
        if side == "long" and close >= bb.middle:
            return "target_middle"
        if side == "short" and close <= bb.middle:
            return "target_middle"
    elif config.target_mode == "opposite":
        if side == "long" and close >= bb.upper:
            return "target_opposite"
        if side == "short" and close <= bb.lower:
            return "target_opposite"

    # Trailing stop
    if config.use_trailing_stop and max_profit_pct >= config.trailing_activation_pct:
        if side == "long":
            peak_price = entry_price * (1 + max_profit_pct)
            trail_level = peak_price - config.trailing_atr_multiplier * atr
            if close <= trail_level:
                return "trailing_stop"
        else:
            trough_price = entry_price * (1 - max_profit_pct)
            trail_level = trough_price + config.trailing_atr_multiplier * atr
            if close >= trail_level:
                return "trailing_stop"

    # Time stop
    if bars_held >= config.max_hold_bars:
        return "time_stop"

    return None


# ===========================================================================
# Position sizing (inverse perpetual)
# ===========================================================================

def position_size_btc(
    capital_btc: float,
    stop_distance_pct: float,
    leverage: int,
    max_margin_pct: float,
    risk_per_trade: float,
) -> float:
    """Calculate position size in BTC for inverse perpetual."""
    if stop_distance_pct <= 0:
        return 0.0
    risk_based = (capital_btc * risk_per_trade) / stop_distance_pct
    cap = capital_btc * max_margin_pct * leverage
    return min(risk_based, cap)


def position_size_usdt(
    capital_usdt: float,
    entry_price: float,
    stop_distance_pct: float,
    leverage: int,
    max_margin_pct: float,
    risk_per_trade: float,
) -> float:
    """Calculate position size in BTC for USDT-M linear perpetual.

    risk_based: (capital * risk%) / stop% / price → BTC qty
    cap: capital * margin% * leverage / price → BTC qty
    """
    if stop_distance_pct <= 0 or entry_price <= 0:
        return 0.0
    risk_based = (capital_usdt * risk_per_trade) / stop_distance_pct / entry_price
    cap = capital_usdt * max_margin_pct * leverage / entry_price
    return min(risk_based, cap)


def inverse_pnl_btc(
    side: str, qty_btc: float, entry: float, exit_: float, fee_rate: float,
) -> float:
    """PnL in BTC for inverse perpetual contract.

    Long:  qty * (exit/entry - 1) - fees
    Short: qty * (1 - exit/entry) - fees
    """
    if side == "long":
        gross = qty_btc * (exit_ / entry - 1)
    else:
        gross = qty_btc * (1 - exit_ / entry)
    fees = qty_btc * fee_rate * 2  # entry + exit
    return gross - fees


def linear_pnl_usdt(
    side: str, qty_btc: float, entry: float, exit_: float, fee_rate: float,
) -> float:
    """PnL in USDT for linear perpetual contract.

    Long:  qty * (exit - entry) - fees
    Short: qty * (entry - exit) - fees
    Fees are on notional: qty * price * fee_rate at entry + exit.
    """
    if side == "long":
        gross = qty_btc * (exit_ - entry)
    else:
        gross = qty_btc * (entry - exit_)
    fees = qty_btc * entry * fee_rate + qty_btc * exit_ * fee_rate
    return gross - fees


# ===========================================================================
# Data helpers
# ===========================================================================

def _aggregate_4h_to_daily(bars_4h: list[dict]) -> list[dict]:
    """Aggregate 4h bars into daily bars (OHLCV)."""
    daily: dict[str, list[dict]] = {}
    for bar in bars_4h:
        day_key = bar["timestamp"].strftime("%Y-%m-%d")
        if day_key not in daily:
            daily[day_key] = []
        daily[day_key].append(bar)

    result = []
    for day_key in sorted(daily.keys()):
        day_bars = daily[day_key]
        result.append({
            "timestamp": day_bars[0]["timestamp"],
            "open": day_bars[0]["open"],
            "high": max(b["high"] for b in day_bars),
            "low": min(b["low"] for b in day_bars),
            "close": day_bars[-1]["close"],
            "volume": sum(b["volume"] for b in day_bars),
        })
    return result


def fetch_binance_native_daily(
    symbol: str = "BTCUSDT",
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 1500,
) -> list[dict]:
    """Fetch native 1d klines from Binance Futures API.

    Uses fapi.binance.com/fapi/v1/klines?interval=1d with auto-pagination.
    Returns list of dicts with timestamp/open/high/low/close/volume.
    """
    import json
    import time as _time
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen

    base_url = "https://fapi.binance.com"
    max_per_req = 1500
    interval_ms = 86_400_000  # 1 day in ms

    if start is None:
        start = datetime(2021, 1, 1)
    if end is None:
        end = datetime.utcnow()

    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    all_bars: list[dict] = []
    cursor = start_ms

    while cursor < end_ms:
        params = {
            "symbol": symbol,
            "interval": "1d",
            "limit": min(limit, max_per_req),
            "startTime": cursor,
            "endTime": end_ms,
        }
        url = f"{base_url}/fapi/v1/klines?{urlencode(params)}"
        req = Request(url=url, method="GET")
        req.add_header("Accept", "application/json")

        with urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        if not raw:
            break

        for row in raw:
            ts = datetime.utcfromtimestamp(int(row[0]) / 1000)
            all_bars.append({
                "timestamp": ts,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            })

        last_open_ms = int(raw[-1][0])
        cursor = last_open_ms + interval_ms

        if len(raw) < max_per_req:
            break
        _time.sleep(0.2)

    return all_bars


def _load_4h_csv(csv_path: str | Path) -> list[dict]:
    """Load 4h OHLCV CSV into list of dicts."""
    import csv as csv_mod
    bars = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv_mod.DictReader(f)
        for row in reader:
            bars.append({
                "timestamp": datetime.fromisoformat(row["timestamp"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
    if not bars:
        raise ValueError(f"No bars loaded from {csv_path}")
    return bars


# ===========================================================================
# Main backtest engine
# ===========================================================================

def run_bb_backtest(
    bars_4h: list[dict],
    config: BBConfig,
    initial_btc: float = 1.0,
    leverage: int = 3,
    daily_bars: list[dict] | None = None,
    margin_type: str = "inverse",
    initial_capital: float = 0.0,
) -> dict[str, Any]:
    """Run complete BB swing backtest on 4h bars.

    Args:
        daily_bars: Native daily bars for indicators. Falls back to 4h aggregation.
        margin_type: "inverse" (COIN-M, capital in BTC) or "linear" (USDT-M, capital in USDT).
        initial_capital: Starting capital in USDT (only used when margin_type="linear").

    Returns dict with summary stats, trades, and equity curve.
    """
    is_linear = margin_type == "linear"
    capital = initial_capital if is_linear else initial_btc
    min_capital = 1.0 if is_linear else 0.001

    # Use native daily bars if provided, otherwise aggregate from 4h
    if daily_bars is None:
        daily_bars = _aggregate_4h_to_daily(bars_4h)
    daily_closes = [d["close"] for d in daily_bars]

    # Build daily index map: date_str -> daily_index
    daily_date_map: dict[str, int] = {}
    for i, d in enumerate(daily_bars):
        day_key = d["timestamp"].strftime("%Y-%m-%d")
        daily_date_map[day_key] = i

    # State
    position_side: str | None = None
    entry_price = 0.0
    entry_ts: datetime | None = None
    entry_bar_idx = 0
    qty_btc = 0.0
    max_profit_pct = 0.0
    last_exit_ts: datetime | None = None
    entry_bb: BBState | None = None

    trades: list[dict] = []
    equity_curve: list[float] = [capital]

    # Need enough daily bars for max(bb_period, 200, adx_period*2)
    min_daily = max(config.bb_period, 200 if config.use_ma200_filter else 0,
                    config.adx_period * 3 if config.use_adx_filter else 0)

    def _calc_pnl(side: str, qty: float, entry: float, exit_: float) -> float:
        if is_linear:
            return linear_pnl_usdt(side, qty, entry, exit_, config.fee_rate)
        return inverse_pnl_btc(side, qty, entry, exit_, config.fee_rate)

    def _calc_size(close: float) -> float:
        if is_linear:
            return position_size_usdt(
                capital_usdt=capital, entry_price=close,
                stop_distance_pct=config.stop_loss_pct, leverage=leverage,
                max_margin_pct=config.max_margin_pct, risk_per_trade=config.risk_per_trade,
            )
        return position_size_btc(
            capital_btc=capital, stop_distance_pct=config.stop_loss_pct,
            leverage=leverage, max_margin_pct=config.max_margin_pct,
            risk_per_trade=config.risk_per_trade,
        )

    for i, bar in enumerate(bars_4h):
        current_ts = bar["timestamp"]
        close = bar["close"]

        # Map to daily index
        day_key = current_ts.strftime("%Y-%m-%d")
        daily_idx = daily_date_map.get(day_key)
        if daily_idx is None or daily_idx <= min_daily:
            equity_curve.append(capital)
            continue

        # Daily indicators — use only CLOSED daily bars (exclude current day
        # to avoid lookahead bias: at 4h intraday we don't know today's close)
        d_closes = daily_closes[:daily_idx]

        bb = calculate_bb(d_closes, period=config.bb_period, k=config.bb_k)
        if bb is None:
            equity_curve.append(capital)
            continue

        ma200 = calculate_sma(d_closes, 200) if config.use_ma200_filter else None

        # RSI on 4h closes for entry timing
        rsi3 = None
        if config.use_rsi_filter and i >= config.rsi_period + 1:
            _4h_closes = [b["close"] for b in bars_4h[max(0, i - 50):i + 1]]
            rsi3 = calculate_rsi(_4h_closes, period=config.rsi_period)

        # ADX on daily bars
        adx = None
        if config.use_adx_filter:
            adx = calculate_adx(daily_bars[:daily_idx], period=config.adx_period)

        # ATR on 4h bars for trailing stop
        atr = None
        if config.use_trailing_stop:
            atr_bars = bars_4h[max(0, i - 20):i + 1]
            atr = calculate_atr(atr_bars, period=14)

        if position_side is None:
            # Check entry
            signal = check_entry_signal(
                close=close, bb=bb, ma200=ma200, rsi3=rsi3, adx=adx,
                config=config, last_exit_ts=last_exit_ts, current_ts=current_ts,
            )
            if signal is not None:
                qty_btc = _calc_size(close)
                if qty_btc > 0:
                    position_side = signal
                    entry_price = close
                    entry_ts = current_ts
                    entry_bar_idx = i
                    max_profit_pct = 0.0
                    entry_bb = bb
        else:
            # Track max profit for trailing stop
            if position_side == "long":
                current_pnl_pct = (close / entry_price) - 1
            else:
                current_pnl_pct = 1 - (close / entry_price)
            max_profit_pct = max(max_profit_pct, current_pnl_pct)

            # Check exit
            bars_held = i - entry_bar_idx
            exit_reason = check_exit_signal(
                side=position_side, entry_price=entry_price, close=close,
                bb=bb, bars_held=bars_held, atr=atr or 0.0,
                max_profit_pct=max_profit_pct, config=config,
            )
            if exit_reason is not None:
                pnl = _calc_pnl(position_side, qty_btc, entry_price, close)
                pnl_pct = pnl / capital * 100 if capital > 0 else 0
                duration = (current_ts - entry_ts).total_seconds() / 86400 if entry_ts else 0

                trades.append({
                    "entry_ts": entry_ts,
                    "exit_ts": current_ts,
                    "side": position_side,
                    "entry_price": entry_price,
                    "exit_price": close,
                    "exit_reason": exit_reason,
                    "qty_btc": qty_btc,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "duration_days": duration,
                    "bb_upper": entry_bb.upper if entry_bb else 0,
                    "bb_lower": entry_bb.lower if entry_bb else 0,
                    "bb_middle": entry_bb.middle if entry_bb else 0,
                    "bb_width_pct": entry_bb.width_pct if entry_bb else 0,
                })

                capital += pnl
                capital = max(capital, min_capital)
                position_side = None
                last_exit_ts = current_ts
                entry_bb = None

        equity_curve.append(capital)

    # Force close any open position at end
    if position_side is not None:
        last_bar = bars_4h[-1]
        pnl = _calc_pnl(position_side, qty_btc, entry_price, last_bar["close"])
        pnl_pct = pnl / capital * 100 if capital > 0 else 0
        duration = (last_bar["timestamp"] - entry_ts).total_seconds() / 86400 if entry_ts else 0
        trades.append({
            "entry_ts": entry_ts,
            "exit_ts": last_bar["timestamp"],
            "side": position_side,
            "entry_price": entry_price,
            "exit_price": last_bar["close"],
            "exit_reason": "forced_end",
            "qty_btc": qty_btc,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "duration_days": duration,
            "bb_upper": entry_bb.upper if entry_bb else 0,
            "bb_lower": entry_bb.lower if entry_bb else 0,
            "bb_middle": entry_bb.middle if entry_bb else 0,
            "bb_width_pct": entry_bb.width_pct if entry_bb else 0,
        })
        capital += pnl
        capital = max(capital, min_capital)

    # Compute summary stats
    initial = initial_capital if is_linear else initial_btc
    total_trades = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / total_trades * 100 if total_trades else 0
    avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    avg_duration = (
        sum(t["duration_days"] for t in trades) / total_trades if total_trades else 0
    )

    # Max drawdown
    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            dd = (peak - eq) / peak
            max_dd = max(max_dd, dd)
    max_dd_pct = max_dd * 100

    # Return / DD ratio
    total_return_pct = (capital / initial - 1) * 100
    r_dd = total_return_pct / max_dd_pct if max_dd_pct > 0 else 0

    # Sharpe (annualized, on daily returns from equity curve)
    sharpe = _compute_sharpe(equity_curve)

    # Trades per year
    if bars_4h:
        span_days = (bars_4h[-1]["timestamp"] - bars_4h[0]["timestamp"]).total_seconds() / 86400
        trades_per_year = total_trades / (span_days / 365.25) if span_days > 0 else 0
    else:
        span_days = 0
        trades_per_year = 0

    # Exit reason breakdown
    exit_reasons: dict[str, int] = {}
    for t in trades:
        r = t["exit_reason"]
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    result = {
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_dd_pct,
        "r_dd": r_dd,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "sharpe": sharpe,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "avg_duration_days": avg_duration,
        "trades_per_year": trades_per_year,
        "exit_reasons": exit_reasons,
        "trades": trades,
        "equity_curve": equity_curve,
        "config_label": config.label,
    }

    if is_linear:
        result["initial_capital"] = initial_capital
        result["final_capital"] = capital
    else:
        result["initial_btc"] = initial_btc
        result["final_btc"] = capital

    return result


def _compute_sharpe(equity_curve: list[float], periods_per_year: float = 365.25) -> float:
    """Annualized Sharpe from equity curve (assumes daily-ish sampling)."""
    if len(equity_curve) < 10:
        return 0.0
    # Subsample to ~daily (take every 6th point for 4h data)
    step = max(1, len(equity_curve) // (len(equity_curve) // 6 + 1))
    sampled = equity_curve[::step]
    if len(sampled) < 3:
        return 0.0
    returns = [(sampled[i] / sampled[i - 1]) - 1 for i in range(1, len(sampled)) if sampled[i - 1] > 0]
    if not returns:
        return 0.0
    mean_r = statistics.mean(returns)
    std_r = statistics.stdev(returns) if len(returns) > 1 else 1e-10
    if std_r < 1e-10:
        return 0.0
    # Annualize: assume each return ~ 1 day
    return (mean_r / std_r) * math.sqrt(periods_per_year)


# ===========================================================================
# Convenience: load real data + run
# ===========================================================================

def load_real_4h_data(force_5y: bool = True) -> list[dict]:
    """Load real BTC 4h data from project CSV files.

    Searches multiple possible locations for the CSV.
    """
    data_dir = Path(__file__).resolve().parent.parent / "data"
    # The project root is two levels above the worktree directory
    # e.g., .../New project/.claude/worktrees/agent-XXX/src/research/bb_swing_backtest.py
    # We need: .../New project/.claude/worktrees/unruffled-wilbur/src/data/
    worktree_root = Path(__file__).resolve().parent.parent.parent  # agent-XXX/
    project_root = worktree_root.parent.parent.parent  # New project/
    alt_dirs = [
        data_dir,
        project_root / ".claude" / "worktrees" / "unruffled-wilbur" / "src" / "data",
    ]

    fname = "btcusdt_4h_5year.csv" if force_5y else "btcusdt_4h_6year.csv"
    fallback = "btcusdt_4h_5year.csv"

    for d in alt_dirs:
        csv_path = d / fname
        if csv_path.exists():
            return _load_4h_csv(csv_path)
        if fname != fallback:
            fb_path = d / fallback
            if fb_path.exists():
                return _load_4h_csv(fb_path)

    raise FileNotFoundError(
        f"Cannot find {fname} in any of: {[str(d) for d in alt_dirs]}"
    )


def main() -> None:
    """Quick standalone run with default config."""
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    bars = load_real_4h_data()
    print(f"Loaded {len(bars)} 4h bars: {bars[0]['timestamp']} to {bars[-1]['timestamp']}")

    config = BBConfig(
        bb_period=20, bb_k=2.0, target_mode="middle",
        use_ma200_filter=True, label="BB(20,2.0) + MA200",
    )
    result = run_bb_backtest(bars_4h=bars, config=config, initial_btc=1.0, leverage=3)
    _print_result(result)


def _print_result(result: dict[str, Any]) -> None:
    """Pretty-print backtest result summary."""
    label = result.get("config_label", "")
    print(f"\n{'=' * 70}")
    print(f"  {label}")
    print(f"{'=' * 70}")
    print(f"  Return:      {result['total_return_pct']:+.1f}%")
    if "final_btc" in result:
        print(f"  Final BTC:   {result['final_btc']:.4f} (from {result['initial_btc']:.4f})")
    else:
        print(f"  Final USDT:  ${result['final_capital']:,.0f} (from ${result['initial_capital']:,.0f})")
    print(f"  Max DD:      {result['max_drawdown_pct']:.1f}%")
    print(f"  R/DD:        {result['r_dd']:.2f}")
    print(f"  Trades:      {result['total_trades']} ({result['trades_per_year']:.1f}/yr)")
    print(f"  Win Rate:    {result['win_rate']:.1f}%")
    print(f"  Profit Fac:  {result['profit_factor']:.2f}")
    print(f"  Sharpe:      {result['sharpe']:.2f}")
    print(f"  Avg Win:     {result['avg_win_pct']:+.2f}%  |  Avg Loss: {result['avg_loss_pct']:+.2f}%")
    print(f"  Avg Duration: {result['avg_duration_days']:.1f} days")
    print(f"  Exit reasons: {result['exit_reasons']}")
    print()


if __name__ == "__main__":
    main()
