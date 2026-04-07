"""Quantify bull market impulse trades with different trail configurations.

Same methodology as bear market ACCEL zone analysis:
- Find breakout entry points in 4 bull market periods
- Simulate each trade with different ATR trail widths and ACCEL multipliers
- Compare total PnL, win rate, avg per trade
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from datetime import datetime as dt
from data.backfill import load_bars_from_csv

bars_4h = load_bars_from_csv('src/data/btcusdt_4h_5year.csv')

# === MACD computation ===
def ema(values, period):
    result = [values[0]]
    k = 2 / (period + 1)
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result

closes = [b.close for b in bars_4h]
timestamps = [b.timestamp for b in bars_4h]

# Daily = every 6th bar
daily_closes = [closes[i] for i in range(0, len(closes), 6)]
daily_ts = [timestamps[i] for i in range(0, len(timestamps), 6)]
# Weekly = every 42nd bar
weekly_closes = [closes[i] for i in range(0, len(closes), 42)]
weekly_ts = [timestamps[i] for i in range(0, len(timestamps), 42)]

d_ema12 = ema(daily_closes, 12)
d_ema26 = ema(daily_closes, 26)
d_macd = [a - b for a, b in zip(d_ema12, d_ema26)]
d_signal = ema(d_macd, 9)
d_hist = [m - s for m, s in zip(d_macd, d_signal)]

w_ema12 = ema(weekly_closes, 12)
w_ema26 = ema(weekly_closes, 26)
w_macd = [a - b for a, b in zip(w_ema12, w_ema26)]
w_signal = ema(w_macd, 9)
w_hist = [m - s for m, s in zip(w_macd, w_signal)]


def get_daily_macd_at(ts):
    best_idx = 0
    for i, t in enumerate(daily_ts):
        if t <= ts:
            best_idx = i
        else:
            break
    return d_macd[best_idx], d_hist[best_idx]


def get_weekly_macd_at(ts):
    best_idx = 0
    for i, t in enumerate(weekly_ts):
        if t <= ts:
            best_idx = i
        else:
            break
    return w_macd[best_idx], w_hist[best_idx]


def calc_atr(bars_slice, period=14):
    if len(bars_slice) < period + 1:
        return 0
    trs = []
    for i in range(1, len(bars_slice)):
        tr = max(
            bars_slice[i].high - bars_slice[i].low,
            abs(bars_slice[i].high - bars_slice[i-1].close),
            abs(bars_slice[i].low - bars_slice[i-1].close)
        )
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0
    return sum(trs[-period:]) / period


def sim_long_trade(bars_4h, entry_idx, entry_price, atr_mult, accel_mult,
                   time_limit_bars=168):
    """Simulate a long trade with trailing stop and bull ACCEL zone."""
    atr = calc_atr(bars_4h[max(0, entry_idx - 60):entry_idx + 1])
    if atr == 0:
        atr = entry_price * 0.015

    trail_stop = entry_price - atr * atr_mult
    peak = entry_price
    accel_bars_count = 0

    for i in range(entry_idx + 1, min(entry_idx + time_limit_bars, len(bars_4h))):
        bar = bars_4h[i]

        # Bull ACCEL: weekly hist > 0 (golden cross) AND daily MACD > 0
        w_m, w_h = get_weekly_macd_at(bar.timestamp)
        d_m, d_h = get_daily_macd_at(bar.timestamp)
        bull_accel = w_h > 0 and d_m > 0

        if bull_accel:
            accel_bars_count += 1
            effective_mult = atr_mult * accel_mult
        else:
            effective_mult = atr_mult

        # Update ATR every 6 bars
        if (i - entry_idx) % 6 == 0:
            new_atr = calc_atr(bars_4h[max(0, i - 60):i + 1])
            if new_atr > 0:
                atr = new_atr

        # Update peak and trail
        if bar.high > peak:
            peak = bar.high
            trail_stop = peak - atr * effective_mult

        # Check stop hit
        if bar.low <= trail_stop:
            return trail_stop, i, 'trail_stop', peak, accel_bars_count

    # Time stop
    exit_i = min(entry_idx + time_limit_bars - 1, len(bars_4h) - 1)
    return bars_4h[exit_i].close, exit_i, 'time_stop', peak, accel_bars_count


def find_bull_entries(bars_4h, start, end, lookback=30):
    """Find breakout entries: close breaks above lookback-bar high after pullback."""
    entries = []
    segment_indices = [(i, b) for i, b in enumerate(bars_4h) if start <= b.timestamp <= end]
    if not segment_indices:
        return entries

    for idx, (gi, bar) in enumerate(segment_indices):
        if gi < lookback:
            continue

        prev_highs = [bars_4h[gi - k].high for k in range(1, lookback + 1)]
        prev_high = max(prev_highs)

        if bar.close > prev_high and bars_4h[gi - 1].close <= prev_high:
            recent_low = min(bars_4h[gi - k].low for k in range(1, min(lookback, 60) + 1))
            pullback_pct = (prev_high - recent_low) / prev_high * 100
            if pullback_pct >= 3:
                entries.append({
                    'idx': gi,
                    'price': bar.close,
                    'date': bar.timestamp,
                    'prev_high': prev_high,
                    'pullback': pullback_pct,
                })

    # Deduplicate: 1 entry per week
    filtered = []
    last_idx = -999
    for e in entries:
        if e['idx'] - last_idx >= 42:
            filtered.append(e)
            last_idx = e['idx']
    return filtered


# === Main ===
bull_periods = [
    {'name': '2023-01~04 (熊市底部反彈)', 'start': dt(2023, 1, 1), 'end': dt(2023, 4, 30)},
    {'name': '2023-10~2024-03 (ETF牛市)', 'start': dt(2023, 10, 1), 'end': dt(2024, 3, 17)},
    {'name': '2024-10~12 (選舉牛市)', 'start': dt(2024, 10, 1), 'end': dt(2024, 12, 31)},
    {'name': '2025-04~08 (反彈牛市)', 'start': dt(2025, 4, 1), 'end': dt(2025, 8, 31)},
]

configs = [
    ('ATR3.5 FLAT', 3.5, 1.0),
    ('ATR5 FLAT', 5.0, 1.0),
    ('ATR7 FLAT', 7.0, 1.0),
    ('ATR5 + ACCEL 2x', 5.0, 2.0),
    ('ATR5 + ACCEL 3x', 5.0, 3.0),
    ('ATR7 + ACCEL 2x', 7.0, 2.0),
    ('ATR7 + ACCEL 3x', 7.0, 3.0),
]

all_results = {c[0]: [] for c in configs}

for period in bull_periods:
    entries = find_bull_entries(bars_4h, period['start'], period['end'])

    print('=' * 110)
    print(f"  {period['name']}")
    print(f"  找到 {len(entries)} 個突破入場點")
    print('=' * 110)

    for e in entries:
        w_m, w_h = get_weekly_macd_at(e['date'])
        d_m, d_h = get_daily_macd_at(e['date'])

        bull_accel = w_h > 0 and d_m > 0
        print(f"\n  入場: {e['date'].strftime('%Y-%m-%d %H:%M')} @ ${e['price']:,.0f}  "
              f"(突破 ${e['prev_high']:,.0f}, 回撤 {e['pullback']:.1f}%)")
        print(f"  MACD: W-hist={w_h:+,.0f}  D-MACD={d_m:+,.0f}  "
              f"Bull ACCEL: {'YES' if bull_accel else 'NO'}")
        print()

        header = (f"  {'Config':<22s} {'Exit Date':<12s} {'Exit $':>10s} "
                  f"{'PnL':>8s} {'Days':>6s} {'Peak':>10s} {'Reason':<12s} ACCEL")
        print(header)
        print(f"  {'-' * 100}")

        for cname, atr_m, accel_m in configs:
            exit_p, exit_i, reason, peak, ab = sim_long_trade(
                bars_4h, e['idx'], e['price'], atr_m, accel_m)
            pnl_pct = (exit_p - e['price']) / e['price'] * 100
            days = (bars_4h[exit_i].timestamp - e['date']).total_seconds() / 86400
            peak_pct = (peak - e['price']) / e['price'] * 100

            all_results[cname].append({
                'period': period['name'][:10],
                'entry': e['price'],
                'exit': exit_p,
                'pnl': pnl_pct,
                'days': days,
                'peak': peak_pct,
                'accel_bars': ab,
            })

            marker = ' <<<' if pnl_pct > 15 else ''
            print(f"  {cname:<22s} {bars_4h[exit_i].timestamp.strftime('%Y-%m-%d'):<12s} "
                  f"${exit_p:>9,.0f} {pnl_pct:>+7.1f}% {days:>5.0f}d "
                  f"${peak:>9,.0f} ({peak_pct:>+5.1f}%) {reason:<12s} {ab:>4d}{marker}")

# === Grand Summary ===
print()
print('=' * 110)
print('  GRAND TOTAL (所有牛市脈衝交易)')
print('=' * 110)
header = (f"  {'Config':<22s} {'Trades':>6s} {'Total PnL':>10s} "
          f"{'Avg/Trade':>10s} {'Win Rate':>9s} {'Max Win':>9s} {'Max Loss':>9s}")
print(header)
print(f"  {'-' * 80}")

for cname, _, _ in configs:
    trades = all_results[cname]
    n = len(trades)
    if n == 0:
        continue
    total = sum(t['pnl'] for t in trades)
    avg = total / n
    wins = sum(1 for t in trades if t['pnl'] > 0)
    wr = wins / n * 100
    max_w = max(t['pnl'] for t in trades)
    max_l = min(t['pnl'] for t in trades)
    print(f"  {cname:<22s} {n:>6d} {total:>+9.1f}% {avg:>+9.1f}% "
          f"{wr:>7.0f}% {max_w:>+8.1f}% {max_l:>+8.1f}%")

# === Per-period summary ===
print()
print('=' * 110)
print('  PER-PERIOD BREAKDOWN')
print('=' * 110)
for period in bull_periods:
    pname = period['name'][:10]
    print(f"\n  {period['name']}:")
    print(f"  {'Config':<22s} {'N':>3s} {'Total':>8s} {'Avg':>8s} {'WR':>6s}")
    print(f"  {'-' * 50}")
    for cname, _, _ in configs:
        trades = [t for t in all_results[cname] if t['period'] == pname]
        n = len(trades)
        if n == 0:
            continue
        total = sum(t['pnl'] for t in trades)
        avg = total / n
        wins = sum(1 for t in trades if t['pnl'] > 0)
        wr = wins / n * 100
        print(f"  {cname:<22s} {n:>3d} {total:>+7.1f}% {avg:>+7.1f}% {wr:>5.0f}%")
