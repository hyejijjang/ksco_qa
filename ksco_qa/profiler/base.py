"""프로필 공통 자료형 (설계 부록 B, 7.1 file_profile)."""

from __future__ import annotations

from dataclasses import dataclass, field

PROFILE_MAX_CHARS = 1500


@dataclass
class FileProfile:
    locator: str  # 01_output_files/ 기준 상대 경로 (ZIP 멤버면 멤버 경로 포함)
    format: str
    inspected: bool
    text: str  # ≤ PROFILE_MAX_CHARS, 관찰 위치 포함
    inspected_locations: list[str] = field(default_factory=list)
    error: str | None = None  # inspected=False일 때 사유
