"""G1a — 중복 후보 생성 (코드) — 골격 (설계 5.3 / 00_Work_Run.md 5.1)."""

from __future__ import annotations

from typing import Any

from ksco_qa.config import Config

# 5.3 신호 표: (이름, 제거 가능 여부)
SIGNALS = ("exact", "param", "same_deliverable", "tfidf_task", "card", "tfidf_orig")
ADJUSTABLE_SIGNALS = ("tfidf_task", "card", "tfidf_orig")


def effective_tasks(row_cards: list[dict[str, Any]], g0_records: list[dict[str, Any]]) -> dict[int, str]:
    """대상: effective_task가 있는 행 (KEEP=원본 G열, REGENERATE=새 Task)."""
    raise NotImplementedError


def signal_exact(tasks: dict[int, str]) -> set[tuple[int, int]]:
    """공백·구두점 제거 후 effective_task 동일."""
    raise NotImplementedError


def signal_param(tasks: dict[int, str]) -> set[tuple[int, int]]:
    """연도·숫자·기간·지역/기관명을 지운 뒤 Task 동일."""
    raise NotImplementedError


def signal_same_deliverable(row_cards: list[dict[str, Any]]) -> set[tuple[int, int]]:
    """expected_filename 동일, 또는 숫자 제거 D열 동일."""
    raise NotImplementedError


def signal_tfidf(texts: dict[int, str], threshold: float, top_k: int = 5) -> dict[tuple[int, int], float]:
    """문자 2~4gram TF-IDF, 행별 상위 top_k 중 유사도 ≥ threshold (tfidf_task 0.30, tfidf_orig 동일)."""
    raise NotImplementedError


def signal_card(task_cards: dict[int, dict[str, Any]], threshold: float, top_k: int = 5) -> dict[tuple[int, int], float]:
    """task_card 토큰 TF-IDF 또는 임베딩, 행별 상위 top_k 중 ≥ threshold (기본 0.40)."""
    raise NotImplementedError


def generate_candidates(row_cards: list[dict[str, Any]], g0_records: list[dict[str, Any]], cfg: Config) -> dict[str, Any]:
    """신호 합집합. 전체 쌍 > active 행 수 × 10이면 조정 가능 신호 임계값을 0.05씩 올린다.
    최종 임계값과 신호별 쌍 수를 기록한다. 쌍은 (min_row, max_row)로 한 번만 저장."""
    raise NotImplementedError


def make_bundles(pairs: list[tuple[int, int]], max_pairs: int, max_rows: int = 20) -> list[list[tuple[int, int]]]:
    """후보 그래프 연결 요소 기준, 묶음당 ≤ max_pairs쌍·≤ max_rows행. 같은 쌍이 두 묶음에 들어가지 않는다."""
    raise NotImplementedError
