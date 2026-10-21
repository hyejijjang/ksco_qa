"""부록 C 최종 판정 규칙 — 표의 각 행 + 우선순위(첫 매칭 하나만)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ksco_qa.g3.final_rules import FinalInputs, NoRuleMatched, decide_final

PASS_ROW = FinalInputs(
    match_status="MATCHED",
    inspected=True,
    reference_mode="GENERATE_REFERENCE",
    g0_action="KEEP",
    g1_status="UNIQUE",
    g1_search_completed=True,
    g2_status="PASS",
)


def test_rule1_duplicate() -> None:
    d = decide_final(replace(PASS_ROW, g1_status="DUPLICATE", g2_status="SKIPPED"))
    assert (d.rule, d.status, d.next_action) == (1, "FAIL", "EXCLUDE_DUPLICATE")


def test_rule2_reselect_b() -> None:
    d = decide_final(replace(PASS_ROW, g0_action="RESELECT_B", g1_status="NOT_EVALUATED", g2_status="SKIPPED"))
    assert (d.rule, d.status, d.next_action) == (2, "FAIL", "RESELECT_DELIVERABLE")


def test_rule3_g2_fail() -> None:
    d = decide_final(replace(PASS_ROW, g2_status="FAIL"))
    assert (d.rule, d.status, d.next_action) == (3, "FAIL", "REVISE_TASK")


@pytest.mark.parametrize(
    "changes, cause, action",
    [
        ({"match_status": "NOT_FOUND", "inspected": False}, "P0_UNRESOLVED", "CHECK_ASSETS"),
        ({"inspected": False}, "P0_UNRESOLVED", "CHECK_ASSETS"),
        ({"g0_action": "REVIEW_B", "g1_status": "NOT_EVALUATED", "g2_status": "SKIPPED"}, "G0_REVIEW_B", "CHECK_ASSETS"),
        ({"g1_status": "REVIEW"}, "G1_REVIEW", "CHECK_DUPLICATE"),
        ({"g1_search_completed": False}, "G1_INCOMPLETE", "CHECK_DUPLICATE"),
        ({"g1_status": None}, "G1_INCOMPLETE", "CHECK_DUPLICATE"),
        ({"g2_status": "REVIEW"}, "G2_REVIEW", "REVIEW_MANUAL"),
        ({"g2_status": None}, "G2_INCOMPLETE", "REVIEW_MANUAL"),
        ({"reference_mode": "UNRESOLVED_REFERENCE"}, "REFERENCE_UNRESOLVED", "CHECK_ASSETS"),
    ],
)
def test_rule4_review_causes(changes: dict, cause: str, action: str) -> None:
    d = decide_final(replace(PASS_ROW, **changes))
    assert (d.rule, d.status, d.next_action) == (4, "REVIEW", action)
    assert d.causes == (cause,)


@pytest.mark.parametrize("action", ["KEEP", "REGENERATE"])
def test_rule5_pass(action: str) -> None:
    d = decide_final(replace(PASS_ROW, g0_action=action))
    assert (d.rule, d.status, d.next_action) == (5, "PASS", "HANDOFF_TO_AI_TEAM")


def test_first_match_only_duplicate_beats_reselect_and_fail() -> None:
    d = decide_final(replace(PASS_ROW, g1_status="DUPLICATE", g0_action="RESELECT_B", g2_status="FAIL"))
    assert d.rule == 1


def test_first_match_only_reselect_beats_g2_fail() -> None:
    d = decide_final(replace(PASS_ROW, g0_action="RESELECT_B", g2_status="FAIL"))
    assert d.rule == 2


def test_first_match_only_g2_fail_beats_review() -> None:
    d = decide_final(replace(PASS_ROW, g2_status="FAIL", g1_status="REVIEW", match_status="AMBIGUOUS"))
    assert d.rule == 3


def test_rule4_multiple_causes_first_decides_action() -> None:
    d = decide_final(replace(PASS_ROW, g1_status="REVIEW", g2_status="REVIEW"))
    assert d.causes == ("G1_REVIEW", "G2_REVIEW")
    assert d.next_action == "CHECK_DUPLICATE"


def test_provided_reference_does_not_block_pass() -> None:
    """Reference 부재·제공 여부 자체는 REVIEW 사유가 아니다 (06 최소 검증 8)."""
    assert decide_final(replace(PASS_ROW, reference_mode="PROVIDED_REFERENCE")).status == "PASS"


def test_no_rule_matched_raises() -> None:
    # KEEP인데 G1 NOT_EVALUATED: 모순된 입력 → 판정을 지어내지 않는다
    with pytest.raises(NoRuleMatched):
        decide_final(replace(PASS_ROW, g1_status="NOT_EVALUATED"))


def test_unknown_enum_value_rejected() -> None:
    with pytest.raises(ValueError):
        decide_final(replace(PASS_ROW, g2_status="DESIGNABLE"))
