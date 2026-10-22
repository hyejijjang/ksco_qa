"""G0 — Task 수정·재생성 (모델, 행 1개 = 호출 1회) (설계 5.2, 6.1, 9.1)."""

from __future__ import annotations

import asyncio
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ksco_qa.config import Config
from ksco_qa.dictionaries import g0_check_keys
from ksco_qa.llm.types import CallResult

REVIEW_ACTIONS = ("REGENERATE", "RESELECT_B", "REVIEW_B")
FAILURE_ACTIONS = {"VALIDATION_FAIL": "VALIDATION_FAILED", "FAILED": "CALL_FAILED"}


def rule_record(row_card: dict[str, Any]) -> dict[str, Any]:
    """inspected=false 행: action=REVIEW_B, 사유 = P0 상태, decided_by=RULE (5.2 대상)."""
    return {
        "source_row": row_card["source_row"],
        "id": row_card["id"],
        "action": "REVIEW_B",
        "decided_by": "RULE",
        "failure": None,
        "rule_reason": f"NOT_INSPECTED: {row_card.get('match_status')}",
        "output": None,
        "escalated": False,
    }


def build_input(row_card: dict[str, Any]) -> dict[str, Any]:
    """호출 입력은 해당 행의 row_card 하나만 쓴다 (5.2 입력, 6.2)."""
    return row_card


def validate_output(row_card: dict[str, Any], output: dict[str, Any]) -> list[str]:
    """G0 출력의 행 직업·판정 정합성과 차원별 사유 중복을 검증한다."""
    errors = []
    expected_job = row_card.get("job_leaf")
    actual_job = output.get("job_evaluated")
    if actual_job != expected_job:
        errors.append(f"job_evaluated가 '{actual_job}'인데 이 행의 직업은 '{expected_job}'이다")

    action = output.get("action")
    checks = output.get("checks") or {}
    if action == "KEEP" and (
        row_card.get("original_task_empty")
        or not isinstance(row_card.get("original_task"), str)
        or not row_card["original_task"].strip()
    ):
        errors.append("ORIGINAL_TASK_EMPTY인데 action이 KEEP이다")
    if action == "KEEP" and "F" in checks.values():
        errors.append("하나 이상의 차원이 F인데 action이 KEEP이다")
    if action == "REGENERATE":
        regenerated = output.get("regenerated_task_new")
        original = row_card.get("original_task")
        if not isinstance(regenerated, str) or not regenerated.strip():
            errors.append("action이 REGENERATE인데 regenerated_task_new가 비어 있다")
        elif regenerated == original:
            errors.append("action이 REGENERATE인데 regenerated_task_new가 original_task와 같다")

    issues = output.get("issues") or {}
    issue_rows: dict[str, list[str]] = defaultdict(list)
    for key in g0_check_keys():
        if checks.get(key) in ("R", "F"):
            issue = issues.get(key)
            if isinstance(issue, str) and issue.strip():
                issue_rows[issue.strip()].append(key)
    for issue, keys in issue_rows.items():
        if len(keys) > 1:
            errors.append(f"차원별 issues 문장이 복사되었다 ({', '.join(keys)}): {issue}")
    return errors


def needs_escalation(output: dict[str, Any], validation_errors: list[str]) -> bool:
    """검증 실패 또는 비KEEP 판정은 G0_ESCALATE 설정에 따라 high로 재판정한다."""
    return bool(validation_errors) or output.get("action") in REVIEW_ACTIONS


def stage_end_checks(records: list[dict[str, Any]], row_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 reason 3회 이상, 직업 내 REVIEW_B·RESELECT_B 비율 50% 이상을 찾는다."""
    model_records = [record for record in records if record.get("decided_by") == "MODEL" and record.get("output")]
    checks = []
    by_reason: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in model_records:
        reason = record["output"].get("reason")
        if isinstance(reason, str) and reason.strip():
            by_reason[reason.strip()].append(record)
    for reason, repeated in by_reason.items():
        if len(repeated) >= 3:
            checks.append({
                "check": "REPEATED_REASON",
                "source_rows": [record["source_row"] for record in repeated],
                "reason": reason,
            })

    cards_by_row = {card["source_row"]: card for card in row_cards}
    by_job: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in model_records:
        job = cards_by_row[record["source_row"]].get("job_leaf") or ""
        by_job[job].append(record)
    for job, group in by_job.items():
        flagged = [record for record in group if record["action"] in ("RESELECT_B", "REVIEW_B")]
        if group and len(flagged) / len(group) >= 0.5:
            checks.append({
                "check": "JOB_REVIEW_ACTION_CONCENTRATION",
                "job_leaf": job,
                "source_rows": [record["source_row"] for record in flagged],
                "action_count": len(flagged),
                "job_model_rows": len(group),
            })
    return checks


def _record(row_card: dict[str, Any], result: CallResult, *, escalated: bool) -> dict[str, Any]:
    failure = FAILURE_ACTIONS.get(result.status)
    if result.status == "VALIDATION_FAIL":
        failure = "VALIDATION_FAILED"
    if failure:
        return {
            "source_row": row_card["source_row"],
            "id": row_card["id"],
            "action": "REVIEW_B",
            "decided_by": "RULE",
            "failure": failure,
            "rule_reason": "; ".join(result.validation_errors) or result.status,
            "output": None,
            "escalated": escalated,
        }
    if result.parsed is None:
        raise RuntimeError(f"G0 {row_card['source_row']}행 {result.status}인데 출력과 실패 사유가 없다")
    return {
        "source_row": row_card["source_row"],
        "id": row_card["id"],
        "action": result.parsed["action"],
        "decided_by": "MODEL",
        "failure": None,
        "rule_reason": None,
        "output": result.parsed,
        "escalated": escalated,
    }


def _append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


async def _call(row_card: dict[str, Any], client: Any, *, attempt_kind: str = "first") -> CallResult:
    return await client.call(
        stage="G0",
        unit_id=row_card["source_row"],
        variable_input=build_input(row_card),
        attempt_kind=attempt_kind,
        reasoning_effort="high" if attempt_kind == "escalate" else None,
        validator=lambda output: validate_output(row_card, output),
    )


async def run_g0(row_cards: list[dict[str, Any]], cfg: Config, run_dir: Path, client: Any) -> list[dict[str, Any]]:
    """G0 판정·검증·high 재판정 후 append-only g0/records.jsonl에 저장한다."""
    run_dir = Path(run_dir)
    records_path = run_dir / "g0" / "records.jsonl"
    existing: dict[int, dict[str, Any]] = {}
    if records_path.is_file():
        for line in records_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                existing[int(record["source_row"])] = record

    results: dict[int, dict[str, Any]] = {}
    pending_cards = []
    for card in row_cards:
        row = int(card["source_row"])
        prior = existing.get(row)
        if prior and (prior.get("decided_by") == "RULE" or
                      (prior.get("decided_by") == "MODEL" and prior.get("output") is not None)):
            results[row] = prior
        elif not card.get("inspected"):
            results[row] = rule_record(card)
        else:
            pending_cards.append(card)

    initial_results = await asyncio.gather(*(_call(card, client) for card in pending_cards))
    pending_by_row = {int(card["source_row"]): card for card in pending_cards}
    escalated_rows: set[int] = set()
    for card, result in zip(pending_cards, initial_results):
        row = int(card["source_row"])
        output = result.parsed or {}
        should_escalate = cfg.G0_ESCALATE and (
            result.status == "VALIDATION_FAIL" or needs_escalation(output, result.validation_errors)
        )
        results[row] = _record(card, result, escalated=False)
        if should_escalate:
            escalated_rows.add(row)

    checks = stage_end_checks(list(results.values()), row_cards)
    for check in checks:
        escalated_rows.update(check["source_rows"])
    escalated_rows = {
        row for row in escalated_rows
        if row in pending_by_row and not results[row].get("escalated")
    }
    high_cards = [pending_by_row[row] for row in sorted(escalated_rows)]
    high_results = await asyncio.gather(*(_call(card, client, attempt_kind="escalate") for card in high_cards))
    for card, result in zip(high_cards, high_results):
        row = int(card["source_row"])
        high_record = _record(card, result, escalated=True)
        if high_record.get("failure") and results[row].get("output"):
            results[row] = {**results[row], "escalated": True, "escalation_failure": high_record["failure"]}
        else:
            results[row] = high_record

    ordered = [results[int(card["source_row"])] for card in row_cards]
    additions = [
        record for record in ordered
        if existing.get(int(record["source_row"])) != record
    ]
    _append_jsonl(records_path, additions)
    _append_jsonl(run_dir / "g0" / "stage_checks.jsonl", checks)
    return ordered
