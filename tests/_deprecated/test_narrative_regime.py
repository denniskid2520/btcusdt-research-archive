from datetime import date

from research.narrative_regime import lookup_narrative_regime


def test_parent_a_mid_channel_short_is_mid() -> None:
    """2024-04-14 at 64137 in Parent A should be mid_channel (valid short zone)."""
    regime = lookup_narrative_regime(date(2024, 4, 14), current_price=64137.0)
    assert regime.parent_id == "A"
    assert regime.parent_context["parent_position_in_channel"] == "mid_channel"


def test_parent_a_near_lower_boundary_after_crash() -> None:
    """2024-08-06 at 56378 in Parent A should be near_lower_boundary (short blocked).

    Parent A upper ~69910, lower ~51845, width ~18065.
    Price 56378 is only 25% above lower — within the lower quarter zone.
    """
    regime = lookup_narrative_regime(date(2024, 8, 6), current_price=56378.0)
    assert regime.parent_id == "A"
    assert regime.parent_context["parent_position_in_channel"] == "near_lower_boundary"


def test_parent_d_position_detection() -> None:
    """Mid-2025 in Parent D ascending channel at 116k should be mid_channel."""
    regime = lookup_narrative_regime(date(2025, 7, 14), current_price=116000.0)
    assert regime.parent_id == "D"
    assert regime.parent_context["parent_structure_type"] == "ascending_channel"
    assert regime.parent_context["parent_position_in_channel"] == "mid_channel"


def test_parent_e_shock_event_type() -> None:
    """Parent E should have shock_break_reclaim event type."""
    regime = lookup_narrative_regime(date(2025, 10, 15), current_price=110000.0)
    assert regime.parent_id == "E"
    assert regime.parent_context["parent_event_type"] == "shock_break_reclaim"


def test_parent_g_confirmed_breakdown_event() -> None:
    """Parent G should have confirmed_breakdown event type."""
    regime = lookup_narrative_regime(date(2026, 3, 1), current_price=70000.0)
    assert regime.parent_id == "G"
    assert regime.parent_context["parent_event_type"] == "confirmed_breakdown"


def test_transition_gap_returns_transition_type() -> None:
    """Date between Parent A and B should return transition regime."""
    regime = lookup_narrative_regime(date(2024, 11, 1), current_price=70000.0)
    assert regime.parent_type == "transition"
    assert "A" in regime.parent_id and "B" in regime.parent_id
