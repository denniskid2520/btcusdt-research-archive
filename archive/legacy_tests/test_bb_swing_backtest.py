"""Tests for Bollinger Bands swing trading backtest (Strategy D).

TDD: these tests define the expected behaviour before implementation.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from research.bb_swing_backtest import (
    BBConfig,
    BBState,
    TradeRecord,
    calculate_bb,
    calculate_rsi,
    calculate_adx,
    calculate_atr,
    check_entry_signal,
    check_exit_signal,
    inverse_pnl_btc,
    linear_pnl_usdt,
    position_size_btc,
    position_size_usdt,
    run_bb_backtest,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_bar(ts: datetime, close: float, *, high: float | None = None, low: float | None = None,
              open_: float | None = None, volume: float = 1000.0) -> dict:
    """Quick bar dict matching the format used by bb_swing_backtest."""
    return {
        "timestamp": ts,
        "open": open_ if open_ is not None else close,
        "high": high if high is not None else close * 1.005,
        "low": low if low is not None else close * 0.995,
        "close": close,
        "volume": volume,
    }


def _daily_bars(prices: list[float], start: datetime | None = None) -> list[dict]:
    """Generate a list of daily bars from close prices."""
    start = start or datetime(2023, 1, 1)
    bars = []
    for i, price in enumerate(prices):
        bars.append(_make_bar(
            ts=start + timedelta(days=i),
            close=price,
            high=price * 1.01,
            low=price * 0.99,
            open_=price * 0.999,
        ))
    return bars


def _4h_bars(prices: list[float], start: datetime | None = None) -> list[dict]:
    """Generate a list of 4h bars from close prices."""
    start = start or datetime(2023, 1, 1)
    bars = []
    for i, price in enumerate(prices):
        bars.append(_make_bar(
            ts=start + timedelta(hours=4 * i),
            close=price,
            high=price * 1.005,
            low=price * 0.995,
            open_=price * 0.999,
        ))
    return bars


# ===========================================================================
# 1. Bollinger Band calculation
# ===========================================================================

class TestBBCalculation:
    def test_basic_bb_values(self) -> None:
        """BB with known values: SMA ± K*StdDev."""
        # 20 identical prices → StdDev = 0 → bands collapse to SMA
        prices = [100.0] * 20
        bb = calculate_bb(prices, period=20, k=2.0)
        assert bb.middle == pytest.approx(100.0)
        assert bb.upper == pytest.approx(100.0)
        assert bb.lower == pytest.approx(100.0)
        assert bb.width_pct == pytest.approx(0.0)

    def test_bb_with_variance(self) -> None:
        """BB with actual variance produces upper > middle > lower."""
        prices = list(range(80, 120))  # 80..119, 40 values
        bb = calculate_bb(prices, period=20, k=2.0)
        assert bb.upper > bb.middle > bb.lower
        assert bb.width_pct > 0

    def test_bb_width_pct_formula(self) -> None:
        """width_pct = (upper - lower) / middle * 100."""
        prices = list(range(90, 110))  # 20 values
        bb = calculate_bb(prices, period=20, k=2.0)
        expected_width = (bb.upper - bb.lower) / bb.middle * 100
        assert bb.width_pct == pytest.approx(expected_width, rel=1e-6)

    def test_bb_insufficient_data_returns_none(self) -> None:
        """Not enough data for period should return None."""
        prices = [100.0] * 10
        result = calculate_bb(prices, period=20, k=2.0)
        assert result is None

    def test_bb_different_k_values(self) -> None:
        """Higher K → wider bands."""
        prices = list(range(90, 110))
        bb_tight = calculate_bb(prices, period=20, k=1.5)
        bb_wide = calculate_bb(prices, period=20, k=2.5)
        assert bb_wide.upper > bb_tight.upper
        assert bb_wide.lower < bb_tight.lower


# ===========================================================================
# 2. RSI calculation
# ===========================================================================

class TestRSICalculation:
    def test_rsi_all_gains(self) -> None:
        """Monotonically rising prices → RSI near 100."""
        prices = [100 + i for i in range(20)]
        rsi = calculate_rsi(prices, period=3)
        assert rsi > 90

    def test_rsi_all_losses(self) -> None:
        """Monotonically falling prices → RSI near 0."""
        prices = [100 - i for i in range(20)]
        rsi = calculate_rsi(prices, period=3)
        assert rsi < 10

    def test_rsi_insufficient_data(self) -> None:
        """Not enough data returns None."""
        rsi = calculate_rsi([100, 101], period=14)
        assert rsi is None


# ===========================================================================
# 3. ADX calculation
# ===========================================================================

class TestADXCalculation:
    def test_adx_trending(self) -> None:
        """Strong trend → high ADX."""
        # Generate bars with strong uptrend
        bars = []
        start = datetime(2023, 1, 1)
        for i in range(50):
            price = 100 + i * 2  # strong trend
            bars.append(_make_bar(
                ts=start + timedelta(days=i),
                close=price, high=price + 1, low=price - 1, open_=price - 0.5,
            ))
        adx = calculate_adx(bars, period=14)
        assert adx is not None
        assert adx > 25  # trending

    def test_adx_insufficient_data(self) -> None:
        """Not enough data returns None."""
        bars = [_make_bar(ts=datetime(2023, 1, 1), close=100)]
        adx = calculate_adx(bars, period=14)
        assert adx is None


# ===========================================================================
# 4. Entry signal logic
# ===========================================================================

class TestEntrySignal:
    def test_long_signal_at_lower_band(self) -> None:
        """Close below lower band triggers LONG."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig()
        signal = check_entry_signal(
            close=89.5, bb=bb, ma200=80.0, rsi3=None, adx=None,
            config=config, last_exit_ts=None, current_ts=datetime(2023, 6, 1),
        )
        assert signal == "long"

    def test_short_signal_at_upper_band(self) -> None:
        """Close above upper band triggers SHORT."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig()
        signal = check_entry_signal(
            close=110.5, bb=bb, ma200=120.0, rsi3=None, adx=None,
            config=config, last_exit_ts=None, current_ts=datetime(2023, 6, 1),
        )
        assert signal == "short"

    def test_no_signal_in_middle(self) -> None:
        """Price in middle of bands → no signal."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig()
        signal = check_entry_signal(
            close=100, bb=bb, ma200=100.0, rsi3=None, adx=None,
            config=config, last_exit_ts=None, current_ts=datetime(2023, 6, 1),
        )
        assert signal is None

    def test_ma200_filter_blocks_long_below(self) -> None:
        """MA200 filter: block long when price below MA200."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig(use_ma200_filter=True)
        signal = check_entry_signal(
            close=89.5, bb=bb, ma200=95.0, rsi3=None, adx=None,
            config=config, last_exit_ts=None, current_ts=datetime(2023, 6, 1),
        )
        assert signal is None  # blocked: close < ma200

    def test_ma200_filter_blocks_short_above(self) -> None:
        """MA200 filter: block short when price above MA200."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig(use_ma200_filter=True)
        signal = check_entry_signal(
            close=110.5, bb=bb, ma200=105.0, rsi3=None, adx=None,
            config=config, last_exit_ts=None, current_ts=datetime(2023, 6, 1),
        )
        assert signal is None  # blocked: close > ma200

    def test_band_width_too_narrow_blocks(self) -> None:
        """Bands too narrow (< min_width) → skip."""
        bb = BBState(middle=100, upper=101, lower=99, width_pct=2.0)
        config = BBConfig(min_band_width_pct=3.0)
        signal = check_entry_signal(
            close=98.5, bb=bb, ma200=80.0, rsi3=None, adx=None,
            config=config, last_exit_ts=None, current_ts=datetime(2023, 6, 1),
        )
        assert signal is None

    def test_band_width_too_wide_blocks(self) -> None:
        """Bands too wide (> max_width) → skip."""
        bb = BBState(middle=100, upper=120, lower=80, width_pct=40.0)
        config = BBConfig(max_band_width_pct=30.0)
        signal = check_entry_signal(
            close=79.0, bb=bb, ma200=60.0, rsi3=None, adx=None,
            config=config, last_exit_ts=None, current_ts=datetime(2023, 6, 1),
        )
        assert signal is None

    def test_rsi_filter_blocks_long(self) -> None:
        """RSI(3) > threshold → blocks long (not oversold)."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig(use_rsi_filter=True, rsi_oversold=30)
        signal = check_entry_signal(
            close=89.5, bb=bb, ma200=80.0, rsi3=50.0, adx=None,
            config=config, last_exit_ts=None, current_ts=datetime(2023, 6, 1),
        )
        assert signal is None  # RSI too high for long

    def test_rsi_filter_allows_long_when_oversold(self) -> None:
        """RSI(3) < threshold → allows long."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig(use_rsi_filter=True, rsi_oversold=30)
        signal = check_entry_signal(
            close=89.5, bb=bb, ma200=80.0, rsi3=20.0, adx=None,
            config=config, last_exit_ts=None, current_ts=datetime(2023, 6, 1),
        )
        assert signal == "long"

    def test_adx_filter_blocks_in_trending(self) -> None:
        """ADX > 25 → trending → block mean-reversion."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig(use_adx_filter=True, adx_threshold=25)
        signal = check_entry_signal(
            close=89.5, bb=bb, ma200=80.0, rsi3=None, adx=35.0,
            config=config, last_exit_ts=None, current_ts=datetime(2023, 6, 1),
        )
        assert signal is None  # ADX too high

    def test_cooldown_blocks_entry(self) -> None:
        """Cannot re-enter within cooldown period."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig(cooldown_days=1)
        last_exit = datetime(2023, 6, 1, 12, 0)
        current = datetime(2023, 6, 1, 20, 0)  # same day
        signal = check_entry_signal(
            close=89.5, bb=bb, ma200=80.0, rsi3=None, adx=None,
            config=config, last_exit_ts=last_exit, current_ts=current,
        )
        assert signal is None

    def test_within_1pct_of_band_triggers(self) -> None:
        """Price within 1% of lower band still triggers LONG."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig(band_touch_pct=0.01)
        # 90 * 1.01 = 90.9 → price 90.8 is within 1% of lower band
        signal = check_entry_signal(
            close=90.8, bb=bb, ma200=80.0, rsi3=None, adx=None,
            config=config, last_exit_ts=None, current_ts=datetime(2023, 6, 1),
        )
        assert signal == "long"


# ===========================================================================
# 5. Exit signal logic
# ===========================================================================

class TestExitSignal:
    def test_target_middle_band_long(self) -> None:
        """Long exits when price reaches middle band."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig(target_mode="middle")
        reason = check_exit_signal(
            side="long", entry_price=89.0, close=100.5, bb=bb,
            bars_held=5, atr=2.0, max_profit_pct=0.0, config=config,
        )
        assert reason == "target_middle"

    def test_target_opposite_band_long(self) -> None:
        """Long exits when price reaches opposite (upper) band."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig(target_mode="opposite")
        reason = check_exit_signal(
            side="long", entry_price=89.0, close=110.5, bb=bb,
            bars_held=5, atr=2.0, max_profit_pct=0.0, config=config,
        )
        assert reason == "target_opposite"

    def test_stop_loss_long(self) -> None:
        """Long stop: price falls X% below lower band at entry."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig(stop_loss_pct=0.03)
        reason = check_exit_signal(
            side="long", entry_price=90.0, close=86.0, bb=bb,
            bars_held=5, atr=2.0, max_profit_pct=0.0, config=config,
        )
        assert reason == "stop_loss"

    def test_stop_loss_short(self) -> None:
        """Short stop: price rises X% above entry."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig(stop_loss_pct=0.03)
        reason = check_exit_signal(
            side="short", entry_price=110.0, close=114.0, bb=bb,
            bars_held=5, atr=2.0, max_profit_pct=0.0, config=config,
        )
        assert reason == "stop_loss"

    def test_time_stop(self) -> None:
        """Close after max_hold_bars if no other exit hit."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig(max_hold_bars=120)  # 20 days * 6 bars/day
        reason = check_exit_signal(
            side="long", entry_price=95.0, close=96.0, bb=bb,
            bars_held=121, atr=2.0, max_profit_pct=0.0, config=config,
        )
        assert reason == "time_stop"

    def test_trailing_stop(self) -> None:
        """Trailing stop: profit > 3%, then retraces past 2x ATR."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig(use_trailing_stop=True, trailing_activation_pct=0.03,
                          trailing_atr_multiplier=2.0)
        # Long entry at 90, max profit was 6% (95.4), now at 93
        # Trail level = 95.4 - 2*2.0 = 91.4 → 93 is above → no stop
        reason = check_exit_signal(
            side="long", entry_price=90.0, close=93.0, bb=bb,
            bars_held=10, atr=2.0, max_profit_pct=0.06, config=config,
        )
        assert reason is None  # still above trail

    def test_trailing_stop_triggers(self) -> None:
        """Trailing stop triggers when price falls below trail level."""
        bb = BBState(middle=100, upper=110, lower=90, width_pct=20.0)
        config = BBConfig(use_trailing_stop=True, trailing_activation_pct=0.03,
                          trailing_atr_multiplier=2.0)
        # Long entry at 90, max profit 10% → peak ~99
        # Trail from peak: 99 - 2*2 = 95, current 94 → triggers
        reason = check_exit_signal(
            side="long", entry_price=90.0, close=94.0, bb=bb,
            bars_held=10, atr=2.0, max_profit_pct=0.10, config=config,
        )
        assert reason == "trailing_stop"


# ===========================================================================
# 6. Position sizing (inverse perpetual)
# ===========================================================================

class TestPositionSizing:
    def test_basic_sizing(self) -> None:
        """5% risk / stop_distance, capped at 90% * leverage."""
        size = position_size_btc(
            capital_btc=1.0, stop_distance_pct=0.05,
            leverage=3, max_margin_pct=0.90, risk_per_trade=0.05,
        )
        # 0.05 / 0.05 = 1.0 BTC, but cap is 0.9 * 3 = 2.7 BTC
        assert size == pytest.approx(1.0)

    def test_cap_at_max_margin(self) -> None:
        """Tiny stop → capped at max_margin * leverage."""
        size = position_size_btc(
            capital_btc=1.0, stop_distance_pct=0.001,
            leverage=3, max_margin_pct=0.90, risk_per_trade=0.05,
        )
        # 0.05 / 0.001 = 50 BTC → capped at 0.9 * 3 = 2.7
        assert size == pytest.approx(2.7)

    def test_zero_stop_returns_zero(self) -> None:
        """Zero stop distance → return 0 (safety)."""
        size = position_size_btc(
            capital_btc=1.0, stop_distance_pct=0.0,
            leverage=3, max_margin_pct=0.90, risk_per_trade=0.05,
        )
        assert size == 0.0


# ===========================================================================
# 7. Inverse PnL model
# ===========================================================================

class TestInversePnL:
    def test_long_profit(self) -> None:
        """Long: buy at 50k, sell at 55k → profit in BTC."""
        pnl = inverse_pnl_btc(side="long", qty_btc=1.0, entry=50000, exit_=55000, fee_rate=0.001)
        # Gross: 1.0 * (55000/50000 - 1) = 0.1 BTC
        # Fees: 1.0 * 0.001 * 2 = 0.002
        expected = 0.1 - 0.002
        assert pnl == pytest.approx(expected, rel=1e-6)

    def test_short_profit(self) -> None:
        """Short: sell at 55k, cover at 50k → profit in BTC."""
        pnl = inverse_pnl_btc(side="short", qty_btc=1.0, entry=55000, exit_=50000, fee_rate=0.001)
        # Gross: 1.0 * (1 - 50000/55000) = 1.0 * (1 - 0.9090909) ≈ 0.0909
        expected = (1 - 50000 / 55000) - 0.002
        assert pnl == pytest.approx(expected, rel=1e-6)

    def test_long_loss(self) -> None:
        """Long: buy at 50k, sell at 48k → loss."""
        pnl = inverse_pnl_btc(side="long", qty_btc=1.0, entry=50000, exit_=48000, fee_rate=0.001)
        assert pnl < 0

    def test_short_loss(self) -> None:
        """Short: sell at 50k, cover at 52k → loss."""
        pnl = inverse_pnl_btc(side="short", qty_btc=1.0, entry=50000, exit_=52000, fee_rate=0.001)
        assert pnl < 0

    def test_zero_fee(self) -> None:
        """No fees: pure PnL."""
        pnl = inverse_pnl_btc(side="long", qty_btc=1.0, entry=50000, exit_=55000, fee_rate=0.0)
        assert pnl == pytest.approx(0.1, rel=1e-6)


# ===========================================================================
# 8. Integration: full backtest on synthetic data
# ===========================================================================

class TestIntegration:
    def _make_mean_reverting_bars(self) -> list[dict]:
        """Create 4h bars that oscillate between bands (mean-reverting regime)."""
        bars = []
        start = datetime(2023, 1, 1)
        # Need enough bars for BB(20 daily) = 20*6 = 120 4h bars warmup
        # Then add 300 bars of mean-reverting action
        n_warmup = 150
        n_trade = 600
        base_price = 50000.0
        amplitude = 4000.0  # 8% swings around base

        for i in range(n_warmup + n_trade):
            t = start + timedelta(hours=4 * i)
            # Sine wave oscillation: period ~60 bars (10 days)
            cycle = math.sin(2 * math.pi * i / 60) * amplitude
            price = base_price + cycle
            # Add small noise
            noise = (((i * 7 + 13) % 100) - 50) * 10  # deterministic noise
            price += noise
            bars.append(_make_bar(
                ts=t, close=price,
                high=price + 200, low=price - 200, open_=price - 50,
            ))
        return bars

    def test_backtest_runs_end_to_end(self) -> None:
        """Full backtest should complete without error and produce trades."""
        bars = self._make_mean_reverting_bars()
        config = BBConfig(
            bb_period=20, bb_k=2.0, target_mode="middle",
            use_ma200_filter=False, use_rsi_filter=False, use_adx_filter=False,
            min_band_width_pct=0.0, max_band_width_pct=100.0,
        )
        result = run_bb_backtest(bars_4h=bars, config=config, initial_btc=1.0, leverage=3)

        assert result["initial_btc"] == 1.0
        assert result["final_btc"] > 0
        assert isinstance(result["trades"], list)
        assert result["total_trades"] >= 0
        assert "max_drawdown_pct" in result
        assert "sharpe" in result

    def test_backtest_trade_records_have_required_fields(self) -> None:
        """Each trade record has all required fields."""
        bars = self._make_mean_reverting_bars()
        config = BBConfig(
            bb_period=20, bb_k=2.0, target_mode="middle",
            use_ma200_filter=False, min_band_width_pct=0.0, max_band_width_pct=100.0,
        )
        result = run_bb_backtest(bars_4h=bars, config=config, initial_btc=1.0, leverage=3)

        if result["trades"]:
            trade = result["trades"][0]
            assert "side" in trade
            assert "entry_price" in trade
            assert "exit_price" in trade
            assert "exit_reason" in trade
            assert "pnl" in trade
            assert "pnl_pct" in trade
            assert "duration_days" in trade
            assert "bb_width_pct" in trade

    def test_backtest_equity_never_negative(self) -> None:
        """Equity should never go negative."""
        bars = self._make_mean_reverting_bars()
        config = BBConfig(bb_period=20, bb_k=2.0, target_mode="middle",
                          min_band_width_pct=0.0, max_band_width_pct=100.0)
        result = run_bb_backtest(bars_4h=bars, config=config, initial_btc=1.0, leverage=3)
        assert result["final_btc"] > 0
        for eq in result["equity_curve"]:
            assert eq > 0

    def test_backtest_exit_reasons_valid(self) -> None:
        """All exit reasons should be known values."""
        bars = self._make_mean_reverting_bars()
        config = BBConfig(bb_period=20, bb_k=2.0, target_mode="middle",
                          min_band_width_pct=0.0, max_band_width_pct=100.0)
        result = run_bb_backtest(bars_4h=bars, config=config, initial_btc=1.0, leverage=3)

        valid_reasons = {
            "target_middle", "target_opposite", "stop_loss",
            "time_stop", "trailing_stop", "forced_end",
        }
        for trade in result["trades"]:
            assert trade["exit_reason"] in valid_reasons, (
                f"Unknown exit reason: {trade['exit_reason']}"
            )


# ===========================================================================
# Native daily bar support
# ===========================================================================

class TestNativeDailyBars:
    """Tests for using native 1d bars instead of 4h aggregation."""

    @staticmethod
    def _make_4h_bars(n_days: int = 250, base: float = 50000.0) -> list[dict]:
        """Generate 4h bars spanning n_days (6 bars per day)."""
        import math
        bars = []
        start = datetime(2021, 1, 1)
        for i in range(n_days * 6):
            day = i // 6
            # Oscillating price for mean reversion
            price = base + 5000 * math.sin(2 * math.pi * day / 40)
            bars.append(_make_bar(
                ts=start + timedelta(hours=i * 4),
                close=price,
                high=price * 1.005,
                low=price * 0.995,
                open_=price * 0.999,
            ))
        return bars

    @staticmethod
    def _make_native_daily(n_days: int = 250, base: float = 50000.0) -> list[dict]:
        """Generate native daily bars with DIFFERENT values from 4h aggregation.

        Shifts the phase slightly so BB bands compute differently.
        """
        import math
        bars = []
        start = datetime(2021, 1, 1)
        for day in range(n_days):
            # Phase-shifted price to ensure meaningfully different BB values
            price = base + 5000 * math.sin(2 * math.pi * day / 40 + 0.3)
            bars.append({
                "timestamp": start + timedelta(days=day),
                "open": price * 1.001,
                "high": price * 1.012,
                "low": price * 0.988,
                "close": price,
                "volume": 10000.0,
            })
        return bars

    def test_backtest_accepts_daily_bars_param(self) -> None:
        """run_bb_backtest should accept daily_bars parameter."""
        bars_4h = self._make_4h_bars()
        daily = self._make_native_daily()
        config = BBConfig(bb_period=20, bb_k=2.0, min_band_width_pct=0.0,
                          max_band_width_pct=100.0)
        result = run_bb_backtest(
            bars_4h=bars_4h, config=config, daily_bars=daily,
        )
        assert "total_return_pct" in result
        assert "trades" in result

    def test_native_daily_produces_different_results(self) -> None:
        """Using native daily bars should give different results than aggregation."""
        bars_4h = self._make_4h_bars()
        daily = self._make_native_daily()
        config = BBConfig(bb_period=20, bb_k=2.0, min_band_width_pct=0.0,
                          max_band_width_pct=100.0)

        result_agg = run_bb_backtest(bars_4h=bars_4h, config=config)
        result_native = run_bb_backtest(
            bars_4h=bars_4h, config=config, daily_bars=daily,
        )
        # They should differ because daily close prices are different
        assert result_agg["total_trades"] != result_native["total_trades"] or \
            abs(result_agg["total_return_pct"] - result_native["total_return_pct"]) > 0.01

    def test_native_daily_uses_daily_close_for_bb(self) -> None:
        """BB should be computed on native daily closes, not 4h-aggregated."""
        from research.bb_swing_backtest import calculate_bb

        native_daily = self._make_native_daily(n_days=25)
        native_closes = [d["close"] for d in native_daily]
        bb_native = calculate_bb(native_closes, period=20, k=2.0)

        # 4h aggregated daily would use different closes
        bars_4h = self._make_4h_bars(n_days=25)
        from research.bb_swing_backtest import _aggregate_4h_to_daily
        agg_daily = _aggregate_4h_to_daily(bars_4h)
        agg_closes = [d["close"] for d in agg_daily]
        bb_agg = calculate_bb(agg_closes, period=20, k=2.0)

        # Both should compute valid BBs but with different values
        assert bb_native is not None
        assert bb_agg is not None
        assert bb_native.middle != bb_agg.middle

    def test_backtest_without_daily_bars_still_works(self) -> None:
        """Backward compatibility: omitting daily_bars falls back to aggregation."""
        bars_4h = self._make_4h_bars()
        config = BBConfig(bb_period=20, bb_k=2.0, min_band_width_pct=0.0,
                          max_band_width_pct=100.0)
        result = run_bb_backtest(bars_4h=bars_4h, config=config)
        assert "total_return_pct" in result


# ===========================================================================
# Linear USDT-M perpetual support
# ===========================================================================

class TestLinearUSDTM:
    """Tests for USDT-margined (linear) perpetual mode."""

    def test_linear_pnl_long_profit(self) -> None:
        """Long profit: qty * (exit - entry) - fees."""
        pnl = linear_pnl_usdt(
            side="long", qty_btc=0.1, entry=80000, exit_=84000, fee_rate=0.001,
        )
        # gross = 0.1 * (84000 - 80000) = 400
        # fees = 0.1 * 80000 * 0.001 + 0.1 * 84000 * 0.001 = 8 + 8.4 = 16.4
        # net = 400 - 16.4 = 383.6
        assert abs(pnl - 383.6) < 0.1

    def test_linear_pnl_short_profit(self) -> None:
        """Short profit: qty * (entry - exit) - fees."""
        pnl = linear_pnl_usdt(
            side="short", qty_btc=0.1, entry=80000, exit_=76000, fee_rate=0.001,
        )
        # gross = 0.1 * (80000 - 76000) = 400
        # fees = 0.1 * 80000 * 0.001 + 0.1 * 76000 * 0.001 = 8 + 7.6 = 15.6
        # net = 400 - 15.6 = 384.4
        assert abs(pnl - 384.4) < 0.1

    def test_linear_pnl_long_loss(self) -> None:
        """Long loss returns negative USDT."""
        pnl = linear_pnl_usdt(
            side="long", qty_btc=0.1, entry=80000, exit_=77000, fee_rate=0.001,
        )
        assert pnl < 0

    def test_position_size_usdt(self) -> None:
        """Position size in BTC from USDT capital."""
        qty = position_size_usdt(
            capital_usdt=10000, entry_price=80000,
            stop_distance_pct=0.03, leverage=3,
            max_margin_pct=0.90, risk_per_trade=0.05,
        )
        # risk_based = (10000 * 0.05) / 0.03 / 80000 = 500 / 0.03 / 80000 = 0.2083
        # cap = 10000 * 0.90 * 3 / 80000 = 0.3375
        # min(0.2083, 0.3375) = 0.2083
        assert abs(qty - 0.2083) < 0.001
        assert qty > 0

    def test_position_size_usdt_capped(self) -> None:
        """Position size should be capped by margin * leverage."""
        qty = position_size_usdt(
            capital_usdt=10000, entry_price=80000,
            stop_distance_pct=0.005, leverage=3,  # tiny stop → risk-based is huge
            max_margin_pct=0.90, risk_per_trade=0.05,
        )
        cap = 10000 * 0.90 * 3 / 80000  # 0.3375
        assert abs(qty - cap) < 0.001

    def test_backtest_linear_mode(self) -> None:
        """run_bb_backtest with margin_type='linear' should use USDT capital."""
        bars_4h = TestNativeDailyBars._make_4h_bars()
        config = BBConfig(bb_period=20, bb_k=2.0, min_band_width_pct=0.0,
                          max_band_width_pct=100.0)
        result = run_bb_backtest(
            bars_4h=bars_4h, config=config,
            margin_type="linear", initial_capital=10000.0,
        )
        assert "total_return_pct" in result
        assert result["initial_capital"] == 10000.0
        assert "final_capital" in result

    def test_backtest_linear_capital_in_usdt(self) -> None:
        """Linear mode equity curve should be in USDT, not BTC."""
        bars_4h = TestNativeDailyBars._make_4h_bars()
        config = BBConfig(bb_period=20, bb_k=2.0, min_band_width_pct=0.0,
                          max_band_width_pct=100.0)
        result = run_bb_backtest(
            bars_4h=bars_4h, config=config,
            margin_type="linear", initial_capital=10000.0,
        )
        # Equity curve values should be in USDT range (thousands), not BTC range (~1)
        for eq in result["equity_curve"]:
            assert eq > 100  # definitely USDT, not BTC

    def test_backtest_inverse_mode_unchanged(self) -> None:
        """Default (inverse) mode still works with BTC capital."""
        bars_4h = TestNativeDailyBars._make_4h_bars()
        config = BBConfig(bb_period=20, bb_k=2.0, min_band_width_pct=0.0,
                          max_band_width_pct=100.0)
        result = run_bb_backtest(
            bars_4h=bars_4h, config=config,
            initial_btc=1.0,
        )
        assert result["initial_btc"] == 1.0
        assert "final_btc" in result
