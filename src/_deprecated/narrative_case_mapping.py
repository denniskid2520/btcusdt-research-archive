from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ParentStructure:
    structure_id: str
    start: str
    end: str
    structure_type: str
    key_highs: list[dict[str, float | str]]
    key_lows: list[dict[str, float | str]]
    transition_event: str


@dataclass(frozen=True)
class NarrativeCase:
    case_id: str
    parent_structure_id: str
    parent_structure_type: str
    period_start: str
    period_end: str
    narrative_summary: str
    correct_classification: str
    invalid_local_rule_if_any: str | None
    cluster_members: list[str]
    whether_it_should_be_short_candidate: bool
    reason: str


def build_parent_structure_timeline() -> list[ParentStructure]:
    return [
        ParentStructure(
            structure_id="A",
            start="2024-03-13",
            end="2024-10-21",
            structure_type="major_descending_channel",
            key_highs=[
                {"date": "2024-03-13", "price": 73650.0},
                {"date": "2024-05-21", "price": 71979.0},
                {"date": "2024-07-29", "price": 70079.0},
            ],
            key_lows=[
                {"date": "2024-05-01", "price": 56552.0},
                {"date": "2024-07-05", "price": 53485.0},
                {"date": "2024-08-05", "price": 49000.0},
                {"date": "2024-09-06", "price": 52550.0},
            ],
            transition_event=(
                "2024-08-05 lower-bound liquidity sweep / false breakdown reclaim, "
                "then 2024-10-21 upside breakout and 2024-11-04 retest success."
            ),
        ),
        ParentStructure(
            structure_id="B",
            start="2024-11-14",
            end="2025-05-02",
            structure_type="major_descending_channel",
            key_highs=[
                {"date": "2024-12-17", "price": 108353.0},
                {"date": "2025-01-22", "price": 106394.0},
            ],
            key_lows=[
                {"date": "2025-02-28", "price": 78258.0},
                {"date": "2025-03-10", "price": 78595.0},
                {"date": "2025-04-08", "price": 76239.0},
            ],
            transition_event=(
                "2025-05-02 upside breakout of major descending channel, followed by consolidation / retest / "
                "support hold before the next impulsive advance."
            ),
        ),
        ParentStructure(
            structure_id="C",
            start="2025-05-08",
            end="2025-07-04",
            structure_type="local_descending_channel_inside_bullish_transition",
            key_highs=[
                {"date": "2025-05-22", "price": 111980.0},
                {"date": "2025-06-10", "price": 110400.0},
                {"date": "2025-06-30", "price": 110000.0},
            ],
            key_lows=[
                {"date": "2025-06-05", "price": 100372.0},
                {"date": "2025-06-22", "price": 98200.0},
            ],
            transition_event=(
                "After another upper-bound test on 2025-06-30, price broke out and then confirmed with "
                "2025-07-04 retest success."
            ),
        ),
        ParentStructure(
            structure_id="D",
            start="2025-07-05",
            end="2025-10-10",
            structure_type="major_ascending_channel",
            key_highs=[
                {"date": "2025-07-14", "price": 123218.0},
                {"date": "2025-08-14", "price": 124474.0},
                {"date": "2025-10-06", "price": 126199.0},
            ],
            key_lows=[
                {"date": "2025-08-31", "price": 108076.0},
                {"date": "2025-09-27", "price": 109064.0},
            ],
            transition_event="2025-10-10 black swan shock starts after this structure.",
        ),
        ParentStructure(
            structure_id="E",
            start="2025-10-10",
            end="2025-11-20",
            structure_type="black_swan_shock_liquidity_sweep_reclaim",
            key_highs=[{"date": "2025-10-10", "price": 122550.0}],
            key_lows=[{"date": "2025-10-10", "price": 102000.0}],
            transition_event=(
                "Pierce below major ascending-channel lower bound then reclaim; "
                "stabilize around the major lower-bound zone (~106k area) for a period, then later print "
                "a clean bearish breakdown."
            ),
        ),
        ParentStructure(
            structure_id="F",
            start="2025-11-21",
            end="2026-01-29",
            structure_type="bearish_impulse_then_ascending_rebound_channel",
            key_highs=[
                {"date": "2025-11-28", "price": 93092.0},
                {"date": "2025-12-03", "price": 94150.0},
                {"date": "2026-01-14", "price": 97924.0},
            ],
            key_lows=[
                {"date": "2025-11-21", "price": 80600.0},
                {"date": "2025-12-01", "price": 83822.0},
                {"date": "2025-12-18", "price": 84450.0},
                {"date": "2026-01-20", "price": 87263.0},
            ],
            transition_event="2026-01-29 downside breakdown followed by selloff into 2026-02-06 low near 60000.",
        ),
        ParentStructure(
            structure_id="G",
            start="2026-02-06",
            end="2026-04-01",
            structure_type="current_ascending_rebound_channel_after_crash",
            key_highs=[
                {"date": "2026-02-09", "price": 71453.0},
                {"date": "2026-03-04", "price": 74050.0},
                {"date": "2026-03-17", "price": 76000.0},
            ],
            key_lows=[
                {"date": "2026-02-06", "price": 60000.0},
                {"date": "2026-02-25", "price": 63913.0},
                {"date": "2026-03-08", "price": 65618.0},
                {"date": "2026-03-23", "price": 67445.0},
                {"date": "2026-03-29", "price": 65000.0},
            ],
            transition_event=(
                "2026-03-25 midline retest near 72026, then 2026-03-29 breakdown below lower bound, "
                "followed by 2026-04-01 retest near 69310 as resistance."
            ),
        ),
    ]


def build_case_mapping() -> list[NarrativeCase]:
    return [
        NarrativeCase(
            case_id="Case1",
            parent_structure_id="A",
            parent_structure_type="major_descending_channel",
            period_start="2024-08-05",
            period_end="2024-09-06",
            narrative_summary="Part of the same lower-bound false-breakdown reclaim sequence in Parent A.",
            correct_classification="major_descending_channel_lower_boundary_false_breakdown_reclaim_cluster",
            invalid_local_rule_if_any="ascending_channel_breakdown_retest_short",
            cluster_members=["Case1", "Case2", "Case3"],
            whether_it_should_be_short_candidate=False,
            reason="Liquidity sweep + reclaim at parent lower boundary, not valid bearish continuation breakdown.",
        ),
        NarrativeCase(
            case_id="Case2",
            parent_structure_id="A",
            parent_structure_type="major_descending_channel",
            period_start="2024-08-05",
            period_end="2024-09-06",
            narrative_summary="Merged into the same Parent A false-breakdown reclaim event as Case1/Case3.",
            correct_classification="major_descending_channel_lower_boundary_false_breakdown_reclaim_cluster",
            invalid_local_rule_if_any="ascending_channel_breakdown_retest_short",
            cluster_members=["Case1", "Case2", "Case3"],
            whether_it_should_be_short_candidate=False,
            reason="Not an independent short near-miss; belongs to one merged reclaim cluster.",
        ),
        NarrativeCase(
            case_id="Case3",
            parent_structure_id="A",
            parent_structure_type="major_descending_channel",
            period_start="2024-08-05",
            period_end="2024-09-06",
            narrative_summary="Merged with Case1/Case2 as one event cluster within Parent A.",
            correct_classification="major_descending_channel_lower_boundary_false_breakdown_reclaim_cluster",
            invalid_local_rule_if_any="ascending_channel_breakdown_retest_short",
            cluster_members=["Case1", "Case2", "Case3"],
            whether_it_should_be_short_candidate=False,
            reason="Parent lower-bound reclaim context invalidates short-breakdown interpretation.",
        ),
        NarrativeCase(
            case_id="Case4",
            parent_structure_id="B",
            parent_structure_type="major_descending_channel",
            period_start="2025-02-28",
            period_end="2025-04-08",
            narrative_summary="Price action occurred near major descending-channel lower boundary support.",
            correct_classification="major_descending_channel_lower_boundary_support_context",
            invalid_local_rule_if_any="ascending_channel_breakdown_retest_short",
            cluster_members=["Case4"],
            whether_it_should_be_short_candidate=False,
            reason="Parent context conflict: lower-bound support zone is not a valid local bear-flag short trigger.",
        ),
        NarrativeCase(
            case_id="Case5",
            parent_structure_id="D",
            parent_structure_type="major_ascending_channel",
            period_start="2025-08-31",
            period_end="2025-09-27",
            narrative_summary="Part of the same major ascending-channel lower-bound support reaction sequence.",
            correct_classification="major_ascending_channel_lower_boundary_support_reaction_context",
            invalid_local_rule_if_any="ascending_channel_breakdown_retest_short",
            cluster_members=["Case5", "Case6", "Case7"],
            whether_it_should_be_short_candidate=False,
            reason="Parent D pullback/support behavior, not valid breakdown-retest short.",
        ),
        NarrativeCase(
            case_id="Case6",
            parent_structure_id="D",
            parent_structure_type="major_ascending_channel",
            period_start="2025-08-31",
            period_end="2025-09-27",
            narrative_summary="Merged in the same Parent D lower-bound support reaction cluster.",
            correct_classification="major_ascending_channel_lower_boundary_support_reaction_context",
            invalid_local_rule_if_any="ascending_channel_breakdown_retest_short",
            cluster_members=["Case5", "Case6", "Case7"],
            whether_it_should_be_short_candidate=False,
            reason="Not an independent short near-miss; same parent support reaction event.",
        ),
        NarrativeCase(
            case_id="Case7",
            parent_structure_id="D",
            parent_structure_type="major_ascending_channel",
            period_start="2025-08-31",
            period_end="2025-09-27",
            narrative_summary="Merged in the same Parent D lower-bound support reaction cluster.",
            correct_classification="major_ascending_channel_lower_boundary_support_reaction_context",
            invalid_local_rule_if_any="ascending_channel_breakdown_retest_short",
            cluster_members=["Case5", "Case6", "Case7"],
            whether_it_should_be_short_candidate=False,
            reason="Parent major ascending channel context overrides local short interpretation.",
        ),
        NarrativeCase(
            case_id="Case8",
            parent_structure_id="E",
            parent_structure_type="black_swan_shock_liquidity_sweep_reclaim",
            period_start="2025-10-10",
            period_end="2025-11-20",
            narrative_summary="Black swan break below boundary followed by reclaim and stabilization.",
            correct_classification="shock_break_reclaim_context",
            invalid_local_rule_if_any="ascending_channel_breakdown_retest_short",
            cluster_members=["Case8", "Case9"],
            whether_it_should_be_short_candidate=False,
            reason="Shock reclaim override: not a standard confirmed breakdown window.",
        ),
        NarrativeCase(
            case_id="Case9",
            parent_structure_id="E",
            parent_structure_type="black_swan_shock_liquidity_sweep_reclaim",
            period_start="2025-10-10",
            period_end="2025-11-20",
            narrative_summary="Post-shock stabilization phase within the same shock/reclaim event cluster.",
            correct_classification="post_shock_stabilization_context",
            invalid_local_rule_if_any="ascending_channel_breakdown_retest_short",
            cluster_members=["Case8", "Case9"],
            whether_it_should_be_short_candidate=False,
            reason="Post-shock zone remains invalid for standard breakdown-retest short labeling.",
        ),
        NarrativeCase(
            case_id="Case10",
            parent_structure_id="F+G",
            parent_structure_type="bearish_impulse_then_current_ascending_rebound_channel_context",
            period_start="2025-11-21",
            period_end="2026-04-01",
            narrative_summary=(
                "Must inherit Parent F then Parent G; key live setup is 2026-03-29 breakdown then 2026-04-01 retest."
            ),
            correct_classification="parent_FG_context_with_live_breakdown_retest_watch",
            invalid_local_rule_if_any=None,
            cluster_members=["Case10"],
            whether_it_should_be_short_candidate=True,
            reason=(
                "Current closest valid short context is the 2026-03-29 breakdown and 2026-04-01 lower-bound retest "
                "as resistance; avoid isolated 2026-02-10-only framing."
            ),
        ),
    ]


def build_report_payload() -> dict[str, Any]:
    parent_timeline = [item.__dict__ for item in build_parent_structure_timeline()]
    cases = [item.__dict__ for item in build_case_mapping()]
    return {
        "meta": {
            "version": "narrative-fixed-v1",
            "instrument": "BTCUSDT",
            "contract_type": "USDT-margined perpetual futures",
            "analysis_priority": [
                "parent_structure_on_1d_first",
                "local_execution_on_4h_second",
                "event_level_case_clustering",
                "shock_reclaim_override",
            ],
            "note": "This report is explicitly fixed to the user-provided narrative and is not inferred from strategy rules.",
        },
        "parent_structure_timeline": parent_timeline,
        "case_mapping_report": cases,
    }


def render_report_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Narrative Case Mapping Report (Fixed Schema)")
    lines.append("")
    meta = payload["meta"]
    lines.append(f"- Version: `{meta['version']}`")
    lines.append(f"- Instrument: `{meta['instrument']}`")
    lines.append(f"- Contract Type: `{meta['contract_type']}`")
    lines.append(f"- Note: {meta['note']}")
    lines.append("")
    lines.append("## Parent Structure Timeline (A~G)")
    lines.append("")
    for item in payload["parent_structure_timeline"]:
        lines.append(f"### Parent {item['structure_id']}")
        lines.append(f"- Period: `{item['start']}` -> `{item['end']}`")
        lines.append(f"- Type: `{item['structure_type']}`")
        highs = ", ".join(f"{point['date']}:{point['price']}" for point in item["key_highs"])
        lows = ", ".join(f"{point['date']}:{point['price']}" for point in item["key_lows"])
        lines.append(f"- Key Highs: {highs}")
        lines.append(f"- Key Lows: {lows}")
        lines.append(f"- Transition: {item['transition_event']}")
        lines.append("")

    lines.append("## Case Mapping (Case1~Case10)")
    lines.append("")
    for case in payload["case_mapping_report"]:
        lines.append(f"### {case['case_id']}")
        lines.append(f"- parent_structure_id: `{case['parent_structure_id']}`")
        lines.append(f"- parent_structure_type: `{case['parent_structure_type']}`")
        lines.append(f"- period_start / period_end: `{case['period_start']}` -> `{case['period_end']}`")
        lines.append(f"- narrative_summary: {case['narrative_summary']}")
        lines.append(f"- correct_classification: `{case['correct_classification']}`")
        lines.append(f"- invalid_local_rule_if_any: `{case['invalid_local_rule_if_any']}`")
        lines.append(f"- cluster_members: `{', '.join(case['cluster_members'])}`")
        lines.append(
            f"- whether_it_should_be_short_candidate: `{case['whether_it_should_be_short_candidate']}`"
        )
        lines.append(f"- reason: {case['reason']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_report(output_dir: str | Path) -> tuple[Path, Path]:
    payload = build_report_payload()
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / "narrative_case_mapping_report.json"
    md_path = target_dir / "narrative_case_mapping_report.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(render_report_markdown(payload), encoding="utf-8")
    return json_path, md_path
