"""G3가 읽는 단계별 결과 기록 (데이터 계약, 설계 4.2·7장). G0·G1·G2 단계(M2~M4)는 이 형식으로 쓴다.

run 폴더(_work/<run_id>/) 안의 파일, 모두 UTF-8 JSONL 추가 전용. 같은 source_row가 여러 번 나오면 마지막 줄이 이긴다
(재판정·사람 검토 반영도 새 줄로 남긴다, 설계 3장 원칙 6).

- row_cards.jsonl, source_cells.jsonl, p0/records.jsonl — P0 (ksco_qa.p0)
- g0/records.jsonl — 행마다 G0 결과
    {source_row, id, action, decided_by: MODEL|RULE|HUMAN, failure: null|CALL_FAILED|VALIDATION_FAILED,
     rule_reason: str|null (RULE일 때 사유, 예: "NOT_INSPECTED: …"), output: schemas/g0.json 응답|null,
     escalated: bool (high 재판정 여부)}
- g1/rows.jsonl — 행마다 G1c 결과 (06 duplicate 필드 그대로)
    {source_row, id, status, duplicate_type, overlap_status, representative_row, representative_id, group,
     compared_rows[], candidate_rows[], candidate_count, adjudicated_candidate_count, unresolved_candidate_count,
     search_scope, search_completed, reason, candidate_pairs[{row, signals[], similarity, verdict, evidence}], decided_by}
- g2/records.jsonl — 행마다 G2 결과
    {source_row, id, status: PASS|REVIEW|FAIL|SKIPPED, skip_reason: str|null, decided_by,
     failure: null|CALL_FAILED|VALIDATION_FAILED (호출·검증 2회 실패 → G3가 REVIEW·RULE로 기록), rule_reason: str|null,
     flags[] (코드 검증 경고), output: schemas/g2.json 응답|null}
- overrides.jsonl — 사람 검토 반영 (CLAUDE.md M1 결정)
    {source_row, id, gate: G0|G1|G2|final, field, old_value, new_value, reviewer, reason, decided_at}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OVERRIDE_GATES = ("G0", "G1", "G2", "final")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not Path(path).is_file():
        return []
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def latest_by_row(records: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """추가 전용 기록에서 source_row별 마지막 줄."""
    out: dict[int, dict[str, Any]] = {}
    for r in records:
        out[int(r["source_row"])] = r
    return out


@dataclass
class GateInputs:
    row_cards: list[dict[str, Any]]
    source_cells: dict[int, dict[str, Any]]
    p0: dict[int, dict[str, Any]]
    g0: dict[int, dict[str, Any]]
    g1: dict[int, dict[str, Any]]
    g2: dict[int, dict[str, Any]]
    overrides: list[dict[str, Any]] = field(default_factory=list)


def load_inputs(run_dir: Path) -> GateInputs:
    run_dir = Path(run_dir)
    return GateInputs(
        row_cards=read_jsonl(run_dir / "row_cards.jsonl"),
        source_cells=latest_by_row(read_jsonl(run_dir / "source_cells.jsonl")),
        p0=latest_by_row(read_jsonl(run_dir / "p0" / "records.jsonl")),
        g0=latest_by_row(read_jsonl(run_dir / "g0" / "records.jsonl")),
        g1=latest_by_row(read_jsonl(run_dir / "g1" / "rows.jsonl")),
        g2=latest_by_row(read_jsonl(run_dir / "g2" / "records.jsonl")),
        overrides=read_jsonl(run_dir / "overrides.jsonl"),
    )


def apply_overrides(inputs: GateInputs) -> list[dict[str, Any]]:
    """사람 검토(overrides.jsonl)를 단계 기록에 반영하고 decided_by=HUMAN으로 표시 (설계 9.2).
    같은 (source_row, gate, field)는 마지막 줄이 이긴다. final 게이트는 최종 판정 뒤에 반영하도록 돌려준다."""
    last: dict[tuple[int, str, str], dict[str, Any]] = {}
    for o in inputs.overrides:
        if o.get("gate") not in OVERRIDE_GATES:
            raise ValueError(f"overrides.jsonl gate는 {OVERRIDE_GATES} 중 하나: {o.get('gate')!r}")
        last[(int(o["source_row"]), o["gate"], o["field"])] = o
    final_overrides = []
    for (row, gate, fld), o in last.items():
        if gate == "final":
            final_overrides.append(o)
            continue
        store = {"G0": inputs.g0, "G1": inputs.g1, "G2": inputs.g2}[gate]
        record = dict(store.get(row, {"source_row": row, "id": o.get("id")}))
        record[fld] = o["new_value"]
        record["decided_by"] = "HUMAN"
        store[row] = record
    return final_overrides
