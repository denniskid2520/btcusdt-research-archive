from pathlib import Path

from research.context_aware_validation import build_truth_vs_strategy_report


def _payload() -> dict:
    source = Path("data/reports/narrative_case_mapping_report.json")
    return build_truth_vs_strategy_report(source)


def test_case1_to_case3_not_in_short_candidate_pool() -> None:
    payload = _payload()
    rows = {row["case_id"]: row for row in payload["case_comparison"]}
    assert rows["Case1"]["whether_short_candidate"] is False
    assert rows["Case2"]["whether_short_candidate"] is False
    assert rows["Case3"]["whether_short_candidate"] is False


def test_case4_not_in_short_candidate_pool() -> None:
    payload = _payload()
    rows = {row["case_id"]: row for row in payload["case_comparison"]}
    assert rows["Case4"]["whether_short_candidate"] is False


def test_case5_to_case7_not_in_short_candidate_pool() -> None:
    payload = _payload()
    rows = {row["case_id"]: row for row in payload["case_comparison"]}
    assert rows["Case5"]["whether_short_candidate"] is False
    assert rows["Case6"]["whether_short_candidate"] is False
    assert rows["Case7"]["whether_short_candidate"] is False


def test_case8_to_case9_blocked_by_shock_override() -> None:
    payload = _payload()
    rows = {row["case_id"]: row for row in payload["case_comparison"]}
    assert rows["Case8"]["rejection_or_gating_reason"] == "shock_override_active"
    assert rows["Case9"]["rejection_or_gating_reason"] == "shock_override_active"


def test_case10_is_current_live_short_context() -> None:
    payload = _payload()
    rows = {row["case_id"]: row for row in payload["case_comparison"]}
    assert rows["Case10"]["whether_short_candidate"] is True
    assert rows["Case10"]["strategy_detected_structure"] == "parent_F_plus_G_breakdown_then_retest_live_context"


def test_summary_checks_are_all_true() -> None:
    payload = _payload()
    assert all(payload["summary_checks"].values())
    assert payload["overall_truth_consistent"] is True
