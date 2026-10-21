"""최종 판정 규칙 (00_Work_Run.md 7.1 원문, 설계 부록 C 요약 / CLAUDE.md 설계 보완 M1 결정 15~18, 29).

위에서부터 먼저 맞는 규칙 하나만 적용한다. 어떤 규칙에도 맞지 않으면 판정을 지어내지 않고 오류를 낸다.
HIGH_OVERLAP만으로는 FAIL이 되지 않는다 (overlap_status는 입력으로 받지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass

from ksco_qa.dictionaries import enum_values

# 규칙 4 원인 코드 → next_action. 원인이 여럿이면 ACTION_PRIORITY 순으로 하나만 쓴다 (결정 15).
REVIEW_CAUSE_ACTION: dict[str, str] = {
    "P0_NOT_FOUND": "CHECK_ASSETS",
    "P0_AMBIGUOUS": "CHECK_ASSETS",
    "P0_CONFLICT": "CHECK_ASSETS",
    "P0_INACCESSIBLE": "CHECK_ASSETS",
    "P0_INVENTORY_INCOMPLETE": "CHECK_ASSETS",
    "NOT_INSPECTED": "CHECK_ASSETS",
    "G0_REVIEW_B": "CHECK_ASSETS",
    "REFERENCE_UNRESOLVED": "CHECK_ASSETS",
    "REFERENCE_HOLD": "CHECK_ASSETS",
    "REFERENCE_CONFLICT": "CHECK_ASSETS",
    "G1_REVIEW": "CHECK_DUPLICATE",
    "G1_INCOMPLETE": "CHECK_DUPLICATE",
    "G2_REVIEW": "REVIEW_MANUAL",
    "G2_INCOMPLETE": "REVIEW_MANUAL",
    "G2_CALL_FAILED": "REVIEW_MANUAL",
    # 결정 18: G0 호출 실패·검증 2회 실패는 우선순위와 무관하게 REVIEW_MANUAL
    "G0_CALL_FAILED": "REVIEW_MANUAL",
    "G0_VALIDATION_FAILED": "REVIEW_MANUAL",
}
ACTION_PRIORITY = ("CHECK_ASSETS", "CHECK_DUPLICATE", "REVIEW_MANUAL")
G0_FAILURE_CODES = {"CALL_FAILED": "G0_CALL_FAILED", "VALIDATION_FAILED": "G0_VALIDATION_FAILED"}


class NoRuleMatched(Exception):
    """어떤 규칙에도 맞지 않는 입력 (앞 단계 결과의 모순 또는 누락)."""


@dataclass(frozen=True)
class FinalInputs:
    """한 행의 최종 판정 입력. 단계 결과가 없으면(미실행) None.

    g0_failure: G0 호출이 두 번 실패("CALL_FAILED") 또는 검증에 두 번 걸림("VALIDATION_FAILED").
                이때 g0_action은 REVIEW_B(decided_by=RULE) (결정 18).
    g2_call_failed: G2 호출이 실패해 판정이 없음 (g2_status=None).
    """

    match_status: str
    inspected: bool
    reference_mode: str
    g0_action: str | None
    g1_status: str | None
    g1_search_completed: bool
    g2_status: str | None
    reference_readiness: str | None = None
    reference_conflict: bool = False
    original_task_empty: bool = False
    g0_failure: str | None = None
    g2_call_failed: bool = False


@dataclass(frozen=True)
class FinalDecision:
    rule: int
    status: str
    next_action: str
    reason_codes: tuple[str, ...] = ()


def _check(value: str | None, enum_name: str, field: str) -> None:
    if value is not None and value not in enum_values(enum_name):
        raise ValueError(f"{field}={value!r}는 enums.yaml '{enum_name}' 허용값이 아니다")


def review_causes(x: FinalInputs) -> list[str]:
    """규칙 4 조건 중 해당하는 원인 코드 (00 7.1 나열 순)."""
    causes: list[str] = []
    if x.match_status != "MATCHED":
        causes.append(f"P0_{x.match_status}")
    elif not x.inspected:
        causes.append("NOT_INSPECTED")
    if x.g0_failure is not None:
        causes.append(G0_FAILURE_CODES[x.g0_failure])
    elif x.g0_action == "REVIEW_B":
        causes.append("G0_REVIEW_B")
    if x.g1_status == "REVIEW":
        causes.append("G1_REVIEW")
    elif x.g1_status is None or (x.g1_status == "UNIQUE" and not x.g1_search_completed):
        causes.append("G1_INCOMPLETE")
    if x.g2_status == "REVIEW":
        causes.append("G2_REVIEW")
    elif x.g2_status is None:
        causes.append("G2_CALL_FAILED" if x.g2_call_failed else "G2_INCOMPLETE")
    if x.reference_mode == "UNRESOLVED_REFERENCE":
        causes.append("REFERENCE_UNRESOLVED")
    if x.reference_readiness == "HOLD":
        causes.append("REFERENCE_HOLD")
    if x.reference_conflict:
        causes.append("REFERENCE_CONFLICT")
    return causes


def _next_action(causes: list[str]) -> str:
    if any(c in ("G0_CALL_FAILED", "G0_VALIDATION_FAILED") for c in causes):
        return "REVIEW_MANUAL"
    actions = {REVIEW_CAUSE_ACTION[c] for c in causes}
    return next(a for a in ACTION_PRIORITY if a in actions)


def decide_final(x: FinalInputs) -> FinalDecision:
    _check(x.match_status, "match_status", "match_status")
    _check(x.reference_mode, "reference_mode", "reference_mode")
    _check(x.g0_action, "revision_action", "g0_action")
    _check(x.g1_status, "duplicate_status", "g1_status")
    _check(x.g2_status, "verify_status", "g2_status")
    _check(x.reference_readiness, "reference_readiness", "reference_readiness")
    if x.g0_failure is not None and (x.g0_failure not in G0_FAILURE_CODES or x.g0_action != "REVIEW_B"):
        raise ValueError(f"g0_failure={x.g0_failure!r}는 g0_action=REVIEW_B와 함께만 쓴다")

    extra = ("ORIGINAL_TASK_EMPTY",) if x.original_task_empty else ()

    # 1. G1 DUPLICATE
    if x.g1_status == "DUPLICATE":
        return FinalDecision(1, "FAIL", "EXCLUDE_DUPLICATE", ("DUPLICATE", *extra))
    # 2. G0 RESELECT_B
    if x.g0_action == "RESELECT_B":
        return FinalDecision(2, "FAIL", "RESELECT_DELIVERABLE", ("RESELECT_B", *extra))
    # 3. G2 FAIL
    if x.g2_status == "FAIL":
        return FinalDecision(3, "FAIL", "REVISE_TASK", ("G2_FAIL", *extra))
    # 4. P0 미해결·G0 REVIEW_B·G1 REVIEW/미완료·G2 REVIEW/미완료·Reference 접근 불명(HOLD·CONFLICT 포함)
    causes = review_causes(x)
    if causes:
        return FinalDecision(4, "REVIEW", _next_action(causes), (*causes, *extra))
    # 5. G0 KEEP/REGENERATE + G1 UNIQUE·완료 + G2 PASS + 매핑 오류 없음 + readiness≠HOLD (규칙 4에서 걸러짐)
    if (
        x.g0_action in ("KEEP", "REGENERATE")
        and x.g1_status == "UNIQUE"
        and x.g1_search_completed
        and x.g2_status == "PASS"
    ):
        return FinalDecision(5, "PASS", "HANDOFF_TO_AI_TEAM", extra)
    raise NoRuleMatched(f"최종 판정 규칙에 맞지 않는 입력: {x}")
