"""G2 — Task 설계 품질 검수 (모델, 행 1개 = 호출 1회) (설계 5.6)."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from ksco_qa.config import Config
from ksco_qa.dictionaries import (
    enum_values,
    g0_check_keys,
    g2_key_for,
    g2_overlap_keys,
)

_NUMBER_RE = re.compile(r"\d+(?:[,.]\d+)*")
_BLUEPRINT_FIELDS = ("scenario", "reference", "reasoning_map", "evaluation")
_SUCCESS_STATUSES = ("OK", "RETRIED")


def skip_record(source_row: int, skip_reason: str) -> dict[str, Any]:
    """평가 대상이 아닌 행을 규칙 기반 SKIPPED 기록으로 만든다."""
    return {
        "source_row": source_row,
        "status": "SKIPPED",
        "skip_reason": skip_reason,
        "decided_by": "RULE",
        "failure": None,
        "rule_reason": None,
        "flags": [],
        "output": None,
    }


def is_target(g0_record: dict[str, Any], g1_record: dict[str, Any]) -> bool:
    """G0가 KEEP/REGENERATE이고 G1이 확정 DUPLICATE가 아닌 행."""
    return g0_record.get("action") in ("KEEP", "REGENERATE") and g1_record.get("status") != "DUPLICATE"


def build_input(
    row_card: dict[str, Any],
    effective_task: str,
    g0_record: dict[str, Any],
    overlap_mode: str,
) -> dict[str, Any]:
    """행 카드와 effective_task만 보내고, AGREE_CHECK의 KEEP만 G0 점수를 덧붙인다."""
    allowed_modes = enum_values("g2_overlap_mode")
    if overlap_mode not in allowed_modes:
        raise ValueError(f"G2_OVERLAP_MODE {overlap_mode!r}는 허용값이 아니다: {allowed_modes}")
    if not isinstance(effective_task, str) or not effective_task.strip():
        raise ValueError(f"G2 입력의 effective_task가 비어 있다: {row_card.get('source_row')}")

    variable_input: dict[str, Any] = {
        "row_card": row_card,
        "effective_task": effective_task,
        "g2_overlap_mode": overlap_mode,
    }
    if overlap_mode == "AGREE_CHECK" and g0_record.get("action") == "KEEP":
        output = g0_record.get("output")
        checks = output.get("checks") if isinstance(output, dict) else None
        if not isinstance(checks, dict):
            raise ValueError(f"G2 입력에 필요한 G0 checks가 없다: {row_card.get('source_row')}")
        expected = set(g0_check_keys())
        if set(checks) != expected:
            raise ValueError(
                f"G2 입력의 G0 checks가 불완전하다: source_row={row_card.get('source_row')}, "
                f"missing={sorted(expected - set(checks))}, extra={sorted(set(checks) - expected)}"
            )
        variable_input["g0_checks"] = {
            g2_key_for(key): checks[key]
            for key in g0_check_keys()
        }
    return variable_input


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        return [str(value)]
    elif isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    elif isinstance(value, (list, tuple)):
        return [text for item in value for text in _strings(item)]
    return []


def _blueprint_number_warnings(row_card: dict[str, Any], output: dict[str, Any]) -> list[str]:
    allowed = {
        token.replace(",", "")
        for text in _strings(row_card)
        for token in _NUMBER_RE.findall(text)
    }
    blueprints = output.get("blueprints") or {}
    warnings = []
    for field in _BLUEPRINT_FIELDS:
        text = blueprints.get(field)
        if not isinstance(text, str):
            continue
        for token in _NUMBER_RE.findall(text):
            normalized = token.replace(",", "")
            if normalized not in allowed:
                warnings.append(f"BLUEPRINT_UNGROUNDED_NUMBER:{field}:{token}")
    return list(dict.fromkeys(warnings))


def validate_output(
    row_card: dict[str, Any],
    output: dict[str, Any],
    *,
    g0_checks: dict[str, str] | None = None,
    overlap_mode: str | None = None,
) -> tuple[list[str], list[str]]:
    """G2의 코드 검증 오류와 Blueprint 근거 경고를 반환한다."""
    errors: list[str] = []
    checks = {
        **(output.get("overlap_review", {}).get("checks") or {}),
        **(output.get("new_checks") or {}),
    }
    if output.get("verify_status") == "PASS" and "F" in checks.values():
        errors.append("하나 이상의 지표가 F인데 verify_status가 PASS이다")
    if output.get("verify_status") == "PASS" and output.get("b_coverage_status") in (
        "MISSING", "PARTIAL_CRITICAL"
    ):
        errors.append(f"b_coverage_status가 {output['b_coverage_status']}인데 verify_status가 PASS이다")

    reference_mode = row_card.get("reference_mode")
    reference_action = output.get("reference_action")
    reference_readiness = output.get("reference_readiness")
    if reference_mode == "GENERATE_REFERENCE" and reference_action != "GENERATE":
        errors.append("reference_mode가 GENERATE_REFERENCE인데 reference_action이 GENERATE가 아니다")
    if reference_mode == "GENERATE_REFERENCE" and reference_readiness != "BLUEPRINT_READY":
        errors.append("reference_mode가 GENERATE_REFERENCE인데 reference_readiness가 BLUEPRINT_READY가 아니다")
    if reference_mode == "UNRESOLVED_REFERENCE" and (
        reference_action != "CHECK_ACCESS" or reference_readiness != "HOLD"
    ):
        errors.append("UNRESOLVED_REFERENCE인데 reference_action=CHECK_ACCESS 또는 reference_readiness=HOLD가 아니다")

    conflict = output.get("reference_conflict")
    conflict_note = output.get("reference_conflict_note")
    if reference_mode != "PROVIDED_REFERENCE" and conflict is True:
        errors.append("PROVIDED_REFERENCE가 아닌데 reference_conflict가 true이다")
    if conflict is True and (not isinstance(conflict_note, str) or not conflict_note.strip()):
        errors.append("reference_conflict가 true인데 reference_conflict_note가 비어 있다")

    overlap_review = output.get("overlap_review") or {}
    overlap_checks = overlap_review.get("checks") or {}
    if overlap_mode is not None and overlap_review.get("mode") != overlap_mode:
        errors.append(f"overlap_review.mode가 입력 모드 {overlap_mode}와 다르다")
    disagreements = overlap_review.get("disagree") or []
    if g0_checks is None:
        if disagreements:
            errors.append("G0 checks가 입력에 없는데 overlap_review.disagree가 비어 있지 않다")
    else:
        expected_overlap = set(g2_overlap_keys())
        if set(g0_checks) != expected_overlap:
            errors.append("G2 입력의 G0 checks 지표가 10개 겹치는 지표와 일치하지 않는다")
        expected_disagreements = {
            key for key, value in g0_checks.items()
            if overlap_checks.get(key) != value
        }
        seen: set[str] = set()
        for item in disagreements:
            indicator = item.get("indicator")
            if indicator in seen:
                errors.append(f"같은 지표가 overlap_review.disagree에 중복되었다: {indicator}")
                continue
            seen.add(indicator)
            if indicator not in g0_checks:
                errors.append(f"입력에 없는 G0 지표가 overlap_review.disagree에 있다: {indicator}")
                continue
            if item.get("g0_value") != g0_checks[indicator]:
                errors.append(f"{indicator} disagree.g0_value가 입력의 G0 값과 다르다")
            if item.get("new_value") != overlap_checks.get(indicator):
                errors.append(f"{indicator} disagree.new_value가 overlap_review.checks와 다르다")
            if item.get("g0_value") == item.get("new_value"):
                errors.append(f"{indicator} G0 값과 new_value가 같은데 disagree로 기록되었다")
            if not isinstance(item.get("reason"), str) or not item["reason"].strip():
                errors.append(f"{indicator} disagree.reason이 비어 있다")
        for indicator in sorted(expected_disagreements - seen):
            errors.append(f"G0 값과 G2 checks가 다른데 disagree에 빠졌다: {indicator}")
        for indicator in sorted(seen - expected_disagreements):
            if indicator in g0_checks and overlap_checks.get(indicator) == g0_checks[indicator]:
                errors.append(f"{indicator} G0 값과 G2 checks가 같은데 disagree로 기록되었다")

    warnings = _blueprint_number_warnings(row_card, output)
    return errors, warnings


def _failure_record(
    row_card: dict[str, Any],
    status: str,
    validation_errors: list[str],
) -> dict[str, Any]:
    failure = "VALIDATION_FAILED" if status == "VALIDATION_FAIL" else "CALL_FAILED"
    return {
        "source_row": int(row_card["source_row"]),
        "id": row_card["id"],
        "status": "REVIEW",
        "skip_reason": None,
        "decided_by": "RULE",
        "failure": failure,
        "rule_reason": "; ".join(validation_errors) or status,
        "flags": [],
        "output": None,
    }


async def _call(
    row_card: dict[str, Any],
    effective_task: str,
    g0_record: dict[str, Any],
    cfg: Config,
    client: Any,
) -> dict[str, Any]:
    variable_input = build_input(row_card, effective_task, g0_record, cfg.G2_OVERLAP_MODE)
    validation_card = {**row_card, "effective_task": effective_task}
    g0_checks = variable_input.get("g0_checks")

    def validator(output: dict[str, Any]) -> list[str]:
        errors, _ = validate_output(
            validation_card,
            output,
            g0_checks=g0_checks,
            overlap_mode=cfg.G2_OVERLAP_MODE,
        )
        return errors

    result = await client.call(
        stage="G2",
        unit_id=row_card["source_row"],
        variable_input=variable_input,
        validator=validator,
    )
    if result.status not in _SUCCESS_STATUSES or result.parsed is None:
        return _failure_record(row_card, result.status, result.validation_errors)

    errors, flags = validate_output(
        validation_card,
        result.parsed,
        g0_checks=g0_checks,
        overlap_mode=cfg.G2_OVERLAP_MODE,
    )
    if errors:
        return _failure_record(row_card, "VALIDATION_FAIL", errors)
    return {
        "source_row": int(row_card["source_row"]),
        "id": row_card["id"],
        "status": result.parsed["verify_status"],
        "skip_reason": None,
        "decided_by": "MODEL",
        "failure": None,
        "rule_reason": None,
        "flags": flags,
        "output": result.parsed,
    }


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: JSONL 레코드가 잘못되었다") from error
    return records


def _append_records(path: Path, records: list[dict[str, Any]]) -> None:
    latest = {int(record["source_row"]): record for record in _read_records(path)}
    additions = [record for record in records if latest.get(int(record["source_row"])) != record]
    if not additions:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as stream:
        for record in additions:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        stream.flush()


async def run_g2(
    row_cards: list[dict[str, Any]],
    g0_records: list[dict[str, Any]],
    g1_records: dict[int, dict[str, Any]],
    cfg: Config,
    run_dir: Path,
    client: Any,
) -> list[dict[str, Any]]:
    """대상 행별 G2 판정과 규칙상 SKIPPED를 추가 전용 JSONL에 저장한다."""
    from ksco_qa.stages.g1a import effective_tasks

    cards_by_row = {int(card["source_row"]): card for card in row_cards}
    g0_by_row = {int(record["source_row"]): record for record in g0_records}
    effective = effective_tasks(row_cards, g0_records)
    if set(g0_by_row) != set(cards_by_row):
        raise ValueError("G2 실행 전에 모든 row_card에 대응하는 G0 기록이 있어야 한다")
    if set(g1_records) != set(cards_by_row):
        raise ValueError("G2 실행 전에 모든 row_card에 대응하는 G1 기록이 있어야 한다")

    pending: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
    results: dict[int, dict[str, Any]] = {}
    for row, card in cards_by_row.items():
        g0_record = g0_by_row[row]
        g1_record = g1_records[row]
        if g0_record.get("id") != card.get("id") or g1_record.get("id") != card.get("id"):
            raise ValueError(f"G2 입력 id가 row_card와 다르다: source_row={row}")
        action = g0_record.get("action")
        if action not in ("KEEP", "REGENERATE", "REVIEW_B", "RESELECT_B"):
            raise ValueError(f"G2 입력의 G0 action이 잘못되었다: source_row={row}, action={action!r}")
        if g1_record.get("status") not in ("UNIQUE", "DUPLICATE", "REVIEW", "NOT_EVALUATED"):
            raise ValueError(f"G2 입력의 G1 status가 잘못되었다: source_row={row}")

        if g1_record["status"] == "DUPLICATE":
            record = skip_record(row, "DUPLICATE_TASK")
            record["id"] = card["id"]
            results[row] = record
        elif action in ("REVIEW_B", "RESELECT_B"):
            record = skip_record(row, f"G0_{action}")
            record["id"] = card["id"]
            results[row] = record
        elif row not in effective:
            record = skip_record(row, "NO_EFFECTIVE_TASK")
            record["id"] = card["id"]
            results[row] = record
        elif g1_record["status"] == "NOT_EVALUATED":
            raise ValueError(f"G1이 미평가인데 effective_task가 있다: source_row={row}")
        elif is_target(g0_record, g1_record):
            pending.append((card, effective[row], g0_record))
        else:
            raise ValueError(f"G2 대상 선택이 정의되지 않았다: source_row={row}")

    called = await asyncio.gather(*(
        _call(card, task, g0_record, cfg, client)
        for card, task, g0_record in pending
    ))
    results.update((int(record["source_row"]), record) for record in called)
    ordered = [results[int(card["source_row"])] for card in row_cards]
    _append_records(Path(run_dir) / "g2" / "records.jsonl", ordered)
    return ordered
