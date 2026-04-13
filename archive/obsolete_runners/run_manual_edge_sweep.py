"""manual_edge_extraction — combined sweep runner for all 4 studies.

Runs each of the four manual-edge hypotheses as a separate sub-sweep
on D1_long and C_long baselines, against the Phase 7 cell configs:

  Base D1_long: rsi_only_20 h=11 long, sl=1.5% close, r=2%, L=2x, frac=1.333
  Base C_long:  rsi_and_macd_14 h=4 long, sl=2% close, r=2%, L=2x, frac=1.0

Sub-sweeps:
  1. REGIME filter — 6 variants (each filter + long-only bull regime combo)
  2. DYNAMIC SIZING — conviction score × frac multiplier {0.5, 0.75, 1.25, 1.5}
  3. PYRAMIDING — 2-leg add-on (fractional first-leg, add on profit check)
  4. ADAPTIVE EXIT — midpoint-PnL × higher-TF-trend driven hold modulation

All sub-sweeps report against the same baseline so the deliverables can
compare deltas directly.

Outputs:
  strategy_c_v2_manual_edge_regime.csv
  strategy_c_v2_manual_edge_sizing.csv
  strategy_c_v2_manual_edge_pyramid.csv
  strategy_c_v2_manual_edge_adaptive_exit.csv
"""
from __future__ import annotations

import csv
import math
import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, "src")

from data.strategy_c_v2_features import rsi_series
from research.strategy_c_v2_runner import (
    TimeframeData,
    format_row,
    load_funding_csv,
    load_timeframe_data,
    run_cell,
)
from strategies.strategy_c_v2_filters import (
    apply_funding_filter,
    apply_side_filter,
)
from strategies.strategy_c_v2_literature import (
    rsi_and_macd_signals,
    rsi_only_signals,
)
from strategies.strategy_c_v2_regime_filter import (
    apply_rsi_extremity_filter,
    apply_trend_filter,
    apply_volatility_filter,
)


KLINES_4H = "src/data/btcusdt_4h_6year.csv"
FUNDING_CSV = "src/data/btcusdt_funding_5year.csv"

REGIME_CSV = Path("strategy_c_v2_manual_edge_regime.csv")
SIZING_CSV = Path("strategy_c_v2_manual_edge_sizing.csv")
PYRAMID_CSV = Path("strategy_c_v2_manual_edge_pyramid.csv")
ADAPTIVE_CSV = Path("strategy_c_v2_manual_edge_adaptive_exit.csv")

FEE_PER_SIDE = 0.0005
SLIP_PER_SIDE = 0.0001


# ── RSI cache for non-{14,30} periods ───────────────────────────────

_RSI_CACHE: dict[tuple[int, int], list[float | None]] = {}


def _rsi_override(features, period: int):
    if period in (14, 30):
        return None
    key = (id(features), period)
    if key not in _RSI_CACHE:
        closes = [f.close for f in features]
        _RSI_CACHE[key] = rsi_series(closes, period)
    return _RSI_CACHE[key]


# ── Base signal functions ────────────────────────────────────────────


def make_D1_long_base(features):
    ov = _rsi_override(features, 20)
    sigs = rsi_only_signals(features, rsi_period=20, rsi_override=ov)
    return apply_side_filter(sigs, side="long")


def make_C_long_base(features):
    sigs = rsi_and_macd_signals(features, rsi_period=14)
    return apply_side_filter(sigs, side="long")


# ── Baseline cell params ────────────────────────────────────────────


BASE_CELLS = [
    {
        "label": "D1_long",
        "name": "rsi_only_20_h11_long",
        "base_fn": make_D1_long_base,
        "hold": 11,
        "stop_loss_pct": 0.015,
        "stop_trigger": "close",
        "risk_per_trade": 0.02,
        "effective_leverage": 2.0,
        "rsi_field": "rsi_14",  # for the RSI extremity filter — period 20 is in rsi_14 slot after override? no — see sizing note
        "rsi_period": 20,
    },
    {
        "label": "C_long",
        "name": "rsi_and_macd_14_h4_long",
        "base_fn": make_C_long_base,
        "hold": 4,
        "stop_loss_pct": 0.02,
        "stop_trigger": "close",
        "risk_per_trade": 0.02,
        "effective_leverage": 2.0,
        "rsi_field": "rsi_14",
        "rsi_period": 14,
    },
]


# ── Sub-sweep 1: REGIME FILTERS ─────────────────────────────────────
#
# Each variant composes a filter on top of the base signal stream.
# Reports delta vs baseline (no filter).


def make_regime_variant(base_fn, variant: str) -> Callable:
    """Return a signal fn that applies the named regime filter."""
    def fn(features):
        sigs = base_fn(features)
        if variant == "none":
            return sigs
        if variant == "ema_cross":
            return apply_trend_filter(sigs, features, mode="ema_cross")
        if variant == "close_vs_sma200":
            return apply_trend_filter(sigs, features, mode="close_vs_sma200")
        if variant == "long_only_bull_regime":
            return apply_trend_filter(sigs, features, mode="long_only_bull_regime")
        if variant == "rv_expansion":
            return apply_volatility_filter(sigs, features, min_rv=0.005)
        if variant == "rv_compression":
            return apply_volatility_filter(sigs, features, max_rv=0.015)
        if variant == "rv_mid_band":
            return apply_volatility_filter(sigs, features, min_rv=0.005, max_rv=0.020)
        if variant == "funding_veto_long":
            return apply_funding_filter(sigs, features, max_long_funding=0.0005)
        if variant == "funding_cum_veto":
            return apply_funding_filter(sigs, features, max_long_funding=0.001, use_cum_24h=True)
        if variant == "rsi_extreme_75":
            return apply_rsi_extremity_filter(sigs, features, long_min_rsi=75.0)
        if variant == "rsi_extreme_80":
            return apply_rsi_extremity_filter(sigs, features, long_min_rsi=80.0)
        if variant == "combo_trend_rv":
            s = apply_trend_filter(sigs, features, mode="ema_cross")
            return apply_volatility_filter(s, features, min_rv=0.005)
        if variant == "combo_trend_rsi_extreme":
            s = apply_trend_filter(sigs, features, mode="ema_cross")
            return apply_rsi_extremity_filter(s, features, long_min_rsi=75.0)
        raise ValueError(f"unknown variant: {variant}")
    return fn


REGIME_VARIANTS = [
    "none",
    "ema_cross",
    "close_vs_sma200",
    "long_only_bull_regime",
    "rv_expansion",
    "rv_compression",
    "rv_mid_band",
    "funding_veto_long",
    "funding_cum_veto",
    "rsi_extreme_75",
    "rsi_extreme_80",
    "combo_trend_rv",
    "combo_trend_rsi_extreme",
]


def run_regime_sweep(tf: TimeframeData) -> list[dict]:
    print(f"\n{'=' * 78}\nSUB-SWEEP 1 — REGIME FILTERS\n{'=' * 78}")
    rows: list[dict] = []
    for cell in BASE_CELLS:
        print(f"\n[{cell['label']}]")
        for variant in REGIME_VARIANTS:
            extras = {
                "base_label": cell["label"],
                "variant": variant,
            }
            row = run_cell(
                name=f"{cell['label']}_{variant}",
                tf=tf,
                signal_fn=make_regime_variant(cell["base_fn"], variant),
                hold_bars=cell["hold"],
                fee_per_side=FEE_PER_SIDE,
                slip_per_side=SLIP_PER_SIDE,
                stop_loss_pct=cell["stop_loss_pct"],
                stop_trigger=cell["stop_trigger"],
                risk_per_trade=cell["risk_per_trade"],
                effective_leverage=cell["effective_leverage"],
                extra_fields=extras,
            )
            rows.append(row)
            print(format_row(row))
    return rows


# ── Sub-sweep 2: DYNAMIC SIZING ─────────────────────────────────────
#
# For each signal bar, compute a conviction score from features and
# produce a position_frac_override that multiplies the base frac.
#
# Score components (all in [0, 1]):
#   - rsi_extremity: distance past threshold / 30 points
#   - trend alignment: +1 if ema_50 > ema_200 (long), -1 opposite
#   - funding favorable: +1 if funding_cum_24h aligned with signal
#   - rv in mid band: +1 if 0.005 < rv_4h < 0.020
#
# Composite: sum of components clipped to [0, 1]
# Multiplier: 0.5 + score * 1.0  → range [0.5, 1.5]
# position_frac_override[i] = base_frac × multiplier


def compute_sizing_score_and_override(features, signals, base_frac: float):
    """Compute per-signal position_frac from a composite conviction score."""
    out: list[float | None] = [None] * len(features)
    for i, (f, s) in enumerate(zip(features, signals)):
        if s == 0:
            continue

        score = 0.0
        n_components = 0

        # RSI extremity (closer to tail = stronger)
        rsi = getattr(f, "rsi_14", None)
        if rsi is not None:
            if s > 0:
                # Long: extremity above 70
                score += min(max((rsi - 70.0) / 20.0, 0.0), 1.0)
            else:
                score += min(max((30.0 - rsi) / 20.0, 0.0), 1.0)
            n_components += 1

        # Trend alignment
        ema_50 = getattr(f, "ema_50", None)
        ema_200 = getattr(f, "ema_200", None)
        if ema_50 is not None and ema_200 is not None:
            aligned = (ema_50 > ema_200 and s > 0) or (ema_50 < ema_200 and s < 0)
            score += 1.0 if aligned else 0.0
            n_components += 1

        # Funding not hostile to direction
        fund = getattr(f, "funding_rate", None)
        if fund is not None:
            if s > 0:
                # Long: prefer fund not too high
                score += 1.0 if fund <= 0.0003 else 0.5 if fund <= 0.0008 else 0.0
            else:
                score += 1.0 if fund >= -0.0003 else 0.5 if fund >= -0.0008 else 0.0
            n_components += 1

        # Mid-band volatility
        rv = getattr(f, "rv_4h", None)
        if rv is not None:
            in_band = 0.005 < rv < 0.020
            score += 1.0 if in_band else 0.0
            n_components += 1

        if n_components == 0:
            out[i] = base_frac
            continue

        avg = score / n_components        # in [0, 1]
        multiplier = 0.5 + avg * 1.0       # in [0.5, 1.5]
        out[i] = base_frac * multiplier
    return out


def make_sizing_fn(cell: dict, mode: str) -> tuple[Callable, Callable]:
    """Return (signal_fn, override_fn)."""
    base_frac = cell["risk_per_trade"] / cell["stop_loss_pct"]
    base_fn = cell["base_fn"]

    def sig_fn(features):
        return base_fn(features)

    def override_fn(features, signals):
        if mode == "fixed":
            return None
        if mode == "dynamic":
            return compute_sizing_score_and_override(features, signals, base_frac)
        if mode == "binary":
            # Hi = 1.5x base, lo = 0.5x base, at rsi extremity threshold
            out: list[float | None] = [None] * len(features)
            for i, (f, s) in enumerate(zip(features, signals)):
                if s == 0:
                    continue
                rsi = getattr(f, "rsi_14", None)
                if rsi is None:
                    out[i] = base_frac
                    continue
                if s > 0:
                    hi = rsi >= 80.0
                elif s < 0:
                    hi = rsi <= 20.0
                else:
                    hi = False
                out[i] = base_frac * (1.5 if hi else 0.5)
            return out
        raise ValueError(f"unknown sizing mode: {mode}")

    return sig_fn, override_fn


def run_sizing_sweep(tf: TimeframeData) -> list[dict]:
    print(f"\n{'=' * 78}\nSUB-SWEEP 2 — DYNAMIC SIZING\n{'=' * 78}")
    rows: list[dict] = []
    for cell in BASE_CELLS:
        print(f"\n[{cell['label']}]")
        for mode in ("fixed", "dynamic", "binary"):
            sig_fn, override_fn = make_sizing_fn(cell, mode)

            # Build override list upfront
            sigs = sig_fn(tf.features)
            override = override_fn(tf.features, sigs) if mode != "fixed" else None

            extras = {
                "base_label": cell["label"],
                "sizing_mode": mode,
            }
            row = _run_cell_with_override(
                name=f"{cell['label']}_sizing_{mode}",
                tf=tf,
                signal_fn=sig_fn,
                hold_bars=cell["hold"],
                stop_loss_pct=cell["stop_loss_pct"],
                stop_trigger=cell["stop_trigger"],
                risk_per_trade=cell["risk_per_trade"],
                effective_leverage=cell["effective_leverage"],
                position_frac_override=override,
                extras=extras,
            )
            rows.append(row)
            print(format_row(row))
    return rows


def _run_cell_with_override(
    *,
    name: str,
    tf: TimeframeData,
    signal_fn: Callable,
    hold_bars: int,
    stop_loss_pct: float,
    stop_trigger: str,
    risk_per_trade: float,
    effective_leverage: float,
    position_frac_override: list[float | None] | None,
    hold_bars_override: list[int | None] | None = None,
    extras: dict,
) -> dict:
    """Variant of run_cell that accepts a pre-built override vector
    and passes it per-split."""
    from research.strategy_c_v2_backtest import NO_LOSS_PROFIT_FACTOR, run_v2_backtest
    from research.strategy_c_v2_runner import (
        combined_profit_factor,
        max_dd_of,
        stitch_equity,
    )

    full_signals = signal_fn(tf.features)

    per_split_curves: list[list[float]] = []
    per_split_metrics: list[dict] = []
    all_pnls: list[float] = []
    all_gross: list[float] = []
    all_funding: list[float] = []
    all_cost: list[float] = []
    all_hold: list[int] = []
    all_adverse: list[float] = []
    exit_counts: dict[str, int] = {}
    pos_windows = 0

    for split in tf.splits:
        test_bars = tf.bars[split.test_lo : split.test_hi]
        test_signals = full_signals[split.test_lo : split.test_hi]
        test_funding = tf.funding_per_bar[split.test_lo : split.test_hi]
        test_override = (
            position_frac_override[split.test_lo : split.test_hi]
            if position_frac_override is not None
            else None
        )
        test_hold_override = (
            hold_bars_override[split.test_lo : split.test_hi]
            if hold_bars_override is not None
            else None
        )

        bt = run_v2_backtest(
            bars=test_bars,
            signals=test_signals,
            funding_per_bar=test_funding,
            hold_bars=hold_bars,
            fee_per_side=FEE_PER_SIDE,
            slip_per_side=SLIP_PER_SIDE,
            stop_loss_pct=stop_loss_pct,
            stop_trigger=stop_trigger,  # type: ignore[arg-type]
            risk_per_trade=risk_per_trade,
            effective_leverage=effective_leverage,
            position_frac_override=test_override,
            hold_bars_override=test_hold_override,
        )
        per_split_curves.append(bt.equity_curve)
        per_split_metrics.append(bt.metrics)
        for t in bt.trades:
            all_pnls.append(t.net_pnl)
            all_gross.append(t.gross_pnl)
            all_funding.append(t.funding_pnl)
            all_cost.append(t.cost)
            all_hold.append(t.hold_bars)
            exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1
            worst = 0.0
            for k in range(t.entry_idx, t.exit_idx):
                bk = test_bars[k]
                if t.side > 0:
                    adv = (t.entry_price - bk.low) / t.entry_price
                else:
                    adv = (bk.high - t.entry_price) / t.entry_price
                if adv > worst:
                    worst = adv
            all_adverse.append(worst)
        if bt.metrics["compounded_return"] > 0:
            pos_windows += 1

    curve = stitch_equity(per_split_curves)
    combined_return = (curve[-1] - 1.0) if curve else 0.0
    combined_dd = max_dd_of(curve)
    num_splits = len(tf.splits)
    total_trades = int(sum(m["num_trades"] for m in per_split_metrics))
    pos_frac = pos_windows / num_splits if num_splits else 0.0
    avg_expo = (
        sum(m["exposure_time"] for m in per_split_metrics) / num_splits
        if num_splits
        else 0.0
    )
    pf = combined_profit_factor(all_pnls)
    worst_trade = min(all_pnls) if all_pnls else 0.0
    worst_adverse = max(all_adverse) if all_adverse else 0.0

    row = {
        "timeframe": tf.name,
        "strategy": name,
        "hold_bars": hold_bars,
        "num_splits": num_splits,
        "total_oos_trades": total_trades,
        "agg_compounded_return": combined_return,
        "combined_max_dd": combined_dd,
        "combined_profit_factor": pf,
        "positive_windows_frac": pos_frac,
        "avg_exposure_time": avg_expo,
        "enough_trades": total_trades >= 30,
        "worst_trade_pnl": worst_trade,
        "worst_adverse_move": worst_adverse,
        "total_gross_pnl": sum(all_gross),
        "total_funding_pnl": sum(all_funding),
        "total_cost_pnl": -sum(all_cost),
        "n_stopped_out": sum(
            1 for k in exit_counts if k.startswith("stop_loss")
        ) and sum(v for k, v in exit_counts.items() if k.startswith("stop_loss")),
    }
    row.update(extras)
    return row


# ── Sub-sweep 3: PYRAMIDING ──────────────────────────────────────────
#
# Simplified pyramiding model: instead of real multi-leg positions,
# we simulate by firing the signal at the base bar AND re-firing on
# the confirmation bar IF the first leg is in profit at that point.
#
# Implementation trick: generate a NEW signal vector where:
#   - Original signal bar → leg 1 with frac = base_frac × 0.4
#   - Confirmation bar (next profitable close within 4 bars) → leg 2
#     with frac = base_frac × 0.3
#   - Second confirmation bar → leg 3 with frac = base_frac × 0.3
# Total notional at fully pyramided = base_frac × 1.0 (same as baseline)
#
# Because the backtester is single-position, leg-2 and leg-3 only fire
# if leg-1 has already exited. We approximate this by letting each
# leg fire independently with its own frac override, effectively
# running the strategy twice/thrice on overlapping sub-windows.
# This is a directional approximation, not a true pyramid simulation.
#
# More faithful model: simulate equivalent trades by shifting entry
# to the confirmation bar with reduced frac. Test three variants:
#   - baseline: single entry, full frac
#   - delayed: skip entries where no 2-bar confirmation of direction
#   - split: half-frac at bar 0, additional half-frac at bar 2 as a
#            separate trade (approximating a late add-on)


def make_pyramid_signals(
    features,
    base_fn: Callable,
    confirm_bars: int,
    pct_move: float,
):
    """Emit signals only at bars where N-bar forward confirmation exists.

    We use CLOSE of the entry bar and CLOSE of entry_bar + confirm_bars
    to check that price moved `pct_move` in the signal direction. This
    is a delayed-entry approximation of pyramid confirmation.

    NOTE: this uses future-price data WITHIN the signal construction,
    which is a look-ahead check for the confirmation. To keep this
    causal in a walk-forward sense, we use the backtester's natural
    forward scan — the confirmation bar is always AFTER the original
    signal bar, so it's only known at backtest time.

    Actually, for a proper causal test, we delay the ENTRY signal: the
    original signal bar emits 0, and the signal is re-emitted at the
    confirmation bar IF the original direction held. This is causal
    because at the confirmation bar, we only read bar j's own close
    relative to bar (j - confirm_bars)'s close.
    """
    sigs = base_fn(features)
    out = [0] * len(sigs)
    closes = [f.close for f in features]
    for i in range(len(sigs)):
        orig = sigs[i]
        if orig == 0:
            continue
        # Was there an original signal `confirm_bars` ago, and has the
        # move happened?
        j = i - confirm_bars
        if j < 0:
            continue
        j_sig = sigs[j]
        if j_sig != orig:  # original must have been the same direction
            continue
        # Check confirmation move
        delta = (closes[i] - closes[j]) / closes[j]
        if orig > 0 and delta >= pct_move:
            out[i] = 1
        elif orig < 0 and -delta >= pct_move:
            out[i] = -1
    return out


def run_pyramid_sweep(tf: TimeframeData) -> list[dict]:
    print(f"\n{'=' * 78}\nSUB-SWEEP 3 — PYRAMIDING (delayed-entry approximation)\n{'=' * 78}")
    rows: list[dict] = []
    for cell in BASE_CELLS:
        print(f"\n[{cell['label']}]")
        variants = [
            ("baseline", None, None),
            ("delayed_2bar_0.5pct", 2, 0.005),
            ("delayed_3bar_0.5pct", 3, 0.005),
            ("delayed_2bar_1pct", 2, 0.010),
            ("delayed_4bar_0.5pct", 4, 0.005),
        ]
        for name, confirm_bars, pct_move in variants:
            if name == "baseline":
                sig_fn = cell["base_fn"]
            else:
                def sig_fn(features, _base=cell["base_fn"], _cb=confirm_bars, _pm=pct_move):
                    return make_pyramid_signals(features, _base, _cb, _pm)

            extras = {
                "base_label": cell["label"],
                "variant": name,
            }
            row = run_cell(
                name=f"{cell['label']}_pyr_{name}",
                tf=tf,
                signal_fn=sig_fn,
                hold_bars=cell["hold"],
                fee_per_side=FEE_PER_SIDE,
                slip_per_side=SLIP_PER_SIDE,
                stop_loss_pct=cell["stop_loss_pct"],
                stop_trigger=cell["stop_trigger"],
                risk_per_trade=cell["risk_per_trade"],
                effective_leverage=cell["effective_leverage"],
                extra_fields=extras,
            )
            rows.append(row)
            print(format_row(row))
    return rows


# ── Sub-sweep 4: ADAPTIVE EXIT ──────────────────────────────────────
#
# At entry time, compute a score that predicts how long the trade
# should run. High-score trades get extended hold; low-score trades
# get compressed hold. Same hold_bars_override mechanism.
#
# Score at entry time is causal — reads features[entry_bar].
# Components:
#   - trend alignment (ema_50 > ema_200 for long)
#   - RSI extremity
#   - funding tailwind
# Mapping:
#   score >= 2 → hold × 1.5 (cap at 20)
#   score == 1 → hold × 1.0 (baseline)
#   score == 0 → hold × 0.5 (floor at 2)


def compute_adaptive_hold_override(features, signals, base_hold: int):
    out: list[int | None] = [None] * len(features)
    for i, (f, s) in enumerate(zip(features, signals)):
        if s == 0:
            continue
        score = 0
        # Trend alignment
        ema_50 = getattr(f, "ema_50", None)
        ema_200 = getattr(f, "ema_200", None)
        if ema_50 is not None and ema_200 is not None:
            if (s > 0 and ema_50 > ema_200) or (s < 0 and ema_50 < ema_200):
                score += 1
        # RSI extremity
        rsi = getattr(f, "rsi_14", None)
        if rsi is not None:
            if s > 0 and rsi > 78:
                score += 1
            elif s < 0 and rsi < 22:
                score += 1
        # Funding tailwind
        fund = getattr(f, "funding_rate", None)
        if fund is not None:
            if s > 0 and fund < 0.0002:
                score += 1
            elif s < 0 and fund > -0.0002:
                score += 1

        if score >= 2:
            out[i] = min(20, int(base_hold * 1.5))
        elif score == 1:
            out[i] = base_hold
        else:
            out[i] = max(2, int(base_hold * 0.5))
    return out


def make_adaptive_override(cell: dict, features) -> list[int | None] | None:
    """Build hold_bars_override for a cell using the adaptive score."""
    signals = cell["base_fn"](features)
    return compute_adaptive_hold_override(features, signals, cell["hold"])


def run_adaptive_exit_sweep(tf: TimeframeData) -> list[dict]:
    print(f"\n{'=' * 78}\nSUB-SWEEP 4 — ADAPTIVE EXIT\n{'=' * 78}")
    rows: list[dict] = []
    for cell in BASE_CELLS:
        print(f"\n[{cell['label']}]")
        # Baseline
        row_base = run_cell(
            name=f"{cell['label']}_exit_fixed",
            tf=tf,
            signal_fn=cell["base_fn"],
            hold_bars=cell["hold"],
            fee_per_side=FEE_PER_SIDE,
            slip_per_side=SLIP_PER_SIDE,
            stop_loss_pct=cell["stop_loss_pct"],
            stop_trigger=cell["stop_trigger"],
            risk_per_trade=cell["risk_per_trade"],
            effective_leverage=cell["effective_leverage"],
            extra_fields={"base_label": cell["label"], "exit_mode": "fixed"},
        )
        rows.append(row_base)
        print(format_row(row_base))

        # Adaptive (score-based)
        hold_override = make_adaptive_override(cell, tf.features)
        row_adap = _run_cell_with_override(
            name=f"{cell['label']}_exit_adaptive",
            tf=tf,
            signal_fn=cell["base_fn"],
            hold_bars=cell["hold"],
            stop_loss_pct=cell["stop_loss_pct"],
            stop_trigger=cell["stop_trigger"],
            risk_per_trade=cell["risk_per_trade"],
            effective_leverage=cell["effective_leverage"],
            position_frac_override=None,
            hold_bars_override=hold_override,
            extras={"base_label": cell["label"], "exit_mode": "adaptive"},
        )
        rows.append(row_adap)
        print(format_row(row_adap))

        # Uniform extended hold (baseline comparison)
        row_ext = run_cell(
            name=f"{cell['label']}_exit_ext",
            tf=tf,
            signal_fn=cell["base_fn"],
            hold_bars=int(cell["hold"] * 1.5),
            fee_per_side=FEE_PER_SIDE,
            slip_per_side=SLIP_PER_SIDE,
            stop_loss_pct=cell["stop_loss_pct"],
            stop_trigger=cell["stop_trigger"],
            risk_per_trade=cell["risk_per_trade"],
            effective_leverage=cell["effective_leverage"],
            extra_fields={"base_label": cell["label"], "exit_mode": "uniform_extended"},
        )
        rows.append(row_ext)
        print(format_row(row_ext))

        # Uniform compressed hold (baseline comparison)
        row_cmp = run_cell(
            name=f"{cell['label']}_exit_cmp",
            tf=tf,
            signal_fn=cell["base_fn"],
            hold_bars=max(2, int(cell["hold"] * 0.5)),
            fee_per_side=FEE_PER_SIDE,
            slip_per_side=SLIP_PER_SIDE,
            stop_loss_pct=cell["stop_loss_pct"],
            stop_trigger=cell["stop_trigger"],
            risk_per_trade=cell["risk_per_trade"],
            effective_leverage=cell["effective_leverage"],
            extra_fields={"base_label": cell["label"], "exit_mode": "uniform_compressed"},
        )
        rows.append(row_cmp)
        print(format_row(row_cmp))
    return rows


# ── output ──────────────────────────────────────────────────────────


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    keys: list[str] = []
    seen = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print(f"Wrote {path} ({len(rows)} rows)")


def main() -> None:
    print("=" * 78)
    print("manual_edge_extraction — combined sweep")
    print("=" * 78)

    funding = load_funding_csv(FUNDING_CSV)
    t0 = time.time()
    print("\nLoading 4h...")
    tf = load_timeframe_data("4h", KLINES_4H, 4.0, funding)
    print(f"  bars: {len(tf.bars):,}  features: {len(tf.features):,}  "
          f"splits: {len(tf.splits)}  ({time.time() - t0:.1f}s)")

    # Sub-sweep 1: regime filters
    regime_rows = run_regime_sweep(tf)
    write_csv(REGIME_CSV, regime_rows)

    # Sub-sweep 2: dynamic sizing
    sizing_rows = run_sizing_sweep(tf)
    write_csv(SIZING_CSV, sizing_rows)

    # Sub-sweep 3: pyramiding
    pyramid_rows = run_pyramid_sweep(tf)
    write_csv(PYRAMID_CSV, pyramid_rows)

    # Sub-sweep 4: adaptive exit
    adaptive_rows = run_adaptive_exit_sweep(tf)
    write_csv(ADAPTIVE_CSV, adaptive_rows)

    print(f"\n{'=' * 78}\nSUMMARY — regime filter deltas vs baseline per cell\n{'=' * 78}")
    for cell_label in ("D1_long", "C_long"):
        base = next(
            r for r in regime_rows
            if r["base_label"] == cell_label and r["variant"] == "none"
        )
        base_ret = base["agg_compounded_return"]
        base_dd = base["combined_max_dd"]
        base_n = int(base["total_oos_trades"])
        print(f"\n[{cell_label}] baseline: ret={base_ret * 100:+7.2f}% dd={base_dd * 100:.2f}% n={base_n}")
        for r in regime_rows:
            if r["base_label"] != cell_label or r["variant"] == "none":
                continue
            d_ret = (r["agg_compounded_return"] - base_ret) * 100
            d_dd = (r["combined_max_dd"] - base_dd) * 100
            d_n = int(r["total_oos_trades"]) - base_n
            print(
                f"  {r['variant']:<28} Δret={d_ret:>+7.2f}pp "
                f"Δdd={d_dd:>+6.2f}pp Δn={d_n:>+5d}  "
                f"→ ret={r['agg_compounded_return'] * 100:>+7.2f}% "
                f"dd={r['combined_max_dd'] * 100:>5.2f}% n={int(r['total_oos_trades']):>4d}"
            )


if __name__ == "__main__":
    main()
