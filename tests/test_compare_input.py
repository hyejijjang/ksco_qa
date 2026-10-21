"""compare 입력 형식: Work 결과 CSV 또는 DataList R~V열 (M5 비교 로직 전, 형식만)."""

from __future__ import annotations

import csv
from pathlib import Path

import openpyxl
import pytest

from fixtures.real_like import WORK_RESULT_COLUMNS, write_work_result_csv
from fixtures.sample_task import DATA_ROWS, LEAK_MARK, TASK_NAME
from ksco_qa.compare import (
    WORK_RESULT_CSV_COLUMNS,
    WorkResultFormatError,
    load_work_result,
)


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp949"])
def test_load_work_result_csv(tmp_path: Path, encoding: str) -> None:
    assert WORK_RESULT_CSV_COLUMNS == WORK_RESULT_COLUMNS
    path = tmp_path / "KSCO-99_work_result.csv"
    write_work_result_csv(path, encoding)
    rows = load_work_result(path)
    assert list(rows) == ["T-001", "T-002", "T-003"]
    assert rows["T-002"].final_verdict == "가상판정C" and rows["T-002"].regenerated_task == "가상 재생성 Task"
    assert rows["T-003"].ai_verdict is None and rows["T-001"].source_row is None


def test_csv_wrong_columns_or_duplicate_id(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    with open(bad, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([["id", "판정"], ["T-001", "x"]])
    with pytest.raises(WorkResultFormatError, match="열이"):
        load_work_result(bad)
    dup = tmp_path / "dup.csv"
    with open(dup, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(WORK_RESULT_COLUMNS)
        w.writerows([["T-001", "", "", "", "", ""], ["T-001", "", "", "", "", ""]])
    with pytest.raises(WorkResultFormatError, match="중복"):
        load_work_result(dup)


def test_load_work_result_from_datalist_r_to_v(sample_task: Path) -> None:
    rows = load_work_result(sample_task / f"{TASK_NAME}_DataList.xlsx")
    assert len(rows) == DATA_ROWS
    r = rows["T-001"]
    assert r.source_row == 2
    assert (r.ai_verdict, r.final_verdict, r.regenerated_task, r.original_task_backup, r.review_memo) == tuple(
        f"{LEAK_MARK}_{c}_T-001" for c in "RSTUV")


def test_datalist_wrong_r_to_v_headers(sample_task: Path) -> None:
    path = sample_task / f"{TASK_NAME}_DataList.xlsx"
    wb = openpyxl.load_workbook(path)
    wb["DataList"]["S1"] = "최종"
    wb.save(path)
    with pytest.raises(WorkResultFormatError, match="S열 '최종'"):
        load_work_result(path)


def test_unsupported_extension(tmp_path: Path) -> None:
    with pytest.raises(WorkResultFormatError):
        load_work_result(tmp_path / "result.jsonl")
