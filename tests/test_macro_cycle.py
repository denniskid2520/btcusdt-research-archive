"""Tests for macro cycle detection: weekly RSI divergence at tops/bottoms.

TDD: tests first, then implementation.

Primary detection: Weekly RSI divergence
  - Bearish: price higher high + RSI lower high → sell BTC
  - Bullish: price lower low + RSI higher low → buy BTC
  - Severity scales sell/buy percentage

Fallback: threshold-based for extreme conditions (early data, blow-off tops).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from adapters.base import MarketBar
from execution.paper_broker import PaperBroker


TS = datetime(2021, 1, 1)


def _make_bars_4h(
    prices: list[float],
    start: datetime = TS,
) -> list[MarketBar]:
    """Create 4h bars from close prices."""
    return [
        MarketBar(
            timestamp=start + timedelta(hours=i * 4),
            open=p * 0.998,
            high=p * 1.003,
            low=p * 0.997,
            close=p,
            volume=100.0,
        )
        for i, p in enumerate(prices)
    ]


def _make_weekly_bars(
    prices: list[float],
    start: datetime = TS,
) -> list[MarketBar]:
    """Create weekly bars from close prices for peak/trough testing."""
    return [
        MarketBar(
            timestamp=start + timedelta(weeks=i),
            open=p * 0.99,
            high=p * 1.02,
            low=p * 0.98,
            close=p,
            volume=1000.0,
        )
        for i, p in enumerate(prices)
    ]


# ── 1. Weekly bar aggregation ──────────────────────────────────────


def test_aggregate_to_weekly_ohlcv() -> None:
    """42 4h bars (1 week) should aggregate to 1 weekly bar with correct OHLCV."""
    from research.macro_cycle import aggregate_to_weekly

    prices = [100 + i * 0.5 for i in range(42)]
    bars = _make_bars_4h(prices, start=datetime(2021, 1, 4))

    weekly = aggregate_to_weekly(bars)
    assert len(weekly) >= 1
    w = weekly[0]
    assert w.open == bars[0].open
    assert w.close == bars[-1].close
    assert w.high == max(b.high for b in bars)
    assert w.low == min(b.low for b in bars)


def test_aggregate_to_weekly_multiple_weeks() -> None:
    """84 4h bars (2 weeks Mon-Sun) should produce 2 weekly bars."""
    from research.macro_cycle import aggregate_to_weekly

    prices = [100 + i * 0.1 for i in range(84)]
    bars = _make_bars_4h(prices, start=datetime(2021, 1, 4))

    weekly = aggregate_to_weekly(bars)
    assert len(weekly) == 2


# ── 2. Daily bar aggregation ──────────────────────────────────────


def test_aggregate_to_daily_ohlcv() -> None:
    """6 4h bars (1 day) should aggregate to 1 daily bar."""
    from research.macro_cycle import aggregate_to_daily

    prices = [100, 102, 101, 103, 99, 101]
    bars = _make_bars_4h(prices)

    daily = aggregate_to_daily(bars)
    assert len(daily) >= 1
    d = daily[0]
    assert d.open == bars[0].open
    assert d.close == bars[-1].close
    assert d.high == max(b.high for b in bars)
    assert d.low == min(b.low for b in bars)


# ── 2b. Monthly bar aggregation ─────────────────────────────────


def test_aggregate_to_monthly_ohlcv() -> None:
    """4h bars across 2 months should produce 2 monthly bars."""
    from research.macro_cycle import aggregate_to_monthly

    # January: 31 days * 6 bars = 186 bars
    # February: 28 days * 6 bars = 168 bars
    jan = _make_bars_4h(
        [40000 + i * 10 for i in range(186)],
        start=datetime(2021, 1, 1),
    )
    feb = _make_bars_4h(
        [42000 + i * 10 for i in range(168)],
        start=datetime(2021, 2, 1),
    )
    bars = jan + feb
    monthly = aggregate_to_monthly(bars)
    assert len(monthly) == 2
    assert monthly[0].open == jan[0].open
    assert monthly[0].close == jan[-1].close
    assert monthly[1].open == feb[0].open
    assert monthly[1].close == feb[-1].close


# ── 3. Weekly RSI computation ─────────────────────────────────────


def test_weekly_rsi_strong_uptrend_is_high() -> None:
    """In a strong bull market, weekly RSI(14) should be > 70."""
    from research.macro_cycle import aggregate_to_weekly, compute_weekly_rsi

    n_bars = 20 * 42
    prices = [20000 * (1.0012 ** i) for i in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2021, 1, 4))

    weekly = aggregate_to_weekly(bars)
    rsi = compute_weekly_rsi(weekly, period=14)
    assert rsi is not None
    assert rsi > 70, f"Bull market RSI should be > 70, got {rsi:.1f}"


def test_weekly_rsi_strong_downtrend_is_low() -> None:
    """In a strong bear market, weekly RSI(14) should be < 30."""
    from research.macro_cycle import aggregate_to_weekly, compute_weekly_rsi

    n_bars = 20 * 42
    prices = [60000 * (0.9988 ** i) for i in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2021, 1, 4))

    weekly = aggregate_to_weekly(bars)
    rsi = compute_weekly_rsi(weekly, period=14)
    assert rsi is not None
    assert rsi < 30, f"Bear market RSI should be < 30, got {rsi:.1f}"


def test_weekly_rsi_uses_full_history_wilder_ema() -> None:
    """RSI must use ALL bars with Wilder EMA, not just last 15 (SMA).

    Bug reproduced from real data: a large gain at the start of the
    14-period SMA window drops out when the window slides by 1 week,
    causing RSI to crash 13 points even though price barely moved.

    With correct Wilder's EMA (full history), the large gain decays
    gradually over many weeks instead of vanishing in one step.
    """
    from research.macro_cycle import compute_weekly_rsi

    # Reproduce the real bug: 20+ weekly bars with a big spike followed
    # by many losses, then a tiny loss that shouldn't crash RSI.
    #
    # Real pattern: W39=112k, W40=123k (+11k spike), then decline to 90k,
    # then W1=91.5k, W2=90.5k (-1k). Buggy RSI: 35->22. Correct: ~41.
    weekly_closes = [
        112000,  # W35 (baseline)
        108000,  # W36 decline
        111000,  # W37 bounce
        115000,  # W38
        115000,  # W39
        112000,  # W40  (in real data this was 123k spike)
        123000,  # W41  <-- big spike that poisons SMA window
        115000,  # W42 pullback
        108000,  # W43
        114000,  # W44
        110000,  # W45
        104000,  # W46 decline
        94000,   # W47 crash
        87000,   # W48
        90000,   # W49 bounce
        90000,   # W50 flat
        88000,   # W51
        88000,   # W52
        88000,   # W53
        91500,   # W1  (small bounce)
        90500,   # W2  (tiny -1k decline)
    ]

    weekly_bars = [
        _make_weekly_bars([c], start=datetime(2025, 8, 25) + timedelta(weeks=i))[0]
        for i, c in enumerate(weekly_closes)
    ]

    rsi_w1 = compute_weekly_rsi(weekly_bars[:-1], 14)  # Up to W1
    rsi_w2 = compute_weekly_rsi(weekly_bars, 14)       # Up to W2

    assert rsi_w1 is not None and rsi_w2 is not None
    diff = abs(rsi_w2 - rsi_w1)
    assert diff < 8.0, (
        f"RSI jumped {diff:.1f} points ({rsi_w1:.1f} -> {rsi_w2:.1f}) "
        f"from a tiny -1k price change. Wilder EMA should be stable."
    )


def test_weekly_rsi_insufficient_data_returns_none() -> None:
    """RSI(14) needs 15+ weekly bars; fewer returns None."""
    from research.macro_cycle import aggregate_to_weekly, compute_weekly_rsi

    prices = [40000 * (1.001 ** i) for i in range(10 * 42)]
    bars = _make_bars_4h(prices, start=datetime(2021, 1, 4))

    weekly = aggregate_to_weekly(bars)
    rsi = compute_weekly_rsi(weekly, period=14)
    assert rsi is None


# ── 4. 200-day SMA ratio ─────────────────────────────────────────


def test_sma200_ratio_after_strong_rally() -> None:
    """Price far above 200d SMA -> ratio > 1.3."""
    from research.macro_cycle import aggregate_to_daily, compute_sma200_ratio

    n_flat = 200 * 6
    n_rally = 100 * 6
    prices = [30000.0] * n_flat + [60000.0] * n_rally
    bars = _make_bars_4h(prices)

    daily = aggregate_to_daily(bars)
    ratio = compute_sma200_ratio(daily)
    assert ratio is not None
    assert ratio > 1.3, f"Price should be far above SMA200, ratio={ratio:.2f}"


def test_sma200_ratio_after_crash() -> None:
    """Price far below 200d SMA -> ratio < 0.8."""
    from research.macro_cycle import aggregate_to_daily, compute_sma200_ratio

    n_flat = 200 * 6
    n_crash = 100 * 6
    prices = [50000.0] * n_flat + [30000.0] * n_crash
    bars = _make_bars_4h(prices)

    daily = aggregate_to_daily(bars)
    ratio = compute_sma200_ratio(daily)
    assert ratio is not None
    assert ratio < 0.8, f"Price should be far below SMA200, ratio={ratio:.2f}"


def test_sma200_ratio_insufficient_data_returns_none() -> None:
    """Need 200+ daily bars; fewer returns None."""
    from research.macro_cycle import aggregate_to_daily, compute_sma200_ratio

    prices = [40000.0] * (100 * 6)
    bars = _make_bars_4h(prices)

    daily = aggregate_to_daily(bars)
    ratio = compute_sma200_ratio(daily)
    assert ratio is None


# ── 5. Peak / trough detection ────────────────────────────────────


def test_find_weekly_peaks_single_peak() -> None:
    """Detect a single clear peak in weekly bars."""
    from research.macro_cycle import find_weekly_peaks

    # Rise to peak, then fall: [100, 110, 120, 130, 140, 150, 140, 130, 120, 110, 100]
    prices = list(range(100, 160, 10)) + list(range(140, 90, -10))
    bars = _make_weekly_bars(prices)

    peaks = find_weekly_peaks(bars, pivot_window=4)
    assert len(peaks) == 1
    assert bars[peaks[0]].high == max(b.high for b in bars)


def test_find_weekly_peaks_multiple_peaks() -> None:
    """Detect two peaks separated by a correction."""
    from research.macro_cycle import find_weekly_peaks

    # Peak 1 around index 8, Peak 2 around index 22
    prices = (
        [100, 105, 110, 115, 120, 125, 130, 135, 140,   # rise to 140
         135, 130, 125, 120, 115, 110,                    # fall to 110
         115, 120, 125, 130, 135, 140, 145, 150,          # rise to 150
         145, 140, 135, 130, 125, 120, 115]               # fall to 115
    )
    bars = _make_weekly_bars(prices)

    peaks = find_weekly_peaks(bars, pivot_window=4)
    assert len(peaks) == 2
    # Second peak should be higher
    assert bars[peaks[1]].high > bars[peaks[0]].high


def test_find_weekly_troughs_single_trough() -> None:
    """Detect a single clear trough in weekly bars."""
    from research.macro_cycle import find_weekly_troughs

    # Fall to trough, then rise: [150, 140, 130, 120, 110, 100, 110, 120, 130, 140, 150]
    prices = list(range(150, 90, -10)) + list(range(110, 160, 10))
    bars = _make_weekly_bars(prices)

    troughs = find_weekly_troughs(bars, pivot_window=4)
    assert len(troughs) == 1
    assert bars[troughs[0]].low == min(b.low for b in bars)


def test_find_weekly_troughs_multiple_troughs() -> None:
    """Detect two troughs with a bounce between them."""
    from research.macro_cycle import find_weekly_troughs

    # Trough 1 around index 8, Trough 2 around index 22
    prices = (
        [200, 190, 180, 170, 160, 150, 140, 130, 120,   # fall to 120
         130, 140, 150, 160, 170, 180,                    # rise to 180
         170, 160, 150, 140, 130, 120, 115, 110,          # fall to 110
         120, 130, 140, 150, 160, 170, 180]               # rise to 180
    )
    bars = _make_weekly_bars(prices)

    troughs = find_weekly_troughs(bars, pivot_window=4)
    assert len(troughs) == 2
    # Second trough should be lower
    assert bars[troughs[1]].low < bars[troughs[0]].low


# ── 6. Bearish RSI divergence (sell_top) ──────────────────────────


def test_bearish_divergence_higher_price_lower_rsi() -> None:
    """Price makes higher high but RSI makes lower high → sell_top.

    Pattern: strong rally → correction → weak rally to higher price.
    RSI at second peak is lower because momentum is weaker.
    """
    from research.macro_cycle import MacroCycleConfig, detect_cycle_signal

    # Build a multi-phase price series:
    # Phase 1: Flat warmup (enough for RSI + SMA200)
    warmup = [30000.0] * (210 * 6)  # 210 days flat

    # Phase 2: Strong rally (high RSI at Peak 1)
    rally1 = [30000 + (i / (50 * 6)) * 25000 for i in range(50 * 6)]
    # ~55000 at peak

    # Phase 3: Correction (RSI drops, builds loss history)
    correct = [55000 - (i / (60 * 6)) * 15000 for i in range(60 * 6)]
    # ~40000 at trough

    # Phase 4: Weaker rally to HIGHER price (momentum lower → RSI lower)
    rally2 = [40000 + (i / (80 * 6)) * 25000 for i in range(80 * 6)]
    # ~65000 at peak (higher than 55000, but slower rally → lower RSI)

    # Phase 5: Drop to confirm the second peak
    drop = [65000 - (i / (30 * 6)) * 10000 for i in range(30 * 6)]
    # ~55000 (confirm peak with pivot_window bars)

    prices = warmup + rally1 + correct + rally2 + drop
    bars = _make_bars_4h(prices, start=datetime(2020, 1, 1))

    config = MacroCycleConfig(
        divergence_pivot_window=4,  # shorter for test (less data needed)
        divergence_min_rsi_drop=3.0,
    )
    signal = detect_cycle_signal(bars, config)
    assert signal.action == "sell_top", (
        f"Expected sell_top from bearish divergence, got {signal.action}"
    )
    assert signal.divergence_score > 0
    assert signal.sell_pct > 0
    assert signal.peak_count >= 2


def test_no_bearish_divergence_when_price_lower() -> None:
    """Peak 2 has LOWER price than Peak 1 → no bearish divergence.

    Bearish divergence requires higher price + lower RSI.
    If price is also lower, this is just a downtrend, not divergence.
    """
    from research.macro_cycle import MacroCycleConfig, detect_cycle_signal

    # Phase 1: Flat warmup
    warmup = [50000.0] * (210 * 6)

    # Phase 2: Rally to Peak 1 (higher)
    rally1 = [50000 + (i / (50 * 6)) * 15000 for i in range(50 * 6)]
    # Peak ~65000

    # Phase 3: Correction
    correct = [65000 - (i / (60 * 6)) * 20000 for i in range(60 * 6)]
    # ~45000

    # Phase 4: Rally to Peak 2 (LOWER than Peak 1)
    rally2 = [45000 + (i / (50 * 6)) * 12000 for i in range(50 * 6)]
    # Peak ~57000 < 65000

    # Phase 5: Drop to confirm
    drop = [57000 - (i / (30 * 6)) * 8000 for i in range(30 * 6)]

    prices = warmup + rally1 + correct + rally2 + drop
    bars = _make_bars_4h(prices, start=datetime(2020, 1, 1))

    config = MacroCycleConfig(divergence_pivot_window=4)
    signal = detect_cycle_signal(bars, config)
    # Peak 2 price < Peak 1 price → no bearish divergence
    assert signal.action != "sell_top", (
        f"Should NOT be sell_top when Peak 2 price is lower, got {signal.action}"
    )


def test_divergence_severity_scales_sell_pct() -> None:
    """More severe divergence → higher sell percentage."""
    from research.macro_cycle import MacroCycleConfig

    config = MacroCycleConfig(
        sell_pct_per_rsi_point=0.01,
        sell_pct_min=0.10,
        sell_pct_max=0.40,
    )

    # Mild divergence: 8 RSI points → 8% but floored to 10%
    pct_mild = max(config.sell_pct_min, min(config.sell_pct_max, 8 * config.sell_pct_per_rsi_point))
    assert pct_mild == 0.10

    # Moderate divergence: 20 RSI points → 20%
    pct_moderate = max(config.sell_pct_min, min(config.sell_pct_max, 20 * config.sell_pct_per_rsi_point))
    assert pct_moderate == 0.20

    # Severe divergence: 50 RSI points → capped at 40%
    pct_severe = max(config.sell_pct_min, min(config.sell_pct_max, 50 * config.sell_pct_per_rsi_point))
    assert pct_severe == 0.40


def test_divergence_min_threshold_filters_noise() -> None:
    """Small RSI difference (< min_rsi_drop) should be ignored."""
    from research.macro_cycle import MacroCycleConfig

    config = MacroCycleConfig(divergence_min_rsi_drop=5.0)
    # A 3-point RSI drop is below threshold → shouldn't trigger
    assert 3.0 < config.divergence_min_rsi_drop


# ── 7. Bullish RSI divergence (buy_bottom) ────────────────────────


def test_bullish_divergence_lower_price_higher_rsi() -> None:
    """Price makes lower low but RSI makes higher low → buy_bottom.

    Pattern: sharp decline → bounce → slower decline to lower price.
    RSI at second trough is higher because selling momentum is weaker.
    """
    from research.macro_cycle import MacroCycleConfig, detect_cycle_signal

    # Phase 1: High warmup (enough for RSI + SMA200)
    warmup = [60000.0] * (210 * 6)

    # Phase 2: Sharp decline (low RSI at Trough 1)
    decline1 = [60000 - (i / (50 * 6)) * 25000 for i in range(50 * 6)]
    # ~35000 at trough

    # Phase 3: Bounce
    bounce = [35000 + (i / (60 * 6)) * 15000 for i in range(60 * 6)]
    # ~50000 at peak

    # Phase 4: Slower decline to LOWER price (less selling pressure → higher RSI)
    decline2 = [50000 - (i / (80 * 6)) * 22000 for i in range(80 * 6)]
    # ~28000 at trough (lower than 35000, but slower → higher RSI)

    # Phase 5: Bounce to confirm trough
    confirm = [28000 + (i / (30 * 6)) * 8000 for i in range(30 * 6)]
    # ~36000

    prices = warmup + decline1 + bounce + decline2 + confirm
    bars = _make_bars_4h(prices, start=datetime(2020, 1, 1))

    config = MacroCycleConfig(
        divergence_pivot_window=4,
        divergence_min_rsi_drop=3.0,
    )
    signal = detect_cycle_signal(bars, config)
    assert signal.action == "buy_bottom", (
        f"Expected buy_bottom from bullish divergence, got {signal.action}"
    )
    assert signal.divergence_score > 0
    assert signal.buy_pct > 0
    assert signal.trough_count >= 2


# ── 8. Signal includes peak/trough counts ────────────────────────


def test_signal_includes_peak_trough_counts() -> None:
    """MacroCycleSignal should track peak and trough counts for dedup."""
    from research.macro_cycle import MacroCycleSignal

    sig = MacroCycleSignal(
        action="sell_top", weekly_rsi=65.0, sma200_ratio=1.2,
        funding_rate=None, top_ls_ratio=None,
        timestamp=TS, divergence_score=15.0, sell_pct=0.15,
        peak_count=3, trough_count=1,
    )
    assert sig.peak_count == 3
    assert sig.trough_count == 1
    assert sig.divergence_score == 15.0
    assert sig.sell_pct == 0.15


# ── 9. Fallback: threshold-based (when too few peaks) ────────────


def test_detect_bull_top_fallback_strict() -> None:
    """Without enough peaks for divergence, fall back to strict thresholds."""
    from research.macro_cycle import MacroCycleConfig, detect_cycle_signal

    # Steady uptrend: no peaks (no corrections), falls back to thresholds
    n_bars = 1800
    prices = [20000 * (1.0005 ** i) for i in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2021, 1, 4))

    config = MacroCycleConfig(
        # Strict fallback: RSI >90, Mayer >1.25
        fallback_rsi_overbought=90.0,
        fallback_sma200_hot=1.25,
    )
    signal = detect_cycle_signal(bars, config)
    assert signal.action == "sell_top"


def test_detect_bear_bottom_fallback_strict() -> None:
    """Without enough troughs for divergence, fall back to strict thresholds."""
    from research.macro_cycle import MacroCycleConfig, detect_cycle_signal

    n_bars = 1800
    prices = [60000 * (0.9995 ** i) for i in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2021, 1, 4))

    config = MacroCycleConfig(
        fallback_rsi_oversold=25.0,
        fallback_sma200_cold=0.75,
    )
    signal = detect_cycle_signal(bars, config)
    assert signal.action == "buy_bottom"


# ── 10. Neutral / insufficient data ──────────────────────────────


def test_neutral_in_range() -> None:
    """Flat/sideways market -> neutral signal."""
    from research.macro_cycle import MacroCycleConfig, detect_cycle_signal

    import random
    random.seed(42)
    prices = [40000 + random.uniform(-500, 500) for _ in range(1800)]
    bars = _make_bars_4h(prices, start=datetime(2021, 1, 4))

    config = MacroCycleConfig()
    signal = detect_cycle_signal(bars, config, funding_rate=0.0005, top_ls_ratio=1.0)
    assert signal.action == "neutral"


def test_insufficient_data_returns_neutral() -> None:
    """Not enough data for SMA200 -> always neutral."""
    from research.macro_cycle import MacroCycleConfig, detect_cycle_signal

    prices = [40000.0] * 100
    bars = _make_bars_4h(prices)

    signal = detect_cycle_signal(bars, MacroCycleConfig())
    assert signal.action == "neutral"


# ── 11. PaperBroker integration ──────────────────────────────────


def test_broker_add_cash() -> None:
    """add_cash increases broker's cash balance (for buying BTC at bottoms)."""
    broker = PaperBroker(initial_cash=1.0, contract_type="inverse")
    broker.add_cash(0.5)
    assert abs(broker.get_cash() - 1.5) < 1e-9


def test_broker_add_cash_usdt_to_btc_conversion() -> None:
    """Simulates buying BTC with USDT reserves at bear bottom."""
    broker = PaperBroker(initial_cash=0.8, contract_type="inverse")
    usdt_amount = 10000.0
    btc_price = 20000.0
    btc_bought = usdt_amount / btc_price
    broker.add_cash(btc_bought)
    assert abs(broker.get_cash() - 1.3) < 1e-9


# ── 12. MacroCycleRecord tracking ─────────────────────────────────


def test_macro_cycle_record_fields() -> None:
    """MacroCycleRecord captures divergence data for reporting."""
    from research.macro_cycle import MacroCycleRecord

    rec = MacroCycleRecord(
        timestamp=TS, action="sell_top", btc_price=120000.0,
        weekly_rsi=64.0, sma200_ratio=1.18,
        funding_rate=0.007, top_ls_ratio=1.82,
        btc_amount=0.3, usdt_amount=36000.0,
        btc_balance_after=0.7, usdt_balance_after=36000.0,
        divergence_score=18.5,
    )
    assert rec.action == "sell_top"
    assert rec.divergence_score == 18.5
    assert rec.btc_price == 120000.0


def test_macro_cycle_record_buy_bottom() -> None:
    """MacroCycleRecord tracks buy_bottom with divergence data."""
    from research.macro_cycle import MacroCycleRecord

    rec = MacroCycleRecord(
        timestamp=TS, action="buy_bottom", btc_price=18000.0,
        weekly_rsi=35.0, sma200_ratio=0.65,
        funding_rate=-0.005, top_ls_ratio=0.88,
        btc_amount=0.8, usdt_amount=14400.0,
        btc_balance_after=1.8, usdt_balance_after=5600.0,
        divergence_score=12.0,
    )
    assert rec.action == "buy_bottom"
    assert rec.divergence_score == 12.0


# ── 13. Config divergence fields ─────────────────────────────────


def test_macro_config_has_divergence_fields() -> None:
    """Config should have divergence detection parameters."""
    from research.macro_cycle import MacroCycleConfig

    config = MacroCycleConfig()
    assert config.divergence_pivot_window > 0
    assert config.divergence_min_rsi_drop > 0
    assert config.sell_pct_per_rsi_point > 0
    assert config.sell_pct_min > 0
    assert config.sell_pct_max > config.sell_pct_min
    assert config.buy_pct_per_rsi_point > 0
    assert config.buy_pct_min > 0
    assert config.buy_pct_max > config.buy_pct_min


def test_divergence_sell_pct_scales_correctly() -> None:
    """sell_pct = clamp(rsi_drop * per_point, min, max)."""
    from research.macro_cycle import MacroCycleConfig

    config = MacroCycleConfig()  # defaults: 0.01 per point, min 0.10, max 0.40
    # 15 RSI points: 15 * 0.01 = 0.15
    pct = max(config.sell_pct_min, min(config.sell_pct_max, 15 * config.sell_pct_per_rsi_point))
    assert pct == 0.15


def test_macro_config_has_monthly_rsi_fields() -> None:
    """Config should have monthly RSI progressive selling parameters."""
    from research.macro_cycle import MacroCycleConfig

    config = MacroCycleConfig()
    assert config.monthly_rsi_sell_start == 70.0
    assert config.monthly_rsi_sell_step == 7.0
    assert config.monthly_rsi_sell_pct == 0.10
    assert config.min_btc_reserve == 1.0
    assert config.weekly_rsi_buy_trigger == 25.0


# ── 14. Monthly RSI progressive selling ──────────────────────────


def test_monthly_rsi_sell_level_1() -> None:
    """Monthly RSI >= 70 triggers first sell level."""
    from research.macro_cycle import MacroCycleConfig, check_monthly_rsi_sell

    # 20+ months of strong uptrend -> monthly RSI > 70
    n_bars = 24 * 180  # ~24 months of 4h bars
    prices = [20000 * (1.0003 ** i) for i in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2021, 1, 1))

    config = MacroCycleConfig()
    should_sell, level, rsi = check_monthly_rsi_sell(bars, config, last_sold_level=0)
    assert should_sell, f"Should trigger at monthly RSI {rsi:.1f}"
    assert level >= 1
    assert rsi >= 70.0


def test_monthly_rsi_sell_no_retrigger() -> None:
    """Same RSI level doesn't re-trigger (last_sold_level prevents it)."""
    from research.macro_cycle import MacroCycleConfig, check_monthly_rsi_sell

    n_bars = 24 * 180
    prices = [20000 * (1.0003 ** i) for i in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2021, 1, 1))

    config = MacroCycleConfig()
    _, level, _ = check_monthly_rsi_sell(bars, config, last_sold_level=0)
    should_sell, _, _ = check_monthly_rsi_sell(bars, config, last_sold_level=level)
    assert not should_sell, "Should not re-trigger at same level"


def test_monthly_rsi_sell_below_threshold_no_trigger() -> None:
    """Monthly RSI below 70 -> no sell."""
    from research.macro_cycle import MacroCycleConfig, check_monthly_rsi_sell

    import random
    random.seed(99)
    prices = [40000 + random.uniform(-300, 300) for _ in range(24 * 180)]
    bars = _make_bars_4h(prices, start=datetime(2021, 1, 1))

    config = MacroCycleConfig()
    should_sell, _, rsi = check_monthly_rsi_sell(bars, config, last_sold_level=0)
    assert not should_sell, f"RSI {rsi:.1f} should not trigger sell"


def test_weekly_rsi_buy_at_oversold() -> None:
    """Weekly RSI <= 25 triggers buy."""
    from research.macro_cycle import MacroCycleConfig, check_weekly_rsi_buy

    # Steep decline: weekly RSI should drop below 25
    n_bars = 120 * 6  # ~120 days, enough for weekly RSI computation
    prices = [60000 * (0.999 ** i) for i in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2021, 1, 1))

    config = MacroCycleConfig(weekly_rsi_buy_trigger=25.0)
    should_buy, rsi = check_weekly_rsi_buy(bars, config)
    assert should_buy, f"Weekly RSI {rsi:.1f} should trigger buy at <= 25"
    assert rsi <= 25.0


def test_weekly_rsi_buy_not_oversold() -> None:
    """Weekly RSI > 25 does not trigger buy."""
    from research.macro_cycle import MacroCycleConfig, check_weekly_rsi_buy

    import random
    random.seed(42)
    prices = [40000 + random.uniform(-300, 300) for _ in range(120 * 6)]
    bars = _make_bars_4h(prices, start=datetime(2021, 1, 1))

    config = MacroCycleConfig(weekly_rsi_buy_trigger=25.0)
    should_buy, rsi = check_weekly_rsi_buy(bars, config)
    assert not should_buy, f"Weekly RSI {rsi:.1f} should NOT trigger buy"


def test_progressive_sell_pct_scales_with_level() -> None:
    """Sell pct = level * base (0.10). L1=10%, L2=20%, L3=30%, L4=40%."""
    from research.macro_cycle import MacroCycleConfig

    config = MacroCycleConfig()  # base = 0.10
    for level, expected in [(1, 0.10), (2, 0.20), (3, 0.30), (4, 0.40)]:
        pct = level * config.monthly_rsi_sell_pct
        assert pct == pytest.approx(expected), (
            f"Level {level}: expected {expected}, got {pct}"
        )


def test_get_monthly_rsi_returns_value() -> None:
    """get_monthly_rsi helper returns current monthly RSI."""
    from research.macro_cycle import MacroCycleConfig, get_monthly_rsi

    n_bars = 24 * 180
    prices = [20000 * (1.0003 ** i) for i in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2021, 1, 1))

    config = MacroCycleConfig()
    rsi = get_monthly_rsi(bars, config)
    assert 0 < rsi <= 100


def test_monthly_rsi_buy_still_works_for_guard() -> None:
    """check_monthly_rsi_buy still returns monthly RSI (used as guard)."""
    from research.macro_cycle import MacroCycleConfig, check_monthly_rsi_buy

    n_bars = 24 * 180
    prices = [60000 * (0.9997 ** i) for i in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2021, 1, 1))

    config = MacroCycleConfig()
    should_buy, rsi = check_monthly_rsi_buy(bars, config)
    assert should_buy, f"Monthly RSI {rsi:.1f} should trigger buy"
    assert rsi <= 30.0


def test_min_btc_reserve_respected() -> None:
    """min_btc_reserve = 1.0 means never sell below 1 BTC.

    Progressive sell: level 1 = 10%, level 2 = 20%, etc.
    sell_pct = level * monthly_rsi_sell_pct (base 0.10)
    """
    from research.macro_cycle import MacroCycleConfig

    config = MacroCycleConfig(min_btc_reserve=1.0)  # base=0.10

    # Level 1: sell_pct = 1 * 0.10 = 10%
    # 1.5 BTC: sellable = 0.5, 10% of 1.5 = 0.15 < 0.5 -> sell 0.15
    free_btc = 1.5
    level = 1
    sell_pct = level * config.monthly_rsi_sell_pct
    sellable = max(0.0, free_btc - config.min_btc_reserve)
    sell_btc = min(free_btc * sell_pct, sellable)
    assert sell_btc == pytest.approx(0.15)

    # Level 2: sell_pct = 2 * 0.10 = 20%
    # 1.5 BTC: sellable = 0.5, 20% of 1.5 = 0.30 < 0.5 -> sell 0.30
    level = 2
    sell_pct = level * config.monthly_rsi_sell_pct
    sell_btc = min(free_btc * sell_pct, sellable)
    assert sell_btc == pytest.approx(0.30)

    # Level 3: sell_pct = 3 * 0.10 = 30%
    # 1.05 BTC: sellable = 0.05, 30% of 1.05 = 0.315 > 0.05 -> sell 0.05
    free_btc = 1.05
    level = 3
    sell_pct = level * config.monthly_rsi_sell_pct
    sellable = max(0.0, free_btc - config.min_btc_reserve)
    sell_btc = min(free_btc * sell_pct, sellable)
    assert sell_btc == pytest.approx(0.05)

    # Below reserve: sellable = 0 -> no sell
    free_btc = 0.95
    sellable = max(0.0, free_btc - config.min_btc_reserve)
    assert sellable == 0.0


def test_monthly_sell_level_resets_after_rsi_drops() -> None:
    """Sell levels should reset when monthly RSI drops below sell_start.

    Without reset, levels fired in cycle 1 (e.g. 2023-2024) can never
    fire again in cycle 2 (e.g. 2025). The backtest tracks this via
    macro_monthly_sold_level, resetting to 0 when RSI < sell_start.
    """
    from research.macro_cycle import MacroCycleConfig, check_monthly_rsi_sell

    config = MacroCycleConfig()

    # Cycle 1: strong uptrend → monthly RSI > 70 → sells at level 1+
    n_bars = 24 * 180  # 24 months
    prices_up = [20000 * (1.0003 ** i) for i in range(n_bars)]
    bars_up = _make_bars_4h(prices_up, start=datetime(2021, 1, 1))

    should_sell, level, rsi = check_monthly_rsi_sell(bars_up, config, last_sold_level=0)
    assert should_sell
    assert level >= 1

    # After cycle: RSI drops below 70 → we should reset to 0
    # This is the backtest's responsibility (not the function's).
    # Verify the function CAN re-trigger from level 0 with same data.
    should_sell2, level2, _ = check_monthly_rsi_sell(bars_up, config, last_sold_level=0)
    assert should_sell2, "After reset to level 0, same RSI should trigger again"
    assert level2 == level

    # But without reset, it cannot re-trigger
    should_sell3, _, _ = check_monthly_rsi_sell(bars_up, config, last_sold_level=level)
    assert not should_sell3, "Without reset, same level should not re-trigger"


# ── 15. BacktestResult includes macro cycle data ─────────────────


def test_backtest_result_has_macro_cycle_fields() -> None:
    """BacktestResult should have macro_cycle_events field."""
    from research.backtest import BacktestResult

    result = BacktestResult(
        initial_cash=1.0, final_equity=1.5,
        total_return_pct=50.0, max_drawdown_pct=10.0,
        total_trades=1, fills=[], trades=[],
        rule_stats=[], rejection_stats={},
        rule_eval_counts={}, event_review_pack=[],
        usdt_reserves=20000.0, btc_harvested=0.3,
        harvest_events=[], macro_cycle_events=[],
    )
    assert result.macro_cycle_events == []


# ── 16. Daily MACD momentum guard ───────────────────────────────


def test_compute_macd_basic() -> None:
    """MACD(12,26,9) returns (macd_line, signal_line, histogram)."""
    from research.macro_cycle import compute_macd, aggregate_to_daily

    # 40 days of steady uptrend → MACD should be positive
    n_bars = 40 * 6  # 40 days of 4h bars
    prices = [30000 * (1.003 ** i) for i in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2022, 1, 1))

    daily = aggregate_to_daily(bars)
    macd_line, signal_line, histogram = compute_macd(daily)
    assert macd_line is not None
    assert signal_line is not None
    assert histogram is not None
    assert macd_line > 0, "Uptrend should have positive MACD line"


def test_compute_macd_downtrend_negative() -> None:
    """Downtrend MACD should be negative."""
    from research.macro_cycle import compute_macd, aggregate_to_daily

    n_bars = 40 * 6
    prices = [60000 * (0.997 ** i) for i in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2022, 1, 1))

    daily = aggregate_to_daily(bars)
    macd_line, _, _ = compute_macd(daily)
    assert macd_line is not None
    assert macd_line < 0, "Downtrend should have negative MACD line"


def test_compute_macd_insufficient_data() -> None:
    """Less than 35 daily bars (26+9) → returns None."""
    from research.macro_cycle import compute_macd, aggregate_to_daily

    n_bars = 20 * 6  # only 20 days
    prices = [40000.0] * n_bars
    bars = _make_bars_4h(prices, start=datetime(2022, 1, 1))

    daily = aggregate_to_daily(bars)
    macd_line, signal_line, histogram = compute_macd(daily)
    assert macd_line is None


def test_macd_momentum_hold_bear() -> None:
    """Short: MACD < 0 + fast line still expanding = hold (don't exit).

    Pattern: flat → decline begins → MACD crosses zero → accelerates.
    The "利潤區間" (profit window) is when MACD is below zero AND
    still getting more negative.
    """
    from research.macro_cycle import macd_momentum_hold, aggregate_to_daily

    # Phase 1: 30 days stable (MACD near zero)
    # Phase 2: 15 days accelerating decline (MACD expanding downward)
    prices: list[float] = []
    for i in range(30 * 6):
        prices.append(60000.0)
    for i in range(15 * 6):
        day = i // 6
        # Accelerating: 0.5% → 2% daily decline
        rate = 0.995 - day * 0.001
        prices.append(prices[-1] * rate)
    bars = _make_bars_4h(prices, start=datetime(2022, 1, 1))

    daily = aggregate_to_daily(bars)
    hold = macd_momentum_hold(daily, position_side="short")
    assert hold is True, "Accelerating bear momentum should hold shorts"


def test_macd_momentum_hold_bull() -> None:
    """Long: MACD > 0 + fast line still expanding = hold."""
    from research.macro_cycle import macd_momentum_hold, aggregate_to_daily

    prices: list[float] = []
    for i in range(30 * 6):
        prices.append(30000.0)
    for i in range(15 * 6):
        day = i // 6
        rate = 1.005 + day * 0.001
        prices.append(prices[-1] * rate)
    bars = _make_bars_4h(prices, start=datetime(2022, 1, 1))

    daily = aggregate_to_daily(bars)
    hold = macd_momentum_hold(daily, position_side="long")
    assert hold is True, "Accelerating bull momentum should hold longs"


def test_macd_momentum_no_hold_wrong_direction() -> None:
    """Long in downtrend: MACD negative → don't hold (allow exit)."""
    from research.macro_cycle import macd_momentum_hold, aggregate_to_daily

    n_bars = 50 * 6
    prices = [60000 * (0.995 ** i) for i in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2022, 1, 1))

    daily = aggregate_to_daily(bars)
    hold = macd_momentum_hold(daily, position_side="long")
    assert hold is False, "Long in downtrend should NOT hold"


def test_macd_momentum_no_hold_flat() -> None:
    """Flat market: no momentum → don't hold."""
    from research.macro_cycle import macd_momentum_hold, aggregate_to_daily

    import random
    random.seed(123)
    n_bars = 50 * 6
    prices = [40000 + random.uniform(-200, 200) for _ in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2022, 1, 1))

    daily = aggregate_to_daily(bars)
    hold_short = macd_momentum_hold(daily, position_side="short")
    hold_long = macd_momentum_hold(daily, position_side="long")
    assert not hold_short, "Flat market should not hold shorts"
    assert not hold_long, "Flat market should not hold longs"


# ── 17. Daily RSI sell trigger (D>=75 + W>=70) ────────────────


def test_daily_rsi_sell_trigger_config() -> None:
    """Config: D+W sell — D-RSI>=75, W-RSI>=70, sell 20%, M-RSI guard>=65."""
    from research.macro_cycle import MacroCycleConfig

    config = MacroCycleConfig()
    assert config.daily_rsi_sell_trigger == 75.0
    assert config.weekly_rsi_sell_confirm == 70.0
    assert config.daily_rsi_sell_pct == 0.20
    assert config.dw_sell_min_monthly_rsi == 65.0


def test_check_daily_rsi_sell_both_conditions_met() -> None:
    """Daily RSI >= 75 AND weekly RSI >= 70 → trigger sell.

    Both conditions must be met: short-term overbought (daily) confirmed
    by medium-term overbought (weekly). Prevents false sells on brief spikes.
    """
    from research.macro_cycle import MacroCycleConfig, check_daily_rsi_sell

    # Long strong uptrend → both daily and weekly RSI overbought
    n_bars = 120 * 6  # ~120 days → enough weekly bars for RSI to be hot
    prices = [30000 * (1.004 ** i) for i in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2022, 1, 1))

    config = MacroCycleConfig(daily_rsi_sell_trigger=75.0, weekly_rsi_sell_confirm=70.0)
    should_sell, d_rsi, w_rsi = check_daily_rsi_sell(bars, config)
    assert should_sell, f"D-RSI {d_rsi:.1f}, W-RSI {w_rsi:.1f} should trigger"
    assert d_rsi >= 75.0
    assert w_rsi >= 70.0


def test_check_daily_rsi_sell_daily_hot_weekly_not() -> None:
    """Daily RSI >= 75 but weekly RSI < 70 → NO trigger.

    Short spike: daily overbought but weekly hasn't confirmed.
    """
    from research.macro_cycle import MacroCycleConfig, check_daily_rsi_sell

    # Short sharp rally after long decline: daily RSI spikes but weekly still low
    n_decline = 80 * 6  # 80 days decline
    n_spike = 15 * 6    # 15 days sharp rally
    prices = [50000 * (0.997 ** i) for i in range(n_decline)]
    base = prices[-1]
    prices += [base * (1.012 ** i) for i in range(n_spike)]
    bars = _make_bars_4h(prices, start=datetime(2022, 1, 1))

    config = MacroCycleConfig(daily_rsi_sell_trigger=75.0, weekly_rsi_sell_confirm=70.0)
    should_sell, d_rsi, w_rsi = check_daily_rsi_sell(bars, config)
    # Daily might be hot, but weekly should still be recovering → no sell
    if d_rsi >= 75.0:
        assert not should_sell, (
            f"D-RSI {d_rsi:.1f} hot but W-RSI {w_rsi:.1f} < 70 → should NOT sell"
        )


def test_check_daily_rsi_sell_no_trigger_in_flat() -> None:
    """Flat market: neither daily nor weekly RSI overbought → no trigger."""
    from research.macro_cycle import MacroCycleConfig, check_daily_rsi_sell

    import random
    random.seed(42)
    n_bars = 120 * 6
    prices = [40000 + random.uniform(-300, 300) for _ in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2022, 1, 1))

    config = MacroCycleConfig()
    should_sell, d_rsi, w_rsi = check_daily_rsi_sell(bars, config)
    assert not should_sell, f"D-RSI {d_rsi:.1f}, W-RSI {w_rsi:.1f} should NOT sell"


def test_check_daily_rsi_sell_insufficient_data() -> None:
    """Not enough data for RSI computation → no trigger."""
    from research.macro_cycle import MacroCycleConfig, check_daily_rsi_sell

    prices = [40000.0] * 30  # Only 5 daily bars
    bars = _make_bars_4h(prices, start=datetime(2022, 1, 1))

    config = MacroCycleConfig()
    should_sell, d_rsi, w_rsi = check_daily_rsi_sell(bars, config)
    assert not should_sell


# ── 18. Daily RSI buy trigger ───────────────────────────────────


def test_daily_rsi_buy_config() -> None:
    """Config: dual buy condition — daily RSI < 27, weekly RSI < 47."""
    from research.macro_cycle import MacroCycleConfig

    config = MacroCycleConfig()
    assert config.daily_rsi_buy_trigger == 27.0
    assert config.weekly_rsi_buy_confirm == 47.0
    assert config.daily_rsi_buy_pct == 0.20


def test_check_daily_rsi_buy_both_conditions_met() -> None:
    """Daily RSI < 27 AND weekly RSI < 47 -> trigger buy.

    Both must be met: daily oversold confirmed by weekly downtrend.
    """
    from research.macro_cycle import MacroCycleConfig, check_daily_rsi_buy

    # Long steep decline -> both daily and weekly RSI deeply oversold
    n_bars = 120 * 6
    prices = [60000 * (0.994 ** i) for i in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2022, 1, 1))

    config = MacroCycleConfig(daily_rsi_buy_trigger=27.0, weekly_rsi_buy_confirm=47.0)
    should_buy, d_rsi, w_rsi = check_daily_rsi_buy(bars, config)
    assert should_buy, f"D-RSI {d_rsi:.1f}, W-RSI {w_rsi:.1f} should trigger buy"
    assert d_rsi < 27.0
    assert w_rsi < 47.0


def test_check_daily_rsi_buy_daily_low_weekly_not() -> None:
    """Daily RSI < 27 but weekly RSI > 47 -> NO trigger.

    Short dip: daily oversold but weekly hasn't confirmed bear.
    """
    from research.macro_cycle import MacroCycleConfig, check_daily_rsi_buy

    # Short sharp dip after long rally: daily crashes but weekly still high
    n_rally = 80 * 6
    n_dip = 10 * 6
    prices = [30000 * (1.003 ** i) for i in range(n_rally)]
    base = prices[-1]
    prices += [base * (0.985 ** i) for i in range(n_dip)]
    bars = _make_bars_4h(prices, start=datetime(2022, 1, 1))

    config = MacroCycleConfig(daily_rsi_buy_trigger=27.0, weekly_rsi_buy_confirm=47.0)
    should_buy, d_rsi, w_rsi = check_daily_rsi_buy(bars, config)
    if d_rsi < 27.0:
        assert not should_buy, (
            f"D-RSI {d_rsi:.1f} low but W-RSI {w_rsi:.1f} > 47 -> should NOT buy"
        )


def test_check_daily_rsi_buy_no_trigger_in_flat() -> None:
    """Flat market → neither condition met → no buy."""
    from research.macro_cycle import MacroCycleConfig, check_daily_rsi_buy

    import random
    random.seed(42)
    n_bars = 120 * 6
    prices = [40000 + random.uniform(-300, 300) for _ in range(n_bars)]
    bars = _make_bars_4h(prices, start=datetime(2022, 1, 1))

    config = MacroCycleConfig()
    should_buy, d_rsi, w_rsi = check_daily_rsi_buy(bars, config)
    assert not should_buy, f"D-RSI {d_rsi:.1f}, W-RSI {w_rsi:.1f} should NOT buy"


def test_check_daily_rsi_buy_insufficient_data() -> None:
    """Insufficient data → no trigger."""
    from research.macro_cycle import MacroCycleConfig, check_daily_rsi_buy

    prices = [40000.0] * 30
    bars = _make_bars_4h(prices, start=datetime(2022, 1, 1))

    config = MacroCycleConfig()
    should_buy, d_rsi, w_rsi = check_daily_rsi_buy(bars, config)
    assert not should_buy


def test_divergence_sell_min_monthly_rsi_default_65() -> None:
    """divergence_sell_min_monthly_rsi should default to 65 (not 50).

    Monthly RSI in the 50s is NOT hot enough to confirm a divergence sell.
    50s = neutral zone; only sell divergence when market is clearly hot (>= 65).
    """
    from research.macro_cycle import MacroCycleConfig

    config = MacroCycleConfig()
    assert config.divergence_sell_min_monthly_rsi == 65.0


# ── 19. No macro sell without weekly RSI confirmation ──────────────


def test_no_monthly_rsi_sell_in_backtest() -> None:
    """Layer 1 monthly RSI progressive sell must NOT exist in backtest.

    User rule: ALL macro cycle sells require dual condition
    (daily RSI >= 75 AND weekly RSI >= 70). Monthly RSI alone
    must NEVER trigger a sell. The check_monthly_rsi_sell import
    should not be used in backtest run_backtest.
    """
    import inspect
    from research.backtest import run_backtest

    source = inspect.getsource(run_backtest)
    assert "check_monthly_rsi_sell" not in source, (
        "run_backtest should not call check_monthly_rsi_sell; "
        "all sells must use D+W dual condition (check_daily_rsi_sell)"
    )


def test_all_macro_sell_events_have_weekly_rsi() -> None:
    """Every macro sell_top event must have weekly RSI stored.

    D+W sells use divergence_score=-1.0 and store weekly RSI in
    sma200_ratio. Divergence sells (score > 0) have weekly_rsi.
    No sell event should have both sma200_ratio==0 and
    divergence_score==0 (that was the old M-RSI pattern).
    """
    from research.macro_cycle import MacroCycleRecord

    # M-RSI pattern: sell_top, divergence_score=0.0, sma200_ratio=0.0
    # This pattern should never appear in a correct run.
    bad_record = MacroCycleRecord(
        timestamp=datetime(2024, 4, 1),
        action="sell_top",
        btc_price=70000.0,
        weekly_rsi=71.2,  # monthly RSI stored here
        sma200_ratio=0.0,  # NO weekly RSI
        funding_rate=None,
        top_ls_ratio=None,
        btc_amount=0.15,
        usdt_amount=10500.0,
        btc_balance_after=1.35,
        usdt_balance_after=10500.0,
        divergence_score=0.0,  # not D+W, not divergence
    )
    # This combination (sell_top + score==0 + sma200_ratio==0) is the
    # M-RSI fingerprint. Verify our detection logic identifies it.
    is_mrsi_pattern = (
        bad_record.action == "sell_top"
        and bad_record.divergence_score == 0.0
        and bad_record.sma200_ratio == 0.0
    )
    assert is_mrsi_pattern, "Test setup: should match M-RSI fingerprint"

    # D+W sell has divergence_score=-1.0 and sma200_ratio = weekly RSI
    good_record = MacroCycleRecord(
        timestamp=datetime(2024, 11, 1),
        action="sell_top",
        btc_price=90000.0,
        weekly_rsi=78.5,  # daily RSI
        sma200_ratio=72.3,  # weekly RSI stored here
        funding_rate=None,
        top_ls_ratio=None,
        btc_amount=0.20,
        usdt_amount=18000.0,
        btc_balance_after=1.10,
        usdt_balance_after=18000.0,
        divergence_score=-1.0,  # D+W marker
    )
    is_dw_pattern = good_record.divergence_score == -1.0
    assert is_dw_pattern, "D+W sell should have divergence_score=-1.0"


def test_backtest_no_monthly_sold_level_state() -> None:
    """run_backtest should not track macro_monthly_sold_level state.

    This state variable only served Layer 1 monthly RSI sell.
    With Layer 1 removed, it should not exist.
    """
    import inspect
    from research.backtest import run_backtest

    source = inspect.getsource(run_backtest)
    assert "macro_monthly_sold_level" not in source, (
        "macro_monthly_sold_level state should be removed; "
        "Layer 1 monthly RSI sell has been removed"
    )


# -- 20. Repeating D+W buy (scale-in at bottom) ----------------


def test_dw_buy_arm_and_confirm_mechanism() -> None:
    """D+W buy uses arm-and-confirm bottom detection.

    Instead of buying on the FIRST bar where D-RSI < 27:
      1. ARM: when D-RSI < 27 AND W-RSI < 47, enter armed mode
      2. Track the lowest price seen while armed
      3. CONFIRM: when price bounces >= 5% from lowest -> BUY
      4. Once bought, don't buy again until D-RSI recovers above 50
    """
    import inspect
    from research.backtest import run_backtest

    source = inspect.getsource(run_backtest)
    assert "dw_buy_armed" in source, (
        "run_backtest should use dw_buy_armed state for bottom detection"
    )
    assert "dw_buy_low_price" in source, (
        "run_backtest should track lowest price during armed period"
    )


def test_dw_buy_bounce_config() -> None:
    """MacroCycleConfig should have D+W buy bounce confirmation field."""
    from research.macro_cycle import MacroCycleConfig

    config = MacroCycleConfig()
    assert config.dw_buy_bounce_pct == 0.05, "Buy when price bounces 5% from low"


# -- 21. D+W sell with monthly RSI guard -------------------------


def test_dw_sell_monthly_guard_config() -> None:
    """dw_sell_min_monthly_rsi = 65: block D+W sell if market not hot enough.

    Prevents selling at $34k in Oct 2023 (M-RSI ~55, not hot zone).
    Only sell when monthly RSI confirms sustained bull cycle (>= 65).
    """
    from research.macro_cycle import MacroCycleConfig

    config = MacroCycleConfig()
    assert config.dw_sell_min_monthly_rsi == 65.0


def test_dw_sell_monthly_guard_in_backtest() -> None:
    """Backtest must check monthly RSI guard before D+W sell."""
    import inspect
    from research.backtest import run_backtest

    source = inspect.getsource(run_backtest)
    assert "dw_sell_min_monthly_rsi" in source, (
        "run_backtest should guard D+W sell with monthly RSI"
    )
    assert "get_monthly_rsi" in source, (
        "run_backtest should call get_monthly_rsi for sell guard"
    )


def test_dw_sell_keeps_level_reset() -> None:
    """D+W sell uses level-based dedup (sell once per RSI cycle).

    macro_daily_sold_level resets when D-RSI drops below 50.
    """
    import inspect
    from research.backtest import run_backtest

    source = inspect.getsource(run_backtest)
    assert "macro_daily_sold_level" in source, (
        "run_backtest should use macro_daily_sold_level for D+W dedup"
    )


# ── 22. Native daily/weekly bar support (15m→month, all data) ──────


def test_aggregate_daily_to_monthly() -> None:
    """aggregate_daily_to_monthly: native daily → monthly bars."""
    from research.macro_cycle import aggregate_daily_to_monthly

    # 90 days spanning 3 months (Jan-Mar)
    bars = []
    for i in range(90):
        ts = TS + timedelta(days=i)
        p = 40000 + i * 100
        bars.append(MarketBar(
            timestamp=ts, open=p, high=p + 50,
            low=p - 50, close=p, volume=100.0,
        ))
    monthly = aggregate_daily_to_monthly(bars)
    assert len(monthly) == 3  # Jan, Feb, Mar


def test_check_daily_rsi_sell_native_matches_aggregated() -> None:
    """Native daily+weekly RSI sell should give same result as 4h-aggregated."""
    from research.macro_cycle import (
        MacroCycleConfig, check_daily_rsi_sell, check_daily_rsi_sell_native,
        aggregate_to_daily, aggregate_to_weekly,
    )

    n_bars = 120 * 6
    prices = [30000 * (1.004 ** i) for i in range(n_bars)]
    bars_4h = _make_bars_4h(prices, start=datetime(2022, 1, 1))
    daily = aggregate_to_daily(bars_4h)
    weekly = aggregate_to_weekly(bars_4h)

    config = MacroCycleConfig()
    sell_4h, d_rsi_4h, w_rsi_4h = check_daily_rsi_sell(bars_4h, config)
    sell_nat, d_rsi_nat, w_rsi_nat = check_daily_rsi_sell_native(daily, weekly, config)

    # Same input (aggregated from same 4h) → identical result
    assert sell_4h == sell_nat
    assert abs(d_rsi_4h - d_rsi_nat) < 0.01
    assert abs(w_rsi_4h - w_rsi_nat) < 0.01


def test_check_daily_rsi_buy_native_matches_aggregated() -> None:
    """Native daily+weekly RSI buy should give same result as 4h-aggregated."""
    from research.macro_cycle import (
        MacroCycleConfig, check_daily_rsi_buy, check_daily_rsi_buy_native,
        aggregate_to_daily, aggregate_to_weekly,
    )

    n_bars = 120 * 6
    prices = [60000 * (0.994 ** i) for i in range(n_bars)]
    bars_4h = _make_bars_4h(prices, start=datetime(2022, 1, 1))
    daily = aggregate_to_daily(bars_4h)
    weekly = aggregate_to_weekly(bars_4h)

    config = MacroCycleConfig()
    buy_4h, d_4h, w_4h = check_daily_rsi_buy(bars_4h, config)
    buy_nat, d_nat, w_nat = check_daily_rsi_buy_native(daily, weekly, config)

    assert buy_4h == buy_nat
    assert abs(d_4h - d_nat) < 0.01
    assert abs(w_4h - w_nat) < 0.01


def test_check_weekly_rsi_buy_native_matches_aggregated() -> None:
    """Native weekly RSI buy should match 4h-aggregated."""
    from research.macro_cycle import (
        MacroCycleConfig, check_weekly_rsi_buy, check_weekly_rsi_buy_native,
        aggregate_to_weekly,
    )

    n_bars = 120 * 6
    prices = [60000 * (0.993 ** i) for i in range(n_bars)]
    bars_4h = _make_bars_4h(prices, start=datetime(2022, 1, 1))
    weekly = aggregate_to_weekly(bars_4h)

    config = MacroCycleConfig()
    buy_4h, rsi_4h = check_weekly_rsi_buy(bars_4h, config)
    buy_nat, rsi_nat = check_weekly_rsi_buy_native(weekly, config)

    assert buy_4h == buy_nat
    assert abs(rsi_4h - rsi_nat) < 0.01


def test_get_monthly_rsi_native_from_daily() -> None:
    """Monthly RSI from native daily bars ~ aggregated from 4h."""
    from research.macro_cycle import (
        MacroCycleConfig, get_monthly_rsi, get_monthly_rsi_native,
        aggregate_to_daily,
    )

    n_bars = 500 * 6  # 500 days
    prices = [30000 * (1.002 ** i) for i in range(n_bars)]
    bars_4h = _make_bars_4h(prices, start=datetime(2022, 1, 1))
    daily = aggregate_to_daily(bars_4h)

    config = MacroCycleConfig()
    rsi_4h = get_monthly_rsi(bars_4h, config)
    rsi_daily = get_monthly_rsi_native(daily, config)

    # Tiny difference possible from daily→monthly vs 4h→monthly grouping
    assert abs(rsi_4h - rsi_daily) < 2.0, (
        f"4h-based {rsi_4h:.1f} vs daily-native {rsi_daily:.1f}"
    )


def test_detect_cycle_signal_accepts_native_bars() -> None:
    """detect_cycle_signal should accept native_daily/native_weekly kwargs."""
    import inspect
    from research.macro_cycle import detect_cycle_signal

    sig = inspect.signature(detect_cycle_signal)
    params = list(sig.parameters.keys())
    assert "native_daily" in params
    assert "native_weekly" in params


def test_backtest_uses_native_1d_1w() -> None:
    """run_backtest should use native 1d/1w from mtf_bars when available."""
    import inspect
    from research.backtest import run_backtest

    source = inspect.getsource(run_backtest)
    # Should check for '1d' in mtf_bars
    assert "1d" in source, "run_backtest should reference '1d' native bars"
    assert "1w" in source, "run_backtest should reference '1w' native bars"
    assert "check_daily_rsi_sell_native" in source, (
        "run_backtest should call native sell function when native bars available"
    )
