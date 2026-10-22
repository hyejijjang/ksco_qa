"""골격 모듈 import, CLI 명령 구성 (설계 10.1)."""

from __future__ import annotations

import importlib

import pytest
from typer.testing import CliRunner

from ksco_qa.cli import app

MODULES = [
    "ksco_qa.p0",
    "ksco_qa.profiler",
    "ksco_qa.profiler.csv_file",
    "ksco_qa.profiler.spreadsheet",
    "ksco_qa.profiler.pdf",
    "ksco_qa.profiler.document",
    "ksco_qa.profiler.pptx_file",
    "ksco_qa.profiler.hwp",
    "ksco_qa.profiler.zip_file",
    "ksco_qa.profiler.structured",
    "ksco_qa.llm.client",
    "ksco_qa.stages.g0",
    "ksco_qa.stages.g1a",
    "ksco_qa.stages.g1b",
    "ksco_qa.stages.g1c",
    "ksco_qa.stages.g2",
    "ksco_qa.g3.export",
    "ksco_qa.g3.validate",
    "ksco_qa.compare",
]


@pytest.mark.parametrize("module", MODULES)
def test_skeleton_imports(module: str) -> None:
    importlib.import_module(module)


runner = CliRunner()


def test_cli_lists_all_modes() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("estimate", "sample", "run", "rerun-failed", "export", "compare"):
        assert cmd in result.output


def test_cli_run_options() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    for opt in ("--stage", "--mode", "--resume", "--llm", "--mock-fault"):
        assert opt in result.output


@pytest.mark.parametrize("args", [["estimate", "t"], ["compare", "t", "--with", "w"]])
def test_no_key_needed_for_non_model_commands(no_api_key, args: list[str]) -> None:
    """키 없이도 돌아야 하는 명령: 본문 미구현(NotImplementedError)까지 가고 키 오류로 멈추지 않는다."""
    result = runner.invoke(app, args)
    assert isinstance(result.exception, NotImplementedError), result.output


@pytest.mark.parametrize(
    "args",
    [
        ["run", "t"],
        ["run", "t", "--mode", "batch"],
        ["run", "t", "--stage", "G2"],
        ["sample", "30", "t"],
        ["sample", "30", "t", "--mode", "batch"],
        ["rerun-failed", "t"],
    ],
)
def test_model_commands_require_key(no_api_key, args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "OPENAI_API_KEY가 설정되지 않음" in result.output


def test_key_present_then_config_checked(monkeypatch: pytest.MonkeyPatch, sample_task) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    result = runner.invoke(app, ["run", str(sample_task)])
    assert result.exit_code == 1 and "MODEL_G0" in result.output
    assert not (sample_task / "03_results").exists()


@pytest.mark.parametrize(
    "args",
    [
        ["run", "{t}", "--llm", "mock"],
        ["run", "{t}", "--llm", "mock", "--mode", "batch"],
        ["sample", "3", "{t}", "--llm", "mock"],
        ["rerun-failed", "{t}", "--llm", "mock", "--mock-fault", "schema_fail=0.5"],
    ],
)
def test_mock_needs_no_key_and_reaches_pipeline(no_api_key, sample_task, args: list[str]) -> None:
    result = runner.invoke(app, [a.format(t=sample_task) for a in args])
    assert isinstance(result.exception, NotImplementedError), result.output
    assert "MOCK" in result.output
    run_dir = next((sample_task / "03_results" / "_work").iterdir())
    assert run_dir.name.startswith("mock-")
    # P0, G0, G1a까지 실제로 돌고, mock 산출물은 run 폴더 안에만 둔다.
    assert (run_dir / "00_mapping_audit.csv").is_file() and (run_dir / "row_cards.jsonl").is_file()
    assert (run_dir / "g0" / "records.jsonl").is_file()
    assert (run_dir / "g1" / "search.jsonl").is_file()
    assert (run_dir / "g1" / "bundles.jsonl").is_file()
    assert (run_dir / "g1" / "pairs.jsonl").is_file()
    assert (run_dir / "g1" / "rows.jsonl").is_file()
    assert "G1 완료" in str(result.exception)
    assert sorted(p.name for p in (sample_task / "03_results").iterdir()) == ["_work"]


def test_mock_fault_rejected_without_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    result = runner.invoke(app, ["run", "t", "--mock-fault", "schema_fail=0.1"])
    assert result.exit_code == 1 and "--llm mock" in result.output


def test_bad_mock_fault_value(no_api_key, sample_task) -> None:
    result = runner.invoke(app, ["run", str(sample_task), "--llm", "mock", "--mock-fault", "nope=1"])
    assert result.exit_code == 1 and "--mock-fault" in result.output


def test_export_needs_no_key_and_reruns_g3(no_api_key, sample_task) -> None:
    """export: 모델 호출 없이 기존 run의 G3만 다시 (키 불필요)."""
    import json

    from fixtures.gate_records import write_gate_records

    result = runner.invoke(app, ["run", str(sample_task), "--llm", "mock"])
    assert isinstance(result.exception, NotImplementedError)  # G1까지 돌고 G2 미구현에서 멈춤
    [run_dir] = list((sample_task / "03_results" / "_work").iterdir())
    cards = [json.loads(l) for l in (run_dir / "row_cards.jsonl").read_text(encoding="utf-8").splitlines()]
    write_gate_records(run_dir, cards)
    result = runner.invoke(app, ["export", str(sample_task)])
    assert result.exit_code == 0, result.output
    assert "G3 COMPLETED" in result.output and (run_dir / "03_final.jsonl").is_file()
    assert sorted(p.name for p in (sample_task / "03_results").iterdir()) == ["_work"]


def test_export_without_run_fails(no_api_key, sample_task) -> None:
    result = runner.invoke(app, ["export", str(sample_task)])
    assert result.exit_code == 1 and "run이 없다" in result.output
