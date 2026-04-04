"""Tests for channel detection accuracy — the system should detect channels
that the narrative identifies, WITHOUT using the narrative as input.

The narrative serves as ground truth to validate algorithmic detection.
"""
from __future__ import annotations

from datetime import datetime

from adapters.base import Position
from data.backfill import load_bars_from_csv
from strategies.trend_breakout import TrendBreakoutConfig, TrendBreakoutStrategy


def _load_bars():
    return load_bars_from_csv("src/data/btcusdt_4h_5year.csv")


def _get_bars_up_to(bars, date_str: str):
    """Return all bars up to and including the given date."""
    cutoff = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=23, minute=59)
    return [b for b in bars if b.timestamp <= cutoff]


# ── Narrative ground truth: 7 parent structures ──
# A: 2024-03-13 to 2024-10-21, major_descending_channel
# B: 2024-11-14 to 2025-05-02, major_descending_channel
# C: 2025-05-08 to 2025-07-04, local_descending_channel
# D: 2025-07-05 to 2025-10-10, major_ascending_channel
# F: 2025-11-21 to 2026-01-29, ascending_rebound_channel
# G: 2026-02-06 to 2026-04-01, ascending_rebound_channel

# Test: at midpoint of each narrative structure, the algorithm should
# detect a parent channel (descending or ascending) — not "unknown".

NARRATIVE_MIDPOINTS = [
    ("2024-07-01", "descending", "Parent A midpoint"),
    ("2024-09-15", "descending", "Parent A late phase"),
    ("2025-02-01", "descending", "Parent B midpoint"),
    ("2025-04-01", "descending", "Parent B late phase"),
    ("2025-06-15", "descending", "Parent C midpoint"),
    ("2025-08-15", "ascending", "Parent D midpoint"),
    ("2025-12-15", "ascending", "Parent F midpoint"),
    ("2026-03-01", "ascending", "Parent G midpoint"),
]


def test_parent_detection_rate_at_narrative_midpoints() -> None:
    """Algorithm should detect parent channels at >=75% of narrative midpoints.

    This is the key test: if detection rate is below 75%, the system
    can't function without narrative.  Target: >=6 out of 8 detected.
    """
    bars = _load_bars()

    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.02,
            entry_buffer_pct=0.20,
            stop_buffer_pct=0.08,
            use_narrative_regime=False,
            require_parent_confirmation=True,
            # Extended parent detection parameters:
            parent_structure_lookback=360,
            parent_timeframe_factor=6,
            parent_pivot_window=3,
            parent_min_pivot_highs=2,
            parent_min_pivot_lows=2,
            max_slope_divergence_ratio=1.5,
        )
    )

    detected = 0
    total = len(NARRATIVE_MIDPOINTS)

    for date_str, expected_direction, label in NARRATIVE_MIDPOINTS:
        history = _get_bars_up_to(bars, date_str)
        if len(history) < 100:
            continue
        evaluation = strategy.evaluate(
            symbol="BTCUSDT", bars=history, position=Position(symbol="BTCUSDT"),
        )
        parent = evaluation.parent_context
        if parent and parent.get("parent_structure_type") not in {"unknown", None}:
            detected += 1
            direction = "descending" if "descending" in str(parent.get("parent_structure_type", "")) else "ascending"
            match = "OK" if direction == expected_direction else "WRONG_DIR"
            print(f"  {label:<30} DETECTED: {parent['parent_structure_type']} [{match}]")
        else:
            print(f"  {label:<30} MISSED (unknown)")

    detection_rate = detected / total
    print(f"\n  Detection rate: {detected}/{total} = {detection_rate:.0%}")
    assert detection_rate >= 0.75, (
        f"Parent detection rate {detection_rate:.0%} is below 75% target. "
        f"Detected {detected}/{total} narrative midpoints."
    )


def test_parent_direction_accuracy_at_narrative_midpoints() -> None:
    """Algorithm should get the channel DIRECTION correct at >=62.5% of midpoints.

    Detection rate is already 88%. But 4/7 detected channels have WRONG direction.
    With R²-weighted scoring + recent-consistency, target: >=5/8 correct direction.
    """
    bars = _load_bars()

    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            impulse_threshold_pct=0.02,
            entry_buffer_pct=0.20,
            stop_buffer_pct=0.08,
            use_narrative_regime=False,
            require_parent_confirmation=True,
            parent_structure_lookback=360,
            parent_timeframe_factor=6,
            parent_pivot_window=3,
            parent_min_pivot_highs=2,
            parent_min_pivot_lows=2,
            max_slope_divergence_ratio=1.5,
        )
    )

    correct_direction = 0
    detected = 0
    total = len(NARRATIVE_MIDPOINTS)

    for date_str, expected_direction, label in NARRATIVE_MIDPOINTS:
        history = _get_bars_up_to(bars, date_str)
        if len(history) < 100:
            continue
        evaluation = strategy.evaluate(
            symbol="BTCUSDT", bars=history, position=Position(symbol="BTCUSDT"),
        )
        parent = evaluation.parent_context
        if parent and parent.get("parent_structure_type") not in {"unknown", None}:
            detected += 1
            structure = str(parent.get("parent_structure_type", ""))
            direction = "descending" if "descending" in structure else "ascending"
            if direction == expected_direction:
                correct_direction += 1
                print(f"  {label:<30} CORRECT: {structure}")
            else:
                print(f"  {label:<30} WRONG: {structure} (expected {expected_direction})")
        else:
            print(f"  {label:<30} MISSED")

    direction_rate = correct_direction / total
    print(f"\n  Direction accuracy: {correct_direction}/{total} = {direction_rate:.0%}")
    print(f"  Detection rate: {detected}/{total}")
    assert correct_direction >= 5, (
        f"Direction accuracy {correct_direction}/{total} is below target (5/8). "
        f"R²-weighted scoring should improve this."
    )


def test_no_narrative_trade_count_minimum() -> None:
    """Without narrative, strategy should find at least 40 trades in 5yr.

    With narrative we get 61. Target: >=40 without it (65% of narrative).
    """
    bars = _load_bars()
    from execution.paper_broker import PaperBroker
    from research.backtest import run_backtest
    from risk.limits import RiskLimits

    strategy = TrendBreakoutStrategy(
        TrendBreakoutConfig(
            impulse_lookback=12,
            structure_lookback=24,
            secondary_structure_lookback=48,
            impulse_threshold_pct=0.02,
            entry_buffer_pct=0.20,
            stop_buffer_pct=0.08,
            min_r_squared=0.0,
            min_stop_atr_multiplier=1.5,
            time_stop_bars=84,
            use_narrative_regime=False,
            require_parent_confirmation=True,
            # Improved parent detection:
            parent_structure_lookback=360,
            parent_pivot_window=3,
            max_slope_divergence_ratio=1.5,
            enable_ascending_channel_resistance_rejection=False,
            enable_descending_channel_breakout_long=False,
            enable_ascending_channel_breakdown_short=False,
        )
    )

    broker = PaperBroker(initial_cash=10_000.0, fee_rate=0.001, slippage_rate=0.0005, leverage=3)
    result = run_backtest(bars, "BTCUSDT", strategy, broker, RiskLimits(leverage=3))

    print(f"\n  No-narrative trades: {result.total_trades}")
    wins = sum(1 for t in result.trades if t.pnl > 0)
    wr = wins / result.total_trades * 100 if result.total_trades > 0 else 0
    print(f"  Win rate: {wr:.1f}%")
    print(f"  Return: {result.total_return_pct:+.1f}%")

    assert result.total_trades >= 40, (
        f"Only {result.total_trades} trades without narrative. "
        f"Target: >=40 (narrative gets 61)."
    )
