"""Narrative-based regime lookup for the strategy.

Uses the user's fixed Parent Structure Timeline (A-G) as the single source
of truth for determining the active parent structure and computing channel
boundaries at any given date.  Returns a parent_context dict that the
existing gate functions in trend_breakout.py can use directly.

This replaces the mechanical parent-context detector (_build_parent_context)
while keeping all the position-in-channel and event-type nuance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import mean
from typing import Any

from research.narrative_case_mapping import ParentStructure, build_parent_structure_timeline


@dataclass(frozen=True)
class NarrativeRegime:
    parent_id: str | None
    parent_type: str | None
    parent_context: dict[str, float | str | None]


# Map narrative structure_type → parent_structure_type for the gate functions
_TYPE_MAP: dict[str, str] = {
    "major_descending_channel": "descending_channel",
    "major_ascending_channel": "ascending_channel",
    "local_descending_channel_inside_bullish_transition": "descending_channel",
    "black_swan_shock_liquidity_sweep_reclaim": "ascending_channel",
    "bearish_impulse_then_ascending_rebound_channel": "ascending_channel",
    "current_ascending_rebound_channel_after_crash": "ascending_channel",
}

# Map narrative structure_type → parent_event_type
_EVENT_MAP: dict[str, str] = {
    "major_descending_channel": "normal",
    "major_ascending_channel": "normal",
    "local_descending_channel_inside_bullish_transition": "normal",
    "black_swan_shock_liquidity_sweep_reclaim": "shock_break_reclaim",
    "bearish_impulse_then_ascending_rebound_channel": "confirmed_breakdown",
    "current_ascending_rebound_channel_after_crash": "confirmed_breakdown",
}

# Transition gaps: (from_id, to_id) → (parent_structure_type, parent_event_type)
_TRANSITION_MAP: dict[tuple[str, str], tuple[str, str]] = {
    ("A", "B"): ("ascending_channel", "normal"),  # bullish breakout
    ("B", "C"): ("ascending_channel", "normal"),  # bullish breakout
    ("C", "D"): ("ascending_channel", "normal"),  # bullish impulse
    ("D", "E"): ("ascending_channel", "shock_break_reclaim"),  # pre-shock
    ("E", "F"): ("descending_channel", "confirmed_breakdown"),  # bearish
    ("F", "G"): ("descending_channel", "confirmed_breakdown"),  # crash
}


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _fit_line(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    if len(points) < 2:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_mean = mean(xs)
    y_mean = mean(ys)
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return None
    numer = sum((x - x_mean) * (y - y_mean) for x, y in points)
    slope = numer / denom
    intercept = y_mean - slope * x_mean
    return slope, intercept


def _compute_boundaries(parent: ParentStructure, eval_date: date) -> tuple[float | None, float | None]:
    """Compute upper and lower boundary at eval_date using parent's key points."""
    high_points = [
        (float(date.fromisoformat(kh["date"]).toordinal()), float(kh["price"]))
        for kh in parent.key_highs
    ]
    low_points = [
        (float(date.fromisoformat(kl["date"]).toordinal()), float(kl["price"]))
        for kl in parent.key_lows
    ]

    upper_fit = _fit_line(high_points)
    lower_fit = _fit_line(low_points)

    ordinal = float(eval_date.toordinal())
    upper = (upper_fit[0] * ordinal + upper_fit[1]) if upper_fit else None
    lower = (lower_fit[0] * ordinal + lower_fit[1]) if lower_fit else None
    return upper, lower


def _position_in_channel(
    price: float,
    upper: float | None,
    lower: float | None,
    zone_pct: float = 0.30,
) -> str:
    if upper is None or lower is None:
        return "unknown"
    width = max(upper - lower, 1e-9)
    zone = width * zone_pct
    if price < lower:
        return "below_lower_boundary"
    if price > upper:
        return "above_upper_boundary"
    if price <= lower + zone:
        return "near_lower_boundary"
    if price >= upper - zone:
        return "near_upper_boundary"
    return "mid_channel"


def lookup_narrative_regime(eval_date: date, current_price: float | None = None) -> NarrativeRegime:
    """Return the regime for a given date based on the narrative timeline."""
    timeline = build_parent_structure_timeline()

    # Check if the date falls within any parent structure
    for parent in timeline:
        start = _parse_date(parent.start)
        end = _parse_date(parent.end)
        if start <= eval_date <= end:
            return _build_regime_from_parent(parent, eval_date, current_price)

    # Date falls in a gap between parents — find which transition
    for i in range(len(timeline) - 1):
        end_prev = _parse_date(timeline[i].end)
        start_next = _parse_date(timeline[i + 1].start)
        if end_prev < eval_date < start_next:
            pair = (timeline[i].structure_id, timeline[i + 1].structure_id)
            ptype, event = _TRANSITION_MAP.get(pair, ("unknown", "normal"))
            return NarrativeRegime(
                parent_id=f"{pair[0]}→{pair[1]}",
                parent_type="transition",
                parent_context={
                    "parent_structure_type": ptype,
                    "parent_upper_boundary": None,
                    "parent_lower_boundary": None,
                    "parent_position_in_channel": "mid_channel",
                    "parent_event_type": event,
                },
            )

    # Before first parent
    first_start = _parse_date(timeline[0].start)
    if eval_date < first_start:
        return NarrativeRegime(
            parent_id=None,
            parent_type=None,
            parent_context={
                "parent_structure_type": "unknown",
                "parent_upper_boundary": None,
                "parent_lower_boundary": None,
                "parent_position_in_channel": "unknown",
                "parent_event_type": "normal",
            },
        )

    # After last parent — extrapolate
    return _build_regime_from_parent(timeline[-1], eval_date, current_price)


def _build_regime_from_parent(
    parent: ParentStructure,
    eval_date: date,
    current_price: float | None,
) -> NarrativeRegime:
    upper, lower = _compute_boundaries(parent, eval_date)
    ptype = _TYPE_MAP.get(parent.structure_type, "unknown")
    event = _EVENT_MAP.get(parent.structure_type, "normal")

    position = "mid_channel"
    if current_price is not None:
        position = _position_in_channel(current_price, upper, lower)

    return NarrativeRegime(
        parent_id=parent.structure_id,
        parent_type=parent.structure_type,
        parent_context={
            "parent_structure_type": ptype,
            "parent_upper_boundary": upper,
            "parent_lower_boundary": lower,
            "parent_position_in_channel": position,
            "parent_event_type": event,
        },
    )
