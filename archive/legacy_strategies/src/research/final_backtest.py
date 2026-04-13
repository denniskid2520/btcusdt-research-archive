"""Final comprehensive backtest: best config + MTF stop refinement.

$10,000 initial, 3x leverage, isolated margin.
4h structure + 15m stop tightening (30% max).
Run with: PYTHONPATH=src python -m research.final_backtest
"""

from __future__ import annotations

import logging
from pathlib import Path

from adapters.futures_data import StaticFuturesProvider
from data.backfill import load_bars_from_csv
from data.mtf_bars import MultiTimeframeBars
from execution.paper_broker import PaperBroker
from research.backtest import BacktestResult, run_backtest
from risk.limits import RiskLimits
from strategies.trend_breakout import TrendBreakoutConfig, TrendBreakoutStrategy

logging.getLogger("research.backtest").setLevel(logging.WARNING)

SYMBOL = "BTCUSDT"
DATA_DIR = Path("src/data")
INITIAL_CASH = 10_000.0
LEVERAGE = 3


def _make_best_config() -> TrendBreakoutConfig:
    """Best known config after all sweeps."""
    return TrendBreakoutConfig(
        # Channel detection
        impulse_lookback=12,
        structure_lookback=24,
        secondary_structure_lookback=48,
        pivot_window=2,
        min_pivot_highs=2,
        min_pivot_lows=2,
        impulse_threshold_pct=0.02,
        entry_buffer_pct=0.30,
        stop_buffer_pct=0.08,
        min_r_squared=0.0,
        min_stop_atr_multiplier=1.5,
        time_stop_bars=168,
        # All channel trade types enabled
        enable_ascending_channel_resistance_rejection=True,
        enable_descending_channel_breakout_long=True,
        enable_ascending_channel_breakdown_short=True,
        # Trailing stop (biggest single improvement)
        use_trailing_exit=True,
        trailing_stop_atr=3.5,
        # Proven filters
        rsi_filter=True,
        rsi_period=3,
        adx_filter=True,
        adx_threshold=25.0,
        adx_mode="smart",
        oi_divergence_lookback=48,
        oi_divergence_threshold=-0.10,
        # NEW: Top trader L/S contrarian (from Coinglass)
        top_ls_contrarian=True,
        top_ls_threshold=1.5,
        # NEW: Multi-timeframe (4h + 1h + 15m)
        # 1h: confidence-based sizing (scale mode, 80% position if no rejection wick)
        mtf_entry_confirmation=True,
        mtf_1h_sizing_mode="scale",
        mtf_1h_lookback=4,
        mtf_1h_min_wick_ratio=0.3,
        mtf_1h_no_confirm_confidence=0.8,
        # 15m: stop refinement (tighten stops 30% max via micro-structure)
        mtf_stop_refinement=True,
        mtf_15m_lookback=16,
        mtf_stop_max_tighten_pct=0.30,
        # Scale-in (ready but not yet configured)
        scale_in_enabled=False,
    )


def _make_limits() -> RiskLimits:
    return RiskLimits(
        max_position_pct=0.90,
        risk_per_trade_pct=0.05,
        leverage=LEVERAGE,
    )


def main() -> None:
    bars_4h = load_bars_from_csv(str(DATA_DIR / "btcusdt_4h_5year.csv"))
    fp = StaticFuturesProvider.from_coinglass_csvs(
        oi_csv=str(DATA_DIR / "coinglass_oi_1d.csv"),
        funding_csv=str(DATA_DIR / "coinglass_funding_1d.csv"),
        top_ls_csv=str(DATA_DIR / "coinglass_top_ls_1d.csv"),
        cvd_csv=str(DATA_DIR / "coinglass_cvd_1d.csv"),
        basis_csv=str(DATA_DIR / "coinglass_basis_1d.csv"),
    )

    # Load multi-timeframe data (4h + 1h + 15m)
    mtf_data: dict[str, list] = {"4h": bars_4h}
    bars_1h_path = DATA_DIR / "btcusdt_1h_5year.csv"
    bars_15m_path = DATA_DIR / "btcusdt_15m_5year.csv"
    if bars_1h_path.exists():
        bars_1h = load_bars_from_csv(str(bars_1h_path))
        mtf_data["1h"] = bars_1h
        print(f"1h bars loaded: {len(bars_1h)}")
    if bars_15m_path.exists():
        bars_15m = load_bars_from_csv(str(bars_15m_path))
        mtf_data["15m"] = bars_15m
        print(f"15m bars loaded: {len(bars_15m)}")
    mtf = MultiTimeframeBars(mtf_data)

    config = _make_best_config()
    limits = _make_limits()

    broker = PaperBroker(
        initial_cash=INITIAL_CASH,
        fee_rate=0.001,
        slippage_rate=0.0005,
        leverage=LEVERAGE,
        margin_mode="isolated",
    )

    print("=" * 80)
    print("FINAL BACKTEST — 3-Timeframe (4h + 1h + 15m)")
    print("=" * 80)
    print(f"Data: {len(bars_4h)} bars, {bars_4h[0].timestamp} to {bars_4h[-1].timestamp}")
    print(f"Capital: ${INITIAL_CASH:,.0f} | Leverage: {LEVERAGE}x | Margin: isolated")
    print(f"Fees: 0.1% + 0.05% slippage per trade")
    print()

    result = run_backtest(
        bars=bars_4h, symbol=SYMBOL,
        strategy=TrendBreakoutStrategy(config),
        broker=broker, limits=limits,
        futures_provider=fp,
        mtf_bars=mtf,
    )

    wr = sum(1 for t in result.trades if t.pnl > 0) / max(len(result.trades), 1) * 100
    avg_win = sum(t.pnl for t in result.trades if t.pnl > 0) / max(sum(1 for t in result.trades if t.pnl > 0), 1)
    avg_loss = sum(t.pnl for t in result.trades if t.pnl < 0) / max(sum(1 for t in result.trades if t.pnl < 0), 1)
    ratio = result.total_return_pct / result.max_drawdown_pct if result.max_drawdown_pct > 0 else 0

    print("── Performance Summary ──────────────────────────────────────")
    print(f"  Total Return:      {result.total_return_pct:+.1f}%")
    print(f"  Final Equity:      ${result.final_equity:,.0f}")
    print(f"  Max Drawdown:      {result.max_drawdown_pct:.1f}%")
    print(f"  Return/DD Ratio:   {ratio:.2f}")
    print(f"  Total Trades:      {result.total_trades}")
    print(f"  Win Rate:          {wr:.1f}%")
    print(f"  Avg Win:           ${avg_win:,.0f}")
    print(f"  Avg Loss:          ${avg_loss:,.0f}")
    if avg_loss != 0:
        print(f"  Win/Loss Ratio:    {abs(avg_win / avg_loss):.2f}")
    print()

    print("── Active Filters ──────────────────────────────────────────")
    print(f"  RSI(3):            oversold<{config.rsi_oversold}, overbought>{config.rsi_overbought}")
    print(f"  ADX(14) smart:     threshold={config.adx_threshold}")
    print(f"  OI divergence:     lookback={config.oi_divergence_lookback}, threshold={config.oi_divergence_threshold}")
    print(f"  Top L/S contrarian: threshold={config.top_ls_threshold}")
    print(f"  Trailing stop:     {config.trailing_stop_atr} ATR")
    print(f"  Time stop:         {config.time_stop_bars} bars")
    print(f"  1h entry scale:    wick={config.mtf_1h_min_wick_ratio}, no_confirm={config.mtf_1h_no_confirm_confidence}")
    print(f"  15m stop refine:   lookback={config.mtf_15m_lookback}, max_tighten={config.mtf_stop_max_tighten_pct}")
    print()

    print("── Position Sizing ─────────────────────────────────────────")
    print(f"  Risk per trade:    {limits.risk_per_trade_pct:.0%}")
    print(f"  Max position:      {limits.max_position_pct:.0%}")
    print(f"  Leverage:          {limits.leverage}x")
    print()

    print("── Trade List ──────────────────────────────────────────────")
    print(f"  {'#':>3} {'Entry Date':<20} {'Side':<6} {'Entry$':>10} {'Exit$':>10} {'P&L':>10} {'Return%':>8}")
    print("  " + "-" * 73)
    running_equity = INITIAL_CASH
    for i, t in enumerate(result.trades):
        running_equity += t.pnl
        trade_return = t.pnl / (running_equity - t.pnl) * 100 if running_equity != t.pnl else 0
        print(
            f"  {i+1:>3} {t.entry_time!s:<20} {t.side:<6} "
            f"${t.entry_price:>9,.0f} ${t.exit_price:>9,.0f} "
            f"${t.pnl:>+9,.0f} {trade_return:>+7.1f}%"
        )

    print()
    print("── Config Parameters ───────────────────────────────────────")
    for field, value in config.__dict__.items():
        if not field.startswith("_"):
            print(f"  {field}: {value}")


if __name__ == "__main__":
    main()
