"""Strategy C v2 Phase 7 — retrospective 30-day paper deployment simulation.

Simulates 30 calendar days of paper deployment (2026-03-06 → 2026-04-05)
for all three Phase 7 deployment cells × both stop semantics. Produces
the PaperTradeLogEntry telemetry stream that the live runner would
emit over those 30 days, plus daily/weekly reconciliation stats.

Uses the existing 4h backtester + trade list — trades whose entry_idx
falls in the last 30 days are extracted and converted to
PaperTradeLogEntry records.

The retrospective simulation is NOT a live run. It proves the infra
works and produces the expected telemetry format, and it gives us
concrete per-day numbers for the day-30 decision framework. A real
forward 30-day run happens in a separate phase.

Output:
    strategy_c_v2_phase7_retrospective_trades.csv
    strategy_c_v2_phase7_retrospective_daily.csv
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

sys.path.insert(0, "src")

from adapters.base import MarketBar
from data.strategy_c_v2_features import rsi_series
from research.strategy_c_v2_backtest import V2Trade, run_v2_backtest
from research.strategy_c_v2_runner import (
    build_funding_per_bar,
    load_funding_csv,
    load_klines_csv,
)
from strategies.strategy_c_v2_filters import apply_side_filter
from strategies.strategy_c_v2_literature import (
    rsi_and_macd_signals,
    rsi_only_signals,
)
from strategies.strategy_c_v2_paper_log import PaperTradeLogEntry


KLINES_4H = "src/data/btcusdt_4h_6year.csv"
FUNDING_CSV = "src/data/btcusdt_funding_5year.csv"

TRADES_CSV = Path("strategy_c_v2_phase7_retrospective_trades.csv")
DAILY_CSV = Path("strategy_c_v2_phase7_retrospective_daily.csv")

FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001

# 30-day window (inclusive-exclusive)
PAPER_START = datetime(2026, 3, 6)
PAPER_END = datetime(2026, 4, 5)


# ── signal factories ────────────────────────────────────────────────


_RSI_CACHE: dict[tuple[int, int], list[float | None]] = {}


def _get_rsi_override(features, period: int) -> list[float | None] | None:
    if period in (14, 30):
        return None
    key = (id(features), period)
    if key not in _RSI_CACHE:
        closes = [f.close for f in features]
        _RSI_CACHE[key] = rsi_series(closes, period)
    return _RSI_CACHE[key]


def make_D1_long(features):
    override = _get_rsi_override(features, 20)
    sigs = rsi_only_signals(features, rsi_period=20, rsi_override=override)
    return apply_side_filter(sigs, side="long")


def make_C_long(features):
    sigs = rsi_and_macd_signals(features, rsi_period=14)
    return apply_side_filter(sigs, side="long")


CELLS = [
    {
        "label": "D1_long_primary",
        "fn": make_D1_long,
        "hold": 11,
        "stop_loss_pct": 0.015,
        "risk_per_trade": 0.02,
        "effective_leverage": 2.0,
        "actual_frac": 1.333,
    },
    {
        "label": "C_long_backup",
        "fn": make_C_long,
        "hold": 4,
        "stop_loss_pct": 0.02,
        "risk_per_trade": 0.02,
        "effective_leverage": 2.0,
        "actual_frac": 1.0,
    },
    {
        "label": "D1_long_frac2_shadow",
        "fn": make_D1_long,
        "hold": 11,
        "stop_loss_pct": 0.0125,
        "risk_per_trade": 0.025,
        "effective_leverage": 2.0,
        "actual_frac": 2.0,
    },
]


def run_cell_full(
    cell: dict,
    bars: list[MarketBar],
    funding_per_bar: list[float],
    features,
    semantics: str,
):
    """Run the cell over the FULL history (needed for feature warmup),
    then filter trades to the 30-day window."""
    sigs = cell["fn"](features)
    result = run_v2_backtest(
        bars=bars,
        signals=sigs,
        funding_per_bar=funding_per_bar,
        hold_bars=cell["hold"],
        fee_per_side=FEE_PER_SIDE,
        slip_per_side=SLIP_PER_SIDE,
        stop_loss_pct=cell["stop_loss_pct"],
        stop_semantics=semantics,  # type: ignore[arg-type]
        risk_per_trade=cell["risk_per_trade"],
        effective_leverage=cell["effective_leverage"],
    )
    return result


def trade_to_paper_log(
    cell: dict,
    semantics: str,
    t: V2Trade,
    bars: list[MarketBar],
) -> PaperTradeLogEntry:
    """Convert a V2Trade into a Phase 7 paper log entry."""
    signal_bar = bars[t.entry_idx - 1] if t.entry_idx > 0 else bars[t.entry_idx]
    stop_level = t.entry_price * (
        1 - cell["stop_loss_pct"] if t.side > 0 else 1 + cell["stop_loss_pct"]
    )
    is_stop_exit = t.exit_reason.startswith("stop_loss")

    # Model fill: what the frictionless model would have said.
    # (For this retrospective, paper = model + 0 slippage overlay.)
    model_entry = bars[t.entry_idx].open

    return PaperTradeLogEntry(
        cell_label=cell["label"],
        signal_timestamp=signal_bar.timestamp,
        completed_bar_timestamp=signal_bar.timestamp,
        intended_entry_price=model_entry,
        paper_fill_entry=t.entry_price,
        side="long" if t.side > 0 else "short",
        stop_semantics=semantics,  # type: ignore[arg-type]
        stop_level=stop_level,
        stop_trigger_timestamp=bars[t.exit_idx - 1].timestamp if is_stop_exit else None,
        stop_fill_price=t.exit_price if is_stop_exit else None,
        stop_slippage_vs_model=(
            (t.exit_price - stop_level) / stop_level if is_stop_exit else None
        ),
        actual_position_frac=cell["actual_frac"],
        exit_reason=t.exit_reason,
        exit_timestamp=t.exit_time,
        exit_price=t.exit_price,
        hold_bars=t.hold_bars,
        gross_pnl=t.gross_pnl,
        funding_pnl=t.funding_pnl,
        cost_pnl=-t.cost,
        net_pnl=t.net_pnl,
        monitor_flags=[],
    )


def main() -> None:
    print("=" * 78)
    print("Strategy C v2 Phase 7 — retrospective 30-day paper deployment")
    print(f"Window: {PAPER_START.date()} → {PAPER_END.date()}")
    print("=" * 78)

    print("\nLoading...")
    funding_records = load_funding_csv(FUNDING_CSV)
    bars = load_klines_csv(KLINES_4H)
    funding_per_bar = build_funding_per_bar(bars, funding_records)
    from data.strategy_c_v2_features import compute_features_v2
    features = compute_features_v2(bars, funding_records=funding_records, bar_hours=4.0)
    print(f"  4h bars: {len(bars):,}  features: {len(features):,}")

    # How many bars of the full series fall in the paper window
    paper_bar_indices = [
        i for i, b in enumerate(bars)
        if PAPER_START <= b.timestamp < PAPER_END
    ]
    print(f"  Paper window bar indices: {len(paper_bar_indices)} (from {paper_bar_indices[0]} to {paper_bar_indices[-1]})")

    all_log_entries: list[PaperTradeLogEntry] = []

    for cell in CELLS:
        for semantics in ("strategy_close_stop", "exchange_intrabar_stop"):
            result = run_cell_full(cell, bars, funding_per_bar, features, semantics)

            # Extract trades whose entry falls in the paper window
            trades_in_window = [
                t for t in result.trades
                if PAPER_START <= t.entry_time < PAPER_END
            ]

            # Also include any trade whose exit falls in the window (even if
            # entry was earlier) — for completeness.
            trades_closed_in_window = [
                t for t in result.trades
                if t.exit_time is not None
                and PAPER_START <= t.exit_time < PAPER_END
                and t not in trades_in_window
            ]

            in_window = trades_in_window + trades_closed_in_window
            print(f"\n[{cell['label']} / {semantics}]  "
                  f"trades in paper window: {len(in_window)}  "
                  f"(of {len(result.trades)} total)")

            for t in in_window:
                entry = trade_to_paper_log(cell, semantics, t, bars)
                all_log_entries.append(entry)
                print(
                    f"  {entry.signal_timestamp.date()} → {entry.exit_timestamp.date() if entry.exit_timestamp else '—'}  "
                    f"entry={entry.paper_fill_entry:>8,.0f}  exit={entry.exit_price:>8,.0f}  "
                    f"hold={entry.hold_bars:>2}  reason={entry.exit_reason:<15} "
                    f"net={entry.net_pnl * 100:>+6.2f}%"
                )

    # Write trades CSV
    if all_log_entries:
        keys = list(all_log_entries[0].to_dict().keys())
        with TRADES_CSV.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            for entry in all_log_entries:
                w.writerow(entry.to_dict())
        print(f"\nWrote {TRADES_CSV} ({len(all_log_entries)} trade rows)")
    else:
        print("\nNo trades in the paper window!")

    # Daily reconciliation summary
    print(f"\n{'=' * 78}")
    print("DAILY SUMMARY BY CELL × SEMANTICS")
    print("=" * 78)

    from collections import defaultdict
    daily_data: dict[tuple, dict] = defaultdict(lambda: {
        "trades": 0, "net_pnl": 0.0, "gross_pnl": 0.0,
        "funding": 0.0, "cost": 0.0, "stops": 0, "worst": 0.0,
    })

    for entry in all_log_entries:
        key = (entry.cell_label, entry.stop_semantics)
        d = daily_data[key]
        d["trades"] += 1
        d["net_pnl"] += entry.net_pnl
        d["gross_pnl"] += entry.gross_pnl
        d["funding"] += entry.funding_pnl
        d["cost"] += entry.cost_pnl
        if entry.exit_reason.startswith("stop_loss"):
            d["stops"] += 1
        if entry.net_pnl < d["worst"]:
            d["worst"] = entry.net_pnl

    print(f"{'cell':<24} {'semantics':<24} {'n':>3} {'net':>8} {'gross':>8} "
          f"{'fund':>7} {'cost':>7} {'stops':>5} {'worst':>7}")
    daily_rows: list[dict] = []
    for (label, semantics), d in sorted(daily_data.items()):
        row = {
            "cell": label,
            "stop_semantics": semantics,
            "trades": d["trades"],
            "net_pnl_sum": d["net_pnl"],
            "gross_pnl_sum": d["gross_pnl"],
            "funding_pnl_sum": d["funding"],
            "cost_pnl_sum": d["cost"],
            "stop_exits": d["stops"],
            "worst_trade": d["worst"],
        }
        daily_rows.append(row)
        print(
            f"{label:<24} {semantics:<24} {d['trades']:>3d} "
            f"{d['net_pnl'] * 100:>+7.2f}% {d['gross_pnl'] * 100:>+7.2f}% "
            f"{d['funding'] * 100:>+6.2f}% {d['cost'] * 100:>+6.2f}% "
            f"{d['stops']:>5d} {d['worst'] * 100:>+6.2f}%"
        )

    if daily_rows:
        with DAILY_CSV.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(daily_rows[0].keys()))
            w.writeheader()
            for r in daily_rows:
                w.writerow(r)
        print(f"\nWrote {DAILY_CSV} ({len(daily_rows)} summary rows)")


if __name__ == "__main__":
    main()
