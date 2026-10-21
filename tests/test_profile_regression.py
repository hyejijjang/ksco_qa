"""프로필 회귀 테스트 — 실제 accounting 파일 4개와 같은 구조의 가상 fixture로, 규칙을 바꿔도 지켜야 할 결과.

- 재무제표형: 재무상태표·손익계산서·현금흐름표가 모두 상세로 들어가고 1단계 과목이 보인다
- 업무추진비형: 연번을 건너뛰고 실제 행 라벨이 보인다
- 2열 "구 분 | 내 용" 표가 데이터 표로 남는다
- 모든 프로필이 PROFILE_MAX_CHARS 이하이고, 관찰 위치는 담은 범위만 적는다
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fixtures.real_like import (
    BALANCE_TOP,
    CASHFLOW_TOP,
    INCOME_TOP,
    expense_pdf_model,
    financial_statement_pdf_model,
    write_settlement_hwpx,
)
from fixtures.sample_task import write_hwpx_card
from ksco_qa.config import Config
from ksco_qa.profiler import profile_file, row_budget
from ksco_qa.profiler.base import ranges

BUDGET = Config().PROFILE_MAX_CHARS


def _pdf_budget(name: str) -> int:
    return row_budget([name], BUDGET)


def _check_pdf_locations(text: str, locations: list[str]) -> None:
    """관찰 위치의 상세 쪽 = 글에 실제로 있는 "pN 상세" 쪽, 나머지 쪽은 "pN:" 한 줄."""
    detail = sorted(int(x) for x in re.findall(r"^p(\d+) 상세:", text, re.M))
    others = sorted(int(x) for x in re.findall(r"^p(\d+): ", text, re.M))
    assert locations[0].startswith(f"p{ranges(detail)} 상세(")
    if others:
        assert any(l.startswith(f"p{ranges(others)} 첫 줄") for l in locations)
    assert f"관찰 위치: {', '.join(locations)}" in text


def _check_doc_locations(text: str, locations: list[str]) -> None:
    """관찰 위치의 문단·상세 표·비상세 표 = 글에 실제로 있는 것."""
    paras = sorted(int(x) for x in re.findall(r"^문단 (\d+):", text, re.M))
    detail = sorted(int(x) for x in re.findall(r"^표(\d+) \(", text, re.M))
    brief = sorted(int(x) for x in re.findall(r"^표(\d+) \d+×\d+", text, re.M))
    if paras:
        assert locations[0].startswith(f"문단 {ranges(paras)} (각 ")
    if detail:
        assert any(l.startswith(f"표{ranges(detail)} 머리글·행 라벨") for l in locations)
    if brief:
        assert any(l.startswith(f"표{ranges(brief)} 크기") for l in locations)
    assert f"관찰 위치: {', '.join(locations)}" in text


def test_financial_statement_pdf_three_statements_detailed() -> None:
    m = financial_statement_pdf_model()
    budget = _pdf_budget("가상첨단산업진흥재단_재무제표_01_재무제표 본표.pdf")
    text, locations = m.fit_to(budget)
    assert len(text) <= budget
    detail = {int(x) for x in re.findall(r"^p(\d+) 상세:", text, re.M)}
    assert {2, 4, 7} <= detail  # 재무상태표·손익계산서·현금흐름표
    for name in ("유동자산", "비유동자산", "매출액", "영업이익", "당기순이익", *CASHFLOW_TOP):
        assert name in text, name
    assert "레이아웃 칸" in text and "(p2 표 이어짐)" in text and "(p4 표 이어짐)" in text
    _check_pdf_locations(text, locations)


def test_income_statement_top_level_all_shown_first() -> None:
    m = financial_statement_pdf_model()
    text, _ = m.fit_to(_pdf_budget("x.pdf"))
    line = next(l for l in text.split("\n") if "행 라벨(상위 우선)" in l and "매출액" in l)
    shown = re.search(r"\d+/\d+: (.*)$", line).group(1)
    assert shown.startswith(", ".join(INCOME_TOP))  # 1단계 10개 전부, 원래 순서로 맨 앞
    assert f"1단계 {len(INCOME_TOP)}/" in line


def test_expense_pdf_skips_serial_column() -> None:
    m = expense_pdf_model()
    budget = _pdf_budget("가상구_업무추진비 공개_가상과_2026년 9월.pdf")
    text, locations = m.fit_to(budget)
    assert len(text) <= budget
    assert "표1 행 라벨: 2열, 1열 연번(5): 기획예산과장, 업무담당자, 기획재정국장, 기획조정팀장, 업무관계자" in text
    assert "상위 우선" not in text  # 번호 체계가 없는 목록은 원래 순서
    _check_pdf_locations(text, locations)


def test_settlement_hwpx_statements_and_top_level(tmp_path: Path) -> None:
    path = tmp_path / "가상공사_결산현황.hwpx"
    write_settlement_hwpx(path)
    budget = row_budget([path.name], BUDGET)
    p = profile_file(path, path.name, None, budget)
    assert p.inspected and len(p.text) <= budget
    t = p.text
    assert t.startswith("HWPX · 제목: 3. 재 무 제 표 (가상공사)")  # 제목 반복 문구는 한 번만
    assert "레이아웃 칸 4개 제외" in t  # 제목 상자(1열) + 1행 제목 칸 3개
    assert re.search(r"^표1 \(문단 \d+ 다음\) 84행 × 8열 .*제목 행: 가상공사 \(단위 : 원\)", t, re.M)
    assert re.search(r"^표2 \(문단 \d+ 다음\) 66행 × 9열", t, re.M)  # 손익계산서 상세
    for name in ("유동자산", "비유동자산", "매출액", "영업이익", "당기순이익"):
        assert name in t, name
    assert "금      액" not in t.split("머리글:")[1].split("\n")[1]  # 머리글 이어짐은 행 라벨이 아님
    _check_doc_locations(t, p.inspected_locations)


def test_two_column_tables_stay_data_tables(tmp_path: Path) -> None:
    write_hwpx_card(tmp_path / "card.hwpx")
    p = profile_file(tmp_path / "card.hwpx", "card.hwpx", None, row_budget(["card.hwpx"], BUDGET))
    t = p.text
    for no, rows in ((3, 3), (4, 2)):
        assert re.search(rf"^표{no} \(문단 \d+ 다음\) {rows}행 × 2열", t, re.M)
    assert "머리글: 구   분 | 내      용" in t
    _check_doc_locations(t, p.inspected_locations)


@pytest.mark.parametrize("budget", [600, 900, 1200])
def test_smaller_budgets_still_within_limit_and_honest(tmp_path: Path, budget: int) -> None:
    """PROFILE_MAX_CHARS를 바꿔도 예산 이하이고 관찰 위치는 담은 범위만."""
    text, locations = financial_statement_pdf_model().fit_to(budget)
    assert len(text) <= budget
    if "…(생략)" not in text:
        _check_pdf_locations(text, locations)
    path = tmp_path / "s.hwpx"
    write_settlement_hwpx(path)
    p = profile_file(path, "s.hwpx", None, budget)
    assert len(p.text) <= budget
    _check_doc_locations(p.text, p.inspected_locations)


def test_balance_sheet_top_levels_present() -> None:
    text, _ = financial_statement_pdf_model().fit_to(_pdf_budget("x.pdf"))
    line = next(l for l in text.split("\n") if "행 라벨(상위 우선)" in l and "유동자산" in l)
    assert re.search(r"\d+/\d+: (.*)$", line).group(1).startswith(", ".join(BALANCE_TOP))
