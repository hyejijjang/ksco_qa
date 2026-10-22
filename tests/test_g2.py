from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ksco_qa.config import Config
from ksco_qa.dictionaries import g0_check_keys, g2_new_keys, g2_overlap_keys
from ksco_qa.llm.client import CallsLogWriter, LLMClient
from ksco_qa.llm.mock import MockClient, MockFaults
from ksco_qa.stages.g2 import (
    build_input,
    is_target,
    run_g2,
    skip_record,
    validate_output,
)


def card(
    row: int,
    *,
    reference_mode: str = "GENERATE_REFERENCE",
    original_task: str | None = "Task 입력",
) -> dict:
    return {
        "source_row": row,
        "id": f"T-{row:03}",
        "job": "회계: 사무원",
        "job_leaf": "사무원",
        "deliverable_title": "예산 집행 현황",
        "format": "xlsx",
        "reference_mode": reference_mode,
        "reference_note": None,
        "file_profile": "시트1 10행 x 4열, 기준연도 2024",
        "original_task": original_task,
        "original_task_empty": original_task is None,
    }


def g0_record(
    row: int,
    action: str = "KEEP",
    *,
    checks: dict[str, str] | None = None,
) -> dict:
    return {
        "source_row": row,
        "id": f"T-{row:03}",
        "action": action,
        "decided_by": "MODEL",
        "failure": None,
        "output": {
            "checks": checks or {key: "P" for key in g0_check_keys()},
            "regenerated_task_new": "재생성 Task" if action == "REGENERATE" else None,
        } if action in ("KEEP", "REGENERATE") else None,
    }


def g2_output(
    row_card: dict,
    *,
    status: str = "REVIEW",
    reference_action: str | None = None,
    reference_readiness: str = "BLUEPRINT_READY",
) -> dict:
    overlap = {key: "P" for key in g2_overlap_keys()}
    new = {key: "P" for key in g2_new_keys()}
    issues = {key: None for key in (*g2_overlap_keys(), *g2_new_keys())}
    mode = row_card["reference_mode"]
    if reference_action is None:
        reference_action = {
            "GENERATE_REFERENCE": "GENERATE",
            "UNRESOLVED_REFERENCE": "CHECK_ACCESS",
            "PROVIDED_REFERENCE": "REUSE",
        }[mode]
    if mode == "UNRESOLVED_REFERENCE":
        reference_readiness = "HOLD"
    return {
        "verify_status": status,
        "overlap_review": {"mode": "AGREE_CHECK", "checks": overlap, "disagree": []},
        "new_checks": new,
        "b_coverage_status": "SUFFICIENT",
        "reference_action": reference_action,
        "reference_readiness": reference_readiness,
        "reference_conflict": None,
        "reference_conflict_note": None,
        "blueprints": {
            "scenario": "2024년 자료를 확인한다",
            "reference": "필요한 자료를 설계한다",
            "reasoning_map": "입력에서 결과를 도출한다",
            "evaluation": "산출물과 대조한다",
        },
        "reason": "이 행의 Task와 산출물을 검토했다",
        "evidence_loc": "file_profile: 시트1",
        "issues": issues,
        "proposed_fix": "요청 범위를 구체화한다" if status != "PASS" else None,
    }


def make_client(run_dir: Path, faults: MockFaults | None = None) -> LLMClient:
    cfg = Config()
    return LLMClient(
        cfg,
        run_dir,
        CallsLogWriter(run_dir),
        MockClient(faults),
        llm="mock",
        run_id="mock-g2-test",
    )


def test_skip_record_and_target_selection() -> None:
    assert skip_record(3, "DUPLICATE_TASK") == {
        "source_row": 3,
        "status": "SKIPPED",
        "skip_reason": "DUPLICATE_TASK",
        "decided_by": "RULE",
        "failure": None,
        "rule_reason": None,
        "flags": [],
        "output": None,
    }
    assert is_target(g0_record(2), {"status": "REVIEW"})
    assert not is_target(g0_record(2), {"status": "DUPLICATE"})
    assert not is_target(g0_record(2, "REVIEW_B"), {"status": "UNIQUE"})


def test_build_input_obeys_overlap_mode_and_g0_action() -> None:
    row = card(2)
    g0 = g0_record(2)
    variable = build_input(row, "Task 입력", g0, "AGREE_CHECK")
    assert variable["row_card"] == row
    assert variable["effective_task"] == "Task 입력"
    assert variable["g2_overlap_mode"] == "AGREE_CHECK"
    assert set(variable["g0_checks"]) == set(g2_overlap_keys())
    assert variable["g0_checks"]["reasoning_requirement"] == "P"
    assert "g0_checks" not in build_input(row, "새 Task", g0_record(2, "REGENERATE"), "AGREE_CHECK")
    assert "g0_checks" not in build_input(row, "Task 입력", g0, "FULL_RECHECK")


def test_validate_output_checks_reference_f_and_blueprint_numbers() -> None:
    row = card(2)
    output = g2_output(row, status="PASS")
    assert validate_output(row, output, overlap_mode="AGREE_CHECK") == ([], [])

    output["blueprints"]["scenario"] = "2025년 기준"
    errors, warnings = validate_output(row, output, overlap_mode="AGREE_CHECK")
    assert not errors
    assert warnings == ["BLUEPRINT_UNGROUNDED_NUMBER:scenario:2025"]

    output["new_checks"]["task_clarity"] = "F"
    output["reference_action"] = "REUSE"
    errors, _ = validate_output(row, output, overlap_mode="AGREE_CHECK")
    assert any("F인데 verify_status가 PASS" in error for error in errors)
    assert any("GENERATE_REFERENCE" in error for error in errors)

    output = g2_output(row, status="PASS")
    output["b_coverage_status"] = "PARTIAL_CRITICAL"
    errors, _ = validate_output(row, output, overlap_mode="AGREE_CHECK")
    assert any("PARTIAL_CRITICAL" in error for error in errors)

    unresolved = card(3, reference_mode="UNRESOLVED_REFERENCE")
    unresolved_output = g2_output(unresolved)
    unresolved_output["reference_readiness"] = "READY_AS_IS"
    errors, _ = validate_output(unresolved, unresolved_output, overlap_mode="AGREE_CHECK")
    assert any("UNRESOLVED_REFERENCE" in error for error in errors)


def test_validate_output_requires_consistent_g0_disagreements() -> None:
    row = card(2)
    checks = {key: "P" for key in g2_overlap_keys()}
    checks["grounding"] = "R"
    g0_checks = {key: "P" for key in g2_overlap_keys()}
    output = g2_output(row)
    output["overlap_review"]["checks"] = checks
    item = {
        "indicator": "grounding",
        "g0_value": "P",
        "new_value": "R",
        "reason": "file_profile 근거에서 차이를 확인했다",
    }
    output["overlap_review"]["disagree"] = [item]
    assert validate_output(row, output, g0_checks=g0_checks, overlap_mode="AGREE_CHECK") == ([], [])

    output["overlap_review"]["disagree"] = []
    errors, _ = validate_output(row, output, g0_checks=g0_checks, overlap_mode="AGREE_CHECK")
    assert any("disagree에 빠졌다" in error for error in errors)

    output["overlap_review"]["disagree"] = [item | {"g0_value": "R"}]
    errors, _ = validate_output(row, output, g0_checks=g0_checks, overlap_mode="AGREE_CHECK")
    assert any("g0_value가 입력의 G0 값과 다르다" in error for error in errors)


def test_validate_output_rejects_reference_conflict_outside_provided_mode() -> None:
    row = card(2)
    output = g2_output(row)
    output["reference_conflict"] = True
    output["reference_conflict_note"] = "구조가 충돌함"
    errors, _ = validate_output(row, output, overlap_mode="AGREE_CHECK")
    assert any("PROVIDED_REFERENCE" in error for error in errors)

    provided = card(2, reference_mode="PROVIDED_REFERENCE")
    output = g2_output(provided)
    output["reference_conflict"] = True
    output["reference_conflict_note"] = "   "
    errors, _ = validate_output(provided, output, overlap_mode="AGREE_CHECK")
    assert any("reference_conflict_note가 비어 있다" in error for error in errors)


def test_run_g2_skips_ineligible_rows_and_is_append_only(tmp_path: Path) -> None:
    cards = [
        card(2),
        card(3),
        card(4),
        card(5),
        card(6, original_task=None),
    ]
    g0 = [
        g0_record(2),
        g0_record(3, "REGENERATE"),
        g0_record(4),
        g0_record(5, "REVIEW_B"),
        g0_record(6),
    ]
    g1 = {
        2: {"source_row": 2, "id": "T-002", "status": "UNIQUE"},
        3: {"source_row": 3, "id": "T-003", "status": "REVIEW"},
        4: {"source_row": 4, "id": "T-004", "status": "DUPLICATE"},
        5: {"source_row": 5, "id": "T-005", "status": "NOT_EVALUATED"},
        6: {"source_row": 6, "id": "T-006", "status": "NOT_EVALUATED"},
    }
    client = make_client(tmp_path)
    records = asyncio.run(run_g2(cards, g0, g1, Config(), tmp_path, client))
    assert [record["source_row"] for record in records] == [2, 3, 4, 5, 6]
    assert all(record["status"] in ("PASS", "REVIEW", "FAIL") for record in records[:2])
    assert records[2]["skip_reason"] == "DUPLICATE_TASK"
    assert records[3]["skip_reason"] == "G0_REVIEW_B"
    assert records[4]["skip_reason"] == "NO_EFFECTIVE_TASK"
    assert all(record["decided_by"] == "MODEL" for record in records[:2])

    calls_path = tmp_path / "calls.jsonl"
    before_calls = calls_path.read_text(encoding="utf-8").splitlines()
    record_path = tmp_path / "g2" / "records.jsonl"
    before_records = record_path.read_text(encoding="utf-8").splitlines()
    records_again = asyncio.run(run_g2(cards, g0, g1, Config(), tmp_path, client))
    assert records_again == records
    assert calls_path.read_text(encoding="utf-8").splitlines() == before_calls
    assert record_path.read_text(encoding="utf-8").splitlines() == before_records


@pytest.mark.parametrize(
    ("faults", "expected_failure"),
    [
        (MockFaults(timeout=1.0, repeats=2), "CALL_FAILED"),
        (MockFaults(validation_fail=1.0, repeats=2), "VALIDATION_FAILED"),
    ],
)
def test_run_g2_maps_exhausted_failures_to_rule_review(
    tmp_path: Path,
    faults: MockFaults,
    expected_failure: str,
) -> None:
    row = card(2)
    records = asyncio.run(run_g2(
        [row],
        [g0_record(2)],
        {2: {"source_row": 2, "id": "T-002", "status": "UNIQUE"}},
        Config(),
        tmp_path,
        make_client(tmp_path, faults),
    ))
    assert len(records) == 1
    assert records[0]["status"] == "REVIEW"
    assert records[0]["decided_by"] == "RULE"
    assert records[0]["failure"] == expected_failure
    assert records[0]["output"] is None
