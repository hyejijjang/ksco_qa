"""HWPX·DOCX·ODT 프로필 (설계 부록 B HWPX·DOCX·ODT 행).

제목 구조, 표 개수와 표별 머리글. HWPX·ODT는 XML을 직접 파싱한다.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from lxml import etree

from ksco_qa.profiler.base import HEADING_RE, ProfileError, ProfileParts, cell_text, row_text

MAX_HEADINGS = 40
MAX_TABLES = 20
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


def _local(xpath_name: str) -> str:
    return f"*[local-name()='{xpath_name}']"


def _texts(el: etree._Element, text_tag: str) -> str:
    return "".join(el.xpath(f".//{_local(text_tag)}/text()"))


def _hwpx(path: Path) -> tuple[list[str], list[list[str]], int]:
    with zipfile.ZipFile(path) as z:
        sections = sorted(n for n in z.namelist() if n.startswith("Contents/section") and n.endswith(".xml"))
        if not sections:
            raise ProfileError("HWPX 본문(Contents/section*.xml)이 없다")
        headings, tables, paragraphs = [], [], 0
        for name in sections:
            root = etree.fromstring(z.read(name), _PARSER)
            for p in root.xpath(f"//{_local('p')}[not(ancestor::{_local('tbl')})]"):
                text = _texts(p, "t").strip()
                if not text:
                    continue
                paragraphs += 1
                if HEADING_RE.match(text) and len(text) <= 60:
                    headings.append(text)
            for tbl in root.xpath(f"//{_local('tbl')}[not(ancestor::{_local('tbl')})]"):
                first = tbl.xpath(f".//{_local('tr')}[1]")
                cells = [_texts(tc, "t") for tc in first[0].xpath(f"./{_local('tc')}")] if first else []
                tables.append(cells)
    return headings, tables, paragraphs


def _docx(path: Path) -> tuple[list[str], list[list[str]], int]:
    import docx

    d = docx.Document(str(path))
    headings, paragraphs = [], 0
    for p in d.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        paragraphs += 1
        style = (p.style.name if p.style is not None else "").lower()
        if style.startswith(("heading", "제목", "title")) or (HEADING_RE.match(text) and len(text) <= 60):
            headings.append(text)
    tables = [[c.text for c in t.rows[0].cells] if t.rows else [] for t in d.tables]
    return headings, tables, paragraphs


def _odt(path: Path) -> tuple[list[str], list[list[str]], int]:
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read("content.xml"), _PARSER)
    headings = ["".join(h.itertext()).strip() for h in root.xpath(f"//{_local('h')}")]
    paragraphs = sum(1 for p in root.xpath(f"//{_local('p')}") if "".join(p.itertext()).strip())
    tables = []
    for t in root.xpath(f"//{_local('table')}[not(ancestor::{_local('table')})]"):
        first = t.xpath(f".//{_local('table-row')}[1]")
        tables.append(["".join(c.itertext()) for c in first[0].xpath(f"./{_local('table-cell')}")] if first else [])
    return [h for h in headings if h], tables, paragraphs + len(headings)


READERS = {"hwpx": _hwpx, "docx": _docx, "odt": _odt}


def profile(path: Path) -> ProfileParts:
    ext = path.suffix.lower().lstrip(".")
    headings, tables, paragraphs = READERS[ext](path)
    fixed = [f"{ext.upper()} · 문단 {paragraphs} · 제목 {len(headings)} · 표 {len(tables)}"]
    return ProfileParts(
        fixed=fixed,
        locations=["본문 전체 문단"] + ([f"표 1-{len(tables)} 첫 행"] if tables else []),
        head=[cell_text(h, 60) for h in headings[:MAX_HEADINGS]],
        head_label="제목 구조",
        tail=[f"표{i + 1} 머리글: {row_text(cells)}" for i, cells in enumerate(tables[:MAX_TABLES])],
        tail_label="표별 머리글",
    )
