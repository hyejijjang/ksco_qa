"""HWPX·DOCX·ODT 프로필 — 골격 (설계 부록 B HWPX·DOCX·ODT 행)."""

from __future__ import annotations

from pathlib import Path

from ksco_qa.profiler.base import FileProfile


def profile(path: Path, locator: str) -> FileProfile:
    """제목 구조, 표 개수와 표별 머리글. HWPX·ODT는 XML을 직접 파싱한다."""
    raise NotImplementedError
