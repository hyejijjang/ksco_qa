"""최종 판정 규칙 — 00 7.1·부록 C 각 행, 우선순위(첫 매칭 하나만), M1 결정 15~18·29."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ksco_qa.dictionaries import enum_values
from ksco_qa.g3.final_rules import REVIEW_CAUSE_ACTION, FinalInputs, NoRuleMatched, decide_final

PASS_ROW = FinalInputs(
    match_status="MATCHED",
    inspected=True,
    reference_mode="GENERATE_REFERENCE",
    g0_action="KEEP",
    g1_status="UNIQUE",
    g1_search_completed=True,
    g2_status="PASS",
    reference_readiness="BLUEPRINT_READY",
)


def test_rule1_duplicate() -> None:
    d = decide_final(replace(PASS_ROW, g1_status="DUPLICATE", g2_status="SKIPPED"))
    assert (d.rule, d.status, d.next_action, d.reason_codes) == (1, "FAIL", "EXCLUDE_DUPLICATE", ("DUPLICATE",))


def test_rule2_reselect_b() -> None:
    d = decide_final(replace(PASS_ROW, g0_action="RESELECT_B", g1_status="NOT_EVALUATED", g2_status="SKIPPED"))
    assert (d.rule, d.status, d.next_action, d.reason_codes) == (2, "FAIL", "RESELECT_DELIVERABLE", ("RESELECT_B",))


def test_rule3_g2_fail() -> None:
    d = decide_final(replace(PASS_ROW, g2_status="FAIL"))
    assert (d.rule, d.status, d.next_action, d.reason_codes) == (3, "FAIL", "REVISE_TASK", ("G2_FAIL",))


@pytest.mark.parametrize(
    "changes, code, action",
    [
        ({"match_status": "NOT_FOUND", "inspected": False}, "P0_NOT_FOUND", "CHECK_ASSETS"),
        ({"match_status": "AMBIGUOUS", "inspected": False}, "P0_AMBIGUOUS", "CHECK_ASSETS"),
        ({"match_status": "CONFLICT", "inspected": False}, "P0_CONFLICT", "CHECK_ASSETS"),
        ({"match_status": "INACCESSIBLE", "inspected": False}, "P0_INACCESSIBLE", "CHECK_ASSETS"),
        ({"match_status": "INVENTORY_INCOMPLETE", "inspected": False}, "P0_INVENTORY_INCOMPLETE", "CHECK_ASSETS"),
        ({"inspected": False}, "NOT_INSPECTED", "CHECK_ASSETS"),
        ({"g0_action": "REVIEW_B", "g1_status": "NOT_EVALUATED", "g2_status": "SKIPPED"}, "G0_REVIEW_B", "CHECK_ASSETS"),
        ({"g1_status": "REVIEW"}, "G1_REVIEW", "CHECK_DUPLICATE"),
        ({"g1_search_completed": False}, "G1_INCOMPLETE", "CHECK_DUPLICATE"),
        ({"g1_status": None}, "G1_INCOMPLETE", "CHECK_DUPLICATE"),
        ({"g2_status": "REVIEW"}, "G2_REVIEW", "REVIEW_MANUAL"),
        ({"g2_status": None}, "G2_INCOMPLETE", "REVIEW_MANUAL"),
        ({"g2_status": None, "g2_call_failed": True}, "G2_CALL_FAILED", "REVIEW_MANUAL"),
        ({"reference_mode": "UNRESOLVED_REFERENCE"}, "REFERENCE_UNRESOLVED", "CHECK_ASSETS"),
        ({"reference_readiness": "HOLD"}, "REFERENCE_HOLD", "CHECK_ASSETS"),
        ({"reference_mode": "PROVIDED_REFERENCE", "reference_conflict": True}, "REFERENCE_CONFLICT", "CHECK_ASSETS"),
    ],
)
def test_rule4_review_causes(changes: dict, code: str, action: str) -> None:
    d = decide_final(replace(PASS_ROW, **changes))
    assert (d.rule, d.status, d.next_action) == (4, "REVIEW", action)
    assert d.reason_codes == (code,)


def test_unresolved_reference_with_hold_reports_both() -> None:
    """E열 값 있음 → UNRESOLVED, G2 readiness HOLD → 최종 REVIEW (00 6.2 기본값)."""
    d = decide_final(replace(PASS_ROW, reference_mode="UNRESOLVED_REFERENCE", reference_readiness="HOLD"))
    assert (d.status, d.next_action) == ("REVIEW", "CHECK_ASSETS")
    assert d.reason_codes == ("REFERENCE_UNRESOLVED", "REFERENCE_HOLD")


@pytest.mark.parametrize("action", ["KEEP", "REGENERATE"])
def test_rule5_pass(action: str) -> None:
    d = decide_final(replace(PASS_ROW, g0_action=action))
    assert (d.rule, d.status, d.next_action, d.reason_codes) == (5, "PASS", "HANDOFF_TO_AI_TEAM", ())


def test_first_match_only() -> None:
    assert decide_final(replace(PASS_ROW, g1_status="DUPLICATE", g0_action="RESELECT_B", g2_status="FAIL")).rule == 1
    assert decide_final(replace(PASS_ROW, g0_action="RESELECT_B", g2_status="FAIL")).rule == 2
    assert decide_final(replace(PASS_ROW, g2_status="FAIL", g1_status="REVIEW", match_status="AMBIGUOUS")).rule == 3


def test_multiple_causes_priority_and_all_codes_kept() -> None:
    """원인이 여럿이면 CHECK_ASSETS > CHECK_DUPLICATE > REVIEW_MANUAL, 원인 전부는 reason_codes에."""
    d = decide_final(replace(PASS_ROW, g1_status="REVIEW", g2_status="REVIEW"))
    assert d.next_action == "CHECK_DUPLICATE" and d.reason_codes == ("G1_REVIEW", "G2_REVIEW")
    d = decide_final(replace(PASS_ROW, g2_status="REVIEW", g1_status="REVIEW", reference_mode="UNRESOLVED_REFERENCE"))
    assert d.next_action == "CHECK_ASSETS"
    assert d.reason_codes == ("G1_REVIEW", "G2_REVIEW", "REFERENCE_UNRESOLVED")


@pytest.mark.parametrize("failure, code", [("CALL_FAILED", "G0_CALL_FAILED"), ("VALIDATION_FAILED", "G0_VALIDATION_FAILED")])
def test_g0_failure_is_review_manual_exception(failure: str, code: str) -> None:
    """결정 18: G0 두 번 실패 → REVIEW_B(RULE), 최종 REVIEW, next_action은 예외로 REVIEW_MANUAL."""
    row = replace(PASS_ROW, g0_action="REVIEW_B", g0_failure=failure, g1_status="NOT_EVALUATED",
                  g2_status="SKIPPED", reference_mode="UNRESOLVED_REFERENCE")
    d = decide_final(row)
    assert (d.rule, d.status, d.next_action) == (4, "REVIEW", "REVIEW_MANUAL")
    assert d.reason_codes == (code, "REFERENCE_UNRESOLVED")


def test_g0_failure_requires_review_b() -> None:
    with pytest.raises(ValueError):
        decide_final(replace(PASS_ROW, g0_failure="CALL_FAILED"))


def test_original_task_empty_code_is_added() -> None:
    d = decide_final(replace(PASS_ROW, g0_action="REGENERATE", original_task_empty=True))
    assert d.status == "PASS" and d.reason_codes == ("ORIGINAL_TASK_EMPTY",)


def test_provided_reference_does_not_block_pass() -> None:
    """Reference 제공 여부 자체는 REVIEW 사유가 아니다 (06 최소 검증 8)."""
    assert decide_final(replace(PASS_ROW, reference_mode="PROVIDED_REFERENCE")).status == "PASS"


def test_all_codes_are_in_enum() -> None:
    codes = set(enum_values("reason_code"))
    assert set(REVIEW_CAUSE_ACTION) <= codes
    assert {"DUPLICATE", "RESELECT_B", "G2_FAIL", "ORIGINAL_TASK_EMPTY"} <= codes


def test_no_rule_matched_raises() -> None:
    with pytest.raises(NoRuleMatched):
        decide_final(replace(PASS_ROW, g1_status="NOT_EVALUATED"))


def test_unknown_enum_value_rejected() -> None:
    with pytest.raises(ValueError):
        decide_final(replace(PASS_ROW, g2_status="DESIGNABLE"))
