"""프로필 공통 자료형·축약 규칙 (설계 부록 B, 7.1 file_profile / M1 결정 11).

프로필은 행당 1,500자 이내. 넘으면 줄이는 순서:
  중간 샘플 → 범주값 목록(20→10개) → 끝 샘플 → 앞 샘플(1행까지).
파일 구조(열·시트·페이지 수)와 관찰 위치는 줄이지 않는다 (fixed 줄).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
from typing import Any, Protocol

PROFILE_MAX_CHARS = 1500
PROFILER_VERSION = "3"
CELL_MAX = 40
ROW_MAX = 200
CATEGORY_MAX = 20
CATEGORY_REDUCED = 10

TOTAL_LABEL_RE = re.compile(r"^\s*(합\s*계|소\s*계|총\s*계|계|total|subtotal|grand total)\s*$", re.I)
HEADING_RE = re.compile(r"^\s*(제\s*\d+\s*[장절편부]|[IVX]+\.\s|\d+\.\s+\S|\d+\.\d+(\.\d+)?\s+\S|[가-하]\.\s)")


class Fittable(Protocol):
    """형식별 프로파일러의 결과. 예산에 맞춘 (글, 관찰 위치)를 돌려준다.
    관찰 위치는 글에 실제로 담은 범위만 적는다 (문서형·PDF·PPTX)."""

    def fit_to(self, budget: int) -> tuple[str, list[str]]: ...


class ProfileError(Exception):
    """파일을 프로파일할 수 없음 → inspected=false(NOT_INSPECTED) + 사유."""


@dataclass
class FileProfile:
    locator: str  # 01_output_files/ 기준 상대 경로 (ZIP 멤버면 "<zip>!/<멤버>")
    format: str
    inspected: bool
    text: str  # 관찰 위치 포함, 예산 이내
    inspected_locations: list[str] = field(default_factory=list)
    error: str | None = None  # inspected=False일 때 사유
    warning: str | None = None  # P0 경고 코드 (예: EXTENSION_MISMATCH)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileProfile":
        return cls(**data)


@dataclass
class ProfileParts:
    """형식별 프로파일러의 결과. fit()이 예산에 맞춰 글로 만든다."""

    fixed: list[str]
    locations: list[str]
    head: list[str] = field(default_factory=list)
    head_label: str = "앞 샘플"
    mid: list[str] = field(default_factory=list)
    mid_label: str = "중간 샘플"
    tail: list[str] = field(default_factory=list)
    tail_label: str = "끝 샘플"
    categories: dict[str, list[str]] = field(default_factory=dict)

    def fit_to(self, budget: int) -> tuple[str, list[str]]:
        return fit(self, budget), list(self.locations)


def render(p: ProfileParts, category_limit: int = CATEGORY_MAX) -> str:
    lines = list(p.fixed)
    if p.locations:
        lines.append("관찰 위치: " + ", ".join(p.locations))
    if p.categories:
        items = []
        for col, values in p.categories.items():
            shown = values[:category_limit]
            more = f" 외 {len(values) - len(shown)}개" if len(values) > len(shown) else ""
            items.append(f"{col}({len(values)}): {', '.join(shown)}{more}")
        lines.append("범주값: " + " / ".join(items))
    for label, rows in ((p.head_label, p.head), (p.mid_label, p.mid), (p.tail_label, p.tail)):
        if rows:
            lines.append(f"{label}:")
            lines.extend(f"  {r}" for r in rows)
    return "\n".join(lines)


def fit(p: ProfileParts, budget: int) -> str:
    """결정 11의 순서로 줄여 budget 이내로 만든다. 고정 줄만으로도 넘으면 끝을 자르고 표시한다."""
    text = render(p)
    if len(text) <= budget:
        return text
    p.mid = []
    text = render(p)
    if len(text) <= budget:
        return text
    text = render(p, CATEGORY_REDUCED)
    if len(text) <= budget:
        return text
    p.tail = []
    text = render(p, CATEGORY_REDUCED)
    while len(text) > budget and len(p.head) > 1:
        p.head = p.head[:-1]
        text = render(p, CATEGORY_REDUCED)
    if len(text) > budget:
        text = text[: max(budget - 6, 0)] + " …(생략)"
    return text


def cell_text(value: Any, limit: int = CELL_MAX) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, (datetime, date, time)):
        value = value.isoformat()
    s = re.sub(r"\s+", " ", str(value)).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def row_text(cells: list[Any], limit: int = ROW_MAX) -> str:
    s = " | ".join(cell_text(c) for c in cells)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        if s.endswith("%"):
            s = s[:-1]
        try:
            return float(s)
        except ValueError:
            return None
    return None


def fmt_number(x: float) -> str:
    return str(int(x)) if x.is_integer() else f"{x:g}"


def decode_text(data: bytes) -> tuple[str, str]:
    """UTF-8 → CP949 순서로 시도, 둘 다 안 되면 charset-normalizer 추정 (부록 B)."""
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc), "utf-8" if enc == "utf-8-sig" else enc
        except UnicodeDecodeError:
            continue
    from charset_normalizer import from_bytes

    best = from_bytes(data).best()
    if best is not None:
        return str(best), best.encoding
    return data.decode("utf-8", errors="replace"), "utf-8(replace)"


def ranges(numbers: list[int]) -> str:
    """[2,3,4,9] → "2-4, 9"."""
    if not numbers:
        return ""
    out, start, prev = [], numbers[0], numbers[0]
    for n in numbers[1:]:
        if n == prev + 1:
            prev = n
            continue
        out.append(f"{start}-{prev}" if start != prev else f"{start}")
        start = prev = n
    out.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ", ".join(out)
