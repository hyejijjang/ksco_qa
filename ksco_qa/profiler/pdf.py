"""PDF 프로필 — pdfplumber (설계 부록 B PDF, 2026-10-21 보강).

표: 쪽마다 extract_tables. "행 4 이하 & 열 2 이하", "1열", "1행(숫자 절반 이상이면 예외)"은 레이아웃 칸으로 보고 표 목록에서 뺀다
(글자는 쪽 텍스트에 그대로 남고, 뺀 개수를 한 줄로 적는다).
쪽 줄: "pN: 첫 줄(제목) · 표k R×C · 머리글: …" — 표 크기는 한 번만 적는다.
첫 줄이 머리글 줄(앞 쪽 표의 머리글과 같거나 제목 없이 바로 표 시작)이면 "(pM 표 이어짐)"으로 적는다.
상세 쪽: 셀 수(행×열)가 큰 표가 있는 쪽부터 고르고, 표가 이어진 쪽은 뒤로 보낸다 (표가 없으면 앞·중간·끝).
  상세 쪽마다 표 크기·머리글(전체), 첫 5줄(각 80자), 금액처럼 보이는 값의 최소·최대, 합계·계·소계 줄 유무,
  단위·기준일 표기, 그 쪽 표의 행 라벨(최대 15개, 연번·날짜 열은 건너뜀)·데이터 앞 2행.
스캔 여부 = 텍스트가 거의 없는 쪽 비율. 관찰 위치는 프로필에 실제로 담은 범위만 적는다.

1,500자를 넘으면: 상세 쪽 밖 표 머리글 앞 3칸 → 데이터 행 2→1 → 첫 줄 5→3→1 → 행 라벨 15→8
→ 행 라벨 1단계 전부+하위 3개 → 상세 쪽 수(맨 마지막, 우선순위 낮은 쪽부터). 쪽 수, 표 개수·크기·쪽 위치, 상세 쪽 표 머리글, 관찰 위치는 줄이지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ksco_qa.profiler.base import ProfileError, cell_text, ranges
from ksco_qa.profiler.doc_model import (
    FIRST_COL_MAX,
    FIRST_COL_REDUCED,
    HEADER_SHORT_CELLS,
    LABELS_TOP_PLUS,
    label_cap_desc,
    row_labels,
    DocTable,
    data_rows_lines,
    is_pdf_layout_cell,
    labels_line,
    table_header,
    table_layout,
)

MAX_PAGES = 300  # 이보다 긴 PDF는 앞 MAX_PAGES쪽만 확인 (범위를 기록)
SCAN_PAGE_CHARS = 30  # 이보다 텍스트가 적은 쪽 = 텍스트가 거의 없는 쪽
SCAN_RATIO = 0.5
DETAIL_ALL_MAX = 8  # 표가 없는 PDF: 이 쪽 수 이하면 전 쪽 상세, 넘으면 앞·중간·끝
LINE_CHARS = 80
AMOUNT_RE = re.compile(r"(?<![\d.,])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d,])")
TOTAL_LINE_RE = re.compile(r"합\s*계|총\s*계|소\s*계|(^|\s)계(\s|$)")
UNIT_RE = re.compile(r"[(\[<]?\s*단\s*위\s*[:：]\s*[^)\]>\n]{1,15}[)\]>]?")
BASE_DATE_RE = re.compile(r"[‘'’]?\d{2,4}\s*[.\-년]\s*\d{1,2}\s*[.\-월]?\s*(\d{1,2}\s*[.일]?)?\s*(현재|기준)")



@dataclass
class PdfPage:
    no: int
    lines: list[str]
    amount_range: tuple[float, float] | None
    has_total_line: bool
    notes: list[str]  # 단위·기준일 표기
    sparse: bool
    table_ids: list[int] = field(default_factory=list)


@dataclass
class PdfTable:
    page: int
    table: DocTable

    @property
    def cells(self) -> int:
        return self.table.n_rows * self.table.n_cols


@dataclass
class PdfModel:
    n_pages: int
    pages: list[PdfPage]
    tables: list[PdfTable]  # 레이아웃 칸을 뺀 표
    layout_excluded: int = 0

    @property
    def checked(self) -> int:
        return len(self.pages)

    def page(self, no: int) -> PdfPage:
        return self.pages[no - 1]

    def continues_from(self, no: int) -> int | None:
        """앞 쪽 표가 이어진 쪽이면 그 앞 쪽 번호.
        첫 줄이 머리글 줄 = 앞 쪽 표의 머리글과 같거나, 이 쪽 첫 표의 머리글과 같음(제목 없이 바로 표 시작)."""
        page = self.page(no)
        if not page.lines or not page.table_ids:
            return None
        prev = next((p.no for p in reversed(self.pages[: no - 1]) if p.table_ids), None)
        if prev is None:
            return None
        first = _key(page.lines[0])
        candidates = [self.tables[j].table for j in self.page(prev).table_ids] + [self.tables[page.table_ids[0]].table]
        return prev if any(first and first == _key(table_header(t)) for t in candidates) else None

    def continuation_parent(self, table_id: int) -> int | None:
        current = self.tables[table_id]
        page = self.page(current.page)
        if not page.table_ids or page.table_ids[0] != table_id:
            return None
        previous_page = self.continues_from(current.page)
        if previous_page is None:
            return None
        header = _key(table_header(current.table))
        candidates = [
            candidate
            for candidate in self.page(previous_page).table_ids
            if _key(table_header(self.tables[candidate].table)) == header
        ]
        return candidates[-1] if candidates else None

    def continuation_group(self, table_id: int) -> list[int]:
        while (parent := self.continuation_parent(table_id)) is not None:
            table_id = parent
        group = [table_id]
        while True:
            child = next(
                (index for index in range(group[-1] + 1, len(self.tables))
                 if self.continuation_parent(index) == group[-1]),
                None,
            )
            if child is None:
                return group
            group.append(child)

    def merged_table(self, table_id: int) -> DocTable:
        """Combine a repeated-header table fragment with its page continuations."""
        group = self.continuation_group(table_id)
        first = self.tables[group[0]].table
        rows = [list(row) for row in first.rows]
        full_span = set(first.full_span_rows)
        for index in group[1:]:
            table = self.tables[index].table
            incoming = table.rows
            if incoming and first.rows and _key(table_header(table)) == _key(table_header(first)):
                incoming = incoming[1:]
            offset = len(rows)
            rows.extend(list(row) for row in incoming)
            full_span.update(offset + row for row in table.full_span_rows)
        return DocTable(rows, first.after_paragraph, any(self.tables[index].table.merged for index in group), full_span)

    def expand_detail(self, pages: set[int]) -> set[int]:
        """Keep all physical pages of a continued table together in detailed observations."""
        expanded = set(pages)
        for index, table in enumerate(self.tables):
            group = self.continuation_group(index)
            group_pages = {self.tables[member].page for member in group}
            if expanded & group_pages:
                expanded.update(group_pages)
        return expanded

    def detail_priority(self) -> list[int]:
        """상세 쪽 우선순위: 셀 수가 큰 표가 있는 쪽부터 (같은 쪽은 한 번), 앞 쪽 표가 이어진 쪽은 뒤로.
        표가 없으면 앞·중간·끝."""
        if self.tables:
            roots = [j for j in range(len(self.tables)) if self.continuation_parent(j) is None]
            roots.sort(key=lambda j: (
                -max(self.tables[member].cells for member in self.continuation_group(j)),
                j,
            ))
            pages = [
                self.tables[member].page
                for root in roots
                for member in self.continuation_group(root)
            ]
            return [p for p in pages if self.continues_from(p) is None] + \
                   [p for p in pages if self.continues_from(p) is not None]
        n = self.checked
        if n <= DETAIL_ALL_MAX:
            return list(range(1, n + 1))
        mid = (n + 1) // 2
        return list(dict.fromkeys([1, mid, n, 2, mid + 1, n - 1]))

    def fit_to(self, budget: int) -> tuple[str, list[str]]:
        """비상세 쪽 머리글 3칸 → 데이터 행 2→1 → 첫 줄 5→3→1 → 행 라벨 15→8 → 행 라벨 1단계 전부+하위 3개
        → 상세 쪽 수(맨 마지막)."""
        priority = self.detail_priority()
        n = len(priority)
        steps = [
            (n, False, 2, 5, FIRST_COL_MAX), (n, True, 2, 5, FIRST_COL_MAX), (n, True, 1, 5, FIRST_COL_MAX),
            (n, True, 1, 3, FIRST_COL_MAX), (n, True, 1, 1, FIRST_COL_MAX), (n, True, 1, 1, FIRST_COL_REDUCED),
            (n, True, 1, 1, LABELS_TOP_PLUS),
        ]
        steps += [(k, True, 1, 1, LABELS_TOP_PLUS) for k in range(n - 1, 0, -1)]
        text, locations = "", []
        for k, short, rows, first_lines, labels in steps:
            text, locations = render(self, self.expand_detail(set(priority[:k])), short, rows, first_lines, labels)
            if len(text) <= budget:
                return text, locations
        return text[: max(budget - 6, 0)] + " …(생략)", locations


def _key(text: str) -> str:
    return re.sub(r"[\s|]", "", text)


def _amount(s: str) -> float:
    return float(s.replace(",", ""))


def _money(x: float) -> str:
    return f"{x:,.0f}" if x.is_integer() else f"{x:,}"


def _table_brief(m: PdfModel, j: int, short: bool, with_title: bool = False) -> str:
    t = m.tables[j].table
    merged = " · 병합 셀 있음" if t.merged else ""
    layout = table_layout(t)
    title = f" · 제목 행: {layout.title_text(t)}" if with_title and layout.title_rows else ""
    group = m.continuation_group(j)
    continuation = ""
    if len(group) > 1 and group[0] == j:
        page_range = ranges([m.tables[index].page for index in group])
        continuation = f" (p{page_range} 연결)"
    return f"표{j + 1} {t.n_rows}×{t.n_cols}{merged}{title}{continuation} · 머리글: {table_header(t, short)}"


def render(m: PdfModel, detail: set[int], short_headers: bool, data_rows: int, first_lines: int,
           label_max: int | str = FIRST_COL_MAX) -> tuple[str, list[str]]:
    detail = m.expand_detail(detail)
    sparse = sum(p.sparse for p in m.pages)
    scan = " → 스캔 PDF로 보임(텍스트 판독 불가)" if m.checked and sparse / m.checked >= SCAN_RATIO else ""
    unchecked = f" (p{m.checked + 1}-p{m.n_pages} 미확인)" if m.checked < m.n_pages else ""
    others = [p.no for p in m.pages if p.no not in detail]
    shortened = short_headers and any(
        t.page not in detail and t.table.rows and len(t.table.rows[table_layout(t.table).header]) > HEADER_SHORT_CELLS
        for t in m.tables
    )
    locations = []
    if detail:
        has_tables = any(t.page in detail for t in m.tables)
        cap = label_max
        if cap == LABELS_TOP_PLUS and not any(row_labels(t.table).leveled for t in m.tables if t.page in detail):
            cap = FIRST_COL_REDUCED  # 번호 체계 있는 표가 없으면 실제 상한은 그대로 8개
        locations.append(f"p{ranges(sorted(detail))} 상세(첫 {first_lines}줄·금액 범위·합계 줄·단위/기준일"
                         + (f", 표 크기·머리글·{label_cap_desc(cap)}·앞 {data_rows}행" if has_tables else "") + ")")
    if others:
        locations.append(f"p{ranges(others)} 첫 줄" + (", 표 크기·머리글" if any(t.page not in detail for t in m.tables) else "")
                         + (" (머리글 앞 3칸)" if shortened else ""))
    lines = [
        f"PDF · {m.n_pages}쪽 · 텍스트 확인 p1-p{m.checked}{unchecked} · 표 {len(m.tables)}개",
        f"텍스트가 거의 없는 쪽 {sparse}/{m.checked}{scan}",
        "관찰 위치: " + (", ".join(locations) or "없음"),
    ]
    if m.layout_excluded:
        lines.append(f"레이아웃 칸 {m.layout_excluded}개 제외")
    for p in m.pages:
        prev = m.continues_from(p.no)
        first = f"(p{prev} 표 이어짐)" if prev else (cell_text(p.lines[0], LINE_CHARS) if p.lines else "(텍스트 없음)")
        if p.no not in detail:
            briefs = [_table_brief(m, j, short_headers) for j in p.table_ids]
            lines.append(f"p{p.no}: " + " · ".join([first] + briefs))
            continue
        lines.append(f"p{p.no} 상세: {first}")
        if p.table_ids and all(m.continuation_parent(j) is not None for j in p.table_ids):
            for j in p.table_ids:
                parent = m.continuation_parent(j)
                assert parent is not None
                table = m.tables[j].table
                lines.append(
                    f"  표{j + 1} {table.n_rows}×{table.n_cols} · 머리글은 표{parent + 1}과 같음"
                )
            continue
        lines.extend(f"  {_table_brief(m, j, False, with_title=True)}" for j in p.table_ids)
        lines.extend(f"  {cell_text(l, LINE_CHARS)}" for l in p.lines[1:first_lines])
        facts = []
        if p.amount_range:
            lo, hi = p.amount_range
            facts.append(f"금액 범위 {_money(lo)}~{_money(hi)}")
        facts.append("합계·계·소계 줄 있음" if p.has_total_line else "합계·계·소계 줄 없음")
        if p.notes:
            facts.append("단위·기준일: " + ", ".join(p.notes))
        lines.append("  " + " · ".join(facts))
        for j in p.table_ids:
            if m.continuation_parent(j) is not None:
                continue
            t = m.merged_table(j)
            group = m.continuation_group(j)
            group_label = f"{group[0] + 1}-{group[-1] + 1} 연결" if len(group) > 1 else str(j + 1)
            label = labels_line(t, label_max, indent=f"  표{group_label} ")
            if label:
                lines.append(label)
            lines.extend(data_rows_lines(t, data_rows, prefix=f"  표{group_label} "))
    return "\n".join(lines), locations


def _page(no: int, text: str, tables: list[list[list[str | None]]]) -> tuple[PdfPage, list[DocTable]]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    amounts = [_amount(a) for a in AMOUNT_RE.findall(text)]
    notes = list(dict.fromkeys(
        [cell_text(m.group(0), 30) for m in UNIT_RE.finditer(text)]
        + [cell_text(m.group(0), 30) for m in BASE_DATE_RE.finditer(text)]
    ))[:3]
    doc_tables = []
    for raw in tables:
        rows, full_span = [], set()
        for r in raw:
            if not any(c not in (None, "") for c in r):
                continue
            if len(r) > 1 and r[0] not in (None, "") and all(c is None for c in r[1:]):
                full_span.add(len(rows))  # 한 칸이 행 전체에 병합
            rows.append([c if c is not None else "" for c in r])
        if rows:
            merged = any(c is None for r in raw for c in r)
            doc_tables.append(DocTable(rows, 0, merged, full_span))
    page = PdfPage(
        no=no,
        lines=lines,
        amount_range=(min(amounts), max(amounts)) if amounts else None,
        has_total_line=any(TOTAL_LINE_RE.search(l) for l in lines),
        notes=notes,
        sparse=len(text.strip()) < SCAN_PAGE_CHARS,
    )
    return page, doc_tables


def profile(path: Path) -> PdfModel:
    import pdfplumber

    try:
        pdf = pdfplumber.open(str(path))
    except Exception as e:
        if "password" in type(e).__name__.lower() or "encrypt" in str(e).lower():
            raise ProfileError("암호가 걸린 PDF") from e
        raise
    with pdf:
        n = len(pdf.pages)
        if n == 0:
            raise ProfileError("페이지가 없는 PDF")
        pages, tables, excluded = [], [], 0
        for i, page in enumerate(pdf.pages[:MAX_PAGES], start=1):
            p, found = _page(i, page.extract_text() or "", page.extract_tables())
            for t in found:
                if is_pdf_layout_cell(t):
                    excluded += 1  # 글자는 page.extract_text()로 이미 쪽 텍스트에 있다
                    continue
                p.table_ids.append(len(tables))
                tables.append(PdfTable(i, t))
            pages.append(p)
    return PdfModel(n, pages, tables, excluded)
