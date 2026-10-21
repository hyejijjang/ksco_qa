"""파일 프로파일러 — 골격 (설계 4.1, 5.1-10, 부록 B).

형식별 구조 요약을 만들고 파일 해시로 캐시한다. 프로필은 행당 1,500자 이내, 관찰 위치를 반드시 포함한다.
"""

from __future__ import annotations

from pathlib import Path

from ksco_qa.profiler.base import FileProfile

# 확장자(소문자) → 프로파일러 모듈 이름 (부록 B)
FORMAT_MODULES = {
    "csv": "csv_file",
    "xlsx": "spreadsheet",
    "xls": "spreadsheet",
    "ods": "spreadsheet",
    "pdf": "pdf",
    "hwpx": "document",
    "docx": "document",
    "odt": "document",
    "pptx": "pptx_file",
    "hwp": "hwp",
    "zip": "zip_file",
}


def file_hash(path: Path) -> str:
    """캐시 열쇠가 되는 파일 내용 해시 (5.1-10)."""
    raise NotImplementedError


def profile_file(path: Path, cache_dir: Path) -> FileProfile:
    """확장자로 프로파일러를 골라 실행하고, 같은 해시는 캐시(_work/file_profiles/)를 재사용한다.
    실패하면 inspected=False(NOT_INSPECTED) + 사유로 기록하고 진행 (12장)."""
    raise NotImplementedError
