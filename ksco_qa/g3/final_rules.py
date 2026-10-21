"""최종 판정 규칙 (설계 부록 C, 5.7-1 / 00_Work_Run.md 7.1).

위에서부터 먼저 맞는 규칙 하나만 적용한다. 어떤 규칙에도 맞지 않으면 판정을 지어내지 않고 오류를 낸다.
HIGH_OVERLAP만으로는 FAIL이 되지 않는다 (overlap_status는 입력으로 받지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass

from ksco_qa.dictionaries import enum_values

# 규칙 4의 원인 → next_action. 원인이 여럿이면 이 순서(부록 C 조건 나열 순)의 첫 원인으로 next_action을 정한다.
REVIEW_CAUSE_ACTION: dict[str, str] = {
    "P0_UNRESOLVED": "CHECK_ASSETS",
    "G0_REVIEW_B": "CHECK_ASSETS",
    "G1_REVIEW": "CHECK_DUPLICATE",
    "G1_INCOMPLETE": "CHECK_DUPLICATE",
    "G2_REVIEW": "REVIEW_MANUAL",
    "G2_INCOMPLETE": "REVIEW_MANUAL",
    "REFERENCE_UNRESOLVED": "CHECK_ASSETS",
}


class NoRuleMatched(Exception):
    """부록 C의 어떤 규칙에도 맞지 않는 입력 (앞 단계 결과의 모순 또는 누락)."""


@dataclass(frozen=True)
class FinalInputs:
    """한 행의 최종 판정 입력. 단계 결과가 없으면(호출 실패·미실행) None."""

    match_status: str
    inspected: bool
    reference_mode: str
    g0_action: str | None
    g1_status: str | None
    g1_search_completed: bool
    g2_status: str | None


@dataclass(frozen=True)
class FinalDecision:
    rule: int
    status: str
    next_action: str
    causes: tuple[str, ...] = ()


def _check(value: str | None, enum_name: str, field: str) -> None:
    if value is not None and value not in enum_values(enum_name):
        raise ValueError(f"{field}={value!r}는 enums.yaml '{enum_name}' 허용값이 아니다")


def review_causes(x: FinalInputs) -> list[str]:
    """규칙 4 조건 중 해당하는 원인 목록 (부록 C 나열 순)."""
    causes: list[str] = []
    if not (x.match_status == "MATCHED" and x.inspected):
        causes.append("P0_UNRESOLVED")
    if x.g0_action == "REVIEW_B":
        causes.append("G0_REVIEW_B")
    if x.g1_status == "REVIEW":
        causes.append("G1_REVIEW")
    elif x.g1_status is None or (x.g1_status == "UNIQUE" and not x.g1_search_completed):
        causes.append("G1_INCOMPLETE")
    if x.g2_status == "REVIEW":
        causes.append("G2_REVIEW")
    elif x.g2_status is None:
        causes.append("G2_INCOMPLETE")
    if x.reference_mode == "UNRESOLVED_REFERENCE":
        causes.append("REFERENCE_UNRESOLVED")
    return causes


def decide_final(x: FinalInputs) -> FinalDecision:
    _check(x.match_status, "match_status", "match_status")
    _check(x.reference_mode, "reference_mode", "reference_mode")
    _check(x.g0_action, "revision_action", "g0_action")
    _check(x.g1_status, "duplicate_status", "g1_status")
    _check(x.g2_status, "verify_status", "g2_status")

    # 1. G1 DUPLICATE
    if x.g1_status == "DUPLICATE":
        return FinalDecision(1, "FAIL", "EXCLUDE_DUPLICATE")
    # 2. G0 RESELECT_B
    if x.g0_action == "RESELECT_B":
        return FinalDecision(2, "FAIL", "RESELECT_DELIVERABLE")
    # 3. G2 FAIL
    if x.g2_status == "FAIL":
        return FinalDecision(3, "FAIL", "REVISE_TASK")
    # 4. P0 미해결, G0 REVIEW_B, G1 REVIEW·미완료, G2 REVIEW(·미완료), Reference 접근 불명
    causes = review_causes(x)
    if causes:
        return FinalDecision(4, "REVIEW", REVIEW_CAUSE_ACTION[causes[0]], tuple(causes))
    # 5. G0 KEEP·REGENERATE + G1 UNIQUE·완료 + G2 PASS + 매핑 오류 없음
    if (
        x.g0_action in ("KEEP", "REGENERATE")
        and x.g1_status == "UNIQUE"
        and x.g1_search_completed
        and x.g2_status == "PASS"
    ):
        return FinalDecision(5, "PASS", "HANDOFF_TO_AI_TEAM")
    raise NoRuleMatched(f"부록 C 규칙에 맞지 않는 입력: {x}")
