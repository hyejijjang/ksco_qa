from __future__ import annotations

import json
from pathlib import Path

from ksco_qa.config import Config
from ksco_qa.stages.g1a import (
    effective_tasks,
    generate_candidates,
    make_bundles,
    signal_card,
    signal_exact,
    signal_param,
    signal_same_deliverable,
    signal_tfidf,
    write_search_artifacts,
)


def test_effective_tasks_uses_g0_action_and_skips_rows_without_effective_task() -> None:
    cards = [
        {"source_row": 2, "original_task": "원본 Task"},
        {"source_row": 3, "original_task": "수정 전"},
        {"source_row": 4, "original_task": "판정 보류"},
        {"source_row": 5, "original_task": None},
    ]
    records = [
        {"source_row": 2, "action": "KEEP", "output": {"regenerated_task_new": None}},
        {"source_row": 3, "action": "REGENERATE", "output": {"regenerated_task_new": "새 Task"}},
        {"source_row": 4, "action": "REVIEW_B", "output": None},
        {"source_row": 5, "action": "KEEP", "output": {}},
    ]

    assert effective_tasks(cards, records) == {2: "원본 Task", 3: "새 Task"}


def test_exact_and_param_signals_normalize_text() -> None:
    assert signal_exact({2: "회계, 합계 검산!", 4: " 회계 합계검산 ", 7: "다른 업무"}) == {(2, 4)}
    assert signal_param({
        2: "2024년 서울 3개 자료센터 조사",
        4: "2025년 부산 4개 통계공단 조사",
        7: "2025년 부산 4개 통계공단 집계",
    }) == {(2, 4)}


def test_same_deliverable_matches_expected_filename_and_numberless_title() -> None:
    cards = [
        {"source_row": 2, "expected_filename": "report.xlsx", "deliverable_title": "보고서 2024"},
        {"source_row": 4, "expected_filename": "report.xlsx", "deliverable_title": "보고서 2025"},
        {"source_row": 7, "expected_filename": "other.xlsx", "deliverable_title": "다른 양식"},
    ]

    assert signal_same_deliverable(cards) == {(2, 4)}


def test_tfidf_signals_apply_threshold_and_top_k() -> None:
    texts = {
        2: "회계 장부 합계 검산",
        4: "회계 장부 합계 확인",
        7: "회계 장부 합계 계산",
    }

    assert signal_tfidf(texts, threshold=0.1, top_k=1)
    assert signal_tfidf(texts, threshold=1.1, top_k=5) == {}
    assert signal_card({
        2: {"input": "회계 장부", "operations": ["합계 검산"]},
        4: {"input": "회계 장부", "operations": ["합계 확인"]},
    }, threshold=0.1)


def test_generate_candidates_uses_effective_task_and_records_signals() -> None:
    cards = [
        {"source_row": 2, "original_task": "월별 급여 합계 검산", "deliverable_title": "급여표 2024",
         "expected_filename": "급여표.xlsx"},
        {"source_row": 4, "original_task": "월별 급여 합계 계산", "deliverable_title": "급여표 2025",
         "expected_filename": "급여표.xlsx"},
        {"source_row": 7, "original_task": "다른 Task", "deliverable_title": "별도 서식",
         "expected_filename": "별도.xlsx"},
    ]
    records = [
        {"source_row": 2, "action": "KEEP", "output": {"task_card": {"operations": ["급여 합계 검산"]}}},
        {"source_row": 4, "action": "REGENERATE",
         "output": {"regenerated_task_new": "월별 급여 합계 검산", "task_card": {"operations": ["급여 합계 검산"]}}},
        {"source_row": 7, "action": "REVIEW_B", "output": None},
    ]

    result = generate_candidates(cards, records, Config())

    assert result["active_rows"] == [2, 4]
    assert result["candidate_count"] == 1
    assert result["pairs"][0]["rows"] == [2, 4]
    assert {"exact", "same_deliverable", "tfidf_task", "card", "tfidf_orig"} <= set(result["pairs"][0]["signals"])
    assert result["candidate_cap"] == 20
    assert len(result["search_id"]) == 64


def test_make_bundles_respects_pair_and_row_caps_without_losing_pairs() -> None:
    pairs = [(1, 2), (1, 3), (1, 4), (1, 5), (5, 6), (6, 7), (8, 9)]

    bundles = make_bundles(pairs, max_pairs=2, max_rows=3)

    assert all(len(bundle) <= 2 for bundle in bundles)
    assert all(len({row for pair in bundle for row in pair}) <= 3 for bundle in bundles)
    assert sorted(pair for bundle in bundles for pair in bundle) == sorted(pairs)
    assert len({pair for bundle in bundles for pair in bundle}) == len(pairs)


def test_write_search_artifacts_is_append_only_and_idempotent(tmp_path: Path) -> None:
    result = {
        "search_id": "stable-search",
        "active_rows": [2, 4],
        "active_row_count": 2,
        "candidate_count": 1,
        "mean_candidates_per_active_row": 1.0,
        "candidate_cap": 20,
        "cap_exceeded_by_fixed_signals": False,
        "signal_counts": {"exact": 1},
        "thresholds": {"tfidf_task": 0.3},
        "target_candidates_per_row": [3, 8],
        "pairs": [{"rows": [2, 4], "signals": ["exact"], "similarities": {"exact": 1.0}, "similarity": 1.0}],
    }
    bundles = [[(2, 4)]]

    directory = tmp_path / "g1"
    directory.mkdir()
    candidate = {"search_id": "stable-search", **result["pairs"][0]}
    (directory / "candidates.jsonl").write_text(json.dumps(candidate) + "\n", encoding="utf-8")

    write_search_artifacts(result, bundles, tmp_path)
    write_search_artifacts(result, bundles, tmp_path)

    candidate_lines = (directory / "candidates.jsonl").read_text(encoding="utf-8").splitlines()
    bundle_lines = (directory / "bundles.jsonl").read_text(encoding="utf-8").splitlines()
    summary_lines = (directory / "search.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(candidate_lines) == len(bundle_lines) == len(summary_lines) == 1
    assert json.loads(bundle_lines[0])["pairs"] == [[2, 4]]
