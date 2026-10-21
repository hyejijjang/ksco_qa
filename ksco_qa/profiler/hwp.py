"""HWP(구버전) 프로필 — 골격 (설계 부록 B HWP 행)."""

from __future__ import annotations

from pathlib import Path

from ksco_qa.profiler.base import FileProfile


def profile(path: Path, locator: str) -> FileProfile:
    """읽을 수 있으면 본문 텍스트 요약. 도구가 없으면 inspected=False(NOT_INSPECTED) + 사유."""
    raise NotImplementedError
