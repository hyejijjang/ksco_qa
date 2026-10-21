"""ksco-qa CLI — 골격 (설계 10.1 실행 모드 8종, 10.3 재개 / CLAUDE.md 설계 보완 --resume).

실행: uv run ksco-qa <mode> <task_folder>
모델을 부르는 명령(run, sample, rerun-failed)은 사람이 직접 실행한다.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import typer

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


TaskFolder = Annotated[Path, typer.Argument(help="Task 폴더 (DataList·01_output_files·task_config.yaml)")]
ConfigOpt = Annotated[Optional[Path], typer.Option("--config", help="전역 설정 파일 (YAML)")]
ModeOpt = Annotated[Mode, typer.Option("--mode", help="online(기본) / batch (6.5)")]


@app.command()
def estimate(task_folder: TaskFolder, config: ConfigOpt = None) -> None:
    """P0만 실행하고 호출 수·예상 토큰·예상 비용을 출력. 모델 호출 없음 (10.1, 11장)."""
    raise NotImplementedError


@app.command()
def sample(
    n: Annotated[int, typer.Argument(min=1, help="무작위로 뽑을 행 수")],
    task_folder: TaskFolder,
    mode: ModeOpt = Mode.online,
    config: ConfigOpt = None,
) -> None:
    """무작위 N행으로 전 단계를 실행 (별도 run) (10.1)."""
    raise NotImplementedError


@app.command()
def run(
    task_folder: TaskFolder,
    stage: Annotated[Optional[Stage], typer.Option("--stage", help="지정 단계부터 끝까지")] = None,
    mode: ModeOpt = Mode.online,
    resume: Annotated[Optional[str], typer.Option("--resume", help="재개할 run_id (명시 재개)")] = None,
    config: ConfigOpt = None,
) -> None:
    """P0 → G3 전체 (기본). 끝난 호출은 건너뜀. --stage로 지정 단계부터 (10.1, 10.3).

    재개 기준은 설정 해시 + 입력 파일 해시 (CLAUDE.md 설계 보완).
    """
    raise NotImplementedError


@app.command("rerun-failed")
def rerun_failed(
    task_folder: TaskFolder,
    mode: ModeOpt = Mode.online,
    resume: Annotated[Optional[str], typer.Option("--resume", help="대상 run_id")] = None,
    config: ConfigOpt = None,
) -> None:
    """status가 FAILED·VALIDATION_FAIL인 호출만 다시 (10.1)."""
    raise NotImplementedError


@app.command()
def export(
    task_folder: TaskFolder,
    resume: Annotated[Optional[str], typer.Option("--resume", help="대상 run_id")] = None,
) -> None:
    """G3만 다시 (overrides 반영, 스키마 수정). 모델 호출 없음 (10.1, 9.2)."""
    raise NotImplementedError


@app.command()
def compare(
    task_folder: TaskFolder,
    with_: Annotated[Path, typer.Option("--with", help="비교할 결과 폴더 (Work 결과 또는 다른 버전)")],
) -> None:
    """두 결과의 일치도 리포트 (9.3, 10.1)."""
    raise NotImplementedError


if __name__ == "__main__":
    app()
