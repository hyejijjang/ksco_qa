"""G1b — 쌍 판정 (모델, 묶음 1개 = 호출 1회) — 골격 (설계 5.4 / 00_Work_Run.md 5.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ksco_qa.config import Config


def build_input(bundle: list[tuple[int, int]], row_cards: dict[int, dict[str, Any]], effective: dict[int, Any]) -> dict[str, Any]:
    """묶음에 든 행들의 effective_task·task_card·직업·D/F, 판정할 쌍 목록."""
    raise NotImplementedError


def missing_pairs(bundle: list[tuple[int, int]], output: dict[str, Any]) -> list[tuple[int, int]]:
    """입력 쌍이 출력에 빠짐없이 한 번씩 있는지 확인. 빠진 쌍만 돌려준다 (재호출 대상)."""
    raise NotImplementedError


async def run_g1b(bundles: list[list[tuple[int, int]]], row_cards: list[dict[str, Any]], cfg: Config, run_dir: Path, client: Any) -> list[dict[str, Any]]:
    """출력: _work/g1/pairs.jsonl (추가 전용)."""
    raise NotImplementedError
