"""G1c — 그룹 확정 (코드 + 필요하면 추가 호출) — 골격 (설계 5.5 / 00_Work_Run.md 5.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ksco_qa.config import Config

CONFIRMED_VERDICTS = ("EXACT", "SEMANTIC", "PARAMETER_VARIANT")
MAX_DIRECT_CHECK_ROUNDS = 2


def build_groups(pairs: list[dict[str, Any]]) -> list[set[int]]:
    """5.5-1: EXACT·SEMANTIC·PARAMETER_VARIANT 쌍으로 연결 요소."""
    raise NotImplementedError


def choose_representative(group: set[int], row_cards: dict[int, dict[str, Any]], g0_records: dict[int, dict[str, Any]]) -> int:
    """5.5-2: P0 inspected → G0 job_fit=P → G0 P 개수 → 작은 source_row."""
    raise NotImplementedError


def missing_direct_pairs(group: set[int], representative: int, pairs: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """5.5-3: 대표-구성원 사이에 직접 판정된 확정 중복 쌍이 없는 구성원 쌍."""
    raise NotImplementedError


def assign_status(row_cards: list[dict[str, Any]], groups: list[set[int]], representatives: dict[int, int], pairs: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """5.5-4: 대표 UNIQUE, 제외 DUPLICATE(대표 행·id 필수), 미판정 후보 남은 행 REVIEW, Task 없는 행 NOT_EVALUATED."""
    raise NotImplementedError


def assign_overlap_status(source_row: int, pairs: list[dict[str, Any]], evaluated: bool) -> str:
    """5.5-5: HIGH_OVERLAP 쌍이 있으면 HIGH_OVERLAP, 쌍이 있으나 모두 DISTINCT면 NONE, 미평가 행 UNDETERMINED.
    LOW_OVERLAP은 쓰지 않는다 (CLAUDE.md 설계 보완). 모든 행에 채운다 (null 금지)."""
    raise NotImplementedError


async def run_g1c(row_cards: list[dict[str, Any]], g0_records: list[dict[str, Any]], pairs: list[dict[str, Any]], cfg: Config, run_dir: Path, client: Any) -> dict[int, dict[str, Any]]:
    """5.5 1~5. 직접 판정이 없으면 G1b 추가 호출 후 1로 돌아감, 최대 2회, 그래도 없으면 그 구성원 REVIEW."""
    raise NotImplementedError
