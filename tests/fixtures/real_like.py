"""실제 accounting 파일 4개의 구조를 흉내 낸 작은 가상 fixture (실제 데이터 아님, 회귀 테스트용).

- 재무제표형 PDF (대구경북 재무제표 01형): 표지 레이아웃 칸, 재무상태표·손익계산서·현금흐름표가 각각
  다음 쪽으로 이어지는 큰 표, 자본변동표. 손으로 만든 PDF에서는 한글 텍스트를 추출할 수 없으므로
  pdfplumber가 돌려주는 형태(쪽별 텍스트 + extract_tables 결과)를 만들어 PDF 모델에 바로 넣는다.
- 업무추진비형 PDF (영등포구형): 연번 | 사용자 | 일시 | 장소 | … 표 2쪽.
- 결산현황형 HWPX (시흥도시공사형): 1행 제목 칸, 제목 행("(단위 : 원)")·머리글 이어짐("금 액 | 금 액")·
  병합으로 칸 수가 들쭉날쭉한 재무표, 주석의 작은 표 30여 개.
- 2열 "구 분 | 내 용" 표가 있는 HWPX는 sample_task.write_hwpx_card (법인카드형).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from ksco_qa.profiler.pdf import PdfModel, PdfTable, _page

# 손익계산서 1단계 (Ⅰ.~Ⅹ.)
INCOME_TOP = ["매출액", "매출원가", "매출총이익", "판매비와관리비", "영업이익",
              "영업외수익", "영업외비용", "법인세비용차감전순이익", "법인세비용", "당기순이익"]
BALANCE_TOP = ["유동자산", "비유동자산", "유동부채", "비유동부채", "자본금",
               "자본잉여금", "이익잉여금"]
CASHFLOW_TOP = ["영업활동으로 인한 현금흐름", "투자활동으로 인한 현금흐름", "재무활동으로 인한 현금흐름"]
ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"


# 실제 재무표와 비슷한 길이의 하위 계정 이름
SUB_ACCOUNTS = ["현금및현금성자산", "단기금융상품", "미수수익", "미수금", "대손충당금", "선급금", "선급비용",
                "당기법인세자산", "보조금수익", "출연금수익", "기부금수익", "수탁사업수익", "감가상각비",
                "무형자산상각비", "대손상각비", "급여", "퇴직급여", "복리후생비", "여비교통비", "지급수수료"]


def _statement_rows(
    tops: list[str], children: int, rows: int, cols: int = 5, start_level: int = 0,
) -> list[list[str | None]]:
    """PDF 재무표 행: 1단계 "Ⅰ. 이름" 다음에 하위 "1. 세부" 행들, 금액 칸."""
    out: list[list[str | None]] = [["과 목", "제 16(당) 기", None, "제 15(전) 기", None]]
    n = 0
    for i, top in enumerate(tops, start=start_level):
        out.append([f"{ROMAN[i]}. {top}", "", "12,345,678,901", "", "11,234,567,890"])
        for k in range(1, children + 1):
            out.append([f"{k}. {SUB_ACCOUNTS[n % len(SUB_ACCOUNTS)]}{n // len(SUB_ACCOUNTS) or ''}",
                        "1,234,567", "", "1,111,111", ""])
            n += 1
    while len(out) < rows:
        out.append([f"{SUB_ACCOUNTS[n % len(SUB_ACCOUNTS)]}{n // len(SUB_ACCOUNTS) or ''}", "100,000", "", "90,000", ""])
        n += 1
    return [r[:cols] for r in out[:rows]]


def financial_statement_pdf_model() -> PdfModel:
    """대구경북 재무제표 01형: 8쪽, 레이아웃 칸 7개, 재무표 3종이 각각 다음 쪽으로 이어짐."""
    pages, tables, excluded = [], [], 0
    cover = "(첨부)재 무 제 표\n재단법인 가상첨단산업진흥재단\n제 16 기\n2025년 01월 01일 부터\n2025년 12월 31일 까지"
    head = "과 목 제 16(당) 기 제 15(전) 기"
    spec = {
        1: (cover, [[["제 16 기", None], ["2025년 01월 01일", "부터"], ["2025년 12월 31일", "까지"]],
                    [["제 15 기", None], ["2024년 01월 01일", "부터"]], [["\"첨부된 재무제표는 당사가 작성한 것입니다.\""]],
                    [["본점 소재지 :", "(도로명주소)", "가상시 가상구 가상로 88"], ["", "(전 화)", "000-000-0000"]]]),
        2: ("재 무 상 태 표\n제16 기 2025년 12월 31일 현재\n(단위: 원)\n" + head,
            [[["재 무 상 태 표", None]], _statement_rows(BALANCE_TOP[:2], 15, 32)]),
        3: (head + "\n부채와 자본",
            [_statement_rows(BALANCE_TOP[2:], 3, 25, start_level=2)]),
        4: ("손 익 계 산 서\n제16 기 2025년 01월 01일부터 2025년 12월 31일까지\n(단위: 원)\n" + head,
            [[["손 익 계 산 서", None]], _statement_rows(INCOME_TOP[:5], 5, 32)]),
        5: (head + "\n영업외수익",
            [_statement_rows(INCOME_TOP[5:], 3, 21, start_level=5)]),
        6: ("자 본 변 동 표\n(단위: 원)", [[["자 본 변 동 표", None]],
                                       [["과 목", "자 본 금", "이 익 잉 여 금", "총 계"]] + [[f"항목{i}", "1", "2", "3"] for i in range(6)]]),
        7: ("현 금 흐 름 표\n제16 기 2025년 01월 01일부터 2025년 12월 31일까지\n(단위: 원)\n" + head,
            [[["현 금 흐 름 표", None]], _statement_rows(CASHFLOW_TOP, 9, 37)]),
        8: (head + "\n현금의 증가", [_statement_rows(["현금의 증가"], 5, 7)]),
    }
    from ksco_qa.profiler.doc_model import is_pdf_layout_cell

    for no in range(1, 9):
        text, raw_tables = spec[no]
        page, found = _page(no, text, raw_tables)
        for t in found:
            if is_pdf_layout_cell(t):
                excluded += 1
                continue
            page.table_ids.append(len(tables))
            tables.append(PdfTable(no, t))
        pages.append(page)
    return PdfModel(8, pages, tables, excluded)


def expense_pdf_model() -> PdfModel:
    """영등포구 업무추진비형: 연번 | 사용자 | 일시 | 장소 | 집행목적 | 대상 인원수 | 금액 | 결제방법 | 비목."""
    header = ["연번", "사용자", "일시", "장소", "집행목적", "대상\n인원수", "금액", "결제방법", "비목"]
    users = ["업무관계자", "기획예산과장", "업무담당자", "기획재정국장", "기획조정팀장"]
    pages, tables = [], []
    for no, (start, n) in enumerate([(1, 41), (42, 12)], start=1):
        rows = [header] + [[str(i), users[i % len(users)], "2026-09-02\n12:00", f"식당{i}", "간담회비 지급",
                            "8", f"{100 + i},000", "신용", "시책"] for i in range(start, start + n)]
        text = "2026. 9. 업무추진비 사용내역\n▣ 부서명: 가상과\n(단위 : 원)\n대상\n연번 사용자 일시 장소 집행목적 금액 결제방법 비목"
        page, found = _page(no, text, [rows])
        page.table_ids.append(len(tables))
        tables.append(PdfTable(no, found[0]))
        pages.append(page)
    return PdfModel(2, pages, tables)


# --- 결산현황형 HWPX ---

def _tc(text: str, col_span: int = 1) -> str:
    return (f"<hp:tc><hp:cellSpan colSpan='{col_span}' rowSpan='1'/><hp:subList><hp:p><hp:run>"
            f"<hp:t>{text}</hp:t></hp:run></hp:p></hp:subList></hp:tc>")


def _tbl(rows: list[list[tuple[str, int]]], col_count: int) -> str:
    trs = "".join("<hp:tr>" + "".join(_tc(t, s) for t, s in row) + "</hp:tr>" for row in rows)
    return f"<hp:p><hp:run><hp:tbl rowCnt='{len(rows)}' colCnt='{col_count}'>{trs}</hp:tbl></hp:run></hp:p>"


def _p(text: str) -> str:
    return f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"


def _settlement_table(tops: list[str], children: int, rows: int, cols: int) -> list[list[tuple[str, int]]]:
    """병합으로 행마다 칸 수가 다른 HWPX 재무표: 제목 행, 머리글, 머리글 이어짐, "Ⅰ." | 이름, "" | "1." | 이름."""
    out = [[("가상공사", 4), ("(단위 : 원)", cols - 4)],
           [("과        목", 4), ("제21(당)기", (cols - 4) // 2), ("제20(전)기", cols - 4 - (cols - 4) // 2)],
           [("금      액", (cols - 4) // 2), ("금      액", cols - 4 - (cols - 4) // 2)]]
    for i, top in enumerate(tops):
        out.append([(f"{ROMAN[i]}.", 1), (top, 3), ("", 1), ("121,072,952,970 ", 1)] + [("", 1)] * (cols - 6))
        for k in range(1, children + 1):
            out.append([("", 1), (f"{k}.", 1), (f"{top}세부{k}", 1), ("", 1), ("61,283,369,312 ", 1)] + [("", 1)] * (cols - 5))
    while len(out) < rows:
        out.append([("", 1)] * cols)
    return out[:rows]


def write_settlement_hwpx(path: Path) -> None:
    """시흥도시공사 결산현황형: 재무상태표 84×8, 손익계산서 66×9, 현금흐름표 56×10, 주석 작은 표 30개."""
    body = [_tbl([[("3. 재 무 제 표 3. 재 무 제 표 (가상공사) (1)-재무상태표(2)-손익계산서", 1)]], 1)]
    for no, name, tops, children, rows, cols in (
        (1, "재무상태표", BALANCE_TOP, 4, 84, 8),
        (2, "손익계산서", INCOME_TOP, 3, 66, 9),
        (3, "현금흐름표", CASHFLOW_TOP, 5, 56, 10),
    ):
        body.append(_tbl([[(f"({no})", 1), ("", 1), (name, 1)]], 3))  # 1행 제목 칸 → 레이아웃
        body += [_p(f"({no}) {name}"), _p(name), _p("당기(제21기) 2024년 1월 1일부터 2024년 12월 31일까지"),
                 _p("전기(제20기) 2023년 1월 1일부터 2023년 12월 31일까지")]
        body.append(_tbl(_settlement_table(tops, children, rows, cols), cols))
    for i in range(1, 31):
        body.append(_p(f"({i}) 주석 항목 {i}에 대한 설명 문단입니다"))
        body.append(_p("(단위 : 원)"))
        body.append(_tbl([[("구 분", 1), ("기 초", 1), ("취 득", 1), ("처 분", 1), ("기 말", 1)],
                          [("토지", 1), ("1", 1), ("2", 1), ("3", 1), ("4", 1)],
                          [("건물", 1), ("5", 1), ("6", 1), ("7", 1), ("8", 1)]], 5))
    ns = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'
    section = (f'<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" {ns}>'
               + "".join(body) + "</hs:sec>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", section)


# --- Work 결과 (가상) ---

WORK_RESULT_COLUMNS = ["id", "AI 판정", "최종 판정", "Regenerate Task", "원본 Task(백업)", "검수 메모"]


def work_result_rows() -> list[dict[str, str]]:
    """KSCO-33_work_result.csv와 같은 열 구조의 가상 Work 결과 (값의 어휘는 실제와 다를 수 있음)."""
    return [
        {"id": "T-001", "AI 판정": "가상판정A", "최종 판정": "가상판정A", "Regenerate Task": "",
         "원본 Task(백업)": "월별 매출 거래 자료를 받아 …", "검수 메모": "가상 메모 1"},
        {"id": "T-002", "AI 판정": "가상판정B", "최종 판정": "가상판정C", "Regenerate Task": "가상 재생성 Task",
         "원본 Task(백업)": "2023년 월별 매출 …", "검수 메모": ""},
        {"id": "T-003", "AI 판정": "", "최종 판정": "", "Regenerate Task": "", "원본 Task(백업)": "", "검수 메모": ""},
    ]


def write_work_result_csv(path: Path, encoding: str = "utf-8-sig") -> None:
    import csv

    with open(path, "w", encoding=encoding, newline="") as f:
        w = csv.DictWriter(f, fieldnames=WORK_RESULT_COLUMNS)
        w.writeheader()
        w.writerows(work_result_rows())
