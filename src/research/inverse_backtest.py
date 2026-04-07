"""Coin-margined (inverse) backtest: same strategy, 1 BTC starting capital.

Key difference from linear (USDT-margined):
  - Capital is in BTC, not USDT
  - PnL settles in BTC
  - When flat (no position), capital still appreciates/depreciates with BTC price
  - This captures BOTH channel trading profits AND underlying BTC price movement

Run with: PYTHONPATH=src python -m research.inverse_backtest
"""

from __future__ import annotations

import logging
from pathlib import Path

from adapters.futures_data import StaticFuturesProvider
from data.backfill import load_bars_from_csv
from data.mtf_bars import MultiTimeframeBars
from execution.paper_broker import PaperBroker
from research.backtest import BacktestResult, run_backtest
from research.macro_cycle import MacroCycleConfig
from risk.limits import RiskLimits
from strategies.trend_breakout import TrendBreakoutConfig, TrendBreakoutStrategy

logging.getLogger("research.backtest").setLevel(logging.WARNING)

SYMBOL = "BTCUSD"
DATA_DIR = Path("src/data")
INITIAL_BTC = 1.0
LEVERAGE = 3
# Backtest starts from this date (empty string = use all data)
START_DATE = ""
# Use native Binance 1d/1w for RSI (True) or aggregate from 4h (False)
USE_NATIVE_RSI = False
# Force 5-year dataset (best result uses original 5-year CSV)
FORCE_5YEAR = True


def _make_best_config() -> TrendBreakoutConfig:
    """Same best config as final_backtest.py (strategy doesn't change)."""
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
        enable_ascending_channel_resistance_rejection=True,
        enable_descending_channel_breakout_long=True,
        enable_ascending_channel_breakdown_short=True,
        use_trailing_exit=True,
        trailing_stop_atr=3.5,
        # Impulse: breakout trades get wider trailing + profit harvest
        impulse_trailing_stop_atr=7.0,
        impulse_harvest_pct=0.0,   # disabled: all profit stays as BTC
        impulse_harvest_min_pnl=0.05,  # (harvest disabled -- sell via macro cycle only)
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
        liq_cascade_threshold=5e7,  # block entry when same-side liq > $50M
        taker_imbalance_filter=True,
        taker_imbalance_threshold=1.3,  # require 1.3x taker flow in trade direction
        cvd_divergence_filter=True,
        cvd_divergence_lookback=48,  # match OI divergence lookback
        weekly_macd_short_gate=False,  # ACCEL zone handles bear/bull context; this gate too aggressive
        accel_trail_multiplier=3.0,  # ACCEL zone (W-death cross + D-MACD<0): 3x trail + block buys
        bear_flag_max_weekly_rsi=0.0,  # disabled
        loss_cooldown_count=0,  # disabled for now
        loss_cooldown_bars=24,  # cooldown 4 days (24 x 4h bars)
        bear_reversal_enabled=False,  # separate project, own capital
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
    """Macro cycle overlay: sell at tops (D+W + monthly guard), buy at bottoms.

    Sell: D-RSI >= 75 AND W-RSI >= 70 -> sell 20% of BTC holdings.
      Monthly RSI guard: only sell when M-RSI >= 65 (confirmed hot market).
      Prevents selling too early in bull cycle.

    Buy: Daily RSI < 27 AND Weekly RSI < 47 -> ARM, bounce 5% -> BUY 20% of USDT.
      + Weekly RSI <= 25 oversold accumulation.

    Divergence: Weekly RSI divergence (structural weakness/strength).
    """
    return MacroCycleConfig(
        weekly_rsi_period=14,
        # Monthly RSI config (kept for divergence guard)
        monthly_rsi_sell_start=70.0,
        monthly_rsi_sell_step=7.0,
        monthly_rsi_sell_pct=0.10,
        min_btc_reserve=1.0,          # NEVER sell below 1 BTC
        # D+W sell: D>=75 + W>=70, sell 35%, monthly guard M>=65
        daily_rsi_sell_trigger=75.0,  # sell when daily RSI >= 75
        weekly_rsi_sell_confirm=70.0, # AND weekly RSI >= 70
        daily_rsi_sell_pct=0.35,      # 35% of current BTC holdings
        dw_sell_min_monthly_rsi=65.0, # guard: block sell if M-RSI < 65
        # Layer 1b: daily+weekly RSI oversold buying — DISABLED (keep USDT from sells)
        daily_rsi_buy_trigger=0.0,    # 0 = disabled
        weekly_rsi_buy_confirm=0.0,
        daily_rsi_buy_pct=0.0,
        dw_buy_bounce_pct=0.0,
        # Layer 1c: weekly RSI bottom buying — DISABLED
        weekly_rsi_buy_trigger=0.0,   # 0 = disabled
        weekly_rsi_buy_pct=0.0,
        # Layer 2: weekly RSI divergence
        divergence_pivot_window=4,    # 4 weeks to confirm peak/trough
        divergence_min_rsi_drop=5.0,  # min 5 RSI points for divergence
        sell_pct_per_rsi_point=0.01,  # 1% per RSI point divergence
        sell_pct_min=0.10,            # floor 10%
        sell_pct_max=0.40,            # cap 40%
        buy_pct_per_rsi_point=0.0,    # divergence buy disabled
        buy_pct_min=0.0,
        buy_pct_max=0.0,
        # Divergence guards: monthly RSI filter
        divergence_sell_min_monthly_rsi=65.0,  # block when monthly RSI below hot zone
        divergence_buy_max_monthly_rsi=40.0,   # block false bottoms in rally
        # Cooldown
        cooldown_bars_4h=168,         # 4 weeks between actions
    )


def main() -> None:
    import argparse
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    from datetime import datetime as _dt

    parser = argparse.ArgumentParser(description="Inverse (coin-margined) backtest")
    parser.add_argument("--start", default=START_DATE, help="Start date YYYY-MM-DD (empty=full dataset)")
    parser.add_argument("--force5y", action="store_true", default=FORCE_5YEAR, help="Force 5-year CSV")
    parser.add_argument("--no-force5y", dest="force5y", action="store_false", help="Use 6-year CSV")
    parser.add_argument("--channel-quality", type=int, default=3, help="Min ★★★ score for ALL channel signals (0=disabled)")
    args = parser.parse_args()
    _force_5y = args.force5y
    _start_date = args.start
    _channel_quality = args.channel_quality

    # Use same OHLCV data (BTC/USD price is the same for linear vs inverse)
    if _force_5y:
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

    # Filter bars from start date onwards (if set)
    if _start_date:
        _start_dt = _dt.strptime(_start_date, "%Y-%m-%d")
        bars_4h = [b for b in all_bars_4h if b.timestamp >= _start_dt]
        print(f"[Data filter] {len(all_bars_4h)} total bars -> {len(bars_4h)} bars from {_start_date}")
    else:
        bars_4h = all_bars_4h
        print(f"[Data] {len(bars_4h)} bars (full dataset, {_4h_path.name})")

    mtf_data: dict[str, list] = {"4h": bars_4h}
    # 1h bars → confidence scoring (MTF)
    if _force_5y:
        bars_1h_path = DATA_DIR / "btcusdt_1h_5year.csv"
    else:
        bars_1h_path = DATA_DIR / "btcusdt_1h_6year.csv"
        if not bars_1h_path.exists():
            bars_1h_path = DATA_DIR / "btcusdt_1h_5year.csv"
    # 15m bars → stop tightening (MTF)
    if _force_5y:
        bars_15m_path = DATA_DIR / "btcusdt_15m_5year.csv"
    else:
        bars_15m_path = DATA_DIR / "btcusdt_15m_6year.csv"
        if not bars_15m_path.exists():
            bars_15m_path = DATA_DIR / "btcusdt_15m_5year.csv"
    # 1d bars → native daily RSI for macro cycle
    bars_1d_path = DATA_DIR / "btcusdt_1d_6year.csv"
    if not bars_1d_path.exists():
        bars_1d_path = DATA_DIR / "btcusdt_1d_5year.csv"
    # 1w bars → native weekly RSI for macro cycle
    bars_1w_path = DATA_DIR / "btcusdt_1w_6year.csv"
    if not bars_1w_path.exists():
        bars_1w_path = DATA_DIR / "btcusdt_1w_5year.csv"

    if bars_1h_path.exists():
        all_1h = load_bars_from_csv(str(bars_1h_path))
        mtf_data["1h"] = [b for b in all_1h if b.timestamp >= bars_4h[0].timestamp]
    if bars_15m_path.exists():
        all_15m = load_bars_from_csv(str(bars_15m_path))
        mtf_data["15m"] = [b for b in all_15m if b.timestamp >= bars_4h[0].timestamp]
    if USE_NATIVE_RSI and bars_1d_path.exists():
        all_1d = load_bars_from_csv(str(bars_1d_path))
        mtf_data["1d"] = [b for b in all_1d if b.timestamp >= bars_4h[0].timestamp]
    if USE_NATIVE_RSI and bars_1w_path.exists():
        all_1w = load_bars_from_csv(str(bars_1w_path))
        mtf_data["1w"] = [b for b in all_1w if b.timestamp >= bars_4h[0].timestamp]
    mtf = MultiTimeframeBars(mtf_data)
    # Show all loaded timeframes
    print(f"[MTF] Timeframes loaded: {sorted(mtf_data.keys())}")
    for _tf in sorted(mtf_data.keys()):
        if _tf != "4h":
            print(f"  {_tf}: {len(mtf_data[_tf])} bars")

    config = _make_best_config()
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
    print("COIN-MARGINED (INVERSE) BACKTEST")
    print("=" * 80)
    print(f"Data: {len(bars_4h)} bars, {bars_4h[0].timestamp} to {bars_4h[-1].timestamp}")
    print(f"Capital: {INITIAL_BTC:.2f} BTC (=${INITIAL_BTC * start_price:,.0f} at start)")
    print(f"Leverage: {LEVERAGE}x | Margin: isolated | Contract: inverse")
    print(f"Macro SELL: D-RSI >= {macro.daily_rsi_sell_trigger:.0f} AND W-RSI >= {macro.weekly_rsi_sell_confirm:.0f} -> sell {macro.daily_rsi_sell_pct:.0%} of BTC (M-RSI >= {macro.dw_sell_min_monthly_rsi:.0f} guard)")
    print(f"Macro BUY:  D-RSI < {macro.daily_rsi_buy_trigger:.0f} + W-RSI < {macro.weekly_rsi_buy_confirm:.0f} -> ARM, bounce {macro.dw_buy_bounce_pct:.0%} -> BUY {macro.daily_rsi_buy_pct:.0%} of USDT")
    print(f"  + Weekly RSI <= {macro.weekly_rsi_buy_trigger} oversold buy | Min reserve: {macro.min_btc_reserve} BTC")
    print(f"Macro DIV:  Weekly RSI divergence (pivot={macro.divergence_pivot_window}w, min_drop={macro.divergence_min_rsi_drop})")
    print(f"  Sell {macro.sell_pct_min:.0%}-{macro.sell_pct_max:.0%} | Buy {macro.buy_pct_min:.0%}-{macro.buy_pct_max:.0%} | Cooldown {macro.cooldown_bars_4h // 42}w")
    print()

    result = run_backtest(
        bars=bars_4h, symbol=SYMBOL,
        strategy=TrendBreakoutStrategy(config),
        broker=broker, limits=limits,
        futures_provider=fp,
        mtf_bars=mtf,
        macro_cycle=macro,
        channel_quality_min_score=_channel_quality,
    )

    # -- BTC Returns --
    final_btc = result.final_equity
    btc_return_pct = (final_btc / INITIAL_BTC - 1) * 100
    btc_profit = final_btc - INITIAL_BTC

    # -- Harvest data --
    usdt_reserves = result.usdt_reserves
    btc_harvested_total = result.btc_harvested

    # -- USD Equivalent (BTC + USDT combined) --
    start_usd = INITIAL_BTC * start_price
    btc_usd = final_btc * end_price
    final_usd = btc_usd + usdt_reserves
    usd_return_pct = (final_usd / start_usd - 1) * 100

    # -- Passive Hold (no trading, just holding 1 BTC) --
    passive_usd = INITIAL_BTC * end_price
    passive_return_pct = (end_price / start_price - 1) * 100

    # -- Trade stats --
    wins = sum(1 for t in result.trades if t.pnl > 0)
    total = max(len(result.trades), 1)
    wr = wins / total * 100
    avg_win = sum(t.pnl for t in result.trades if t.pnl > 0) / max(wins, 1)
    losses = sum(1 for t in result.trades if t.pnl < 0)
    avg_loss = sum(t.pnl for t in result.trades if t.pnl < 0) / max(losses, 1)
    ratio = btc_return_pct / result.max_drawdown_pct if result.max_drawdown_pct > 0 else 0

    print("== BTC Returns (coin-margined) ==============================")
    print(f"  Starting BTC:      {INITIAL_BTC:.4f} BTC")
    print(f"  Final BTC:         {final_btc:.4f} BTC")
    print(f"  BTC Profit:        {btc_profit:+.4f} BTC ({btc_return_pct:+.1f}%)")
    print(f"  Max Drawdown:      {result.max_drawdown_pct:.1f}% (in BTC)")
    print(f"  Return/DD:         {ratio:.2f}")
    print()

    print("== Portfolio Summary =========================================")
    print(f"  BTC holdings:      {final_btc:.4f} BTC (=${btc_usd:>12,.0f})")
    print(f"  USDT reserves:     ${usdt_reserves:>12,.0f}")
    print(f"  TOTAL value:       ${final_usd:>12,.0f}")
    print(f"  Start value:       ${start_usd:>12,.0f} ({INITIAL_BTC} BTC @ ${start_price:,.0f})")
    print(f"  Total Return:      {usd_return_pct:+.1f}%")
    print()

    print("== vs Passive Hold (no trading) ==============================")
    print(f"  Passive (1 BTC):   ${passive_usd:>12,.0f} ({passive_return_pct:+.1f}%)")
    print(f"  Strategy:          ${final_usd:>12,.0f} ({usd_return_pct:+.1f}%)")
    print(f"  Alpha:             ${final_usd - passive_usd:>+12,.0f} ({usd_return_pct - passive_return_pct:+.1f}%)")
    print(f"  Extra BTC earned:  {btc_profit:+.4f} BTC (=${btc_profit * end_price:+,.0f})")
    print(f"  USDT locked in:    ${usdt_reserves:>12,.0f}")
    print()

    print("== Trade Stats ===============================================")
    print(f"  Total trades:      {result.total_trades}")
    print(f"  Win rate:          {wr:.1f}%")
    print(f"  Avg win:           {avg_win:+.6f} BTC (=${avg_win * end_price:+,.0f})")
    print(f"  Avg loss:          {avg_loss:+.6f} BTC (=${avg_loss * end_price:+,.0f})")
    if avg_loss != 0:
        print(f"  Win/Loss ratio:    {abs(avg_win / avg_loss):.2f}")
    print()

    # -- Report with emoji format --
    from strategies.trend_breakout import _BREAKOUT_RULES

    _FLAG_RULES = {"daily_bear_flag", "daily_bull_flag"}

    # ── Rule decoder: maps rule name → (structure, conditions, purpose) ──
    _RULE_DECODE = {
        "ascending_channel_support_bounce": (
            "\u4e0a\u5347\u901a\u9053\u652f\u6490\u53cd\u5f48",
            "\u5075\u6e2c\u4e0a\u5347\u901a\u9053 + \u50f9\u683c\u89f8\u53ca\u652f\u6490\u7dda + \u591a\u982d\u8108\u885d\u78ba\u8a8d",
            "\u901a\u9053\u5167\u53cd\u5f48\u4ea4\u6613\uff1a\u9810\u671f\u50f9\u683c\u5f9e\u652f\u6490\u53cd\u5f48\u5411\u963b\u529b",
        ),
        "ascending_channel_breakout": (
            "\u4e0a\u5347\u901a\u9053\u7a81\u7834",
            "\u5075\u6e2c\u4e0a\u5347\u901a\u9053 + \u50f9\u683c\u7a81\u7834\u963b\u529b\u7dda + \u591a\u982d\u8108\u885d\u78ba\u8a8d",
            "\u7a81\u7834\u4ea4\u6613\uff1a\u901a\u9053\u4e0a\u7dde\u88ab\u7a81\u7834\uff0c\u9810\u671f\u52a0\u901f\u4e0a\u6f32",
        ),
        "descending_channel_rejection": (
            "\u4e0b\u964d\u901a\u9053\u963b\u529b\u62d2\u7d55",
            "\u5075\u6e2c\u4e0b\u964d\u901a\u9053 + \u50f9\u683c\u89f8\u53ca\u963b\u529b\u7dda + \u7a7a\u982d\u8108\u885d\u78ba\u8a8d",
            "\u901a\u9053\u5167\u505a\u7a7a\uff1a\u9810\u671f\u50f9\u683c\u5f9e\u963b\u529b\u56de\u843d\u5411\u652f\u6490",
        ),
        "descending_channel_breakdown": (
            "\u4e0b\u964d\u901a\u9053\u8dcc\u7834",
            "\u5075\u6e2c\u4e0b\u964d\u901a\u9053 + \u50f9\u683c\u8dcc\u7834\u652f\u6490\u7dda + \u7a7a\u982d\u8108\u885d\u78ba\u8a8d",
            "\u7a81\u7834\u4ea4\u6613\uff1a\u901a\u9053\u4e0b\u7dde\u88ab\u8dcc\u7834\uff0c\u9810\u671f\u52a0\u901f\u4e0b\u8dcc",
        ),
        "rising_channel_breakdown_retest_short": (
            "\u4e0a\u5347\u901a\u9053\u8dcc\u7834\u5f8c\u56de\u8e29",
            "\u5075\u6e2c\u4e0a\u5347\u901a\u9053 + \u50f9\u683c\u5df2\u8dcc\u7834\u652f\u6490 + \u56de\u8e29\u652f\u6490\u4f5c\u70ba\u963b\u529b",
            "\u56de\u8e29\u505a\u7a7a\uff1a\u652f\u6490\u8b8a\u963b\u529b\u78ba\u8a8d\uff0c\u9810\u671f\u7e7c\u7e8c\u4e0b\u8dcc",
        ),
        "rising_channel_breakdown_continuation_short": (
            "\u4e0a\u5347\u901a\u9053\u8dcc\u7834\u5ef6\u7e8c",
            "\u5075\u6e2c\u4e0a\u5347\u901a\u9053 + \u50f9\u683c\u6301\u7e8c\u5728\u652f\u6490\u4e0b\u65b9",
            "\u5ef6\u7e8c\u505a\u7a7a\uff1a\u8dcc\u7834\u5f8c\u672a\u53cd\u5f48\uff0c\u4e0b\u8dcc\u52d5\u80fd\u5ef6\u7e8c",
        ),
        "descending_channel_support_bounce": (
            "\u4e0b\u964d\u901a\u9053\u652f\u6490\u53cd\u5f48",
            "\u5075\u6e2c\u4e0b\u964d\u901a\u9053 + \u50f9\u683c\u89f8\u53ca\u652f\u6490\u7dda\uff08\u9707\u76ea\u4ea4\u6613\uff09",
            "\u901a\u9053\u5167\u505a\u591a\uff1a\u5373\u4f7f\u4e0b\u964d\u901a\u9053\uff0c\u652f\u6490\u4ecd\u6709\u53cd\u5f48\u529b\u9053",
        ),
        "ascending_channel_resistance_rejection": (
            "\u4e0a\u5347\u901a\u9053\u963b\u529b\u62d2\u7d55",
            "\u5075\u6e2c\u4e0a\u5347\u901a\u9053 + \u50f9\u683c\u89f8\u53ca\u963b\u529b\u7dda\uff08\u9707\u76ea\u4ea4\u6613\uff09",
            "\u901a\u9053\u5167\u505a\u7a7a\uff1a\u5373\u4f7f\u4e0a\u5347\u901a\u9053\uff0c\u963b\u529b\u4ecd\u6709\u58d3\u529b",
        ),
        "descending_channel_breakout_long": (
            "\u4e0b\u964d\u901a\u9053\u5411\u4e0a\u7a81\u7834",
            "\u5075\u6e2c\u4e0b\u964d\u901a\u9053 + \u50f9\u683c\u7a81\u7834\u963b\u529b\u7dda + \u591a\u982d\u8108\u885d\u78ba\u8a8d",
            "\u53cd\u8f49\u7a81\u7834\uff1a\u4e0b\u964d\u901a\u9053\u88ab\u5411\u4e0a\u7a81\u7834\uff0c\u8da8\u52e2\u53ef\u80fd\u53cd\u8f49",
        ),
        "ascending_channel_breakdown_short": (
            "\u4e0a\u5347\u901a\u9053\u5411\u4e0b\u8dcc\u7834",
            "\u5075\u6e2c\u4e0a\u5347\u901a\u9053 + \u50f9\u683c\u8dcc\u7834\u652f\u6490\u7dda + \u7a7a\u982d\u8108\u885d\u78ba\u8a8d",
            "\u53cd\u8f49\u8dcc\u7834\uff1a\u4e0a\u5347\u901a\u9053\u88ab\u5411\u4e0b\u8dcc\u7834\uff0c\u8da8\u52e2\u53ef\u80fd\u53cd\u8f49",
        ),
        "daily_bear_flag": (
            "\u65e5\u7dda\u718a\u65d7\u5d29\u8dcc",
            "\u65e5\u7dda\u5c3a\u5ea6\u5075\u6e2c\u718a\u65d7\u578b\u614b + \u50f9\u683c\u8dcc\u7834\u65d7\u578b\u4e0b\u7dda",
            "\u8108\u885d\u505a\u7a7a\uff1a\u718a\u65d7\u5ef6\u7e8c\u4e0b\u8dcc\u52d5\u80fd\uff0c\u9810\u671f\u5927\u5e45\u4e0b\u8dcc",
        ),
        "daily_bull_flag": (
            "\u65e5\u7dda\u725b\u65d7\u7a81\u7834",
            "\u65e5\u7dda\u5c3a\u5ea6\u5075\u6e2c\u725b\u65d7\u578b\u614b + \u50f9\u683c\u7a81\u7834\u65d7\u578b\u4e0a\u7dda",
            "\u8108\u885d\u505a\u591a\uff1a\u725b\u65d7\u5ef6\u7e8c\u4e0a\u6f32\u52d5\u80fd\uff0c\u9810\u671f\u5927\u5e45\u4e0a\u6f32",
        ),
    }

    _EXIT_DECODE = {
        "trailing_stop": "\u8ffd\u8e64\u6b62\u640d\uff1a\u50f9\u683c\u56de\u64a4\u8d85\u904e ATR \u52d5\u614b\u6b62\u640d",
        "long_structure_stop": "\u7d50\u69cb\u6b62\u640d\uff1a\u50f9\u683c\u8dcc\u7834\u901a\u9053\u652f\u6490\uff08\u5047\u8a2d\u5931\u6548\uff09",
        "short_structure_stop": "\u7d50\u69cb\u6b62\u640d\uff1a\u50f9\u683c\u7a81\u7834\u901a\u9053\u963b\u529b\uff08\u5047\u8a2d\u5931\u6548\uff09",
        "time_stop": "\u6642\u9593\u6b62\u640d\uff1a\u6301\u5009\u8d85\u904e\u6700\u5927\u6642\u9593\u9650\u5236",
        "forced_end_of_backtest": "\u56de\u6e2c\u7d50\u675f\u5f37\u5236\u5e73\u5009",
        "liquidation": "\u7206\u5009\uff1a\u69d3\u687f\u5c0e\u81f4\u5f37\u5236\u6e05\u7b97",
    }

    # Summary by side
    longs = [t for t in result.trades if t.side == "long"]
    shorts = [t for t in result.trades if t.side == "short"]
    long_wins = sum(1 for t in longs if t.pnl > 0)
    short_wins = sum(1 for t in shorts if t.pnl > 0)
    long_pnl = sum(t.pnl for t in longs)
    short_pnl = sum(t.pnl for t in shorts)
    trade_btc_pnl = long_pnl + short_pnl
    print(f"Long:  {len(longs)} \u7b46 ({long_wins}W/{len(longs)-long_wins}L) "
          f"PnL: {long_pnl:>+.4f} BTC (${long_pnl * end_price:>+,.0f})")
    print(f"Short: {len(shorts)} \u7b46 ({short_wins}W/{len(shorts)-short_wins}L) "
          f"PnL: {short_pnl:>+.4f} BTC (${short_pnl * end_price:>+,.0f})")
    print(f"Total: {result.total_trades} \u7b46, PnL: {trade_btc_pnl:>+.4f} BTC "
          f"(${trade_btc_pnl * end_price:>+,.0f})")
    print()

    # ============================================================
    # Section 2: Harvest Events
    # ============================================================
    if result.harvest_events:
        print(f"{len(result.harvest_events)} \u7b46\u5229\u6f64\u6536\u5272\uff08BTC \u2192 USDT\uff09")
        print(f"{'#':>3}\t{'\u65e5\u671f':<12}\t{'\u4ea4\u6613 PnL':>10}\t"
              f"{'\u6536\u5272\u91cf':>10}\t{'@ \u50f9\u683c':>10}\t{'USDT':>10}")
        print("-" * 70)
        for i, h in enumerate(result.harvest_events):
            print(
                f"{i+1:>3}\t{str(h.timestamp)[:10]:<12}\t"
                f"{h.trade_pnl_btc:>+.3f}B\t{h.harvested_btc:.3f}B\t"
                f"${h.btc_price:>,.0f}\t+${h.usdt_gained:>,.0f}"
            )
        print(f"\t{'\u5408\u8a08':>12}\t\t{btc_harvested_total:.3f}B\t\t"
              f"${usdt_reserves:>,.0f}")
    else:
        print("Harvest: DISABLED (impulse_harvest_pct=0)")
        print("\u6240\u6709\u4ea4\u6613 BTC \u5229\u6f64\u7559\u5728\u5e33\u4e0a\u3002"
              "\u50c5 Macro Cycle \u8ce3\u51fa\u8f49\u63db BTC \u2192 USDT\u3002")
    print()

    # ============================================================
    # Section 3: Macro Cycle Events
    # ============================================================
    macro_events = result.macro_cycle_events or []
    macro_sells = [m for m in macro_events if m.action == "sell_top"]
    macro_buys = [m for m in macro_events if m.action == "buy_bottom"]

    if macro_sells:
        print(f"{len(macro_sells)} \u7b46 Macro Cycle \u8ce3\u51fa")
        print(f"{'#':>3}\t{'\u65e5\u671f':<12}\t{'\u5c64\u7d1a':<8}\t"
              f"{'D-RSI':>6}\t{'W-RSI':>6}\t{'M-RSI':>6}\t"
              f"{'BTC \u8ce3\u51fa':>10}\t{'@ \u50f9\u683c':>10}\t"
              f"{'USDT \u5f97':>12}\t{'BTC \u9918\u984d':>10}\t"
              f"{'USDT \u9918\u984d':>11}")
        print("-" * 120)
        for i, m in enumerate(macro_sells):
            if m.divergence_score == -1.0:
                layer = "D+W"
            elif m.divergence_score > 0:
                layer = f"W-DIV"
            else:
                layer = "OTHER"
            d_rsi = f"{m.weekly_rsi:.1f}"
            w_rsi = f"{m.sma200_ratio:.1f}" if m.divergence_score < 0 else "--"
            m_rsi = f"{m.funding_rate:.1f}" if m.funding_rate is not None else "--"
            print(
                f"{i+1:>3}\t{str(m.timestamp)[:10]:<12}\t{layer:<8}\t"
                f"{d_rsi:>6}\t{w_rsi:>6}\t{m_rsi:>6}\t"
                f"-{m.btc_amount:.4f}B\t${m.btc_price:>,.0f}\t"
                f"+${m.usdt_amount:>,.0f}\t"
                f"{m.btc_balance_after:.4f}B\t${m.usdt_balance_after:>,.0f}"
            )
        total_sold = sum(m.btc_amount for m in macro_sells)
        total_usdt = sum(m.usdt_amount for m in macro_sells)
        avg_sell_p = total_usdt / max(total_sold, 0.0001)
        print(f"\t\u5408\u8a08: {total_sold:.4f} BTC \u8ce3\u51fa "
              f"\u2192 ${total_usdt:>,.0f} USDT (avg ${avg_sell_p:,.0f}/BTC)")
    print()

    if macro_buys:
        print(f"{len(macro_buys)} \u7b46 Macro Cycle \u8cb7\u5165")
        print(f"{'#':>3}\t{'\u65e5\u671f':<12}\t{'\u5c64\u7d1a':<8}\t"
              f"{'D-RSI':>6}\t{'W-RSI':>6}\t"
              f"{'BTC \u8cb7\u5165':>10}\t{'@ \u50f9\u683c':>10}\t"
              f"{'USDT \u82b1\u8cbb':>11}\t{'BTC \u9918\u984d':>10}\t"
              f"{'USDT \u9918\u984d':>11}")
        print("-" * 110)
        for i, m in enumerate(macro_buys):
            if m.divergence_score == -2.0:
                layer = "D+W"
            elif m.divergence_score > 0:
                layer = "W-DIV"
            else:
                layer = "W-RSI"
            d_rsi = f"{m.weekly_rsi:.1f}"
            w_rsi = f"{m.sma200_ratio:.1f}" if m.divergence_score < 0 else "--"
            print(
                f"{i+1:>3}\t{str(m.timestamp)[:10]:<12}\t{layer:<8}\t"
                f"{d_rsi:>6}\t{w_rsi:>6}\t"
                f"+{m.btc_amount:.4f}B\t${m.btc_price:>,.0f}\t"
                f"${m.usdt_amount:>,.0f}\t"
                f"{m.btc_balance_after:.4f}B\t${m.usdt_balance_after:>,.0f}"
            )
        total_bought = sum(m.btc_amount for m in macro_buys)
        total_spent = sum(m.usdt_amount for m in macro_buys)
        avg_buy_p = total_spent / max(total_bought, 0.0001)
        print(f"\t\u5408\u8a08: {total_bought:.4f} BTC \u8cb7\u5165 "
              f"\u2190 ${total_spent:>,.0f} USDT (avg ${avg_buy_p:,.0f}/BTC)")
    print()

    # ============================================================
    # Section 4: Electronic Passbook (電子存摺)
    # ============================================================
    print()
    print("=" * 130)
    print("\U0001f4d2 \u96fb\u5b50\u5b58\u647a\uff08\u6309\u6642\u9593\u5e8f\uff09")
    print("=" * 130)
    print(f"{'#':>3}\t{'\u65e5\u671f':<12}\t{'\u985e\u578b':<14}\t"
          f"{'\u65b9\u5411':<6}\t{'\u50f9\u683c':>10}\t"
          f"{'BTC \u8b8a\u52d5':>12}\t{'USDT \u8b8a\u52d5':>12}\t"
          f"{'BTC \u9918\u984d':>12}\t{'USDT \u9918\u984d':>12}\t"
          f"{'\u7e3d\u8cc7\u7522 USD':>14}")
    print("-" * 130)

    # Build chronological ledger: merge trades + macro events
    ledger: list[tuple] = []
    # (timestamp, type_str, direction, price, btc_delta, usdt_delta, note)

    for t in result.trades:
        # Entry
        if t.side == "long":
            ledger.append((t.entry_time, "\u958b\u5009", "LONG", t.entry_price,
                           0.0, 0.0, t.entry_rule))
            # Exit
            icon = "\u2705" if t.pnl > 0 else "\u274c"
            ledger.append((t.exit_time, f"\u5e73\u5009 {icon}", "LONG",
                           t.exit_price, t.pnl, 0.0, t.exit_reason))
        else:
            ledger.append((t.entry_time, "\u958b\u5009", "SHORT", t.entry_price,
                           0.0, 0.0, t.entry_rule))
            icon = "\u2705" if t.pnl > 0 else "\u274c"
            ledger.append((t.exit_time, f"\u5e73\u5009 {icon}", "SHORT",
                           t.exit_price, t.pnl, 0.0, t.exit_reason))

    for m in macro_events:
        if m.action == "sell_top":
            ledger.append((m.timestamp, "\U0001f4b0 Macro\u8ce3",
                           "BTC\u2192USDT", m.btc_price,
                           -m.btc_amount, +m.usdt_amount, ""))
        else:
            ledger.append((m.timestamp, "\U0001f4b0 Macro\u8cb7",
                           "USDT\u2192BTC", m.btc_price,
                           +m.btc_amount, -m.usdt_amount, ""))

    ledger.sort(key=lambda x: x[0])

    # Track running balances
    run_btc = INITIAL_BTC
    run_usdt = 0.0
    seq = 0

    for ts, typ, direction, price, btc_d, usdt_d, note in ledger:
        run_btc += btc_d
        run_usdt += usdt_d
        total_usd = run_btc * price + run_usdt
        seq += 1

        btc_str = f"{btc_d:>+.4f}" if btc_d != 0 else "--"
        usdt_str = f"{usdt_d:>+,.0f}" if usdt_d != 0 else "--"

        print(
            f"{seq:>3}\t{str(ts)[:10]:<12}\t{typ:<14}\t"
            f"{direction:<6}\t${price:>10,.0f}\t"
            f"{btc_str:>12}\t{usdt_str:>12}\t"
            f"{run_btc:>10.4f}B\t${run_usdt:>10,.0f}\t"
            f"${total_usd:>12,.0f}"
        )

    print("-" * 130)
    _final_total = run_btc * end_price + run_usdt
    print(f"\t\u6700\u7d42\u9918\u984d\t\t\t\t\t\t"
          f"{run_btc:>10.4f}B\t${run_usdt:>10,.0f}\t"
          f"${_final_total:>12,.0f}")
    print()

    # ============================================================
    # Section 5: Final Summary
    # ============================================================
    print("=" * 50)
    print(f"\u6700\u7d42 BTC\t{final_btc:.4f} BTC ({btc_return_pct:+.1f}%)")
    print(f"USDT \u5132\u5099\t${usdt_reserves:,.0f}")
    print(f"\u7e3d\u8cc7\u7522\t${final_usd:,.0f} ({usd_return_pct:+.1f}%)")
    print(f"\u88ab\u52d5\u6301\u6709\t${passive_usd:,.0f} ({passive_return_pct:+.1f}%)")
    print(f"Alpha\t+${final_usd - passive_usd:,.0f} "
          f"({usd_return_pct - passive_return_pct:+.1f}%)")
    print(f"\u6700\u5927\u56de\u64a4\t{result.max_drawdown_pct:.1f}%")
    print(f"\u5831\u916c/\u56de\u64a4\t{ratio:.2f}")
    print(f"\u4ea4\u6613\u6578\t{result.total_trades}")
    print(f"\u52dd\u7387\t{wr:.1f}%\uff08{wins} \u52dd {total - wins} \u8ca0\uff09")
    print(f"\u5e73\u5747\u7372\u5229\t{avg_win:+.4f} BTC (${avg_win * end_price:+,.0f})")
    print(f"\u5e73\u5747\u8667\u640d\t{avg_loss:+.4f} BTC (${avg_loss * end_price:+,.0f})")
    if avg_loss != 0:
        print(f"\u76c8\u8667\u6bd4\t{abs(avg_win / avg_loss):.2f}")
    print("=" * 50)

    # ============================================================
    # Section 6: Per-trade detailed annotations
    # ============================================================
    print()
    print("=" * 100)
    print("\u4ea4\u6613\u8a73\u7d30\u5206\u6790\uff08\u6bcf\u7b46\u4ea4\u6613\u7684\u898f\u5247\u3001\u689d\u4ef6\u3001\u76ee\u7684\uff09")
    print("=" * 100)

    for i, t in enumerate(result.trades):
        usd_pnl = t.pnl * t.exit_price
        days_held = (t.exit_time - t.entry_time).total_seconds() / 86400
        total_fee = t.entry_fee + t.exit_fee
        icon = "\u2705" if t.pnl > 0 else "\u274c"
        meta = t.metadata or {}
        rule_info = _RULE_DECODE.get(t.entry_rule, (t.entry_rule, "--", "--"))
        exit_info = _EXIT_DECODE.get(t.exit_reason, t.exit_reason)
        stop_p = meta.get("stop_price")
        target_p = meta.get("target_price")
        trail_atr = meta.get("trailing_stop_atr", 0)

        print(f"\n--- Trade #{i+1} {icon} {'='*60}")
        print(f"  \u65b9\u5411:     {t.side.upper()}")
        print(f"  \u898f\u5247:     {rule_info[0]} ({t.entry_rule})")
        print(f"  \u7d50\u69cb:     {rule_info[1]}")
        print(f"  \u76ee\u7684:     {rule_info[2]}")
        print(f"  \u5165\u5834:     {str(t.entry_time)[:16]}  ${t.entry_price:,.0f}  qty={t.quantity:.6f}")
        print(f"  \u51fa\u5834:     {str(t.exit_time)[:16]}  ${t.exit_price:,.0f}  ({exit_info})")
        print(f"  \u6301\u5009:     {days_held:.1f} \u5929")
        if stop_p:
            print(f"  \u6b62\u640d\u50f9:   ${stop_p:,.0f}  (\u8ddd\u5165\u5834 {abs(t.entry_price - stop_p) / t.entry_price * 100:.1f}%)")
        if target_p:
            print(f"  \u76ee\u6a19\u50f9:   ${target_p:,.0f}")
        if trail_atr and trail_atr > 0:
            print(f"  \u8ffd\u8e64 ATR: {trail_atr:.1f}x")
        print(f"  \u624b\u7e8c\u8cbb:   {total_fee:.6f} BTC")
        print(f"  \u640d\u76ca:     {t.pnl:+.4f} BTC (${usd_pnl:+,.0f})  return={t.return_pct:+.1f}%")

    # ============================================================
    # Section 7: Save detailed report to reports/ folder
    # ============================================================
    import json
    from datetime import datetime as _dtx

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    report_time = _dtx.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"backtest_{report_time}.txt"

    lines: list[str] = []
    lines.append(f"COIN-MARGINED INVERSE BACKTEST REPORT")
    lines.append(f"Generated: {_dtx.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Data: {len(bars_4h)} bars, {bars_4h[0].timestamp} to {bars_4h[-1].timestamp}")
    lines.append(f"Capital: {INITIAL_BTC} BTC (=${INITIAL_BTC * start_price:,.0f})")
    lines.append(f"Leverage: {LEVERAGE}x | Contract: inverse | Margin: isolated")
    lines.append("")
    lines.append("=" * 80)
    lines.append("RESULTS")
    lines.append("=" * 80)
    lines.append(f"Final BTC:       {final_btc:.4f} BTC ({btc_return_pct:+.1f}%)")
    lines.append(f"USDT Reserves:   ${usdt_reserves:,.0f}")
    lines.append(f"Total Value:     ${final_usd:,.0f} ({usd_return_pct:+.1f}%)")
    lines.append(f"Passive Hold:    ${passive_usd:,.0f} ({passive_return_pct:+.1f}%)")
    lines.append(f"Alpha:           +${final_usd - passive_usd:,.0f}")
    lines.append(f"Max Drawdown:    {result.max_drawdown_pct:.1f}%")
    lines.append(f"Return/DD:       {ratio:.2f}")
    lines.append(f"Trades:          {result.total_trades}")
    lines.append(f"Win Rate:        {wr:.1f}% ({wins}W/{total - wins}L)")
    lines.append(f"Avg Win:         {avg_win:+.4f} BTC (${avg_win * end_price:+,.0f})")
    lines.append(f"Avg Loss:        {avg_loss:+.4f} BTC (${avg_loss * end_price:+,.0f})")
    if avg_loss != 0:
        lines.append(f"Win/Loss:        {abs(avg_win / avg_loss):.2f}")
    lines.append("")

    lines.append("=" * 80)
    lines.append("TRADE DETAIL")
    lines.append("=" * 80)
    for i, t in enumerate(result.trades):
        usd_pnl = t.pnl * t.exit_price
        days_held = (t.exit_time - t.entry_time).total_seconds() / 86400
        total_fee = t.entry_fee + t.exit_fee
        meta = t.metadata or {}
        rule_info = _RULE_DECODE.get(t.entry_rule, (t.entry_rule, "--", "--"))
        exit_info = _EXIT_DECODE.get(t.exit_reason, t.exit_reason)
        stop_p = meta.get("stop_price")
        target_p = meta.get("target_price")
        trail_atr = meta.get("trailing_stop_atr", 0)

        lines.append(f"")
        lines.append(f"--- Trade #{i+1} {'WIN' if t.pnl > 0 else 'LOSS'} ---")
        lines.append(f"  Side:       {t.side.upper()}")
        lines.append(f"  Rule:       {rule_info[0]} ({t.entry_rule})")
        lines.append(f"  Structure:  {rule_info[1]}")
        lines.append(f"  Purpose:    {rule_info[2]}")
        lines.append(f"  Entry:      {t.entry_time}  ${t.entry_price:,.0f}  qty={t.quantity:.6f}")
        lines.append(f"  Exit:       {t.exit_time}  ${t.exit_price:,.0f}  ({exit_info})")
        lines.append(f"  Duration:   {days_held:.1f} days")
        if stop_p:
            lines.append(f"  Stop:       ${stop_p:,.0f} ({abs(t.entry_price - stop_p) / t.entry_price * 100:.1f}% from entry)")
        if target_p:
            lines.append(f"  Target:     ${target_p:,.0f}")
        if trail_atr and trail_atr > 0:
            lines.append(f"  Trail ATR:  {trail_atr:.1f}x")
        lines.append(f"  Fees:       {total_fee:.6f} BTC")
        lines.append(f"  PnL:        {t.pnl:+.4f} BTC (${usd_pnl:+,.0f})  return={t.return_pct:+.1f}%")

    # Macro events
    if macro_sells or macro_buys:
        lines.append("")
        lines.append("=" * 80)
        lines.append("MACRO CYCLE EVENTS")
        lines.append("=" * 80)
        for m in macro_events:
            if m.action == "sell_top":
                if m.divergence_score == -1.0:
                    _lbl = f"D+W sell  D-RSI={m.weekly_rsi:.0f} W-RSI={m.sma200_ratio:.0f} M-RSI={m.funding_rate:.0f}" if m.funding_rate is not None else f"D+W sell  D-RSI={m.weekly_rsi:.0f} W-RSI={m.sma200_ratio:.0f}"
                elif m.divergence_score > 0:
                    _lbl = f"W-DIV sell  W-RSI={m.weekly_rsi:.0f} div={m.divergence_score:.1f}"
                else:
                    _lbl = f"sell  RSI={m.weekly_rsi:.0f}"
                lines.append(f"  SELL {str(m.timestamp)[:10]}  -{m.btc_amount:.4f} BTC @ ${m.btc_price:,.0f} -> +${m.usdt_amount:,.0f} USDT  ({_lbl})")
            else:
                if m.divergence_score == -2.0:
                    _lbl = f"D+W buy  D-RSI={m.weekly_rsi:.0f} W-RSI={m.sma200_ratio:.0f}"
                elif m.divergence_score > 0:
                    _lbl = f"W-DIV buy  W-RSI={m.weekly_rsi:.0f} div={m.divergence_score:.1f}"
                else:
                    _lbl = f"W-RSI buy  W-RSI={m.weekly_rsi:.0f}"
                lines.append(f"  BUY  {str(m.timestamp)[:10]}  +{m.btc_amount:.4f} BTC @ ${m.btc_price:,.0f} <- ${m.usdt_amount:,.0f} USDT  ({_lbl})")

    # Config
    lines.append("")
    lines.append("=" * 80)
    lines.append("STRATEGY CONFIG")
    lines.append("=" * 80)
    for field, value in config.__dict__.items():
        if not field.startswith("_"):
            lines.append(f"  {field}: {value}")
    lines.append("")
    lines.append("MACRO CYCLE CONFIG")
    for field, value in macro.__dict__.items():
        if not field.startswith("_"):
            lines.append(f"  {field}: {value}")

    report_text = "\n".join(lines)
    report_path.write_text(report_text, encoding="utf-8")
    print(f"\n\u2705 \u5831\u544a\u5df2\u5132\u5b58: {report_path}")

    # Also save JSON for programmatic access
    json_path = reports_dir / f"backtest_{report_time}.json"
    json_data = {
        "timestamp": report_time,
        "config": {k: v for k, v in config.__dict__.items() if not k.startswith("_")},
        "macro_config": {k: v for k, v in macro.__dict__.items() if not k.startswith("_")},
        "results": {
            "final_btc": final_btc,
            "btc_return_pct": btc_return_pct,
            "usdt_reserves": usdt_reserves,
            "total_usd": final_usd,
            "usd_return_pct": usd_return_pct,
            "max_drawdown_pct": result.max_drawdown_pct,
            "return_dd_ratio": ratio,
            "total_trades": result.total_trades,
            "win_rate": wr,
            "avg_win_btc": avg_win,
            "avg_loss_btc": avg_loss,
        },
        "trades": [
            {
                "id": i + 1,
                "side": t.side,
                "entry_rule": t.entry_rule,
                "exit_reason": t.exit_reason,
                "entry_time": str(t.entry_time),
                "exit_time": str(t.exit_time),
                "days_held": round((t.exit_time - t.entry_time).total_seconds() / 86400, 1),
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "entry_fee": t.entry_fee,
                "exit_fee": t.exit_fee,
                "pnl_btc": t.pnl,
                "pnl_usd": t.pnl * t.exit_price,
                "return_pct": t.return_pct,
                "confidence": (t.metadata or {}).get("confidence"),
                "stop_price": (t.metadata or {}).get("stop_price"),
                "target_price": (t.metadata or {}).get("target_price"),
                "trailing_stop_atr": (t.metadata or {}).get("trailing_stop_atr"),
            }
            for i, t in enumerate(result.trades)
        ],
        "macro_events": [
            {
                "action": m.action,
                "timestamp": str(m.timestamp),
                "layer": (
                    "D+W" if m.divergence_score == -1.0 else
                    "D+W_buy" if m.divergence_score == -2.0 else
                    "W-DIV" if m.divergence_score > 0 else
                    "W-RSI"
                ),
                "btc_price": m.btc_price,
                "btc_amount": m.btc_amount,
                "usdt_amount": m.usdt_amount,
                "divergence_score": m.divergence_score,
                "weekly_rsi": m.weekly_rsi,
                "sma200_ratio": m.sma200_ratio,
                "funding_rate": m.funding_rate,
                "top_ls_ratio": m.top_ls_ratio,
                "btc_balance_after": m.btc_balance_after,
                "usdt_balance_after": m.usdt_balance_after,
            }
            for m in macro_events
        ],
    }
    json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\u2705 JSON \u5df2\u5132\u5b58: {json_path}")


if __name__ == "__main__":
    main()
