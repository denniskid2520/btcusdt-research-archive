"""Diagnose Strategy B entries: check all indicators at each entry point.

Find what differentiates winning crash entries from losing bounce entries.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'src')

from datetime import datetime
from pathlib import Path
from bisect import bisect_right

from adapters.base import MarketBar
from adapters.futures_data import StaticFuturesProvider
from data.backfill import load_bars_from_csv
from research.macro_cycle import compute_macd, aggregate_to_daily, aggregate_to_weekly, compute_weekly_rsi
from strategies.trend_breakout import _compute_rsi as compute_rsi

DATA_DIR = Path("src/data")

# Load all data
bars_4h = load_bars_from_csv(str(DATA_DIR / "btcusdt_4h_5year.csv"))
bars_1d = load_bars_from_csv(str(DATA_DIR / "btcusdt_1d_6year.csv"))
bars_1w = load_bars_from_csv(str(DATA_DIR / "btcusdt_1w_6year.csv"))

ts_4h = [b.timestamp for b in bars_4h]
ts_1d = [b.timestamp for b in bars_1d]
ts_1w = [b.timestamp for b in bars_1w]

fp = StaticFuturesProvider.from_coinglass_csvs(
    oi_csv=str(DATA_DIR / "coinglass_oi_1d.csv"),
    funding_csv=str(DATA_DIR / "coinglass_funding_1d.csv"),
    top_ls_csv=str(DATA_DIR / "coinglass_top_ls_1d.csv"),
    cvd_csv=str(DATA_DIR / "coinglass_cvd_1d.csv"),
    basis_csv=str(DATA_DIR / "coinglass_basis_1d.csv"),
    liquidation_csv=str(DATA_DIR / "coinglass_liquidation_4h.csv") if (DATA_DIR / "coinglass_liquidation_4h.csv").exists() else None,
    taker_csv=str(DATA_DIR / "coinglass_taker_volume_4h.csv") if (DATA_DIR / "coinglass_taker_volume_4h.csv").exists() else None,
)

# Strategy B entry points (from weekly_macd_short_gate backtest)
entries = [
    # (date, price, rule, pnl, result)
    (datetime(2021, 7, 20), 29586, "daily_channel_breakdown", -0.0446, "LOSS"),
    (datetime(2021, 8, 6), 42815, "asc_chan_resist_reject", -0.0549, "LOSS"),
    (datetime(2021, 9, 1), 47020, "daily_bear_flag", -0.0345, "LOSS"),
    (datetime(2021, 9, 8), 46427, "daily_bear_flag", -0.0113, "LOSS"),
    (datetime(2021, 9, 20), 45520, "daily_bear_flag", -0.0097, "LOSS"),
    (datetime(2021, 10, 14), 58037, "asc_chan_resist_reject", -0.0374, "LOSS"),
    (datetime(2021, 11, 13), 63742, "daily_bear_flag", +0.0977, "WIN"),  # ATH crash
    (datetime(2022, 1, 21), 38446, "daily_channel_breakdown", -0.0435, "LOSS"),
    (datetime(2022, 4, 28), 39365, "desc_chan_rejection", -0.0251, "LOSS"),
    (datetime(2022, 5, 6), 36444, "daily_channel_breakdown", +0.1245, "WIN"),  # Luna
    (datetime(2022, 6, 14), 22117, "daily_channel_breakdown", +0.0184, "WIN"),  # 3AC
    (datetime(2023, 8, 18), 26385, "daily_channel_breakdown", -0.0044, "LOSS"),
    (datetime(2024, 5, 2), 57414, "daily_channel_breakdown", -0.0371, "LOSS"),
    (datetime(2024, 6, 11), 68430, "daily_bear_flag", +0.1352, "WIN"),  # correction
    (datetime(2024, 8, 20), 60589, "asc_chan_resist_reject", -0.0427, "LOSS"),
    (datetime(2024, 9, 17), 61105, "asc_chan_resist_reject", -0.0603, "LOSS"),
    (datetime(2024, 10, 11), 60584, "daily_bear_flag", -0.0474, "LOSS"),
    (datetime(2025, 2, 11), 98220, "asc_chan_resist_reject", +0.0073, "WIN"),
    (datetime(2025, 3, 4), 83942, "daily_channel_breakdown", +0.0025, "WIN"),
    (datetime(2025, 8, 25), 112860, "daily_bear_flag", -0.0160, "LOSS"),
    (datetime(2025, 10, 12), 110621, "daily_bear_flag", +0.0300, "WIN"),  # bear
    (datetime(2025, 11, 14), 99090, "daily_channel_breakdown", +0.0514, "WIN"),  # bear
    (datetime(2026, 1, 21), 89388, "daily_bear_flag", +0.2527, "WIN"),  # big bear
    (datetime(2026, 3, 28), 66207, "daily_bear_flag", -0.0040, "LOSS"),
]


def get_4h_idx(ts):
    idx = bisect_right(ts_4h, ts) - 1
    return max(0, idx)


def compute_atr(bars_slice, period=14):
    if len(bars_slice) < period + 1:
        return 0
    trs = []
    for i in range(1, len(bars_slice)):
        tr = max(
            bars_slice[i].high - bars_slice[i].low,
            abs(bars_slice[i].high - bars_slice[i - 1].close),
            abs(bars_slice[i].low - bars_slice[i - 1].close),
        )
        trs.append(tr)
    return sum(trs[-period:]) / period if len(trs) >= period else 0


def compute_adx(bars_slice, period=14):
    """Compute ADX, +DI, -DI."""
    if len(bars_slice) < period * 2:
        return None, None, None
    plus_dm, minus_dm, tr_list = [], [], []
    for i in range(1, len(bars_slice)):
        h = bars_slice[i].high - bars_slice[i - 1].high
        l = bars_slice[i - 1].low - bars_slice[i].low
        plus_dm.append(h if h > l and h > 0 else 0)
        minus_dm.append(l if l > h and l > 0 else 0)
        tr = max(
            bars_slice[i].high - bars_slice[i].low,
            abs(bars_slice[i].high - bars_slice[i - 1].close),
            abs(bars_slice[i].low - bars_slice[i - 1].close),
        )
        tr_list.append(tr)

    def smooth(values, p):
        result = [sum(values[:p])]
        for v in values[p:]:
            result.append(result[-1] - result[-1] / p + v)
        return result

    str_vals = smooth(tr_list, period)
    spdm = smooth(plus_dm, period)
    smdm = smooth(minus_dm, period)

    plus_di = [100 * p / t if t > 0 else 0 for p, t in zip(spdm, str_vals)]
    minus_di = [100 * m / t if t > 0 else 0 for m, t in zip(smdm, str_vals)]
    dx = [100 * abs(p - m) / (p + m) if (p + m) > 0 else 0 for p, m in zip(plus_di, minus_di)]

    if len(dx) < period:
        return None, None, None
    adx_vals = smooth(dx, period)
    return adx_vals[-1], plus_di[-1], minus_di[-1]


print("=" * 160)
print("STRATEGY B 入場點診斷 — 所有指標")
print("=" * 160)
print()

header = (
    f"{'#':>2} {'Result':<5} {'Date':<12} {'$':>8} {'Rule':<25}"
    f"{'D-MACD':>8} {'D-Slope':>8} {'W-Hist':>8} {'W-RSI':>6}"
    f"{'RSI3':>6} {'ADX':>5} {'+DI':>5} {'-DI':>5}"
    f"{'OI-Chg%':>8} {'Fund%':>7} {'LS-Top':>7} {'CVD-Chg':>8}"
    f"{'PnL':>8}"
)
print(header)
print("-" * 160)

win_indicators = []
loss_indicators = []

for i, (ts, price, rule, pnl, result) in enumerate(entries, 1):
    idx_4h = get_4h_idx(ts)

    # Daily MACD
    di = bisect_right(ts_1d, ts)
    d_bars = bars_1d[:di]
    d_macd, d_sig, d_hist = (None, None, None)
    d_slope = None
    if len(d_bars) >= 35:
        d_macd, d_sig, d_hist = compute_macd(d_bars)
        # MACD slope: compare to 3 days ago
        if len(d_bars) >= 38:
            d_macd_prev, _, _ = compute_macd(d_bars[:-3])
            if d_macd is not None and d_macd_prev is not None:
                d_slope = d_macd - d_macd_prev

    # Weekly MACD hist
    wi = bisect_right(ts_1w, ts)
    w_bars = bars_1w[:wi]
    w_macd, w_sig, w_hist = (None, None, None)
    if len(w_bars) >= 35:
        w_macd, w_sig, w_hist = compute_macd(w_bars)

    # Weekly RSI
    w_rsi = compute_weekly_rsi(w_bars) if len(w_bars) >= 20 else None

    # RSI(3) - _compute_rsi expects MarketBar objects
    rsi3_bars = bars_4h[max(0, idx_4h - 60) : idx_4h + 1]
    rsi3 = compute_rsi(rsi3_bars, 3) if len(rsi3_bars) > 3 else None

    # ADX on daily bars
    adx, plus_di, minus_di = compute_adx(d_bars[-60:], 14) if len(d_bars) >= 30 else (None, None, None)

    # Coinglass indicators
    snap = fp.get_snapshot("BTCUSD", ts) if fp else None
    oi_chg = None
    funding = None
    ls_top = None
    cvd_chg = None
    if snap:
        # OI change: compare current OI to 48 bars ago
        snap_prev = fp.get_snapshot("BTCUSD", bars_4h[max(0, idx_4h - 48)].timestamp) if idx_4h > 48 else None
        if snap.open_interest and snap_prev and snap_prev.open_interest and snap_prev.open_interest > 0:
            oi_chg = (snap.open_interest - snap_prev.open_interest) / snap_prev.open_interest * 100
        funding = snap.funding_rate
        ls_top = snap.top_ls_ratio
        # CVD change
        if snap.cvd and snap_prev and snap_prev.cvd:
            cvd_chg = snap.cvd - snap_prev.cvd

    row = {
        "d_macd": d_macd,
        "d_slope": d_slope,
        "w_hist": w_hist,
        "w_rsi": w_rsi,
        "rsi3": rsi3,
        "adx": adx,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "oi_chg": oi_chg,
        "funding": funding,
        "ls_top": ls_top,
        "cvd_chg": cvd_chg,
    }

    if result == "WIN":
        win_indicators.append(row)
    else:
        loss_indicators.append(row)

    print(
        f"{i:>2} {'✅' if result == 'WIN' else '❌':<4} {ts.strftime('%Y-%m-%d'):<12} "
        f"${price:>7,} {rule:<25}"
        f"{d_macd:>+8,.0f}" if d_macd is not None else f"{'N/A':>8}",
        end="",
    )
    # Print remaining cols
    print(
        f" {d_slope:>+8,.0f}" if d_slope is not None else f" {'N/A':>8}",
        end="",
    )
    print(
        f" {w_hist:>+8,.0f}" if w_hist is not None else f" {'N/A':>8}",
        end="",
    )
    print(f" {w_rsi:>5.1f}" if w_rsi is not None else f" {'N/A':>6}", end="")
    print(f" {rsi3:>5.1f}" if rsi3 is not None else f" {'N/A':>6}", end="")
    print(f" {adx:>5.1f}" if adx is not None else f" {'N/A':>5}", end="")
    print(f" {plus_di:>5.1f}" if plus_di is not None else f" {'N/A':>5}", end="")
    print(f" {minus_di:>5.1f}" if minus_di is not None else f" {'N/A':>5}", end="")
    print(f" {oi_chg:>+7.1f}%" if oi_chg is not None else f" {'N/A':>8}", end="")
    print(f" {funding:>+6.3f}%" if funding is not None else f" {'N/A':>7}", end="")
    print(f" {ls_top:>6.2f}" if ls_top is not None else f" {'N/A':>7}", end="")
    print(f" {cvd_chg:>+8,.0f}" if cvd_chg is not None else f" {'N/A':>8}", end="")
    print(f" {pnl:>+7.4f}")

# Summary: average indicators for wins vs losses
print()
print("=" * 100)
print("指標平均值比較：WIN vs LOSS")
print("=" * 100)

def avg_field(rows, field):
    vals = [r[field] for r in rows if r[field] is not None]
    return sum(vals) / len(vals) if vals else None

fields = [
    ("D-MACD", "d_macd"),
    ("D-MACD Slope", "d_slope"),
    ("W-Hist", "w_hist"),
    ("W-RSI", "w_rsi"),
    ("RSI(3)", "rsi3"),
    ("ADX", "adx"),
    ("+DI", "plus_di"),
    ("-DI", "minus_di"),
    ("OI Change %", "oi_chg"),
    ("Funding %", "funding"),
    ("LS Top Ratio", "ls_top"),
    ("CVD Change", "cvd_chg"),
]

print(f"{'Indicator':<20} {'WIN avg':>12} {'LOSS avg':>12} {'差異':>12} {'方向':<20}")
print("-" * 80)
for name, field in fields:
    w = avg_field(win_indicators, field)
    l = avg_field(loss_indicators, field)
    if w is not None and l is not None:
        diff = w - l
        if field == "d_macd":
            direction = "WIN更負=更熊" if diff < 0 else "LOSS更負=反彈入場"
        elif field == "d_slope":
            direction = "WIN下降=崩中" if diff < 0 else "LOSS下降=反彈前"
        elif field == "w_hist":
            direction = "WIN更負=深熊" if diff < 0 else "LOSS更負"
        elif field == "w_rsi":
            direction = "WIN更低=熊市" if diff < 0 else "LOSS更低"
        elif field == "rsi3":
            direction = "WIN更低=超賣" if diff < 0 else "LOSS更低=超賣"
        elif field == "adx":
            direction = "WIN趨勢更強" if diff > 0 else "LOSS趨勢更強"
        elif field in ("plus_di", "minus_di"):
            direction = ""
        elif field == "oi_chg":
            direction = "WIN OI下降=清倉" if diff < 0 else "LOSS OI下降"
        elif field == "funding":
            direction = "WIN資金費率更低" if diff < 0 else ""
        elif field == "ls_top":
            direction = "WIN多空比更低" if diff < 0 else ""
        elif field == "cvd_chg":
            direction = "WIN CVD更負=賣壓" if diff < 0 else ""
        else:
            direction = ""
        print(
            f"{name:<20} {w:>12,.1f} {l:>12,.1f} {diff:>+12,.1f} {direction}"
        )
    else:
        print(f"{name:<20} {'N/A':>12} {'N/A':>12}")

# Additional: check D-MACD < 0 filter
print()
print("=" * 80)
print("D-MACD < 0 過濾效果")
print("=" * 80)
for label, rows in [("WIN", win_indicators), ("LOSS", loss_indicators)]:
    total = len(rows)
    d_neg = sum(1 for r in rows if r["d_macd"] is not None and r["d_macd"] < 0)
    print(f"  {label}: {d_neg}/{total} 筆 D-MACD<0 ({d_neg / total * 100:.0f}%)")

# D-MACD slope < 0 filter
print()
print("D-MACD Slope < 0 過濾效果")
for label, rows in [("WIN", win_indicators), ("LOSS", loss_indicators)]:
    total = len(rows)
    neg_slope = sum(1 for r in rows if r["d_slope"] is not None and r["d_slope"] < 0)
    print(f"  {label}: {neg_slope}/{total} 筆 D-slope<0 ({neg_slope / total * 100:.0f}%)")

# ADX with -DI > +DI
print()
print("ADX > 25 AND -DI > +DI 過濾效果")
for label, rows in [("WIN", win_indicators), ("LOSS", loss_indicators)]:
    total = len(rows)
    match = sum(
        1
        for r in rows
        if r["adx"] is not None
        and r["adx"] > 25
        and r["minus_di"] is not None
        and r["plus_di"] is not None
        and r["minus_di"] > r["plus_di"]
    )
    print(f"  {label}: {match}/{total} 筆 ADX>25 & -DI>+DI ({match / total * 100:.0f}%)")

# Weekly RSI < 50
print()
print("W-RSI < 50 過濾效果")
for label, rows in [("WIN", win_indicators), ("LOSS", loss_indicators)]:
    total = len(rows)
    match = sum(1 for r in rows if r["w_rsi"] is not None and r["w_rsi"] < 50)
    print(f"  {label}: {match}/{total} 筆 W-RSI<50 ({match / total * 100:.0f}%)")

# OI declining
print()
print("OI Change < 0% 過濾效果")
for label, rows in [("WIN", win_indicators), ("LOSS", loss_indicators)]:
    total = len(rows)
    match = sum(1 for r in rows if r["oi_chg"] is not None and r["oi_chg"] < 0)
    print(f"  {label}: {match}/{total} 筆 OI下降 ({match / total * 100:.0f}%)")
