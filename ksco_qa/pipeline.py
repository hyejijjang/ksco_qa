"""P0 → G3 단계 연결 (설계 4장, 10.1, 13장 M4). 구현된 단계까지 실제로 돈다."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from ksco_qa.config import Config
from ksco_qa.llm.client import LLMClient
from ksco_qa.p0 import run_p0
from ksco_qa.stages.g0 import run_g0
from ksco_qa.stages.g1a import generate_candidates, make_bundles, write_search_artifacts

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
    p0 = run_p0(ctx.task_folder, cfg, ctx.run_dir, ctx.result_path("00_mapping_audit.csv"))
    if STAGE_ORDER.index(start_stage) <= STAGE_ORDER.index("G0"):
        g0_records = asyncio.run(run_g0(p0.row_cards, cfg, ctx.run_dir, client))
    else:
        records_path = ctx.run_dir / "g0" / "records.jsonl"
        if not records_path.is_file():
            raise RuntimeError(f"{start_stage}부터 재개할 G0 기록이 없다: {records_path}")
        latest: dict[int, dict[str, Any]] = {}
        for line in records_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                latest[int(record["source_row"])] = record
        g0_records = [latest[int(card["source_row"])] for card in p0.row_cards if int(card["source_row"]) in latest]
        if len(g0_records) != len(p0.row_cards):
            raise RuntimeError(
                f"{start_stage}부터 재개할 G0 기록이 불완전하다: {len(g0_records)}/{len(p0.row_cards)}행"
            )
        mismatched = [
            int(card["source_row"])
            for card, record in zip(p0.row_cards, g0_records)
            if record.get("id") != card["id"]
        ]
        if mismatched:
            raise RuntimeError(f"{start_stage} 재개 G0 기록의 id가 현재 입력과 다르다: {mismatched[:10]}")

    if STAGE_ORDER.index(start_stage) <= STAGE_ORDER.index("G1"):
        search = generate_candidates(p0.row_cards, g0_records, cfg)
        bundles = make_bundles(
            [tuple(candidate["rows"]) for candidate in search["pairs"]],
            cfg.G1_PAIRS_PER_CALL,
        )
        write_search_artifacts(search, bundles, ctx.run_dir)
        raise NotImplementedError(
            f"G1a 완료: 후보 {search['candidate_count']}쌍, G1b 이후 단계 미구현 (M3)"
        )
    raise NotImplementedError(f"{start_stage} 단계 실행은 아직 미구현 (M3~M4)")
