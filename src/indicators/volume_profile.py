"""Volume Profile (VRVP) indicator and Bear Bottom Reversal detection.

Computes from daily OHLCV bars:
  - POC (Point of Control): price bin with highest traded volume
  - VAH (Value Area High): upper edge of 70% volume range
  - VAL (Value Area Low): lower edge of 70% volume range
  - HVN (High Volume Nodes): bins > 1.5x median volume
  - LVN (Low Volume Nodes): bins < 0.3x median volume

Bear Reversal Combo (state machine):
  Phase 0 → 1: Capitulation (RSI<22 + vol spike + below VA)
  Phase 1 → 2: Reversal (VAL reclaim + RSI recovery) → BUY signal
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VolumeProfile:
    poc: float  # Point of Control price
    val: float  # Value Area Low
    vah: float  # Value Area High
    hvn: list[tuple[float, float]] = field(default_factory=list)  # High Volume Nodes (lo, hi)
    lvn: list[tuple[float, float]] = field(default_factory=list)  # Low Volume Nodes (lo, hi)


@dataclass(frozen=True)
class BearReversalPhase:
    phase: int  # 0=none, 1=capitulation, 2=reversal confirmed
    action: str  # "hold" or "buy"
    entry_price: float = 0.0
    stop_price: float = 0.0
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


def compute_volume_profile(
    bars: list,
    n_bins: int = 50,
) -> VolumeProfile | None:
    """Compute Volume Profile from daily OHLCV bars.

    Args:
        bars: list of MarketBar with open/high/low/close/volume
        n_bins: number of price bins to divide the range into

    Returns:
        VolumeProfile with POC, VAL, VAH, HVN, LVN or None if insufficient data
    """
    if len(bars) < 10:
        return None

    lo = min(b.low for b in bars)
    hi = max(b.high for b in bars)
    if hi <= lo:
        return None

    bin_size = (hi - lo) / n_bins
    bins: dict[int, float] = {}

    for b in bars:
        b_lo = int((b.low - lo) / bin_size)
        b_hi = min(int((b.high - lo) / bin_size), n_bins - 1)
        n = max(1, b_hi - b_lo + 1)
        vol_per_bin = b.volume / n
        for j in range(b_lo, b_hi + 1):
            bins[j] = bins.get(j, 0) + vol_per_bin

    if not bins:
        return None

    # POC: bin with highest volume
    poc_bin = max(bins, key=bins.get)
    poc_price = lo + poc_bin * bin_size + bin_size / 2

    # Value Area: expand from POC until 70% of total volume
    total_vol = sum(bins.values())
    sorted_by_vol = sorted(bins.items(), key=lambda x: x[1], reverse=True)
    cumul = 0.0
    va_bins: list[int] = []
    for idx, vol in sorted_by_vol:
        va_bins.append(idx)
        cumul += vol
        if cumul >= total_vol * 0.70:
            break

    val_price = lo + min(va_bins) * bin_size
    vah_price = lo + (max(va_bins) + 1) * bin_size

    # HVN / LVN
    vol_values = sorted(bins.values())
    median_vol = vol_values[len(vol_values) // 2]

    hvn: list[tuple[float, float]] = []
    lvn: list[tuple[float, float]] = []
    for j, v in sorted(bins.items()):
        price_lo = lo + j * bin_size
        price_hi = lo + (j + 1) * bin_size
        if v > median_vol * 1.5:
            hvn.append((price_lo, price_hi))
        elif v < median_vol * 0.3 and min(va_bins) < j < max(va_bins):
            lvn.append((price_lo, price_hi))

    return VolumeProfile(poc=poc_price, val=val_price, vah=vah_price, hvn=hvn, lvn=lvn)


def _rsi_from_closes(closes: list[float], period: int = 14) -> float | None:
    """Compute RSI from a list of close prices."""
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    if len(gains) < period:
        return None
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def detect_bear_reversal_phase(
    bars: list,
    vp_lookback: int = 60,
    rsi_period: int = 14,
    capitulation_rsi: float = 22.0,
    capitulation_vol_ratio: float = 1.5,
    recovery_rsi: float = 33.0,
    capitulation_timeout: int = 30,
) -> BearReversalPhase:
    """Walk through bars and detect bear bottom reversal combo.

    Returns the CURRENT phase state after processing all bars.
    Phase 0: no signal. Phase 1: capitulation detected. Phase 2: reversal confirmed (BUY).

    Args:
        bars: daily OHLCV bars (need 250+ for meaningful analysis)
        vp_lookback: days to compute volume profile
        rsi_period: RSI period
        capitulation_rsi: RSI threshold for capitulation (<= this)
        capitulation_vol_ratio: volume must exceed this × 20d average
        recovery_rsi: RSI must recover above this for phase 2
        capitulation_timeout: max bars between phase 1 and phase 2
    """
    min_bars = 200
    if len(bars) < min_bars:
        return BearReversalPhase(phase=0, action="hold")

    phase = 0
    phase1_bar = 0
    phase1_details: dict[str, Any] = {}
    result = BearReversalPhase(phase=0, action="hold")

    for i in range(min_bars, len(bars)):
        bar = bars[i]
        prev = bars[i - 1]
        closes = [b.close for b in bars[: i + 1]]
        volumes = [b.volume for b in bars[: i + 1]]

        rsi_val = _rsi_from_closes(closes, rsi_period)
        vol_sma = _sma(volumes, 20)
        vol_ratio = bar.volume / vol_sma if vol_sma and vol_sma > 0 else 0

        vp = compute_volume_profile(bars[max(0, i + 1 - vp_lookback) : i + 1])
        prev_vp = compute_volume_profile(bars[max(0, i - vp_lookback) : i])

        if not vp or rsi_val is None:
            continue

        # Phase 0 → 1: Capitulation
        if phase == 0:
            if (
                rsi_val <= capitulation_rsi
                and vol_ratio >= capitulation_vol_ratio
                and bar.close < vp.val
            ):
                phase = 1
                phase1_bar = i
                phase1_details = {
                    "date": bar.timestamp,
                    "price": bar.close,
                    "rsi": rsi_val,
                    "vol_ratio": vol_ratio,
                }
                result = BearReversalPhase(
                    phase=1, action="hold",
                    metadata={"capitulation": phase1_details},
                )

        # Phase 1 → 2: Reversal confirmed
        elif phase == 1:
            if i - phase1_bar > capitulation_timeout:
                phase = 0
                result = BearReversalPhase(phase=0, action="hold")
                continue

            # Check recent RSI minimum (must have had extreme oversold)
            recent_rsis = []
            for j in range(max(min_bars, i - 10), i + 1):
                r = _rsi_from_closes([b.close for b in bars[: j + 1]], rsi_period)
                if r is not None:
                    recent_rsis.append(r)
            rsi_min = min(recent_rsis) if recent_rsis else 50.0

            # Check if price was below VAL recently (within timeout window)
            was_below_val = any(
                bars[j].close < compute_volume_profile(
                    bars[max(0, j + 1 - vp_lookback) : j + 1]
                ).val
                for j in range(phase1_bar, i)
                if compute_volume_profile(bars[max(0, j + 1 - vp_lookback) : j + 1]) is not None
            )

            is_val_reclaim = (
                was_below_val
                and bar.close > vp.val
                and rsi_val > recovery_rsi
                and rsi_min <= capitulation_rsi
            )

            if is_val_reclaim:
                phase = 2
                # Stop below recent low or VAL
                recent_low = min(b.low for b in bars[phase1_bar : i + 1])
                result = BearReversalPhase(
                    phase=2,
                    action="buy",
                    entry_price=bar.close,
                    stop_price=min(recent_low, vp.val) * 0.98,
                    confidence=0.8,
                    metadata={
                        "capitulation": phase1_details,
                        "vp_poc": vp.poc,
                        "vp_val": vp.val,
                        "vp_vah": vp.vah,
                        "rsi_at_entry": rsi_val,
                        "rsi_min": rsi_min,
                    },
                )

    return result
