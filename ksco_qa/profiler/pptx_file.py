"""PPTX 프로필 (설계 부록 B PPTX 행): 슬라이드 수, 슬라이드별 제목, 표·도표 여부."""

from __future__ import annotations

from pathlib import Path

from ksco_qa.profiler.base import ProfileParts, cell_text


def profile(path: Path) -> ProfileParts:
    from pptx import Presentation

    prs = Presentation(str(path))
    lines, n_tables, n_charts = [], 0, 0
    for i, slide in enumerate(prs.slides, start=1):
        title = slide.shapes.title.text if slide.shapes.title is not None and slide.shapes.title.has_text_frame else ""
        has_table = any(getattr(s, "has_table", False) and s.has_table for s in slide.shapes)
        has_chart = any(getattr(s, "has_chart", False) and s.has_chart for s in slide.shapes)
        n_tables += has_table
        n_charts += has_chart
        flags = "".join(f" [{name}]" for name, on in (("표", has_table), ("도표", has_chart)) if on)
        lines.append(f"s{i}: {cell_text(title, 60) or '(제목 없음)'}{flags}")
    n = len(lines)
    return ProfileParts(
        fixed=[f"PPTX · 슬라이드 {n} · 표 있는 슬라이드 {n_tables} · 도표 있는 슬라이드 {n_charts}"],
        locations=[f"슬라이드 1-{n}" if n else "슬라이드 없음"],
        head=lines,
        head_label="슬라이드별 제목",
    )
