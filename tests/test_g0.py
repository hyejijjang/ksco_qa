"""G0 — 행별 검증, escalation, 추가 전용 기록, mock 재개."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fixtures.gate_records import g0_output
from ksco_qa.config import Config
from ksco_qa.llm.client import CallsLogWriter, LLMClient
from ksco_qa.llm.mock import MockClient
from ksco_qa.llm.types import CallResult
from ksco_qa.p0 import run_p0
from ksco_qa.stages.g0 import (
    build_input,
    needs_escalation,
    rule_record,
    run_g0,
    stage_end_checks,
    validate_output,
)


def test_rule_record_for_uninspected_card() -> None:
    card = {"source_row": 7, "id": "T-007", "inspected": False, "match_status": "NOT_FOUND"}
    assert rule_record(card) == {
        "source_row": 7,
        "id": "T-007",
        "action": "REVIEW_B",
        "decided_by": "RULE",
        "failure": None,
        "rule_reason": "NOT_INSPECTED: NOT_FOUND",
        "output": None,
        "escalated": False,
    }


def test_build_input_is_only_the_given_row() -> None:
    card = {"source_row": 2, "id": "T-001", "job_leaf": "회계 사무원", "original_task": "원본"}
    assert build_input(card) is card


def test_validate_output_checks_job_keep_regenerate_and_duplicate_issues(sample_task: Path) -> None:
    cards = run_p0(sample_task, Config(), sample_task / "test-run", sample_task / "mapping.csv").row_cards
    card = cards[0]
    output = g0_output(card, "KEEP")
    output["job_evaluated"] = "다른 직업"
    output["checks"]["job_fit"] = "R"
    output["checks"]["deliverable_fit"] = "F"
    output["issues"]["job_fit"] = "같은 사유"
    output["issues"]["deliverable_fit"] = "같은 사유"
    errors = validate_output(card, output)
    assert any("job_evaluated" in error for error in errors)
    assert any("F인데 action이 KEEP" in error for error in errors)
    assert any("issues 문장이 복사" in error for error in errors)

    regenerate = g0_output(card, "REGENERATE")
    regenerate["regenerated_task_new"] = card["original_task"]
    assert any("original_task와 같다" in error for error in validate_output(card, regenerate))

    empty_card = card | {"original_task": None, "original_task_empty": True}
    empty_keep = g0_output(empty_card, "KEEP")
    assert any("ORIGINAL_TASK_EMPTY" in error for error in validate_output(empty_card, empty_keep))


def test_escalation_conditions() -> None:
    assert needs_escalation({"action": "KEEP"}, ["job mismatch"])
    assert needs_escalation({"action": "REVIEW_B"}, [])
    assert not needs_escalation({"action": "KEEP"}, [])


def test_stage_end_checks_detect_repeated_reason_and_job_concentration() -> None:
    cards = [
        {"source_row": row, "job_leaf": "회계 사무원"}
        for row in (2, 3, 4, 5)
    ]
    records = [
        {"source_row": 2, "action": "REVIEW_B", "decided_by": "MODEL",
         "output": {"reason": "같은 이유"}},
        {"source_row": 3, "action": "RESELECT_B", "decided_by": "MODEL",
         "output": {"reason": "같은 이유"}},
        {"source_row": 4, "action": "KEEP", "decided_by": "MODEL",
         "output": {"reason": "같은 이유"}},
        {"source_row": 5, "action": "REVIEW_B", "decided_by": "RULE", "output": None},
    ]
    checks = stage_end_checks(records, cards)
    assert {check["check"] for check in checks} == {"REPEATED_REASON", "JOB_REVIEW_ACTION_CONCENTRATION"}
    assert {row for check in checks for row in check["source_rows"]} == {2, 3, 4}


def test_run_g0_writes_rule_and_model_records_and_resumes(sample_task: Path, tmp_path: Path) -> None:
    cfg = Config()
    p0 = run_p0(sample_task, cfg, tmp_path, tmp_path / "00_mapping_audit.csv")
    llm = LLMClient(cfg, tmp_path, CallsLogWriter(tmp_path), MockClient(), llm="mock", run_id="mock-g0-test")
    records = asyncio.run(run_g0(p0.row_cards, cfg, tmp_path, llm))
    path = tmp_path / "g0" / "records.jsonl"
    saved = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert len(records) == len(p0.row_cards) == len(saved)
    assert [record["source_row"] for record in records] == [card["source_row"] for card in p0.row_cards]
    assert all(record["action"] in ("KEEP", "REGENERATE", "REVIEW_B", "RESELECT_B") for record in records)
    for card, record in zip(p0.row_cards, records):
        if card["inspected"]:
            assert record["decided_by"] in ("MODEL", "RULE")
            if record["decided_by"] == "MODEL":
                assert validate_output(card, record["output"]) == []
        else:
            assert (record["action"], record["decided_by"], record["failure"]) == ("REVIEW_B", "RULE", None)

    calls_before = len((tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines())
    records_again = asyncio.run(run_g0(p0.row_cards, cfg, tmp_path, llm))
    calls_after = len((tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines())
    saved_after = path.read_text(encoding="utf-8").splitlines()
    assert calls_after == calls_before
    assert len(saved_after) == len(saved)
    assert records_again == records
