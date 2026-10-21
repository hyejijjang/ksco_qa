"""G3 내보내기 — 골격 (설계 5.7-2·3·5, 7.4, 9.2 / 06_Result_Schema.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ksco_qa.config import Config

SCHEMA_VERSION = "ksco-taskqa/canonical-1.0"


CALL_STAGES = ("G0", "G1B", "G2")


def execution_notes_object(*, run_id: str, llm: str, cfg: Config, prompt_versions: dict[str, str]) -> dict[str, Any]:
    """run_report.json에 남길 실행 방식 객체 (7.4). mock run이면 "MOCK"을 기록해 실제 결과와 구분한다."""
    mock = llm == "mock"
    return {
        "pipeline": "API 파이프라인",
        "llm": "MOCK" if mock else "OPENAI",
        "run_id": run_id,
        "mode": cfg.MODE,
        "models": {s: ("mock" if mock else getattr(cfg, f"MODEL_{s}")) for s in CALL_STAGES},
        "reasoning_effort": {s: getattr(cfg, f"EFFORT_{s}") for s in CALL_STAGES},
        "prompt_versions": dict(prompt_versions),
        "G2_OVERLAP_MODE": cfg.G2_OVERLAP_MODE,
        "review_independence": "SEPARATE_CALL",
    }


def execution_notes(*, run_id: str, llm: str, cfg: Config, prompt_versions: dict[str, str]) -> str:
    """final.execution_notes 문자열 (06에 타입 없음 → M1 결정 19).
    예: "API 파이프라인; run_id=…; G0=모델/추론강도; G1B=…; G2=…; prompt=G0:…,G1B:…,G2:…;
    G2_OVERLAP_MODE=…; review_independence=SEPARATE_CALL". mock이면 "API 파이프라인(MOCK)"."""
    o = execution_notes_object(run_id=run_id, llm=llm, cfg=cfg, prompt_versions=prompt_versions)
    parts = ["API 파이프라인(MOCK)" if o["llm"] == "MOCK" else "API 파이프라인", f"run_id={run_id}"]
    parts += [f"{s}={o['models'][s]}/{o['reasoning_effort'][s]}" for s in CALL_STAGES]
    parts.append("prompt=" + ",".join(f"{s}:{prompt_versions.get(s, '-')}" for s in CALL_STAGES))
    parts.append(f"G2_OVERLAP_MODE={o['G2_OVERLAP_MODE']}")
    parts.append(f"review_independence={o['review_independence']}")
    return "; ".join(parts)


def expand_checks(model_checks: dict[str, str], issues: dict[str, str | None], evidence_loc: str) -> dict[str, dict[str, str]]:
    """5.7-2: status는 모델 값(P/R/F/NA → PASS/REVIEW/FAIL/N_A), criterion은 criteria.yaml,
    evidence는 evidence_loc, conclusion은 R/F면 issues 문장, P면 "기준 충족 (G2 판정)"."""
    raise NotImplementedError


def build_final_record(source_row: int, inputs: dict[str, Any]) -> dict[str, Any]:
    """7.4: 최상위 키 12개 (06 스키마 그대로) + 각 Gate 객체 decided_by, duplicate.candidate_pairs[],
    final.execution_notes. overlap_status null 금지."""
    raise NotImplementedError


def write_revision_xlsx(path: Path, records: list[dict[str, Any]]) -> None:
    """03_results/00_revision_regenerate.xlsx (5.2 출력)."""
    raise NotImplementedError


def write_duplicate_audit_xlsx(path: Path, records: list[dict[str, Any]]) -> None:
    """03_results/01_duplicate_audit.xlsx — audit 열 + coverage 열 (5.5 출력)."""
    raise NotImplementedError


def write_task_verify_xlsx(path: Path, records: list[dict[str, Any]]) -> None:
    """03_results/02_task_verify.xlsx (5.7-3)."""
    raise NotImplementedError


def write_final_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """03_results/03_final.jsonl — 원본 1행 = 객체 1개 = 1줄, UTF-8 (5.7-3)."""
    raise NotImplementedError


def write_review_queue(path: Path, records: list[dict[str, Any]]) -> None:
    """_work/review_queue.csv — 9.2 샘플링 표 (RESELECT_B·G2 FAIL 전체, 재판정·REVIEW 전체,
    REGENERATE 20%(최소 10행), DUPLICATE 그룹 20%(최소 5그룹), 최종 PASS 무작위 20행)."""
    raise NotImplementedError


def apply_overrides(records: list[dict[str, Any]], overrides_path: Path) -> list[dict[str, Any]]:
    """_work/overrides.jsonl의 사람 판정을 decided_by=HUMAN으로 반영 (9.2). 모델 호출 없음."""
    raise NotImplementedError


def write_run_report(path: Path, summary: dict[str, Any]) -> None:
    """_work/run_report.json — 요약·검증·비용 (5.7-5, 10.4)."""
    raise NotImplementedError


def run_g3(task_folder: Path, run_dir: Path) -> str:
    """5.7 전체. 검증 실패가 하나라도 있으면 run 상태 FAILED_VALIDATION (파일은 남김)."""
    raise NotImplementedError
