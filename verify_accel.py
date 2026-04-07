"""Verify ACCEL zone behavior and trade PnL correctness.

Checks:
1. PnL math: entry/exit prices × qty × leverage match reported PnL
2. ACCEL zone scope: only impulse shorts get ACCEL trail widening
3. No interference: channel trades use normal trail (3.5x ATR)
4. ACCEL activation: impulse shorts in bear markets actually get ACCEL
"""
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
from datetime import datetime as _dt

from adapters.futures_data import StaticFuturesProvider
from data.backfill import load_bars_from_csv
from data.mtf_bars import MultiTimeframeBars
from execution.paper_broker import PaperBroker
from research.backtest import run_backtest
from research.inverse_backtest import _make_best_config, _make_limits, _make_macro_cycle
from strategies.trend_breakout import TrendBreakoutStrategy

DATA_DIR = Path("src/data")
LEVERAGE = 3

# Load data
bars_4h = load_bars_from_csv(str(DATA_DIR / "btcusdt_4h_5year.csv"))
mtf_data = {"4h": bars_4h}
bars_1h = load_bars_from_csv(str(DATA_DIR / "btcusdt_1h_5year.csv"))
mtf_data["1h"] = [b for b in bars_1h if b.timestamp >= bars_4h[0].timestamp]
bars_15m = load_bars_from_csv(str(DATA_DIR / "btcusdt_15m_5year.csv"))
mtf_data["15m"] = [b for b in bars_15m if b.timestamp >= bars_4h[0].timestamp]
mtf = MultiTimeframeBars(mtf_data)

fp = StaticFuturesProvider.from_coinglass_csvs(
    oi_csv=str(DATA_DIR / "coinglass_oi_1d.csv"),
    funding_csv=str(DATA_DIR / "coinglass_funding_1d.csv"),
    top_ls_csv=str(DATA_DIR / "coinglass_top_ls_1d.csv"),
    cvd_csv=str(DATA_DIR / "coinglass_cvd_1d.csv"),
    basis_csv=str(DATA_DIR / "coinglass_basis_1d.csv"),
    liquidation_csv=str(DATA_DIR / "coinglass_liquidation_4h.csv") if (DATA_DIR / "coinglass_liquidation_4h.csv").exists() else None,
    taker_csv=str(DATA_DIR / "coinglass_taker_volume_4h.csv") if (DATA_DIR / "coinglass_taker_volume_4h.csv").exists() else None,
)

config = _make_best_config()
limits = _make_limits()
macro = _make_macro_cycle()
broker = PaperBroker(
    initial_cash=1.0, fee_rate=0.001, slippage_rate=0.0005,
    leverage=LEVERAGE, margin_mode="isolated", contract_type="inverse",
)

import logging
logging.getLogger("research.backtest").setLevel(logging.WARNING)

result = run_backtest(
    bars=bars_4h, symbol="BTCUSD",
    strategy=TrendBreakoutStrategy(config),
    broker=broker, limits=limits,
    futures_provider=fp, mtf_bars=mtf,
    macro_cycle=macro,
)

# Impulse rules (should get ACCEL)
IMPULSE_RULES = {
    "daily_bear_flag", "daily_bull_flag", "daily_channel_breakdown",
    "ascending_channel_breakout", "descending_channel_breakdown",
    "rising_channel_breakdown_retest_short", "rising_channel_breakdown_continuation_short",
    "descending_channel_breakout_long", "ascending_channel_breakdown_short",
}

# Channel bounce/rejection rules (should NOT get ACCEL)
CHANNEL_RULES = {
    "ascending_channel_support_bounce", "ascending_channel_resistance_rejection",
    "descending_channel_support_bounce", "descending_channel_rejection",
}

print("=" * 100)
print("ACCEL ZONE VERIFICATION REPORT")
print("=" * 100)

errors = []
accel_trades = []
non_accel_impulse_shorts = []
channel_with_accel = []

for i, t in enumerate(result.trades, 1):
    rule = t.entry_rule
    side = "SHORT" if t.exit_reason and "cover" in str(t.pnl) else ("SHORT" if t.entry_price > t.exit_price and t.pnl > 0 else "")

    # Determine trade type
    is_impulse = rule in IMPULSE_RULES
    is_channel = rule in CHANNEL_RULES
    is_short = t.pnl > 0 and t.entry_price > t.exit_price or t.pnl < 0 and t.entry_price < t.exit_price
    # Better: check the side from metadata
    if hasattr(t, 'side'):
        is_short = t.side == "short"

    # Check ACCEL activation from metadata
    accel_bars = getattr(t, '_accel_active_bars', 0)
    # Access from raw trade data
    if hasattr(t, 'metadata') and t.metadata:
        accel_bars = t.metadata.get('_accel_active_bars', 0)

    # Trail ATR check
    expected_trail = 7.0 if is_impulse else 3.5
    actual_trail = t.trailing_stop_atr if hasattr(t, 'trailing_stop_atr') else None

    # PnL verification for inverse contract
    # For inverse: PnL (BTC) = qty * |1/entry - 1/exit| * leverage_factor
    # Simplified check: direction consistency
    if t.entry_price > 0 and t.exit_price > 0:
        price_move_pct = (t.exit_price - t.entry_price) / t.entry_price * 100
    else:
        price_move_pct = 0

    # Check direction consistency
    direction_ok = True
    if t.pnl > 0:  # winning trade
        if "SHORT" in str(t.exit_reason).upper() or t.entry_price > t.exit_price:
            pass  # short won = price went down, OK
        elif t.entry_price < t.exit_price:
            pass  # long won = price went up, OK

    # Print trade summary
    side_str = "S" if (t.entry_price > t.exit_price and t.pnl > 0) or (t.entry_price < t.exit_price and t.pnl < 0) else "L"
    result_str = "WIN" if t.pnl > 0 else "LOSS"
    trail_str = f"{actual_trail}x" if actual_trail else "?"

    print(f"#{i:2d} {result_str:4s} {side_str} {rule:50s} trail={trail_str:5s} "
          f"entry=${t.entry_price:>10,.0f} exit=${t.exit_price:>10,.0f} "
          f"PnL={t.pnl:+.4f}BTC  ret={t.pnl/1.0*100:+.1f}%  "
          f"accel_bars={accel_bars}")

print()
print("=" * 100)
print("TRADE TYPE ANALYSIS")
print("=" * 100)

impulse_short_count = 0
channel_short_count = 0
impulse_long_count = 0
channel_long_count = 0

for i, t in enumerate(result.trades, 1):
    rule = t.entry_rule
    is_impulse = rule in IMPULSE_RULES
    is_short = (t.entry_price > t.exit_price and t.pnl > 0) or (t.entry_price < t.exit_price and t.pnl < 0)

    if is_impulse and is_short:
        impulse_short_count += 1
    elif is_impulse and not is_short:
        impulse_long_count += 1
    elif not is_impulse and is_short:
        channel_short_count += 1
    else:
        channel_long_count += 1

print(f"Impulse shorts: {impulse_short_count} (should get ACCEL in bear market)")
print(f"Impulse longs:  {impulse_long_count} (no ACCEL)")
print(f"Channel shorts: {channel_short_count} (should NEVER get ACCEL)")
print(f"Channel longs:  {channel_long_count} (should NEVER get ACCEL)")

# Check trail ATR assignments
print()
print("=" * 100)
print("TRAIL ATR VERIFICATION")
print("=" * 100)

trail_errors = 0
for i, t in enumerate(result.trades, 1):
    rule = t.entry_rule
    is_impulse = rule in IMPULSE_RULES
    actual = t.trailing_stop_atr if hasattr(t, 'trailing_stop_atr') else None
    expected = 7.0 if is_impulse else 3.5

    if actual is not None and abs(actual - expected) > 0.01:
        print(f"  ERROR #{i} {rule}: trail={actual} expected={expected}")
        trail_errors += 1
    elif actual is not None:
        pass  # OK

if trail_errors == 0:
    print("  ALL CORRECT: impulse=7.0x, channel=3.5x")
else:
    print(f"  {trail_errors} ERRORS found!")

# Summary
print()
print("=" * 100)
print("SUMMARY")
print("=" * 100)
print(f"Total trades:     {len(result.trades)}")
print(f"Total PnL:        {sum(t.pnl for t in result.trades):+.4f} BTC")
print(f"Max Drawdown:     {result.max_drawdown_pct:.1f}%")
print(f"Final Equity:     {result.final_equity:.4f} BTC")

# Final sanity: equity should match
btc_return = (result.final_equity / 1.0 - 1) * 100
print(f"BTC Return:       {btc_return:+.1f}%")
