"""FILE_ACCESS=fulltext: 원본 전문 텍스트와 행 기준치 (2026-10-23 결정)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ksco_qa.config import Config
from ksco_qa.p0 import FULLTEXT_FIELDS, ROW_CARD_FIELDS, run_p0
from ksco_qa.profiler.fulltext import FullText, combine_for_row, estimate_tokens, extract


@pytest.fixture
def full(sample_task: Path, tmp_path: Path):
    result = run_p0(sample_task, Config(FILE_ACCESS="fulltext"), tmp_path / "run", tmp_path / "audit.csv")
    return {c["id"]: (c, r) for c, r in zip(result.row_cards, result.records)}


def test_profile_mode_row_card_unchanged(sample_task: Path, tmp_path: Path) -> None:
    result = run_p0(sample_task, Config(), tmp_path / "run", tmp_path / "audit.csv")
    assert all(tuple(card) == ROW_CARD_FIELDS for card in result.row_cards)


def test_fulltext_mode_adds_fields_after_design_fields(full) -> None:
    for card, _ in full.values():
        assert tuple(card) == ROW_CARD_FIELDS + FULLTEXT_FIELDS


@pytest.mark.parametrize("row_id, markers", [
    ("T-001", ["[파일] 2024년 월별 매출 현황.csv"]),
    ("T-003", ["[시트]"]),
    ("T-006", ["[p1]", "Overview of the survey procedure", "3. Response review and tabulation steps"]),
    ("T-007", ["[슬라이드 1]"]),
    ("T-008", ["[파일] 통계 보고서.hwpx", "[파일] 통계 보고서.xlsx", "[표1 "]),
    ("T-010", ["[파일] 자료모음.zip!/원자료/설문 원자료.json", "records"]),
    ("T-012", ["절차"]),
])
def test_each_format_attaches_full_text(full, row_id: str, markers: list[str]) -> None:
    card, rec = full[row_id]
    for marker in markers:
        assert marker in card["file_fulltext"], marker
    assert "원본 전문 첨부" in card["file_fulltext_note"]
    assert all("text" not in item for item in rec["fulltext"])  # 전문은 row_card에만, P0 기록엔 토큰·사유만


def test_unsupported_or_unmatched_rows_keep_profile_only(full) -> None:
    hwp, _ = full["T-013"]
    assert hwp["file_fulltext"] is None and "미지원 형식: HWP" in hwp["file_fulltext_note"]
    missing, _ = full["T-004"]
    assert missing["file_fulltext"] is None and missing["file_fulltext_note"] == "매핑 NOT_FOUND: 원본 없음"


def test_large_text_file_skipped_by_size_without_reading(tmp_path: Path) -> None:
    big = tmp_path / "big.csv"
    big.write_text("가,나\n" * 50_000, encoding="utf-8")  # 30만 바이트 → 하한 약 7만 토큰
    result = extract(big, max_tokens=30_000)
    assert result.text is None and result.lower_bound and result.tokens > 30_000


def test_row_budget_is_cumulative_in_file_order() -> None:
    items = [FullText("a.pdf", "가" * 1000, 700), FullText("b.pdf", "나" * 1000, 700),
             FullText("c.csv", None, 90_000, lower_bound=True)]
    text, note = combine_for_row(items, max_tokens=1000)
    assert text == "[파일] a.pdf\n" + "가" * 1000
    assert "a.pdf: 원본 전문 첨부 (약 700토큰)" in note
    assert "b.pdf: 미첨부 (약 700토큰, 행 누적 기준 1,000 초과)" in note
    assert "c.csv: 미첨부 (약 90,000토큰 이상 > 기준 1,000)" in note


def test_estimate_is_conservative_against_measured_ratio() -> None:
    # 실측 0.61~0.64 토큰/글자보다 크게 잡는다
    assert estimate_tokens("가" * 1000) == 700


def test_config_rejects_unknown_file_access() -> None:
    with pytest.raises(ValueError):
        Config(FILE_ACCESS="fulltext+tools")
    assert Config(FILE_ACCESS="fulltext", MODE="batch").FULLTEXT_MAX_TOKENS == 30000
