"""비교 도구 — 골격 (설계 4.1 비교 도구, 9.3, 10.1 compare --with)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_final_jsonl(results_dir: Path) -> list[dict[str, Any]]:
    """03_results/03_final.jsonl을 읽는다 (Work 분할본과 API 결과 공통 형식, 3장 원칙 8)."""
    raise NotImplementedError


def g0_action_agreement(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any]:
    """9.3: G0 action 일치율 / Cohen's kappa (source_row 기준 정렬)."""
    raise NotImplementedError


def duplicate_pair_diff(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any]:
    """9.3: G1 확정 중복 쌍 양방향 차이."""
    raise NotImplementedError


def verify_status_agreement(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any]:
    """9.3: 양쪽 모두 평가한 행의 G2 verify_status 일치율."""
    raise NotImplementedError


def final_status_agreement(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any]:
    """9.3: 최종 status 일치율."""
    raise NotImplementedError


def compare_results(left: Path, right: Path) -> dict[str, Any]:
    """두 결과 폴더의 일치도 리포트. 불일치 행은 4분류 대상으로 목록화 (9.3)."""
    raise NotImplementedError
