"""JSON·XML·HTML 프로필 (M1 결정: 부록 B에 추가).

JSON: 최상위 구조·키 목록·레코드 수·샘플. XML: 루트·반복 요소·필드. HTML: 제목 구조·표.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from lxml import etree

from ksco_qa.profiler.base import ProfileError, ProfileParts, cell_text, decode_text, row_text

MAX_KEYS = 30
SAMPLE = 2
_XML_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


def _type_name(v: Any) -> str:
    if isinstance(v, dict):
        return f"객체({len(v)}키)"
    if isinstance(v, list):
        return f"배열({len(v)})"
    return {str: "문자열", bool: "참거짓", int: "숫자", float: "숫자", type(None): "null"}.get(type(v), type(v).__name__)


def _records(v: Any) -> bool:
    return isinstance(v, list) and bool(v) and all(isinstance(x, dict) for x in v[:50])


def _sample(x: Any) -> str:
    return cell_text(json.dumps(x, ensure_ascii=False), 180)


def profile_json(path: Path) -> ProfileParts:
    text, encoding = decode_text(path.read_bytes())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ProfileError(f"JSON 파싱 실패: {e.msg} ({e.lineno}행)") from e
    fixed = [f"JSON · 인코딩 {encoding} · 최상위 {_type_name(data)}"]
    records_path, records = None, None
    if _records(data):
        records_path, records = "$", data
    elif isinstance(data, dict):
        keys = list(data)
        fixed.append("최상위 키: " + ", ".join(f"{k}:{_type_name(data[k])}" for k in keys[:MAX_KEYS])
                     + (f" 외 {len(keys) - MAX_KEYS}개" if len(keys) > MAX_KEYS else ""))
        for k in keys:
            v = data[k]
            if _records(v):
                records_path, records = f"$.{k}", v
                break
            if isinstance(v, dict):
                inner = next((k2 for k2, v2 in v.items() if _records(v2)), None)
                if inner is not None:
                    records_path, records = f"$.{k}.{inner}", v[inner]
                    break
    head, tail, locations = [], [], ["전체 구조"]
    if records is not None:
        keys = list(dict.fromkeys(k for r in records[:200] for k in r))
        fixed.append(f"레코드 배열 {records_path}: {len(records)}건 · 필드 {len(keys)}: {', '.join(keys[:MAX_KEYS])}")
        head = [f"[{i}] {_sample(r)}" for i, r in enumerate(records[:SAMPLE])]
        tail = [f"[{len(records) - 1}] {_sample(records[-1])}"] if len(records) > SAMPLE else []
        locations.append(f"{records_path}[0-{min(SAMPLE, len(records)) - 1}]" + (f", [{len(records) - 1}]" if tail else ""))
    return ProfileParts(fixed=fixed, locations=locations, head=head, tail=tail, head_label="앞 레코드", tail_label="끝 레코드")


def _local(tag: Any) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else str(tag)


def _record_parent(root: etree._Element, max_depth: int = 3) -> etree._Element:
    """같은 태그 자식이 가장 많이 반복되는 요소 (깊이 3까지)."""
    best, best_count, frontier = root, 0, [root]
    for _ in range(max_depth):
        nxt = []
        for el in frontier:
            children = [c for c in el if isinstance(c.tag, str)]
            if children:
                count = Counter(_local(c.tag) for c in children).most_common(1)[0][1]
                if count > best_count:
                    best, best_count = el, count
            nxt += children[:20]
        frontier = nxt
    return best


def profile_xml(path: Path) -> ProfileParts:
    try:
        root = etree.fromstring(path.read_bytes(), _XML_PARSER)
    except etree.XMLSyntaxError as e:
        raise ProfileError(f"XML 파싱 실패: {e}") from e
    parent = _record_parent(root)
    children = [c for c in parent if isinstance(c.tag, str)]
    fixed = [f"XML · 루트 <{_local(root.tag)}> · 하위 요소 {len([c for c in root if isinstance(c.tag, str)])}"]
    head, tail, locations = [], [], ["전체 구조"]
    if children:
        tag, count = Counter(_local(c.tag) for c in children).most_common(1)[0]
        records = [c for c in children if _local(c.tag) == tag]
        fields = list(dict.fromkeys(
            [f"@{_local(a)}" for a in records[0].attrib] + [_local(f.tag) for f in records[0] if isinstance(f.tag, str)]
        ))
        fixed.append(f"반복 요소 <{tag}> {count}건 (부모 <{_local(parent.tag)}>) · 필드: {', '.join(fields[:MAX_KEYS])}")

        def rec(el: etree._Element) -> str:
            parts = [f"@{_local(k)}={v}" for k, v in el.attrib.items()]
            parts += [f"{_local(f.tag)}={(f.text or '').strip()}" for f in el if isinstance(f.tag, str)]
            return row_text(parts)

        head = [rec(r) for r in records[:SAMPLE]]
        tail = [rec(records[-1])] if len(records) > SAMPLE else []
        locations.append(f"<{tag}> 1-{min(SAMPLE, len(records))}" + (f", {len(records)}" if tail else "") + "번째")
    return ProfileParts(fixed=fixed, locations=locations, head=head, tail=tail, head_label="앞 레코드", tail_label="끝 레코드")


def profile_html(path: Path) -> ProfileParts:
    from lxml import html

    text, encoding = decode_text(path.read_bytes())
    doc = html.fromstring(text)
    title = cell_text(" ".join(doc.xpath("//title//text()")), 80)
    headings = [f"{h.tag}: {cell_text(h.text_content(), 60)}" for h in doc.xpath("//h1|//h2|//h3")]
    tables = doc.xpath("//table")
    table_lines = []
    for i, t in enumerate(tables[:20], start=1):
        first = t.xpath(".//tr[1]")
        cells = [c.text_content() for c in first[0].xpath("./th|./td")] if first else []
        table_lines.append(f"표{i} 머리글: {row_text(cells)}")
    return ProfileParts(
        fixed=[f"HTML · 인코딩 {encoding} · 제목: {title or '(없음)'} · h1-h3 {len(headings)} · 표 {len(tables)}"],
        locations=["문서 전체"],
        head=headings[:40],
        head_label="제목 구조",
        tail=table_lines,
        tail_label="표별 머리글",
    )
