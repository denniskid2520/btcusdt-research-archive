"""Archived post-signal filters.

Tested in backtests and either showed no improvement or hurt performance.
Preserved for future research.

Status:
  - ma_regime_filter: MA200 halves DD but also halves returns. Use only for "safe" config.
  - crowded_long/short: Needs Coinglass OI data. No improvement at tested thresholds.
  - liq_cascade_filter: Needs liquidation data. Too noisy to be useful filter.
  - taker_imbalance_filter: Buy/sell ratio filter. No net benefit in backtest.
  - basis_extreme_filter: Futures premium filter. Basis never hit threshold in BTC data.
  - cvd_divergence_filter: CVD trend direction. TOO STRICT — kills good trades.
"""

from __future__ import annotations

from typing import Any

from adapters.base import MarketBar
from strategies.base import StrategySignal


def apply_ma_regime_filter(
    signal: StrategySignal,
    bars: list[MarketBar],
    ma_period: int = 200,
) -> StrategySignal:
    """Block longs below SMA, shorts above SMA.

    Result: halves DD (19.3% → 9.6%) but also halves returns (+36.5% → +33.2%).
    Best for: conservative "safe" config. Not for max-return config.
    """
    if signal.action == "hold" or len(bars) < ma_period:
        return signal
    sma_val = sum(b.close for b in bars[-ma_period:]) / ma_period
    current_close = bars[-1].close
    if signal.action == "buy" and current_close < sma_val:
        return StrategySignal(action="hold", confidence=0.0, reason="ma_regime_blocked_long")
    if signal.action == "short" and current_close > sma_val:
        return StrategySignal(action="hold", confidence=0.0, reason="ma_regime_blocked_short")
    return signal


def apply_crowded_filter(
    signal: StrategySignal,
    futures_provider: Any,
    symbol: str,
    timestamp: Any,
    crowded_long_threshold: float = 0.0,
    crowded_short_threshold: float = 0.0,
) -> StrategySignal:
    """Block longs when crowd is too long, shorts when too short.

    Result: no improvement at tested thresholds. Needs better OI data.
    """
    if signal.action == "hold" or futures_provider is None:
        return signal
    snapshot = futures_provider.get_snapshot(symbol, timestamp)
    if snapshot is None:
        return signal
    if signal.action == "buy" and crowded_long_threshold > 0:
        if snapshot.long_pct >= crowded_long_threshold * 100:
            return StrategySignal(action="hold", confidence=0.0, reason="oi_crowded_long_blocked")
    elif signal.action == "short" and crowded_short_threshold > 0:
        if snapshot.short_pct >= crowded_short_threshold * 100:
            return StrategySignal(action="hold", confidence=0.0, reason="oi_crowded_short_blocked")
    return signal


def apply_liq_cascade_filter(
    signal: StrategySignal,
    futures_provider: Any,
    symbol: str,
    timestamp: Any,
    min_usd: float = 1_000_000,
) -> StrategySignal:
    """Require liquidation cascade to confirm trade direction.

    Result: too noisy. Liquidation data is daily, not granular enough for 4h signals.
    """
    if signal.action == "hold" or futures_provider is None:
        return signal
    snap = futures_provider.get_snapshot(symbol, timestamp)
    if snap is None:
        return signal
    if signal.action == "short":
        if (snap.liq_long_usd or 0) < min_usd:
            return StrategySignal(action="hold", confidence=0.0, reason="liq_cascade_not_confirmed")
    elif signal.action == "buy":
        if (snap.liq_short_usd or 0) < min_usd:
            return StrategySignal(action="hold", confidence=0.0, reason="liq_cascade_not_confirmed")
    return signal


def apply_taker_imbalance_filter(
    signal: StrategySignal,
    futures_provider: Any,
    symbol: str,
    timestamp: Any,
    min_ratio: float = 1.1,
) -> StrategySignal:
    """Require taker buy/sell imbalance to confirm direction.

    Result: no net benefit. Taker data too noisy at daily resolution.
    """
    if signal.action == "hold" or futures_provider is None:
        return signal
    snap = futures_provider.get_snapshot(symbol, timestamp)
    if snap is None:
        return signal
    buy_usd = snap.taker_buy_usd or 0
    sell_usd = snap.taker_sell_usd or 0
    if signal.action == "buy" and sell_usd > 0:
        if buy_usd / sell_usd < min_ratio:
            return StrategySignal(action="hold", confidence=0.0, reason="taker_imbalance_not_confirmed")
    elif signal.action == "short" and buy_usd > 0:
        if sell_usd / buy_usd < min_ratio:
            return StrategySignal(action="hold", confidence=0.0, reason="taker_imbalance_not_confirmed")
    return signal


def apply_basis_extreme_filter(
    signal: StrategySignal,
    futures_provider: Any,
    symbol: str,
    timestamp: Any,
    threshold: float = 0.10,
) -> StrategySignal:
    """Block trades at extreme futures premium/discount.

    Result: no effect in BTC backtest. Basis never hit 10% threshold.
    """
    if signal.action == "hold" or futures_provider is None:
        return signal
    snap = futures_provider.get_snapshot(symbol, timestamp)
    if snap is None or snap.basis is None:
        return signal
    if signal.action == "buy" and snap.basis > threshold:
        return StrategySignal(action="hold", confidence=0.0, reason="basis_too_extreme")
    if signal.action == "short" and snap.basis < -threshold:
        return StrategySignal(action="hold", confidence=0.0, reason="basis_too_extreme")
    return signal


def apply_cvd_divergence_filter(
    signal: StrategySignal,
    futures_provider: Any,
    symbol: str,
    bars: list[MarketBar],
    lookback: int = 12,
) -> StrategySignal:
    """Block when CVD trend opposes trade direction.

    Result: TOO STRICT. Kills good trades. CVD is noisy at daily resolution.
    """
    if signal.action == "hold" or futures_provider is None or len(bars) <= lookback:
        return signal
    recent_bars = bars[-lookback:]
    cvd_values = []
    for b in recent_bars:
        snap = futures_provider.get_snapshot(symbol, b.timestamp)
        if snap is not None and snap.cvd is not None:
            cvd_values.append(snap.cvd)
    if len(cvd_values) < 2:
        return signal
    cvd_trend = cvd_values[-1] - cvd_values[0]
    if signal.action == "buy" and cvd_trend < 0:
        return StrategySignal(action="hold", confidence=0.0, reason="cvd_divergence")
    if signal.action == "short" and cvd_trend > 0:
        return StrategySignal(action="hold", confidence=0.0, reason="cvd_divergence")
    return signal
