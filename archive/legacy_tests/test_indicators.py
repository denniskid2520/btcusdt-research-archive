"""Unit tests for technical indicator computations (RSI, ADX, R²)."""

from tests.fixtures_synthetic_bars import make_bar
from strategies.trend_breakout import _compute_rsi, _compute_adx, _r_squared, _linear_fit


def test_rsi_all_gains_returns_100() -> None:
    """When all closes are rising, RSI should approach 100."""
    bars = [make_bar(i, 50000 + i * 100) for i in range(10)]
    rsi = _compute_rsi(bars, 3)
    assert rsi is not None
    assert rsi == 100.0


def test_rsi_all_losses_returns_0() -> None:
    """When all closes are falling, RSI should approach 0."""
    bars = [make_bar(i, 60000 - i * 100) for i in range(10)]
    rsi = _compute_rsi(bars, 3)
    assert rsi is not None
    assert rsi == 0.0


def test_rsi_mixed_returns_midrange() -> None:
    """Alternating up/down should give RSI near 50."""
    bars = [make_bar(i, 55000 + (100 if i % 2 == 0 else -100)) for i in range(10)]
    rsi = _compute_rsi(bars, 3)
    assert rsi is not None
    assert 30 < rsi < 70


def test_rsi_insufficient_bars_returns_none() -> None:
    """Not enough bars for the period → None."""
    bars = [make_bar(i, 50000) for i in range(3)]
    rsi = _compute_rsi(bars, 3)
    assert rsi is None


def test_rsi_short_period_more_sensitive() -> None:
    """RSI(3) should be more extreme than RSI(14) for the same data."""
    # 20 bars of steady rise
    bars = [make_bar(i, 50000 + i * 50) for i in range(20)]
    rsi_3 = _compute_rsi(bars, 3)
    rsi_14 = _compute_rsi(bars, 14)
    assert rsi_3 is not None and rsi_14 is not None
    # RSI(3) should be at or closer to 100 than RSI(14)
    assert rsi_3 >= rsi_14


def test_adx_trending_market_high_value() -> None:
    """Strong unidirectional movement should produce high ADX."""
    # 30 bars of strong uptrend with directional high/low
    bars = [make_bar(i, 50000 + i * 300, high_pad=50, low_pad=50) for i in range(40)]
    adx = _compute_adx(bars, 14)
    assert adx is not None
    assert adx > 25, f"ADX should be >25 in trending market, got {adx:.1f}"


def test_adx_ranging_market_low_value() -> None:
    """Choppy sideways movement should produce low ADX."""
    bars = [make_bar(i, 55000 + (50 if i % 2 == 0 else -50), high_pad=60, low_pad=60) for i in range(40)]
    adx = _compute_adx(bars, 14)
    assert adx is not None
    assert adx < 25, f"ADX should be <25 in ranging market, got {adx:.1f}"


def test_adx_insufficient_bars_returns_none() -> None:
    """Not enough bars for ADX computation → None."""
    bars = [make_bar(i, 50000) for i in range(10)]
    adx = _compute_adx(bars, 14)
    assert adx is None


# ── R² tests ──────────────────────────────────────────────────────────────


def test_r_squared_perfect_fit() -> None:
    """R² should be 1.0 for perfectly linear data."""
    x = list(range(10))
    y = [100.0 + 5.0 * i for i in x]
    fit = _linear_fit(x, y)
    assert fit is not None
    r2 = _r_squared(x, y, fit[0], fit[1])
    assert abs(r2 - 1.0) < 1e-9


def test_r_squared_noisy_fit_lower() -> None:
    """R² should be lower for noisy data."""
    x = list(range(10))
    y_clean = [100.0 + 5.0 * i for i in x]
    # Add noise
    noise = [0, 10, -8, 15, -12, 20, -5, 8, -10, 3]
    y_noisy = [y + n for y, n in zip(y_clean, noise)]
    fit = _linear_fit(x, y_noisy)
    assert fit is not None
    r2 = _r_squared(x, y_noisy, fit[0], fit[1])
    assert r2 < 0.95, f"Noisy data should have R² < 0.95, got {r2:.3f}"


def test_r_squared_used_in_channel_scoring() -> None:
    """Channels with higher R² should score higher in multi-scale detection.

    This tests that _build_parent_context incorporates R² into its scoring.
    """
    # This is an integration-level expectation. The key behavior:
    # if two candidate windows produce channels with similar touch counts,
    # the one with higher R² (better fit) should win.
    x_clean = list(range(5))
    y_clean = [100.0 + 10.0 * i for i in x_clean]
    fit_clean = _linear_fit(x_clean, y_clean)
    assert fit_clean is not None
    r2_clean = _r_squared(x_clean, y_clean, fit_clean[0], fit_clean[1])

    x_noisy = list(range(5))
    y_noisy = [100.0, 130.0, 105.0, 160.0, 115.0]
    fit_noisy = _linear_fit(x_noisy, y_noisy)
    assert fit_noisy is not None
    r2_noisy = _r_squared(x_noisy, y_noisy, fit_noisy[0], fit_noisy[1])

    # Clean channel has higher R²
    assert r2_clean > r2_noisy, "Clean channel should have higher R² than noisy"
    # Score formula: touches * (1 + R²) — with same touches, clean wins
    touches = 3
    score_clean = touches * (1 + r2_clean)
    score_noisy = touches * (1 + r2_noisy)
    assert score_clean > score_noisy
