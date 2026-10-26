"""파일 프로파일러 (설계 부록 B / M1 결정 11~14, JSON·XML·HTML 추가)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from fixtures.sample_task import (
    write_csv,
    write_docx_card,
    write_hwpx_card,
    write_pdf,
    write_pdf_table,
    write_pptx,
    write_xlsx,
)
from ksco_qa.profiler import PROFILERS, combine_for_row, profile_file, row_budget
from ksco_qa.profiler import csv_file
from ksco_qa.profiler.base import ProfileParts, fit, render
from ksco_qa.profiler.zip_file import member_display_name


def prof(path: Path, budget: int = 1500):
    return profile_file(path, path.name, None, budget)


# --- 축약 순서 (결정 11) ---


def parts() -> ProfileParts:
    return ProfileParts(
        fixed=["구조: 열 4 · 행 100"],
        locations=["1-4행", "50-52행", "98-100행"],
        head=[f"앞{i} " + "가" * 50 for i in range(3)],
        mid=[f"중{i} " + "나" * 50 for i in range(3)],
        tail=[f"끝{i} " + "다" * 50 for i in range(3)],
        categories={"지역": [f"지역{i:02d}" for i in range(20)]},
    )


def test_fit_reduction_order() -> None:
    """중간 샘플 → 범주값(20→10) → 끝 샘플 → 앞 샘플(1행까지). 구조·관찰 위치는 남는다."""
    full = fit(parts(), 10_000)
    assert "중0" in full and "지역19" in full

    p = parts()
    p.mid = []
    s1 = fit(parts(), len(render(p)))
    assert "중0" not in s1 and "지역19" in s1 and "끝0" in s1 and "앞2" in s1

    s2 = fit(parts(), len(render(p, 10)))
    assert "지역09" in s2 and "지역10" not in s2 and "외 10개" in s2 and "끝0" in s2

    p.tail = []
    s3 = fit(parts(), len(render(p, 10)))
    assert "끝0" not in s3 and "앞2" in s3

    p.head = p.head[:1]
    s4 = fit(parts(), len(render(p, 10)))
    assert "앞0" in s4 and "앞1" not in s4
    assert "구조: 열 4" in s4 and "관찰 위치: 1-4행, 50-52행, 98-100행" in s4


def test_fit_never_exceeds_budget() -> None:
    p = parts()
    p.fixed = ["구조 " + "x" * 400]
    assert len(fit(p, 150)) <= 150


def test_row_budget_splits_for_multiple_files() -> None:
    assert row_budget(["a.csv"]) == 1500 - len("[파일] a.csv\n")
    two = row_budget(["a.hwpx", "a.xlsx"])
    assert 2 * two + len("[파일] a.hwpx\n[파일] a.xlsx\n") + 2 <= 1500


# --- 형식별 ---


def test_csv_utf8_and_cp949(tmp_path: Path) -> None:
    write_csv(tmp_path / "u.csv", 2024)
    write_csv(tmp_path / "k.csv", 2024, encoding="cp949")
    u, k = prof(tmp_path / "u.csv"), prof(tmp_path / "k.csv")
    assert u.inspected and k.inspected
    assert "인코딩 utf-8" in u.text and "인코딩 cp949" in k.text
    for p in (u, k):
        assert "열 4 · 데이터 행 13" in p.text and "헤더(1행): 월 | 구분 | 매출액 | 전월대비증감률" in p.text
        assert "매출액 1087~1494" in p.text and "합계·소계 행: 14행" in p.text
        assert "구분(2): 상반기, 하반기" in p.text
        assert "관찰 위치:" in p.text and "중간 샘플" in p.text


def test_csv_streaming_over_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "big.csv"
    path.write_text("a,b\n" + "".join(f"{i},x{i}\n" for i in range(1, 101)), encoding="cp949")
    monkeypatch.setattr(csv_file, "STREAM_THRESHOLD", 100)
    p = prof(path)
    assert p.inspected and "데이터 행 100" in p.text and "대용량: 행 수와 샘플만" in p.text
    assert "2행: 1 | x1" in p.text and "101행: 100 | x100" in p.text
    assert "범주값:" not in p.text


def test_xlsx(tmp_path: Path) -> None:
    write_xlsx(tmp_path / "a.xlsx")
    p = prof(tmp_path / "a.xlsx")
    assert p.inspected and "시트 1개: 집계" in p.text and "A1:C5" in p.text
    assert "머리글 병합 셀: A1:C1" in p.text and "수식 열: B(1), C(1)" in p.text and "합계·소계 행: 5행" in p.text


def test_ods(tmp_path: Path) -> None:
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table, TableCell, TableRow
    from odf.text import P

    doc = OpenDocumentSpreadsheet()
    t = Table(name="시트1")
    for row in (["구분", "값"], ["서울", "10"], ["합계", "10"]):
        tr = TableRow()
        for v in row:
            tc = TableCell(valuetype="string")
            tc.addElement(P(text=v))
            tr.addElement(tc)
        t.addElement(tr)
    doc.spreadsheet.addElement(t)
    doc.save(str(tmp_path / "a.ods"))
    p = prof(tmp_path / "a.ods")
    assert p.inspected and "ODS · 시트 1개: 시트1" in p.text and "(3행 × 2열)" in p.text


def test_pdf_text_pages(tmp_path: Path) -> None:
    write_pdf(tmp_path / "a.pdf", ("1. Overview of the survey procedure and scope", "Appendix text body is long enough"))
    p = prof(tmp_path / "a.pdf")
    assert p.inspected and "PDF · 2쪽 · 텍스트 확인 p1-p2 · 표 0개" in p.text
    assert "텍스트가 거의 없는 쪽 0/2" in p.text and "스캔" not in p.text
    assert "p1 상세:" in p.text and "1. Overview of the survey procedure and scope" in p.text
    assert p.inspected_locations == ["p1-2 상세(첫 5줄·금액 범위·합계 줄·단위/기준일)"]


def test_pdf_scan_detected(tmp_path: Path) -> None:
    write_pdf(tmp_path / "s.pdf", ("x", "y"))
    assert "스캔 PDF로 보임" in prof(tmp_path / "s.pdf").text


def test_pdf_layout_cells_excluded(tmp_path: Path) -> None:
    """행 4 이하 & 열 2 이하 또는 1열짜리 표는 표 목록에서 빼고 개수만 남긴다. 글자는 쪽 텍스트에 남는다."""
    write_pdf_table(tmp_path / "cover.pdf", "Financial statements cover page", ["Period", "Year 16"], [["From", "2025-01-01"]])
    p = prof(tmp_path / "cover.pdf")
    assert "표 0개" in p.text and "레이아웃 칸 1개 제외" in p.text
    assert "Period" in p.text  # 칸 안의 글자는 쪽 첫 줄 목록에 남음


def test_pdf_page_facts() -> None:
    from ksco_qa.profiler.pdf import _page

    text = "2026. 9. 업무추진비 사용내역\n(단위 : 원)\n'26.03.31.현재\n합      계 1,234,000\n연번 2,000"
    page, tables = _page(1, text, [[["구분", "금액"], ["가", "1,000"], [None, "2,000"]]])
    assert page.amount_range == (2000.0, 1234000.0)
    assert page.has_total_line and page.notes == ["(단위 : 원)", "'26.03.31.현재"]
    assert tables[0].merged and tables[0].n_rows == 3


def _pdf_model(n_pages: int, table_sizes: dict[int, tuple[int, int]]):
    """table_sizes: 쪽 → (행, 열)."""
    from ksco_qa.profiler.doc_model import DocTable
    from ksco_qa.profiler.pdf import PdfModel, PdfPage, PdfTable

    pages, tables = [], []
    for no in range(1, n_pages + 1):
        page = PdfPage(no, [f"p{no} 제목줄"] + [f"p{no} 줄{i} " + "가" * 60 for i in range(1, 6)],
                       (1000.0, 2000.0), False, [], False)
        if no in table_sizes:
            r, c = table_sizes[no]
            page.table_ids.append(len(tables))
            rows = [["과 목"] + [f"머리{k}" for k in range(1, c)]] + \
                   [[f"과목{no}-{i}"] + [f"{i},000"] * (c - 1) for i in range(1, r)]
            tables.append(PdfTable(no, DocTable(rows, 0)))
        pages.append(page)
    return PdfModel(n_pages, pages, tables)


def test_pdf_detail_priority_by_table_cells() -> None:
    m = _pdf_model(8, {2: (32, 5), 4: (32, 5), 7: (37, 5), 6: (7, 4)})
    assert m.detail_priority() == [7, 2, 4, 6]
    assert _pdf_model(5, {}).detail_priority() == [1, 2, 3, 4, 5]
    assert _pdf_model(20, {}).detail_priority() == [1, 10, 20, 2, 11, 19]


def test_pdf_table_extracted_with_serial_column(tmp_path: Path) -> None:
    write_pdf_table(tmp_path / "t.pdf", "Card usage", ["No", "Place", "Amount"],
                    [["1", "Cafe A", "144,000"], ["2", "Hall B", "22,300"], ["3", "Shop C", "462,000"]])
    p = prof(tmp_path / "t.pdf")
    assert "표 1개" in p.text and "레이아웃 칸" not in p.text
    assert "p1 상세: Card usage\n  표1 4×3 · 머리글: No | Place | Amount" in p.text
    assert "표1 행 라벨: 2열, 1열 연번(3): Cafe A, Hall B, Shop C" in p.text
    assert "표1 2행: 1 | Cafe A | 144,000" in p.text and "표1 3행: 2 | Hall B | 22,300" in p.text
    assert "표1 4행" not in p.text  # 데이터 앞 2행만
    assert "금액 범위 22,300~462,000" in p.text
    assert p.text.count("4×3") == 1  # 표 크기는 한 번만
    assert p.inspected_locations == [
        "p1 상세(첫 5줄·금액 범위·합계 줄·단위/기준일, 표 크기·머리글·행 라벨 최대 15개·앞 2행)"]


def test_pdf_continuation_pages() -> None:
    """첫 줄이 앞 쪽 표 머리글과 같거나 이 쪽 표 머리글로 바로 시작하면 '표 이어짐', 우선순위는 뒤로."""
    m = _pdf_model(8, {2: (32, 5), 3: (29, 5), 4: (32, 5), 7: (37, 5)})
    m.pages[2].lines[0] = "과 목  머리1 머리2 머리3 머리4"  # p3: 머리글 줄로 시작
    assert m.continues_from(3) == 2 and m.continues_from(4) is None and m.continues_from(2) is None
    assert m.detail_priority() == [7, 2, 4, 3]
    assert m.continuation_group(0) == [0, 1]
    assert m.merged_table(0).n_rows == 60  # repeated page header is counted once
    assert m.expand_detail({2}) == {2, 3}
    from ksco_qa.profiler.pdf import render

    text, _ = render(m, {7}, True, 1, 1)
    assert "p3: (p2 표 이어짐) · 표2 29×5 · 머리글: 과 목 | 머리1 | 머리2 …+2칸" in text


def test_pdf_reduction_order_and_locations() -> None:
    """비상세 쪽 머리글 3칸 → 데이터 행 2→1 → 첫 줄 5→3→1 → 행 라벨 15→8 → 상세 쪽 수(맨 마지막)."""
    from ksco_qa.profiler.pdf import render

    m = _pdf_model(8, {2: (32, 5), 4: (32, 5), 7: (37, 5)})
    all3 = {7, 2, 4}
    steps = [
        render(m, all3, True, 2, 5, 15), render(m, all3, True, 1, 5, 15), render(m, all3, True, 1, 3, 15),
        render(m, all3, True, 1, 1, 15), render(m, all3, True, 1, 1, 8), render(m, {7, 2}, True, 1, 1, 8),
    ]
    lengths = [len(t) for t, _ in steps]
    assert lengths == sorted(lengths, reverse=True)
    for t, loc in steps:
        assert m.fit_to(len(t)) == (t, loc)
    last_all3, loc = steps[4]
    assert loc[0] == "p2, 4, 7 상세(첫 1줄·금액 범위·합계 줄·단위/기준일, 표 크기·머리글·행 라벨 최대 8개·앞 1행)"
    assert "표2 2행" in last_all3 and "표2 3행" not in last_all3 and "외 23개" in last_all3
    two, loc2 = steps[5]
    assert loc2 == ["p2, 7 상세(첫 1줄·금액 범위·합계 줄·단위/기준일, 표 크기·머리글·행 라벨 최대 8개·앞 1행)",
                    "p1, 3-6, 8 첫 줄, 표 크기·머리글 (머리글 앞 3칸)"]
    assert "p4: p4 제목줄 · 표2 32×5 · 머리글: 과 목 | 머리1 | 머리2 …+2칸" in two  # 상세 쪽 밖 표
    assert "  표3 37×5 · 머리글: 과 목 | 머리1 | 머리2 | 머리3 | 머리4" in two  # 상세 쪽 표는 전체
    for kept in ("PDF · 8쪽", "표1 32×5", "표2 32×5", "표3 37×5", "관찰 위치:"):
        assert kept in two
    assert two.count("32×5") == 2 and two.count("37×5") == 1  # 표 크기는 한 번만


@pytest.mark.parametrize("header, values, serial", [
    ("연번", ["7", "8"], True), ("No.", ["a"], True), ("순 번", [], True),
    ("구분", ["1", "2", "3", "4", "x"], True), ("구분", ["1", "2", "x", "y"], False), ("과목", ["자산", "부채"], False),
])
def test_serial_column_rule(header: str, values: list[str], serial: bool) -> None:
    from ksco_qa.profiler.doc_model import is_serial_column

    assert is_serial_column(header, values) is serial


def test_row_labels_skip_serial_and_date_up_to_third_column() -> None:
    from ksco_qa.profiler.doc_model import DocTable, row_labels

    rows = [["연번", "일시", "장소", "금액"], ["1", "2026-09-02 12:00", "식당A", "1,000"], ["2", "2026-09-01", "식당B", "2,000"]]
    labels = row_labels(DocTable(rows, 0))
    assert (labels.columns[0], labels.values) == (2, ["식당A", "식당B"])
    assert labels.describe() == "행 라벨: 3열, 1열 연번·2열 날짜"
    rows = [["번호", "일자", "일시"], ["1", "2026-01-01", "2026-01-02"]]
    assert row_labels(DocTable(rows, 0)).values == []  # 3번째 열까지 모두 연번·날짜 → 라벨 없음
    rows = [["과 목", "금액"], ["자산", "1"], ["부채", "2"]]
    assert row_labels(DocTable(rows, 0)).describe() == "첫 열"


def test_row_labels_keep_spaced_subtotal_marked() -> None:
    """회귀 (2026-10-26): "지역본부 계"를 빼면 G0가 프로필에 없는 항목으로 보고 grounding 오판 → "(소계)"로 남긴다."""
    from ksco_qa.profiler.doc_model import DocTable, row_labels
    rows = [["구 분", "수 량"], ["총 계", "1,266"], ["본 사", "375"], ["지역본부 계", "891"],
            ["서울지역본부", "120"], ["회계팀", "5"], ["소 계", "10"]]
    labels = row_labels(DocTable(rows, 0))
    assert labels.values == ["본 사", "지역본부 계(소계)", "서울지역본부", "회계팀"]  # 붙여 쓴 "회계"는 소계 아님
    assert labels.has_total  # 총 계·소 계는 그대로 합계 행


def test_xlsx_row_labels(tmp_path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["순번", "기관", "금액"])
    for i, name in enumerate(["가기관", "나기관", "다기관"], start=1):
        ws.append([i, name, i * 100])
    wb.save(tmp_path / "s.xlsx")
    p = prof(tmp_path / "s.xlsx")
    assert "행 라벨: 2열, 1열 연번(3): 가기관, 나기관, 다기관 (머리글 1행 기준)" in p.text


def test_odt_table(tmp_path: Path) -> None:
    from odf.opendocument import OpenDocumentText
    from odf.table import Table, TableCell, TableColumn, TableRow
    from odf.text import H, P

    doc = OpenDocumentText()
    doc.text.addElement(H(outlinelevel=1, text="제1장 개요"))
    doc.text.addElement(P(text="(단위 : 원)"))
    table = Table(name="t1")
    table.addElement(TableColumn(numbercolumnsrepeated=3))
    for row in (["구 분", "예산", "결산"], ["인건비", "100", "90"], ["운영비", "50", "40"], ["사업비", "30", "20"],
                ["합계", "180", "150"]):
        tr = TableRow()
        for v in row:
            tc = TableCell()
            tc.addElement(P(text=v))
            tr.addElement(tc)
        table.addElement(tr)
    doc.text.addElement(table)
    doc.save(str(tmp_path / "a.odt"))
    t = prof(tmp_path / "a.odt").text
    assert t.startswith("ODT · 제목: 제1장 개요 · 문단 2 · 표 1")
    assert "표1 (문단 2 다음) 5행 × 3열\n  머리글: 구 분 | 예산 | 결산\n  첫 열(3): 인건비, 운영비, 사업비 · 합계 행 있음" in t


def test_title_rows_and_header_continuation() -> None:
    """제목 행(단위·절반 이상 빈칸·행 전체 병합) 최대 3행 건너뜀, "금 액 | 금 액"은 머리글 이어짐."""
    from ksco_qa.profiler.doc_model import DocTable, row_labels, table_layout

    rows = [
        ["가상공사", "(단위 : 원)"],
        ["과        목", "제21(당)기", "제20(전)기"],
        ["금      액", "금      액"],
        ["", "", "자산", "", "", ""],
        ["Ⅰ.", "유동자산", "", "", "213,098", "216,448"],
        ["(1)", "당좌자산", "", "", "50,935", "35,761"],
        ["", "1.", "현금및현금성자산", "(주석3)", "46,729", "6,625"],
        ["", "2.", "단기금융상품", "", "-", "3,000"],
        ["", "", "자산총계", "", "300,000", "250,000"],
        ["Ⅱ. 비유동자산", "", "", "", "86,000", "33,000"],
    ]
    t = DocTable(rows, 0)
    layout = table_layout(t)
    assert (layout.title_rows, layout.header, layout.data_start) == ([0], 1, 3)
    assert layout.title_text(t) == "가상공사 (단위 : 원)"
    labels = row_labels(t)
    # 상위 우선: 1단계(Ⅰ.) → 2단계(1.) → 3단계((1)). "자산"은 번호가 없어 같은 열(3열)의 2단계로 추정
    assert labels.values == ["유동자산", "비유동자산", "자산", "현금및현금성자산", "단기금융상품", "당좌자산"]
    assert labels.has_total and (labels.top_level, labels.top_level_count) == (1, 2)
    assert labels.describe().startswith("행 라벨: 1-3열")


@pytest.mark.parametrize("text, level", [
    ("Ⅰ.", 1), ("Ⅱ. 매출원가", 1), ("IV.", 1), ("1.", 2), ("12) 기타", 2), ("(1)", 3), ("( 2 ) 당좌자산", 3),
    ("가.", 4), ("(나)", 4), ("①", 4), ("유동자산", None),
])
def test_numbering_level(text: str, level: int | None) -> None:
    from ksco_qa.profiler.doc_model import numbering_level

    assert numbering_level(text) == level


def test_top_level_labels_first_and_all_shown() -> None:
    """상위 우선: 1단계 전부 → 2단계 …, 같은 단계는 원래 순서. 1단계는 개수 제한을 넘어도 전부."""
    from ksco_qa.profiler.doc_model import DocTable, labels_line

    rows = [["과 목", "", "당기", "전기"]]
    for i, top in enumerate(["매출액", "매출원가", "매출총이익", "판매비와관리비", "영업이익",
                             "영업외수익", "영업외비용", "법인세차감전순이익", "법인세비용", "당기순이익"]):
        rows.append([f"{'ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ'[i]}.", top, "1,000", "900"])
        rows.append(["", f"1. {top} 세부", "100", "90"])
    line = labels_line(DocTable(rows, 0), 8)
    assert line.startswith("  행 라벨(상위 우선): 2열, 1열 번호 · 1단계 10/20: 매출액, 매출원가,")
    assert "영업이익" in line and "당기순이익 외 10개" in line and "세부" not in line


def test_single_level_numbering_keeps_original_order() -> None:
    from ksco_qa.profiler.doc_model import DocTable, row_labels

    rows = [["구분", "내용"], ["① 접수", "a"], ["② 검토", "b"], ["③ 결재", "c"]]
    labels = row_labels(DocTable(rows, 0))
    assert labels.values == ["접수", "검토", "결재"] and not labels.leveled


def test_brief_table_title_lookup() -> None:
    """비상세 표 제목: 위로 최대 3문단 안 제목 패턴, 기간·기준일 줄은 건너뜀."""
    from ksco_qa.profiler.doc_model import DocModel, DocTable, table_title

    paragraphs = ["(2) 손익계산서", "손익계산서", "당기(제21기) 2024년 1월 1일부터 2024년 12월 31일까지",
                  "전기(제20기) 2023년 1월 1일부터 2023년 12월 31일까지", "본문 설명", "(단위 : 원)", "2024년 12월 31일 현재"]
    t1, t2, t3 = DocTable([["a", "b"], ["c", "d"]], 4), DocTable([["a", "b"], ["c", "d"]], 7), DocTable([["a"]], 0)
    m = DocModel("HWPX", "제목", paragraphs, [t1, t2, t3])
    assert table_title(m, t1) == "손익계산서"  # 기간 줄 2개를 건너뛰고 "~계산서"
    assert table_title(m, t2) is None  # 3문단 안에 제목 패턴 없음
    assert table_title(m, t3) is None


def test_numbering_column_and_full_span_title() -> None:
    from ksco_qa.profiler.doc_model import DocTable, labels_line, row_labels, table_layout

    rows = [["재 무 상 태 표", "", ""], ["순번", "과목", "금액"], ["①", "인건비", "100"], ["②", "운영비", "50"], ["③", "소계", "150"]]
    t = DocTable(rows, 0, full_span_rows={0})
    assert table_layout(t).header == 1
    labels = row_labels(t)
    assert labels.values == ["인건비", "운영비"] and labels.has_total
    assert labels.describe() == "행 라벨: 2열, 1열 연번"
    assert labels_line(t, 15) == "  행 라벨: 2열, 1열 연번(2): 인건비, 운영비 · 합계 행 있음"
    numbered = DocTable([["구분", "금액"], ["가.", "10"], ["나.", "20"], ["다.", "30"], ["라.", "40"], ["", "50"]], 0)
    assert row_labels(numbered).skipped == ["1열 번호"]


def test_duplicate_header_tables_marked_with_previous_paragraph() -> None:
    from ksco_qa.profiler.doc_model import DocTable, build_doc_model

    big = [["구  분", "내      용"]] + [[f"업종{i}", "내용"] for i in range(6)]
    blocks = [("p", "ㅇ첫 업종"), ("t", DocTable([r[:] for r in big], 0)),
              ("p", "ㅇ둘째 업종"), ("t", DocTable([["구   분", "내      용"]] + big[1:], 0))]
    text, _ = build_doc_model("HWPX", blocks).fit_to(1500)
    assert "표1 (문단 1 다음) 7행 × 2열 · 앞 문단: ㅇ첫 업종" in text
    assert "표2 (문단 2 다음) 7행 × 2열 · 앞 문단: ㅇ둘째 업종" in text


def test_extension_mismatch(tmp_path: Path) -> None:
    (tmp_path / "fake.hwpx").write_bytes(bytes.fromhex("d0cf11e0a1b11ae1") + b"\0" * 100)
    (tmp_path / "fake.docx").write_bytes(b"plain text, not a zip")
    h, d = prof(tmp_path / "fake.hwpx"), prof(tmp_path / "fake.docx")
    assert (h.inspected, h.warning) == (False, "EXTENSION_MISMATCH")
    assert h.error == "EXTENSION_MISMATCH: 확장자는 .hwpx인데 zip 형식이 아님 (실제 형식: HWP 구버전 추정)"
    assert d.warning == "EXTENSION_MISMATCH" and "실제 형식: 알 수 없음" in d.error


def test_hwpx_card_profile(tmp_path: Path) -> None:
    write_hwpx_card(tmp_path / "card.hwpx")
    p = prof(tmp_path / "card.hwpx")
    t = p.text
    assert t.startswith("HWPX · 제목: 가상기관 법인카드 관리현황 · 문단 11 · 표 4")
    assert "레이아웃 칸 1개 제외" in t  # 제목 상자(1열)만. 2열 업종 표는 데이터 표
    assert p.inspected_locations == ["문단 1-11 (각 80자)", "표1-4 머리글·행 라벨·앞 2행"]
    assert "문단 2: '26.03.31.현재" in t and "문단 4: (단위 : 매)" in t
    assert "표1 (문단 4 다음) 5행 × 2열\n  머리글: 구    분 | 수 량" in t  # 머리글 공백 원문 그대로
    assert "첫 열(3): 본 사, 지역본부 계(소계), 서울지역본부 · 합계 행 있음" in t  # 총 계만 합계 행, 소계는 표시해 남김
    assert "표2 (문단 6 다음) 6행 × 2열 · 병합 셀 있음 · 앞 문단: ㅇ카드사용 의무적 제한 업종" in t
    assert "표3 (문단 8 다음) 3행 × 2열 · 앞 문단: ㅇ카드사용 금지 업종\n  머리글: 구   분 | 내      용" in t
    assert "표4 (문단 10 다음) 2행 × 2열 · 앞 문단: ㅇ카드사용 제한 업종" in t


def test_docx_card_profile(tmp_path: Path) -> None:
    write_docx_card(tmp_path / "card.docx")
    t = prof(tmp_path / "card.docx").text
    assert t.startswith("DOCX · 제목: 가상기관 법인카드 관리현황 · 문단 7 · 표 4")
    assert "레이아웃 칸" not in t
    assert "표1 (문단 4 다음) 5행 × 2열\n  머리글: 구    분 | 수 량" in t
    assert "표2 (문단 5 다음) 6행 × 2열 · 앞 문단: ㅇ카드사용 의무적 제한 업종\n  머리글: 구  분 | 내      용\n  첫 열(5): 유흥업종" in t
    assert "표3 (문단 6 다음) 3행 × 2열 · 앞 문단: ㅇ카드사용 금지 업종" in t


def test_layout_rules_by_format() -> None:
    """문서형: 1열 또는 1행(숫자 절반 이상이면 예외)만. PDF: 행 4 이하 & 열 2 이하, 1열, 1행."""
    from ksco_qa.profiler.doc_model import DocTable, is_doc_layout_cell, is_pdf_layout_cell

    def t(r: int, c: int, value: str = "x") -> DocTable:
        return DocTable([[value] * c for _ in range(r)], 0)

    assert is_doc_layout_cell(t(1, 3)) and is_doc_layout_cell(t(30, 1))
    assert not is_doc_layout_cell(t(4, 2)) and not is_doc_layout_cell(t(2, 2)) and not is_doc_layout_cell(t(5, 3))
    assert not is_doc_layout_cell(DocTable([["1,234", "(5,000)", "-300", "합계"]], 0))  # 1행이라도 절반 이상 숫자
    assert is_pdf_layout_cell(t(4, 2)) and is_pdf_layout_cell(t(1, 1)) and is_pdf_layout_cell(t(1, 5))
    assert not is_pdf_layout_cell(t(5, 2)) and not is_pdf_layout_cell(t(2, 3))
    assert not is_pdf_layout_cell(DocTable([["1,234", "(5,000)", "300"]], 0))


def test_title_repeats_collapsed() -> None:
    from ksco_qa.profiler.doc_model import DocTable, build_doc_model, collapse_repeats

    assert collapse_repeats("3. 재 무 제 표 3. 재 무 제 표 (가상공사) 목차") == "3. 재 무 제 표 (가상공사) 목차"
    assert collapse_repeats("법인카드 현황") == "법인카드 현황"
    m = build_doc_model("HWPX", [("t", DocTable([["3. 재 무 제 표 3. 재 무 제 표"]], 0)), ("p", "본문")])
    assert m.title == "3. 재 무 제 표"


def _doc_model(n_paragraphs: int = 30):
    from ksco_qa.profiler.doc_model import DocModel, DocTable

    paragraphs = [f"문단내용{i} " + "가" * 90 for i in range(1, n_paragraphs + 1)]
    paragraphs[14] = "(2) 작은 표 제목"
    rows = [["구  분", "내 용", "비고", "기타"]] + [[f"라벨{i}", "값 " + "나" * 50, "", ""] for i in range(20)]
    small = [["항목", "당기", "전기", "증감"]] + [[f"작은{i}", "1", "2", "3"] for i in range(5)]
    return DocModel("HWPX", "제목", paragraphs, [DocTable(rows, 10), DocTable(small, 15), DocTable(rows, 20)])


def test_document_reduction_order() -> None:
    """비상세 머리글 3칸 → 데이터 행 → 문단 80→40 → 행 라벨 15→8 → 비보호 문단
    → 비상세 머리글 생략 → 비상세 앞 문단 제목 생략 → 상세 표 수(맨 마지막)."""
    from ksco_qa.profiler.doc_model import _fit_with_paragraphs, fit_document, render

    m = _doc_model()
    everything = set(range(1, 31))
    all3 = {0, 1, 2}
    assert m.detail_priority() == [0, 2, 1]
    steps = [render(m, all3, "short", *lv, everything)[0]
             for lv in ((2, 80, 15), (1, 80, 15), (1, 40, 15), (1, 40, 8))]
    assert [len(s) for s in steps] == sorted((len(s) for s in steps), reverse=True)
    assert fit_document(m, len(steps[1]))[0] == steps[1]
    assert fit_document(m, len(steps[2]))[1][0] == "문단 1-30 (각 40자)"
    assert fit_document(m, len(steps[3]))[0] == steps[3] and "외 12개" in steps[3]

    level = (1, 40, 8)
    short_title, _, _ = _fit_with_paragraphs(m, {0, 2}, "short", True, level, 10_000)
    none_title, _, _ = _fit_with_paragraphs(m, {0, 2}, "none", True, level, 10_000)
    none_none, _, _ = _fit_with_paragraphs(m, {0, 2}, "none", False, level, 10_000)
    assert "표2 6×4 · (2) 작은 표 제목 · 머리글: 항목 | 당기 | 전기 …+1칸" in short_title
    assert "표2 6×4 · (2) 작은 표 제목\n" in none_title  # 머리글 먼저 생략, 앞 문단 제목은 남김
    assert "표2 6×4\n" in none_none  # 그다음 제목 생략


def test_document_header_then_title_dropped_before_detail_count() -> None:
    from ksco_qa.profiler.doc_model import DocModel, DocTable, fit_document

    big = [["과 목", "당기", "전기"]] + [[f"과목{i}", "1,000", "2,000"] for i in range(30)]
    small = [["구 분", "기 초", "취 득", "처 분", "기 말"]] + [["토지", "1", "2", "3", "4"]]
    paragraphs, tables = [], []
    for i in range(2):
        paragraphs.append(f"({i + 1}) 큰 표 {i + 1}")
        tables.append(DocTable([r[:] for r in big], len(paragraphs)))
    for i in range(30):
        paragraphs.append(f"가. 작은 표 제목 {i + 1} (단위 : 원) 설명이 조금 길게 붙어 있다")
        tables.append(DocTable([r[:] for r in small], len(paragraphs)))
    m = DocModel("HWPX", "재무제표", paragraphs, tables)
    text, loc = fit_document(m, 1500)
    assert len(text) <= 1500
    assert "표1 (문단 1 다음)" in text and "표2 (문단 2 다음)" in text  # 큰 표 2개는 상세로 남는다
    import re

    briefs = re.findall(r"^표\d+ 2×5.*$", text, re.M)
    assert briefs and all(re.fullmatch(r"표\d+ 2×5", b) for b in briefs)  # 비상세 표는 크기만 (머리글·제목 생략)
    assert loc[-1].endswith(" 크기")


def test_document_truncation_locations_match_text() -> None:
    """끝까지 넘쳐 줄 단위로 자를 때도 관찰 위치는 실제로 남은 문단·표만 적는다."""
    import re

    from ksco_qa.profiler.doc_model import DocModel, DocTable, fit_document

    rows = [["과 목", "금액", "비고"]] + [[f"항목{i}", "1", ""] for i in range(5)]
    m = DocModel("HWPX", "제목", [f"문단{i}" for i in range(1, 41)], [DocTable(rows, i) for i in range(1, 41)])
    text, loc = fit_document(m, 300)
    assert len(text) <= 300 and loc[-1] == "이후 생략"
    shown_detail = [int(x) for x in re.findall(r"^표(\d+) \(", text, re.M)]
    shown_brief = [int(x) for x in re.findall(r"^표(\d+) \d+×\d+", text, re.M)]
    shown_paras = [int(x) for x in re.findall(r"^문단 (\d+):", text, re.M)]
    assert shown_detail == [1]
    if shown_paras:
        assert loc[0].startswith("문단 ")
    if shown_brief:
        assert any(l.startswith("표") and l.endswith(" 크기") for l in loc)
    assert f"관찰 위치: {', '.join(loc)}" in text


def test_pptx_locations_only_included_slides(tmp_path: Path) -> None:
    from ksco_qa.profiler.pptx_file import PptxModel

    write_pptx(tmp_path / "a.pptx")
    p = prof(tmp_path / "a.pptx")
    assert "s1: 부서별 실적 [표]" in p.text and p.inspected_locations == ["슬라이드 1-2 제목·표/도표 여부"]
    m = PptxModel([f"s{i}: 제목{i} " + "가" * 40 for i in range(1, 31)], 0, 0)
    text, loc = m.fit_to(600)
    k = int(loc[0].split("-")[1].split(" ")[0])
    assert len(text) <= 600 and f"s{k}:" in text and f"s{k + 1}:" not in text and f"(슬라이드 {k + 1}-30 미포함)" in text


def test_json_xml_html(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text('[{"id": 1, "v": "a"}, {"id": 2, "v": "b"}, {"id": 3, "w": "c"}]', encoding="utf-8")
    (tmp_path / "a.xml").write_text("<r><w><item n='1'><x>1</x></item><item n='2'><x>2</x></item></w></r>", encoding="utf-8")
    (tmp_path / "a.html").write_text("<html><title>T</title><h1>A</h1><table><tr><th>k</th><th>v</th></tr></table></html>",
                                     encoding="cp949")
    j, x, h = prof(tmp_path / "a.json"), prof(tmp_path / "a.xml"), prof(tmp_path / "a.html")
    assert "레코드 배열 $: 3건 · 필드 3: id, v, w" in j.text
    assert "반복 요소 <item> 2건 (부모 <w>)" in x.text and "@n, x" in x.text
    assert "제목: T" in h.text and "표1 머리글: k | v" in h.text


def test_not_inspected_cases(tmp_path: Path) -> None:
    (tmp_path / "a.hwp").write_bytes(b"HWP")
    (tmp_path / "a.xyz").write_bytes(b"?")
    (tmp_path / "bad.pdf").write_bytes(b"%PDF-1.4 broken")
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    hwp, unknown, bad_pdf, bad_json = (prof(tmp_path / n) for n in ("a.hwp", "a.xyz", "bad.pdf", "bad.json"))
    assert (hwp.inspected, hwp.error) == (False, "HWP(구버전) 판독 도구 없음")
    assert unknown.inspected is False and "지원하지 않는 형식" in unknown.error
    assert bad_pdf.inspected is False and str(tmp_path) not in bad_pdf.error
    assert bad_json.inspected is False and "JSON 파싱 실패" in bad_json.error


def test_cache_by_content_hash(tmp_path: Path) -> None:
    write_csv(tmp_path / "a.csv", 2024)
    (tmp_path / "b.csv").write_bytes((tmp_path / "a.csv").read_bytes())
    cache = tmp_path / "cache"
    a = profile_file(tmp_path / "a.csv", "a.csv", cache)
    b = profile_file(tmp_path / "b.csv", "sub/b.csv", cache)
    assert len(list(cache.iterdir())) == 1
    assert a.text == b.text and b.locator == "sub/b.csv"


def test_combine_for_row() -> None:
    from ksco_qa.profiler.base import FileProfile

    text = combine_for_row([FileProfile("a.csv", "CSV", True, "본문"), FileProfile("b.hwp", "HWP", False, "", [], "사유")])
    assert text == "[파일] a.csv\n본문\n\n[파일] b.hwp\nNOT_INSPECTED: 사유"


def test_cp949_zip_member_name() -> None:
    info = zipfile.ZipInfo("보고서.csv".encode("cp949").decode("cp437"))
    info.flag_bits = 0
    assert member_display_name(info) == "보고서.csv"


def test_every_supported_extension_has_profiler() -> None:
    assert {"csv", "xlsx", "xls", "ods", "pdf", "hwpx", "docx", "odt", "pptx", "hwp", "json", "xml", "html"} <= set(PROFILERS)
