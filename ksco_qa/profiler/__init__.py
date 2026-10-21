"""파일 프로파일러 (설계 4.1, 5.1-10, 부록 B / M1 결정 11~14).

형식별 구조 요약을 만들고 (파일 내용 해시, 예산, 프로파일러 버전)으로 캐시한다.
실패하면 inspected=False(NOT_INSPECTED) + 사유로 기록하고 진행한다 (12장).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from ksco_qa.profiler import csv_file, document, hwp, pdf, pptx_file, spreadsheet, structured
from ksco_qa.profiler.base import PROFILE_MAX_CHARS, PROFILER_VERSION, FileProfile, ProfileError, ProfileParts, fit

# 확장자(소문자) → 프로파일러
PROFILERS: dict[str, Callable[[Path], ProfileParts]] = {
    "csv": csv_file.profile,
    "xlsx": spreadsheet.profile,
    "xlsm": spreadsheet.profile,
    "xls": spreadsheet.profile,
    "ods": spreadsheet.profile,
    "pdf": pdf.profile,
    "hwpx": document.profile,
    "docx": document.profile,
    "odt": document.profile,
    "pptx": pptx_file.profile,
    "hwp": hwp.profile,
    "json": structured.profile_json,
    "xml": structured.profile_xml,
    "html": structured.profile_html,
    "htm": structured.profile_html,
}


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sanitize(message: str, path: Path) -> str:
    """오류 메시지에서 절대 경로를 지운다 (호출·산출물에 절대 경로 금지)."""
    for p in {str(path), str(path.resolve()), path.as_posix(), str(path.parent), str(path.parent.resolve())}:
        message = message.replace(p, "<file>")
    return message


def profile_file(path: Path, locator: str, cache_dir: Path | None, budget: int = PROFILE_MAX_CHARS) -> FileProfile:
    """확장자로 프로파일러를 골라 실행한다. 같은 내용·예산이면 캐시(_work/file_profiles/)를 쓴다."""
    ext = path.suffix.lower().lstrip(".")
    fmt = ext.upper() or "(확장자 없음)"
    profiler = PROFILERS.get(ext)
    cache_path = None
    if cache_dir is not None:
        cache_path = Path(cache_dir) / f"{file_hash(path)}__{budget}__v{PROFILER_VERSION}.json"
        if cache_path.is_file():
            cached = FileProfile.from_dict(json.loads(cache_path.read_text(encoding="utf-8")))
            cached.locator = locator
            return cached
    if profiler is None:
        result = FileProfile(locator, fmt, False, "", [], f"지원하지 않는 형식: {fmt}")
    else:
        try:
            parts = profiler(path)
            result = FileProfile(locator, fmt, True, fit(parts, budget), list(parts.locations))
        except ProfileError as e:
            result = FileProfile(locator, fmt, False, "", [], str(e))
        except Exception as e:  # 손상 파일 등: NOT_INSPECTED로 기록하고 진행
            result = FileProfile(locator, fmt, False, "", [], f"{type(e).__name__}: {_sanitize(str(e), path)}")
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        data = result.to_dict() | {"locator": ""}
        cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return result


def combine_for_row(profiles: list[FileProfile]) -> str:
    """row_card.file_profile: 파일별 '[파일] <locator>' 머리 + 프로필 (실패 파일은 사유)."""
    blocks = []
    for p in profiles:
        body = p.text if p.inspected else f"NOT_INSPECTED: {p.error}"
        blocks.append(f"[파일] {p.locator}\n{body}")
    return "\n\n".join(blocks)


def row_budget(locators: list[str], total: int = PROFILE_MAX_CHARS) -> int:
    """한 행에 파일이 여럿이면 1,500자를 나눠 쓴다 (머리·구분 줄 몫을 뺌)."""
    overhead = sum(len(f"[파일] {loc}\n") for loc in locators) + 2 * (len(locators) - 1)
    return max((total - overhead) // max(len(locators), 1), 100)


__all__ = ["FileProfile", "ProfileError", "combine_for_row", "file_hash", "profile_file", "row_budget"]
