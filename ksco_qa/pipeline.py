"""P0 → G3 단계 연결 (설계 4장, 10.1, 13장 M4). 구현된 단계까지 실제로 돈다."""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ksco_qa.config import Config
from ksco_qa.g3.export import run_g3
from ksco_qa.llm.client import LLMClient, prompt_version
from ksco_qa.p0 import find_datalist, run_p0
from ksco_qa.stages.g0 import run_g0, write_review_workbook
from ksco_qa.stages.g1a import effective_tasks, generate_candidates, make_bundles, write_search_artifacts
from ksco_qa.stages.g1b import run_g1b
from ksco_qa.stages.g1c import run_g1c
from ksco_qa.stages.g2 import run_g2

if TYPE_CHECKING:
    from ksco_qa.run import RunContext

STAGE_ORDER = ("P0", "G0", "G1", "G2", "G3")


def _load_stage_records(
    run_dir: Path,
    stage: str,
    row_cards: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    paths = {
        "G0": run_dir / "g0" / "records.jsonl",
        "G1": run_dir / "g1" / "rows.jsonl",
        "G2": run_dir / "g2" / "records.jsonl",
    }
    path = paths[stage]
    if not path.is_file():
        raise RuntimeError(f"{stage}부터 재개할 기록이 없다: {path}")

    latest: dict[int, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: JSONL 레코드가 잘못되었다") from error
        latest[int(record["source_row"])] = record

    expected = {int(card["source_row"]) for card in row_cards}
    missing = sorted(expected - set(latest))
    extra = sorted(set(latest) - expected)
    if missing or extra:
        raise RuntimeError(f"{stage} 재개 기록 범위가 현재 입력과 다르다: missing={missing[:10]}, extra={extra[:10]}")
    expected_ids = {int(card["source_row"]): card["id"] for card in row_cards}
    mismatched = [row for row, record in latest.items() if record.get("id") != expected_ids[row]]
    if mismatched:
        raise RuntimeError(f"{stage} 재개 기록의 id가 현재 입력과 다르다: {sorted(mismatched)[:10]}")
    return latest


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
    start_index = STAGE_ORDER.index(start_stage)
    p0 = run_p0(ctx.task_folder, cfg, ctx.run_dir, ctx.result_path("00_mapping_audit.csv"))
    if start_index <= STAGE_ORDER.index("G0"):
        g0_records = asyncio.run(run_g0(p0.row_cards, cfg, ctx.run_dir, client))
    else:
        g0_by_row = _load_stage_records(ctx.run_dir, "G0", p0.row_cards)
        g0_records = [g0_by_row[int(card["source_row"])] for card in p0.row_cards]

    if start_index <= STAGE_ORDER.index("G1"):
        search = generate_candidates(p0.row_cards, g0_records, cfg)
        bundles = make_bundles(
            [tuple(candidate["rows"]) for candidate in search["pairs"]],
            cfg.G1_PAIRS_PER_CALL,
        )
        write_search_artifacts(search, bundles, ctx.run_dir)
        pair_records = asyncio.run(run_g1b(
            bundles,
            p0.row_cards,
            cfg,
            ctx.run_dir,
            client,
            g0_records=g0_records,
            effective=effective_tasks(p0.row_cards, g0_records),
            candidate_pairs=search["pairs"],
        ))
        g1_rows = asyncio.run(run_g1c(
            p0.row_cards,
            g0_records,
            pair_records,
            cfg,
            ctx.run_dir,
            client,
            candidate_pairs=search["pairs"],
            search_completed=bool(search["code_search_completed"] and search["semantic_search_completed"]),
            effective=effective_tasks(p0.row_cards, g0_records),
        ))
    else:
        g1_rows = _load_stage_records(ctx.run_dir, "G1", p0.row_cards)

    if start_index <= STAGE_ORDER.index("G2"):
        asyncio.run(run_g2(
            p0.row_cards,
            g0_records,
            g1_rows,
            cfg,
            ctx.run_dir,
            client,
        ))
    else:
        _load_stage_records(ctx.run_dir, "G2", p0.row_cards)

    datalist, _ = find_datalist(ctx.task_folder)
    prompt_versions = {
        "G0": prompt_version("G0"),
        "G1B": prompt_version("G1B"),
        "G2": prompt_version("G2", cfg.G2_OVERLAP_MODE),
    }
    report = run_g3(ctx, cfg, prompt_versions, source_file=datalist.name)
    return report["status"]


def run_g0_sample(
    ctx: "RunContext",
    cfg: Config,
    client: LLMClient,
    sample_n: int,
) -> dict[str, Any]:
    """감사 가능한 표본에 P0·G0만 실행하고 G1B·G2는 호출하지 않는다."""
    if sample_n < 1:
        raise ValueError("sample_n은 1 이상이어야 한다")

    p0 = run_p0(ctx.task_folder, cfg, ctx.run_dir, ctx.run_dir / "00_mapping_audit.csv")
    if sample_n > len(p0.row_cards):
        raise ValueError(f"표본 {sample_n}행을 요청했지만 DataList 데이터 행은 {len(p0.row_cards)}개다")

    rng = random.Random(ctx.run_id)
    selected = sorted(rng.sample(p0.row_cards, sample_n), key=lambda card: int(card["source_row"]))
    records = asyncio.run(run_g0(selected, cfg, ctx.run_dir, client))
    write_review_workbook(ctx.run_dir / "g0_review.xlsx", selected, records)

    action_counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    for record in records:
        action_counts[record["action"]] = action_counts.get(record["action"], 0) + 1
        decision = record["decided_by"]
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
    stage_checks_path = ctx.run_dir / "g0" / "stage_checks.jsonl"
    stage_checks = [
        json.loads(line)
        for line in stage_checks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if stage_checks_path.is_file() else []
    report = {
        "run_id": ctx.run_id,
        "llm": ctx.llm,
        "sample_n": sample_n,
        "sample_seed": ctx.run_id,
        "p0_rows": len(p0.row_cards),
        "selected_rows": [
            {"source_row": int(card["source_row"]), "id": card["id"]}
            for card in selected
        ],
        "g0_action": action_counts,
        "g0_decided_by": decision_counts,
        "g0_escalated_rows": [
            int(record["source_row"]) for record in records if record.get("escalated")
        ],
        "stage_checks": stage_checks,
        "review_workbook": "g0_review.xlsx",
    }
    (ctx.run_dir / "g0_sample_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
