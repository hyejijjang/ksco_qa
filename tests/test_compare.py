from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fixtures.real_like import WORK_RESULT_COLUMNS
from ksco_qa.cli import app
from ksco_qa.compare import CompareError, compare_results, load_final_jsonl


def _api_record(row_id: str, source_row: int, status: str | None, regenerated: str | None) -> dict:
    return {
        "id": row_id,
        "source_row": source_row,
        "final": {"status": status},
        "revision": {"regenerated_task_new": regenerated},
    }


def _write_final(path: Path, records: list[dict]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    final_path = path / "03_final.jsonl"
    final_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return final_path


def _write_work_csv(path: Path, rows: list[list[str]]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(WORK_RESULT_COLUMNS)
        writer.writerows(rows)


def test_compare_final_status_and_regenerated_task_by_id(tmp_path: Path) -> None:
    api_results = tmp_path / "results"
    _write_final(api_results, [
        _api_record("T-001", 2, "PASS", None),
        _api_record("T-002", 3, "REVIEW", "Generated API task"),
        _api_record("T-003", 4, None, None),
        _api_record("T-004", 5, "FAIL", None),
    ])
    work_result = tmp_path / "work.csv"
    _write_work_csv(work_result, [
        ["T-001", "PASS", "", "", "", ""],
        ["T-002", "PASS", "", "Generated Work task", "", ""],
        ["T-003", "REVIEW", "", "Work task", "", ""],
        ["T-005", "FAIL", "", "", "", ""],
    ])

    report = compare_results(api_results, work_result)

    assert report["matched_ids"] == 3
    assert report["api_only_ids"] == ["T-004"] and report["work_only_ids"] == ["T-005"]
    status = report["final_status_agreement"]
    assert (status["compared"], status["matching"], status["mismatching"]) == (2, 1, 1)
    assert status["agreement_rate"] == 0.5
    assert status["mismatches"][0]["id"] == "T-002"
    assert status["missing_api_value"][0]["id"] == "T-003"
    tasks = report["regenerated_task_comparison"]
    assert (tasks["compared"], tasks["matching"], tasks["mismatching"]) == (3, 1, 2)
    assert {row["id"] for row in tasks["mismatches"]} == {"T-002", "T-003"}


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ('{"id":"T-001","final":{"status":"PASS"},"revision":{"regenerated_task_new":null}}\n'
         '{"id":"T-001","final":{"status":"PASS"},"revision":{"regenerated_task_new":null}}\n', "id 중복"),
        ("{malformed}\n", "JSON 형식 오류"),
        ('{"id":"T-001","final":{}}\n', "final·revision 객체"),
    ],
)
def test_load_final_jsonl_rejects_invalid_records(tmp_path: Path, contents: str, message: str) -> None:
    final = tmp_path / "03_final.jsonl"
    final.write_text(contents, encoding="utf-8")
    with pytest.raises(CompareError, match=message):
        load_final_jsonl(tmp_path)


def test_compare_cli_reads_latest_final_and_prints_json(tmp_path: Path) -> None:
    task = tmp_path / "task"
    _write_final(task / "03_results", [_api_record("T-001", 2, "PASS", None)])
    work_result = tmp_path / "work.csv"
    _write_work_csv(work_result, [["T-001", "PASS", "", "", "", ""]])

    result = CliRunner().invoke(app, ["compare", str(task), "--with", str(work_result)])

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["final_status_agreement"]["agreement_rate"] == 1
    assert report["api_results_dir"].endswith("03_results")
