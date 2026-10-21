"""G0 — Task 수정·재생성 (모델, 행 1개 = 호출 1회) — 골격 (설계 5.2, 6.1, 9.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ksco_qa.config import Config


def rule_record(row_card: dict[str, Any]) -> dict[str, Any]:
    """inspected=false 행: action=REVIEW_B, 사유 = P0 상태, decided_by=RULE (5.2 대상)."""
    raise NotImplementedError


def build_input(row_card: dict[str, Any]) -> dict[str, Any]:
    """그 행의 row_card만 넣는다. 다른 행 정보·Task 이름·폴더 이름 금지 (5.2 입력, 6.2)."""
    raise NotImplementedError


def validate_output(row_card: dict[str, Any], output: dict[str, Any]) -> list[str]:
    """호출 직후 코드 검증 (5.2): job_evaluated = row_card job_leaf, F가 있는데 KEEP,
    REGENERATE인데 새 Task가 비었거나 원본과 같음, 차원별 issues 문장 복사. 위반 메시지 목록을 돌려준다."""
    raise NotImplementedError


def needs_escalation(output: dict[str, Any], validation_errors: list[str]) -> bool:
    """G0_ESCALATE: 검증 실패 또는 REGENERATE·RESELECT_B·REVIEW_B면 high로 한 번 더 (6.1)."""
    raise NotImplementedError


def stage_end_checks(records: list[dict[str, Any]], row_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """G0 단계 끝 검사 (9.1): 같은 reason 문장 3회 이상, 한 직업에서만 RESELECT_B·REVIEW_B ≥ 50%."""
    raise NotImplementedError


async def run_g0(row_cards: list[dict[str, Any]], cfg: Config, run_dir: Path, client: Any) -> list[dict[str, Any]]:
    """출력: _work/g0/records.jsonl (추가 전용). 완료 조건: 전 데이터 행에 action, REGENERATE 행에 새 Task (5.2)."""
    raise NotImplementedError
