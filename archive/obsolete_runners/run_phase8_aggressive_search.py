"""Phase 8 AGGRESSIVE search — D1 family push to 3x/4x/5x notional.

Mainline: D1 (rsi_only_20), variants long_only + both.
Dual-stop architecture: alpha (close-trigger) + catastrophe (intrabar wick).
Leverage sweep: 3x / 4x / 5x / 6x exchange leverage, max_frac up to 5.0.

All results reported at portfolio_allocation = 1.0, starting equity
= $10,000, against the Phase B stress suite defined in
`strategy_c_v2_stress_test`.

Writes:
  strategy_c_v2_phase8_aggressive_sweep.csv — full grid with metrics

Columns (Phase D contract):
  variant (V1/V2/V3), direction_mode, base_hold_bars, alpha_stop_pct,
  catastrophe_stop_pct, risk_per_trade, base_frac, max_frac,
  exchange_leverage, use_dynamic, use_adaptive,
  num_trades, win_rate, profit_factor, oos_return, ending_equity_usd,
  max_dd_pct, max_dd_usd, worst_trade_pct, worst_trade_usd,
  avg_stopped_loss, stop_exit_fraction, alpha_stop_count,
  catastrophe_stop_count, avg_actual_frac, max_actual_frac,
  worst_adverse_move, liquidation_adverse_move, liq_buffer_multiple,
  historical_liquidated, shock_10, shock_15, shock_20, shock_30,
  shock_40, slip_01, slip_03, slip_05, slip_10, shortlist_pass,
  shortlist_reason
"""
from __future__ import annotations

import csv
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, "src")

from data.strategy_c_v2_features import rsi_series
from research.strategy_c_v2_backtest import run_v2_backtest
from research.strategy_c_v2_runner import (
    combined_profit_factor,
    load_funding_csv,
    load_timeframe_data,
    stitch_equity,
)
from research.strategy_c_v2_stress_test import (
    StressConfig,
    run_stress_suite,
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
FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001

OUTPUT_CSV = Path("strategy_c_v2_phase8_aggressive_sweep.csv")


@dataclass
class CellResult:
    variant: str
    direction_mode: str
    base_hold_bars: int
    alpha_stop_pct: float
    catastrophe_stop_pct: float
    risk_per_trade: float
    base_frac: float
    max_frac: float
    exchange_leverage: float
    use_dynamic: bool
    use_adaptive: bool
    # metrics
    num_trades: int
    num_wins: int
    win_rate: float
    profit_factor: float
    oos_return: float
    ending_equity_usd: float
    max_dd_pct: float
    max_dd_usd: float
    worst_trade_pnl: float
    worst_trade_usd: float
    avg_stopped_loss: float
    stop_exit_fraction: float
    alpha_stop_count: int
    catastrophe_stop_count: int
    time_stop_count: int
    flip_exit_count: int
    avg_actual_frac: float
    max_actual_frac: float
    worst_adverse_move: float
    liquidation_adverse_move: float
    liq_buffer_multiple: float
    # stress verdicts (only populated for shortlist-eligible cells)
    historical_liquidated: bool
    shock_10_verdict: str
    shock_15_verdict: str
    shock_20_verdict: str
    shock_30_verdict: str
    shock_40_verdict: str
    slip_01_delta_pp: float
    slip_03_delta_pp: float
    slip_05_delta_pp: float
    slip_10_delta_pp: float
    slip_10_acceptable: bool
    shortlist_pass: bool
    shortlist_reason: str


def compute_signals(features, direction_mode: str) -> list[int]:
    """Build D1 signal stream with the requested direction mode.

    - long_only: rsi_only_20 > 70 → +1, else 0 (shorts zeroed)
    - both: rsi_only_20 > 70 → +1, rsi_only_20 < 30 → -1
    """
    closes = [f.close for f in features]
    rsi20 = rsi_series(closes, 20)
    sigs = rsi_only_signals(features, rsi_period=20, rsi_override=rsi20)
    if direction_mode == "long_only":
        sigs = apply_side_filter(sigs, side="long")
    elif direction_mode == "both":
        pass  # keep both sides
    else:
        raise ValueError(f"unknown direction_mode: {direction_mode!r}")
    return sigs


def build_sizing_override(
    features,
    signals,
    base_frac: float,
    max_frac: float,
    use_dynamic: bool,
) -> list[float | None]:
    """Build a per-signal frac override clipped at max_frac."""
    if use_dynamic:
        raw = compute_position_frac_override(features, signals, base_frac)
        return [
            min(v, max_frac) if v is not None else None
            for v in raw
        ]
    out: list[float | None] = [None] * len(features)
    for i, s in enumerate(signals):
        if s != 0:
            out[i] = min(base_frac, max_frac)
    return out


def compute_dollar_drawdown(curve: list[float]) -> float:
    if not curve:
        return 0.0
    peak_usd = STARTING_EQUITY_USD
    worst = 0.0
    for point in curve:
        eq = STARTING_EQUITY_USD * point
        if eq > peak_usd:
            peak_usd = eq
        drop = peak_usd - eq
        if drop > worst:
            worst = drop
    return worst


def max_dd_of(curve: list[float]) -> float:
    if not curve:
        return 0.0
    peak = curve[0]
    dd = 0.0
    for e in curve:
        if e > peak:
            peak = e
        if peak > 0:
            d = (peak - e) / peak
            if d > dd:
                dd = d
    return dd


def run_cell(
    *,
    variant: str,
    direction_mode: str,
    base_hold_bars: int,
    alpha_stop_pct: float,
    catastrophe_stop_pct: float,
    risk_per_trade: float,
    base_frac: float,
    max_frac: float,
    exchange_leverage: float,
    use_dynamic: bool,
    use_adaptive: bool,
    tf,
    signals_by_direction: dict[str, list[int]],
) -> CellResult:
    signals = signals_by_direction[direction_mode]

    override_frac = build_sizing_override(
        tf.features, signals, base_frac, max_frac, use_dynamic
    )
    override_hold = None
    if use_adaptive:
        override_hold = compute_hold_bars_override_vector(
            tf.features, signals, base_hold_bars
        )

    per_curves: list[list[float]] = []
    all_pnls: list[float] = []
    all_adv: list[float] = []
    all_actual_frac: list[float] = []
    stopped_losses: list[float] = []
    exit_counts = {
        "alpha_stop_long": 0,
        "alpha_stop_short": 0,
        "catastrophe_stop_long": 0,
        "catastrophe_stop_short": 0,
        "time_stop": 0,
        "opposite_flip": 0,
        "end_of_series": 0,
    }
    num_trades = 0
    num_wins = 0

    for split in tf.splits:
        test_bars = tf.bars[split.test_lo : split.test_hi]
        test_signals = signals[split.test_lo : split.test_hi]
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
            hold_bars=base_hold_bars,
            fee_per_side=FEE_PER_SIDE,
            slip_per_side=SLIP_PER_SIDE,
            alpha_stop_pct=alpha_stop_pct,
            catastrophe_stop_pct=catastrophe_stop_pct,
            risk_per_trade=risk_per_trade,
            effective_leverage=max_frac,  # cap default at max_frac
            position_frac_override=test_ovr_frac,
            hold_bars_override=test_ovr_hold,
        )
        per_curves.append(bt.equity_curve)
        for t in bt.trades:
            all_pnls.append(t.net_pnl)
            num_trades += 1
            if t.net_pnl > 0:
                num_wins += 1
            # Track actual frac per trade (from override or default)
            # The override is what we built; if it's None at this bar,
            # use default_position_frac from the backtest:
            i = t.entry_idx - 1  # signal bar
            if 0 <= i < len(test_ovr_frac) and test_ovr_frac[i] is not None:
                frac_used = test_ovr_frac[i]
            else:
                frac_used = min(risk_per_trade / alpha_stop_pct, max_frac)
            all_actual_frac.append(frac_used)
            # Exit reason counting
            key = t.exit_reason
            if key not in exit_counts:
                exit_counts[key] = 0
            exit_counts[key] += 1
            if key.startswith(("alpha_stop", "catastrophe_stop")):
                stopped_losses.append(t.net_pnl)
            # Worst adverse move
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

    curve = stitch_equity(per_curves)
    oos_return = (curve[-1] - 1.0) if curve else 0.0
    ending_equity = STARTING_EQUITY_USD * (1 + oos_return)
    dd = max_dd_of(curve)
    dd_usd = compute_dollar_drawdown(curve)
    pf = combined_profit_factor(all_pnls)
    worst_trade = min(all_pnls) if all_pnls else 0.0
    worst_trade_usd = worst_trade * STARTING_EQUITY_USD
    worst_adv = max(all_adv) if all_adv else 0.0
    avg_stopped = (
        sum(stopped_losses) / len(stopped_losses)
        if stopped_losses
        else 0.0
    )
    alpha_count = (
        exit_counts.get("alpha_stop_long", 0)
        + exit_counts.get("alpha_stop_short", 0)
    )
    catastrophe_count = (
        exit_counts.get("catastrophe_stop_long", 0)
        + exit_counts.get("catastrophe_stop_short", 0)
    )
    total_stops = alpha_count + catastrophe_count
    stop_frac = total_stops / num_trades if num_trades else 0.0
    avg_frac = (
        sum(all_actual_frac) / len(all_actual_frac)
        if all_actual_frac
        else 0.0
    )
    max_frac_obs = max(all_actual_frac) if all_actual_frac else 0.0
    win_rate = num_wins / num_trades if num_trades else 0.0

    # Liquidation math
    liq_distance = 1.0 / exchange_leverage
    liq_buffer = (
        liq_distance / worst_adv if worst_adv > 0 else float("inf")
    )

    # Run the Phase B stress suite
    verdict = run_stress_suite(
        config=StressConfig(
            exchange_leverage=exchange_leverage,
            max_actual_frac=max_frac_obs if max_frac_obs > 0 else max_frac,
            starting_equity_usd=STARTING_EQUITY_USD,
        ),
        historical_max_adverse=worst_adv,
        num_trades=num_trades,
        num_stop_exits=total_stops,
        avg_actual_frac=avg_frac,
        baseline_return_pct=oos_return * 100.0,
        profit_factor=pf,
        win_rate=win_rate,
    )

    shock_verdicts = {sr.shock_pct: sr.verdict for sr in verdict.shock_results}
    slip_deltas = {sr.slip_pct: sr.return_delta_pp for sr in verdict.slippage_results}
    slip_10_sr = next(
        (sr for sr in verdict.slippage_results if sr.slip_pct == 0.01),
        None,
    )
    slip_10_acceptable = slip_10_sr.operationally_acceptable if slip_10_sr else False

    return CellResult(
        variant=variant,
        direction_mode=direction_mode,
        base_hold_bars=base_hold_bars,
        alpha_stop_pct=alpha_stop_pct,
        catastrophe_stop_pct=catastrophe_stop_pct,
        risk_per_trade=risk_per_trade,
        base_frac=base_frac,
        max_frac=max_frac,
        exchange_leverage=exchange_leverage,
        use_dynamic=use_dynamic,
        use_adaptive=use_adaptive,
        num_trades=num_trades,
        num_wins=num_wins,
        win_rate=win_rate,
        profit_factor=pf,
        oos_return=oos_return,
        ending_equity_usd=ending_equity,
        max_dd_pct=dd,
        max_dd_usd=dd_usd,
        worst_trade_pnl=worst_trade,
        worst_trade_usd=worst_trade_usd,
        avg_stopped_loss=avg_stopped,
        stop_exit_fraction=stop_frac,
        alpha_stop_count=alpha_count,
        catastrophe_stop_count=catastrophe_count,
        time_stop_count=exit_counts.get("time_stop", 0),
        flip_exit_count=exit_counts.get("opposite_flip", 0),
        avg_actual_frac=avg_frac,
        max_actual_frac=max_frac_obs,
        worst_adverse_move=worst_adv,
        liquidation_adverse_move=liq_distance,
        liq_buffer_multiple=liq_buffer,
        historical_liquidated=verdict.historical_liquidated,
        shock_10_verdict=shock_verdicts.get(0.10, "?"),
        shock_15_verdict=shock_verdicts.get(0.15, "?"),
        shock_20_verdict=shock_verdicts.get(0.20, "?"),
        shock_30_verdict=shock_verdicts.get(0.30, "?"),
        shock_40_verdict=shock_verdicts.get(0.40, "?"),
        slip_01_delta_pp=slip_deltas.get(0.001, 0.0),
        slip_03_delta_pp=slip_deltas.get(0.003, 0.0),
        slip_05_delta_pp=slip_deltas.get(0.005, 0.0),
        slip_10_delta_pp=slip_deltas.get(0.010, 0.0),
        slip_10_acceptable=slip_10_acceptable,
        shortlist_pass=verdict.shortlist_pass,
        shortlist_reason=verdict.shortlist_reason,
    )


def build_grid() -> list[dict[str, Any]]:
    """Phase A search grid.

    Instead of testing the full cartesian product (~170k configs),
    we test a focused subset that covers the key tradeoffs the brief
    calls out. The grid is explicitly enumerated here so the user
    can see exactly what was tested.

    The grid spans:
        - 2 direction modes
        - 3 hold values (10, 11, 12 — around the canonical 11)
        - 3 alpha stops (1.0%, 1.25%, 1.5% — from the tighter end
          where earlier runs showed better risk-adjusted return)
        - 4 catastrophe stops (2.0%, 2.5%, 3.0%, — wider than alpha)
        - 3 risks (2.5%, 3.5%, 4.5%)
        - 3 (base_frac, max_frac, exchange_leverage) tier tuples
          targeting 3x / 4x / 5x actual notional
        - 3 variants (V1 fixed, V2 +dynamic, V3 +dynamic +adaptive)

    For each cell, the sizing formula `risk / alpha_stop` must be
    between 1.0 and max_frac to be included (otherwise it's
    operationally meaningless).
    """
    grid: list[dict[str, Any]] = []

    # Tier tuples: (tier_label, base_frac, max_frac, exchange_leverage)
    # Match the brief's search axes. Use "exchange_leverage >= max_frac"
    # as the isolated-margin constraint (fully-margined max).
    tiers = [
        # 2x safe floor (comparison anchor with prior Phase 8 results)
        ("2x", 1.333, 2.0, 2.0),
        ("2x", 2.0, 2.0, 2.0),
        # 3x target
        ("3x", 2.0, 3.0, 3.0),
        ("3x", 2.5, 3.0, 3.0),
        ("3x", 2.0, 3.0, 4.0),
        # 4x target
        ("4x", 2.5, 4.0, 4.0),
        ("4x", 3.0, 4.0, 4.0),
        ("4x", 2.67, 4.0, 5.0),
        # 5x target
        ("5x", 3.0, 5.0, 5.0),
        ("5x", 3.33, 5.0, 5.0),
        ("5x", 3.0, 5.0, 6.0),
    ]

    direction_modes = ("long_only", "both")
    holds = (10, 11, 12)
    alpha_stops = (0.010, 0.0125, 0.015)
    catastrophe_stops = (0.020, 0.025, 0.030)
    risks = (0.025, 0.035, 0.045)
    variants = (
        ("V1", False, False),
        ("V2", True, False),
        ("V3", True, True),
    )

    for direction in direction_modes:
        for hold in holds:
            for alpha in alpha_stops:
                for catastrophe in catastrophe_stops:
                    if catastrophe <= alpha:
                        continue
                    for risk in risks:
                        implied_base_frac = risk / alpha
                        for tier_name, base_frac, max_frac, lev in tiers:
                            # Skip if implied base_frac from risk/alpha
                            # doesn't match the tier base_frac within
                            # 0.3 tolerance (we want risk/stop to drive
                            # the sizing ladder)
                            if abs(implied_base_frac - base_frac) > 0.3:
                                continue
                            for variant_name, use_dyn, use_adap in variants:
                                grid.append({
                                    "variant": variant_name,
                                    "direction_mode": direction,
                                    "base_hold_bars": hold,
                                    "alpha_stop_pct": alpha,
                                    "catastrophe_stop_pct": catastrophe,
                                    "risk_per_trade": risk,
                                    "base_frac": base_frac,
                                    "max_frac": max_frac,
                                    "exchange_leverage": lev,
                                    "use_dynamic": use_dyn,
                                    "use_adaptive": use_adap,
                                    "tier_label": tier_name,
                                })
    return grid


def write_csv(path: Path, results: list[CellResult]) -> None:
    if not results:
        return
    fieldnames = list(asdict(results[0]).keys())
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            w.writerow(asdict(r))
    print(f"\nWrote {path} ({len(results)} rows)")


def main() -> None:
    print("=" * 78)
    print("Phase 8 AGGRESSIVE search — D1 family 3x/4x/5x push")
    print(f"Starting equity: ${STARTING_EQUITY_USD:,.0f}")
    print("=" * 78)

    print("\nLoading data...")
    t0 = time.time()
    funding = load_funding_csv(FUNDING_CSV)
    tf = load_timeframe_data("4h", KLINES_4H, 4.0, funding)
    print(f"  bars={len(tf.bars):,} splits={len(tf.splits)} "
          f"({time.time()-t0:.1f}s)")

    # Precompute signals per direction mode (avoid redundant rsi work)
    signals_by_direction = {
        "long_only": compute_signals(tf.features, "long_only"),
        "both": compute_signals(tf.features, "both"),
    }
    for d, sigs in signals_by_direction.items():
        pos = sum(1 for s in sigs if s > 0)
        neg = sum(1 for s in sigs if s < 0)
        print(f"  {d}: {pos} long + {neg} short signals")

    grid = build_grid()
    print(f"\nGrid size: {len(grid)} configs")

    results: list[CellResult] = []
    t1 = time.time()
    for i, cfg in enumerate(grid):
        tier = cfg.pop("tier_label")  # not a run_cell param
        r = run_cell(
            **cfg,
            tf=tf,
            signals_by_direction=signals_by_direction,
        )
        results.append(r)
        if (i + 1) % 50 == 0 or (i + 1) == len(grid):
            elapsed = time.time() - t1
            rate = (i + 1) / elapsed
            eta = (len(grid) - (i + 1)) / rate
            print(f"  [{i + 1}/{len(grid)}] "
                  f"elapsed={elapsed:.0f}s rate={rate:.1f}/s eta={eta:.0f}s")

    write_csv(OUTPUT_CSV, results)

    # Summary: shortlist pass rate and top 20 by OOS return
    passing = [r for r in results if r.shortlist_pass]
    passing.sort(key=lambda r: r.oos_return, reverse=True)
    print(f"\nShortlist pass: {len(passing)}/{len(results)}")
    print("\nTop 20 shortlist-passing configs (by OOS return):")
    print(f"{'variant':<4} {'dir':<10} {'hold':<5} {'aS':<6} {'cS':<6} "
          f"{'risk':<6} {'bf':<5} {'mf':<5} {'L':<4} {'dyn':<4} {'adp':<4} "
          f"{'trades':<7} {'wr':<7} {'PF':<5} {'ret':<9} {'DD':<7} "
          f"{'sh40':<14}")
    for r in passing[:20]:
        print(f"{r.variant:<4} {r.direction_mode:<10} {r.base_hold_bars:<5} "
              f"{r.alpha_stop_pct*100:>4.2f}% {r.catastrophe_stop_pct*100:>4.2f}% "
              f"{r.risk_per_trade*100:>4.1f}% {r.base_frac:<5} {r.max_frac:<5} "
              f"{r.exchange_leverage:<4} {str(r.use_dynamic):<4} "
              f"{str(r.use_adaptive):<4} "
              f"{r.num_trades:<7} {r.win_rate*100:>5.1f}% {r.profit_factor:<5.2f} "
              f"{r.oos_return*100:>+7.1f}% {r.max_dd_pct*100:>5.1f}% "
              f"{r.shock_40_verdict:<14}")


if __name__ == "__main__":
    main()
