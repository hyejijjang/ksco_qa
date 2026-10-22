from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ksco_qa.config import Config
from ksco_qa.llm.client import CallsLogWriter, LLMClient
from ksco_qa.llm.mock import MockClient
from ksco_qa.stages.g1c import (
    assign_overlap_status,
    assign_status,
    build_groups,
    choose_representative,
    missing_direct_pairs,
    run_g1c,
)

CARDS = [
    {"source_row": 2, "id": "T-001", "inspected": True, "job": "직업 A", "job_leaf": "직업 A",
     "deliverable_title": "문서 A", "format": "xlsx", "original_task": "Task A"},
    {"source_row": 4, "id": "T-002", "inspected": True, "job": "직업 B", "job_leaf": "직업 B",
     "deliverable_title": "문서 B", "format": "csv", "original_task": "Task B"},
    {"source_row": 7, "id": "T-003", "inspected": False, "job": "직업 C", "job_leaf": "직업 C",
     "deliverable_title": "문서 C", "format": "pdf", "original_task": "Task C"},
    {"source_row": 10, "id": "T-004", "inspected": True, "job": "직업 D", "job_leaf": "직업 D",
     "deliverable_title": "문서 D", "format": "xlsx", "original_task": None},
]
G0 = [
    {
        "source_row": 2, "id": "T-001",
        "output": {"checks": {"job_fit": "R", "deliverable_fit": "P"}, "task_card": {"summary": "Task A"}},
    },
    {
        "source_row": 4, "id": "T-002",
        "output": {"checks": {"job_fit": "P", "deliverable_fit": "P"}, "task_card": {"summary": "Task B"}},
    },
    {
        "source_row": 7, "id": "T-003",
        "output": {"checks": {"job_fit": "P"}, "task_card": {"summary": "Task C"}},
    },
    {"source_row": 10, "id": "T-004", "output": None},
]
EFFECTIVE = {2: "Task A", 4: "Task B", 7: "Task C"}


def pair(
    left: int,
    right: int,
    verdict: str,
    *,
    status: str = "OK",
    added: bool = False,
    similarity: float | None = 0.8,
) -> dict:
    return {
        "source_rows": [left, right],
        "verdict": verdict,
        "evidence": f"행 {left}과 {right} 비교 근거",
        "conclusion": None if verdict == "DISTINCT" else f"행 {left}와 {right} 판정",
        "signals": ["tfidf_task"],
        "similarities": {"tfidf_task": similarity} if similarity else {},
        "similarity": similarity,
        "status": status,
        "added": added,
        "call_id": f"call-{left}-{right}-{verdict}",
        "bundle_id": "bundle-test",
    }


def make_client(run_dir: Path) -> LLMClient:
    return LLMClient(
        Config(),
        run_dir,
        CallsLogWriter(run_dir),
        MockClient(),
        llm="mock",
        run_id="mock-g1c-test",
    )


def test_build_groups_uses_only_successful_confirmed_verdicts() -> None:
    records = [
        pair(2, 4, "SEMANTIC"),
        pair(4, 7, "PARAMETER_VARIANT", added=True),
        pair(2, 7, "DISTINCT"),
        pair(7, 10, "EXACT", status="FAILED"),
    ]

    assert build_groups(records) == [{2, 4, 7}]


def test_representative_uses_inspection_then_job_fit_then_pass_count_then_row() -> None:
    cards = {
        2: CARDS[0] | {"inspected": True},
        4: CARDS[1] | {"inspected": False},
    }
    g0 = {
        2: G0[0] | {"output": {"checks": {"job_fit": "R", "deliverable_fit": "P"}}},
        4: G0[1] | {"output": {"checks": {"job_fit": "P"}}},
    }

    assert choose_representative({2, 4}, cards, g0) == 2
    cards[4] = cards[4] | {"inspected": True}
    assert choose_representative({2, 4}, cards, g0) == 4
    g0[2] = g0[2] | {"output": {"checks": {"job_fit": "P", "deliverable_fit": "P"}}}
    assert choose_representative({2, 4}, cards, g0) == 2
    g0[4] = g0[4] | {"output": {"checks": {"job_fit": "P", "deliverable_fit": "P"}}}
    assert choose_representative({2, 4}, cards, g0) == 2


def test_missing_direct_pairs_does_not_repeat_already_adjudicated_distinct() -> None:
    records = [pair(2, 4, "SEMANTIC"), pair(4, 7, "SEMANTIC"), pair(2, 7, "DISTINCT")]

    assert missing_direct_pairs({2, 4, 7}, 2, records) == []
    assert missing_direct_pairs({2, 4, 7}, 2, records[:2]) == [(2, 7)]


def test_assign_status_preserves_duplicate_review_and_search_completeness_rules() -> None:
    group = {2, 4, 7}
    representatives = {1: 4}
    records = [
        pair(2, 4, "SEMANTIC"),
        pair(4, 7, "PARAMETER_VARIANT"),
        pair(2, 7, "HIGH_OVERLAP"),
    ]

    rows = assign_status(
        CARDS,
        [group],
        representatives,
        records,
        active_rows={2, 4, 7},
        search_completed=True,
    )

    assert rows[4]["status"] == "UNIQUE" and rows[4]["representative_id"] == "T-002"
    assert rows[2]["status"] == "DUPLICATE" and rows[2]["representative_row"] == 4
    assert rows[7]["status"] == "DUPLICATE"
    assert rows[2]["overlap_status"] == "HIGH_OVERLAP"
    assert rows[2]["unresolved_candidate_count"] == 0 and rows[2]["search_completed"]
    assert rows[10]["status"] == "NOT_EVALUATED"
    assert rows[10]["overlap_status"] == "UNDETERMINED"

    incomplete = assign_status(CARDS[:1], [], {}, [], active_rows={2}, search_completed=False)
    assert incomplete[2]["status"] == "REVIEW"
    assert incomplete[2]["duplicate_type"] == "UNDETERMINED"
    assert incomplete[2]["overlap_status"] == "UNDETERMINED"

    unresolved = assign_status(
        CARDS,
        [{2, 4}],
        {1: 4},
        [pair(2, 4, "SEMANTIC"), pair(2, 7, "DISTINCT", status="FAILED")],
        active_rows={2, 4, 7},
        search_completed=True,
    )
    assert unresolved[2]["status"] == "REVIEW"
    assert unresolved[2]["overlap_status"] == "UNDETERMINED"
    assert unresolved[2]["unresolved_candidate_count"] == 1
    assert not unresolved[2]["search_completed"]


def test_assign_overlap_status_is_non_null_for_all_cases() -> None:
    records = [pair(2, 4, "HIGH_OVERLAP"), pair(4, 7, "DISTINCT")]

    assert assign_overlap_status(2, records, True) == "HIGH_OVERLAP"
    assert assign_overlap_status(7, records, True) == "NONE"
    assert assign_overlap_status(10, records, False) == "UNDETERMINED"


def test_run_g1c_checks_representative_directly_and_appends_rows(tmp_path: Path) -> None:
    pairs = [pair(2, 4, "SEMANTIC"), pair(4, 7, "SEMANTIC")]
    candidates = [
        {"rows": [2, 4], "signals": ["param"], "similarities": {"param": 0.9}, "similarity": 0.9},
        {"rows": [4, 7], "signals": ["tfidf_task"], "similarities": {"tfidf_task": 0.8}, "similarity": 0.8},
    ]
    cards = [card | {"inspected": card["source_row"] == 2} for card in CARDS]
    g0 = [
        record | {"output": record["output"] | {"checks": {"job_fit": "P", "deliverable_fit": "P"}}}
        if record["source_row"] == 2 else record
        for record in G0
    ]
    pair_path = tmp_path / "g1" / "pairs.jsonl"
    pair_path.parent.mkdir(parents=True)
    pair_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in pairs),
        encoding="utf-8",
    )
    rows = asyncio.run(run_g1c(
        cards,
        g0,
        pairs,
        Config(),
        tmp_path,
        make_client(tmp_path),
        candidate_pairs=candidates,
        search_completed=True,
        effective=EFFECTIVE,
    ))

    assert (tmp_path / "g1" / "rows.jsonl").is_file()
    stored = [json.loads(line) for line in (tmp_path / "g1" / "rows.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(stored) == len(cards)
    assert rows[2]["status"] == "UNIQUE"
    assert rows[10]["status"] == "NOT_EVALUATED"
    assert len((tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()) == 1

    asyncio.run(run_g1c(
        cards,
        g0,
        pairs,
        Config(),
        tmp_path,
        make_client(tmp_path),
        candidate_pairs=candidates,
        search_completed=True,
        effective=EFFECTIVE,
    ))
    assert len((tmp_path / "g1" / "rows.jsonl").read_text(encoding="utf-8").splitlines()) == len(cards)


def test_run_g1c_keeps_confirmed_duplicate_but_marks_incomplete_search(tmp_path: Path) -> None:
    rows = asyncio.run(run_g1c(
        CARDS,
        G0,
        [pair(2, 4, "EXACT")],
        Config(),
        tmp_path,
        make_client(tmp_path),
        candidate_pairs=[{"rows": [2, 4], "signals": ["exact"], "similarities": {}, "similarity": 1.0}],
        search_completed=False,
        effective=EFFECTIVE,
    ))

    assert rows[2]["status"] == "DUPLICATE"
    assert rows[4]["status"] == "UNIQUE"
    assert not rows[4]["search_completed"]
