"""P0 → G3 단계 연결 (설계 4장, 10.1, 13장 M4). 구현된 단계까지 실제로 돈다."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ksco_qa.config import Config
from ksco_qa.llm.client import LLMClient
from ksco_qa.p0 import run_p0

if TYPE_CHECKING:
    from ksco_qa.run import RunContext

STAGE_ORDER = ("P0", "G0", "G1", "G2", "G3")


def run_pipeline(
    ctx: "RunContext",
    cfg: Config,
    client: LLMClient,
    *,
    start_stage: str = "P0",
    rerun_failed: bool = False,
) -> str:
    """start_stage부터 G3까지 차례로 실행하고 run 상태를 돌려준다.

    P0는 결정적이고 산출물이 추가 전용(같으면 그대로)이라 어느 단계에서 시작해도 다시 돈다.
    최종 산출물은 ctx.result_path()로만 쓴다 (mock run은 run 폴더 안).
    final.execution_notes는 g3.export.execution_notes()로 만든다.
    """
    if start_stage not in STAGE_ORDER:
        raise ValueError(f"start_stage는 {STAGE_ORDER} 중 하나: {start_stage!r}")
    run_p0(ctx.task_folder, cfg, ctx.run_dir, ctx.result_path("00_mapping_audit.csv"))
    raise NotImplementedError("G0 이후 단계 미구현 (M2~M4)")
