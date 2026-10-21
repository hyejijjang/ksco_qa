"""XLSX·XLS·ODS 프로필 — 골격 (설계 부록 B XLSX·XLS·ODS 행)."""

from __future__ import annotations

from pathlib import Path

from ksco_qa.profiler.base import FileProfile


def profile(path: Path, locator: str) -> FileProfile:
    """시트 목록, 시트별 사용 범위, 머리글 영역(병합 셀 포함), 수식·합계 열, 앞·끝 샘플.
    머리글이 여러 행인 통계표가 많다. 수식은 캐시값과 원문을 모두 확인한다."""
    raise NotImplementedError
