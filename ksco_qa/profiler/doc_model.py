"""문서형(HWPX·DOCX·ODT) 프로필의 공통 모델·렌더링·축약 + 표 공통 규칙 (설계 부록 B, 2026-10-21).

표 공통 (PDF·HWPX·DOCX·ODT·XLSX):
- 머리글 행: 위에서부터 제목 행("단위" 포함, 칸 절반 이상 빈칸, 한 칸이 행 전체 병합)을 최대 3행 건너뛴다.
  건너뛴 제목 행 내용은 표 줄에 남긴다. 머리글 바로 아래 같은 글자만 반복되는 행("금 액 | 금 액")은 머리글 이어짐.
- 행 라벨: 연번 열(머리글 연번·순번·번호·No·NO 또는 값의 80% 이상이 1부터 증가하는 정수)·날짜 열은 열 단위로 건너뛴다.
  행마다 남은 칸 중 처음 나오는 이름 칸을 쓴다 — 빈칸·번호만 있는 칸(Ⅰ. (1) 1. 가. ①)·금액 칸은 건너뛰고,
  "Ⅰ. 유동자산"처럼 번호가 붙어 있으면 번호를 뗀다. 소계·합계 줄은 빼고 "합계 행 있음"으로 표시.

문서형:
- 레이아웃 칸("1열" 또는 "1행" — 단 1행 표는 칸 절반 이상이 숫자면 데이터 표, 2열 이상 여러 행 표는 데이터 표)은
  표에서 빼고 글자를 문단 흐름에 남긴다. "레이아웃 칸 N개 제외".
- 상세 표 = 셀 수(행×열)가 큰 표부터. 상세 표는 위치·크기·제목 행·머리글·행 라벨·데이터 앞 2행,
  나머지 표는 "표k R×C · 머리글: 앞 3칸" 한 줄. 상세 표 앞뒤 문단은 꼭 담는다.
- 1,500자 초과 시: 비상세 표 머리글 앞 3칸 → 데이터 행 2→1 → 문단 80→40자 → 행 라벨 15→8
  → 상세 표와 붙지 않은 문단을 뒤에서부터 → 비상세 표 머리글 생략(크기만) → 비상세 표 앞 문단 제목(30자) 생략
  → 상세 표 수 → 본문 끝 줄부터(관찰 위치에 "이후 생략").
관찰 위치는 프로필에 실제로 담은 범위만 적는다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ksco_qa.profiler.base import cell_text, ranges

FIRST_COL_MAX = 15
FIRST_COL_REDUCED = 8
HEADER_SHORT_CELLS = 3
MAX_TITLE_ROWS = 3
SERIAL_HEADERS = {"연번", "순번", "번호", "No", "NO"}
SERIAL_DATE_RATIO = 0.8
LABEL_MAX_COLUMN = 3
DATE_VALUE_RE = re.compile(
    r"^\s*(\d{4}|\d{2})\s*[-./년]\s*\d{1,2}\s*[-./월]?\s*(\d{1,2}\s*[.일]?)?\s*(\d{1,2}:\d{2}(:\d{2})?)?\s*$"
)
_NUMBERING = r"(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+\s*\.?|[IVX]+\s*\.|\(\s*\d+\s*\)|\d+\s*[.)]|[가-하]\s*[.)]|\(\s*[가-하]\s*\)|[①-⑳])"
NUMBERING_PREFIX_RE = re.compile(rf"^\s*{_NUMBERING}\s*")
BARE_NUMBERING_RE = re.compile(rf"^\s*{_NUMBERING}\s*$")
NUMERIC_CELL_RE = re.compile(r"^\s*\(?\s*[-−△▲]?\s*[\d,]+(\.\d+)?\s*\)?\s*%?\s*$|^\s*[-−]\s*$")
TOTAL_ROW_RE = re.compile(r"(합\s*계|소\s*계|총\s*계)$|^계$|^total$|^subtotal$", re.I)


@dataclass
class DocTable:
    rows: list[list[str]]
    after_paragraph: int  # 이 표 바로 앞의 (비어 있지 않은) 문단 번호, 0 = 문서 시작
    merged: bool = False
    full_span_rows: set[int] = field(default_factory=set)  # 한 칸이 행 전체에 병합된 행 (0부터)

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    @property
    def cells(self) -> int:
        return self.n_rows * self.n_cols


def header_text(value: object) -> str:
    """머리글은 글자 사이 공백을 원문 그대로 둔다 (줄바꿈·탭만 공백으로)."""
    return re.sub(r"[\r\n\t]+", " ", "" if value is None else str(value)).strip()


def is_numeric_cell(value: object) -> bool:
    return bool(NUMERIC_CELL_RE.match(cell_text(value))) if cell_text(value) else False


def is_layout_cell(t: DocTable) -> bool:
    """레이아웃 칸 (PDF·문서형 공통): 행 4 이하 & 열 2 이하, 또는 1열짜리."""
    return (t.n_rows <= 4 and t.n_cols <= 2) or t.n_cols == 1


def is_one_row_layout(t: DocTable) -> bool:
    """1행짜리 표. 단 칸의 절반 이상이 숫자면 데이터 표."""
    if t.n_rows != 1:
        return False
    cells = t.rows[0]
    return sum(is_numeric_cell(c) for c in cells) * 2 < len(cells)


def is_doc_layout_cell(t: DocTable) -> bool:
    """문서형(HWPX·DOCX·ODT): 1열 표 또는 1행 표(숫자 절반 이상이면 예외)만. 2열 이상 여러 행 표는 데이터 표."""
    return t.n_cols == 1 or is_one_row_layout(t)


def is_pdf_layout_cell(t: DocTable) -> bool:
    """PDF: 행 4 이하 & 열 2 이하, 1열, 또는 1행 표(숫자 절반 이상이면 예외)."""
    return is_layout_cell(t) or is_one_row_layout(t)


_REPEAT_RE = re.compile(r"(\S.*?\S)(?:\s+\1)+(?=\s|$)")


def collapse_repeats(text: str) -> str:
    """연속으로 같은 문구가 반복되면 한 번만 남긴다 ("3. 재 무 제 표 3. 재 무 제 표" → "3. 재 무 제 표")."""
    previous = None
    while previous != text:
        previous, text = text, _REPEAT_RE.sub(r"\1", text)
    return text


# --- 머리글 행·제목 행 ---


def is_title_row(t: DocTable, i: int) -> bool:
    row = t.rows[i]
    texts = [cell_text(c) for c in row]
    if any("단위" in x for x in texts):
        return True
    if i in t.full_span_rows or (len(row) == 1 and t.n_cols > 1):
        return True
    return sum(not x for x in texts) * 2 >= len(row)


@dataclass
class TableLayout:
    title_rows: list[int]
    header: int
    data_start: int

    def title_text(self, t: DocTable) -> str:
        return " ".join(cell_text(c, 60) for i in self.title_rows for c in t.rows[i] if cell_text(c))


def table_layout(t: DocTable) -> TableLayout:
    titles, i = [], 0
    while i < min(MAX_TITLE_ROWS, t.n_rows - 1) and is_title_row(t, i):
        titles.append(i)
        i += 1
    header = i
    j = header + 1
    while j < t.n_rows:  # 머리글 이어짐: 같은 글자만 반복 ("금 액 | 금 액")
        values = [re.sub(r"\s+", "", cell_text(c)) for c in t.rows[j] if cell_text(c)]
        if len(values) >= 2 and len(set(values)) == 1 and not is_numeric_cell(values[0]):
            j += 1
            continue
        break
    return TableLayout(titles, header, j)


def table_header(t: DocTable, short: bool = False) -> str:
    if not t.rows:
        return ""
    cells = [header_text(c) for c in t.rows[table_layout(t).header]]
    if short and len(cells) > HEADER_SHORT_CELLS:
        return " | ".join(cells[:HEADER_SHORT_CELLS]) + f" …+{len(cells) - HEADER_SHORT_CELLS}칸"
    return " | ".join(cells)


def header_key(t: DocTable) -> str:
    """같은 머리글 비교용: 공백을 모두 지운다 ("구  분"과 "구   분"은 같은 머리글)."""
    return re.sub(r"\s+", "", table_header(t))


# --- 행 라벨 ---


def is_serial_column(header: str, values: list[str]) -> bool:
    """연번 판정: 머리글이 연번·순번·번호·No·NO 중 하나이거나, 값의 80% 이상이 1부터 증가하는 정수."""
    if re.sub(r"[\s.]", "", header) in SERIAL_HEADERS:
        return True
    if not values:
        return False
    hits = sum(1 for i, v in enumerate(values, start=1) if v.isdigit() and int(v) == i)
    return hits / len(values) >= SERIAL_DATE_RATIO


def is_date_column(values: list[str]) -> bool:
    return bool(values) and sum(bool(DATE_VALUE_RE.match(v)) for v in values) / len(values) >= SERIAL_DATE_RATIO


def is_numbering_column(values: list[str]) -> bool:
    return bool(values) and sum(bool(BARE_NUMBERING_RE.match(v)) for v in values) / len(values) >= SERIAL_DATE_RATIO


def column_values(t: DocTable, j: int, start: int = 1) -> list[str]:
    """start행부터 j열의 비어 있지 않은 값 (순서대로)."""
    return [cell_text(r[j]) for r in t.rows[start:] if j < len(r) and cell_text(r[j])]


def _label_cell(value: str) -> str | None:
    """이름 칸이면 번호를 뗀 이름, 아니면 None (빈칸·번호만·금액·날짜·정수)."""
    if not value or BARE_NUMBERING_RE.match(value) or is_numeric_cell(value) or DATE_VALUE_RE.match(value):
        return None
    name = NUMBERING_PREFIX_RE.sub("", value).strip()
    return name or None


@dataclass
class RowLabels:
    columns: list[int]  # 라벨을 얻은 열 (0부터, 많이 쓴 순)
    header: str
    values: list[str]  # 중복 제거, 합계 줄 제외. 번호 체계가 있으면 상위 단계부터
    skipped: list[str]  # 예: ["1열 연번", "2열 날짜", "1열 번호"]
    has_total: bool = False
    top_level_count: int | None = None  # 번호 체계가 있는 표: 최상위 단계 라벨 수 (없으면 None)
    top_level: int | None = None  # 최상위 단계 (보통 1)

    @property
    def leveled(self) -> bool:
        return self.top_level_count is not None

    def columns_desc(self) -> str:
        cols = ranges(sorted(c + 1 for c in set(self.columns)))
        text = f"{cols}열({self.header})"
        return text + (f", {'·'.join(self.skipped)}" if self.skipped else "")

    def describe(self) -> str:
        if not self.skipped and self.columns[:1] == [0] and len(set(self.columns)) == 1:
            return "첫 열"
        return f"행 라벨: {self.columns_desc()}"


def numbering_level(text: str) -> int | None:
    """번호 단계: Ⅰ.·Ⅱ. = 1, 1.·2. = 2, (1)·(2) = 3, 가.·(가)·① = 4."""
    s = text.strip()
    if re.match(r"^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+|[IVX]+\s*\.)", s):
        return 1
    if re.match(r"^\(\s*\d+\s*\)", s):
        return 3
    if re.match(r"^\d+\s*[.)]", s):
        return 2
    if re.match(r"^([가-하]\s*[.)]|\(\s*[가-하]\s*\)|[①-⑳])", s):
        return 4
    return None


def row_labels(t: DocTable) -> RowLabels:
    layout = table_layout(t)
    header_row = t.rows[layout.header] if t.rows else []
    skip_cols: set[int] = set()
    skipped: list[str] = []
    for j in range(min(LABEL_MAX_COLUMN, t.n_cols)):
        header = header_text(header_row[j]) if j < len(header_row) else ""
        values = column_values(t, j, layout.data_start)
        if is_serial_column(header, values):
            kind = "연번"
        elif j > 0 and is_date_column(values):
            kind = "날짜"
        elif is_numbering_column(values):
            kind = "번호"
        else:
            break  # 첫 열이 연번·날짜·번호가 아니면 그 열부터 라벨 (뒤쪽 열은 판정하지 않음)
        if kind != "번호":
            # 번호 열은 칸 단위로 거른다: 번호만 있는 칸은 _label_cell이 건너뛰고, 같은 열의 이름 칸
            # (재무표에서 상위 과목 "매출액"이 하위 번호 "1."들과 같은 열에 있는 경우)은 살린다
            skip_cols.add(j)
        skipped.append(f"{j + 1}열 {kind}")

    found: list[tuple[str, int | None, int]] = []  # (이름, 번호 단계, 열)
    has_total = False
    for row in t.rows[layout.data_start:]:
        level = None
        for j, cell in enumerate(row):
            text = cell_text(cell)
            if level is None and text and BARE_NUMBERING_RE.match(text):
                level = numbering_level(text)  # 번호만 있는 칸 (예: "Ⅰ." | "유동자산")
            if j in skip_cols:
                continue
            name = _label_cell(text)
            if name is None:
                continue
            if level is None and NUMBERING_PREFIX_RE.match(text):
                level = numbering_level(text)  # 번호가 붙은 이름 (예: "Ⅰ. 유동자산")
            if TOTAL_ROW_RE.search(re.sub(r"\s+", "", name)):
                has_total = True
            else:
                found.append((name, level, j))
            break

    top_count, top_level = None, None
    present = {level for _, level, _ in found if level is not None}
    if len(present) >= 2:  # 번호 단계가 둘 이상일 때만 계층으로 본다 (①②만 있는 목록은 원래 순서)
        # 번호가 없는 행은 같은 열에 놓인 번호 있는 행의 단계로 추정, 추정이 안 되면 맨 아래 단계
        by_col: dict[int, Counter] = {}
        for _, level, j in found:
            if level is not None:
                by_col.setdefault(j, Counter())[level] += 1
        deepest = max(level for _, level, _ in found if level is not None)
        resolved = [(name, level if level is not None else
                     (by_col[j].most_common(1)[0][0] if j in by_col else deepest), j) for name, level, j in found]
        ordered = sorted(enumerate(resolved), key=lambda x: (x[1][1], x[0]))  # 단계 → 원래 순서
        values = list(dict.fromkeys(name for _, (name, _, _) in ordered))
        top_level = min(present)
        top_count = len(dict.fromkeys(name for name, level, _ in resolved if level == top_level))
    else:
        values = list(dict.fromkeys(name for name, _, _ in found))
    used = [j for _, _, j in found]
    counts = Counter(used)
    columns = [c for c, _ in counts.most_common()] or [0]
    main = columns[0]
    # 머리글 행이 병합으로 칸 수가 모자라면 열 번호가 맞지 않으므로 첫 머리글 칸(보통 "과 목"·"구 분")을 쓴다
    aligned = len(header_row) == t.n_cols
    header = header_text(header_row[main]) if aligned and main < len(header_row) else ""
    if not header:  # 병합으로 비었으면 첫 머리글 칸
        header = header_text(header_row[0]) if header_row else ""
    return RowLabels(columns, header, values, skipped, has_total, top_count, top_level)


def labels_line(t: DocTable, limit: int, indent: str = "  ") -> str | None:
    labels = row_labels(t)
    if not labels.values and not labels.has_total:
        return None
    # 번호 체계가 있으면 1단계는 개수 제한과 상관없이 전부, 남는 자리를 하위 단계로 채운다
    shown = labels.values[:max(limit, labels.top_level_count or 0)]
    more = f" 외 {len(labels.values) - len(shown)}개" if len(labels.values) > len(shown) else ""
    total = " · 합계 행 있음" if labels.has_total else ""
    if labels.leveled:
        return (f"{indent}행 라벨(상위 우선): {labels.columns_desc()} · {labels.top_level}단계 {labels.top_level_count}개 / "
                f"전체 {len(labels.values)}개: {', '.join(shown)}{more}{total}")
    return f"{indent}{labels.describe()}({len(labels.values)}): {', '.join(shown)}{more}{total}"


def data_rows_lines(t: DocTable, count: int, prefix: str = "  ") -> list[str]:
    start = table_layout(t).data_start
    return [f"{prefix}{i + 1}행: " + " | ".join(cell_text(c) for c in row)
            for i, row in enumerate(t.rows[start:start + count], start=start)]


# --- 문서 모델 ---


@dataclass
class DocModel:
    kind: str
    title: str | None
    paragraphs: list[str]  # 1번부터
    tables: list[DocTable] = field(default_factory=list)
    layout_excluded: int = 0

    def detail_priority(self) -> list[int]:
        return sorted(range(len(self.tables)), key=lambda j: (-self.tables[j].cells, j))

    def fit_to(self, budget: int) -> tuple[str, list[str]]:
        return fit_document(self, budget)


def build_doc_model(kind: str, blocks: list[tuple[str, object]], styled_title: str | None = None) -> DocModel:
    """블록(("p", 글) / ("t", DocTable))을 문서 순서대로 받아 레이아웃 칸을 문단 흐름으로 옮긴다."""
    paragraphs: list[str] = []
    tables: list[DocTable] = []
    excluded = 0
    for kind_, value in blocks:
        if kind_ == "p":
            text = str(value).strip()
            if text:
                paragraphs.append(text)
            continue
        t = value
        assert isinstance(t, DocTable)
        if not t.rows:
            continue
        if is_doc_layout_cell(t):
            excluded += 1
            text = " ".join(cell_text(c, 200) for r in t.rows for c in r if cell_text(c))
            if text:
                paragraphs.append(text)
            continue
        t.after_paragraph = len(paragraphs)
        tables.append(t)
    title = styled_title or (paragraphs[0] if paragraphs else None)
    return DocModel(kind, collapse_repeats(title) if title else None, paragraphs, tables, excluded)


def render_detail_table(t: DocTable, no: int, data_rows: int, label_max: int, before: str | None,
                        duplicate: bool) -> list[str]:
    head = f"표{no} (문단 {t.after_paragraph} 다음) {t.n_rows}행 × {t.n_cols}열" if t.after_paragraph else \
        f"표{no} (문서 시작) {t.n_rows}행 × {t.n_cols}열"
    if t.merged:
        head += " · 병합 셀 있음"
    if duplicate and before:
        head += f" · 앞 문단: {cell_text(before, 40)}"
    layout = table_layout(t)
    if layout.title_rows:
        head += f" · 제목 행: {layout.title_text(t)}"
    lines = [head, f"  머리글: {table_header(t)}"]
    labels = labels_line(t, label_max)
    if labels:
        lines.append(labels)
    lines.extend(data_rows_lines(t, data_rows))
    return lines


BRIEF_TITLE_CHARS = 30
TITLE_LOOKBACK = 3
TABLE_TITLE_RE = re.compile(
    r"^\s*(\(\s*\d+\s*\)|\d+\s*\.|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+\s*\.|[가-하]\s*\.)|(표|계산서|명세서)\s*$"
)
PERIOD_LINE_RE = re.compile(r"부터.*까지|현재\s*\)?\s*$|기준\s*\)?\s*$")


def table_title(model: "DocModel", t: DocTable) -> str | None:
    """비상세 표 제목: 위로 최대 3문단 안에서 제목 패턴((1)·1.·Ⅰ.·가., "~표"·"~계산서"·"~명세서")에 맞는
    가장 가까운 문단. 기간·기준일 줄("~부터 ~까지", "~현재")은 건너뛴다."""
    for i in range(t.after_paragraph, max(t.after_paragraph - TITLE_LOOKBACK, 0), -1):
        text = model.paragraphs[i - 1].strip()
        if PERIOD_LINE_RE.search(text):
            continue
        if TABLE_TITLE_RE.search(text):
            return text
    return None


def _brief_mode(brief: object) -> str:
    """비상세 표 머리글: "full"(전체) · "short"(앞 3칸) · "none"(생략). bool은 False=full, True=short."""
    if isinstance(brief, bool):
        return "short" if brief else "full"
    return str(brief)


def render_brief_table(t: DocTable, no: int, brief: object, title: str | None = None) -> str:
    """비상세 표 한 줄: "표k R×C · <표 제목 30자> · 머리글: …"."""
    mode = _brief_mode(brief)
    parts = [f"표{no} {t.n_rows}×{t.n_cols}"]
    if title:
        parts.append(cell_text(title, BRIEF_TITLE_CHARS))
    if mode != "none":
        parts.append(f"머리글: {table_header(t, mode == 'short')}")
    return " · ".join(parts)


def _protected(model: DocModel, detail: set[int]) -> set[int]:
    """첫 문단과 상세 표 바로 앞뒤 문단 (표 제목·단위·기준일 역할) — 빼지 않는다."""
    keep = {1} if model.paragraphs else set()
    for j in detail:
        a = model.tables[j].after_paragraph
        if a:
            keep.add(a)
        if a + 1 <= len(model.paragraphs):
            keep.add(a + 1)
    return keep


def render(model: DocModel, detail: set[int], brief: object, data_rows: int, para_chars: int, label_max: int,
           included: set[int], brief_title: bool = True) -> tuple[str, list[str]]:
    mode = _brief_mode(brief)
    n_p, n_t = len(model.paragraphs), len(model.tables)
    others = [j for j in range(n_t) if j not in detail]
    locations = []
    if included:
        locations.append(f"문단 {ranges(sorted(included))} (각 {para_chars}자)")
    if detail:
        locations.append(f"표{ranges(sorted(j + 1 for j in detail))} 머리글·행 라벨·앞 {data_rows}행")
    if others:
        locations.append(f"표{ranges([j + 1 for j in others])} {_brief_desc(model, others, mode, brief_title)}")
    lines = [
        f"{model.kind} · 제목: {cell_text(model.title, 80) if model.title else '(없음)'} · 문단 {n_p} · 표 {n_t}",
        "관찰 위치: " + (", ".join(locations) or "없음"),
    ]
    if model.layout_excluded:
        lines.append(f"레이아웃 칸 {model.layout_excluded}개 제외")
    if included != set(range(1, n_p + 1)) and n_p:
        omitted = sorted(set(range(1, n_p + 1)) - included)
        lines.append(f"(문단 {ranges(omitted)} 미포함)")

    keys = [header_key(t) for t in model.tables]
    by_after: dict[int, list[int]] = {}
    for j, t in enumerate(model.tables):
        by_after.setdefault(t.after_paragraph, []).append(j)

    def emit_tables(after: int) -> None:
        for j in by_after.get(after, []):
            t = model.tables[j]
            before = model.paragraphs[t.after_paragraph - 1] if t.after_paragraph else None
            if j not in detail:
                lines.append(render_brief_table(t, j + 1, mode, table_title(model, t) if brief_title else None))
                continue
            duplicate = bool(keys[j]) and keys.count(keys[j]) > 1
            lines.extend(render_detail_table(t, j + 1, data_rows, label_max, before, duplicate))

    emit_tables(0)
    for i, text in enumerate(model.paragraphs, start=1):
        if i in included:
            lines.append(f"문단 {i}: {cell_text(text, para_chars)}")
        emit_tables(i)
    return "\n".join(lines), locations


def _brief_desc(model: DocModel, others: list[int], mode: str, brief_title: bool) -> str:
    parts = ["크기"]
    if brief_title and any(table_title(model, model.tables[j]) for j in others):
        parts.append("표 제목 30자")
    shortened = mode == "short" and any(
        len(model.tables[j].rows[table_layout(model.tables[j]).header]) > HEADER_SHORT_CELLS for j in others)
    if mode == "full" or (mode == "short" and not shortened):
        parts.append("머리글")
    elif mode == "short":
        parts.append("머리글 앞 3칸")
    return "·".join(parts)


def _fit_with_paragraphs(model: DocModel, detail: set[int], brief: str, title: bool, level: tuple,
                         budget: int) -> tuple[str, list[str], bool]:
    """상세 표와 붙지 않은 문단을 뒤에서부터 빼며 맞춘다. (글, 관찰 위치, 맞았는지)."""
    included = set(range(1, len(model.paragraphs) + 1))
    text, locations = render(model, detail, brief, *level, included, title)
    removable = sorted(included - _protected(model, detail), reverse=True)
    while removable and len(text) > budget:
        step = max(1, len(removable) // 10)  # 긴 문서도 빨리 맞추도록 여러 문단씩
        for _ in range(step):
            if removable:
                included.discard(removable.pop(0))
        text, locations = render(model, detail, brief, *level, included, title)
    return text, locations, len(text) <= budget


def fit_document(model: DocModel, budget: int) -> tuple[str, list[str]]:
    """비상세 표 머리글 3칸 → 데이터 행 2→1 → 문단 80→40자 → 행 라벨 15→8 → 비보호 문단
    → 비상세 표 머리글 생략 → 비상세 표 앞 문단 제목 생략 → 상세 표 수 → 본문 끝 줄부터."""
    priority = model.detail_priority()
    everything = set(range(1, len(model.paragraphs) + 1))
    n = len(priority)
    detail = set(priority)
    for brief, rows, chars, labels in (("full", 2, 80, FIRST_COL_MAX), ("short", 2, 80, FIRST_COL_MAX),
                                       ("short", 1, 80, FIRST_COL_MAX), ("short", 1, 40, FIRST_COL_MAX),
                                       ("short", 1, 40, FIRST_COL_REDUCED)):
        text, locations = render(model, detail, brief, rows, chars, labels, everything)
        if len(text) <= budget:
            return text, locations
    level = (1, 40, FIRST_COL_REDUCED)
    attempts = [(n, "short", True), (n, "none", True), (n, "none", False)]
    attempts += [(k, "none", False) for k in range(n - 1, 0, -1)]
    if n == 0:
        attempts = [(0, "short", True), (0, "none", True), (0, "none", False)]
    for k, brief, title in attempts:
        text, locations, ok = _fit_with_paragraphs(model, set(priority[:k]), brief, title, level, budget)
        if ok:
            return text, locations
    return _truncate_by_lines(text, budget, level[1], level[0])


_PARA_LINE_RE = re.compile(r"^문단 (\d+):")
_DETAIL_TABLE_RE = re.compile(r"^표(\d+) \(")
_BRIEF_TABLE_RE = re.compile(r"^표(\d+) \d+×\d+")


def _truncate_by_lines(text: str, budget: int, para_chars: int, data_rows: int) -> tuple[str, list[str]]:
    """마지막 수단: 본문 끝 줄부터 빼고, 관찰 위치는 실제로 남은 문단·표로 다시 쓴다 (부록 B 관찰 위치 규칙)."""
    lines = text.split("\n")
    head = [lines[0]] + [l for l in lines[2:4] if l.startswith("레이아웃 칸 ")]
    body = [l for l in lines[2:] if not l.startswith("레이아웃 칸 ")
            and not (l.startswith("(문단 ") and l.endswith(" 미포함)"))]
    keep = len(body)
    while True:
        kept = body[:keep]
        paras = [int(m.group(1)) for l in kept if (m := _PARA_LINE_RE.match(l))]
        detail = [int(m.group(1)) for l in kept if (m := _DETAIL_TABLE_RE.match(l))]
        brief = [int(m.group(1)) for l in kept if (m := _BRIEF_TABLE_RE.match(l))]
        partial = bool(detail) and keep < len(body) and body[keep].startswith("  ")
        locations = []
        if paras:
            locations.append(f"문단 {ranges(paras)} (각 {para_chars}자)")
        if detail:
            locations.append(f"표{ranges(detail)} 머리글·행 라벨·앞 {data_rows}행"
                             + (f" (표{detail[-1]}은 일부)" if partial else ""))
        if brief:
            locations.append(f"표{ranges(brief)} 크기")
        locations.append("이후 생략")
        out = "\n".join([head[0], "관찰 위치: " + ", ".join(locations), *head[1:], *kept])
        if len(out) <= budget or keep == 0:
            return out, locations
        keep -= 1
