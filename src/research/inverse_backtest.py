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
        impulse_trailing_stop_atr=6.0,
        impulse_harvest_pct=0.0,   # disabled: all profit stays as BTC
        impulse_harvest_min_pnl=0.05,  # (harvest disabled -- sell via macro cycle only)
        rsi_filter=True,
        rsi_period=3,
        adx_filter=True,
        adx_threshold=25.0,
        adx_mode="smart",
        oi_divergence_lookback=48,
        oi_divergence_threshold=-0.10,
        top_ls_contrarian=True,
        top_ls_threshold=1.5,
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
        # D+W sell: D>=75 + W>=70, sell 20%, monthly guard M>=65
        daily_rsi_sell_trigger=75.0,  # sell when daily RSI >= 75
        weekly_rsi_sell_confirm=70.0, # AND weekly RSI >= 70
        daily_rsi_sell_pct=0.20,      # 20% of current BTC holdings
        dw_sell_min_monthly_rsi=65.0, # guard: block sell if M-RSI < 65
        # Layer 1b: daily+weekly RSI oversold buying (arm-and-confirm)
        daily_rsi_buy_trigger=27.0,   # ARM when daily RSI < 27
        weekly_rsi_buy_confirm=47.0,  # AND weekly RSI < 47
        daily_rsi_buy_pct=0.20,       # 20% of USDT reserves
        dw_buy_bounce_pct=0.05,       # CONFIRM: buy when price bounces 5% from low
        # Layer 1c: weekly RSI bottom buying
        weekly_rsi_buy_trigger=25.0,  # buy when weekly RSI <= 25
        weekly_rsi_buy_pct=0.40,      # spend 40% of USDT reserves
        # Layer 2: weekly RSI divergence
        divergence_pivot_window=4,    # 4 weeks to confirm peak/trough
        divergence_min_rsi_drop=5.0,  # min 5 RSI points for divergence
        sell_pct_per_rsi_point=0.01,  # 1% per RSI point divergence
        sell_pct_min=0.10,            # floor 10%
        sell_pct_max=0.40,            # cap 40%
        buy_pct_per_rsi_point=0.02,
        buy_pct_min=0.20,
        buy_pct_max=0.60,
        # Divergence guards: monthly RSI filter
        divergence_sell_min_monthly_rsi=65.0,  # block when monthly RSI below hot zone
        divergence_buy_max_monthly_rsi=40.0,   # block false bottoms in rally
        # Cooldown
        cooldown_bars_4h=168,         # 4 weeks between actions
    )


def main() -> None:
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    from datetime import datetime as _dt

    # Use same OHLCV data (BTC/USD price is the same for linear vs inverse)
    if FORCE_5YEAR:
        _4h_path = DATA_DIR / "btcusdt_4h_5year.csv"
    else:
        _4h_path = DATA_DIR / "btcusdt_4h_6year.csv"
        if not _4h_path.exists():
            _4h_path = DATA_DIR / "btcusdt_4h_5year.csv"
    all_bars_4h = load_bars_from_csv(str(_4h_path))
    fp = StaticFuturesProvider.from_coinglass_csvs(
        oi_csv=str(DATA_DIR / "coinglass_oi_1d.csv"),
        funding_csv=str(DATA_DIR / "coinglass_funding_1d.csv"),
        top_ls_csv=str(DATA_DIR / "coinglass_top_ls_1d.csv"),
        cvd_csv=str(DATA_DIR / "coinglass_cvd_1d.csv"),
        basis_csv=str(DATA_DIR / "coinglass_basis_1d.csv"),
    )

    # Filter bars from START_DATE onwards (if set)
    if START_DATE:
        _start_dt = _dt.strptime(START_DATE, "%Y-%m-%d")
        bars_4h = [b for b in all_bars_4h if b.timestamp >= _start_dt]
        print(f"[Data filter] {len(all_bars_4h)} total bars -> {len(bars_4h)} bars from {START_DATE}")
    else:
        bars_4h = all_bars_4h
        print(f"[Data] {len(bars_4h)} bars (full dataset, {_4h_path.name})")

    mtf_data: dict[str, list] = {"4h": bars_4h}
    # 1h bars → confidence scoring (MTF)
    if FORCE_5YEAR:
        bars_1h_path = DATA_DIR / "btcusdt_1h_5year.csv"
    else:
        bars_1h_path = DATA_DIR / "btcusdt_1h_6year.csv"
        if not bars_1h_path.exists():
            bars_1h_path = DATA_DIR / "btcusdt_1h_5year.csv"
    # 15m bars → stop tightening (MTF)
    if FORCE_5YEAR:
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

    # ============================================================
    # Section 1: Trade table
    # ============================================================
    print(f"{result.total_trades} \u7b46\u4ea4\u6613\u660e\u7d30")
    print(f"{'#':>3}\t{'日期':<12}\t{'方向':<6}\t{'入場$':>8}\t{'出場$':>8}\t"
          f"{'PnL BTC':>10}\t{'PnL USD':>10}\t")
    print("-" * 100)

    for i, t in enumerate(result.trades):
        usd_pnl = t.pnl * t.exit_price
        entry_k = f"{int(round(t.entry_price)):,}"
        exit_k = f"{int(round(t.exit_price)):,}"
        # Result icon
        if t.pnl > 0:
            icon = "\u2705"  # green check
        else:
            icon = "\u274c"  # red X
        # Extra markers
        extra = ""
        if t.pnl >= 0.10:
            extra += "\U0001f525"  # fire
        if t.pnl >= 0.30:
            extra += "\U0001f525"  # double fire for huge wins
        if t.entry_rule in _FLAG_RULES:
            extra += "\U0001f3f4"  # flag

        print(
            f"{i+1:>3}\t{str(t.entry_time)[:10]:<12}\t{t.side:<6}\t"
            f"{entry_k:>8}\t{exit_k:>8}\t"
            f"{t.pnl:>+.4f}\t{usd_pnl:>+,.0f}\t"
            f"{icon}{extra}"
        )

    print()
    print(f"\U0001f525 = \u5927\u7372\u5229\uff08>+0.10 BTC\uff09\t"
          f"\U0001f3f4 = \u65e5\u7dda\u65d7\u5f62\u65b0\u589e\u4ea4\u6613")
    print()

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


if __name__ == "__main__":
    main()
