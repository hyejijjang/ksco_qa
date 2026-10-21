"""PDF 프로필 — 골격 (설계 부록 B PDF 행)."""

from __future__ import annotations

from pathlib import Path

from ksco_qa.profiler.base import FileProfile


def profile(path: Path, locator: str) -> FileProfile:
    """페이지 수, 목차 또는 장·절 제목, 표 제목과 위치(페이지), 텍스트가 없는 스캔 여부.
    앞 몇 장만 보고 전체를 본 것처럼 쓰지 않는다. 확인 페이지 범위를 기록한다."""
    raise NotImplementedError
