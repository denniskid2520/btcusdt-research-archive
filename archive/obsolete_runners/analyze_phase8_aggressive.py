"""Phase 8 aggressive search post-hoc analysis.

Reads `strategy_c_v2_phase8_aggressive_sweep.csv` and produces:

  1. Strict-filter pass count (Phase 8 hard filters as written)
  2. Near-miss frontier at each relaxation level
  3. Blocking-constraint identification per tier (2x / 3x / 4x / 5x)
  4. Per-tier top candidates
  5. Final optimized + fallback configs

The strict filters are:
  - trade count >= 100
  - profit factor >= 2.0
  - win rate >= 55%
  - no historical liquidation
  - 1.0% slippage must not collapse the strategy (delta >= -50pp)

Relaxed filter modes:
  - R1: trade count >= 70 (long-only 4h realistic)
  - R2: R1 + slippage bar lowered to 0.5%
  - R3: R2 + trade count >= 60 (allow tightest stops)
"""
from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


CSV_PATH = Path("strategy_c_v2_phase8_aggressive_sweep.csv")
STARTING_EQUITY_USD = 10_000.0


@dataclass
class Row:
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

    @property
    def tier(self) -> str:
        if self.exchange_leverage == 2.0:
            return "2x"
        if self.exchange_leverage == 3.0:
            return "3x"
        if self.exchange_leverage == 4.0:
            return "4x"
        if self.exchange_leverage in (5.0, 6.0):
            return "5x"
        return f"{self.exchange_leverage:g}x"

    @property
    def notional_usd(self) -> float:
        return STARTING_EQUITY_USD * self.max_actual_frac


def load_rows(path: Path = CSV_PATH) -> list[Row]:
    out: list[Row] = []
    with path.open("r", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            out.append(Row(
                variant=r["variant"],
                direction_mode=r["direction_mode"],
                base_hold_bars=int(r["base_hold_bars"]),
                alpha_stop_pct=float(r["alpha_stop_pct"]),
                catastrophe_stop_pct=float(r["catastrophe_stop_pct"]),
                risk_per_trade=float(r["risk_per_trade"]),
                base_frac=float(r["base_frac"]),
                max_frac=float(r["max_frac"]),
                exchange_leverage=float(r["exchange_leverage"]),
                use_dynamic=r["use_dynamic"].lower() == "true",
                use_adaptive=r["use_adaptive"].lower() == "true",
                num_trades=int(r["num_trades"]),
                num_wins=int(r["num_wins"]),
                win_rate=float(r["win_rate"]),
                profit_factor=float(r["profit_factor"]),
                oos_return=float(r["oos_return"]),
                ending_equity_usd=float(r["ending_equity_usd"]),
                max_dd_pct=float(r["max_dd_pct"]),
                max_dd_usd=float(r["max_dd_usd"]),
                worst_trade_pnl=float(r["worst_trade_pnl"]),
                worst_trade_usd=float(r["worst_trade_usd"]),
                avg_stopped_loss=float(r["avg_stopped_loss"]),
                stop_exit_fraction=float(r["stop_exit_fraction"]),
                alpha_stop_count=int(r["alpha_stop_count"]),
                catastrophe_stop_count=int(r["catastrophe_stop_count"]),
                time_stop_count=int(r["time_stop_count"]),
                flip_exit_count=int(r["flip_exit_count"]),
                avg_actual_frac=float(r["avg_actual_frac"]),
                max_actual_frac=float(r["max_actual_frac"]),
                worst_adverse_move=float(r["worst_adverse_move"]),
                liquidation_adverse_move=float(r["liquidation_adverse_move"]),
                liq_buffer_multiple=(
                    float(r["liq_buffer_multiple"])
                    if r["liq_buffer_multiple"] not in ("inf", "")
                    else float("inf")
                ),
                historical_liquidated=r["historical_liquidated"].lower() == "true",
                shock_10_verdict=r["shock_10_verdict"],
                shock_15_verdict=r["shock_15_verdict"],
                shock_20_verdict=r["shock_20_verdict"],
                shock_30_verdict=r["shock_30_verdict"],
                shock_40_verdict=r["shock_40_verdict"],
                slip_01_delta_pp=float(r["slip_01_delta_pp"]),
                slip_03_delta_pp=float(r["slip_03_delta_pp"]),
                slip_05_delta_pp=float(r["slip_05_delta_pp"]),
                slip_10_delta_pp=float(r["slip_10_delta_pp"]),
                slip_10_acceptable=r["slip_10_acceptable"].lower() == "true",
                shortlist_pass=r["shortlist_pass"].lower() == "true",
                shortlist_reason=r["shortlist_reason"],
            ))
    return out


# ── filters ────────────────────────────────────────────────────────


def strict_filter(r: Row) -> bool:
    return (
        r.num_trades >= 100
        and r.profit_factor >= 2.0
        and r.win_rate >= 0.55
        and not r.historical_liquidated
        and r.slip_10_acceptable
    )


def r1_filter(r: Row) -> bool:
    """Realistic long-only trade count (>=70), everything else strict."""
    return (
        r.num_trades >= 70
        and r.profit_factor >= 2.0
        and r.win_rate >= 0.55
        and not r.historical_liquidated
        and r.slip_10_acceptable
    )


def r2_filter(r: Row) -> bool:
    """R1 with 0.5% slippage as the acceptance bar (vs 1.0%)."""
    return (
        r.num_trades >= 70
        and r.profit_factor >= 2.0
        and r.win_rate >= 0.55
        and not r.historical_liquidated
        and r.slip_05_delta_pp >= -50.0
    )


def r3_filter(r: Row) -> bool:
    """R2 with trade count >= 60."""
    return (
        r.num_trades >= 60
        and r.profit_factor >= 2.0
        and r.win_rate >= 0.55
        and not r.historical_liquidated
        and r.slip_05_delta_pp >= -50.0
    )


def no_filter(r: Row) -> bool:
    return True


# ── blocking constraint identification ────────────────────────────


def identify_blocker(r: Row) -> list[str]:
    blockers = []
    if r.num_trades < 100:
        blockers.append(f"trades {r.num_trades}<100")
    if r.profit_factor < 2.0:
        blockers.append(f"PF {r.profit_factor:.2f}<2.0")
    if r.win_rate < 0.55:
        blockers.append(f"WR {r.win_rate*100:.1f}%<55%")
    if r.historical_liquidated:
        blockers.append(
            f"liquidated (worst_adv {r.worst_adverse_move*100:.1f}% >= liq {r.liquidation_adverse_move*100:.1f}%)"
        )
    if not r.slip_10_acceptable:
        blockers.append(
            f"1% slip collapses by {r.slip_10_delta_pp:+.0f}pp"
        )
    return blockers


# ── reporting helpers ─────────────────────────────────────────────


def format_row(r: Row) -> str:
    return (
        f"{r.variant:<3} {r.tier:<3} {r.direction_mode:<10} "
        f"h={r.base_hold_bars:<3} aS={r.alpha_stop_pct*100:.2f}% "
        f"cS={r.catastrophe_stop_pct*100:.2f}% "
        f"r={r.risk_per_trade*100:.1f}% "
        f"bf={r.base_frac:<5} mf={r.max_frac:<4} L={r.exchange_leverage:<3} "
        f"dyn={str(r.use_dynamic):<5} adp={str(r.use_adaptive):<5} | "
        f"n={r.num_trades:>3} WR={r.win_rate*100:>5.1f}% "
        f"PF={r.profit_factor:>4.2f} ret={r.oos_return*100:>+7.1f}% "
        f"end=${r.ending_equity_usd:>8,.0f} "
        f"DD={r.max_dd_pct*100:>5.1f}%(${r.max_dd_usd:>6,.0f}) "
        f"wt={r.worst_trade_pnl*100:>+5.1f}%(${r.worst_trade_usd:>7,.0f}) "
        f"slip1%={r.slip_10_delta_pp:>+6.0f}pp "
        f"shk40={r.shock_40_verdict[:4]}"
    )


def top_n_by_return(
    rows: list[Row],
    n: int,
    predicate: Callable[[Row], bool] = no_filter,
) -> list[Row]:
    filtered = [r for r in rows if predicate(r)]
    filtered.sort(key=lambda x: x.oos_return, reverse=True)
    return filtered[:n]


def top_n_per_tier(
    rows: list[Row],
    n: int,
    predicate: Callable[[Row], bool] = no_filter,
) -> dict[str, list[Row]]:
    by_tier: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        if predicate(r):
            by_tier[r.tier].append(r)
    for tier in by_tier:
        by_tier[tier].sort(key=lambda x: x.oos_return, reverse=True)
        by_tier[tier] = by_tier[tier][:n]
    return by_tier


# ── main ──────────────────────────────────────────────────────────


def main() -> None:
    rows = load_rows()
    print(f"Loaded {len(rows)} configs from {CSV_PATH}\n")

    # ── 1. Strict-filter pass count ──
    strict_pass = [r for r in rows if strict_filter(r)]
    print(f"STRICT filters pass: {len(strict_pass)}/{len(rows)}")
    if strict_pass:
        print("\nStrict-filter winners (top 10 by OOS return):")
        for r in top_n_by_return(rows, 10, strict_filter):
            print("  " + format_row(r))

    # ── 2. R1 (realistic trade count, strict quality + slip) ──
    r1_pass = [r for r in rows if r1_filter(r)]
    print(f"\nR1 filters (trades>=70) pass: {len(r1_pass)}/{len(rows)}")
    if r1_pass:
        print("\nR1 winners (top 15 by OOS return):")
        for r in top_n_by_return(rows, 15, r1_filter):
            print("  " + format_row(r))

    # ── 3. R2 (trades>=70, 0.5% slip) ──
    r2_pass = [r for r in rows if r2_filter(r)]
    print(f"\nR2 filters (trades>=70, 0.5% slip) pass: {len(r2_pass)}/{len(rows)}")

    # ── 4. R3 (trades>=60, 0.5% slip) ──
    r3_pass = [r for r in rows if r3_filter(r)]
    print(f"R3 filters (trades>=60, 0.5% slip) pass: {len(r3_pass)}/{len(rows)}")

    # ── 5. Per-tier top candidates ──
    print("\n" + "=" * 78)
    print("PER-TIER TOP CANDIDATES (R1 filter: trades>=70, PF>=2.0, WR>=55%, no liq, 1% slip OK)")
    print("=" * 78)
    per_tier_r1 = top_n_per_tier(rows, 5, r1_filter)
    for tier in ["2x", "3x", "4x", "5x"]:
        candidates = per_tier_r1.get(tier, [])
        print(f"\n--- {tier} tier ---")
        if not candidates:
            print(f"  NO R1-passing candidates at {tier}")
        else:
            for r in candidates:
                print("  " + format_row(r))

    # ── 6. Per-tier top candidates at ANY filter (to show frontier) ──
    print("\n" + "=" * 78)
    print("PER-TIER TOP BY RAW RETURN (no filters — shows headline numbers)")
    print("=" * 78)
    per_tier_raw = top_n_per_tier(rows, 5, no_filter)
    for tier in ["2x", "3x", "4x", "5x"]:
        candidates = per_tier_raw.get(tier, [])
        print(f"\n--- {tier} tier raw frontier ---")
        for r in candidates:
            print("  " + format_row(r))

    # ── 7. Blocking-constraint identification per tier ──
    print("\n" + "=" * 78)
    print("BLOCKING CONSTRAINTS PER TIER (top return in each tier, why it fails strict)")
    print("=" * 78)
    for tier in ["2x", "3x", "4x", "5x"]:
        tier_rows = [r for r in rows if r.tier == tier]
        if not tier_rows:
            continue
        tier_rows.sort(key=lambda x: x.oos_return, reverse=True)
        print(f"\n--- {tier} top-5 by return (blocker → strict fail reason) ---")
        for r in tier_rows[:5]:
            blockers = identify_blocker(r)
            label = f"{r.variant} {r.direction_mode} h{r.base_hold_bars} aS{r.alpha_stop_pct*100:g}% cS{r.catastrophe_stop_pct*100:g}% bf{r.base_frac} mf{r.max_frac} dyn={r.use_dynamic} adp={r.use_adaptive}"
            print(
                f"  ret={r.oos_return*100:>+7.1f}% end=${r.ending_equity_usd:>8,.0f} "
                f"DD={r.max_dd_pct*100:>5.1f}% n={r.num_trades:>3} PF={r.profit_factor:.2f} "
                f"WR={r.win_rate*100:.1f}% | {label}"
            )
            if blockers:
                print(f"       BLOCKERS: {'; '.join(blockers)}")
            else:
                print(f"       (passes strict)")

    # ── 8. Sanity: safe-floor comparison ──
    print("\n" + "=" * 78)
    print("SAFE FLOOR COMPARISON — long_only 2x frac=2.0 tight stop (Phase 8 earlier winner)")
    print("=" * 78)
    safe_floor_candidates = [
        r for r in rows
        if r.tier == "2x"
        and r.direction_mode == "long_only"
        and r.variant == "V3"
        and abs(r.alpha_stop_pct - 0.0125) < 1e-6
        and abs(r.risk_per_trade - 0.025) < 1e-6
        and r.base_frac == 2.0
        and r.max_frac == 2.0
    ]
    for r in safe_floor_candidates:
        print("  " + format_row(r))
        print(f"    blockers: {identify_blocker(r)}")


if __name__ == "__main__":
    main()
