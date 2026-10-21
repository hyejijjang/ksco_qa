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
    """row_card + effective_task. AGREE_CHECK: REGENERATE 행은 G0 값 제외, KEEP 행은 G0 값 포함.
    FULL_RECHECK: 모든 행에서 G0 값 제외 (5.6)."""
    raise NotImplementedError


def validate_output(row_card: dict[str, Any], output: dict[str, Any]) -> tuple[list[str], list[str]]:
    """5.6 코드 검증. (재호출 대상 오류, 경고) 반환:
    F가 있는데 PASS, GENERATE_REFERENCE인데 reference_action≠GENERATE → 오류.
    Blueprint에 row_card에 없는 숫자 패턴 → 경고."""
    raise NotImplementedError


async def run_g2(row_cards: list[dict[str, Any]], g0_records: list[dict[str, Any]], g1_records: dict[int, dict[str, Any]], cfg: Config, run_dir: Path, client: Any) -> list[dict[str, Any]]:
    """출력: _work/g2/records.jsonl (추가 전용). review_independence=SEPARATE_CALL."""
    raise NotImplementedError
