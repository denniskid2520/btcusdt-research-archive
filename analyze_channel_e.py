#!/usr/bin/env python3
"""Analyze Channel E (ascending, 2025-11 to 2026-01) using Coinglass daily data."""
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

# Channel E key dates
events = [
    ("2025-11-21", "80600 LOW (start)", "low"),
    ("2025-11-28", "93036 HIGH", "high"),
    ("2025-12-01", "83757 LOW", "low"),
    ("2025-12-03", "94164 HIGH", "high"),
    ("2025-12-06", "89214 MID retest", "mid"),
    ("2025-12-09", "94571 HIGH", "high"),
    ("2025-12-18", "85426 LOW", "low"),
    ("2025-12-22", "90537 MID fail", "mid"),
    ("2025-12-29", "86673 LOW", "low"),
    ("2026-01-05", "94736 MID high", "mid"),
    ("2026-01-14", "97879 HIGH (peak)", "high"),
    ("2026-01-20", "87695 BROKE", "break"),
    ("2026-01-28", "89131 RETEST FAIL", "break"),
]

print("=" * 130)
print("CHANNEL E — ASCENDING CHANNEL (2025-11 to 2026-01)")
print("=" * 130)
header = f"{'Date':<12} {'Event':<28} {'OI($B)':>8} {'OI vs PrevH':>12} {'Funding%':>10} {'L/S':>6} {'Long$M':>9} {'Short$M':>9} {'LiqRatio':>9} {'Type':>6}"
print(header)
print("-" * 130)

peak_oi = 0.0
peak_funding = -999.0
prev_high_oi = 0.0
high_dates_ls: list[tuple[str, float]] = []

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

    tag = {"low": "LOW", "high": "HIGH", "mid": "MID", "break": "BREAK"}[etype]

    print(f"{date:<12} {event:<28} {oi_b:>7.1f}B {oi_vs_str:>12} {funding:>9.4f}% {ls:>5.2f} {long_m:>8.1f}M {short_m:>8.1f}M {liq_r:>8.2f}  {tag}")

# Post-crash
for extra_d in ["2026-01-29", "2026-01-30", "2026-01-31", "2026-02-01", "2026-02-03"]:
    oi = oi_by_date.get(extra_d, 0)
    funding = funding_by_date.get(extra_d, 0)
    ls = ls_by_date.get(extra_d, 0)
    liq = liq_by_date.get(extra_d, {"long": 0.0, "short": 0.0})
    long_m = liq["long"] / 1e6
    short_m = liq["short"] / 1e6
    liq_r = long_m / short_m if short_m > 0.001 else 0
    oi_b = oi / 1e9
    oi_vs = (oi - prev_high_oi) / prev_high_oi * 100 if prev_high_oi > 0 else 0
    print(f"{extra_d:<12} {'(post-crash)':<28} {oi_b:>7.1f}B {oi_vs:>+11.1f}% {funding:>9.4f}% {ls:>5.2f} {long_m:>8.1f}M {short_m:>8.1f}M {liq_r:>8.2f}  AFTER")

print()
print("=" * 80)
print("4-RULE VERIFICATION — Channel E")
print("=" * 80)

# Rule 1
avg_ls = sum(v for _, v in high_dates_ls) / len(high_dates_ls)
print()
print("Rule 1: Channel highs L/S ratio > 1.10")
for d, v in high_dates_ls:
    status = "OK" if v > 1.10 else "FAIL"
    print(f"  {d}: L/S = {v:.2f}  [{status}]")
print(f"  Avg = {avg_ls:.2f}")
r1 = all(v > 1.10 for _, v in high_dates_ls)
print(f"  => {'PASS' if r1 else 'FAIL'}")

# Rule 2
break_date = "2026-01-20"
bl = liq_by_date.get(break_date, {"long": 0.0, "short": 0.0})
br_ratio = bl["long"] / bl["short"] if bl["short"] > 0 else 0
print()
print("Rule 2: Breakdown Long/Short liq ratio > 1.5x")
print(f"  {break_date}: Long=${bl['long']/1e6:.1f}M Short=${bl['short']/1e6:.1f}M Ratio={br_ratio:.2f}x")
r2 = br_ratio > 1.5
print(f"  => {'PASS' if r2 else 'FAIL'}")

# Retest fail
rl = liq_by_date.get("2026-01-28", {"long": 0.0, "short": 0.0})
rr = rl["long"] / rl["short"] if rl["short"] > 0 else 0
print(f"  2026-01-28 (retest): Long=${rl['long']/1e6:.1f}M Short=${rl['short']/1e6:.1f}M Ratio={rr:.2f}x")

# Rule 3
last_high = "2026-01-14"
lh_oi = oi_by_date.get(last_high, 0)
bk_oi = oi_by_date.get(break_date, 0)
oi_drop = (bk_oi - lh_oi) / lh_oi * 100
print()
print("Rule 3: OI drop > 5% from last high to breakdown")
print(f"  {last_high} OI: ${lh_oi/1e9:.2f}B")
print(f"  {break_date} OI: ${bk_oi/1e9:.2f}B")
print(f"  Change: {oi_drop:+.1f}%")
r3 = oi_drop < -5
print(f"  => {'PASS' if r3 else 'FAIL'}")

# Rule 4
bk_funding = funding_by_date.get(break_date, 0)
print()
print("Rule 4: Breakdown funding < 50% of channel peak funding")
print(f"  Peak funding (at highs): {peak_funding:.4f}%")
print(f"  Breakdown funding: {bk_funding:.4f}%")

# Also find max funding across entire channel
start = datetime(2025, 11, 21)
end = datetime(2026, 1, 28)
d = start
max_f_date = ""
max_f_val = -999.0
while d <= end:
    ds = d.strftime("%Y-%m-%d")
    f = funding_by_date.get(ds, None)
    if f is not None and f > max_f_val:
        max_f_val = f
        max_f_date = ds
    d += timedelta(days=1)

print(f"  Max funding in entire channel: {max_f_date} = {max_f_val:.4f}%")

# Use the higher of peak-at-highs vs channel-max
use_peak = max(peak_funding, max_f_val)
print(f"  Using peak: {use_peak:.4f}%")

if use_peak > 0:
    ratio_pct = bk_funding / use_peak * 100
    print(f"  Ratio: {ratio_pct:.1f}% of peak")
    r4 = bk_funding < use_peak * 0.50
elif use_peak < 0 and bk_funding < 0:
    print(f"  Both negative")
    r4 = True  # funding collapsed
else:
    r4 = False
print(f"  => {'PASS' if r4 else 'FAIL'}")

print()
score = sum([r1, r2, r3, r4])
print(f"{'=' * 80}")
print(f"TOTAL: {score}/4 rules passed")
if score >= 3:
    print("Channel E CONFIRMS the breakdown rules!")
else:
    print(f"Only {score}/4 passed - need to investigate why.")
print(f"{'=' * 80}")

# Mid-channel analysis
print()
print("=" * 80)
print("MID-CHANNEL ANALYSIS")
print("=" * 80)
mid_dates = [
    ("2025-12-06", "89214 MID retest (support held)"),
    ("2025-12-22", "90537 MID retest FAIL"),
    ("2026-01-05", "94736 MID high"),
]
for md, desc in mid_dates:
    oi = oi_by_date.get(md, 0)
    funding = funding_by_date.get(md, 0)
    ls = ls_by_date.get(md, 0)
    liq = liq_by_date.get(md, {"long": 0.0, "short": 0.0})
    print(f"\n  {md} - {desc}")
    print(f"    OI: ${oi/1e9:.2f}B | Funding: {funding:.4f}% | L/S: {ls:.2f}")
    print(f"    Long Liq: ${liq['long']/1e6:.1f}M | Short Liq: ${liq['short']/1e6:.1f}M")
    # Find surrounding context
    for delta in [-2, -1, 0, 1, 2]:
        dd = datetime.strptime(md, "%Y-%m-%d") + timedelta(days=delta)
        ds = dd.strftime("%Y-%m-%d")
        o = oi_by_date.get(ds, 0)
        f = funding_by_date.get(ds, 0)
        l = ls_by_date.get(ds, 0)
        lq = liq_by_date.get(ds, {"long": 0.0, "short": 0.0})
        tag = " <--" if delta == 0 else ""
        print(f"    {ds}: OI=${o/1e9:.1f}B F={f:.4f}% L/S={l:.2f} LongLiq=${lq['long']/1e6:.1f}M ShortLiq=${lq['short']/1e6:.1f}M{tag}")
