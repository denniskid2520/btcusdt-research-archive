"""Phase 6 supplemental — slippage stress on the Phase 5A conservative cells.

The main Phase 6 sweep selected the top 20 cells by OOS return for slip
stress, which are all D1 variants at high risk budgets. We also want to
know how the Phase 5A primary (A_both sl=1.5% wick r=2%) and backup
(C_long sl=2% close r=2%) degrade under slippage — they didn't make
the top 20 by return.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, "src")

from data.strategy_c_v2_features import rsi_series
from research.strategy_c_v2_runner import (
    format_row,
    load_funding_csv,
    load_timeframe_data,
    run_cell,
)
from strategies.strategy_c_v2_filters import apply_side_filter
from strategies.strategy_c_v2_literature import rsi_and_macd_signals, rsi_only_signals


KLINES_4H = "src/data/btcusdt_4h_6year.csv"
FUNDING_CSV = "src/data/btcusdt_funding_5year.csv"
OUTPUT_CSV = Path("strategy_c_v2_phase6_conservative_slip.csv")

FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001

SLIPPAGE_LEVELS = (0.0, 0.001, 0.003, 0.010)


# Critical: rsi_only_signals silently falls through to rsi_30 for any
# period not in {14, 30}. Must compute RSI via rsi_series and pass as
# rsi_override. This was the Phase 3 silent-collapse bug fix.

_RSI_CACHE: dict[tuple[int, int], list[float | None]] = {}


def _get_rsi_override(features, period: int) -> list[float | None] | None:
    if period in (14, 30):
        return None
    key = (id(features), period)
    if key not in _RSI_CACHE:
        closes = [f.close for f in features]
        _RSI_CACHE[key] = rsi_series(closes, period)
    return _RSI_CACHE[key]


def make_A_both(features):
    override = _get_rsi_override(features, 21)
    return rsi_only_signals(features, rsi_period=21, rsi_override=override)


def make_A_long(features):
    override = _get_rsi_override(features, 21)
    sigs = rsi_only_signals(features, rsi_period=21, rsi_override=override)
    return apply_side_filter(sigs, side="long")


def make_C_long(features):
    sigs = rsi_and_macd_signals(features, rsi_period=14)
    return apply_side_filter(sigs, side="long")


CELLS = [
    {
        "label": "A_both", "name": "A_both_phase5a_primary",
        "hold": 12, "stop_loss_pct": 0.015, "stop_trigger": "wick",
        "risk_per_trade": 0.02, "effective_leverage": 2.0,
        "fn": make_A_both,
    },
    {
        "label": "A_long", "name": "A_long_phase5a_conservative",
        "hold": 12, "stop_loss_pct": 0.015, "stop_trigger": "close",
        "risk_per_trade": 0.02, "effective_leverage": 2.0,
        "fn": make_A_long,
    },
    {
        "label": "C_long", "name": "C_long_phase5a_backup",
        "hold": 4, "stop_loss_pct": 0.02, "stop_trigger": "close",
        "risk_per_trade": 0.02, "effective_leverage": 2.0,
        "fn": make_C_long,
    },
]


def main() -> None:
    print("Loading...")
    funding = load_funding_csv(FUNDING_CSV)
    tf = load_timeframe_data("4h", KLINES_4H, 4.0, funding)
    print(f"  bars: {len(tf.bars):,}  splits: {len(tf.splits)}")

    rows: list[dict] = []
    print("\nConservative cells (Phase 5A primaries) under slippage stress:")
    for cell in CELLS:
        print(f"\n[{cell['label']}]  sl={cell['stop_loss_pct']*100:.2f}% {cell['stop_trigger']} "
              f"r={cell['risk_per_trade']*100:.1f}%")
        for slip in SLIPPAGE_LEVELS:
            extras = {
                "label": cell["label"],
                "stop_loss_pct": cell["stop_loss_pct"],
                "stop_trigger": cell["stop_trigger"],
                "risk_per_trade": cell["risk_per_trade"],
                "effective_leverage": cell["effective_leverage"],
                "stop_slip_pct": slip,
            }
            row = run_cell(
                name=cell["name"],
                tf=tf,
                signal_fn=cell["fn"],
                hold_bars=cell["hold"],
                fee_per_side=FEE_PER_SIDE,
                slip_per_side=SLIP_PER_SIDE,
                stop_loss_pct=cell["stop_loss_pct"],
                stop_trigger=cell["stop_trigger"],
                stop_slip_pct=slip,
                risk_per_trade=cell["risk_per_trade"],
                effective_leverage=cell["effective_leverage"],
                extra_fields=extras,
            )
            rows.append(row)
            print(
                f"  slip={slip * 100:>4.2f}%  ret={row['agg_compounded_return'] * 100:>+7.2f}%  "
                f"dd={row['combined_max_dd'] * 100:>5.2f}%  n={int(row['total_oos_trades']):>3d}  "
                f"wt={row['worst_trade_pnl'] * 100:>+6.2f}%  stop%={row['exit_stop_loss_frac'] * 100:>5.1f}%"
            )

    # Write CSV
    keys = list(rows[0].keys())
    with OUTPUT_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nWrote {OUTPUT_CSV} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
