"""CSV 프로필 (설계 부록 B CSV 행 / M1 결정 14: 20MB 넘으면 스트리밍).

인코딩, 열 수·헤더, 데이터 행 수, 앞·중간·끝 샘플 각 3행, 범주형 열 고유값(최대 20개),
숫자 열 최소·최대, 합계·소계 행 여부. 대용량은 행 수만 세고 샘플만 읽는다.
"""

from __future__ import annotations

import codecs
import csv
import io
from collections import deque
from pathlib import Path

from ksco_qa.profiler.base import (
    CATEGORY_MAX,
    TOTAL_LABEL_RE,
    ProfileError,
    ProfileParts,
    as_number,
    decode_text,
    fmt_number,
    is_blank,
    ranges,
    row_text,
)

STREAM_THRESHOLD = 20 * 1024 * 1024
SAMPLE = 3
DELIMITERS = ",\t;|"


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample[:20000], delimiters=DELIMITERS).delimiter
    except csv.Error:
        return ","


def _detect_stream_encoding(path: Path) -> str:
    with open(path, "rb") as f:
        head = f.read(1 << 20)
    for enc in ("utf-8-sig", "cp949"):
        try:
            codecs.getincrementaldecoder(enc)().decode(head, final=False)
            return enc
        except UnicodeDecodeError:
            continue
    return decode_text(head)[1]


def profile(path: Path) -> ProfileParts:
    if path.stat().st_size > STREAM_THRESHOLD:
        return _profile_stream(path)
    text, encoding = decode_text(path.read_bytes())
    delimiter = _sniff_delimiter(text)
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter) if any(not is_blank(c) for c in r)]
    if not rows:
        raise ProfileError("빈 CSV")
    header, data = rows[0], rows[1:]
    n = len(data)

    numeric, categories = [], {}
    for j, name in enumerate(header):
        values = [r[j].strip() for r in data if j < len(r) and not is_blank(r[j])]
        if not values:
            continue
        nums = [as_number(v) for v in values]
        label = name.strip() or f"열{j + 1}"
        if all(x is not None for x in nums):
            numeric.append(f"{label} {fmt_number(min(nums))}~{fmt_number(max(nums))}")
            continue
        distinct = list(dict.fromkeys(values))
        if len(distinct) <= CATEGORY_MAX:
            categories[label] = distinct
    totals = [i + 2 for i, r in enumerate(data) if r and TOTAL_LABEL_RE.match(next((c for c in r if not is_blank(c)), ""))]

    head_idx = list(range(min(SAMPLE, n)))
    mid_start = max(n // 2 - SAMPLE // 2, SAMPLE)
    mid_idx = [i for i in range(mid_start, min(mid_start + SAMPLE, n)) if i >= SAMPLE and i < n - SAMPLE]
    tail_idx = [i for i in range(max(n - SAMPLE, SAMPLE), n)]
    observed = [1] + [i + 2 for i in head_idx + mid_idx + tail_idx]

    fixed = [
        f"CSV · 인코딩 {encoding} · 구분자 {delimiter!r} · 열 {len(header)} · 데이터 행 {n}",
        f"헤더(1행): {row_text(header)}",
        f"숫자 열 범위: {'; '.join(numeric[:10])}" if numeric else "숫자 열: 없음",
        f"합계·소계 행: {ranges(totals)}행" if totals else "합계·소계 행: 없음",
    ]
    return ProfileParts(
        fixed=fixed,
        locations=[f"전체 {n}행 집계", f"{ranges(sorted(set(observed)))}행 샘플"],
        head=[f"{i + 2}행: {row_text(data[i])}" for i in head_idx],
        mid=[f"{i + 2}행: {row_text(data[i])}" for i in mid_idx],
        tail=[f"{i + 2}행: {row_text(data[i])}" for i in tail_idx],
        categories=categories,
    )


def _profile_stream(path: Path) -> ProfileParts:
    encoding = _detect_stream_encoding(path)
    with open(path, encoding=encoding, errors="replace", newline="") as f:
        delimiter = _sniff_delimiter(f.read(20000))
    head: list[tuple[int, list[str]]] = []
    tail: deque[tuple[int, list[str]]] = deque(maxlen=SAMPLE)
    header: list[str] = []
    n = 0
    with open(path, encoding=encoding, errors="replace", newline="") as f:
        for row in csv.reader(f, delimiter=delimiter):
            if not any(not is_blank(c) for c in row):
                continue
            if not header:
                header = row
                continue
            n += 1
            if len(head) < SAMPLE:
                head.append((n + 1, row))
            tail.append((n + 1, row))
    mid: list[tuple[int, list[str]]] = []
    mid_start = max(n // 2 - SAMPLE // 2, SAMPLE)
    with open(path, encoding=encoding, errors="replace", newline="") as f:
        k = -1
        for row in csv.reader(f, delimiter=delimiter):
            if not any(not is_blank(c) for c in row):
                continue
            k += 1
            if k == 0:
                continue
            if mid_start <= k - 1 < mid_start + SAMPLE and SAMPLE <= k - 1 < n - SAMPLE:
                mid.append((k + 1, row))
            if k - 1 >= mid_start + SAMPLE:
                break
    size_mb = path.stat().st_size / (1024 * 1024)
    observed = sorted({1, *(r for r, _ in head), *(r for r, _ in mid), *(r for r, _ in tail)})
    return ProfileParts(
        fixed=[
            f"CSV · 인코딩 {encoding} · 구분자 {delimiter!r} · 열 {len(header)} · 데이터 행 {n} · "
            f"{size_mb:.1f}MB 대용량: 행 수와 샘플만 확인(범주값·숫자 범위·합계 행 미확인)",
            f"헤더(1행): {row_text(header)}",
        ],
        locations=[f"전체 {n}행 행 수 집계", f"{ranges(observed)}행 샘플"],
        head=[f"{r}행: {row_text(c)}" for r, c in head],
        mid=[f"{r}행: {row_text(c)}" for r, c in mid],
        tail=[f"{r}행: {row_text(c)}" for r, c in tail],
    )
