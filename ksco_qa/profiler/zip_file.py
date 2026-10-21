"""ZIP 프로필 — 골격 (설계 부록 B ZIP 행)."""

from __future__ import annotations

from pathlib import Path

from ksco_qa.profiler.base import FileProfile


def profile_member(zip_path: Path, member: str, locator: str) -> FileProfile:
    """멤버별로 형식 규칙을 적용한다. 멤버 경로를 matched_locator에 기록한다."""
    raise NotImplementedError
