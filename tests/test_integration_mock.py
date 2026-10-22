"""MockClient로 P0→G3 전체를 fixtures 샘플로 끝까지 도는 통합 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fixtures.sample_task import DATA_ROWS
from ksco_qa.cli import app

FINAL_OUTPUTS = (
    "00_mapping_audit.csv",
    "00_revision_regenerate.xlsx",
    "01_duplicate_audit.xlsx",
    "02_task_verify.xlsx",
    "03_final.jsonl",
    "04_sheet_paste.xlsx",
)

runner = CliRunner()


@pytest.mark.parametrize(
    "fault_args",
    [[], ["--mock-fault", "rate_limit=0.3", "--mock-fault", "schema_fail=0.2", "--mock-fault", "validation_fail=0.2"]],
    ids=["clean", "faults"],
)
def test_mock_run_end_to_end(sample_task: Path, no_api_key, fault_args: list[str]) -> None:
    result = runner.invoke(app, ["run", str(sample_task), "--llm", "mock", *fault_args])
    if result.exception is not None:
        raise result.exception
    assert result.exit_code == 0, result.output

    # mock 산출물은 03_results/ 최상위가 아니라 _work/<run_id>/ 안에만
    results = sample_task / "03_results"
    assert sorted(p.name for p in results.iterdir()) == ["_work"]
    [run_dir] = list((results / "_work").iterdir())
    assert run_dir.name.startswith("mock-")
    for name in FINAL_OUTPUTS:
        assert (run_dir / name).is_file(), name

    records = [json.loads(l) for l in (run_dir / "03_final.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(records) == DATA_ROWS
    assert [r["source_row"] for r in records] == list(range(2, 2 + DATA_ROWS))
    for r in records:
        assert r["final"]["execution_notes"].startswith("API 파이프라인(MOCK);")
        assert r["duplicate"]["overlap_status"] is not None

    calls = [json.loads(l) for l in (run_dir / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert calls and all(c["llm"] == "mock" and c["model"] == "mock" for c in calls)
    assert all(c["usage"] is not None for c in calls if c["status"] in ("OK", "RETRIED"))
    assert {c["stage"] for c in calls} >= {"G0", "G1B", "G2"}

    report = json.loads((run_dir / "run_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "COMPLETED"
    assert all(not errors for errors in report["validation"].values())
