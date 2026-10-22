from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from ksco_qa.config import Config
from ksco_qa.llm.client import CallsLogWriter, LLMClient
from ksco_qa.llm.mock import MockClient, MockFaults
from ksco_qa.stages.g1b import build_input, missing_pairs, run_g1b, validate_output

CARDS = [
    {"source_row": 2, "id": "T-001", "job": "직업 A", "deliverable_title": "산출물 A", "format": "xlsx",
     "original_task": "Task A", "job_leaf": "직업 A"},
    {"source_row": 4, "id": "T-002", "job": "직업 B", "deliverable_title": "산출물 B", "format": "csv",
     "original_task": "Task B", "job_leaf": "직업 B"},
    {"source_row": 7, "id": "T-003", "job": "직업 C", "deliverable_title": "산출물 C", "format": "pdf",
     "original_task": "Task C", "job_leaf": "직업 C"},
]
G0 = [
    {"source_row": 2, "id": "T-001", "action": "KEEP",
     "output": {"task_card": {"input": "원자료 A", "operations": ["집계"], "criteria": ["합계 확인"], "output": "표 A"}}},
    {"source_row": 4, "id": "T-002", "action": "REGENERATE",
     "output": {"regenerated_task_new": "새 Task B",
                "task_card": {"input": "원자료 B", "operations": ["분류"], "criteria": ["범주 대조"], "output": "표 B"}}},
    {"source_row": 7, "id": "T-003", "action": "KEEP",
     "output": {"task_card": {"input": "원자료 C", "operations": ["검토"], "criteria": ["오류 점검"], "output": "목록 C"}}},
]
EFFECTIVE = {2: "Task A", 4: "새 Task B", 7: "Task C"}
OUTPUT_PAIR = {
    "row_1": 2,
    "row_2": 4,
    "verdict": "SEMANTIC",
    "evidence": "두 Task는 원자료의 합계를 확인해 표로 정리한다.",
    "conclusion": "집계와 결과 정리 역량이 겹친다.",
}


def make_client(run_dir: Path, faults: MockFaults | None = None) -> LLMClient:
    return LLMClient(
        Config(),
        run_dir,
        CallsLogWriter(run_dir),
        MockClient(faults),
        llm="mock",
        run_id="mock-test",
    )


def test_build_input_includes_only_rows_in_bundle_and_effective_data() -> None:
    g0_by_row = {record["source_row"]: record for record in G0}
    rows = {
        card["source_row"]: card | {"_g0_output": g0_by_row[card["source_row"]]["output"]}
        for card in CARDS
    }

    result = build_input([(2, 4)], rows, EFFECTIVE)

    assert result["pairs"] == [[2, 4]]
    assert [row["source_row"] for row in result["rows"]] == [2, 4]
    assert result["rows"][1]["effective_task"] == "새 Task B"
    assert result["rows"][1]["task_card"] == G0[1]["output"]["task_card"]
    assert "id" not in result["rows"][0] and "original_task" not in result["rows"][0]


def test_build_input_rejects_missing_task_card_or_task() -> None:
    with pytest.raises(ValueError, match="task_card"):
        build_input([(2, 4)], {2: CARDS[0], 4: CARDS[1]}, {2: "Task A"})

    rows = {2: CARDS[0] | {"_g0_output": {"task_card": {}}}, 4: CARDS[1] | {"_g0_output": {"task_card": {}}}}
    with pytest.raises(ValueError, match="effective_task"):
        build_input([(2, 4)], rows, {})


def test_missing_pairs_reports_only_unreturned_input_pairs() -> None:
    expected = [(2, 4), (2, 7), (4, 7)]
    output = {"pairs": [{"row_1": 2, "row_2": 4}, {"row_1": 4, "row_2": 7}]}

    assert missing_pairs(expected, output) == [(2, 7)]


def test_validate_output_enforces_coverage_added_pair_scope_and_conclusions() -> None:
    valid = {
        "pairs": [OUTPUT_PAIR],
        "added_pairs": [
            {"row_1": 4, "row_2": 7, "verdict": "DISTINCT", "evidence": "입력과 판단 규칙이 다르다.", "conclusion": None}
        ],
    }
    assert validate_output([(2, 4)], {2, 4, 7}, valid) == []

    invalid = {
        "pairs": [OUTPUT_PAIR, OUTPUT_PAIR],
        "added_pairs": [
            {"row_1": 4, "row_2": 9, "verdict": "DISTINCT", "evidence": "외부 행", "conclusion": "불가"},
            {"row_1": 4, "row_2": 4, "verdict": "SEMANTIC", "evidence": "", "conclusion": None},
        ],
    }
    errors = validate_output([(2, 4)], {2, 4, 7}, invalid)
    assert any("중복 판정" in error for error in errors)
    assert any("묶음 밖" in error for error in errors)
    assert any("오름차순" in error for error in errors)
    assert any("evidence가 비어" in error for error in errors)


def test_run_g1b_records_results_and_reuses_success_on_resume(tmp_path: Path) -> None:
    cfg = Config()
    bundle = [(2, 4)]
    candidates = [{"rows": [2, 4], "signals": ["param"], "similarities": {"param": 0.8}, "similarity": 1.0}]
    client = make_client(tmp_path)

    first = asyncio.run(run_g1b(
        [bundle], CARDS, cfg, tmp_path, client, g0_records=G0, effective=EFFECTIVE, candidate_pairs=candidates
    ))
    second = asyncio.run(run_g1b(
        [bundle], CARDS, cfg, tmp_path, client, g0_records=G0, effective=EFFECTIVE, candidate_pairs=candidates
    ))

    path = tmp_path / "g1" / "pairs.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["source_rows"] == [2, 4]
    assert records[0]["signals"] == ["param"]
    assert records[0]["status"] == "OK"
    assert first == second == records
    assert len((tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_run_g1b_logs_unresolved_pairs_after_validation_retries(tmp_path: Path) -> None:
    client = make_client(tmp_path, MockFaults(validation_fail=1.0, repeats=2))

    records = asyncio.run(run_g1b(
        [[(2, 4)]], CARDS, Config(), tmp_path, client, g0_records=G0, effective=EFFECTIVE
    ))

    [record] = records
    assert record["source_rows"] == [2, 4]
    assert record["verdict"] is None
    assert record["status"] == "VALIDATION_FAIL"
    assert record["failure"]
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 3
    assert "-missing-" in calls[1]["unit_id"]
    assert calls[1]["unit_id"] == calls[2]["unit_id"]
    assert calls[-1]["attempt_kind"] == "feedback"


class StaticClient:
    def __init__(self, parsed: dict[str, Any]) -> None:
        self.parsed = parsed

    async def call(self, **kwargs: Any):
        from ksco_qa.llm.types import CallResult

        errors = kwargs["validator"](self.parsed)
        assert not errors
        return CallResult("static-call", "OK", self.parsed, None, "first")


class RetryClient:
    def __init__(self, parsed: dict[str, Any]) -> None:
        self.parsed = parsed
        self.calls = 0

    async def call(self, **kwargs: Any):
        from ksco_qa.llm.types import CallResult

        self.calls += 1
        if self.calls == 1:
            return CallResult("retry-call", "FAILED", None, None, "first", ["temporary failure"])
        errors = kwargs["validator"](self.parsed)
        assert not errors
        return CallResult("retry-call", "OK", self.parsed, None, "first")


class PartialRecoveryClient:
    def __init__(self) -> None:
        self.inputs: list[dict[str, Any]] = []

    async def call(self, **kwargs: Any):
        from ksco_qa.llm.types import CallResult

        self.inputs.append(kwargs["variable_input"])
        if len(self.inputs) == 1:
            output = {"pairs": [OUTPUT_PAIR], "added_pairs": []}
            call_id = "partial-call"
        else:
            output = {
                "pairs": [
                    {"row_1": 2, "row_2": 7, "verdict": "DISTINCT",
                     "evidence": "입력과 판단 규칙이 다르다.", "conclusion": None}
                ],
                "added_pairs": [],
            }
            call_id = "recovery-call"
        errors = kwargs["validator"](output)
        assert not errors
        return CallResult(call_id, "OK", output, None, "first")


def test_run_g1b_retries_only_missing_pairs(tmp_path: Path) -> None:
    client = PartialRecoveryClient()

    records = asyncio.run(run_g1b(
        [[(2, 4), (2, 7)]], CARDS, Config(), tmp_path, client, g0_records=G0, effective=EFFECTIVE
    ))

    assert [call["pairs"] for call in client.inputs] == [[[2, 4], [2, 7]], [[2, 7]]]
    assert [record["source_rows"] for record in records] == [[2, 4], [2, 7]]
    assert {record["call_id"] for record in records} == {"partial-call", "recovery-call"}


def test_run_g1b_appends_recovery_after_failed_call(tmp_path: Path) -> None:
    client = RetryClient({"pairs": [OUTPUT_PAIR], "added_pairs": []})

    first = asyncio.run(run_g1b(
        [[(2, 4)]], CARDS, Config(), tmp_path, client, g0_records=G0, effective=EFFECTIVE
    ))
    second = asyncio.run(run_g1b(
        [[(2, 4)]], CARDS, Config(), tmp_path, client, g0_records=G0, effective=EFFECTIVE
    ))
    records = [json.loads(line) for line in (tmp_path / "g1" / "pairs.jsonl").read_text(encoding="utf-8").splitlines()]

    assert [record["verdict"] for record in first] == [None]
    assert [record["verdict"] for record in second] == ["SEMANTIC"]
    assert [record["status"] for record in records] == ["FAILED", "OK"]


def test_run_g1b_saves_model_added_pair(tmp_path: Path) -> None:
    output = {
        "pairs": [
            OUTPUT_PAIR,
            {"row_1": 2, "row_2": 7, "verdict": "DISTINCT", "evidence": "입력과 판단 규칙이 다르다.",
             "conclusion": None},
        ],
        "added_pairs": [
            {"row_1": 4, "row_2": 7, "verdict": "HIGH_OVERLAP", "evidence": "두 작업은 입력 자료를 검토한다.",
             "conclusion": "검토 방식은 겹치지만 입력과 판단 기준이 다르다."}
        ],
    }
    records = asyncio.run(run_g1b(
        [[(2, 4), (2, 7)]], CARDS, Config(), tmp_path, StaticClient(output), g0_records=G0, effective=EFFECTIVE
    ))

    assert [(record["source_rows"], record["added"]) for record in records] == [
        ([2, 4], False), ([2, 7], False), ([4, 7], True)
    ]
    assert records[2]["signals"] == []


def test_run_g1b_with_no_bundles_writes_empty_result_log(tmp_path: Path) -> None:
    records = asyncio.run(run_g1b([], CARDS, Config(), tmp_path, make_client(tmp_path), g0_records=G0))

    assert records == []
    assert (tmp_path / "g1" / "pairs.jsonl").is_file()
    assert not (tmp_path / "calls.jsonl").exists()
