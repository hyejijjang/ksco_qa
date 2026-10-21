"""PDF 프로필 — pypdf (설계 부록 B PDF 행 / M1 결정 12).

페이지 수, outline(목차) 또는 본문에서 찾은 장·절 제목, 표 제목과 위치(페이지),
페이지별 텍스트 길이로 스캔 여부(텍스트가 거의 없는 페이지 비율). 확인한 페이지 범위를 기록한다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ksco_qa.profiler.base import HEADING_RE, ProfileError, ProfileParts, cell_text

MAX_PAGES = 300  # 이보다 긴 PDF는 앞 MAX_PAGES쪽만 텍스트 확인 (범위를 기록)
SCAN_PAGE_CHARS = 30  # 이보다 텍스트가 적은 페이지 = 텍스트가 거의 없는 페이지
SCAN_RATIO = 0.5
TABLE_TITLE_RE = re.compile(r"^\s*(<\s*표\s*[\d\-.]+\s*>|\[\s*표\s*[\d\-.]+\s*\]|표\s*\d+([\-.]\d+)*[.)]?\s+\S)")
MAX_ITEMS = 40


def _flatten_outline(reader: Any, items: list, depth: int = 0) -> list[tuple[int, str, int | None]]:
    out = []
    for item in items:
        if isinstance(item, list):
            out += _flatten_outline(reader, item, depth + 1)
            continue
        try:
            page = reader.get_destination_page_number(item) + 1
        except Exception:
            page = None
        out.append((depth, str(item.title), page))
    return out


def profile(path: Path) -> ProfileParts:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise ProfileError("암호가 걸린 PDF")
        except Exception as e:
            raise ProfileError("암호가 걸린 PDF") from e
    n = len(reader.pages)
    if n == 0:
        raise ProfileError("페이지가 없는 PDF")
    checked = min(n, MAX_PAGES)

    sparse = 0
    headings: list[str] = []
    tables: list[str] = []
    for i in range(checked):
        text = reader.pages[i].extract_text() or ""
        if len(text.strip()) < SCAN_PAGE_CHARS:
            sparse += 1
        for line in text.splitlines():
            line = line.strip()
            if not line or len(line) > 80:
                continue
            if TABLE_TITLE_RE.match(line):
                tables.append(f"p{i + 1}: {cell_text(line, 70)}")
            elif HEADING_RE.match(line) and len(line) <= 60:
                headings.append(f"p{i + 1}: {cell_text(line, 60)}")

    try:
        outline = _flatten_outline(reader, reader.outline)
    except Exception:
        outline = []
    if outline:
        head = [f"{'  ' * d}{cell_text(t, 60)}" + (f" (p{p})" if p else "") for d, t, p in outline[:MAX_ITEMS]]
        head_label = "목차(outline)"
    else:
        head = headings[:MAX_ITEMS]
        head_label = "장·절 제목(본문 추출)"

    ratio = sparse / checked
    scan = " → 스캔 PDF로 보임(텍스트 판독 불가)" if ratio >= SCAN_RATIO else ""
    fixed = [
        f"PDF · {n}쪽 · 텍스트 확인 p1-p{checked}" + ("" if checked == n else f" (p{checked + 1}-p{n} 미확인)"),
        f"텍스트가 거의 없는 쪽 {sparse}/{checked} ({ratio:.0%}){scan}",
        f"표 제목 {len(tables)}개 · 목차 {'있음' if outline else '없음'}",
    ]
    return ProfileParts(
        fixed=fixed,
        locations=[f"p1-p{checked} 텍스트"] + (["outline"] if outline else []),
        head=head,
        head_label=head_label,
        tail=tables[:MAX_ITEMS],
        tail_label="표 제목(쪽)",
    )
