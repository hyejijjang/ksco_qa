"""P0 — 사전 검사·매핑·row_card (설계 5.1, 7.1 / M1 결정 1~10, KSCO-28 추가 규칙)."""

from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

import openpyxl
import pytest

from fixtures.sample_task import DATA_ROWS, EXPECTED, LEAK_MARK, TASK_NAME, build_sample_task
from ksco_qa.config import Config
from ksco_qa.p0 import (
    MAPPING_AUDIT_COLUMNS,
    ROW_CARD_FIELDS,
    InventoryEntry,
    P0Stop,
    build_index,
    build_inventory,
    classify_reference,
    job_leaf,
    jobinfo_warnings,
    match_deliverable,
    parse_formats,
    run_p0,
)


@pytest.fixture
def p0(sample_task: Path, tmp_path: Path):
    return run_p0(sample_task, Config(), tmp_path / "run", tmp_path / "audit.csv"), tmp_path


def by_id(result) -> dict[str, tuple[dict, dict]]:
    return {c["id"]: (c, r) for c, r in zip(result.row_cards, result.records)}


def test_every_fixture_row_as_expected(p0) -> None:
    result, _ = p0
    rows = by_id(result)
    assert set(rows) == set(EXPECTED)
    for rid, (status, inspected, warnings) in EXPECTED.items():
        card, rec = rows[rid]
        assert (card["match_status"], card["inspected"]) == (status, inspected), rid
        assert warnings <= set(rec["warnings"]), rid


def test_data_rows_and_counts(p0) -> None:
    """교훈 #6: 체크박스만 있는 행은 데이터 행이 아니다. 완료 조건: 행 수 = row_card 수 = audit 행 수."""
    result, tmp = p0
    assert [c["source_row"] for c in result.row_cards] == list(range(2, 2 + DATA_ROWS))
    with open(tmp / "audit.csv", encoding="utf-8-sig", newline="") as f:
        audit = list(csv.DictReader(f))
    assert len(audit) == DATA_ROWS and tuple(audit[0]) == MAPPING_AUDIT_COLUMNS
    for name in ("row_cards.jsonl", "source_cells.jsonl", "p0/records.jsonl"):
        assert len((tmp / "run" / name).read_text(encoding="utf-8").splitlines()) == DATA_ROWS


def test_row_card_has_only_design_fields_and_no_previous_qa(p0) -> None:
    """KSCO-28 추가 규칙: 이전 검수 결과 열(R~V)·O·L·M열은 절대 모델 입력에 넣지 않는다."""
    result, tmp = p0
    for card in result.row_cards:
        assert tuple(card) == ROW_CARD_FIELDS
        text = json.dumps(card, ensure_ascii=False)
        assert LEAK_MARK not in text
        assert "개인태그" not in text and "원본 링크" not in text and "example.com" not in text
    row_cards_text = (tmp / "run" / "row_cards.jsonl").read_text(encoding="utf-8")
    assert LEAK_MARK not in row_cards_text


def test_row_card_has_no_task_name_or_absolute_path(p0, sample_task: Path) -> None:
    from ksco_qa.llm.client import _DRIVE_PATH_RE

    result, _ = p0
    values = [str(v) for card in result.row_cards for v in card.values() if v is not None]
    for v in values:
        assert TASK_NAME not in v and sample_task.name not in v
        assert _DRIVE_PATH_RE.search(v) is None, v


def test_source_cells_preserve_everything(p0) -> None:
    result, tmp = p0
    lines = [json.loads(l) for l in (tmp / "run" / "source_cells.jsonl").read_text(encoding="utf-8").splitlines()]
    first = lines[0]["cells"]
    assert first["B"]["value"] == "T-001" and first["B"]["header"] == "id"
    assert first["J"]["formula"] == "=LEN(G2)" and first["J"]["value"] is None  # 캐시값 없음 → 추측 안 함
    assert first["M"]["hyperlink"] == "https://example.com/source"
    assert first["O"]["value"] == "개인태그"
    assert first["R"]["value"].startswith(LEAK_MARK)  # 원본 보존은 하되 row_card에는 없음
    assert lines[6]["cells"]["D"]["value"] == "월간 업무 보고 "  # D열 원문(끝 공백) 그대로


def test_reference_mode(p0) -> None:
    rows = by_id(p0[0])
    assert rows["T-001"][0]["reference_mode"] == "GENERATE_REFERENCE"
    assert rows["T-006"][0]["reference_mode"] == "UNRESOLVED_REFERENCE"
    assert rows["T-006"][0]["reference_note"] == "조사 지침서"


def test_original_task_empty_marked(p0) -> None:
    card = by_id(p0[0])["T-010"][0]
    assert card["original_task"] is None and card["original_task_empty"] is True


def test_job_leaf_in_cards(p0) -> None:
    rows = by_id(p0[0])
    assert rows["T-001"][0]["job_leaf"] == "회계 사무원"
    assert rows["T-003"][0]["job_leaf"] == "통계 및 설문 조사 사무원"  # 전각 콜론
    assert rows["T-007"][0]["job_leaf"] == "총무 사무원"  # 구분자 없음


def test_multi_format_profiles_each_file(p0) -> None:
    card, rec = by_id(p0[0])["T-008"]
    assert rec["matched_locators"] == ["통계 보고서.hwpx", "통계 보고서.xlsx"]
    assert card["expected_filename"] == "통계 보고서.hwpx, 통계 보고서.xlsx"
    assert "[파일] 통계 보고서.hwpx" in card["file_profile"] and "[파일] 통계 보고서.xlsx" in card["file_profile"]
    assert len(card["file_profile"]) <= 1500


def test_zip_member_locator_and_profile(p0) -> None:
    card, rec = by_id(p0[0])["T-010"]
    assert rec["matched_locators"] == ["자료모음.zip!/원자료/설문 원자료.json"]
    assert "레코드 배열 $.records: 7건" in card["file_profile"]


def test_not_inspected_reason_recorded(p0) -> None:
    card, rec = by_id(p0[0])["T-013"]
    assert card["match_status"] == "MATCHED" and card["inspected"] is False
    assert "HWP(구버전) 판독 도구 없음" in rec["reason"]
    assert "NOT_INSPECTED" in card["file_profile"]


def test_extension_mismatch_in_mapping_audit(p0) -> None:
    """확장자는 .hwpx인데 zip이 아니면 NOT_INSPECTED + 경고 EXTENSION_MISMATCH, mapping_audit에 보인다."""
    result, tmp = p0
    card, rec = by_id(result)["T-016"]
    assert card["match_status"] == "MATCHED" and card["inspected"] is False
    assert "EXTENSION_MISMATCH: 확장자는 .hwpx인데 zip 형식이 아님 (실제 형식: HWP 구버전 추정)" in rec["reason"]
    with open(tmp / "audit.csv", encoding="utf-8-sig", newline="") as f:
        row = next(r for r in csv.DictReader(f) if r["id"] == "T-016")
    assert "EXTENSION_MISMATCH" in row["warnings"].split("; ")


def test_profile_budget_from_config(sample_task: Path, tmp_path: Path) -> None:
    result = run_p0(sample_task, Config(PROFILE_MAX_CHARS=400), tmp_path / "run", tmp_path / "a.csv")
    sizes = [len(c["file_profile"]) for c in result.row_cards if c["file_profile"]]
    assert sizes and max(sizes) <= 400


def test_all_profiles_within_budget(p0) -> None:
    for card in p0[0].row_cards:
        assert card["file_profile"] is None or len(card["file_profile"]) <= 1500


def test_rerun_is_write_once_and_identical(sample_task: Path, tmp_path: Path) -> None:
    run_p0(sample_task, Config(), tmp_path / "run", tmp_path / "a.csv")
    before = (tmp_path / "run" / "row_cards.jsonl").read_text(encoding="utf-8")
    run_p0(sample_task, Config(), tmp_path / "run", tmp_path / "a.csv")  # 같으면 그대로
    assert (tmp_path / "run" / "row_cards.jsonl").read_text(encoding="utf-8") == before
    (tmp_path / "run" / "row_cards.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(P0Stop, match="덮어쓰기 금지"):
        run_p0(sample_task, Config(), tmp_path / "run", tmp_path / "a.csv")


# --- 중단 조건 ---


def _edit_datalist(task: Path, fn) -> None:
    path = task / f"{TASK_NAME}_DataList.xlsx"
    wb = openpyxl.load_workbook(path)
    fn(wb)
    wb.save(path)


@pytest.mark.parametrize("edit, message", [
    (lambda wb: setattr(wb["DataList"], "title", "Data"), "'DataList' 탭이 없다"),
    (lambda wb: wb["DataList"].__setitem__("F1", "형식"), "F열 '형식'"),
    (lambda wb: wb["DataList"].__setitem__("B3", None), "id 누락"),
    (lambda wb: wb["DataList"].__setitem__("B3", "T-001"), "id 중복"),
])
def test_stops(sample_task: Path, tmp_path: Path, edit, message: str) -> None:
    _edit_datalist(sample_task, edit)
    with pytest.raises(P0Stop, match=message):
        run_p0(sample_task, Config(), tmp_path / "run", tmp_path / "a.csv")


def test_header_whitespace_and_newline_tolerated(sample_task: Path, tmp_path: Path) -> None:
    _edit_datalist(sample_task, lambda wb: wb["DataList"].__setitem__("I1", "  직무정보\n"))
    run_p0(sample_task, Config(), tmp_path / "run", tmp_path / "a.csv")


def test_not_found_ratio_stop(sample_task: Path, tmp_path: Path) -> None:
    for p in (sample_task / "01_output_files").glob("*.xlsx"):
        p.unlink()
    for p in (sample_task / "01_output_files").glob("*.XLSX"):
        p.unlink()
    with pytest.raises(P0Stop, match="NOT_FOUND"):
        run_p0(sample_task, Config(NOT_FOUND_STOP_RATIO=0.1), tmp_path / "run", tmp_path / "a.csv")


def test_broken_zip_turns_not_found_into_inventory_incomplete(sample_task: Path, tmp_path: Path) -> None:
    (sample_task / "01_output_files" / "깨진.zip").write_bytes(b"PK\x03\x04 not a zip")
    result = run_p0(sample_task, Config(), tmp_path / "run", tmp_path / "a.csv")
    assert by_id(result)["T-004"][0]["match_status"] == "INVENTORY_INCOMPLETE"


# --- 단위 규칙 ---


@pytest.mark.parametrize("value, expected", [
    ("CSV", (["CSV"], None)),
    (" .xlsx ", (["xlsx"], None)),
    ("HWPX, XLSX", (["HWPX", "XLSX"], None)),
    ("pdf, PDF", (["pdf"], None)),
    ("CSV/PDF", (None, "F열 형식 해석 불가: 'CSV/PDF'")),
    (None, (None, "F열 누락")),
    ("..csv", (None, "F열 형식 해석 불가: '..csv'")),
])
def test_parse_formats(value, expected) -> None:
    assert parse_formats(value) == expected


@pytest.mark.parametrize("job, leaf", [
    ("a:b:  회계 사무원 ", "회계 사무원"), ("a：b：c", "c"), ("총무 사무원", "총무 사무원"), (None, None),
])
def test_job_leaf(job, leaf) -> None:
    assert job_leaf(job) == leaf


@pytest.mark.parametrize("value, warnings", [
    (None, ["JOBINFO_EMPTY"]), ("  ", ["JOBINFO_EMPTY"]), ("#N/A", ["JOBINFO_SHEET_ERROR"]),
    ("#REF!", ["JOBINFO_SHEET_ERROR"]), ("직무 매칭 실패", ["JOBINFO_MATCH_FAILED"]), ("정상 직무정보", []),
])
def test_jobinfo_warnings(value, warnings) -> None:
    assert jobinfo_warnings(value) == warnings


def test_classify_reference() -> None:
    assert classify_reference(None) == ("GENERATE_REFERENCE", None)
    assert classify_reference("  ") == ("GENERATE_REFERENCE", None)
    assert classify_reference("조사 지침서") == ("UNRESOLVED_REFERENCE", "조사 지침서")


def _entry(name: str, accessible: bool = True, in_zip: bool = False) -> InventoryEntry:
    return InventoryEntry(name, name, in_zip, accessible, Path(name), None, None if accessible else "권한 오류")


def test_inaccessible_and_nfc_and_extension_case() -> None:
    import unicodedata
    from types import SimpleNamespace

    # 인벤토리 이름은 NFC로 저장된다 (build_inventory). D열이 NFD여도 같아야 한다.
    inv = SimpleNamespace(entries=[_entry("보고서.PDF"), _entry("잠긴.pdf", False)])
    index = build_index(inv)
    assert match_deliverable(unicodedata.normalize("NFD", "보고서"), "pdf", index, False).match_status == "MATCHED"
    assert match_deliverable("잠긴", "PDF", index, False).match_status == "INACCESSIBLE"
    assert match_deliverable("보고서 ", "pdf", index, False).warnings == ["D_TRAILING_SPACE"]
    assert match_deliverable("보고", "pdf", index, False).match_status == "NOT_FOUND"  # stem 일부 일치 금지


def test_inventory_marks_encrypted_member_inaccessible(tmp_path: Path) -> None:
    out = tmp_path / "01_output_files"
    out.mkdir()
    zpath = out / "a.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("비밀.csv", "a\n1\n")
    data = bytearray(zpath.read_bytes())
    # 로컬 헤더(offset 6)와 중앙 디렉터리 헤더(offset +8)의 flag 비트 0(암호)을 켠다
    data[6] |= 0x01
    cd = data.find(b"PK\x01\x02")
    data[cd + 8] |= 0x01
    zpath.write_bytes(bytes(data))
    inv = build_inventory(out)
    member = next(e for e in inv.entries if e.in_zip)
    assert member.locator == "a.zip!/비밀.csv" and member.accessible is False
    assert match_deliverable("비밀", "CSV", build_index(inv), False).match_status == "INACCESSIBLE"


def test_inventory_requires_output_dir(tmp_path: Path) -> None:
    with pytest.raises(P0Stop, match="01_output_files"):
        build_inventory(tmp_path / "01_output_files")
