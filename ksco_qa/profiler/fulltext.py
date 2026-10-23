"""원본 전문 텍스트 (FILE_ACCESS=fulltext, 2026-10-23 결정).

Deliverable 파일의 글자를 형식별로 순서대로 뽑아 row_card.file_fulltext로 보낸다. 요약·축약은 하지 않는다.
행의 추정 토큰 합계가 FULLTEXT_MAX_TOKENS 이하인 파일만 붙이고, 넘는 파일은 file_profile만 쓴다 (사유는 file_fulltext_note).

추정 토큰 = 글자 수 × 0.7. 2026-10-23 실측(G0 30호출, 입력 글자 대비 API input_tokens 0.61~0.64)보다 넉넉하게 잡았다.
이 값은 기준치 판정에만 쓰고, 토큰·비용 기록은 API usage 실측값만 쓴다.
"""

from __future__ import annotations

import json
import math
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from ksco_qa.profiler.base import ProfileError, decode_text

FULLTEXT_VERSION = "1"
TOKENS_PER_CHAR = 0.7
# 글자 수를 바이트로 아래에서 어림할 수 있는 텍스트 형식: 한 글자는 많아야 3바이트(UTF-8)
TEXT_FORMATS = {"csv", "json", "xml", "html", "htm"}
MAX_BYTES_PER_CHAR = 3


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) * TOKENS_PER_CHAR)


@dataclass
class FullText:
    locator: str | None  # 캐시 파일에는 null
    text: str | None  # 추출 실패·크기 초과로 읽지 않았으면 None
    tokens: int | None  # 추정 토큰 (크기로 건너뛴 경우 하한)
    error: str | None = None
    lower_bound: bool = False  # tokens가 파일 크기로 어림한 하한이면 True

    def to_dict(self) -> dict:
        return asdict(self)


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value).split())


def _rows(rows: list[list[object]]) -> list[str]:
    out = []
    for row in rows:
        cells = [_cell(v) for v in row]
        while cells and not cells[-1]:
            cells.pop()
        out.append(" | ".join(cells))
    return out


def _pdf(path: Path) -> str:
    import pdfplumber

    try:
        pdf = pdfplumber.open(str(path))
    except Exception as e:
        raise ProfileError(f"PDF를 열 수 없음: {type(e).__name__}") from e
    with pdf:
        pages = [f"[p{i}]\n{(page.extract_text() or '').strip()}" for i, page in enumerate(pdf.pages, start=1)]
    return "\n".join(pages)


def _spreadsheet(path: Path) -> str:
    from ksco_qa.profiler import spreadsheet

    loaders = {"xlsx": spreadsheet._load_xlsx, "xlsm": spreadsheet._load_xlsx,
               "xls": spreadsheet._load_xls, "ods": spreadsheet._load_ods}
    sheets = loaders[path.suffix.lower().lstrip(".")](path)
    return "\n".join(f"[시트] {s.name}\n" + "\n".join(_rows(s.rows)) for s in sheets)


def _document(path: Path) -> str:
    from ksco_qa.profiler import document

    model = document.profile(path)
    by_position: dict[int, list[int]] = {}
    for j, t in enumerate(model.tables):
        by_position.setdefault(t.after_paragraph, []).append(j)
    lines: list[str] = []

    def emit_tables(after: int) -> None:
        for j in by_position.get(after, []):
            t = model.tables[j]
            lines.append(f"[표{j + 1} {t.n_rows}×{t.n_cols}]")
            lines.extend(_rows(t.rows))

    emit_tables(0)
    for i, paragraph in enumerate(model.paragraphs, start=1):
        lines.append(paragraph)
        emit_tables(i)
    return "\n".join(lines)


def _pptx(path: Path) -> str:
    from pptx import Presentation

    lines = []
    for i, slide in enumerate(Presentation(str(path)).slides, start=1):
        lines.append(f"[슬라이드 {i}]")
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                lines.append(shape.text_frame.text.strip())
            if getattr(shape, "has_table", False) and shape.has_table:
                lines.extend(_rows([[c.text for c in r.cells] for r in shape.table.rows]))
    return "\n".join(lines)


def _text_file(path: Path) -> str:
    text, _ = decode_text(path.read_bytes())
    if path.suffix.lower() in (".html", ".htm"):
        import lxml.html

        return lxml.html.fromstring(text).text_content()
    return text


EXTRACTORS = {
    "pdf": _pdf,
    "xlsx": _spreadsheet, "xlsm": _spreadsheet, "xls": _spreadsheet, "ods": _spreadsheet,
    "hwpx": _document, "docx": _document, "odt": _document,
    "pptx": _pptx,
    "csv": _text_file, "json": _text_file, "xml": _text_file, "html": _text_file, "htm": _text_file,
}


def extract(path: Path, max_tokens: int) -> FullText:
    """형식별 전문 텍스트. 텍스트 형식은 파일 크기만으로 기준치를 넘는 게 확실하면 읽지 않는다."""
    ext = path.suffix.lower().lstrip(".")
    extractor = EXTRACTORS.get(ext)
    if extractor is None:
        return FullText(None, None, None, f"전문 추출 미지원 형식: {ext.upper() or '(확장자 없음)'}")
    if ext in TEXT_FORMATS:
        floor = math.ceil(path.stat().st_size / MAX_BYTES_PER_CHAR * TOKENS_PER_CHAR)
        if floor > max_tokens:
            return FullText(None, None, floor, None, lower_bound=True)
    try:
        text = extractor(path)
    except ProfileError as e:
        return FullText(None, None, None, str(e))
    except Exception as e:  # 손상 파일 등: 전문 없이 프로필로 진행
        return FullText(None, None, None, f"전문 추출 실패: {type(e).__name__}")
    text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    return FullText(None, text, estimate_tokens(text))


def fulltext_file(path: Path, locator: str, cache_dir: Path | None, max_tokens: int) -> FullText:
    """같은 내용·기준치면 캐시(_work/file_profiles/)를 쓴다."""
    from ksco_qa.profiler import file_hash

    cache_path = None
    if cache_dir is not None:
        cache_path = Path(cache_dir) / f"{file_hash(path)}__fulltext{max_tokens}__v{FULLTEXT_VERSION}.json"
        if cache_path.is_file():
            cached = FullText(**json.loads(cache_path.read_text(encoding="utf-8")))
            cached.locator = locator
            return cached
    result = extract(path, max_tokens)
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False), encoding="utf-8")
    result.locator = locator
    return result


def fulltext_member(zip_path: Path, member: str, locator: str, cache_dir: Path | None, max_tokens: int) -> FullText:
    suffix = Path(member).suffix
    with zipfile.ZipFile(zip_path) as z, tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / f"member{suffix}"
        with z.open(member) as src, open(target, "wb") as dst:
            while chunk := src.read(1 << 20):
                dst.write(chunk)
        return fulltext_file(target, locator, cache_dir, max_tokens)


def combine_for_row(items: list[FullText], max_tokens: int) -> tuple[str | None, str]:
    """행의 파일 순서대로, 누적 추정 토큰이 기준치 이하인 파일만 붙인다. (file_fulltext, file_fulltext_note)."""
    blocks, notes, used = [], [], 0
    for item in items:
        if item.text is None:
            if item.error:
                notes.append(f"{item.locator}: 미첨부 ({item.error}) — file_profile 참고")
            else:
                notes.append(f"{item.locator}: 미첨부 (약 {item.tokens:,}토큰 이상 > 기준 {max_tokens:,}) — file_profile 참고")
            continue
        if used + item.tokens > max_tokens:
            notes.append(f"{item.locator}: 미첨부 (약 {item.tokens:,}토큰, 행 누적 기준 {max_tokens:,} 초과) — file_profile 참고")
            continue
        used += item.tokens
        blocks.append(f"[파일] {item.locator}\n{item.text}")
        notes.append(f"{item.locator}: 원본 전문 첨부 (약 {item.tokens:,}토큰)")
    return ("\n\n".join(blocks) if blocks else None), "; ".join(notes)


__all__ = ["FullText", "combine_for_row", "estimate_tokens", "extract", "fulltext_file", "fulltext_member"]
