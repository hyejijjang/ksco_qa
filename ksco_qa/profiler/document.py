"""HWPX·DOCX·ODT 프로필 (설계 부록 B 문서형, 2026-10-21 보강). 모델·렌더링·축약은 doc_model.

HWPX·ODT는 XML을 직접 파싱한다. 문서를 블록(문단·표) 순서대로 읽고, 레이아웃 칸은 문단 흐름으로 옮긴다.
확장자는 zip 기반 형식인데 zip이 아니면 dispatcher(profile_file)가 EXTENSION_MISMATCH로 처리한다.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from lxml import etree

from ksco_qa.profiler.base import ProfileError
from ksco_qa.profiler.doc_model import DocModel, DocTable, build_doc_model

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
ODF_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
ODF_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"


def _L(name: str) -> str:
    return f"*[local-name()='{name}']"


# --- HWPX ---


def _hwpx_cell_text(tc: etree._Element) -> str:
    parts = ["".join(p.xpath(f".//{_L('t')}/text()")) for p in tc.xpath(f".//{_L('p')}")]
    return " ".join(s for s in parts if s.strip())


def _hwpx_table(tbl: etree._Element) -> DocTable:
    rows, merged, full_span = [], False, set()
    col_count = int(tbl.get("colCnt", "0") or 0)
    for i, tr in enumerate(tbl.xpath(f"./{_L('tr')}")):
        cells = []
        tcs = tr.xpath(f"./{_L('tc')}")
        for tc in tcs:
            span = tc.xpath(f"./{_L('cellSpan')}")
            col_span = int(span[0].get("colSpan", "1")) if span else 1
            if span and (col_span != 1 or span[0].get("rowSpan", "1") != "1"):
                merged = True
            if len(tcs) == 1 and col_count > 1 and col_span >= col_count:
                full_span.add(i)
            cells.append(_hwpx_cell_text(tc))
        rows.append(cells)
    return DocTable(rows, 0, merged, full_span)


def _hwpx(path: Path) -> DocModel:
    with zipfile.ZipFile(path) as z:
        sections = sorted(n for n in z.namelist() if n.startswith("Contents/section") and n.endswith(".xml"))
        if not sections:
            raise ProfileError("HWPX 본문(Contents/section*.xml)이 없다")
        blocks: list[tuple[str, object]] = []
        for name in sections:
            root = etree.fromstring(z.read(name), _PARSER)
            for p in root.xpath(f"./{_L('p')}"):
                blocks.append(("p", "".join(p.xpath(f".//{_L('t')}[not(ancestor::{_L('tbl')})]/text()"))))
                for tbl in p.xpath(f".//{_L('tbl')}[not(ancestor::{_L('tbl')})]"):
                    blocks.append(("t", _hwpx_table(tbl)))
    return build_doc_model("HWPX", blocks)


# --- DOCX ---


def _docx(path: Path) -> DocModel:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    blocks: list[tuple[str, object]] = []
    styled_title = None
    for child in d.element.body.iterchildren():
        tag = etree.QName(child).localname
        if tag == "p":
            para = Paragraph(child, d)
            text = para.text.strip()
            blocks.append(("p", text))
            style = (para.style.name if para.style is not None else "").lower()
            if text and styled_title is None and (style == "title" or style.startswith(("heading 1", "제목"))):
                styled_title = text
        elif tag == "tbl":
            table = Table(child, d)
            rows, full_span = [], set()
            for i, row in enumerate(table.rows):
                seen, cells = set(), []
                for c in row.cells:  # 가로 병합 셀은 같은 _tc가 반복된다
                    if id(c._tc) in seen:
                        continue
                    seen.add(id(c._tc))
                    cells.append(c.text)
                if len(cells) == 1 and len(row.cells) > 1:
                    full_span.add(i)
                rows.append(cells)
            merged = bool(child.xpath(".//*[local-name()='gridSpan' or local-name()='vMerge']"))
            blocks.append(("t", DocTable(rows, 0, merged, full_span)))
    return build_doc_model("DOCX", blocks, styled_title)


# --- ODT ---


def _odt(path: Path) -> DocModel:
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read("content.xml"), _PARSER)
    blocks: list[tuple[str, object]] = []
    styled_title = None
    elements = root.xpath(
        f"//{_L('text')}//*[(local-name()='p' or local-name()='h' or local-name()='table')"
        f" and not(ancestor::{_L('table')})]"
    )
    for el in elements:
        name = etree.QName(el).localname
        if name in ("p", "h"):
            text = "".join(el.itertext()).strip()
            blocks.append(("p", text))
            if text and styled_title is None and name == "h" and el.get(f"{{{ODF_TEXT}}}outline-level", "1") == "1":
                styled_title = text
            continue
        rows, merged = [], False
        for tr in el.xpath(f".//{_L('table-row')}"):
            cells = []
            for tc in tr:
                cname = etree.QName(tc).localname
                if cname == "covered-table-cell":
                    merged = True
                    continue
                if cname != "table-cell":
                    continue
                if int(tc.get(f"{{{ODF_TABLE}}}number-columns-spanned", "1")) > 1:
                    merged = True
                repeat = min(int(tc.get(f"{{{ODF_TABLE}}}number-columns-repeated", "1")), 50)
                cells.extend(["".join(tc.itertext())] * repeat)
            while cells and not cells[-1].strip():
                cells.pop()
            rows.append(cells)
        blocks.append(("t", DocTable(rows, 0, merged)))
    return build_doc_model("ODT", blocks, styled_title)


READERS = {"hwpx": _hwpx, "docx": _docx, "odt": _odt}


def profile(path: Path) -> DocModel:
    return READERS[path.suffix.lower().lstrip(".")](path)
