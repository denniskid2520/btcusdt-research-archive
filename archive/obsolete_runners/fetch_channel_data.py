"""Fetch Coinglass daily data for descending channel analysis.

Channel: 2025-11-15 to 2026-02-05
Indicators: OI, Funding Rate, L/S Ratio (top trader), Liquidation
Sources: local CSVs for OI/Funding/LS, API for liquidation daily
"""

from __future__ import annotations

import csv
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

# --- Config ---
API_KEY = os.environ.get("COINGLASS_API_KEY", "")
BASE_URL = "https://open-api-v4.coinglass.com"

START_DATE = datetime(2025, 11, 10)  # buffer before channel
END_DATE = datetime(2026, 2, 10)     # buffer after channel

DATA_DIR = "src/data"

# Key channel dates with labels
KEY_DATES = [
    ("2025-11-21", 80600,  "LOW  - channel low"),
    ("2025-11-28", 93036,  "HIGH - channel high"),
    ("2025-12-01", 83757,  "LOW  - channel low"),
    ("2025-12-03", 94164,  "HIGH - channel high"),
    ("2025-12-06", 89214,  "MID  - mid retest"),
    ("2025-12-09", 94571,  "HIGH - channel high"),
    ("2025-12-18", 85426,  "LOW  - channel low"),
    ("2025-12-22", 90537,  "MID  - mid retest fail"),
    ("2025-12-29", 86673,  "LOW  - channel low"),
    ("2026-01-05", 94736,  "MID  - mid high"),
    ("2026-01-14", 97879,  "HIGH - channel high"),
    ("2026-01-20", 87695,  "BROKE - breakdown"),
    ("2026-01-28", 89131,  "FAIL - retest fail -> crash"),
]


def load_csv_as_dict(filepath, value_fn):
    """Load a CSV, index by date string (YYYY-MM-DD), apply value_fn to each row."""
    result = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row["timestamp"][:10]  # YYYY-MM-DD
            dt = datetime.fromisoformat(ts)
            if START_DATE <= dt <= END_DATE:
                result[ts] = value_fn(row)
    return result


def load_4h_liquidation_aggregate(filepath):
    """Load 4h liquidation CSV and aggregate to daily sums."""
    daily = defaultdict(lambda: {"long_usd": 0.0, "short_usd": 0.0})
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row["timestamp"][:10]
            dt = datetime.fromisoformat(ts)
            if START_DATE <= dt <= END_DATE:
                daily[ts]["long_usd"] += float(row["long_usd"])
                daily[ts]["short_usd"] += float(row["short_usd"])
    return dict(daily)


def fetch_liquidation_daily_api():
    """Fetch daily liquidation from Coinglass API as fallback."""
    start_ts = int(START_DATE.replace(tzinfo=timezone.utc).timestamp())
    end_ts = int(END_DATE.replace(tzinfo=timezone.utc).timestamp())

    params = {
        "symbol": "BTC",
        "interval": "1d",
        "exchange_list": "Binance",
        "limit": 4500,
        "startTime": start_ts,
        "endTime": end_ts,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE_URL}/api/futures/liquidation/aggregated-history?{query}"

    req = Request(url, method="GET")
    req.add_header("CG-API-KEY", API_KEY)
    req.add_header("Accept", "application/json")

    with urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    if result.get("code") != "0":
        raise RuntimeError(f"API error: {result.get('msg', 'unknown')}")

    data = result.get("data", [])
    daily = {}
    for d in data:
        ts = datetime.fromtimestamp(d["time"] / 1000, tz=timezone.utc)
        date_str = ts.strftime("%Y-%m-%d")
        daily[date_str] = {
            "long_usd": float(d.get("aggregated_long_liquidation_usd", 0)),
            "short_usd": float(d.get("aggregated_short_liquidation_usd", 0)),
        }
    return daily


def fmt_billions(val):
    """Format large numbers as billions with 2 decimal places."""
    return f"${val / 1e9:.2f}B"


def fmt_millions(val):
    """Format as millions."""
    if val >= 1e6:
        return f"${val / 1e6:.1f}M"
    elif val >= 1e3:
        return f"${val / 1e3:.0f}K"
    else:
        return f"${val:.0f}"


def fmt_pct(val):
    """Format as percentage."""
    return f"{val * 100:.4f}%"


def main():
    print("=" * 120)
    print("DESCENDING CHANNEL ANALYSIS: BTC 2025-11-15 to 2026-02-05")
    print("Coinglass Daily Data: OI, Funding Rate, L/S Ratio, Liquidation")
    print("=" * 120)

    # --- Load data from local CSVs ---
    print("\nLoading data from local CSVs...")

    # OI: close value
    oi_data = load_csv_as_dict(
        f"{DATA_DIR}/coinglass_oi_1d.csv",
        lambda r: {
            "close": float(r["close"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
        }
    )
    print(f"  OI: {len(oi_data)} daily bars loaded")

    # Funding rate: close value (OI-weighted daily average)
    funding_data = load_csv_as_dict(
        f"{DATA_DIR}/coinglass_funding_1d.csv",
        lambda r: {
            "close": float(r["close"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
        }
    )
    print(f"  Funding: {len(funding_data)} daily bars loaded")

    # Top trader L/S ratio
    ls_data = load_csv_as_dict(
        f"{DATA_DIR}/coinglass_top_ls_1d.csv",
        lambda r: {
            "long_pct": float(r["long_percent"]),
            "short_pct": float(r["short_percent"]),
            "ratio": float(r["ratio"]),
        }
    )
    print(f"  L/S Ratio: {len(ls_data)} daily bars loaded")

    # Liquidation: aggregate 4h to daily
    print("  Aggregating 4h liquidation to daily...")
    liq_data = load_4h_liquidation_aggregate(f"{DATA_DIR}/coinglass_liquidation_4h.csv")
    if not liq_data:
        print("  No local liquidation data, fetching from API...")
        liq_data = fetch_liquidation_daily_api()
    print(f"  Liquidation: {len(liq_data)} daily bars loaded")

    # --- Compute OI changes (1-day and 3-day) ---
    all_dates_sorted = sorted(oi_data.keys())
    oi_change_1d = {}
    oi_change_3d = {}
    for i, d in enumerate(all_dates_sorted):
        if i >= 1:
            prev = all_dates_sorted[i - 1]
            if prev in oi_data and d in oi_data:
                chg = (oi_data[d]["close"] - oi_data[prev]["close"]) / oi_data[prev]["close"]
                oi_change_1d[d] = chg
        if i >= 3:
            prev3 = all_dates_sorted[i - 3]
            if prev3 in oi_data and d in oi_data:
                chg = (oi_data[d]["close"] - oi_data[prev3]["close"]) / oi_data[prev3]["close"]
                oi_change_3d[d] = chg

    # ============================
    # TABLE 1: Full daily data for the entire channel period
    # ============================
    print("\n")
    print("=" * 150)
    print("FULL DAILY DATA: 2025-11-15 to 2026-02-05")
    print("=" * 150)

    header = f"{'Date':<12} {'OI Close':>14} {'OI Chg 1d':>10} {'OI Chg 3d':>10} {'Funding':>10} {'L/S Ratio':>10} {'Long%':>7} {'Liq Long':>12} {'Liq Short':>12} {'Liq Net':>12} {'Label'}"
    print(header)
    print("-" * 150)

    channel_start = datetime(2025, 11, 15)
    channel_end = datetime(2026, 2, 5)

    key_date_set = {kd[0] for kd in KEY_DATES}
    key_date_map = {kd[0]: (kd[1], kd[2]) for kd in KEY_DATES}

    d = channel_start
    while d <= channel_end:
        ds = d.strftime("%Y-%m-%d")
        label = ""
        marker = "  "
        if ds in key_date_map:
            price, desc = key_date_map[ds]
            label = f"${price:,} {desc}"
            if "HIGH" in desc:
                marker = ">>"
            elif "LOW" in desc:
                marker = "<<"
            elif "BROKE" in desc or "FAIL" in desc:
                marker = "!!"
            else:
                marker = "--"

        oi_close_str = fmt_billions(oi_data[ds]["close"]) if ds in oi_data else "N/A"
        oi_1d_str = f"{oi_change_1d[ds]*100:+.1f}%" if ds in oi_change_1d else "N/A"
        oi_3d_str = f"{oi_change_3d[ds]*100:+.1f}%" if ds in oi_change_3d else "N/A"
        fund_str = fmt_pct(funding_data[ds]["close"]) if ds in funding_data else "N/A"
        ls_ratio_str = f"{ls_data[ds]['ratio']:.2f}" if ds in ls_data else "N/A"
        long_pct_str = f"{ls_data[ds]['long_pct']:.1f}%" if ds in ls_data else "N/A"

        liq_long_str = "N/A"
        liq_short_str = "N/A"
        liq_net_str = "N/A"
        if ds in liq_data:
            ll = liq_data[ds]["long_usd"]
            ls_val = liq_data[ds]["short_usd"]
            liq_long_str = fmt_millions(ll)
            liq_short_str = fmt_millions(ls_val)
            net = ll - ls_val
            liq_net_str = fmt_millions(abs(net))
            if net > 0:
                liq_net_str = f"+L {liq_net_str}"
            else:
                liq_net_str = f"-S {liq_net_str}"

        print(f"{marker}{ds:<10} {oi_close_str:>14} {oi_1d_str:>10} {oi_3d_str:>10} {fund_str:>10} {ls_ratio_str:>10} {long_pct_str:>7} {liq_long_str:>12} {liq_short_str:>12} {liq_net_str:>12} {label}")

        d += timedelta(days=1)

    # ============================
    # TABLE 2: Key dates summary
    # ============================
    print("\n\n")
    print("=" * 150)
    print("KEY DATES SUMMARY")
    print("=" * 150)

    header2 = f"{'Date':<12} {'Price':>8} {'Type':<28} {'OI Close':>14} {'OI 1d%':>8} {'OI 3d%':>8} {'Funding':>10} {'L/S':>6} {'Long%':>7} {'Liq Long':>12} {'Liq Short':>12} {'Net Liq':>14}"
    print(header2)
    print("-" * 150)

    for ds, price, desc in KEY_DATES:
        oi_close_str = fmt_billions(oi_data[ds]["close"]) if ds in oi_data else "N/A"
        oi_1d_str = f"{oi_change_1d[ds]*100:+.1f}%" if ds in oi_change_1d else "N/A"
        oi_3d_str = f"{oi_change_3d[ds]*100:+.1f}%" if ds in oi_change_3d else "N/A"
        fund_str = fmt_pct(funding_data[ds]["close"]) if ds in funding_data else "N/A"
        ls_ratio_str = f"{ls_data[ds]['ratio']:.2f}" if ds in ls_data else "N/A"
        long_pct_str = f"{ls_data[ds]['long_pct']:.1f}%" if ds in ls_data else "N/A"

        liq_long_str = "N/A"
        liq_short_str = "N/A"
        liq_net_str = "N/A"
        if ds in liq_data:
            ll = liq_data[ds]["long_usd"]
            ls_val = liq_data[ds]["short_usd"]
            liq_long_str = fmt_millions(ll)
            liq_short_str = fmt_millions(ls_val)
            net = ll - ls_val
            liq_net_str = fmt_millions(abs(net))
            if net > 0:
                liq_net_str = f"+LONG {liq_net_str}"
            else:
                liq_net_str = f"-SHORT {liq_net_str}"

        print(f"{ds:<12} {price:>8,} {desc:<28} {oi_close_str:>14} {oi_1d_str:>8} {oi_3d_str:>8} {fund_str:>10} {ls_ratio_str:>6} {long_pct_str:>7} {liq_long_str:>12} {liq_short_str:>12} {liq_net_str:>14}")

    # ============================
    # TABLE 3: OI divergence analysis (price vs OI direction)
    # ============================
    print("\n\n")
    print("=" * 120)
    print("OI DIVERGENCE ANALYSIS (Key Dates)")
    print("=" * 120)
    print(f"{'Date':<12} {'Price':>8} {'Type':<18} {'OI 3d Chg':>10} {'Funding':>10} {'L/S':>6} {'Divergence Signal'}")
    print("-" * 120)

    for ds, price, desc in KEY_DATES:
        oi_3d = oi_change_3d.get(ds)
        fund = funding_data.get(ds, {}).get("close")
        ls_r = ls_data.get(ds, {}).get("ratio")

        signal = ""
        if oi_3d is not None and fund is not None:
            # Price at HIGH but OI falling = bearish divergence
            if "HIGH" in desc and oi_3d < -0.02:
                signal = "!! BEARISH DIV: price high but OI dropping"
            elif "HIGH" in desc and oi_3d < 0:
                signal = "? WEAK: price high, OI slightly down"
            elif "HIGH" in desc and oi_3d > 0.05:
                signal = "STRONG: price high, OI rising = conviction"

            # Price at LOW but OI rising = shorts loading
            elif "LOW" in desc and oi_3d > 0.03:
                signal = "!! SHORTS LOADING: price low, OI rising"
            elif "LOW" in desc and oi_3d < -0.05:
                signal = "CAPITULATION: price low, OI flushing"

            # Breakdown/retest
            elif "BROKE" in desc or "FAIL" in desc:
                if oi_3d < -0.03:
                    signal = "CAPITULATION: breakdown + OI flushing"
                elif oi_3d > 0.02:
                    signal = "!! TRAP: retest with rising OI = bearish"
                else:
                    signal = "neutral OI on breakdown"

            # Funding extremes
            if fund > 0.001 and "HIGH" in desc:
                signal += " | EXTREME FUNDING (overleveraged longs)"
            elif fund < -0.001 and "LOW" in desc:
                signal += " | EXTREME NEG FUNDING (overleveraged shorts)"

        # L/S extremes
        if ls_r is not None:
            if ls_r > 1.2:
                signal += f" | L/S {ls_r:.2f} CROWDED LONG"
            elif ls_r < 0.85:
                signal += f" | L/S {ls_r:.2f} CROWDED SHORT"

        oi_3d_str = f"{oi_3d*100:+.1f}%" if oi_3d is not None else "N/A"
        fund_str = fmt_pct(fund) if fund is not None else "N/A"
        ls_str = f"{ls_r:.2f}" if ls_r is not None else "N/A"

        print(f"{ds:<12} {price:>8,} {desc:<18} {oi_3d_str:>10} {fund_str:>10} {ls_str:>6} {signal}")

    # ============================
    # TABLE 4: Liquidation cascade analysis
    # ============================
    print("\n\n")
    print("=" * 100)
    print("LIQUIDATION CASCADE ANALYSIS (Key Dates)")
    print("=" * 100)
    print(f"{'Date':<12} {'Price':>8} {'Type':<18} {'Liq Long':>12} {'Liq Short':>12} {'Ratio L/S':>10} {'Signal'}")
    print("-" * 100)

    for ds, price, desc in KEY_DATES:
        if ds not in liq_data:
            print(f"{ds:<12} {price:>8,} {desc:<18} {'N/A':>12} {'N/A':>12} {'N/A':>10}")
            continue

        ll = liq_data[ds]["long_usd"]
        ls_val = liq_data[ds]["short_usd"]
        total = ll + ls_val
        liq_ratio = ll / ls_val if ls_val > 0 else float("inf")

        signal = ""
        if "LOW" in desc or "BROKE" in desc:
            if liq_ratio > 3:
                signal = "!! LONG CAPITULATION (longs wiped)"
            elif liq_ratio > 1.5:
                signal = "longs punished on drop"
            elif liq_ratio < 0.5:
                signal = "?? shorts squeezed at low?"
        elif "HIGH" in desc:
            if liq_ratio < 0.3:
                signal = "!! SHORT SQUEEZE (shorts wiped)"
            elif liq_ratio < 0.7:
                signal = "shorts punished on rally"
            elif liq_ratio > 2:
                signal = "?? longs liquidated at high?"
        elif "FAIL" in desc:
            if ll > 5e6:
                signal = "!! MASSIVE LONG LIQS on retest fail"
            elif ll > 1e6:
                signal = "significant long liqs on fail"

        if total > 20e6:
            signal += " | MEGA LIQ DAY"
        elif total > 10e6:
            signal += " | heavy liq day"

        print(f"{ds:<12} {price:>8,} {desc:<18} {fmt_millions(ll):>12} {fmt_millions(ls_val):>12} {liq_ratio:>10.2f} {signal}")

    # ============================
    # SUMMARY STATS
    # ============================
    print("\n\n")
    print("=" * 80)
    print("SUMMARY STATISTICS FOR CHANNEL PERIOD")
    print("=" * 80)

    # Collect stats for the channel period
    oi_values = []
    funding_values = []
    ls_ratios = []
    total_long_liqs = 0.0
    total_short_liqs = 0.0

    d = channel_start
    while d <= channel_end:
        ds = d.strftime("%Y-%m-%d")
        if ds in oi_data:
            oi_values.append(oi_data[ds]["close"])
        if ds in funding_data:
            funding_values.append(funding_data[ds]["close"])
        if ds in ls_data:
            ls_ratios.append(ls_data[ds]["ratio"])
        if ds in liq_data:
            total_long_liqs += liq_data[ds]["long_usd"]
            total_short_liqs += liq_data[ds]["short_usd"]
        d += timedelta(days=1)

    if oi_values:
        print(f"OI range:           {fmt_billions(min(oi_values))} - {fmt_billions(max(oi_values))}")
        print(f"OI start -> end:    {fmt_billions(oi_values[0])} -> {fmt_billions(oi_values[-1])} ({(oi_values[-1]/oi_values[0]-1)*100:+.1f}%)")

    if funding_values:
        avg_f = sum(funding_values) / len(funding_values)
        print(f"Avg daily funding:  {fmt_pct(avg_f)}")
        print(f"Funding range:      {fmt_pct(min(funding_values))} to {fmt_pct(max(funding_values))}")

    if ls_ratios:
        print(f"L/S ratio range:    {min(ls_ratios):.2f} - {max(ls_ratios):.2f}")
        print(f"Avg L/S ratio:      {sum(ls_ratios)/len(ls_ratios):.2f}")

    print(f"Total long liqs:    {fmt_millions(total_long_liqs)}")
    print(f"Total short liqs:   {fmt_millions(total_short_liqs)}")
    total_liqs = total_long_liqs + total_short_liqs
    if total_liqs > 0:
        print(f"Long liq share:     {total_long_liqs/total_liqs*100:.1f}%")

    print("\nDone.")


if __name__ == "__main__":
    main()
