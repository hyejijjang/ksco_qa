"""파일 프로파일러 (설계 부록 B / M1 결정 11~14, JSON·XML·HTML 추가)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from fixtures.sample_task import write_csv, write_docx, write_hwpx, write_pdf, write_pptx, write_xlsx
from ksco_qa.profiler import PROFILERS, combine_for_row, profile_file, row_budget
from ksco_qa.profiler import csv_file
from ksco_qa.profiler.base import ProfileParts, fit, render
from ksco_qa.profiler.pdf import TABLE_TITLE_RE
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


def test_pdf(tmp_path: Path) -> None:
    write_pdf(tmp_path / "a.pdf", ("1. Overview of the survey procedure and scope", "Appendix text body is long enough"))
    p = prof(tmp_path / "a.pdf")
    assert p.inspected and "PDF · 2쪽 · 텍스트 확인 p1-p2" in p.text
    assert "텍스트가 거의 없는 쪽 0/2" in p.text and "스캔" not in p.text
    assert "p1: 1. Overview" in p.text


def test_pdf_scan_detected(tmp_path: Path) -> None:
    write_pdf(tmp_path / "s.pdf", ("x", "y"))
    assert "스캔 PDF로 보임" in prof(tmp_path / "s.pdf").text


@pytest.mark.parametrize("line, ok", [
    ("<표 3> 지역별 응답", True), ("[표 2-1] 집계", True), ("표 4. 연도별 현황", True), ("표준 절차", False),
])
def test_pdf_table_title_pattern(line: str, ok: bool) -> None:
    assert bool(TABLE_TITLE_RE.match(line)) is ok


def test_hwpx_docx(tmp_path: Path) -> None:
    write_hwpx(tmp_path / "a.hwpx")
    write_docx(tmp_path / "a.docx")
    h, d = prof(tmp_path / "a.hwpx"), prof(tmp_path / "a.docx")
    assert h.inspected and "표 1" in h.text and "1. 조사 개요" in h.text and "표1 머리글: 지역 | 응답 수" in h.text
    assert d.inspected and "결산 일정" in d.text and "표1 머리글: 서류 | 기한" in d.text


def test_odt(tmp_path: Path) -> None:
    from odf.opendocument import OpenDocumentText
    from odf.text import H, P

    doc = OpenDocumentText()
    doc.text.addElement(H(outlinelevel=1, text="제1장 개요"))
    doc.text.addElement(P(text="본문"))
    doc.save(str(tmp_path / "a.odt"))
    p = prof(tmp_path / "a.odt")
    assert p.inspected and "제1장 개요" in p.text


def test_pptx(tmp_path: Path) -> None:
    write_pptx(tmp_path / "a.pptx")
    p = prof(tmp_path / "a.pptx")
    assert p.inspected and "슬라이드 2" in p.text and "s1: 부서별 실적 [표]" in p.text


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
