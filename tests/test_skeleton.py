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


def test_profiler_modules_exist() -> None:
    from ksco_qa.profiler import FORMAT_MODULES

    for name in set(FORMAT_MODULES.values()):
        importlib.import_module(f"ksco_qa.profiler.{name}")


runner = CliRunner()


def test_cli_lists_all_modes() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("estimate", "sample", "run", "rerun-failed", "export", "compare"):
        assert cmd in result.output


def test_cli_run_options() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    for opt in ("--stage", "--mode", "--resume"):
        assert opt in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["estimate", "t"],
        ["sample", "30", "t"],
        ["run", "t"],
        ["run", "t", "--stage", "G2"],
        ["run", "t", "--mode", "batch"],
        ["rerun-failed", "t"],
        ["export", "t"],
        ["compare", "t", "--with", "w"],
    ],
)
def test_cli_bodies_not_implemented(args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert isinstance(result.exception, NotImplementedError), result.output
