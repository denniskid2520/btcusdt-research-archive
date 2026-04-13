"""Strategy B: ACCEL zone bear impulse short-only strategy.

Pure bear market impulse short strategy. Only enters during ACCEL zone:
  - Weekly MACD death cross (hist <= 0)
  - Daily MACD < 0
  - ATR7 trail * 3x ACCEL multiplier
  - No longs

Earned BTC is sold 30% at macro cycle highs (same D+W RSI trigger as Strategy A).

Designed to run on a SEPARATE API/account from Strategy A.

Run with: PYTHONPATH=src python -m research.inverse_backtest_b
"""

from __future__ import annotations

import logging
from pathlib import Path

from adapters.futures_data import StaticFuturesProvider
from data.backfill import load_bars_from_csv
from data.mtf_bars import MultiTimeframeBars
from execution.paper_broker import PaperBroker
from research.backtest import run_backtest
from research.macro_cycle import MacroCycleConfig
from risk.limits import RiskLimits
from strategies.trend_breakout import TrendBreakoutConfig, TrendBreakoutStrategy

logging.getLogger("research.backtest").setLevel(logging.WARNING)

SYMBOL = "BTCUSD"
DATA_DIR = Path("src/data")
INITIAL_BTC = 1.0
LEVERAGE = 3
FORCE_5YEAR = True


def _make_config() -> TrendBreakoutConfig:
    """ACCEL zone short-only config.

    Short-only bear impulse strategy:
    - weekly_macd_short_gate=True: only short during weekly death cross (W-hist<=0)
    - allow_longs=False: no long positions
    - accel_trail_multiplier=3.0: 3x trail widening during ACCEL zone
    - ATR7 base trail
    """
    return TrendBreakoutConfig(
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
        allow_longs=False,  # NO longs — pure bear short strategy
        enable_ascending_channel_resistance_rejection=True,
        enable_descending_channel_breakout_long=False,
        enable_ascending_channel_breakdown_short=True,
        use_trailing_exit=True,
        trailing_stop_atr=3.5,
        impulse_trailing_stop_atr=7.0,
        impulse_harvest_pct=0.0,
        impulse_harvest_min_pnl=0.05,
        rsi_filter=True,
        rsi_period=3,
        rsi_oversold=20.0,
        adx_filter=True,
        adx_threshold=25.0,
        adx_mode="smart",
        oi_divergence_lookback=48,
        oi_divergence_threshold=-0.10,
        top_ls_contrarian=True,
        top_ls_threshold=1.5,
        liq_cascade_filter=True,
        liq_cascade_threshold=5e7,
        taker_imbalance_filter=True,
        taker_imbalance_threshold=1.3,
        cvd_divergence_filter=True,
        cvd_divergence_lookback=48,
        weekly_macd_short_gate=True,  # Only short during weekly death cross
        weekly_macd_golden_cross_exit=True,  # Close shorts when weekly golden cross
        accel_trail_multiplier=3.0,  # 3x trail widening during ACCEL zone
        bear_flag_max_weekly_rsi=0.0,
        loss_cooldown_count=0,
        loss_cooldown_bars=24,
        bear_reversal_enabled=False,
        mtf_entry_confirmation=True,
        mtf_1h_sizing_mode="scale",
        mtf_1h_lookback=4,
        mtf_1h_min_wick_ratio=0.3,
        mtf_1h_no_confirm_confidence=0.8,
        mtf_stop_refinement=True,
        mtf_15m_lookback=16,
        mtf_stop_max_tighten_pct=0.30,
        scale_in_enabled=False,
    )


def _make_limits() -> RiskLimits:
    return RiskLimits(
        max_position_pct=0.90,
        risk_per_trade_pct=0.05,
        leverage=LEVERAGE,
    )


def _make_macro_cycle() -> MacroCycleConfig:
    """Macro cycle: sell 30% BTC at highs (same timing as Strategy A)."""
    return MacroCycleConfig(
        weekly_rsi_period=14,
        monthly_rsi_sell_start=70.0,
        monthly_rsi_sell_step=7.0,
        monthly_rsi_sell_pct=0.10,
        min_btc_reserve=1.0,
        # D+W sell: same RSI triggers as Strategy A, sell 35% at tops
        daily_rsi_sell_trigger=75.0,
        weekly_rsi_sell_confirm=70.0,
        daily_rsi_sell_pct=0.45,  # 45% of BTC holdings
        dw_sell_min_monthly_rsi=65.0,
        # All buy triggers disabled
        daily_rsi_buy_trigger=0.0,
        weekly_rsi_buy_confirm=0.0,
        daily_rsi_buy_pct=0.0,
        dw_buy_bounce_pct=0.0,
        weekly_rsi_buy_trigger=0.0,
        weekly_rsi_buy_pct=0.0,
        # Divergence sell (same as Strategy A)
        divergence_pivot_window=4,
        divergence_min_rsi_drop=5.0,
        sell_pct_per_rsi_point=0.01,
        sell_pct_min=0.10,
        sell_pct_max=0.40,
        buy_pct_per_rsi_point=0.0,
        buy_pct_min=0.0,
        buy_pct_max=0.0,
        divergence_sell_min_monthly_rsi=65.0,
        divergence_buy_max_monthly_rsi=40.0,
        cooldown_bars_4h=168,
    )


def main() -> None:
    import argparse
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    from datetime import datetime as _dt

    parser = argparse.ArgumentParser(description="Strategy B: ACCEL zone short-only backtest")
    parser.add_argument("--start", default="", help="Start date YYYY-MM-DD")
    parser.add_argument("--force5y", action="store_true", default=FORCE_5YEAR)
    parser.add_argument("--no-force5y", dest="force5y", action="store_false")
    args = parser.parse_args()

    if args.force5y:
        _4h_path = DATA_DIR / "btcusdt_4h_5year.csv"
    else:
        _4h_path = DATA_DIR / "btcusdt_4h_6year.csv"
        if not _4h_path.exists():
            _4h_path = DATA_DIR / "btcusdt_4h_5year.csv"

    all_bars_4h = load_bars_from_csv(str(_4h_path))
    _liq_csv = DATA_DIR / "coinglass_liquidation_4h.csv"
    _taker_csv = DATA_DIR / "coinglass_taker_volume_4h.csv"
    fp = StaticFuturesProvider.from_coinglass_csvs(
        oi_csv=str(DATA_DIR / "coinglass_oi_1d.csv"),
        funding_csv=str(DATA_DIR / "coinglass_funding_1d.csv"),
        top_ls_csv=str(DATA_DIR / "coinglass_top_ls_1d.csv"),
        cvd_csv=str(DATA_DIR / "coinglass_cvd_1d.csv"),
        basis_csv=str(DATA_DIR / "coinglass_basis_1d.csv"),
        liquidation_csv=str(_liq_csv) if _liq_csv.exists() else None,
        taker_csv=str(_taker_csv) if _taker_csv.exists() else None,
    )

    if args.start:
        _start_dt = _dt.strptime(args.start, "%Y-%m-%d")
        bars_4h = [b for b in all_bars_4h if b.timestamp >= _start_dt]
        print(f"[Data] {len(bars_4h)} bars from {args.start}")
    else:
        bars_4h = all_bars_4h
        print(f"[Data] {len(bars_4h)} bars ({_4h_path.name})")

    mtf_data: dict[str, list] = {"4h": bars_4h}
    if args.force5y:
        bars_1h_path = DATA_DIR / "btcusdt_1h_5year.csv"
        bars_15m_path = DATA_DIR / "btcusdt_15m_5year.csv"
    else:
        bars_1h_path = DATA_DIR / "btcusdt_1h_6year.csv"
        bars_15m_path = DATA_DIR / "btcusdt_15m_6year.csv"
        if not bars_1h_path.exists():
            bars_1h_path = DATA_DIR / "btcusdt_1h_5year.csv"
        if not bars_15m_path.exists():
            bars_15m_path = DATA_DIR / "btcusdt_15m_5year.csv"

    if bars_1h_path.exists():
        all_1h = load_bars_from_csv(str(bars_1h_path))
        mtf_data["1h"] = [b for b in all_1h if b.timestamp >= bars_4h[0].timestamp]
    if bars_15m_path.exists():
        all_15m = load_bars_from_csv(str(bars_15m_path))
        mtf_data["15m"] = [b for b in all_15m if b.timestamp >= bars_4h[0].timestamp]
    # Native daily + weekly bars for accurate MACD gate
    _1d_path = DATA_DIR / "btcusdt_1d_6year.csv"
    _1w_path = DATA_DIR / "btcusdt_1w_6year.csv"
    if _1d_path.exists():
        mtf_data["1d"] = load_bars_from_csv(str(_1d_path))
    if _1w_path.exists():
        mtf_data["1w"] = load_bars_from_csv(str(_1w_path))
    mtf = MultiTimeframeBars(mtf_data)

    config = _make_config()
    limits = _make_limits()
    macro = _make_macro_cycle()

    broker = PaperBroker(
        initial_cash=INITIAL_BTC,
        fee_rate=0.001,
        slippage_rate=0.0005,
        leverage=LEVERAGE,
        margin_mode="isolated",
        contract_type="inverse",
    )

    start_price = bars_4h[0].close
    end_price = bars_4h[-1].close

    print("=" * 80)
    print("STRATEGY B: ACCEL ZONE BEAR IMPULSE SHORT-ONLY")
    print("=" * 80)
    print(f"Data: {len(bars_4h)} bars, {bars_4h[0].timestamp} to {bars_4h[-1].timestamp}")
    print(f"Capital: {INITIAL_BTC:.2f} BTC | Leverage: {LEVERAGE}x | Margin: isolated")
    print(f"Entry gate: ACCEL zone ONLY (W-hist<=0 + D-MACD<0)")
    print(f"Trail: ATR7 * 3x ACCEL = 21 ATR effective")
    print(f"Longs: DISABLED | Sell at highs: 35% BTC | Golden cross exit: ON")
    print()

    result = run_backtest(
        bars=bars_4h, symbol=SYMBOL,
        strategy=TrendBreakoutStrategy(config),
        broker=broker, limits=limits,
        futures_provider=fp,
        mtf_bars=mtf,
        macro_cycle=macro,
    )

    final_btc = result.final_equity
    btc_return_pct = (final_btc / INITIAL_BTC - 1) * 100
    btc_profit = final_btc - INITIAL_BTC
    usdt_reserves = result.usdt_reserves
    start_usd = INITIAL_BTC * start_price
    btc_usd = final_btc * end_price
    final_usd = btc_usd + usdt_reserves
    usd_return_pct = (final_usd / start_usd - 1) * 100
    passive_usd = INITIAL_BTC * end_price
    passive_return_pct = (end_price / start_price - 1) * 100

    wins = sum(1 for t in result.trades if t.pnl > 0)
    total = max(len(result.trades), 1)
    wr = wins / total * 100
    avg_win = sum(t.pnl for t in result.trades if t.pnl > 0) / max(wins, 1)
    losses = sum(1 for t in result.trades if t.pnl < 0)
    avg_loss = sum(t.pnl for t in result.trades if t.pnl < 0) / max(losses, 1)
    ratio = btc_return_pct / result.max_drawdown_pct if result.max_drawdown_pct > 0 else 0

    print("== BTC Returns ================================================")
    print(f"  Starting BTC:      {INITIAL_BTC:.4f} BTC")
    print(f"  Final BTC:         {final_btc:.4f} BTC")
    print(f"  BTC Profit:        {btc_profit:+.4f} BTC ({btc_return_pct:+.1f}%)")
    print(f"  Max Drawdown:      {result.max_drawdown_pct:.1f}%")
    print(f"  Return/DD:         {ratio:.2f}")
    print()
    print("== Portfolio ===================================================")
    print(f"  BTC holdings:      {final_btc:.4f} BTC (=${btc_usd:>12,.0f})")
    print(f"  USDT reserves:     ${usdt_reserves:>12,.0f}")
    print(f"  TOTAL value:       ${final_usd:>12,.0f}")
    print(f"  Start value:       ${start_usd:>12,.0f}")
    print(f"  Total Return:      {usd_return_pct:+.1f}%")
    print()
    print("== vs Passive Hold =============================================")
    print(f"  Passive (1 BTC):   ${passive_usd:>12,.0f} ({passive_return_pct:+.1f}%)")
    print(f"  Strategy B:        ${final_usd:>12,.0f} ({usd_return_pct:+.1f}%)")
    print(f"  Alpha:             ${final_usd - passive_usd:>+12,.0f}")
    print()
    print("== Trade Stats =================================================")
    print(f"  Total trades:      {result.total_trades}")
    print(f"  Win rate:          {wr:.1f}%")
    print(f"  Avg win:           {avg_win:+.6f} BTC")
    print(f"  Avg loss:          {avg_loss:+.6f} BTC")
    if avg_loss != 0:
        print(f"  Win/Loss ratio:    {abs(avg_win / avg_loss):.2f}")
    print()

    # Trade log
    for i, t in enumerate(result.trades, 1):
        icon = "✅" if t.pnl > 0 else "❌"
        print(f"  #{i:2d} {icon} {t.side:5s} {t.entry_rule:45s} "
              f"{t.entry_time.strftime('%Y-%m-%d')} ${t.entry_price:>9,.0f} → "
              f"${t.exit_price:>9,.0f}  {t.pnl:+.4f} BTC  ({t.exit_reason})")

    print()
    print("=" * 60)
    print(f"Strategy B: {btc_return_pct:+.1f}% BTC | {result.total_trades} trades | "
          f"{wr:.0f}% WR | {result.max_drawdown_pct:.1f}% DD")
    print("=" * 60)


if __name__ == "__main__":
    main()
