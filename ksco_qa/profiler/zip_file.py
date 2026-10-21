"""ZIP 멤버 (설계 부록 B ZIP 행): 멤버를 임시로 꺼내 형식별 규칙을 적용한다.
멤버 경로는 locator("<zip 상대 경로>!/<멤버>")로 matched_locator에 기록된다.
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from ksco_qa.profiler import profile_file
from ksco_qa.profiler.base import PROFILE_MAX_CHARS, FileProfile

ZIP_LOCATOR_SEP = "!/"


def member_display_name(info: zipfile.ZipInfo) -> str:
    """UTF-8 플래그가 없는 한국어 ZIP(CP949) 멤버 이름을 바로잡는다."""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def profile_member(
    zip_path: Path, member: str, locator: str, cache_dir: Path | None, budget: int = PROFILE_MAX_CHARS
) -> FileProfile:
    suffix = Path(member).suffix
    with zipfile.ZipFile(zip_path) as z, tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / f"member{suffix}"
        with z.open(member) as src, open(target, "wb") as dst:
            while chunk := src.read(1 << 20):
                dst.write(chunk)
        return profile_file(target, locator, cache_dir, budget)
