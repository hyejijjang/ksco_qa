"""PPTX 프로필 — 골격 (설계 부록 B PPTX 행)."""

from __future__ import annotations

from pathlib import Path

from ksco_qa.profiler.base import FileProfile


def profile(path: Path, locator: str) -> FileProfile:
    """슬라이드 수, 슬라이드별 제목, 표·도표 여부."""
    raise NotImplementedError
