"""enum·criterion 사전과 스키마 로더 (설계 8.1).

dictionaries/enums.yaml이 enum의 유일한 출처다 (CLAUDE.md 핵심 원칙 4).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DICT_DIR = REPO_ROOT / "dictionaries"
SCHEMA_DIR = REPO_ROOT / "schemas"
PROMPT_DIR = REPO_ROOT / "prompts"
CRITERIA_DIR = REPO_ROOT / "criteria"

SCHEMA_NAMES = ("g0", "g1b", "g2")


@lru_cache(maxsize=None)
def load_enums() -> dict[str, Any]:
    with open(DICT_DIR / "enums.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def enum_values(name: str) -> list[str]:
    values = load_enums().get(name)
    if not isinstance(values, list):
        raise KeyError(f"enums.yaml에 enum '{name}'이 없다")
    return values


@lru_cache(maxsize=None)
def load_criteria() -> list[dict[str, Any]]:
    with open(DICT_DIR / "criteria.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["indicators"]


def g0_check_keys() -> list[str]:
    """G0 10개 차원 이름 (부록 A 순서)."""
    return [c["g0_key"] for c in load_criteria() if c["g0_key"] is not None]


def g2_check_keys() -> list[str]:
    """G2 16개 지표 이름 (부록 A 순서)."""
    return [c["g2_key"] for c in load_criteria()]


def g2_overlap_keys() -> list[str]:
    """G0와 겹치는 G2 지표 10개."""
    return [c["g2_key"] for c in load_criteria() if c["g0_key"] is not None]


def g2_new_keys() -> list[str]:
    """G2 고유 지표 6개."""
    return [c["g2_key"] for c in load_criteria() if c["g0_key"] is None]


def criterion_for(key: str) -> str:
    """G0 또는 G2 지표 이름으로 criterion 고정 문장을 찾는다."""
    for c in load_criteria():
        if key in (c["g0_key"], c["g2_key"]):
            return c["criterion"]
    raise KeyError(f"criteria.yaml에 지표 '{key}'가 없다")


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    if name not in SCHEMA_NAMES:
        raise KeyError(f"알 수 없는 스키마 '{name}'")
    with open(SCHEMA_DIR / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)
