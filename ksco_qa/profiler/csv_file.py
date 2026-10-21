"""CSV 프로필 — 골격 (설계 부록 B CSV 행)."""

from __future__ import annotations

from pathlib import Path

from ksco_qa.profiler.base import FileProfile


def profile(path: Path, locator: str) -> FileProfile:
    """인코딩, 열 수·헤더, 데이터 행 수, 앞·중간·끝 샘플 각 3행, 범주형 열 고유값(최대 20개),
    숫자 열 최소·최대, 합계·소계 행 여부. UTF-8 → CP949 순서로 시도.
    수십 MB 파일은 스트리밍으로 행 수만 세고 샘플만 읽는다."""
    raise NotImplementedError
