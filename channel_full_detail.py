#!/usr/bin/env python3
"""Full detail: every high, low, mid, breakdown — ALL indicators + RSI."""
import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

from adapters.binance_futures import BinanceFuturesAdapter


# ── RSI ──
def compute_rsi(closes: list[float], period: int) -> list[float]:
    rsi = [0.0] * len(closes)
    if len(closes) < period + 1:
        return rsi
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rsi[i + 1] = 100 - 100 / (1 + avg_gain / avg_loss)
    return rsi


# ── Load Coinglass ──
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
    "C": {
        "period": "Jan-Apr 2022",
        "events": [
            ("2022-01-24", 33000, "LOW", "start"),
            ("2022-02-10", 45821, "HIGH", ""),
            ("2022-02-24", 34300, "LOW", ""),
            ("2022-03-02", 45400, "HIGH", ""),
            ("2022-03-09", 37000, "MID", "retest"),
            ("2022-03-28", 48189, "HIGH", "peak"),
            ("2022-04-11", 39200, "LOW", ""),
            ("2022-04-18", 41500, "MID", ""),
            ("2022-04-28", 37600, "BROKE", ""),
        ],
    },
    "A": {
        "period": "May 2022",
        "events": [
            ("2022-05-01", 38500, "HIGH", ""),
            ("2022-05-05", 36000, "LOW", ""),
            ("2022-05-09", 34000, "LOW", ""),
            ("2022-05-12", 28800, "BROKE", ""),
            ("2022-05-16", 31300, "MID", "retest"),
        ],
    },
    "B": {
        "period": "Jul-Aug 2022",
        "events": [
            ("2022-06-18", 17570, "LOW", "start"),
            ("2022-06-26", 21888, "HIGH", ""),
            ("2022-06-30", 18800, "LOW", ""),
            ("2022-07-08", 22400, "HIGH", ""),
            ("2022-07-13", 19200, "LOW", ""),
            ("2022-07-20", 24200, "HIGH", ""),
            ("2022-07-26", 20700, "LOW", ""),
            ("2022-08-04", 23200, "MID", ""),
            ("2022-08-10", 24900, "HIGH", "peak"),
            ("2022-08-15", 24400, "MID", ""),
            ("2022-08-19", 21300, "BROKE", ""),
            ("2022-08-26", 21800, "MID", "retest"),
        ],
    },
    "D": {
        "period": "Apr-Oct 2025",
        "events": [
            ("2025-04-09", 75000, "LOW", "start"),
            ("2025-05-12", 104000, "HIGH", ""),
            ("2025-06-06", 98700, "LOW", ""),
            ("2025-06-13", 106000, "HIGH", ""),
            ("2025-06-20", 101500, "LOW", ""),
            ("2025-07-03", 109000, "HIGH", ""),
            ("2025-08-02", 104000, "MID", ""),
            ("2025-08-18", 107000, "HIGH", ""),
            ("2025-09-01", 109000, "HIGH", "peak"),
            ("2025-09-16", 105000, "MID", "retest_fail"),
            ("2025-10-02", 99000, "BROKE", ""),
        ],
    },
    "E": {
        "period": "Nov25-Jan26",
        "events": [
            ("2025-11-21", 80600, "LOW", "start"),
            ("2025-11-28", 93036, "HIGH", ""),
            ("2025-12-01", 83757, "LOW", ""),
            ("2025-12-03", 94164, "HIGH", ""),
            ("2025-12-06", 89214, "MID", "retest"),
            ("2025-12-09", 94571, "HIGH", ""),
            ("2025-12-18", 85426, "LOW", ""),
            ("2025-12-22", 90537, "MID", "retest_fail"),
            ("2025-12-29", 86673, "LOW", ""),
            ("2026-01-05", 94736, "MID", ""),
            ("2026-01-14", 97879, "HIGH", "peak"),
            ("2026-01-20", 87695, "BROKE", ""),
            ("2026-01-28", 89131, "MID", "retest_fail"),
        ],
    },
    "F": {
        "period": "Feb-Mar 2026",
        "events": [
            ("2026-02-05", 62749, "LOW", "start"),
            ("2026-02-06", 71645, "HIGH", ""),
            ("2026-02-24", 64023, "LOW", ""),
            ("2026-03-04", 74041, "HIGH", ""),
            ("2026-03-08", 65572, "LOW", ""),
            ("2026-03-16", 74847, "HIGH", "peak"),
            ("2026-03-22", 67305, "LOW", ""),
            ("2026-03-25", 71980, "MID", "retest_fail"),
            ("2026-03-27", 65470, "BROKE", ""),
            ("2026-04-04", 69600, "MID", "retesting"),
        ],
    },
}


def main():
    cg = load_all()

    # Fetch Binance daily bars
    print("Fetching Binance daily bars...")
    adapter = BinanceFuturesAdapter()
    bars = adapter.fetch_range("BTCUSDT", "1d", datetime(2022, 1, 1), datetime(2026, 4, 6))
    print(f"Got {len(bars)} bars\n")

    closes = [b.close for b in bars]
    date_idx = {b.timestamp.strftime("%Y-%m-%d"): i for i, b in enumerate(bars)}

    rsi3 = compute_rsi(closes, 3)
    rsi7 = compute_rsi(closes, 7)
    rsi14 = compute_rsi(closes, 14)

    def find_idx(date_str):
        if date_str in date_idx:
            return date_idx[date_str]
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        for off in range(-2, 3):
            alt = (dt + timedelta(days=off)).strftime("%Y-%m-%d")
            if alt in date_idx:
                return date_idx[alt]
        return None

    # ══════════════════════════════════════════════════
    # PART 1: Every event, all indicators
    # ══════════════════════════════════════════════════
    for ch_name, ch_info in CHANNELS.items():
        print("=" * 160)
        print(f"CHANNEL {ch_name} -- {ch_info['period']}")
        print("=" * 160)
        hdr = (f"  {'Date':<11} {'Price':>7} {'Type':<6} {'Note':<13}"
               f" {'R3':>5} {'R7':>5} {'R14':>5}"
               f" {'OI$B':>6} {'OI%':>7}"
               f" {'Fund%':>8} {'L/S':>5} {'L%':>5}"
               f" {'LLiq$M':>8} {'SLiq$M':>8} {'LiqR':>6}"
               f" {'CVD_B':>8} {'Basis':>6} {'TkrBS':>6}")
        print(hdr)
        print("  " + "-" * 156)

        prev_oi = None
        for date, price, etype, note in ch_info["events"]:
            idx = find_idx(date)
            r3 = rsi3[idx] if idx else 0
            r7 = rsi7[idx] if idx else 0
            r14 = rsi14[idx] if idx else 0

            oi = cg["oi"].get(date, 0)
            fund = cg["fund"].get(date, 0)
            ls = cg["ls"].get(date, 0)
            lq = cg["liq"].get(date, {"l": 0, "s": 0})
            ll = lq["l"] / 1e6
            sl = lq["s"] / 1e6
            lr = ll / sl if sl > 0.001 else 0
            cvd = cg["cvd"].get(date, 0)
            bas = cg["basis"].get(date, 0)
            tk = cg["taker"].get(date, {"b": 0, "s": 0})
            tkr = tk["b"] / tk["s"] if tk["s"] > 0 else 0

            oi_b = oi / 1e9 if oi else 0
            oi_pct = ""
            if prev_oi and prev_oi > 0 and oi > 0:
                oi_pct = f"{(oi-prev_oi)/prev_oi*100:+.1f}%"
            if oi > 0:
                prev_oi = oi

            # Format
            oi_s = f"{oi_b:.1f}" if oi_b > 0 else "-"
            f_s = f"{fund:+.4f}" if fund != 0 else "-"
            ls_s = f"{ls:.2f}" if ls > 0 else "-"
            lp_s = f"{ls/(1+ls)*100:.1f}" if ls > 0 else "-"
            ll_s = f"{ll:.1f}" if ll > 0.01 else "-"
            sl_s = f"{sl:.1f}" if sl > 0.01 else "-"
            lr_s = f"{lr:.2f}" if lr > 0 else "-"
            cvd_s = f"{cvd/1e9:.1f}" if cvd != 0 else "-"
            bas_s = f"{bas:.4f}" if bas != 0 else "-"
            tkr_s = f"{tkr:.3f}" if tkr > 0 else "-"

            tag = f"{etype:<6}"
            note_s = f"{note:<13}" if note else f"{'':13}"

            print(f"  {date:<11} {price:>7} {tag} {note_s}"
                  f" {r3:>5.1f} {r7:>5.1f} {r14:>5.1f}"
                  f" {oi_s:>6} {oi_pct:>7}"
                  f" {f_s:>8} {ls_s:>5} {lp_s:>5}"
                  f" {ll_s:>8} {sl_s:>8} {lr_s:>6}"
                  f" {cvd_s:>8} {bas_s:>6} {tkr_s:>6}")

        # Breakdown window: 7 days before and 3 after
        broke_date = None
        for date, price, etype, note in ch_info["events"]:
            if etype == "BROKE":
                broke_date = date
        if broke_date:
            bidx = find_idx(broke_date)
            if bidx:
                print(f"\n  --- Breakdown window: {broke_date} ---")
                print(f"  {'Date':<11} {'Close':>8} {'R3':>6} {'R7':>6} {'R14':>6}"
                      f" {'OI$B':>6} {'Fund%':>8} {'L/S':>5}"
                      f" {'LLiq$M':>8} {'SLiq$M':>8} {'LiqR':>6}"
                      f" {'TkrBS':>6}")
                print(f"  {'-'*100}")
                for off in range(-7, 6):
                    i = bidx + off
                    if 0 <= i < len(bars):
                        dd = bars[i].timestamp.strftime("%Y-%m-%d")
                        c = closes[i]
                        oi_v = cg["oi"].get(dd, 0)
                        fd_v = cg["fund"].get(dd, 0)
                        ls_v = cg["ls"].get(dd, 0)
                        lq_v = cg["liq"].get(dd, {"l": 0, "s": 0})
                        ll_v = lq_v["l"] / 1e6
                        sl_v = lq_v["s"] / 1e6
                        lr_v = ll_v / sl_v if sl_v > 0.001 else 0
                        tk_v = cg["taker"].get(dd, {"b": 0, "s": 0})
                        tkr_v = tk_v["b"] / tk_v["s"] if tk_v["s"] > 0 else 0

                        mark = " <<<" if off == 0 else ""
                        oi_s2 = f"{oi_v/1e9:.1f}" if oi_v else "-"
                        fd_s2 = f"{fd_v:+.4f}" if fd_v != 0 else "-"
                        ls_s2 = f"{ls_v:.2f}" if ls_v > 0 else "-"
                        ll_s2 = f"{ll_v:.1f}" if ll_v > 0.01 else "-"
                        sl_s2 = f"{sl_v:.1f}" if sl_v > 0.01 else "-"
                        lr_s2 = f"{lr_v:.2f}" if lr_v > 0 else "-"
                        tkr_s2 = f"{tkr_v:.3f}" if tkr_v > 0 else "-"

                        print(f"  {dd:<11} {c:>8.0f} {rsi3[i]:>6.1f} {rsi7[i]:>6.1f} {rsi14[i]:>6.1f}"
                              f" {oi_s2:>6} {fd_s2:>8} {ls_s2:>5}"
                              f" {ll_s2:>8} {sl_s2:>8} {lr_s2:>6}"
                              f" {tkr_s2:>6}{mark}")
        print()

    # ══════════════════════════════════════════════════
    # PART 2: Cross-channel tables by type
    # ══════════════════════════════════════════════════
    print()
    print("=" * 130)
    print("ALL HIGHS — SORTED BY CHANNEL")
    print("=" * 130)
    print(f"  {'Ch':<3} {'Date':<11} {'Price':>7} {'Note':<10}"
          f" {'R3':>5} {'R7':>5} {'R14':>5}"
          f" {'OI$B':>6} {'Fund%':>8} {'L/S':>5}"
          f" {'LLiq$M':>8} {'SLiq$M':>8} {'LiqR':>6}"
          f" {'CVD_B':>7} {'TkrBS':>6}")
    print(f"  {'-'*125}")

    for ch_name, ch_info in CHANNELS.items():
        for date, price, etype, note in ch_info["events"]:
            if etype != "HIGH":
                continue
            idx = find_idx(date)
            r3 = rsi3[idx] if idx else 0
            r7 = rsi7[idx] if idx else 0
            r14 = rsi14[idx] if idx else 0
            oi = cg["oi"].get(date, 0)
            fund = cg["fund"].get(date, 0)
            ls = cg["ls"].get(date, 0)
            lq = cg["liq"].get(date, {"l": 0, "s": 0})
            ll = lq["l"] / 1e6; sl = lq["s"] / 1e6
            lr = ll / sl if sl > 0.001 else 0
            cvd = cg["cvd"].get(date, 0)
            tk = cg["taker"].get(date, {"b": 0, "s": 0})
            tkr = tk["b"] / tk["s"] if tk["s"] > 0 else 0

            oi_s = f"{oi/1e9:.1f}" if oi else "-"
            f_s = f"{fund:+.4f}" if fund != 0 else "-"
            ls_s = f"{ls:.2f}" if ls > 0 else "-"
            ll_s = f"{ll:.1f}" if ll > 0.01 else "-"
            sl_s = f"{sl:.1f}" if sl > 0.01 else "-"
            lr_s = f"{lr:.2f}" if lr > 0 else "-"
            cvd_s = f"{cvd/1e9:.1f}" if cvd != 0 else "-"
            tkr_s = f"{tkr:.3f}" if tkr > 0 else "-"
            n_s = f"{note:<10}" if note else f"{'':10}"

            print(f"  {ch_name:<3} {date:<11} {price:>7} {n_s}"
                  f" {r3:>5.1f} {r7:>5.1f} {r14:>5.1f}"
                  f" {oi_s:>6} {f_s:>8} {ls_s:>5}"
                  f" {ll_s:>8} {sl_s:>8} {lr_s:>6}"
                  f" {cvd_s:>7} {tkr_s:>6}")

    print()
    print("=" * 130)
    print("ALL LOWS — SORTED BY CHANNEL")
    print("=" * 130)
    print(f"  {'Ch':<3} {'Date':<11} {'Price':>7} {'Note':<10}"
          f" {'R3':>5} {'R7':>5} {'R14':>5}"
          f" {'OI$B':>6} {'Fund%':>8} {'L/S':>5}"
          f" {'LLiq$M':>8} {'SLiq$M':>8} {'LiqR':>6}"
          f" {'CVD_B':>7} {'TkrBS':>6}")
    print(f"  {'-'*125}")

    for ch_name, ch_info in CHANNELS.items():
        for date, price, etype, note in ch_info["events"]:
            if etype != "LOW":
                continue
            idx = find_idx(date)
            r3 = rsi3[idx] if idx else 0
            r7 = rsi7[idx] if idx else 0
            r14 = rsi14[idx] if idx else 0
            oi = cg["oi"].get(date, 0)
            fund = cg["fund"].get(date, 0)
            ls = cg["ls"].get(date, 0)
            lq = cg["liq"].get(date, {"l": 0, "s": 0})
            ll = lq["l"] / 1e6; sl = lq["s"] / 1e6
            lr = ll / sl if sl > 0.001 else 0
            cvd = cg["cvd"].get(date, 0)
            tk = cg["taker"].get(date, {"b": 0, "s": 0})
            tkr = tk["b"] / tk["s"] if tk["s"] > 0 else 0

            oi_s = f"{oi/1e9:.1f}" if oi else "-"
            f_s = f"{fund:+.4f}" if fund != 0 else "-"
            ls_s = f"{ls:.2f}" if ls > 0 else "-"
            ll_s = f"{ll:.1f}" if ll > 0.01 else "-"
            sl_s = f"{sl:.1f}" if sl > 0.01 else "-"
            lr_s = f"{lr:.2f}" if lr > 0 else "-"
            cvd_s = f"{cvd/1e9:.1f}" if cvd != 0 else "-"
            tkr_s = f"{tkr:.3f}" if tkr > 0 else "-"
            n_s = f"{note:<10}" if note else f"{'':10}"

            print(f"  {ch_name:<3} {date:<11} {price:>7} {n_s}"
                  f" {r3:>5.1f} {r7:>5.1f} {r14:>5.1f}"
                  f" {oi_s:>6} {f_s:>8} {ls_s:>5}"
                  f" {ll_s:>8} {sl_s:>8} {lr_s:>6}"
                  f" {cvd_s:>7} {tkr_s:>6}")

    print()
    print("=" * 130)
    print("ALL BREAKDOWNS")
    print("=" * 130)
    print(f"  {'Ch':<3} {'Date':<11} {'Price':>7}"
          f" {'R3':>5} {'R7':>5} {'R14':>5}"
          f" {'OI$B':>6} {'Fund%':>8} {'L/S':>5}"
          f" {'LLiq$M':>8} {'SLiq$M':>8} {'LiqR':>6}"
          f" {'CVD_B':>7} {'Basis':>6} {'TkrBS':>6}")
    print(f"  {'-'*115}")

    for ch_name, ch_info in CHANNELS.items():
        for date, price, etype, note in ch_info["events"]:
            if etype != "BROKE":
                continue
            idx = find_idx(date)
            r3 = rsi3[idx] if idx else 0
            r7 = rsi7[idx] if idx else 0
            r14 = rsi14[idx] if idx else 0
            oi = cg["oi"].get(date, 0)
            fund = cg["fund"].get(date, 0)
            ls = cg["ls"].get(date, 0)
            lq = cg["liq"].get(date, {"l": 0, "s": 0})
            ll = lq["l"] / 1e6; sl = lq["s"] / 1e6
            lr = ll / sl if sl > 0.001 else 0
            cvd = cg["cvd"].get(date, 0)
            bas = cg["basis"].get(date, 0)
            tk = cg["taker"].get(date, {"b": 0, "s": 0})
            tkr = tk["b"] / tk["s"] if tk["s"] > 0 else 0

            oi_s = f"{oi/1e9:.1f}" if oi else "-"
            f_s = f"{fund:+.4f}" if fund != 0 else "-"
            ls_s = f"{ls:.2f}" if ls > 0 else "-"
            ll_s = f"{ll:.1f}" if ll > 0.01 else "-"
            sl_s = f"{sl:.1f}" if sl > 0.01 else "-"
            lr_s = f"{lr:.2f}" if lr > 0 else "-"
            cvd_s = f"{cvd/1e9:.1f}" if cvd != 0 else "-"
            bas_s = f"{bas:.4f}" if bas != 0 else "-"
            tkr_s = f"{tkr:.3f}" if tkr > 0 else "-"

            print(f"  {ch_name:<3} {date:<11} {price:>7}"
                  f" {r3:>5.1f} {r7:>5.1f} {r14:>5.1f}"
                  f" {oi_s:>6} {f_s:>8} {ls_s:>5}"
                  f" {ll_s:>8} {sl_s:>8} {lr_s:>6}"
                  f" {cvd_s:>7} {bas_s:>6} {tkr_s:>6}")

    print()
    print("=" * 130)
    print("ALL MIDS (retest / retest_fail / retesting)")
    print("=" * 130)
    print(f"  {'Ch':<3} {'Date':<11} {'Price':>7} {'Note':<13}"
          f" {'R3':>5} {'R7':>5} {'R14':>5}"
          f" {'OI$B':>6} {'Fund%':>8} {'L/S':>5}"
          f" {'LLiq$M':>8} {'SLiq$M':>8} {'LiqR':>6}"
          f" {'CVD_B':>7} {'TkrBS':>6}")
    print(f"  {'-'*125}")

    for ch_name, ch_info in CHANNELS.items():
        for date, price, etype, note in ch_info["events"]:
            if etype != "MID":
                continue
            idx = find_idx(date)
            r3 = rsi3[idx] if idx else 0
            r7 = rsi7[idx] if idx else 0
            r14 = rsi14[idx] if idx else 0
            oi = cg["oi"].get(date, 0)
            fund = cg["fund"].get(date, 0)
            ls = cg["ls"].get(date, 0)
            lq = cg["liq"].get(date, {"l": 0, "s": 0})
            ll = lq["l"] / 1e6; sl = lq["s"] / 1e6
            lr = ll / sl if sl > 0.001 else 0
            cvd = cg["cvd"].get(date, 0)
            tk = cg["taker"].get(date, {"b": 0, "s": 0})
            tkr = tk["b"] / tk["s"] if tk["s"] > 0 else 0

            oi_s = f"{oi/1e9:.1f}" if oi else "-"
            f_s = f"{fund:+.4f}" if fund != 0 else "-"
            ls_s = f"{ls:.2f}" if ls > 0 else "-"
            ll_s = f"{ll:.1f}" if ll > 0.01 else "-"
            sl_s = f"{sl:.1f}" if sl > 0.01 else "-"
            lr_s = f"{lr:.2f}" if lr > 0 else "-"
            cvd_s = f"{cvd/1e9:.1f}" if cvd != 0 else "-"
            tkr_s = f"{tkr:.3f}" if tkr > 0 else "-"
            n_s = f"{note:<13}" if note else f"{'':13}"

            print(f"  {ch_name:<3} {date:<11} {price:>7} {n_s}"
                  f" {r3:>5.1f} {r7:>5.1f} {r14:>5.1f}"
                  f" {oi_s:>6} {f_s:>8} {ls_s:>5}"
                  f" {ll_s:>8} {sl_s:>8} {lr_s:>6}"
                  f" {cvd_s:>7} {tkr_s:>6}")


if __name__ == "__main__":
    main()
