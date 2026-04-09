"""TDD tests for EMA-based Bollinger Bands and asymmetric entry.

Academic basis:
  - HBEM 2024: EMA replaces SMA in BB → Sharpe 3.22 on crypto futures
  - Hsu & Chiang 2022: BB(60) outperforms BB(20) on BTC
  - Beluska & Vojtko 2024: BTC trends at highs, reverts at lows (asymmetric)
"""

import pytest
import math


# ═══════════════════════════════════════════════════════════
# Test: EMA calculation
# ═══════════════════════════════════════════════════════════

class TestCalculateEMA:
    """Exponential Moving Average calculation."""

    def test_basic_ema(self):
        """EMA with known values."""
        from research.bb_swing_backtest import calculate_ema
        prices = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        ema = calculate_ema(prices, period=10)
        assert ema is not None
        # EMA should be between min and max
        assert 10 < ema < 20

    def test_ema_closer_to_recent(self):
        """EMA weighs recent prices more → closer to recent values than SMA."""
        from research.bb_swing_backtest import calculate_ema, calculate_sma
        # Flat then jump: EMA reacts faster to the jump
        prices = [100] * 10 + [100, 105, 110, 115, 120, 130, 140, 150, 160, 180]
        ema = calculate_ema(prices, period=10)
        sma = calculate_sma(prices, period=10)
        assert ema is not None and sma is not None
        assert ema > sma  # EMA tracks the jump faster

    def test_ema_insufficient_data_returns_none(self):
        from research.bb_swing_backtest import calculate_ema
        assert calculate_ema([1, 2, 3], period=10) is None

    def test_ema_exact_period_data(self):
        """With exactly period data points, EMA = SMA (seed value)."""
        from research.bb_swing_backtest import calculate_ema
        prices = [10, 20, 30, 40, 50]
        ema = calculate_ema(prices, period=5)
        assert ema is not None
        assert abs(ema - 30.0) < 0.01  # SMA seed = mean([10,20,30,40,50]) = 30

    def test_constant_prices_ema_equals_price(self):
        """Constant prices → EMA = that constant."""
        from research.bb_swing_backtest import calculate_ema
        prices = [100.0] * 30
        ema = calculate_ema(prices, period=20)
        assert ema is not None
        assert abs(ema - 100.0) < 0.01


# ═══════════════════════════════════════════════════════════
# Test: EMA-based Bollinger Bands
# ═══════════════════════════════════════════════════════════

class TestCalculateBBEma:
    """BB with EMA center instead of SMA."""

    def test_ema_bb_returns_bbstate(self):
        """EMA-based BB returns valid BBState."""
        from research.bb_swing_backtest import calculate_bb, BBState
        prices = list(range(100, 130))  # 30 prices
        bb = calculate_bb(prices, period=20, k=2.0, use_ema=True)
        assert bb is not None
        assert isinstance(bb, BBState)
        assert bb.upper > bb.middle > bb.lower

    def test_ema_bb_different_from_sma_bb(self):
        """EMA BB should produce different bands from SMA BB."""
        from research.bb_swing_backtest import calculate_bb
        # Flat then accelerating up: EMA diverges from SMA
        prices = [100] * 20 + [100, 105, 112, 120, 130, 142, 155, 170, 188, 210,
                                235, 260, 290, 320, 355, 395, 440, 490, 545, 600]
        bb_sma = calculate_bb(prices, period=20, k=2.0, use_ema=False)
        bb_ema = calculate_bb(prices, period=20, k=2.0, use_ema=True)
        assert bb_sma is not None and bb_ema is not None
        assert bb_sma.middle != bb_ema.middle

    def test_ema_bb_constant_prices_equals_sma(self):
        """Constant prices → EMA BB ≈ SMA BB."""
        from research.bb_swing_backtest import calculate_bb
        prices = [50000.0] * 30
        bb_sma = calculate_bb(prices, period=20, k=2.0, use_ema=False)
        bb_ema = calculate_bb(prices, period=20, k=2.0, use_ema=True)
        assert bb_sma is not None and bb_ema is not None
        assert abs(bb_sma.middle - bb_ema.middle) < 0.01
        assert abs(bb_sma.upper - bb_ema.upper) < 0.01

    def test_ema_bb_insufficient_data(self):
        from research.bb_swing_backtest import calculate_bb
        prices = [100, 101, 102]
        bb = calculate_bb(prices, period=20, k=2.0, use_ema=True)
        assert bb is None

    def test_default_is_sma(self):
        """Default use_ema=False maintains backward compatibility."""
        from research.bb_swing_backtest import calculate_bb
        prices = list(range(100, 130))
        bb1 = calculate_bb(prices, period=20, k=2.0)
        bb2 = calculate_bb(prices, period=20, k=2.0, use_ema=False)
        assert bb1.middle == bb2.middle
        assert bb1.upper == bb2.upper


# ═══════════════════════════════════════════════════════════
# Test: BBConfig bb_type field
# ═══════════════════════════════════════════════════════════

class TestBBConfigType:
    """BBConfig supports bb_type='sma' or 'ema'."""

    def test_default_bb_type_is_sma(self):
        from research.bb_swing_backtest import BBConfig
        cfg = BBConfig()
        assert cfg.bb_type == "sma"

    def test_ema_bb_type(self):
        from research.bb_swing_backtest import BBConfig
        cfg = BBConfig(bb_type="ema")
        assert cfg.bb_type == "ema"


# ═══════════════════════════════════════════════════════════
# Test: Asymmetric entry mode
# ═══════════════════════════════════════════════════════════

class TestAsymmetricEntry:
    """Beluska & Vojtko 2024: BTC trends at highs, reverts at lows.

    asymmetric_entry = True:
      - Lower band touch → long (mean reversion)   ← keep
      - Upper band touch → CONTINUE long (breakout) ← instead of shorting
    This effectively disables short entries.
    """

    def test_asymmetric_lower_touch_goes_long(self):
        """Lower band touch still triggers long in asymmetric mode."""
        from research.bb_swing_backtest import check_entry_signal, BBConfig, BBState
        config = BBConfig(
            asymmetric_entry=True,
            band_touch_pct=0.01,
        )
        bb = BBState(middle=50000, upper=55000, lower=45000, width_pct=20.0)
        signal = check_entry_signal(
            close=45100, bb=bb, ma200=None, rsi3=None, adx=None,
            config=config, last_exit_ts=None, current_ts=None,
        )
        assert signal == "long"

    def test_asymmetric_upper_touch_blocks_short(self):
        """Upper band touch does NOT trigger short in asymmetric mode."""
        from research.bb_swing_backtest import check_entry_signal, BBConfig, BBState
        config = BBConfig(
            asymmetric_entry=True,
            band_touch_pct=0.01,
        )
        bb = BBState(middle=50000, upper=55000, lower=45000, width_pct=20.0)
        signal = check_entry_signal(
            close=54900, bb=bb, ma200=None, rsi3=None, adx=None,
            config=config, last_exit_ts=None, current_ts=None,
        )
        assert signal is None  # short blocked

    def test_symmetric_upper_touch_allows_short(self):
        """Without asymmetric mode, upper touch triggers short as normal."""
        from research.bb_swing_backtest import check_entry_signal, BBConfig, BBState
        config = BBConfig(
            asymmetric_entry=False,
            band_touch_pct=0.01,
        )
        bb = BBState(middle=50000, upper=55000, lower=45000, width_pct=20.0)
        signal = check_entry_signal(
            close=54900, bb=bb, ma200=None, rsi3=None, adx=None,
            config=config, last_exit_ts=None, current_ts=None,
        )
        assert signal == "short"

    def test_config_default_is_symmetric(self):
        from research.bb_swing_backtest import BBConfig
        cfg = BBConfig()
        assert cfg.asymmetric_entry is False
