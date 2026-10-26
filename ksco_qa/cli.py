"""ksco-qa CLI (설계 10.1 실행 모드 8종, 10.3 재개 / CLAUDE.md 설계 보완 --resume).

실행: uv run ksco-qa <mode> <task_folder>
모델을 부르는 명령(run, sample, rerun-failed)은 사람이 직접 실행한다.
--llm mock이면 실제 API 대신 MockClient가 응답한다 (API 키 불필요, 산출물은 _work/<run_id>/ 안에만).
API 키(OPENAI_API_KEY)는 --llm openai로 run·sample·rerun-failed를 실행할 때만 확인한다.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, NoReturn, Optional

import typer

from ksco_qa.compare import CompareError, WorkResultFormatError, compare_results
from ksco_qa.compare_runs import compare_runs
from ksco_qa.config import ConfigError, require_for_model_calls, resolve_config
from ksco_qa.estimate import estimate_run
from ksco_qa.llm.client import BudgetExceeded, ForbiddenContext
from ksco_qa.llm.factory import build_client
from ksco_qa.llm.mock import MockFaults
from ksco_qa.llm.openai_transport import ApiKeyMissing, require_api_key
from ksco_qa.p0 import P0Stop, run_p0
from ksco_qa.pipeline import run_g0_sample, run_pipeline
from ksco_qa.run import RunError, prepare_run

app = typer.Typer(no_args_is_help=True, add_completion=False, help="KSCO Task QA 파이프라인 (P0→G0→G1→G2→G3)")


class Mode(str, Enum):
    online = "online"
    batch = "batch"


class Stage(str, Enum):
    P0 = "P0"
    G0 = "G0"
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"


class Llm(str, Enum):
    openai = "openai"
    mock = "mock"


TaskFolder = Annotated[Path, typer.Argument(help="Task 폴더 (DataList·01_output_files·task_config.yaml)")]
ConfigOpt = Annotated[Optional[Path], typer.Option("--config", help="전역 설정 파일 (YAML)")]
ModeOpt = Annotated[Mode, typer.Option("--mode", help="online(기본) / batch (6.5)")]
LlmOpt = Annotated[Llm, typer.Option("--llm", help="openai(기본) / mock (가짜 응답, API 키 불필요)")]
FaultOpt = Annotated[
    Optional[list[str]],
    typer.Option("--mock-fault", help="mock 고장 주입, 반복 지정 (예: rate_limit=0.2, schema_fail=0.1, validation_fail=0.1, timeout=0.1, repeats=2)"),
]


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(1)


def _start_model_run(
    task_folder: Path,
    *,
    mode: Mode,
    llm: Llm,
    resume: str | None,
    config: Path | None,
    mock_fault: list[str] | None,
    sample_n: int | None = None,
    start_stage: str = "P0",
    rerun_failed: bool = False,
) -> None:
    """run·sample·rerun-failed 공통 시작 (online·batch 모두)."""
    if llm is Llm.openai:
        if mock_fault:
            _fail("--mock-fault는 --llm mock에서만 쓸 수 있다")
        try:
            require_api_key()
        except ApiKeyMissing as e:
            _fail(str(e))
    try:
        faults = MockFaults.parse(mock_fault) if llm is Llm.mock else None
        cfg = resolve_config(task_folder, config, overrides={"MODE": mode.value})
        if llm is Llm.openai:
            require_for_model_calls(cfg)
        ctx = prepare_run(task_folder, cfg, llm.value, resume=resume, sample_n=sample_n)
        client = build_client(cfg, ctx, faults)
    except (ValueError, ConfigError, RunError, P0Stop, ApiKeyMissing) as e:
        _fail(str(e))
    typer.echo(f"run_id: {ctx.run_id}" + ("  [MOCK — 산출물은 run 폴더 안에만]" if ctx.is_mock else ""))
    try:
        status = run_pipeline(ctx, cfg, client, start_stage=start_stage, rerun_failed=rerun_failed)
    except (BudgetExceeded, ForbiddenContext, P0Stop) as e:
        _fail(str(e))
    if client.progress is not None:
        typer.echo(f"run 완료 — G3 {status} · 이번 실행 비용 ${client.progress.total_cost():.4f} "
                   f"(실측 합계: {ctx.run_id}/run_report.json)")


@app.command()
def estimate(task_folder: TaskFolder, config: ConfigOpt = None) -> None:
    """P0만 실행하고 호출 수·예상 토큰·예상 비용을 출력. 모델 호출 없음 (10.1, 11장)."""
    try:
        cfg = resolve_config(task_folder, config)
        with TemporaryDirectory(prefix="ksco-qa-estimate-") as temp:
            temp_dir = Path(temp)
            p0 = run_p0(
                task_folder,
                cfg,
                temp_dir,
                temp_dir / "00_mapping_audit.csv",
            )
            report = estimate_run(p0.row_cards, cfg)
    except (ConfigError, P0Stop, OSError, ValueError) as error:
        _fail(str(error))
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@app.command()
def sample(
    n: Annotated[int, typer.Argument(min=1, help="무작위로 뽑을 행 수")],
    task_folder: TaskFolder,
    mode: ModeOpt = Mode.online,
    llm: LlmOpt = Llm.openai,
    mock_fault: FaultOpt = None,
    config: ConfigOpt = None,
) -> None:
    """무작위 N행으로 전 단계를 실행 (별도 run) (10.1)."""
    _start_model_run(task_folder, mode=mode, llm=llm, resume=None, config=config, mock_fault=mock_fault, sample_n=n)


@app.command("g0-sample")
def g0_sample(
    n: Annotated[int, typer.Argument(min=1, help="무작위로 뽑을 G0 행 수")],
    task_folder: TaskFolder,
    mode: ModeOpt = Mode.online,
    llm: LlmOpt = Llm.openai,
    mock_fault: FaultOpt = None,
    config: ConfigOpt = None,
) -> None:
    """무작위 N행만 P0→G0 실행하고 G0 검토용 workbook을 만든다 (M2)."""
    if llm is Llm.openai:
        if mock_fault:
            _fail("--mock-fault는 --llm mock에서만 쓸 수 있다")
        try:
            require_api_key()
        except ApiKeyMissing as e:
            _fail(str(e))
    try:
        faults = MockFaults.parse(mock_fault) if llm is Llm.mock else None
        cfg = resolve_config(task_folder, config, overrides={"MODE": mode.value})
        if llm is Llm.openai:
            require_for_model_calls(cfg, stages=("G0",))
        ctx = prepare_run(task_folder, cfg, llm.value, sample_n=n)
        client = build_client(cfg, ctx, faults)
    except (ValueError, ConfigError, RunError, P0Stop, ApiKeyMissing) as e:
        _fail(str(e))
    typer.echo(f"run_id: {ctx.run_id}" + ("  [MOCK — 산출물은 run 폴더 안에만]" if ctx.is_mock else ""))
    try:
        report = run_g0_sample(ctx, cfg, client, n)
    except (BudgetExceeded, ForbiddenContext, P0Stop, ValueError) as e:
        _fail(str(e))
    typer.echo(
        f"G0 표본 {report['sample_n']}행 완료 · 판정 {report['g0_action']} · "
        f"검토 파일: {ctx.run_dir / report['review_workbook']}"
    )


@app.command()
def run(
    task_folder: TaskFolder,
    stage: Annotated[Optional[Stage], typer.Option("--stage", help="지정 단계부터 끝까지")] = None,
    mode: ModeOpt = Mode.online,
    llm: LlmOpt = Llm.openai,
    mock_fault: FaultOpt = None,
    resume: Annotated[Optional[str], typer.Option("--resume", help="재개할 run_id (명시 재개)")] = None,
    config: ConfigOpt = None,
) -> None:
    """P0 → G3 전체 (기본). 끝난 호출은 건너뜀. --stage로 지정 단계부터 (10.1, 10.3).

    재개 기준은 설정 해시 + 입력 파일 해시 (CLAUDE.md 설계 보완).
    """
    _start_model_run(
        task_folder, mode=mode, llm=llm, resume=resume, config=config, mock_fault=mock_fault,
        start_stage=stage.value if stage else "P0",
    )


@app.command("rerun-failed")
def rerun_failed(
    task_folder: TaskFolder,
    mode: ModeOpt = Mode.online,
    llm: LlmOpt = Llm.openai,
    mock_fault: FaultOpt = None,
    resume: Annotated[Optional[str], typer.Option("--resume", help="대상 run_id")] = None,
    config: ConfigOpt = None,
) -> None:
    """status가 FAILED·VALIDATION_FAIL인 호출만 다시 (10.1)."""
    _start_model_run(
        task_folder, mode=mode, llm=llm, resume=resume, config=config, mock_fault=mock_fault, rerun_failed=True
    )


@app.command()
def export(
    task_folder: TaskFolder,
    resume: Annotated[Optional[str], typer.Option("--resume", help="대상 run_id")] = None,
) -> None:
    """G3만 다시 (overrides 반영, 스키마 수정). 모델 호출 없음 (10.1, 9.2). --resume이 없으면 가장 최근 run."""
    from ksco_qa.g3.export import run_g3
    from ksco_qa.llm.client import STAGE_FILES, prompt_version
    from ksco_qa.p0 import find_datalist
    from ksco_qa.run import open_run

    try:
        ctx = open_run(task_folder, resume)
        cfg = resolve_config(task_folder, overrides=_resolved_overrides(ctx.run_dir))
        datalist, _ = find_datalist(task_folder)
    except (ConfigError, RunError, P0Stop) as e:
        _fail(str(e))
    versions = {s: prompt_version(s, cfg.G2_OVERLAP_MODE if s == "G2" else None) for s in STAGE_FILES}
    report = run_g3(ctx, cfg, versions, source_file=datalist.name)
    failed = [name for name, errors in report["validation"].items() if errors]
    typer.echo(f"run_id: {ctx.run_id} · G3 {report['status']} · 최종 {report['summary']['final_status']}")
    if failed:
        _fail("검증 실패: " + ", ".join(failed) + f" (자세한 내용: {ctx.run_id}/run_report.json)")


def _resolved_overrides(run_dir: Path) -> dict:
    """run 폴더의 config.resolved.yaml 값을 그대로 쓴다 (export는 그 run의 설정으로 다시 만든다)."""
    import yaml

    path = run_dir / "config.resolved.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}


@app.command()
def compare(
    task_folder: TaskFolder,
    with_: Annotated[Path, typer.Option("--with", help="Work 결과 CSV/TSV 또는 DataList.xlsx")],
) -> None:
    """Work AI 판정·재생성 Task를 최신 API 결과와 비교한다 (9.3, 10.1)."""
    results_root = Path(task_folder) / "03_results"
    candidates = [results_root] if (results_root / "03_final.jsonl").is_file() else []
    work_root = results_root / "_work"
    if work_root.is_dir():
        candidates.extend(
            run_dir for run_dir in work_root.iterdir()
            if run_dir.is_dir() and (run_dir / "03_final.jsonl").is_file()
        )
    if not candidates:
        _fail(f"{results_root} 또는 _work 아래에 비교할 03_final.jsonl이 없다")
    api_results = max(candidates, key=lambda path: (path / "03_final.jsonl").stat().st_mtime_ns)
    try:
        report = compare_results(api_results, with_)
    except (CompareError, WorkResultFormatError, OSError, ValueError) as error:
        _fail(str(error))
    report["api_results_dir"] = str(api_results)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@app.command("compare-runs")
def compare_runs_cmd(
    task_folder: TaskFolder,
    old: Annotated[str, typer.Option("--old", help="이전 run_id (03_results/_work 아래 폴더 이름)")],
    new: Annotated[str, typer.Option("--new", help="새 run_id")],
    with_: Annotated[Path, typer.Option("--with", help="Work 결과 CSV/TSV 또는 DataList.xlsx (사람 판정·검수 메모)")],
    out: Annotated[Optional[Path], typer.Option("--out", help="출력 xlsx (기본: 새 run 폴더/compare_vs_<이전 run_id>.xlsx)")] = None,
) -> None:
    """같은 표본의 두 run을 행별로 비교한다: G0 action·차원별 R/F·재생성 Task, G1·G2·최종, 사람 판정."""
    try:
        path = compare_runs(task_folder, old, new, with_, out)
    except (CompareError, WorkResultFormatError, OSError, ValueError) as error:
        _fail(str(error))
    typer.echo(f"비교표: {path}")


if __name__ == "__main__":
    app()
