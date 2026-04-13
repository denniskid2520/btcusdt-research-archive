#!/usr/bin/env python3
"""Analyze Channel F (ascending, 2026-02 to 2026-03) — LIVE retesting now."""
import csv
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")


def load_csv(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def date_str(ts_str):
    return ts_str[:10]


# Load data
oi_data = load_csv("src/data/coinglass_oi_1d.csv")
funding_data = load_csv("src/data/coinglass_funding_1d.csv")
ls_data = load_csv("src/data/coinglass_top_ls_1d.csv")
liq_data = load_csv("src/data/coinglass_liquidation_4h.csv")

# Index by date
oi_by_date = {}
for r in oi_data:
    d = date_str(r["timestamp"])
    oi_by_date[d] = float(r["close"])

funding_by_date = {}
for r in funding_data:
    d = date_str(r["timestamp"])
    funding_by_date[d] = float(r["close"]) * 100  # to percent

ls_by_date = {}
for r in ls_data:
    d = date_str(r["timestamp"])
    ls_by_date[d] = float(r["ratio"])

liq_by_date: dict[str, dict] = {}
for r in liq_data:
    d = date_str(r["timestamp"])
    if d not in liq_by_date:
        liq_by_date[d] = {"long": 0.0, "short": 0.0}
    liq_by_date[d]["long"] += float(r["long_usd"])
    liq_by_date[d]["short"] += float(r["short_usd"])

# Channel F key dates (2026)
events = [
    ("2026-02-05", "62749 LOW (start)", "low"),
    ("2026-02-06", "71645 HIGH", "high"),
    ("2026-02-24", "64023 LOW", "low"),
    ("2026-03-04", "74041 HIGH", "high"),
    ("2026-03-08", "65572 LOW", "low"),
    ("2026-03-16", "74847 HIGH", "high"),
    ("2026-03-22", "67305 LOW", "low"),
    ("2026-03-25", "71980 MID retest fail", "mid"),
    ("2026-03-27", "65470 BROKE", "break"),
    ("2026-04-06", "69600 RETESTING NOW", "retest"),
]

print("=" * 135)
print("CHANNEL F -- ASCENDING CHANNEL (2026-02 to 2026-03) -- LIVE RETEST IN PROGRESS")
print("=" * 135)
header = f"{'Date':<12} {'Event':<30} {'OI($B)':>8} {'OI vs PrevH':>12} {'Funding%':>10} {'L/S':>6} {'Long$M':>9} {'Short$M':>9} {'LiqRatio':>9} {'Type':>7}"
print(header)
print("-" * 135)

peak_oi = 0.0
peak_funding = -999.0
prev_high_oi = 0.0
high_dates_ls: list[tuple[str, float]] = []
all_high_fundings: list[float] = []

for date, event, etype in events:
    oi = oi_by_date.get(date, 0)
    funding = funding_by_date.get(date, 0)
    ls = ls_by_date.get(date, 0)
    liq = liq_by_date.get(date, {"long": 0.0, "short": 0.0})
    long_m = liq["long"] / 1e6
    short_m = liq["short"] / 1e6
    liq_r = long_m / short_m if short_m > 0.001 else 0

    oi_b = oi / 1e9

    if prev_high_oi > 0:
        oi_vs_high = (oi - prev_high_oi) / prev_high_oi * 100
        oi_vs_str = f"{oi_vs_high:+.1f}%"
    else:
        oi_vs_str = "-"

    if etype == "high":
        prev_high_oi = oi
        peak_oi = max(peak_oi, oi)
        peak_funding = max(peak_funding, funding)
        high_dates_ls.append((date, ls))
        all_high_fundings.append(funding)

    tag = {"low": "LOW", "high": "HIGH", "mid": "MID", "break": "BREAK", "retest": ">>>NOW"}[etype]

    marker = " <<<" if etype == "retest" else ""
    print(f"{date:<12} {event:<30} {oi_b:>7.1f}B {oi_vs_str:>12} {funding:>9.4f}% {ls:>5.2f} {long_m:>8.1f}M {short_m:>8.1f}M {liq_r:>8.2f}  {tag}{marker}")

# Show days around breakdown and retest
print()
print("--- Breakdown window (3/25 - 3/31) ---")
for d_offset in range(-2, 5):
    dd = datetime(2026, 3, 27) + timedelta(days=d_offset)
    ds = dd.strftime("%Y-%m-%d")
    oi = oi_by_date.get(ds, 0)
    funding = funding_by_date.get(ds, 0)
    ls = ls_by_date.get(ds, 0)
    liq = liq_by_date.get(ds, {"long": 0.0, "short": 0.0})
    long_m = liq["long"] / 1e6
    short_m = liq["short"] / 1e6
    liq_r = long_m / short_m if short_m > 0.001 else 0
    tag = " <-- BROKE" if ds == "2026-03-27" else ""
    print(f"  {ds}: OI=${oi/1e9:.1f}B F={funding:.4f}% L/S={ls:.2f} LongLiq=${long_m:.1f}M ShortLiq=${short_m:.1f}M LiqR={liq_r:.2f}{tag}")

print()
print("--- Retest window (4/3 - 4/6) ---")
for d_offset in range(-3, 4):
    dd = datetime(2026, 4, 6) + timedelta(days=d_offset)
    ds = dd.strftime("%Y-%m-%d")
    oi = oi_by_date.get(ds, 0)
    funding = funding_by_date.get(ds, 0)
    ls = ls_by_date.get(ds, 0)
    liq = liq_by_date.get(ds, {"long": 0.0, "short": 0.0})
    long_m = liq["long"] / 1e6
    short_m = liq["short"] / 1e6
    liq_r = long_m / short_m if short_m > 0.001 else 0
    tag = " <-- TODAY" if ds == "2026-04-06" else ""
    if oi > 0:
        print(f"  {ds}: OI=${oi/1e9:.1f}B F={funding:.4f}% L/S={ls:.2f} LongLiq=${long_m:.1f}M ShortLiq=${short_m:.1f}M LiqR={liq_r:.2f}{tag}")

print()
print("=" * 80)
print("4-RULE VERIFICATION -- Channel F Breakdown (3/27)")
print("=" * 80)

# Rule 1: Channel highs L/S > 1.10
avg_ls = sum(v for _, v in high_dates_ls) / len(high_dates_ls) if high_dates_ls else 0
print()
print("Rule 1: Channel highs L/S ratio > 1.10")
for d, v in high_dates_ls:
    status = "OK" if v > 1.10 else "FAIL"
    print(f"  {d}: L/S = {v:.2f}  [{status}]")
print(f"  Avg = {avg_ls:.2f}")
r1 = all(v > 1.10 for _, v in high_dates_ls)
print(f"  => {'PASS' if r1 else 'FAIL'}")

# Rule 2: Breakdown liq ratio > 1.5x
break_date = "2026-03-27"
bl = liq_by_date.get(break_date, {"long": 0.0, "short": 0.0})
br_ratio = bl["long"] / bl["short"] if bl["short"] > 0 else 0
print()
print("Rule 2: Breakdown Long/Short liq ratio > 1.5x")
print(f"  {break_date}: Long=${bl['long']/1e6:.1f}M Short=${bl['short']/1e6:.1f}M Ratio={br_ratio:.2f}x")
r2 = br_ratio > 1.5
print(f"  => {'PASS' if r2 else 'FAIL'}")

# Rule 3: OI drop > 5% from last high to breakdown
last_high = "2026-03-16"
lh_oi = oi_by_date.get(last_high, 0)
bk_oi = oi_by_date.get(break_date, 0)
oi_drop = (bk_oi - lh_oi) / lh_oi * 100 if lh_oi > 0 else 0
print()
print("Rule 3: OI drop > 5% from last high to breakdown")
print(f"  {last_high} OI: ${lh_oi/1e9:.2f}B")
print(f"  {break_date} OI: ${bk_oi/1e9:.2f}B")
print(f"  Change: {oi_drop:+.1f}%")
r3 = oi_drop < -5
print(f"  => {'PASS' if r3 else 'FAIL'}")

# Rule 4: Funding anomaly (4a or 4b)
bk_funding = funding_by_date.get(break_date, 0)
avg_high_funding = sum(all_high_fundings) / len(all_high_fundings) if all_high_fundings else 0

# Find max funding in channel
start = datetime(2026, 2, 5)
end = datetime(2026, 3, 27)
d = start
max_f_val = -999.0
max_f_date = ""
while d <= end:
    ds = d.strftime("%Y-%m-%d")
    f = funding_by_date.get(ds, None)
    if f is not None and f > max_f_val:
        max_f_val = f
        max_f_date = ds
    d += timedelta(days=1)

print()
print("Rule 4: Funding anomaly (4a OR 4b)")
print(f"  Peak funding at highs: {peak_funding:.4f}%")
print(f"  Avg funding at highs: {avg_high_funding:.4f}%")
print(f"  Max funding in channel: {max_f_date} = {max_f_val:.4f}%")
print(f"  Breakdown funding: {bk_funding:.4f}%")

use_peak = max(peak_funding, max_f_val)
# Rule 4a: breakdown < 50% of peak
if use_peak > 0:
    ratio_4a = bk_funding / use_peak * 100
    r4a = bk_funding < use_peak * 0.50
    print(f"  4a: Breakdown = {ratio_4a:.1f}% of peak ({use_peak:.4f}%) => {'PASS' if r4a else 'FAIL'}")
else:
    r4a = False
    print(f"  4a: Peak <= 0, skipping => FAIL")

# Rule 4b: breakdown > 3x avg at highs
if abs(avg_high_funding) > 0.001:
    ratio_4b = abs(bk_funding) / abs(avg_high_funding)
    r4b = abs(bk_funding) > 3 * abs(avg_high_funding)
    print(f"  4b: |Breakdown| / |Avg high| = {ratio_4b:.1f}x => {'PASS' if r4b else 'FAIL'}")
else:
    r4b = False
    print(f"  4b: Avg high funding ~0, skipping => FAIL")

r4 = r4a or r4b
print(f"  => Combined: {'PASS' if r4 else 'FAIL'}")

print()
score = sum([r1, r2, r3, r4])
print(f"{'=' * 80}")
print(f"TOTAL: {score}/4 rules passed")
print(f"{'=' * 80}")

# RETEST analysis
print()
print("=" * 80)
print("RETEST ANALYSIS -- Should it fail or succeed?")
print("=" * 80)

retest_date = "2026-04-04"  # latest data we have
rt_oi = oi_by_date.get(retest_date, 0)
rt_funding = funding_by_date.get(retest_date, 0)
rt_ls = ls_by_date.get(retest_date, 0)
rt_liq = liq_by_date.get(retest_date, {"long": 0.0, "short": 0.0})

# Compare with breakdown
print(f"\n  Indicator comparison: Breakdown vs Retest")
print(f"  {'':>20} {'Breakdown(3/27)':>18} {'Retest(~4/4-6)':>18}")
print(f"  {'OI':>20} ${bk_oi/1e9:.2f}B         ${rt_oi/1e9:.2f}B")
print(f"  {'Funding':>20} {bk_funding:.4f}%       {rt_funding:.4f}%")
print(f"  {'L/S':>20} {ls_by_date.get(break_date, 0):.2f}            {rt_ls:.2f}")
rt_long = rt_liq['long'] / 1e6
rt_short = rt_liq['short'] / 1e6
rt_liq_r = rt_long / rt_short if rt_short > 0.001 else 0
bk_long = bl['long'] / 1e6
bk_short = bl['short'] / 1e6
print(f"  {'Long Liq':>20} ${bk_long:.1f}M          ${rt_long:.1f}M")
print(f"  {'Short Liq':>20} ${bk_short:.1f}M          ${rt_short:.1f}M")

# OI recovery from low
# Find lowest OI after breakdown
low_oi_after = 999e9
low_oi_date = ""
d = datetime(2026, 3, 27)
end = datetime(2026, 4, 6)
while d <= end:
    ds = d.strftime("%Y-%m-%d")
    o = oi_by_date.get(ds, None)
    if o is not None and o < low_oi_after:
        low_oi_after = o
        low_oi_date = ds
    d += timedelta(days=1)

if low_oi_after < 999e9:
    oi_recovery = (rt_oi - low_oi_after) / low_oi_after * 100
    print(f"\n  OI after break: lowest ${low_oi_after/1e9:.2f}B ({low_oi_date})")
    print(f"  OI at retest: ${rt_oi/1e9:.2f}B (recovery: {oi_recovery:+.1f}%)")

# Channel E retest comparison
print(f"\n  --- Channel E retest pattern (for comparison) ---")
print(f"  E broke 1/20: OI=$60.4B, F=0.97%")
print(f"  E retest 1/28: OI=$59.8B (weak +2.3% recovery), F=0.62%")
print(f"  E result: RETEST FAILED -> crash next day")

# Verdict
print()
print("  RETEST VERDICT:")
if rt_ls > 1.5:
    print(f"  - L/S = {rt_ls:.2f} -> STILL CROWDED LONG (bearish)")
else:
    print(f"  - L/S = {rt_ls:.2f} -> longs reduced (mixed)")

if rt_oi > bk_oi:
    pct = (rt_oi - bk_oi) / bk_oi * 100
    print(f"  - OI rose {pct:+.1f}% into retest -> NEW POSITIONS OPENING (could trap)")
else:
    pct = (rt_oi - bk_oi) / bk_oi * 100
    print(f"  - OI still below breakdown ({pct:+.1f}%) -> weak conviction")

if rt_funding > 0.5:
    print(f"  - Funding {rt_funding:.4f}% -> LONGS PAYING HEAVILY (bearish)")
elif rt_funding > 0:
    print(f"  - Funding {rt_funding:.4f}% -> longs paying (slightly bearish)")
else:
    print(f"  - Funding {rt_funding:.4f}% -> shorts paying (neutral/bullish)")
