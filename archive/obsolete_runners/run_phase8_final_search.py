"""Phase 8 FINAL search — D1_long leveraged futures optimizer.

Single-track optimization for the ONE final BTCUSDT perpetual futures
strategy on a $10,000 account.

Mainline: D1_long (rsi_only_20 long, 4h, strategy_close_stop)
Allowed modifiers: dynamic sizing, adaptive exit
Reference exchange leverage: 2x isolated
Hard constraints:
  - actual_frac ≤ 2.0 (Phase 6 tail-event stress: survives 40% shock
    without liquidation; frac > 2.0 breaks this on 2x isolated)
  - stops_fired / num_trades ≤ 0.45 (operational realism)
  - worst single trade ≥ -20% USD (no catastrophic loss)
  - liquidation buffer multiple ≥ 3x (worst observed adverse move is
    less than 1/3 of the liquidation distance)

Search axes:
  - stop_loss_pct
  - risk_per_trade
  - dynamic sizing on/off
  - adaptive exit on/off

actual_frac is a derived quantity: min(risk / stop, 2.0) for fixed,
or base * dynamic_multiplier capped at 2.0 for dynamic variants.

Reports strategy-level leveraged futures numbers (layer 1 only). No
portfolio allocation dilution. Starting equity = $10,000 in every
config. Exchange leverage = 2x in every config.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

sys.path.insert(0, "src")

from data.strategy_c_v2_features import rsi_series
from research.strategy_c_v2_backtest import run_v2_backtest
from research.strategy_c_v2_runner import (
    combined_profit_factor,
    load_funding_csv,
    load_timeframe_data,
    stitch_equity,
)
from strategies.strategy_c_v2_dynamic_sizing import (
    compute_hold_bars_override_vector,
    compute_position_frac_override,
)
from strategies.strategy_c_v2_filters import apply_side_filter
from strategies.strategy_c_v2_literature import rsi_only_signals


KLINES_4H = "src/data/btcusdt_4h_6year.csv"
FUNDING_CSV = "src/data/btcusdt_funding_5year.csv"

STARTING_EQUITY_USD = 10_000.0
EXCHANGE_LEVERAGE = 2.0
FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001

# Hard constraints
FRAC_CAP = 2.0                     # actual_frac ceiling under Phase 6 tail stress
STOP_RATE_CEILING = 0.45           # stops_fired / num_trades must be ≤ this
WORST_TRADE_FLOOR = -0.20          # worst single trade cannot be worse than -20%
LIQ_BUFFER_FLOOR = 3.0             # liquidation buffer must be ≥ 3x
TAIL_SHOCK = 0.40                  # Phase 6 synthetic shock


@dataclass
class ConfigResult:
    label: str
    stop_pct: float
    risk_pct: float
    base_frac: float
    max_frac_realized: float
    use_dynamic: bool
    use_adaptive: bool
    num_trades: int
    stops_fired: int
    stop_rate: float
    oos_return: float
    ending_equity_usd: float
    max_dd: float
    max_dd_usd: float
    profit_factor: float
    worst_trade_pnl: float
    worst_trade_usd: float
    worst_adverse_move: float
    liq_distance: float
    liq_buffer_multiple: float
    tail_shock_loss_frac: float
    survives_tail: bool
    operational_realism_ok: bool
    passes_all_constraints: bool


def build_sizing_override(
    features,
    signals,
    base_frac: float,
    use_dynamic: bool,
) -> list[float | None]:
    """Build a position_frac override vector.

    For fixed: every signal bar gets exactly `base_frac`.
    For dynamic: every signal bar gets `base_frac * multiplier`,
    where multiplier comes from the shared dynamic sizing module,
    then clamped at FRAC_CAP so no bar exceeds the 2.0 ceiling.
    """
    if use_dynamic:
        raw = compute_position_frac_override(features, signals, base_frac)
        return [
            min(v, FRAC_CAP) if v is not None else None
            for v in raw
        ]
    # Fixed: uniform override at base_frac
    out: list[float | None] = [None] * len(features)
    for i, s in enumerate(signals):
        if s != 0:
            out[i] = min(base_frac, FRAC_CAP)
    return out


def compute_dollar_drawdown(stitched_curve: list[float]) -> float:
    """Max peak-to-trough drawdown in USD on $10k starting equity."""
    if not stitched_curve:
        return 0.0
    peak_usd = STARTING_EQUITY_USD
    worst = 0.0
    for point in stitched_curve:
        eq = STARTING_EQUITY_USD * point
        if eq > peak_usd:
            peak_usd = eq
        drop = peak_usd - eq
        if drop > worst:
            worst = drop
    return worst


def run_config(
    *,
    label: str,
    stop_pct: float,
    risk_pct: float,
    use_dynamic: bool,
    use_adaptive: bool,
    tf,
    signals_base,
) -> ConfigResult:
    hold_base = 11
    base_frac = min(risk_pct / stop_pct, FRAC_CAP)

    override_frac = build_sizing_override(
        tf.features, signals_base, base_frac, use_dynamic
    )
    override_hold = None
    if use_adaptive:
        override_hold = compute_hold_bars_override_vector(
            tf.features, signals_base, hold_base
        )

    per_curves: list[list[float]] = []
    all_pnls: list[float] = []
    all_adv: list[float] = []
    total_trades = 0
    stops_fired = 0
    max_frac_observed = 0.0

    for split in tf.splits:
        test_bars = tf.bars[split.test_lo : split.test_hi]
        test_signals = signals_base[split.test_lo : split.test_hi]
        test_funding = tf.funding_per_bar[split.test_lo : split.test_hi]
        test_ovr_frac = override_frac[split.test_lo : split.test_hi]
        test_ovr_hold = (
            override_hold[split.test_lo : split.test_hi]
            if override_hold is not None
            else None
        )

        bt = run_v2_backtest(
            bars=test_bars,
            signals=test_signals,
            funding_per_bar=test_funding,
            hold_bars=hold_base,
            fee_per_side=FEE_PER_SIDE,
            slip_per_side=SLIP_PER_SIDE,
            stop_loss_pct=stop_pct,
            stop_trigger="close",
            stop_semantics="strategy_close_stop",
            risk_per_trade=risk_pct,
            effective_leverage=EXCHANGE_LEVERAGE,
            position_frac_override=test_ovr_frac,
            hold_bars_override=test_ovr_hold,
        )
        per_curves.append(bt.equity_curve)
        for t in bt.trades:
            all_pnls.append(t.net_pnl)
            total_trades += 1
            if t.exit_reason.startswith("stop_loss"):
                stops_fired += 1
            worst = 0.0
            for k in range(t.entry_idx, t.exit_idx):
                bk = test_bars[k]
                adv = (
                    (t.entry_price - bk.low) / t.entry_price
                    if t.side > 0
                    else (bk.high - t.entry_price) / t.entry_price
                )
                if adv > worst:
                    worst = adv
            all_adv.append(worst)
        # Track max realized frac across the override vector
        for v in test_ovr_frac:
            if v is not None and v > max_frac_observed:
                max_frac_observed = v

    curve = stitch_equity(per_curves)
    ret = (curve[-1] - 1.0) if curve else 0.0
    ending_equity = STARTING_EQUITY_USD * (1 + ret)

    def max_dd(c: list[float]) -> float:
        if not c:
            return 0.0
        peak = c[0]
        dd = 0.0
        for e in c:
            if e > peak:
                peak = e
            if peak > 0:
                d = (peak - e) / peak
                if d > dd:
                    dd = d
        return dd

    dd = max_dd(curve)
    dd_usd = compute_dollar_drawdown(curve)
    pf = combined_profit_factor(all_pnls)
    worst_trade = min(all_pnls) if all_pnls else 0.0
    worst_trade_usd = worst_trade * STARTING_EQUITY_USD
    worst_adv = max(all_adv) if all_adv else 0.0
    stop_rate = stops_fired / total_trades if total_trades else 0.0

    # Liquidation math
    liq_distance = 1.0 / EXCHANGE_LEVERAGE  # 0.50 for 2x
    liq_buffer_multiple = (
        liq_distance / worst_adv if worst_adv > 0 else float("inf")
    )

    # Tail shock at max realized frac (use dynamic cap-clamped value)
    max_frac_for_stress = max_frac_observed if max_frac_observed > 0 else base_frac
    tail_loss = TAIL_SHOCK * max_frac_for_stress  # fraction of equity lost on 40% shock
    survives_tail = tail_loss < 1.0  # account still has some equity left

    operational_ok = (
        stop_rate <= STOP_RATE_CEILING
        and worst_trade >= WORST_TRADE_FLOOR
    )
    passes_all = (
        survives_tail
        and operational_ok
        and liq_buffer_multiple >= LIQ_BUFFER_FLOOR
        and max_frac_for_stress <= FRAC_CAP + 1e-6
    )

    return ConfigResult(
        label=label,
        stop_pct=stop_pct,
        risk_pct=risk_pct,
        base_frac=base_frac,
        max_frac_realized=max_frac_for_stress,
        use_dynamic=use_dynamic,
        use_adaptive=use_adaptive,
        num_trades=total_trades,
        stops_fired=stops_fired,
        stop_rate=stop_rate,
        oos_return=ret,
        ending_equity_usd=ending_equity,
        max_dd=dd,
        max_dd_usd=dd_usd,
        profit_factor=pf,
        worst_trade_pnl=worst_trade,
        worst_trade_usd=worst_trade_usd,
        worst_adverse_move=worst_adv,
        liq_distance=liq_distance,
        liq_buffer_multiple=liq_buffer_multiple,
        tail_shock_loss_frac=tail_loss,
        survives_tail=survives_tail,
        operational_realism_ok=operational_ok,
        passes_all_constraints=passes_all,
    )


def format_row(r: ConfigResult) -> str:
    notional = STARTING_EQUITY_USD * r.max_frac_realized
    return (
        f"{r.label:<42} "
        f"stop={r.stop_pct*100:>4.2f}% risk={r.risk_pct*100:>4.2f}% "
        f"frac={r.max_frac_realized:>5.3f} "
        f"notional=${notional:>7,.0f} "
        f"n={r.num_trades:>3d} "
        f"ret={r.oos_return*100:>+7.2f}% "
        f"end=${r.ending_equity_usd:>9,.0f} "
        f"dd={r.max_dd*100:>5.2f}%(${r.max_dd_usd:>6,.0f}) "
        f"pf={r.profit_factor:>4.2f} "
        f"wt={r.worst_trade_pnl*100:>+6.2f}%(${r.worst_trade_usd:>7,.0f}) "
        f"stops={r.stops_fired:>2d}/{r.num_trades:>2d} ({r.stop_rate*100:>5.1f}%) "
        f"liq_buf={r.liq_buffer_multiple:>4.2f}x "
        f"tail_loss={r.tail_shock_loss_frac*100:>5.1f}% "
        f"{'PASS' if r.passes_all_constraints else 'FAIL'}"
    )


def main() -> None:
    print("=" * 78)
    print("Phase 8 FINAL search — D1_long leveraged futures optimizer")
    print(f"Starting equity: ${STARTING_EQUITY_USD:,.0f}")
    print(f"Exchange leverage: {EXCHANGE_LEVERAGE:g}x (isolated)")
    print(f"Hard constraints: frac<={FRAC_CAP}, stop_rate<={STOP_RATE_CEILING*100:.0f}%, "
          f"worst_trade>={WORST_TRADE_FLOOR*100:.0f}%, liq_buffer>={LIQ_BUFFER_FLOOR:.1f}x")
    print("=" * 78)

    print("\nLoading data...")
    funding = load_funding_csv(FUNDING_CSV)
    tf = load_timeframe_data("4h", KLINES_4H, 4.0, funding)
    closes = [f.close for f in tf.features]
    rsi20 = rsi_series(closes, 20)
    sigs = rsi_only_signals(tf.features, rsi_period=20, rsi_override=rsi20)
    sigs = apply_side_filter(sigs, side="long")
    print(f"  bars={len(tf.bars):,} splits={len(tf.splits)} signals={sum(1 for s in sigs if s)}")

    # Search grid
    # For each variant, test several (stop, risk) combos targeting frac ≤ 2.0
    #
    # VARIANT 1 — fixed sizing, target max frac = 2.0
    v1_configs = [
        # Canonical reference
        ("V1_fixed_s1.5_r3.0_f2.0", 0.015, 0.030),
        # Tighter stop, same frac
        ("V1_fixed_s1.0_r2.0_f2.0", 0.010, 0.020),
        ("V1_fixed_s1.25_r2.5_f2.0", 0.0125, 0.025),
        # Looser stop, same frac
        ("V1_fixed_s2.0_r4.0_f2.0", 0.020, 0.040),
        ("V1_fixed_s2.5_r5.0_f2.0", 0.025, 0.050),
        # Canonical baseline (frac=1.333) for reference
        ("V1_fixed_s1.5_r2.0_f1.333", 0.015, 0.020),
    ]
    # VARIANT 2 — dynamic sizing on
    # Dynamic multiplier [0.5, 1.5]; base should allow upside to hit 2.0 cap
    # base=1.333 → range [0.667, 2.0] — full dynamic under cap
    # base=1.5   → range [0.75, 2.25] — upside clipped at 2.0 on max-conviction bars
    # base=2.0   → range [1.0, 2.0] — only downside dynamic, no upside
    v2_configs = [
        ("V2_dyn_s1.5_r2.0_base1.333", 0.015, 0.020),
        ("V2_dyn_s1.0_r1.333_base1.333", 0.010, 0.01333),
        ("V2_dyn_s2.0_r2.667_base1.333", 0.020, 0.02667),
        # Try higher base (clipped)
        ("V2_dyn_s1.5_r2.25_base1.5", 0.015, 0.0225),
        ("V2_dyn_s1.5_r2.667_base1.777", 0.015, 0.02667),
        ("V2_dyn_s1.5_r3.0_base2.0", 0.015, 0.030),
        # Tight-stop variant matching V1 winner
        ("V2_dyn_s1.25_r2.5_base2.0", 0.0125, 0.025),
    ]
    # VARIANT 3 — dynamic sizing + adaptive hold
    v3_configs = [
        ("V3_dyn_adap_s1.5_r2.0_base1.333", 0.015, 0.020),
        ("V3_dyn_adap_s1.0_r1.333_base1.333", 0.010, 0.01333),
        ("V3_dyn_adap_s2.0_r2.667_base1.333", 0.020, 0.02667),
        ("V3_dyn_adap_s1.5_r2.25_base1.5", 0.015, 0.0225),
        ("V3_dyn_adap_s1.5_r3.0_base2.0", 0.015, 0.030),
        # Tight-stop variant matching V1 winner
        ("V3_dyn_adap_s1.25_r2.5_base2.0", 0.0125, 0.025),
    ]

    results: list[ConfigResult] = []

    print("\n" + "=" * 78)
    print("VARIANT 1 — D1_long fixed sizing")
    print("=" * 78)
    for label, stop, risk in v1_configs:
        r = run_config(
            label=label,
            stop_pct=stop,
            risk_pct=risk,
            use_dynamic=False,
            use_adaptive=False,
            tf=tf,
            signals_base=sigs,
        )
        results.append(r)
        print(format_row(r))

    print("\n" + "=" * 78)
    print("VARIANT 2 — D1_long + dynamic sizing")
    print("=" * 78)
    for label, stop, risk in v2_configs:
        r = run_config(
            label=label,
            stop_pct=stop,
            risk_pct=risk,
            use_dynamic=True,
            use_adaptive=False,
            tf=tf,
            signals_base=sigs,
        )
        results.append(r)
        print(format_row(r))

    print("\n" + "=" * 78)
    print("VARIANT 3 — D1_long + dynamic sizing + adaptive exit")
    print("=" * 78)
    for label, stop, risk in v3_configs:
        r = run_config(
            label=label,
            stop_pct=stop,
            risk_pct=risk,
            use_dynamic=True,
            use_adaptive=True,
            tf=tf,
            signals_base=sigs,
        )
        results.append(r)
        print(format_row(r))

    # Filter to passing configs and pick best per variant
    print("\n" + "=" * 78)
    print("CONSTRAINT-PASSING CONFIGS ONLY (ranked by OOS return)")
    print("=" * 78)
    passing = [r for r in results if r.passes_all_constraints]
    passing.sort(key=lambda r: r.oos_return, reverse=True)
    for r in passing:
        print(format_row(r))

    # Per-variant best
    print("\n" + "=" * 78)
    print("BEST-PER-VARIANT SUMMARY (constraint-passing only)")
    print("=" * 78)
    for variant_tag in ("V1_", "V2_", "V3_"):
        subset = [r for r in passing if r.label.startswith(variant_tag)]
        if subset:
            best = max(subset, key=lambda r: r.oos_return)
            print(f"\n[{variant_tag}] best:")
            print("  " + format_row(best))
        else:
            print(f"\n[{variant_tag}] NO constraint-passing config")


if __name__ == "__main__":
    main()
