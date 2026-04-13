#!/usr/bin/env python3
"""Every HIGH and LOW across all 6 channels — check each indicator condition, count matches."""
import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

from adapters.binance_futures import BinanceFuturesAdapter


def compute_rsi(closes, period):
    rsi = [0.0] * len(closes)
    if len(closes) < period + 1:
        return rsi
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        if i > period:
            ag = (ag * (period - 1) + gains[i]) / period
            al = (al * (period - 1) + losses[i]) / period
        rsi[i + 1] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return rsi


def load_csv(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append(r)
    except FileNotFoundError:
        pass
    return rows


def load_all():
    d = {}
    oi = {}
    for r in load_csv("src/data/coinglass_oi_1d.csv"):
        oi[r["timestamp"][:10]] = float(r["close"])
    d["oi"] = oi

    fund = {}
    for r in load_csv("src/data/coinglass_funding_1d.csv"):
        fund[r["timestamp"][:10]] = float(r["close"]) * 100
    d["fund"] = fund

    ls = {}
    for r in load_csv("src/data/coinglass_top_ls_1d.csv"):
        ls[r["timestamp"][:10]] = float(r["ratio"])
    d["ls"] = ls

    liq: dict[str, dict] = {}
    for r in load_csv("src/data/coinglass_liquidation_4h.csv"):
        dt = r["timestamp"][:10]
        if dt not in liq:
            liq[dt] = {"l": 0.0, "s": 0.0}
        liq[dt]["l"] += float(r["long_usd"])
        liq[dt]["s"] += float(r["short_usd"])
    d["liq"] = liq

    cvd = {}
    for r in load_csv("src/data/coinglass_cvd_1d.csv"):
        cvd[r["timestamp"][:10]] = float(r["cvd"])
    d["cvd"] = cvd

    basis = {}
    for r in load_csv("src/data/coinglass_basis_1d.csv"):
        basis[r["timestamp"][:10]] = float(r["close_basis"])
    d["basis"] = basis

    taker: dict[str, dict] = {}
    for r in load_csv("src/data/coinglass_taker_volume_4h.csv"):
        dt = r["timestamp"][:10]
        if dt not in taker:
            taker[dt] = {"b": 0.0, "s": 0.0}
        taker[dt]["b"] += float(r["buy_usd"])
        taker[dt]["s"] += float(r["sell_usd"])
    d["taker"] = taker

    return d


CHANNELS = {
    "C": [
        ("2022-01-24", 33000, "LOW"), ("2022-02-10", 45821, "HIGH"),
        ("2022-02-24", 34300, "LOW"), ("2022-03-02", 45400, "HIGH"),
        ("2022-03-28", 48189, "HIGH"), ("2022-04-11", 39200, "LOW"),
        ("2022-04-28", 37600, "BROKE"),
    ],
    "A": [
        ("2022-05-01", 38500, "HIGH"), ("2022-05-05", 36000, "LOW"),
        ("2022-05-09", 34000, "LOW"), ("2022-05-12", 28800, "BROKE"),
    ],
    "B": [
        ("2022-06-18", 17570, "LOW"), ("2022-06-26", 21888, "HIGH"),
        ("2022-06-30", 18800, "LOW"), ("2022-07-08", 22400, "HIGH"),
        ("2022-07-13", 19200, "LOW"), ("2022-07-20", 24200, "HIGH"),
        ("2022-07-26", 20700, "LOW"), ("2022-08-10", 24900, "HIGH"),
        ("2022-08-19", 21300, "BROKE"),
    ],
    "D": [
        ("2025-04-09", 75000, "LOW"), ("2025-05-12", 104000, "HIGH"),
        ("2025-06-06", 98700, "LOW"), ("2025-06-13", 106000, "HIGH"),
        ("2025-06-20", 101500, "LOW"), ("2025-07-03", 109000, "HIGH"),
        ("2025-08-18", 107000, "HIGH"), ("2025-09-01", 109000, "HIGH"),
        ("2025-10-02", 99000, "BROKE"),
    ],
    "E": [
        ("2025-11-21", 80600, "LOW"), ("2025-11-28", 93036, "HIGH"),
        ("2025-12-01", 83757, "LOW"), ("2025-12-03", 94164, "HIGH"),
        ("2025-12-09", 94571, "HIGH"), ("2025-12-18", 85426, "LOW"),
        ("2025-12-29", 86673, "LOW"), ("2026-01-14", 97879, "HIGH"),
        ("2026-01-20", 87695, "BROKE"),
    ],
    "F": [
        ("2026-02-05", 62749, "LOW"), ("2026-02-06", 71645, "HIGH"),
        ("2026-02-24", 64023, "LOW"), ("2026-03-04", 74041, "HIGH"),
        ("2026-03-08", 65572, "LOW"), ("2026-03-16", 74847, "HIGH"),
        ("2026-03-22", 67305, "LOW"), ("2026-03-27", 65470, "BROKE"),
    ],
}


def main():
    cg = load_all()

    print("Fetching Binance daily bars...")
    adapter = BinanceFuturesAdapter()
    bars = adapter.fetch_range("BTCUSDT", "1d", datetime(2022, 1, 1), datetime(2026, 4, 6))
    print(f"Got {len(bars)} bars\n")

    closes = [b.close for b in bars]
    date_idx = {b.timestamp.strftime("%Y-%m-%d"): i for i, b in enumerate(bars)}
    rsi3 = compute_rsi(closes, 3)
    rsi7 = compute_rsi(closes, 7)
    rsi14 = compute_rsi(closes, 14)

    def find_idx(ds):
        if ds in date_idx:
            return date_idx[ds]
        dt = datetime.strptime(ds, "%Y-%m-%d")
        for off in range(-2, 3):
            alt = (dt + timedelta(days=off)).strftime("%Y-%m-%d")
            if alt in date_idx:
                return date_idx[alt]
        return None

    # Compute OI % change from previous event in same channel
    def get_oi_changes():
        result = {}
        for ch, events in CHANNELS.items():
            prev_oi = None
            for date, price, etype in events:
                oi = cg["oi"].get(date, 0)
                pct = None
                if prev_oi and prev_oi > 0 and oi > 0:
                    pct = (oi - prev_oi) / prev_oi * 100
                result[(ch, date)] = pct
                if oi > 0:
                    prev_oi = oi
        return result

    oi_changes = get_oi_changes()

    # Compute CVD change from previous event
    def get_cvd_changes():
        result = {}
        for ch, events in CHANNELS.items():
            prev_cvd = None
            for date, price, etype in events:
                cvd = cg["cvd"].get(date, 0)
                chg = None
                if prev_cvd is not None and cvd != 0:
                    chg = cvd - prev_cvd
                result[(ch, date)] = chg
                if cvd != 0:
                    prev_cvd = cvd
        return result

    cvd_changes = get_cvd_changes()

    # ══════════════════════════════════════════════════════════
    # HIGHS TABLE
    # ══════════════════════════════════════════════════════════
    print("=" * 180)
    print("ALL HIGHS — Every indicator + condition check")
    print("=" * 180)

    # Define HIGH conditions to check
    high_conditions = [
        ("R3>65", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r3 > 65),
        ("R3>70", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r3 > 70),
        ("R7>55", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r7 > 55),
        ("R7>60", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r7 > 60),
        ("R14>50", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r14 > 50),
        ("R14>55", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r14 > 55),
        ("Fund>0", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: f > 0),
        ("L/S>1.0", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: ls > 1.0 if ls > 0 else None),
        ("L/S>1.1", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: ls > 1.1 if ls > 0 else None),
        ("LiqR<1", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: lr < 1.0 if lr is not None else None),
        ("OI up", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: oi_chg > 0 if oi_chg is not None else None),
        ("OI>+5%", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: oi_chg > 5 if oi_chg is not None else None),
        ("CVD up", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: cvd_chg > 0 if cvd_chg is not None else None),
        ("Tkr>1.0", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: tkr > 1.0 if tkr > 0 else None),
        ("Bas>0.04", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: bas > 0.04 if bas > 0 else None),
    ]

    cond_names_h = [c[0] for c in high_conditions]
    # Header
    hdr = f"  {'Ch':<3} {'Date':<11} {'$':>7} {'R3':>5} {'R7':>5} {'R14':>4} {'Fund%':>7} {'L/S':>5} {'LiqR':>5} {'OI%':>6} {'CVD':>7} {'TkrBS':>5} {'Bas':>6}"
    for cn in cond_names_h:
        hdr += f" {cn:>8}"
    hdr += "  Score"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    high_totals = {cn: {"yes": 0, "no": 0, "na": 0} for cn in cond_names_h}
    high_scores = []

    for ch, events in CHANNELS.items():
        for date, price, etype in events:
            if etype != "HIGH":
                continue
            idx = find_idx(date)
            r3 = rsi3[idx] if idx else 0
            r7 = rsi7[idx] if idx else 0
            r14 = rsi14[idx] if idx else 0
            f = cg["fund"].get(date, 0)
            ls = cg["ls"].get(date, 0)
            lq = cg["liq"].get(date, {"l": 0, "s": 0})
            ll, sl = lq["l"] / 1e6, lq["s"] / 1e6
            lr = ll / sl if sl > 0.001 else None
            oi_chg = oi_changes.get((ch, date))
            cvd_chg = cvd_changes.get((ch, date))
            tk = cg["taker"].get(date, {"b": 0, "s": 0})
            tkr = tk["b"] / tk["s"] if tk["s"] > 0 else 0
            bas = cg["basis"].get(date, 0)

            oi_s = f"{oi_chg:+.1f}" if oi_chg is not None else "-"
            cvd_s = f"{cvd_chg/1e9:+.1f}B" if cvd_chg is not None else "-"
            lr_s = f"{lr:.2f}" if lr is not None else "-"
            tkr_s = f"{tkr:.3f}" if tkr > 0 else "-"
            bas_s = f"{bas:.4f}" if bas > 0 else "-"

            line = f"  {ch:<3} {date:<11} {price:>7} {r3:>5.1f} {r7:>5.1f} {r14:>4.1f} {f:>+7.4f} {ls:>5.2f} {lr_s:>5} {oi_s:>6} {cvd_s:>7} {tkr_s:>5} {bas_s:>6}"

            score = 0
            total_applicable = 0
            for cn, fn in high_conditions:
                result = fn(r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas)
                if result is None:
                    line += f" {'n/a':>8}"
                    high_totals[cn]["na"] += 1
                elif result:
                    line += f" {'Y':>8}"
                    high_totals[cn]["yes"] += 1
                    score += 1
                    total_applicable += 1
                else:
                    line += f" {'-':>8}"
                    high_totals[cn]["no"] += 1
                    total_applicable += 1

            pct = score / total_applicable * 100 if total_applicable > 0 else 0
            line += f"  {score}/{total_applicable} ({pct:.0f}%)"
            high_scores.append(pct)
            print(line)

    # Totals
    print()
    print("  HIT RATE:")
    line = f"  {'':3} {'':11} {'':>7} {'':>5} {'':>5} {'':>4} {'':>7} {'':>5} {'':>5} {'':>6} {'':>7} {'':>5} {'':>6}"
    for cn in cond_names_h:
        t = high_totals[cn]
        total = t["yes"] + t["no"]
        rate = t["yes"] / total * 100 if total > 0 else 0
        line += f" {t['yes']}/{total:>2}={rate:>3.0f}%"
    print(line)
    print(f"\n  Average score across all highs: {sum(high_scores)/len(high_scores):.0f}%")

    # ══════════════════════════════════════════════════════════
    # LOWS TABLE
    # ══════════════════════════════════════════════════════════
    print()
    print("=" * 180)
    print("ALL LOWS — Every indicator + condition check")
    print("=" * 180)

    low_conditions = [
        ("R3<25", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r3 < 25),
        ("R3<30", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r3 < 30),
        ("R3<35", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r3 < 35),
        ("R7<30", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r7 < 30),
        ("R7<35", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r7 < 35),
        ("R7<40", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r7 < 40),
        ("R14<40", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r14 < 40),
        ("R14<45", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r14 < 45),
        ("Fund<0.3", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: f < 0.3),
        ("L/S>1.0", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: ls > 1.0 if ls > 0 else None),
        ("LiqR>1.0", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: lr > 1.0 if lr is not None else None),
        ("LiqR>1.5", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: lr > 1.5 if lr is not None else None),
        ("OI down", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: oi_chg < 0 if oi_chg is not None else None),
        ("OI<-5%", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: oi_chg < -5 if oi_chg is not None else None),
        ("CVD dn", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: cvd_chg < 0 if cvd_chg is not None else None),
        ("Tkr<1.0", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: tkr < 1.0 if tkr > 0 else None),
        ("Tkr<0.97", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: tkr < 0.97 if tkr > 0 else None),
    ]

    cond_names_l = [c[0] for c in low_conditions]
    hdr = f"  {'Ch':<3} {'Date':<11} {'$':>7} {'R3':>5} {'R7':>5} {'R14':>4} {'Fund%':>7} {'L/S':>5} {'LiqR':>5} {'OI%':>6} {'CVD':>7} {'TkrBS':>5} {'Bas':>6}"
    for cn in cond_names_l:
        hdr += f" {cn:>8}"
    hdr += "  Score"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    low_totals = {cn: {"yes": 0, "no": 0, "na": 0} for cn in cond_names_l}
    low_scores = []

    for ch, events in CHANNELS.items():
        for date, price, etype in events:
            if etype != "LOW":
                continue
            idx = find_idx(date)
            r3 = rsi3[idx] if idx else 0
            r7 = rsi7[idx] if idx else 0
            r14 = rsi14[idx] if idx else 0
            f = cg["fund"].get(date, 0)
            ls = cg["ls"].get(date, 0)
            lq = cg["liq"].get(date, {"l": 0, "s": 0})
            ll, sl = lq["l"] / 1e6, lq["s"] / 1e6
            lr = ll / sl if sl > 0.001 else None
            oi_chg = oi_changes.get((ch, date))
            cvd_chg = cvd_changes.get((ch, date))
            tk = cg["taker"].get(date, {"b": 0, "s": 0})
            tkr = tk["b"] / tk["s"] if tk["s"] > 0 else 0
            bas = cg["basis"].get(date, 0)

            oi_s = f"{oi_chg:+.1f}" if oi_chg is not None else "-"
            cvd_s = f"{cvd_chg/1e9:+.1f}B" if cvd_chg is not None else "-"
            lr_s = f"{lr:.2f}" if lr is not None else "-"
            tkr_s = f"{tkr:.3f}" if tkr > 0 else "-"
            bas_s = f"{bas:.4f}" if bas > 0 else "-"

            line = f"  {ch:<3} {date:<11} {price:>7} {r3:>5.1f} {r7:>5.1f} {r14:>4.1f} {f:>+7.4f} {ls:>5.2f} {lr_s:>5} {oi_s:>6} {cvd_s:>7} {tkr_s:>5} {bas_s:>6}"

            score = 0
            total_applicable = 0
            for cn, fn in low_conditions:
                result = fn(r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas)
                if result is None:
                    line += f" {'n/a':>8}"
                    low_totals[cn]["na"] += 1
                elif result:
                    line += f" {'Y':>8}"
                    low_totals[cn]["yes"] += 1
                    score += 1
                    total_applicable += 1
                else:
                    line += f" {'-':>8}"
                    low_totals[cn]["no"] += 1
                    total_applicable += 1

            pct = score / total_applicable * 100 if total_applicable > 0 else 0
            low_scores.append(pct)
            line += f"  {score}/{total_applicable} ({pct:.0f}%)"
            print(line)

    print()
    print("  HIT RATE:")
    line = f"  {'':3} {'':11} {'':>7} {'':>5} {'':>5} {'':>4} {'':>7} {'':>5} {'':>5} {'':>6} {'':>7} {'':>5} {'':>6}"
    for cn in cond_names_l:
        t = low_totals[cn]
        total = t["yes"] + t["no"]
        rate = t["yes"] / total * 100 if total > 0 else 0
        line += f" {t['yes']}/{total:>2}={rate:>3.0f}%"
    print(line)
    print(f"\n  Average score across all lows: {sum(low_scores)/len(low_scores):.0f}%")

    # ══════════════════════════════════════════════════════════
    # BREAKDOWNS TABLE
    # ══════════════════════════════════════════════════════════
    print()
    print("=" * 180)
    print("ALL BREAKDOWNS — Every indicator + condition check")
    print("=" * 180)

    broke_conditions = [
        ("R3<20", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r3 < 20),
        ("R3<30", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r3 < 30),
        ("R7<30", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r7 < 30),
        ("R7<40", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r7 < 40),
        ("R14<42", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: r14 < 42),
        ("L/S>1.0", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: ls > 1.0 if ls > 0 else None),
        ("LiqR>1.5", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: lr > 1.5 if lr is not None else None),
        ("LiqR>3.0", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: lr > 3.0 if lr is not None else None),
        ("OI down", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: oi_chg < 0 if oi_chg is not None else None),
        ("OI<-5%", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: oi_chg < -5 if oi_chg is not None else None),
        ("CVD dn", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: cvd_chg < 0 if cvd_chg is not None else None),
        ("Tkr<0.90", lambda r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas: tkr < 0.90 if tkr > 0 else None),
    ]

    cond_names_b = [c[0] for c in broke_conditions]
    hdr = f"  {'Ch':<3} {'Date':<11} {'$':>7} {'R3':>5} {'R7':>5} {'R14':>4} {'Fund%':>7} {'L/S':>5} {'LiqR':>5} {'OI%':>6} {'CVD':>7} {'TkrBS':>5}"
    for cn in cond_names_b:
        hdr += f" {cn:>8}"
    hdr += "  Score"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    broke_totals = {cn: {"yes": 0, "no": 0, "na": 0} for cn in cond_names_b}

    for ch, events in CHANNELS.items():
        for date, price, etype in events:
            if etype != "BROKE":
                continue
            idx = find_idx(date)
            r3 = rsi3[idx] if idx else 0
            r7 = rsi7[idx] if idx else 0
            r14 = rsi14[idx] if idx else 0
            f = cg["fund"].get(date, 0)
            ls = cg["ls"].get(date, 0)
            lq = cg["liq"].get(date, {"l": 0, "s": 0})
            ll, sl = lq["l"] / 1e6, lq["s"] / 1e6
            lr = ll / sl if sl > 0.001 else None
            oi_chg = oi_changes.get((ch, date))
            cvd_chg = cvd_changes.get((ch, date))
            tk = cg["taker"].get(date, {"b": 0, "s": 0})
            tkr = tk["b"] / tk["s"] if tk["s"] > 0 else 0

            oi_s = f"{oi_chg:+.1f}" if oi_chg is not None else "-"
            cvd_s = f"{cvd_chg/1e9:+.1f}B" if cvd_chg is not None else "-"
            lr_s = f"{lr:.2f}" if lr is not None else "-"
            tkr_s = f"{tkr:.3f}" if tkr > 0 else "-"

            line = f"  {ch:<3} {date:<11} {price:>7} {r3:>5.1f} {r7:>5.1f} {r14:>4.1f} {f:>+7.4f} {ls:>5.2f} {lr_s:>5} {oi_s:>6} {cvd_s:>7} {tkr_s:>5}"

            score = 0
            total_applicable = 0
            for cn, fn in broke_conditions:
                result = fn(r3, r7, r14, f, ls, lr, oi_chg, cvd_chg, tkr, bas)
                if result is None:
                    line += f" {'n/a':>8}"
                    broke_totals[cn]["na"] += 1
                elif result:
                    line += f" {'Y':>8}"
                    broke_totals[cn]["yes"] += 1
                    score += 1
                    total_applicable += 1
                else:
                    line += f" {'-':>8}"
                    broke_totals[cn]["no"] += 1
                    total_applicable += 1

            pct = score / total_applicable * 100 if total_applicable > 0 else 0
            line += f"  {score}/{total_applicable} ({pct:.0f}%)"
            print(line)

    print()
    print("  HIT RATE:")
    line = f"  {'':3} {'':11} {'':>7} {'':>5} {'':>5} {'':>4} {'':>7} {'':>5} {'':>5} {'':>6} {'':>7} {'':>5}"
    for cn in cond_names_b:
        t = broke_totals[cn]
        total = t["yes"] + t["no"]
        rate = t["yes"] / total * 100 if total > 0 else 0
        line += f" {t['yes']}/{total:>2}={rate:>3.0f}%"
    print(line)

    # ══════════════════════════════════════════════════════════
    # FINAL SUMMARY
    # ══════════════════════════════════════════════════════════
    print()
    print("=" * 100)
    print("CONDITION HIT RATE SUMMARY")
    print("=" * 100)

    print("\n  HIGH conditions (for SHORT entry):")
    print(f"  {'Condition':<15} {'Hit':>5} {'Total':>5} {'Rate':>6} {'Usable?'}")
    print(f"  {'-'*45}")
    for cn in cond_names_h:
        t = high_totals[cn]
        total = t["yes"] + t["no"]
        rate = t["yes"] / total * 100 if total > 0 else 0
        usable = "***" if rate >= 70 else ("**" if rate >= 60 else ("*" if rate >= 50 else ""))
        print(f"  {cn:<15} {t['yes']:>5} {total:>5} {rate:>5.0f}% {usable}")

    print("\n  LOW conditions (for LONG entry):")
    print(f"  {'Condition':<15} {'Hit':>5} {'Total':>5} {'Rate':>6} {'Usable?'}")
    print(f"  {'-'*45}")
    for cn in cond_names_l:
        t = low_totals[cn]
        total = t["yes"] + t["no"]
        rate = t["yes"] / total * 100 if total > 0 else 0
        usable = "***" if rate >= 70 else ("**" if rate >= 60 else ("*" if rate >= 50 else ""))
        print(f"  {cn:<15} {t['yes']:>5} {total:>5} {rate:>5.0f}% {usable}")

    print("\n  BREAKDOWN conditions:")
    print(f"  {'Condition':<15} {'Hit':>5} {'Total':>5} {'Rate':>6} {'Usable?'}")
    print(f"  {'-'*45}")
    for cn in cond_names_b:
        t = broke_totals[cn]
        total = t["yes"] + t["no"]
        rate = t["yes"] / total * 100 if total > 0 else 0
        usable = "***" if rate >= 70 else ("**" if rate >= 60 else ("*" if rate >= 50 else ""))
        print(f"  {cn:<15} {t['yes']:>5} {total:>5} {rate:>5.0f}% {usable}")


if __name__ == "__main__":
    main()
