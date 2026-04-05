"""Tests for live-context validation (Case10, Parent F+G)."""

from __future__ import annotations

from datetime import date

from context.live_setup_validator import (
    check_breakdown_event,
    check_parent_f_bearish_impulse,
    check_parent_g_ascending_channel,
    check_parent_g_channel_boundaries,
    check_retest_event,
    check_retest_failure_confirmed,
    validate_case10_live_setup,
)
from research.narrative_case_mapping import (
    build_case_mapping,
    build_parent_structure_timeline,
)


# ── Parent structure data integrity (via Codex's narrative module) ────

def test_parent_timeline_has_seven_entries():
    assert len(build_parent_structure_timeline()) == 7


def test_parent_timeline_names():
    names = [p.structure_id for p in build_parent_structure_timeline()]
    assert names == ["A", "B", "C", "D", "E", "F", "G"]


def test_parent_g_has_breakdown_low():
    pg = next(p for p in build_parent_structure_timeline() if p.structure_id == "G")
    breakdown_lows = [kl for kl in pg.key_lows if float(kl["price"]) == 65000.0]
    assert len(breakdown_lows) == 1
    assert breakdown_lows[0]["date"] == "2026-03-29"


# ── Case mapping integrity ──────────────────────────────────────────

def test_case_mapping_has_ten_entries():
    assert len(build_case_mapping()) == 10


def test_only_case10_is_valid_for_short():
    valid = [c for c in build_case_mapping() if c.whether_it_should_be_short_candidate]
    assert len(valid) == 1
    assert valid[0].case_id == "Case10"


def test_case10_links_parent_f_and_g():
    case10 = next(c for c in build_case_mapping() if c.case_id == "Case10")
    assert case10.parent_structure_id == "F+G"


# ── Live-context conditions ──────────────────────────────────────────

def test_parent_f_bearish_impulse_passes():
    assert check_parent_f_bearish_impulse().passed is True


def test_parent_g_ascending_channel_passes():
    assert check_parent_g_ascending_channel().passed is True


def test_parent_g_channel_slopes_rising():
    result, bounds = check_parent_g_channel_boundaries()
    assert result.passed is True
    assert bounds["upper_slope"] > 0
    assert bounds["lower_slope"] > 0


def test_breakdown_below_lower_bound():
    _, bounds = check_parent_g_channel_boundaries()
    assert check_breakdown_event(bounds).passed is True


def test_retest_near_lower_bound():
    _, bounds = check_parent_g_channel_boundaries()
    assert check_retest_event(bounds).passed is True


def test_retest_failure_confirmed_when_price_below():
    _, bounds = check_parent_g_channel_boundaries()
    result = check_retest_failure_confirmed(67500.0, date(2026, 4, 3), bounds)
    assert result.passed is True


def test_retest_failure_not_confirmed_when_price_above():
    _, bounds = check_parent_g_channel_boundaries()
    result = check_retest_failure_confirmed(69500.0, date(2026, 4, 3), bounds)
    assert result.passed is False


def test_retest_failure_not_confirmed_without_price():
    _, bounds = check_parent_g_channel_boundaries()
    result = check_retest_failure_confirmed(None, None, bounds)
    assert result.passed is False


# ── Full report ──────────────────────────────────────────────────────

def test_full_report_valid_at_67500():
    report = validate_case10_live_setup(current_price=67500.0, current_date=date(2026, 4, 3))
    assert report["trade_valid"] is True
    assert report["all_conditions_met"] is True
    tp = report["trade_plan"]
    assert tp["side"] == "short"
    assert tp["entry"] > 0
    assert tp["stop"] > tp["entry"]
    assert tp["target_1"] < tp["entry"]
    assert tp["target_2"] < tp["target_1"]


def test_full_report_invalid_at_69500():
    report = validate_case10_live_setup(current_price=69500.0, current_date=date(2026, 4, 3))
    assert report["trade_valid"] is False
    assert report["trade_plan"] is None
    assert len(report["blocking_conditions"]) > 0


def test_full_report_contains_required_sections():
    report = validate_case10_live_setup(current_price=67500.0, current_date=date(2026, 4, 3))
    assert "parent_structure_summary" in report
    assert "local_structure_summary" in report
    assert "channel_boundaries" in report
    assert "conditions" in report
    assert report["case_id"] == "Case10"
