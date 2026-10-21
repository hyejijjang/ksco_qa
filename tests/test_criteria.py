"""criteria.yaml — 16개 지표, 설계 부록 A 원문과 글자 단위 일치."""

from __future__ import annotations

import re

from ksco_qa.dictionaries import REPO_ROOT, criterion_for, load_criteria


def appendix_a_rows() -> list[tuple[str, str, str]]:
    text = (REPO_ROOT / "docs" / "design.md").read_text(encoding="utf-8")
    section = re.search(r"### A\..*?\n(.*?)\n### B\.", text, re.S).group(1)
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0] not in ("지표",) and not set(cells[0]) <= {"-"}:
            rows.append((cells[0], cells[1], cells[2]))
    return rows


def indicator_label(c: dict) -> str:
    if c["g0_key"] is None:
        return c["g2_key"]
    if c["g0_key"] == c["g2_key"]:
        return c["g0_key"]
    return f"{c['g0_key']} / {c['g2_key']}"


def test_sixteen_indicators() -> None:
    criteria = load_criteria()
    assert len(criteria) == 16
    assert len({c["g2_key"] for c in criteria}) == 16
    assert sum(c["g0_key"] is not None for c in criteria) == 10


def test_matches_design_appendix_a_verbatim() -> None:
    expected = appendix_a_rows()
    assert len(expected) == 16
    actual = [(indicator_label(c), c["stage"], c["criterion"]) for c in load_criteria()]
    assert actual == expected


def test_criterion_lookup_by_g0_or_g2_key() -> None:
    assert criterion_for("reasoning_validity") == criterion_for("reasoning_requirement")
    assert criterion_for("no_answer_leakage") == criterion_for("answer_leakage")
