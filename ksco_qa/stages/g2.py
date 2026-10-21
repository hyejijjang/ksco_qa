"""G2 — Task 설계 품질 검수 (모델, 행 1개 = 호출 1회) — 골격 (설계 5.6 / 00_Work_Run.md 6장)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ksco_qa.config import Config


def skip_record(source_row: int, skip_reason: str) -> dict[str, Any]:
    """대상이 아닌 행: verify.status=SKIPPED + skip_reason, decided_by=RULE (5.6 대상)."""
    raise NotImplementedError


def is_target(g0_record: dict[str, Any], g1_record: dict[str, Any]) -> bool:
    """G0가 KEEP/REGENERATE이고 G1이 DUPLICATE가 아닌 행 (5.6)."""
    raise NotImplementedError


def build_input(row_card: dict[str, Any], effective_task: str, g0_record: dict[str, Any], overlap_mode: str) -> dict[str, Any]:
    """row_card + effective_task + g2_overlap_mode. AGREE_CHECK: REGENERATE 행은 G0 값 제외,
    KEEP 행은 G0 값 포함. FULL_RECHECK: 모든 행에서 G0 값 제외 (5.6).
    G0 값은 g0_checks 키로 넣고, 지표 이름은 dictionaries.g2_key_for()로 G2 이름으로 바꾼다."""
    raise NotImplementedError


def validate_output(row_card: dict[str, Any], output: dict[str, Any]) -> tuple[list[str], list[str]]:
    """5.6 코드 검증. (재호출 대상 오류, 경고) 반환:
    F가 있는데 PASS, GENERATE_REFERENCE인데 reference_action≠GENERATE → 오류.
    disagree 정합 (스키마로 막을 수 없음) → 오류:
      G0 값이 입력에 없는데 disagree가 있음, g0_value가 입력의 G0 값과 다름,
      new_value가 overlap_review.checks[indicator]와 다름, g0_value = new_value, 같은 지표 중복,
      G0 값과 checks가 다른 지표인데 disagree에 없음.
    Reference (결정 1·29) → 오류: UNRESOLVED_REFERENCE인데 reference_action≠CHECK_ACCESS 또는 reference_readiness≠HOLD,
      PROVIDED_REFERENCE가 아닌데 reference_conflict가 true, reference_conflict=true인데 note 없음.
    Blueprint에 row_card에 없는 숫자 패턴 → 경고."""
    raise NotImplementedError


async def run_g2(row_cards: list[dict[str, Any]], g0_records: list[dict[str, Any]], g1_records: dict[int, dict[str, Any]], cfg: Config, run_dir: Path, client: Any) -> list[dict[str, Any]]:
    """출력: _work/g2/records.jsonl (추가 전용). review_independence=SEPARATE_CALL."""
    raise NotImplementedError
