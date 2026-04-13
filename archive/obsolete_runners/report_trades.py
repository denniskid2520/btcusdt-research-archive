"""Trade report: pre-entry indicators + result for every trade.

Shows the market conditions BEFORE each entry and the outcome.
Run with: PYTHONPATH=src python report_trades.py
"""
from __future__ import annotations

import sys
sys.stdout.reconfigure(encoding='utf-8')

from bisect import bisect_right
from datetime import datetime
from pathlib import Path
from statistics import mean

from adapters.base import MarketBar
from adapters.futures_data import StaticFuturesProvider
from data.backfill import load_bars_from_csv
from data.mtf_bars import MultiTimeframeBars
from execution.paper_broker import PaperBroker
from research.backtest import run_backtest
from research.macro_cycle import (
    MacroCycleConfig, aggregate_to_daily, aggregate_to_weekly, compute_macd,
)
from risk.limits import RiskLimits
from strategies.trend_breakout import (
    TrendBreakoutConfig, TrendBreakoutStrategy, _compute_rsi,
)

DATA_DIR = Path("src/data")
SYMBOL = "BTCUSD"
INITIAL_BTC = 1.0
LEVERAGE = 3


# ── Indicator helpers ──────────────────────────────────────────


def _compute_di(bars: list[MarketBar], period: int = 14) -> tuple[float, float]:
    """Return (+DI, -DI) from bars."""
    needed = 2 * period + 1
    if len(bars) < needed:
        return 0.0, 0.0
    window = bars[-needed:]
    plus_dm, minus_dm, tr_list = [], [], []
    for i in range(1, len(window)):
        hd = window[i].high - window[i - 1].high
        ld = window[i - 1].low - window[i].low
        plus_dm.append(hd if hd > ld and hd > 0 else 0.0)
        minus_dm.append(ld if ld > hd and ld > 0 else 0.0)
        tr_list.append(max(
            window[i].high - window[i].low,
            abs(window[i].high - window[i - 1].close),
            abs(window[i].low - window[i - 1].close),
        ))
    atr_s = sum(tr_list[:period])
    pdm_s = sum(plus_dm[:period])
    mdm_s = sum(minus_dm[:period])
    for i in range(period, len(tr_list)):
        atr_s = atr_s - atr_s / period + tr_list[i]
        pdm_s = pdm_s - pdm_s / period + plus_dm[i]
        mdm_s = mdm_s - mdm_s / period + minus_dm[i]
    if atr_s == 0:
        return 0.0, 0.0
    return 100 * pdm_s / atr_s, 100 * mdm_s / atr_s


def _get_indicators_at(
    ts: datetime,
    bars_4h: list[MarketBar],
    daily_bars: list[MarketBar],
    weekly_bars: list[MarketBar],
    daily_ts: list[datetime],
    weekly_ts: list[datetime],
    fp: StaticFuturesProvider,
) -> dict:
    """Compute all indicators as-of timestamp ts."""
    # Daily MACD
    di = bisect_right(daily_ts, ts)
    d_bars = daily_bars[:di]
    d_macd, _, _ = compute_macd(d_bars) if len(d_bars) > 30 else (None, None, None)

    # Weekly MACD histogram
    wi = bisect_right(weekly_ts, ts)
    w_bars = weekly_bars[:wi]
    _, _, w_hist = compute_macd(w_bars) if len(w_bars) > 30 else (None, None, None)

    # RSI(3) on 4h bars up to ts
    bi = bisect_right([b.timestamp for b in bars_4h], ts)
    h = bars_4h[:bi]
    rsi3 = _compute_rsi(h[-60:], 3) if len(h) > 10 else None

    # ADX + DI on 4h
    from strategies.trend_breakout import _compute_adx
    adx = _compute_adx(h[-100:], 14) if len(h) > 30 else None
    pdi, mdi = _compute_di(h[-100:], 14) if len(h) > 30 else (0, 0)

    # ACCEL zone: W-hist <= 0 AND D-MACD < 0
    accel = (w_hist is not None and w_hist <= 0
             and d_macd is not None and d_macd < 0)

    # Coinglass snapshot
    snap = fp.get_snapshot(SYMBOL, ts) if fp else None
    oi_close = getattr(snap, "oi_close", None) if snap else None
    # OI change vs 48 bars ago (~2 days)
    oi_chg = None
    if snap and oi_close and oi_close > 0:
        snap_prev = fp.get_snapshot(SYMBOL, bars_4h[max(0, bi - 48)].timestamp) if bi > 48 else None
        if snap_prev and getattr(snap_prev, "oi_close", None):
            oi_chg = (oi_close - snap_prev.oi_close) / snap_prev.oi_close * 100

    ls = getattr(snap, "top_ls_ratio", None) if snap else None
    funding = getattr(snap, "funding_rate", None) if snap else None
    cvd = getattr(snap, "cvd", None) if snap else None

    return {
        "d_macd": d_macd,
        "w_hist": w_hist,
        "rsi3": rsi3,
        "adx": adx,
        "pdi": pdi,
        "mdi": mdi,
        "accel": accel,
        "oi_chg": oi_chg,
        "ls": ls,
        "funding": funding,
        "cvd": cvd,
    }


# ── Config (same as inverse_backtest.py) ───────────────────────


def _make_config() -> TrendBreakoutConfig:
    return TrendBreakoutConfig(
        impulse_lookback=12, structure_lookback=24,
        secondary_structure_lookback=48,
        pivot_window=2, min_pivot_highs=2, min_pivot_lows=2,
        impulse_threshold_pct=0.02,
        entry_buffer_pct=0.30, stop_buffer_pct=0.08,
        min_r_squared=0.0, min_stop_atr_multiplier=1.5,
        time_stop_bars=168,
        enable_ascending_channel_resistance_rejection=True,
        enable_descending_channel_breakout_long=True,
        enable_ascending_channel_breakdown_short=True,
        use_trailing_exit=True,
        trailing_stop_atr=3.5,
        impulse_trailing_stop_atr=7.0,
        impulse_harvest_pct=0.0, impulse_harvest_min_pnl=0.05,
        rsi_filter=True, rsi_period=3, rsi_oversold=20.0,
        adx_filter=True, adx_threshold=25.0, adx_mode="smart",
        oi_divergence_lookback=48, oi_divergence_threshold=-0.10,
        top_ls_contrarian=True, top_ls_threshold=1.5,
        liq_cascade_filter=True, liq_cascade_threshold=5e7,
        taker_imbalance_filter=True, taker_imbalance_threshold=1.3,
        cvd_divergence_filter=True, cvd_divergence_lookback=48,
        weekly_macd_short_gate=False,
        accel_trail_multiplier=3.0,
        bear_flag_max_weekly_rsi=0.0,
        loss_cooldown_count=0, loss_cooldown_bars=24,
        bear_reversal_enabled=False,
        mtf_entry_confirmation=True, mtf_1h_sizing_mode="scale",
        mtf_1h_lookback=4, mtf_1h_min_wick_ratio=0.3,
        mtf_1h_no_confirm_confidence=0.8,
        mtf_stop_refinement=True, mtf_15m_lookback=16,
        mtf_stop_max_tighten_pct=0.30,
        scale_in_enabled=False,
    )


def _make_macro() -> MacroCycleConfig:
    return MacroCycleConfig(
        weekly_rsi_period=14,
        monthly_rsi_sell_start=70.0, monthly_rsi_sell_step=7.0,
        monthly_rsi_sell_pct=0.10, min_btc_reserve=1.0,
        daily_rsi_sell_trigger=75.0, weekly_rsi_sell_confirm=70.0,
        daily_rsi_sell_pct=0.35, dw_sell_min_monthly_rsi=65.0,
        daily_rsi_buy_trigger=0.0, weekly_rsi_buy_confirm=0.0,
        daily_rsi_buy_pct=0.0, dw_buy_bounce_pct=0.0,
        weekly_rsi_buy_trigger=0.0, weekly_rsi_buy_pct=0.0,
        divergence_pivot_window=4, divergence_min_rsi_drop=5.0,
        sell_pct_per_rsi_point=0.01, sell_pct_min=0.10, sell_pct_max=0.40,
        buy_pct_per_rsi_point=0.0, buy_pct_min=0.0, buy_pct_max=0.0,
        divergence_sell_min_monthly_rsi=65.0,
        divergence_buy_max_monthly_rsi=40.0,
        cooldown_bars_4h=168,
    )


# ── Main ───────────────────────────────────────────────────────


def main() -> None:
    # Load data
    _4h_path = DATA_DIR / "btcusdt_4h_5year.csv"
    bars_4h = load_bars_from_csv(str(_4h_path))
    print(f"[Data] {len(bars_4h)} 4h bars")

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

    # MTF bars
    mtf_data: dict[str, list] = {"4h": bars_4h}
    for tf, fname in [("1h", "btcusdt_1h_5year.csv"), ("15m", "btcusdt_15m_5year.csv")]:
        p = DATA_DIR / fname
        if p.exists():
            all_b = load_bars_from_csv(str(p))
            mtf_data[tf] = [b for b in all_b if b.timestamp >= bars_4h[0].timestamp]
    mtf = MultiTimeframeBars(mtf_data)

    # Native daily + weekly for MACD
    daily_bars = load_bars_from_csv(str(DATA_DIR / "btcusdt_1d_6year.csv"))
    weekly_bars = load_bars_from_csv(str(DATA_DIR / "btcusdt_1w_6year.csv"))
    daily_ts = [b.timestamp for b in daily_bars]
    weekly_ts = [b.timestamp for b in weekly_bars]
    print(f"[Data] {len(daily_bars)} daily, {len(weekly_bars)} weekly bars")

    # Run backtest
    config = _make_config()
    broker = PaperBroker(
        initial_cash=INITIAL_BTC, fee_rate=0.001, slippage_rate=0.0005,
        leverage=LEVERAGE, margin_mode="isolated", contract_type="inverse",
    )
    result = run_backtest(
        bars=bars_4h, symbol=SYMBOL,
        strategy=TrendBreakoutStrategy(config),
        broker=broker, limits=RiskLimits(
            max_position_pct=0.90, risk_per_trade_pct=0.05, leverage=LEVERAGE,
        ),
        futures_provider=fp, mtf_bars=mtf, macro_cycle=_make_macro(),
        channel_quality_min_score=3,
    )

    trades = result.trades
    print(f"[Backtest] {len(trades)} trades, +{(result.final_equity/INITIAL_BTC-1)*100:.1f}% BTC")
    print()

    # ── Impulse vs Channel classification ──
    IMPULSE_RULES = {
        "daily_bear_flag", "daily_bull_flag",
        "daily_channel_breakdown", "daily_channel_breakout",
        "descending_channel_breakout_long",
        "ascending_channel_breakdown_short",
    }

    # ── Print report ──
    print("=" * 200)
    print("  TRADE REPORT: PRE-ENTRY CONDITIONS → RESULT")
    print("=" * 200)

    hdr = (
        f"{'#':>3}  {'Date':<11} {'Side':<6} {'Rule':<42} {'Entry$':>8}"
        f"  │ {'D-MACD':>7} {'W-Hist':>7} {'RSI3':>5} {'ADX':>4} {'+DI':>4} {'-DI':>4} {'ACCEL':>5}"
        f"  {'OI%':>6} {'LS':>5} {'Fund':>7}"
        f"  │ {'Exit$':>8} {'PnL%':>7} {'PnL BTC':>9} {'Reason':<25} {'Days':>4} {'Trail':>5}"
    )
    print(hdr)
    print("-" * 200)

    # Accumulators for summary
    win_indicators: list[dict] = []
    loss_indicators: list[dict] = []

    running_btc = INITIAL_BTC

    for i, t in enumerate(trades):
        # Get pre-entry indicators
        ind = _get_indicators_at(
            t.entry_time, bars_4h, daily_bars, weekly_bars,
            daily_ts, weekly_ts, fp,
        )

        # Classification
        is_impulse = t.entry_rule in IMPULSE_RULES
        trail = "7.0x" if is_impulse else "3.5x"

        # Duration
        days = (t.exit_time - t.entry_time).total_seconds() / 86400

        # PnL percentage (leveraged)
        pnl_pct = t.pnl / running_btc * 100 if running_btc > 0 else 0
        running_btc += t.pnl

        # Format indicators
        dm = f"{ind['d_macd']:>+7,.0f}" if ind["d_macd"] is not None else "    --"
        wh = f"{ind['w_hist']:>+7,.0f}" if ind["w_hist"] is not None else "    --"
        r3 = f"{ind['rsi3']:>5.1f}" if ind["rsi3"] is not None else "   --"
        ax = f"{ind['adx']:>4.0f}" if ind["adx"] is not None else "  --"
        pd = f"{ind['pdi']:>4.0f}" if ind["pdi"] else "  --"
        md = f"{ind['mdi']:>4.0f}" if ind["mdi"] else "  --"
        ac = "  YES" if ind["accel"] else "   no"
        oi = f"{ind['oi_chg']:>+5.1f}%" if ind["oi_chg"] is not None else "    --"
        ls = f"{ind['ls']:>5.2f}" if ind["ls"] is not None else "   --"
        fd = f"{ind['funding']*100:>+6.3f}%" if ind["funding"] is not None else "     --"

        icon = "✅" if t.pnl > 0 else "❌"

        print(
            f"{i+1:>3}  {str(t.entry_time)[:10]:<11} {t.side:<6} {t.entry_rule:<42} "
            f"${t.entry_price:>7,.0f}"
            f"  │ {dm} {wh} {r3} {ax} {pd} {md} {ac}"
            f"  {oi} {ls} {fd}"
            f"  │ ${t.exit_price:>7,.0f} {pnl_pct:>+6.1f}% {t.pnl:>+8.4f}B"
            f"  {t.exit_reason:<25} {days:>4.0f}d {trail}"
            f"  {icon}"
        )

        if t.pnl > 0:
            win_indicators.append(ind)
        else:
            loss_indicators.append(ind)

    # ── Summary ──
    print("=" * 200)
    print()

    def _avg(vals: list, key: str) -> str:
        nums = [v[key] for v in vals if v[key] is not None]
        if not nums:
            return "--"
        return f"{mean(nums):+.1f}" if key in ("d_macd", "w_hist", "oi_chg") else f"{mean(nums):.1f}"

    print("  INDICATOR AVERAGES: WIN vs LOSS")
    print("  " + "=" * 90)
    print(f"  {'':20s} {'D-MACD':>10} {'W-Hist':>10} {'RSI3':>8} {'ADX':>8} "
          f"{'OI%':>8} {'LS':>8} {'ACCEL%':>8}")
    print("  " + "-" * 90)

    win_accel = sum(1 for v in win_indicators if v["accel"]) / max(len(win_indicators), 1) * 100
    loss_accel = sum(1 for v in loss_indicators if v["accel"]) / max(len(loss_indicators), 1) * 100

    print(f"  {'WIN  (' + str(len(win_indicators)) + ')':<20s} "
          f"{_avg(win_indicators, 'd_macd'):>10} "
          f"{_avg(win_indicators, 'w_hist'):>10} "
          f"{_avg(win_indicators, 'rsi3'):>8} "
          f"{_avg(win_indicators, 'adx'):>8} "
          f"{_avg(win_indicators, 'oi_chg'):>8} "
          f"{_avg(win_indicators, 'ls'):>8} "
          f"{win_accel:>7.0f}%")
    print(f"  {'LOSS (' + str(len(loss_indicators)) + ')':<20s} "
          f"{_avg(loss_indicators, 'd_macd'):>10} "
          f"{_avg(loss_indicators, 'w_hist'):>10} "
          f"{_avg(loss_indicators, 'rsi3'):>8} "
          f"{_avg(loss_indicators, 'adx'):>8} "
          f"{_avg(loss_indicators, 'oi_chg'):>8} "
          f"{_avg(loss_indicators, 'ls'):>8} "
          f"{loss_accel:>7.0f}%")
    print()

    # ACCEL zone breakdown
    accel_trades = [(i, t) for i, t in enumerate(trades)
                    if _get_indicators_at(t.entry_time, bars_4h, daily_bars, weekly_bars,
                                          daily_ts, weekly_ts, fp)["accel"]]
    non_accel = [(i, t) for i, t in enumerate(trades)
                 if not _get_indicators_at(t.entry_time, bars_4h, daily_bars, weekly_bars,
                                           daily_ts, weekly_ts, fp)["accel"]]

    def _zone_stats(label: str, subset: list[tuple[int, object]]) -> None:
        if not subset:
            return
        wins = sum(1 for _, t in subset if t.pnl > 0)
        total_pnl = sum(t.pnl for _, t in subset)
        n = len(subset)
        print(f"  {label}: {n} trades | {wins}W/{n-wins}L ({wins/n*100:.0f}%) | "
              f"PnL: {total_pnl:+.4f} BTC")

    print("  ACCEL ZONE BREAKDOWN")
    print("  " + "=" * 60)
    _zone_stats("ACCEL zone (W-死叉 + D-MACD<0)", accel_trades)
    _zone_stats("Non-ACCEL zone              ", non_accel)
    print()

    # Final result
    print(f"  FINAL: {result.final_equity:.4f} BTC (+{(result.final_equity/INITIAL_BTC-1)*100:.1f}%)"
          f" | USDT: ${result.usdt_reserves:,.0f}"
          f" | Total: ${result.final_equity * bars_4h[-1].close + result.usdt_reserves:,.0f}"
          f" | DD: {result.max_drawdown_pct:.1f}%"
          f" | R/DD: {(result.final_equity/INITIAL_BTC-1)*100/result.max_drawdown_pct:.2f}")


if __name__ == "__main__":
    main()
