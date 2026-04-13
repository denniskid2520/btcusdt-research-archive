"""Phase 8B — Row 4 circuit-breaker validation.

Runs Row 4 (4x V3 D1_long dyn+adap, h=11, aS=1.25%, cS=2.5%,
bf=3.0, mf=4.0, L=4x) through the full OOS walk-forward, then
replays each trade at 1h and 15m resolution through 4 breaker
thresholds (8/10/12/15%) using both adverse-move and equity-DD
breaker types.

Also runs Row 2 (3x V3 bf=2.0 mf=3.0 L=3) as the baseline
comparison anchor.

Outputs a compact comparison table per the Phase 8B brief.
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, "src")

from data.strategy_c_v2_features import rsi_series
from research.strategy_c_v2_backtest import V2Trade, run_v2_backtest
from research.strategy_c_v2_circuit_breaker import (
    run_adverse_move_breaker,
    run_equity_dd_breaker,
)
from research.strategy_c_v2_runner import (
    combined_profit_factor,
    load_funding_csv,
    load_klines_csv,
    load_timeframe_data,
    stitch_equity,
)
from research.strategy_c_v2_stress_test import (
    StressConfig,
    classify_shock,
    estimate_slippage_impact,
)
from strategies.strategy_c_v2_dynamic_sizing import (
    compute_hold_bars_override_vector,
    compute_position_frac_override,
)
from strategies.strategy_c_v2_filters import apply_side_filter
from strategies.strategy_c_v2_literature import rsi_only_signals


KLINES_4H = "src/data/btcusdt_4h_6year.csv"
KLINES_1H = "src/data/btcusdt_1h_6year.csv"
KLINES_15M = "src/data/btcusdt_15m_6year.csv"
FUNDING_CSV = "src/data/btcusdt_funding_5year.csv"

STARTING_EQUITY = 10_000.0
FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001
ROUND_TRIP = 2.0 * (FEE_PER_SIDE + SLIP_PER_SIDE)

BREAKER_PCTS = [0.08, 0.10, 0.12, 0.15]
SHOCK_LEVELS = [0.10, 0.15, 0.20, 0.30]
SLIP_LEVELS = [0.001, 0.003, 0.005, 0.010]


def build_d1_long_signals(features):
    closes = [f.close for f in features]
    rsi20 = rsi_series(closes, 20)
    sigs = rsi_only_signals(features, rsi_period=20, rsi_override=rsi20)
    return apply_side_filter(sigs, side="long")


def run_row_walkforward(
    *,
    tf,
    signals,
    alpha_stop_pct: float,
    catastrophe_stop_pct: float,
    risk_per_trade: float,
    base_frac: float,
    max_frac: float,
    use_dynamic: bool,
    use_adaptive: bool,
    hold_bars: int = 11,
):
    """Run the walk-forward and collect trades + per-trade fracs."""
    override_frac_full = None
    if use_dynamic:
        raw = compute_position_frac_override(tf.features, signals, base_frac)
        override_frac_full = [
            min(v, max_frac) if v is not None else None for v in raw
        ]
    else:
        override_frac_full = [None] * len(tf.features)
        for i, s in enumerate(signals):
            if s != 0:
                override_frac_full[i] = min(base_frac, max_frac)

    override_hold_full = None
    if use_adaptive:
        override_hold_full = compute_hold_bars_override_vector(
            tf.features, signals, hold_bars
        )

    all_trades: list[V2Trade] = []
    all_fracs: list[float] = []
    per_curves: list[list[float]] = []

    for split in tf.splits:
        s, e = split.test_lo, split.test_hi
        test_bars = tf.bars[s:e]
        test_signals = signals[s:e]
        test_funding = tf.funding_per_bar[s:e]
        test_frac = override_frac_full[s:e]
        test_hold = override_hold_full[s:e] if override_hold_full else None

        bt = run_v2_backtest(
            bars=test_bars,
            signals=test_signals,
            funding_per_bar=test_funding,
            hold_bars=hold_bars,
            fee_per_side=FEE_PER_SIDE,
            slip_per_side=SLIP_PER_SIDE,
            alpha_stop_pct=alpha_stop_pct,
            catastrophe_stop_pct=catastrophe_stop_pct,
            risk_per_trade=risk_per_trade,
            effective_leverage=max_frac,
            position_frac_override=test_frac,
            hold_bars_override=test_hold,
        )
        per_curves.append(bt.equity_curve)
        for t in bt.trades:
            all_trades.append(t)
            idx = t.entry_idx - 1
            if 0 <= idx < len(test_frac) and test_frac[idx] is not None:
                all_fracs.append(test_frac[idx])
            else:
                all_fracs.append(min(risk_per_trade / alpha_stop_pct, max_frac))

    curve = stitch_equity(per_curves)
    return all_trades, all_fracs, curve


def compute_metrics(trades, fracs, curve, label=""):
    pnls = [t.net_pnl for t in trades]
    n = len(trades)
    wins = sum(1 for p in pnls if p > 0)
    ret = (curve[-1] - 1.0) if curve else 0.0
    peak = curve[0] if curve else 1.0
    dd = 0.0
    for e in curve:
        if e > peak:
            peak = e
        if peak > 0:
            d = (peak - e) / peak
            if d > dd:
                dd = d
    dd_usd = 0.0
    peak_usd = STARTING_EQUITY
    for e in curve:
        eq = STARTING_EQUITY * e
        if eq > peak_usd:
            peak_usd = eq
        drop = peak_usd - eq
        if drop > dd_usd:
            dd_usd = drop
    worst = min(pnls) if pnls else 0.0
    pf = combined_profit_factor(pnls)
    wr = wins / n if n else 0.0
    stops = sum(1 for t in trades if t.exit_reason.startswith(("alpha_stop", "catastrophe_stop", "stop_loss")))
    avg_frac = sum(fracs) / len(fracs) if fracs else 0.0
    max_frac_obs = max(fracs) if fracs else 0.0
    # Worst adverse on 4h bars
    worst_adv = 0.0
    # (approximate — from the trade data we don't have intrabar here)
    return {
        "label": label,
        "n": n,
        "wr": wr,
        "pf": pf,
        "ret": ret,
        "end_usd": STARTING_EQUITY * (1 + ret),
        "dd": dd,
        "dd_usd": dd_usd,
        "worst_trade": worst,
        "worst_trade_usd": worst * STARTING_EQUITY,
        "stops": stops,
        "stop_frac": stops / n if n else 0.0,
        "avg_frac": avg_frac,
        "max_frac": max_frac_obs,
    }


def print_comparison_table(rows: list[dict]) -> None:
    """Print the Phase 8B comparison table."""
    header = (
        f"{'Label':<35} {'n':>4} {'WR':>6} {'PF':>5} "
        f"{'Return':>9} {'End$':>9} {'DD%':>6} {'DD$':>7} "
        f"{'Worst%':>7} {'Worst$':>7} {'StopFr':>7} "
        f"{'Shk10':>6} {'Shk15':>6} {'Shk20':>6} {'Shk30':>6} "
        f"{'S.1%':>7} {'S.3%':>7} {'S1%':>7} {'Verdict':>10}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['label']:<35} "
            f"{r['n']:>4} "
            f"{r['wr']*100:>5.1f}% "
            f"{r['pf']:>5.2f} "
            f"{r['ret']*100:>+8.1f}% "
            f"${r['end_usd']:>8,.0f} "
            f"{r['dd']*100:>5.1f}% "
            f"${r['dd_usd']:>6,.0f} "
            f"{r['worst_trade']*100:>+6.1f}% "
            f"${r['worst_trade_usd']:>6,.0f} "
            f"{r['stop_frac']*100:>5.1f}% "
            f"{r.get('shk10','?'):>6} "
            f"{r.get('shk15','?'):>6} "
            f"{r.get('shk20','?'):>6} "
            f"{r.get('shk30','?'):>6} "
            f"{r.get('slip01',''):>+6.0f}pp " if r.get('slip01') is not None else ""
            f"{r.get('slip03',''):>+6.0f}pp " if r.get('slip03') is not None else ""
            f"{r.get('slip10',''):>+6.0f}pp " if r.get('slip10') is not None else ""
            f"{r.get('verdict',''):>10}"
        )


def add_stress_to_metrics(
    m: dict,
    exchange_leverage: float,
    max_frac_obs: float,
    worst_adverse: float,
) -> dict:
    """Add shock and slippage columns to a metrics dict."""
    liq = 1.0 / exchange_leverage
    for shock in SHOCK_LEVELS:
        combined = worst_adverse + shock
        if combined >= liq:
            v = "liq"
        elif liq - combined < 0.05:
            v = "tight"
        else:
            v = "surv"
        m[f"shk{int(shock*100)}"] = v

    # Slippage
    stops = m.get("stops", 0)
    avg_frac = m.get("avg_frac", 1.0)
    base_ret = m["ret"] * 100.0
    for slip in SLIP_LEVELS:
        sr = estimate_slippage_impact(
            slip_pct=slip,
            num_stop_exits=stops,
            avg_actual_frac=avg_frac,
            num_trades=m["n"],
            baseline_return_pct=base_ret,
        )
        key = f"slip{str(int(slip*1000)).zfill(2)}"
        m[key] = sr.return_delta_pp
    return m


def main() -> None:
    print("=" * 78)
    print("Phase 8B — Row 4 circuit-breaker validation")
    print("=" * 78)

    # Load data
    print("\nLoading data...")
    t0 = time.time()
    funding = load_funding_csv(FUNDING_CSV)
    tf = load_timeframe_data("4h", KLINES_4H, 4.0, funding)
    bars_1h = load_klines_csv(KLINES_1H)
    bars_15m = load_klines_csv(KLINES_15M)
    print(f"  4h: {len(tf.bars):,} bars")
    print(f"  1h: {len(bars_1h):,} bars")
    print(f"  15m: {len(bars_15m):,} bars")
    print(f"  ({time.time()-t0:.1f}s)")

    signals = build_d1_long_signals(tf.features)

    # ── Run Row 2 baseline (3x V3 bf=2.0 mf=3.0 L=3) ──
    print("\nRunning Row 2 baseline...")
    r2_trades, r2_fracs, r2_curve = run_row_walkforward(
        tf=tf, signals=signals,
        alpha_stop_pct=0.0125,
        catastrophe_stop_pct=0.025,
        risk_per_trade=0.025,
        base_frac=2.0, max_frac=3.0,
        use_dynamic=True, use_adaptive=True,
    )
    r2_m = compute_metrics(r2_trades, r2_fracs, r2_curve, "Row2 3x V3 bf2.0 mf3.0")

    # ── Run Row 4 raw (4x V3 bf=3.0 mf=4.0 L=4) ──
    print("Running Row 4 raw...")
    r4_trades, r4_fracs, r4_curve = run_row_walkforward(
        tf=tf, signals=signals,
        alpha_stop_pct=0.0125,
        catastrophe_stop_pct=0.025,
        risk_per_trade=0.035,
        base_frac=3.0, max_frac=4.0,
        use_dynamic=True, use_adaptive=True,
    )
    r4_m = compute_metrics(r4_trades, r4_fracs, r4_curve, "Row4 4x V3 RAW")

    # Compute worst adverse from 4h trades (for stress verdicts)
    worst_adv_4h = 0.0
    for t in r4_trades:
        # Use entry/exit price as proxy
        if t.side > 0:
            adv = (t.entry_price - t.exit_price) / t.entry_price if t.exit_price < t.entry_price else 0.0
        else:
            adv = (t.exit_price - t.entry_price) / t.entry_price if t.exit_price > t.entry_price else 0.0
        if adv > worst_adv_4h:
            worst_adv_4h = adv

    # Scan 1h intrabar adverse — ONLY for non-stop trades.
    # Trades that exited via alpha_stop or catastrophe_stop already
    # closed the position intrabar; scanning their full [entry, exit)
    # range on 1h bars would include post-exit price action and
    # inflate the observed adverse (the position was already flat).
    print("\nScanning 1h intrabar adverse moves for Row 4 trades...")
    print("  (skipping stop-exited trades — position was already flat)")
    from research.strategy_c_v2_circuit_breaker import _compute_max_adverse_intrabar
    from bisect import bisect_left, bisect_right
    hires_ts = [b.timestamp for b in bars_1h]
    max_adv_1h = 0.0
    max_adv_1h_trade_idx = -1
    non_stop_count = 0
    stop_count = 0
    for ti, t in enumerate(r4_trades):
        if t.exit_reason.startswith(("alpha_stop", "catastrophe_stop", "stop_loss")):
            stop_count += 1
            continue
        non_stop_count += 1
        lo = bisect_left(hires_ts, t.entry_time)
        hi = bisect_right(hires_ts, t.exit_time)
        adv, _, _ = _compute_max_adverse_intrabar(bars_1h, lo, hi, t.entry_price, t.side)
        if adv > max_adv_1h:
            max_adv_1h = adv
            max_adv_1h_trade_idx = ti
    print(f"  Non-stop trades scanned: {non_stop_count} (stop-exited skipped: {stop_count})")
    print(f"  Worst 1h intrabar adverse (non-stop trades only): {max_adv_1h*100:.2f}%")
    if max_adv_1h_trade_idx >= 0:
        t = r4_trades[max_adv_1h_trade_idx]
        print(f"  Trade #{max_adv_1h_trade_idx}: entry={t.entry_time} exit_reason={t.exit_reason} "
              f"side={'long' if t.side>0 else 'short'} net_pnl={t.net_pnl*100:+.2f}%")

    # Also scan stop-exited trades for comparison (post-exit noise)
    max_adv_stop_trades = 0.0
    for ti, t in enumerate(r4_trades):
        if not t.exit_reason.startswith(("alpha_stop", "catastrophe_stop", "stop_loss")):
            continue
        lo = bisect_left(hires_ts, t.entry_time)
        hi = bisect_right(hires_ts, t.exit_time)
        adv, _, _ = _compute_max_adverse_intrabar(bars_1h, lo, hi, t.entry_price, t.side)
        if adv > max_adv_stop_trades:
            max_adv_stop_trades = adv
    print(f"  Worst 1h adverse on STOP-exited trades (includes post-exit): {max_adv_stop_trades*100:.2f}%")
    print(f"  (this number is inflated — position was already flat before the worst point)")

    # ── Run breaker study on Row 4 at each threshold ──
    breaker_rows: list[dict] = []

    for bp in BREAKER_PCTS:
        print(f"\nRunning adverse-move breaker @ {bp*100:.0f}% (1h replay)...")
        result = run_adverse_move_breaker(
            trades_4h=r4_trades,
            bars_4h=tf.bars,
            bars_hires=bars_1h,
            breaker_pct=bp,
            position_fracs=r4_fracs,
            round_trip_cost=ROUND_TRIP,
        )
        # Build metrics from the breaker result
        pnls_with = []
        for ti, trade in enumerate(r4_trades):
            evt = next((e for e in result.events if e.trade_index == ti), None)
            if evt:
                pnls_with.append(evt.pnl_with_breaker)
            else:
                pnls_with.append(trade.net_pnl)
        from research.strategy_c_v2_circuit_breaker import _build_equity_curve, _max_dd_from_curve
        curve_b = _build_equity_curve(pnls_with)
        ret_b = (curve_b[-1] - 1.0) if curve_b else 0.0
        dd_b = _max_dd_from_curve(curve_b)
        dd_usd_b = 0.0
        peak_usd = STARTING_EQUITY
        for e in curve_b:
            eq = STARTING_EQUITY * e
            if eq > peak_usd: peak_usd = eq
            drop = peak_usd - eq
            if drop > dd_usd_b: dd_usd_b = drop
        worst_b = min(pnls_with) if pnls_with else 0.0
        pf_b = combined_profit_factor(pnls_with)
        wins_b = sum(1 for p in pnls_with if p > 0)
        stops_b = sum(1 for t in r4_trades if t.exit_reason.startswith(("alpha_stop", "catastrophe_stop")))
        # Breaker exits count as stop-like exits for slippage purposes
        total_stop_like = stops_b + result.breaker_fires
        avg_frac = sum(r4_fracs) / len(r4_fracs) if r4_fracs else 1.0

        m = {
            "label": f"Row4 + breaker({bp*100:.0f}%) adv",
            "n": len(r4_trades),
            "wr": wins_b / len(r4_trades) if r4_trades else 0.0,
            "pf": pf_b,
            "ret": ret_b,
            "end_usd": STARTING_EQUITY * (1 + ret_b),
            "dd": dd_b,
            "dd_usd": dd_usd_b,
            "worst_trade": worst_b,
            "worst_trade_usd": worst_b * STARTING_EQUITY,
            "stops": total_stop_like,
            "stop_frac": total_stop_like / len(r4_trades) if r4_trades else 0.0,
            "avg_frac": avg_frac,
            "max_frac": max(r4_fracs) if r4_fracs else 0.0,
            "breaker_fires": result.breaker_fires,
        }
        # For shock verdicts, the breaker caps adverse at bp
        capped_adv = min(max_adv_1h, bp)
        m = add_stress_to_metrics(m, 4.0, max(r4_fracs) if r4_fracs else 4.0, capped_adv)
        breaker_rows.append(m)

        print(f"  Breaker fires: {result.breaker_fires}/{len(r4_trades)}")
        print(f"  Return: {ret_b*100:+.1f}% (vs raw {r4_m['ret']*100:+.1f}%)")
        print(f"  DD: {dd_b*100:.1f}% (vs raw {r4_m['dd']*100:.1f}%)")

    # ── Add stress columns to Row 2 and Row 4 raw ──
    r2_m = add_stress_to_metrics(r2_m, 3.0, max(r2_fracs) if r2_fracs else 3.0, max_adv_1h)
    r4_m = add_stress_to_metrics(r4_m, 4.0, max(r4_fracs) if r4_fracs else 4.0, max_adv_1h)

    # ── Print comparison table ──
    print("\n" + "=" * 78)
    print("PHASE 8B COMPARISON TABLE")
    print("=" * 78)

    all_rows = [r2_m, r4_m] + breaker_rows

    print(f"\n{'Label':<35} | {'n':>3} {'WR':>5} {'PF':>5} | "
          f"{'Return':>8} {'End$':>9} | {'DD%':>5} {'DD$':>7} {'Wrst%':>6} {'Wrst$':>6} | "
          f"{'StpFr':>5} {'BrkFr':>5} | "
          f"{'10%':>5} {'15%':>5} {'20%':>5} {'30%':>5} | "
          f"{'s0.1':>5} {'s0.3':>5} {'s1.0':>5}")
    print("-" * 140)
    for r in all_rows:
        brk = r.get("breaker_fires", "-")
        print(
            f"{r['label']:<35} | "
            f"{r['n']:>3} {r['wr']*100:>4.1f}% {r['pf']:>5.2f} | "
            f"{r['ret']*100:>+7.1f}% ${r['end_usd']:>8,.0f} | "
            f"{r['dd']*100:>4.1f}% ${r['dd_usd']:>6,.0f} "
            f"{r['worst_trade']*100:>+5.1f}% ${r['worst_trade_usd']:>5,.0f} | "
            f"{r['stop_frac']*100:>4.1f}% {brk:>5} | "
            f"{r.get('shk10','?'):>5} {r.get('shk15','?'):>5} "
            f"{r.get('shk20','?'):>5} {r.get('shk30','?'):>5} | "
            f"{r.get('slip01',0):>+4.0f}p {r.get('slip03',0):>+4.0f}p "
            f"{r.get('slip10',0):>+5.0f}p"
        )

    # ── Promotion verdict ──
    print("\n" + "=" * 78)
    print("PROMOTION VERDICT")
    print("=" * 78)

    for r in breaker_rows:
        bp_label = r["label"]
        ret_pct = r["ret"] * 100
        pf = r["pf"]
        shk15 = r.get("shk15", "?")
        shk20 = r.get("shk20", "?")
        slip10 = r.get("slip10", -9999)

        promotes = (
            ret_pct >= 500
            and pf >= 2.0
            and shk15 in ("surv", "tight")
            and slip10 > -50
        )
        verdict = "PROMOTE" if promotes else "REJECT"
        reasons = []
        if ret_pct < 500:
            reasons.append(f"return {ret_pct:+.1f}% < 500%")
        if pf < 2.0:
            reasons.append(f"PF {pf:.2f} < 2.0")
        if shk15 not in ("surv", "tight"):
            reasons.append(f"15% shock = {shk15}")
        if slip10 <= -50:
            reasons.append(f"1% slip = {slip10:+.0f}pp collapse")

        print(f"  {bp_label}: {verdict}")
        if reasons:
            print(f"    reason: {'; '.join(reasons)}")
        else:
            print(f"    all criteria pass: ret={ret_pct:+.1f}%, PF={pf:.2f}, "
                  f"shk15={shk15}, shk20={shk20}")


if __name__ == "__main__":
    main()
