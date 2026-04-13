#!/usr/bin/env python3
"""Neutral analysis of all 6 ascending channels using ALL available Coinglass indicators."""
import csv
import sys
import json
from datetime import datetime, timedelta
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")


# ── Data Loading ──

def load_csv(path: str) -> list[dict]:
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
    except FileNotFoundError:
        pass
    return rows


def date_str(ts: str) -> str:
    return ts[:10]


def load_all_data():
    """Load all available Coinglass data into date-indexed dicts."""
    data = {}

    # OI daily
    oi_by_date = {}
    for r in load_csv("src/data/coinglass_oi_1d.csv"):
        d = date_str(r["timestamp"])
        oi_by_date[d] = {
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        }
    data["oi"] = oi_by_date

    # Funding daily
    funding_by_date = {}
    for r in load_csv("src/data/coinglass_funding_1d.csv"):
        d = date_str(r["timestamp"])
        funding_by_date[d] = {
            "open": float(r["open"]) * 100,
            "high": float(r["high"]) * 100,
            "low": float(r["low"]) * 100,
            "close": float(r["close"]) * 100,
        }
    data["funding"] = funding_by_date

    # L/S ratio daily
    ls_by_date = {}
    for r in load_csv("src/data/coinglass_top_ls_1d.csv"):
        d = date_str(r["timestamp"])
        ls_by_date[d] = {
            "long_pct": float(r["long_percent"]),
            "short_pct": float(r["short_percent"]),
            "ratio": float(r["ratio"]),
        }
    data["ls"] = ls_by_date

    # Liquidation 4h -> aggregate to daily
    liq_by_date: dict[str, dict] = {}
    for r in load_csv("src/data/coinglass_liquidation_4h.csv"):
        d = date_str(r["timestamp"])
        if d not in liq_by_date:
            liq_by_date[d] = {"long": 0.0, "short": 0.0}
        liq_by_date[d]["long"] += float(r["long_usd"])
        liq_by_date[d]["short"] += float(r["short_usd"])
    data["liq"] = liq_by_date

    # CVD daily
    cvd_by_date = {}
    for r in load_csv("src/data/coinglass_cvd_1d.csv"):
        d = date_str(r["timestamp"])
        buy = float(r["buy_vol"])
        sell = float(r["sell_vol"])
        cvd_by_date[d] = {
            "buy": buy,
            "sell": sell,
            "cvd": float(r["cvd"]),
            "ratio": buy / sell if sell > 0 else 0,
        }
    data["cvd"] = cvd_by_date

    # Basis daily
    basis_by_date = {}
    for r in load_csv("src/data/coinglass_basis_1d.csv"):
        d = date_str(r["timestamp"])
        basis_by_date[d] = {
            "open": float(r["open_basis"]),
            "close": float(r["close_basis"]),
        }
    data["basis"] = basis_by_date

    # Taker Volume 4h -> aggregate to daily
    taker_by_date: dict[str, dict] = {}
    for r in load_csv("src/data/coinglass_taker_volume_4h.csv"):
        d = date_str(r["timestamp"])
        if d not in taker_by_date:
            taker_by_date[d] = {"buy": 0.0, "sell": 0.0}
        taker_by_date[d]["buy"] += float(r["buy_usd"])
        taker_by_date[d]["sell"] += float(r["sell_usd"])
    data["taker"] = taker_by_date

    return data


# ── Channel Definitions ──

CHANNELS = {
    "C": {
        "period": "Jan-Apr 2022",
        "events": [
            ("2022-01-24", 33000, "low", "start"),
            ("2022-02-10", 45821, "high", ""),
            ("2022-02-24", 34300, "low", ""),
            ("2022-03-02", 45400, "high", ""),
            ("2022-03-09", 37000, "mid", "retest"),
            ("2022-03-28", 48189, "high", "peak"),
            ("2022-04-11", 39200, "low", ""),
            ("2022-04-18", 41500, "mid", ""),
            ("2022-04-28", 37600, "low", "broke"),
        ],
    },
    "A": {
        "period": "May 2022",
        "events": [
            ("2022-05-01", 38500, "high", ""),
            ("2022-05-05", 36000, "low", ""),
            ("2022-05-09", 34000, "low", ""),
            ("2022-05-12", 28800, "low", "broke"),
            ("2022-05-16", 31300, "mid", "retest"),
        ],
    },
    "B": {
        "period": "Jul-Aug 2022",
        "events": [
            ("2022-06-18", 17570, "low", "start"),
            ("2022-06-26", 21888, "high", ""),
            ("2022-06-30", 18800, "low", ""),
            ("2022-07-08", 22400, "high", ""),
            ("2022-07-13", 19200, "low", ""),
            ("2022-07-20", 24200, "high", ""),
            ("2022-07-26", 20700, "low", ""),
            ("2022-08-04", 23200, "mid", ""),
            ("2022-08-10", 24900, "high", "peak"),
            ("2022-08-15", 24400, "mid", ""),
            ("2022-08-19", 21300, "low", "broke"),
            ("2022-08-26", 21800, "mid", "retest"),
        ],
    },
    "D": {
        "period": "Apr-Oct 2025",
        "events": [
            ("2025-04-09", 75000, "low", "start"),
            ("2025-05-12", 104000, "high", ""),
            ("2025-06-06", 98700, "low", ""),
            ("2025-06-13", 106000, "high", ""),
            ("2025-06-20", 101500, "low", ""),
            ("2025-07-03", 109000, "high", ""),
            ("2025-08-02", 104000, "mid", ""),
            ("2025-08-18", 107000, "high", ""),
            ("2025-09-01", 109000, "high", "peak"),
            ("2025-09-16", 105000, "mid", "retest_fail"),
            ("2025-10-02", 99000, "low", "broke"),
        ],
    },
    "E": {
        "period": "Nov25-Jan26",
        "events": [
            ("2025-11-21", 80600, "low", "start"),
            ("2025-11-28", 93036, "high", ""),
            ("2025-12-01", 83757, "low", ""),
            ("2025-12-03", 94164, "high", ""),
            ("2025-12-06", 89214, "mid", "retest"),
            ("2025-12-09", 94571, "high", ""),
            ("2025-12-18", 85426, "low", ""),
            ("2025-12-22", 90537, "mid", "retest_fail"),
            ("2025-12-29", 86673, "low", ""),
            ("2026-01-05", 94736, "mid", ""),
            ("2026-01-14", 97879, "high", "peak"),
            ("2026-01-20", 87695, "low", "broke"),
            ("2026-01-28", 89131, "mid", "retest_fail"),
        ],
    },
    "F": {
        "period": "Feb-Mar 2026",
        "events": [
            ("2026-02-05", 62749, "low", "start"),
            ("2026-02-06", 71645, "high", ""),
            ("2026-02-24", 64023, "low", ""),
            ("2026-03-04", 74041, "high", ""),
            ("2026-03-08", 65572, "low", ""),
            ("2026-03-16", 74847, "high", "peak"),
            ("2026-03-22", 67305, "low", ""),
            ("2026-03-25", 71980, "mid", "retest_fail"),
            ("2026-03-27", 65470, "low", "broke"),
            ("2026-04-04", 69600, "mid", "retesting"),
        ],
    },
}


def get_window_avg(data_dict: dict, date_str: str, field: str, window: int = 3) -> Optional[float]:
    """Get average of a field over a window centered on date."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    values = []
    for offset in range(-window, window + 1):
        d = (dt + timedelta(days=offset)).strftime("%Y-%m-%d")
        entry = data_dict.get(d)
        if entry and field in entry:
            values.append(entry[field])
    return sum(values) / len(values) if values else None


def get_window_sum(data_dict: dict, date_str: str, field: str, window: int = 3) -> Optional[float]:
    """Get sum of a field over a window."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    total = 0.0
    count = 0
    for offset in range(-window, window + 1):
        d = (dt + timedelta(days=offset)).strftime("%Y-%m-%d")
        entry = data_dict.get(d)
        if entry and field in entry:
            total += entry[field]
            count += 1
    return total if count > 0 else None


def oi_change_pct(data: dict, date_from: str, date_to: str) -> Optional[float]:
    """OI percentage change between two dates."""
    oi_from = data["oi"].get(date_from, {}).get("close")
    oi_to = data["oi"].get(date_to, {}).get("close")
    if oi_from and oi_to and oi_from > 0:
        return (oi_to - oi_from) / oi_from * 100
    return None


def main():
    data = load_all_data()

    print("=" * 140)
    print("ALL 6 CHANNELS — NEUTRAL INDICATOR ANALYSIS")
    print("=" * 140)
    print(f"Data sources: OI(1d), Funding(1d), L/S(1d), Liquidation(4h->1d), CVD(1d), Basis(1d), TakerVol(4h->1d)")
    print()

    # ── Per-channel detailed dump ──
    all_channel_stats = {}

    for ch_name, ch_info in CHANNELS.items():
        print()
        print(f"{'#' * 140}")
        print(f"# CHANNEL {ch_name} — {ch_info['period']}")
        print(f"{'#' * 140}")

        events = ch_info["events"]
        ch_stats = {"highs": [], "lows": [], "mids": [], "breaks": []}

        # Find first/last dates for channel range stats
        first_date = events[0][0]
        last_date = events[-1][0]

        # Channel-wide stats
        all_dates = []
        dt = datetime.strptime(first_date, "%Y-%m-%d")
        end_dt = datetime.strptime(last_date, "%Y-%m-%d")
        while dt <= end_dt:
            all_dates.append(dt.strftime("%Y-%m-%d"))
            dt += timedelta(days=1)

        # Compute channel-wide aggregates
        channel_oi = [(d, data["oi"].get(d, {}).get("close", 0)) for d in all_dates if data["oi"].get(d, {}).get("close")]
        channel_funding = [(d, data["funding"].get(d, {}).get("close", 0)) for d in all_dates if data["funding"].get(d)]
        channel_ls = [(d, data["ls"].get(d, {}).get("ratio", 0)) for d in all_dates if data["ls"].get(d)]
        channel_cvd_vals = [(d, data["cvd"].get(d, {}).get("cvd", 0)) for d in all_dates if data["cvd"].get(d)]
        channel_basis = [(d, data["basis"].get(d, {}).get("close", 0)) for d in all_dates if data["basis"].get(d)]

        if channel_oi:
            max_oi = max(channel_oi, key=lambda x: x[1])
            min_oi = min(channel_oi, key=lambda x: x[1])
            oi_range_pct = (max_oi[1] - min_oi[1]) / min_oi[1] * 100 if min_oi[1] > 0 else 0
            print(f"\n  OI Range: ${min_oi[1]/1e9:.1f}B ({min_oi[0]}) ~ ${max_oi[1]/1e9:.1f}B ({max_oi[0]}) | Swing: {oi_range_pct:.1f}%")

        if channel_funding:
            max_f = max(channel_funding, key=lambda x: x[1])
            min_f = min(channel_funding, key=lambda x: x[1])
            avg_f = sum(x[1] for x in channel_funding) / len(channel_funding)
            pos_days = sum(1 for _, v in channel_funding if v > 0)
            neg_days = sum(1 for _, v in channel_funding if v < 0)
            print(f"  Funding: avg={avg_f:.4f}% | max={max_f[1]:.4f}% ({max_f[0]}) | min={min_f[1]:.4f}% ({min_f[0]}) | +days:{pos_days} -days:{neg_days}")

        if channel_ls:
            max_ls = max(channel_ls, key=lambda x: x[1])
            min_ls = min(channel_ls, key=lambda x: x[1])
            avg_ls = sum(x[1] for x in channel_ls) / len(channel_ls)
            above_1 = sum(1 for _, v in channel_ls if v > 1.0)
            total_ls = len(channel_ls)
            # L/S trend: first half avg vs second half avg
            mid = len(channel_ls) // 2
            first_half = sum(x[1] for x in channel_ls[:mid]) / mid if mid > 0 else 0
            second_half = sum(x[1] for x in channel_ls[mid:]) / (len(channel_ls) - mid) if (len(channel_ls) - mid) > 0 else 0
            ls_trend = "RISING" if second_half > first_half else "FALLING"
            print(f"  L/S: avg={avg_ls:.2f} | max={max_ls[1]:.2f} ({max_ls[0]}) | min={min_ls[1]:.2f} ({min_ls[0]}) | >1.0: {above_1}/{total_ls} days | Trend: {ls_trend} ({first_half:.2f}->{second_half:.2f})")

        if channel_cvd_vals:
            start_cvd = channel_cvd_vals[0][1]
            end_cvd = channel_cvd_vals[-1][1]
            cvd_change = end_cvd - start_cvd
            print(f"  CVD: start={start_cvd/1e9:.2f}B -> end={end_cvd/1e9:.2f}B | change={cvd_change/1e9:+.2f}B")

        if channel_basis:
            avg_basis = sum(x[1] for x in channel_basis) / len(channel_basis)
            max_basis = max(channel_basis, key=lambda x: x[1])
            min_basis = min(channel_basis, key=lambda x: x[1])
            print(f"  Basis: avg={avg_basis:.4f} | max={max_basis[1]:.4f} ({max_basis[0]}) | min={min_basis[1]:.4f} ({min_basis[0]})")

        # Per-event detail
        print()
        cols = f"  {'Date':<12} {'Price':>8} {'Type':<6} {'Note':<14} {'OI($B)':>8} {'OIchg%':>8} {'Fund%':>9} {'L/S':>6} {'L%':>6} {'LongLiq$M':>10} {'ShortLiq$M':>10} {'LiqDom':>7} {'CVD_B':>8} {'Basis':>7} {'TakerBR':>8}"
        print(cols)
        print("  " + "-" * 136)

        prev_oi = None
        for date, price, etype, note in events:
            oi_entry = data["oi"].get(date, {})
            oi_val = oi_entry.get("close", 0)
            fund_entry = data["funding"].get(date, {})
            fund_val = fund_entry.get("close", 0) if fund_entry else 0
            ls_entry = data["ls"].get(date, {})
            ls_val = ls_entry.get("ratio", 0) if ls_entry else 0
            long_pct = ls_entry.get("long_pct", 0) if ls_entry else 0
            liq_entry = data["liq"].get(date, {"long": 0, "short": 0})
            long_liq = liq_entry["long"] / 1e6
            short_liq = liq_entry["short"] / 1e6
            liq_dom = "LONG" if long_liq > short_liq * 1.2 else ("SHORT" if short_liq > long_liq * 1.2 else "EVEN")
            cvd_entry = data["cvd"].get(date, {})
            cvd_val = cvd_entry.get("cvd", 0) if cvd_entry else 0
            basis_entry = data["basis"].get(date, {})
            basis_val = basis_entry.get("close", 0) if basis_entry else 0
            taker_entry = data["taker"].get(date, {})
            taker_buy = taker_entry.get("buy", 0) if taker_entry else 0
            taker_sell = taker_entry.get("sell", 0) if taker_entry else 0
            taker_ratio = taker_buy / taker_sell if taker_sell > 0 else 0

            oi_chg = ""
            if prev_oi and prev_oi > 0 and oi_val > 0:
                pct = (oi_val - prev_oi) / prev_oi * 100
                oi_chg = f"{pct:+.1f}%"

            oi_str = f"{oi_val/1e9:.1f}B" if oi_val > 0 else "-"
            fund_str = f"{fund_val:.4f}" if fund_entry else "-"
            ls_str = f"{ls_val:.2f}" if ls_entry else "-"
            lpct_str = f"{long_pct:.1f}" if ls_entry else "-"
            ll_str = f"{long_liq:.1f}M" if liq_entry["long"] > 0 else "-"
            sl_str = f"{short_liq:.1f}M" if liq_entry["short"] > 0 else "-"
            cvd_str = f"{cvd_val/1e9:.2f}B" if cvd_entry else "-"
            basis_str = f"{basis_val:.4f}" if basis_entry else "-"
            taker_str = f"{taker_ratio:.3f}" if taker_ratio > 0 else "-"

            tag = f"{etype:<6}"
            note_str = f"{note:<14}" if note else f"{'':14}"

            print(f"  {date:<12} {price:>8} {tag} {note_str} {oi_str:>8} {oi_chg:>8} {fund_str:>9} {ls_str:>6} {lpct_str:>6} {ll_str:>10} {sl_str:>10} {liq_dom:>7} {cvd_str:>8} {basis_str:>7} {taker_str:>8}")

            if oi_val > 0:
                prev_oi = oi_val

            # Collect stats by type
            row = {
                "date": date, "price": price, "channel": ch_name,
                "oi": oi_val, "funding": fund_val, "ls": ls_val, "long_pct": long_pct,
                "long_liq": long_liq, "short_liq": short_liq,
                "liq_ratio": long_liq / short_liq if short_liq > 0.001 else 0,
                "cvd": cvd_val, "basis": basis_val, "taker_ratio": taker_ratio,
                "note": note,
            }
            if etype == "high":
                ch_stats["highs"].append(row)
            elif etype == "low":
                if "broke" in note:
                    ch_stats["breaks"].append(row)
                else:
                    ch_stats["lows"].append(row)
            elif etype == "mid":
                ch_stats["mids"].append(row)

        all_channel_stats[ch_name] = ch_stats

    # ══════════════════════════════════════════════════════════════
    # CROSS-CHANNEL COMPARISON
    # ══════════════════════════════════════════════════════════════
    print()
    print()
    print("=" * 140)
    print("CROSS-CHANNEL COMPARISON — AVERAGES BY EVENT TYPE")
    print("=" * 140)

    for etype_label, etype_key in [("HIGHS", "highs"), ("LOWS", "lows"), ("MIDS", "mids"), ("BREAKDOWNS", "breaks")]:
        print(f"\n{'─' * 100}")
        print(f"  {etype_label}")
        print(f"{'─' * 100}")
        print(f"  {'Channel':<8} {'Count':>5} {'AvgFund%':>10} {'AvgL/S':>8} {'AvgLong%':>9} {'AvgLiqR':>8} {'AvgBasis':>9} {'AvgTkrR':>8} {'Notes'}")
        print(f"  {'-'*95}")

        for ch_name in CHANNELS:
            rows = all_channel_stats[ch_name][etype_key]
            if not rows:
                continue
            n = len(rows)
            fund_vals = [r["funding"] for r in rows if r["funding"] != 0]
            ls_vals = [r["ls"] for r in rows if r["ls"] > 0]
            lpct_vals = [r["long_pct"] for r in rows if r["long_pct"] > 0]
            liq_vals = [r["liq_ratio"] for r in rows]
            basis_vals = [r["basis"] for r in rows if r["basis"] != 0]
            taker_vals = [r["taker_ratio"] for r in rows if r["taker_ratio"] > 0]

            avg_f = sum(fund_vals) / len(fund_vals) if fund_vals else 0
            avg_ls = sum(ls_vals) / len(ls_vals) if ls_vals else 0
            avg_lpct = sum(lpct_vals) / len(lpct_vals) if lpct_vals else 0
            avg_liq = sum(liq_vals) / len(liq_vals) if liq_vals else 0
            avg_basis = sum(basis_vals) / len(basis_vals) if basis_vals else 0
            avg_taker = sum(taker_vals) / len(taker_vals) if taker_vals else 0

            notes = ", ".join(r["note"] for r in rows if r["note"])
            f_str = f"{avg_f:+.4f}" if fund_vals else "-"
            ls_str = f"{avg_ls:.2f}" if ls_vals else "-"
            lp_str = f"{avg_lpct:.1f}%" if lpct_vals else "-"
            lr_str = f"{avg_liq:.2f}" if liq_vals else "-"
            b_str = f"{avg_basis:.4f}" if basis_vals else "-"
            t_str = f"{avg_taker:.3f}" if taker_vals else "-"

            print(f"  {ch_name:<8} {n:>5} {f_str:>10} {ls_str:>8} {lp_str:>9} {lr_str:>8} {b_str:>9} {t_str:>8}  {notes}")

    # ══════════════════════════════════════════════════════════════
    # KEY METRICS AT BREAKDOWN — SIDE BY SIDE
    # ══════════════════════════════════════════════════════════════
    print()
    print()
    print("=" * 140)
    print("BREAKDOWN POINT COMPARISON — ALL INDICATORS SIDE BY SIDE")
    print("=" * 140)

    # For each channel, find the breakdown event and the last high before it
    for ch_name, ch_info in CHANNELS.items():
        events = ch_info["events"]
        broke_event = None
        last_high_event = None
        peak_high_event = None
        for date, price, etype, note in events:
            if etype == "high":
                last_high_event = (date, price, note)
                if peak_high_event is None or price > peak_high_event[1]:
                    peak_high_event = (date, price, note)
            if "broke" in note:
                broke_event = (date, price, note)

        if not broke_event or not last_high_event:
            continue

        hd, hp, hn = last_high_event
        bd, bp, bn = broke_event
        pd_, pp, pn = peak_high_event

        # Compute changes
        h_oi = data["oi"].get(hd, {}).get("close", 0)
        b_oi = data["oi"].get(bd, {}).get("close", 0)
        oi_chg = (b_oi - h_oi) / h_oi * 100 if h_oi > 0 else 0

        h_fund = data["funding"].get(hd, {}).get("close", 0)
        b_fund = data["funding"].get(bd, {}).get("close", 0)

        h_ls = data["ls"].get(hd, {}).get("ratio", 0)
        b_ls = data["ls"].get(bd, {}).get("ratio", 0)

        b_liq = data["liq"].get(bd, {"long": 0, "short": 0})
        b_liq_ratio = b_liq["long"] / b_liq["short"] if b_liq["short"] > 0.001 else 0

        # Channel-wide funding peak
        first_d = events[0][0]
        dt = datetime.strptime(first_d, "%Y-%m-%d")
        end_dt = datetime.strptime(bd, "%Y-%m-%d")
        max_fund = -999
        while dt <= end_dt:
            ds = dt.strftime("%Y-%m-%d")
            f = data["funding"].get(ds, {}).get("close")
            if f is not None and f > max_fund:
                max_fund = f
            dt += timedelta(days=1)

        fund_vs_peak = b_fund / max_fund * 100 if max_fund > 0.001 else 0

        # CVD change
        h_cvd = data["cvd"].get(hd, {}).get("cvd", 0)
        b_cvd = data["cvd"].get(bd, {}).get("cvd", 0)
        cvd_chg = (b_cvd - h_cvd) / 1e9 if h_cvd else 0

        # Basis
        h_basis = data["basis"].get(hd, {}).get("close", 0)
        b_basis = data["basis"].get(bd, {}).get("close", 0)

        # Taker
        b_taker = data["taker"].get(bd, {})
        b_taker_ratio = b_taker.get("buy", 0) / b_taker.get("sell", 1) if b_taker.get("sell", 0) > 0 else 0

        print(f"\n  Channel {ch_name} ({ch_info['period']})")
        print(f"    Last High: {hd} ${hp:,}  ->  Breakdown: {bd} ${bp:,}  (price chg: {(bp-hp)/hp*100:+.1f}%)")
        print(f"    OI:          ${h_oi/1e9:.1f}B -> ${b_oi/1e9:.1f}B ({oi_chg:+.1f}%)")
        print(f"    Funding:     {h_fund:.4f}% -> {b_fund:.4f}% (vs channel peak {max_fund:.4f}%: {fund_vs_peak:.0f}%)")
        print(f"    L/S:         {h_ls:.2f} -> {b_ls:.2f}")
        print(f"    Breakdown Liq: Long=${b_liq['long']/1e6:.1f}M Short=${b_liq['short']/1e6:.1f}M Ratio={b_liq_ratio:.2f}x")
        if b_cvd or h_cvd:
            print(f"    CVD change:  {cvd_chg:+.2f}B")
        if b_basis:
            print(f"    Basis:       {h_basis:.4f} -> {b_basis:.4f}")
        if b_taker_ratio:
            print(f"    Taker B/S:   {b_taker_ratio:.3f}")

    # ══════════════════════════════════════════════════════════════
    # PATTERN MATRIX — each indicator at each event type per channel
    # ══════════════════════════════════════════════════════════════
    print()
    print()
    print("=" * 140)
    print("INDICATOR PATTERN MATRIX — Avg at Highs vs Avg at Lows vs Breakdown")
    print("=" * 140)

    indicators = [
        ("Funding%", "funding"),
        ("L/S Ratio", "ls"),
        ("Long%", "long_pct"),
        ("Liq Ratio (L/S)", "liq_ratio"),
    ]

    for ind_label, ind_key in indicators:
        print(f"\n  {ind_label}:")
        print(f"  {'Channel':<8} {'Avg@Highs':>12} {'Avg@Lows':>12} {'@Breakdown':>12} {'Hi->Brk':>12} {'Lo->Brk':>12}")
        print(f"  {'-'*70}")

        for ch_name in CHANNELS:
            stats = all_channel_stats[ch_name]
            h_vals = [r[ind_key] for r in stats["highs"] if r[ind_key] != 0]
            l_vals = [r[ind_key] for r in stats["lows"] if r[ind_key] != 0]
            b_vals = [r[ind_key] for r in stats["breaks"] if r[ind_key] != 0]

            h_avg = sum(h_vals) / len(h_vals) if h_vals else None
            l_avg = sum(l_vals) / len(l_vals) if l_vals else None
            b_avg = sum(b_vals) / len(b_vals) if b_vals else None

            h_str = f"{h_avg:.4f}" if h_avg is not None else "-"
            l_str = f"{l_avg:.4f}" if l_avg is not None else "-"
            b_str = f"{b_avg:.4f}" if b_avg is not None else "-"

            hb_str = "-"
            lb_str = "-"
            if h_avg is not None and b_avg is not None:
                if ind_key == "funding":
                    hb_str = f"{b_avg - h_avg:+.4f}"
                else:
                    hb_str = f"{(b_avg/h_avg - 1)*100:+.1f}%" if h_avg != 0 else "-"
            if l_avg is not None and b_avg is not None:
                if ind_key == "funding":
                    lb_str = f"{b_avg - l_avg:+.4f}"
                else:
                    lb_str = f"{(b_avg/l_avg - 1)*100:+.1f}%" if l_avg != 0 else "-"

            print(f"  {ch_name:<8} {h_str:>12} {l_str:>12} {b_str:>12} {hb_str:>12} {lb_str:>12}")

    # Save raw data as JSON for further analysis
    output = {}
    for ch_name, stats in all_channel_stats.items():
        output[ch_name] = {}
        for key, rows in stats.items():
            output[ch_name][key] = rows
    with open("channel_analysis_raw.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n\nRaw data saved to channel_analysis_raw.json")


if __name__ == "__main__":
    main()
