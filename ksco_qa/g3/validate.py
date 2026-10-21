"""G3 검증 — 골격 (설계 5.7-4, 9.1 G3 행 / 06_Result_Schema.md 최소 검증 1~10)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def check_row_counts(datalist_rows: int, gate_files: dict[str, Path], jsonl_records: list[dict[str, Any]]) -> list[str]:
    """06-1, 9.1: 원본 데이터 행 수 = 모든 Gate Excel 행 수 = JSONL 레코드 수 (5개 파일 행 수 일치)."""
    raise NotImplementedError


def check_row_identity(datalist_rows: list[dict[str, Any]], jsonl_records: list[dict[str, Any]]) -> list[str]:
    """06-2: source_row와 id가 원본 행에 대응, 정렬·삭제·삽입 없음."""
    raise NotImplementedError


def check_source_cells(source_cells: list[dict[str, Any]], jsonl_records: list[dict[str, Any]]) -> list[str]:
    """06-3, 9.1: source.cells와 원본 대조."""
    raise NotImplementedError


def check_match_method(jsonl_records: list[dict[str, Any]]) -> list[str]:
    """06-4: D_F_EXACT_FILENAME 외의 매핑 방법이 MATCHED로 기록되지 않았는가."""
    raise NotImplementedError


def check_regenerate_task(jsonl_records: list[dict[str, Any]]) -> list[str]:
    """06-5: REGENERATE 행에 regenerated_task_new가 있고 effective_task와 정확히 일치하는가."""
    raise NotImplementedError


def check_duplicate_consistency(jsonl_records: list[dict[str, Any]]) -> list[str]:
    """06-6: DUPLICATE면 대표 행 존재, verify SKIPPED, final FAIL."""
    raise NotImplementedError


def check_search_completed(jsonl_records: list[dict[str, Any]]) -> list[str]:
    """06-7: 미평가 후보가 있는데 search_completed=true가 아닌가."""
    raise NotImplementedError


def check_reference_not_auto_review(jsonl_records: list[dict[str, Any]]) -> list[str]:
    """06-8: Reference 부재를 이유로 자동 REVIEW하지 않았는가."""
    raise NotImplementedError


def check_pass_conditions(jsonl_records: list[dict[str, Any]]) -> list[str]:
    """06-9: final PASS면 G0 채택, G1 완료/UNIQUE, G2 PASS, 핵심 자료 확인."""
    raise NotImplementedError


def check_summary_counts(jsonl_records: list[dict[str, Any]], report: dict[str, Any]) -> list[str]:
    """06-10: 요약의 Gate별 집계가 행 수·후보쌍 수와 맞는가 (API판은 QA_SUMMARY 대신 run_report)."""
    raise NotImplementedError


def check_enums(jsonl_records: list[dict[str, Any]]) -> list[str]:
    """9.1: 모든 enum 필드가 enums.yaml 허용값인가 (DESIGNABLE 같은 값 차단, 7.5)."""
    raise NotImplementedError


def check_all_null_fields(jsonl_records: list[dict[str, Any]]) -> list[str]:
    """9.1: 전 행 null인 필드 = 실패 (교훈 #9)."""
    raise NotImplementedError


def check_template_sentences(jsonl_records: list[dict[str, Any]], min_rows: int = 10) -> list[str]:
    """9.1: 같은 문장이 min_rows행 이상 반복되면 템플릿 판정으로 실패."""
    raise NotImplementedError


def validate_all(task_folder: Path, run_dir: Path) -> dict[str, list[str]]:
    """위 검사를 모두 돌려 검사 이름 → 실패 메시지 목록을 돌려준다."""
    raise NotImplementedError
