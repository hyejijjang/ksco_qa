"""G1b — 쌍 판정 (모델, 묶음 1개 = 호출 1회) (설계 5.4 / 00_Work_Run.md 5.2)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ksco_qa.config import Config
from ksco_qa.llm.types import CallResult

VERDICTS = ("EXACT", "SEMANTIC", "PARAMETER_VARIANT", "HIGH_OVERLAP", "DISTINCT", "UNCERTAIN")


def _pair_key(pair: tuple[int, int]) -> tuple[int, int]:
    return min(pair), max(pair)


def build_input(
    bundle: list[tuple[int, int]],
    row_cards: dict[int, dict[str, Any]],
    effective: dict[int, Any],
) -> dict[str, Any]:
    """묶음의 행 입력과 판정 대상 쌍만 구성한다."""
    normalized = [tuple(map(int, pair)) for pair in bundle]
    if not normalized:
        raise ValueError("G1b bundle에 판정할 쌍이 없다")
    rows_in_bundle = sorted({row for pair in normalized for row in pair})
    rows = []
    for source_row in rows_in_bundle:
        card = row_cards.get(source_row)
        if card is None:
            raise ValueError(f"G1b bundle에 row_card가 없는 행이 있다: {source_row}")
        effective_task = effective.get(source_row)
        if not isinstance(effective_task, str) or not effective_task.strip():
            raise ValueError(f"G1b bundle 행의 effective_task가 비어 있다: {source_row}")
        g0_output = card.get("_g0_output")
        task_card = g0_output.get("task_card") if isinstance(g0_output, dict) else card.get("task_card")
        if not isinstance(task_card, dict):
            raise ValueError(f"G1b bundle 행의 task_card가 없다: {source_row}")
        rows.append({
            "source_row": source_row,
            "job": card.get("job"),
            "deliverable_title": card.get("deliverable_title"),
            "format": card.get("format"),
            "effective_task": effective_task,
            "task_card": task_card,
        })
    return {"rows": rows, "pairs": [list(pair) for pair in normalized]}


def missing_pairs(bundle: list[tuple[int, int]], output: dict[str, Any]) -> list[tuple[int, int]]:
    """모델 출력에서 빠진 입력 쌍만 돌려준다."""
    result_pairs = output.get("pairs")
    if not isinstance(result_pairs, list):
        return list(bundle)
    counts = Counter(
        (item.get("row_1"), item.get("row_2"))
        for item in result_pairs
        if isinstance(item, dict)
    )
    return [pair for pair in bundle if counts[pair] == 0]


def validate_output(
    bundle: list[tuple[int, int]],
    rows: set[int],
    output: dict[str, Any],
    *,
    require_coverage: bool = True,
) -> list[str]:
    """요청 쌍의 정확한 1:1 판정과 added_pairs의 묶음 내 유효성을 검증한다."""
    errors: list[str] = []
    requested = [tuple(map(int, pair)) for pair in bundle]
    requested_counts = Counter(requested)
    result_pairs = output.get("pairs")
    if not isinstance(result_pairs, list):
        return ["pairs가 배열이 아니다"]
    actual_counts = Counter(
        (item.get("row_1"), item.get("row_2"))
        for item in result_pairs
        if isinstance(item, dict)
    )
    if require_coverage:
        for pair in missing_pairs(requested, output):
            errors.append(f"입력 쌍이 출력에서 누락되었다: {pair}")
    for pair, request_count in requested_counts.items():
        if request_count > 1:
            errors.append(f"입력 묶음에 같은 쌍이 중복되었다: {pair}")
        if actual_counts[pair] > 1:
            errors.append(f"입력 쌍이 중복 판정되었다: {pair}")
    for pair in actual_counts:
        if pair not in requested_counts:
            errors.append(f"요청하지 않은 쌍이 pairs에 있다: {pair}")

    def validate_pair(item: Any, label: str) -> tuple[int, int] | None:
        if not isinstance(item, dict):
            errors.append(f"{label} 항목이 객체가 아니다")
            return None
        left, right = item.get("row_1"), item.get("row_2")
        if not isinstance(left, int) or isinstance(left, bool) or not isinstance(right, int) or isinstance(right, bool):
            errors.append(f"{label} row_1·row_2는 정수여야 한다")
            return None
        pair = (left, right)
        if left >= right:
            errors.append(f"{label} 행 번호는 오름차순으로 서로 달라야 한다: {pair}")
        if left not in rows or right not in rows:
            errors.append(f"{label} 행이 이번 묶음 밖에 있다: {pair}")
        if item.get("verdict") not in VERDICTS:
            errors.append(f"{label} verdict가 허용 목록에 없다")
        evidence = item.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            errors.append(f"{label} evidence가 비어 있다")
        conclusion = item.get("conclusion")
        if item.get("verdict") == "DISTINCT":
            if conclusion is not None:
                errors.append(f"{label} DISTINCT conclusion은 null이어야 한다")
        elif not isinstance(conclusion, str) or not conclusion.strip():
            errors.append(f"{label} {item.get('verdict')} conclusion이 비어 있다")
        return pair

    for item in result_pairs:
        validate_pair(item, "pairs")

    added_pairs = output.get("added_pairs")
    if not isinstance(added_pairs, list):
        errors.append("added_pairs가 배열이 아니다")
        return errors
    added_seen: set[tuple[int, int]] = set()
    requested_set = set(requested_counts)
    for item in added_pairs:
        pair = validate_pair(item, "added_pairs")
        if pair is None:
            continue
        key = _pair_key(pair)
        if key in requested_set:
            errors.append(f"added_pairs에 요청한 쌍이 다시 들어 있다: {pair}")
        if key in added_seen:
            errors.append(f"added_pairs에 같은 쌍이 중복되었다: {pair}")
        added_seen.add(key)
    return errors


def _append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        stream.flush()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: JSONL 레코드가 잘못되었다") from error
    return records


def _record_pair(
    item: dict[str, Any],
    *,
    bundle_id: str,
    call_id: str,
    added: bool,
    status: str,
    candidate_meta: dict[tuple[int, int], dict[str, Any]],
) -> dict[str, Any]:
    row_1, row_2 = int(item["row_1"]), int(item["row_2"])
    candidate = candidate_meta.get(_pair_key((row_1, row_2)), {})
    return {
        "source_rows": [row_1, row_2],
        "verdict": item["verdict"],
        "evidence": item["evidence"],
        "conclusion": item["conclusion"],
        "signals": candidate.get("signals", []),
        "similarities": candidate.get("similarities", {}),
        "similarity": candidate.get("similarity"),
        "bundle_id": bundle_id,
        "call_id": call_id,
        "added": added,
        "status": status,
        "failure": None,
    }


async def _call_bundle(
    bundle_index: int,
    bundle: list[tuple[int, int]],
    row_cards: dict[int, dict[str, Any]],
    effective: dict[int, str],
    client: Any,
    *,
    require_coverage: bool = False,
) -> tuple[str, CallResult]:
    variable_input = build_input(bundle, row_cards, effective)
    rows = {int(row["source_row"]) for row in variable_input["rows"]}
    bundle_hash = hashlib.sha256(
        json.dumps(variable_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    bundle_id = f"bundle-{bundle_index}-{bundle_hash}"
    return bundle_id, await client.call(
        stage="G1B",
        unit_id=bundle_id,
        variable_input=variable_input,
        validator=lambda output: validate_output(bundle, rows, output, require_coverage=require_coverage),
    )


async def run_g1b(
    bundles: list[list[tuple[int, int]]],
    row_cards: list[dict[str, Any]],
    cfg: Config,
    run_dir: Path,
    client: Any,
    *,
    g0_records: list[dict[str, Any]] | None = None,
    effective: dict[int, str] | None = None,
    candidate_pairs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """쌍 묶음별 판정 후 _work/g1/pairs.jsonl에 결과를 추가 전용으로 쓴다."""
    cards_by_row = {int(card["source_row"]): card for card in row_cards}
    g0_by_row = {int(record["source_row"]): record for record in (g0_records or [])}
    if effective is None:
        from ksco_qa.stages.g1a import effective_tasks

        effective = effective_tasks(row_cards, g0_records or [])
    model_rows = {
        row: {
            **card,
            "_g0_output": (g0_by_row.get(row) or {}).get("output"),
        }
        for row, card in cards_by_row.items()
    }
    candidate_meta = {
        _pair_key(tuple(map(int, candidate["rows"]))): candidate
        for candidate in (candidate_pairs or [])
    }
    requested_by_bundle = [
        [tuple(map(int, pair)) for pair in bundle]
        for bundle in bundles
    ]
    all_requested: set[tuple[int, int]] = set()
    for index, bundle in enumerate(requested_by_bundle, start=1):
        if not bundle:
            raise ValueError(f"G1b bundle {index}에 쌍이 없다")
        for pair in bundle:
            if pair[0] >= pair[1]:
                raise ValueError(f"G1b bundle {index}의 행 쌍은 오름차순이어야 한다: {pair}")
            if pair in all_requested:
                raise ValueError(f"G1b candidate pair가 여러 bundle에 중복되었다: {pair}")
            all_requested.add(pair)
        if len(bundle) > cfg.G1_PAIRS_PER_CALL:
            raise ValueError(f"G1b bundle {index}이 G1_PAIRS_PER_CALL을 초과한다: {len(bundle)}")
        if len({row for pair in bundle for row in pair}) > 20:
            raise ValueError(f"G1b bundle {index}이 20개 행 제한을 초과한다")
    for row, card in cards_by_row.items():
        g0_record = g0_by_row.get(row)
        if g0_record is not None and g0_record.get("id") != card.get("id"):
            raise ValueError(f"G1b 입력의 G0 id가 row_card와 다르다: source_row={row}")

    results = await asyncio.gather(*(
        _call_bundle(index, bundle, model_rows, effective, client)
        for index, bundle in enumerate(requested_by_bundle, start=1)
    ))

    async def recover_missing(
        bundle: list[tuple[int, int]], bundle_id: str, result: CallResult
    ) -> tuple[list[tuple[int, int]], CallResult] | None:
        if result.parsed is None:
            return None
        missing = missing_pairs(bundle, result.parsed)
        if not missing:
            return None
        variable_input = build_input(missing, model_rows, effective)
        rows = {int(row["source_row"]) for row in variable_input["rows"]}
        missing_hash = hashlib.sha256(
            json.dumps(variable_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:12]
        retry = await client.call(
            stage="G1B",
            unit_id=f"{bundle_id}-missing-{missing_hash}",
            variable_input=variable_input,
            validator=lambda output: validate_output(missing, rows, output),
        )
        return missing, retry

    recoveries = await asyncio.gather(*(
        recover_missing(bundle, bundle_id, result)
        for bundle, (bundle_id, result) in zip(requested_by_bundle, results)
    ))

    path = Path(run_dir) / "g1" / "pairs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    existing = _read_jsonl(path)
    latest_by_key = {
        (record.get("call_id"), tuple(record.get("source_rows", [])), bool(record.get("added"))): record
        for record in existing
    }
    output_records: list[dict[str, Any]] = []
    active_call_ids: dict[str, set[str]] = {}
    for bundle, (bundle_id, initial), recovery in zip(requested_by_bundle, results, recoveries):
        active_call_ids.setdefault(bundle_id, set()).add(initial.call_id)
        outcomes: list[tuple[list[tuple[int, int]], CallResult]] = [(bundle, initial)]
        if recovery is not None:
            missing, recovered = recovery
            outcomes.append((missing, recovered))
            active_call_ids[bundle_id].add(recovered.call_id)

        seen_added = {_pair_key(pair) for pair in bundle}
        for requested_pairs, result in outcomes:
            if result.parsed is None:
                for row_1, row_2 in requested_pairs:
                    candidate = candidate_meta.get(_pair_key((row_1, row_2)), {})
                    record = {
                        "source_rows": [row_1, row_2],
                        "verdict": None,
                        "evidence": None,
                        "conclusion": None,
                        "signals": candidate.get("signals", []),
                        "similarities": candidate.get("similarities", {}),
                        "similarity": candidate.get("similarity"),
                        "bundle_id": bundle_id,
                        "call_id": result.call_id,
                        "added": False,
                        "status": result.status,
                        "failure": result.validation_errors or [result.status],
                    }
                    key = (record["call_id"], (row_1, row_2), False)
                    if latest_by_key.get(key) != record:
                        output_records.append(record)
                        latest_by_key[key] = record
                continue

            for added, items in ((False, result.parsed["pairs"]), (True, result.parsed["added_pairs"])):
                for item in items:
                    normalized_pair = _pair_key((int(item["row_1"]), int(item["row_2"])))
                    if added and normalized_pair in seen_added:
                        continue
                    if added:
                        seen_added.add(normalized_pair)
                    record = _record_pair(
                        item,
                        bundle_id=bundle_id,
                        call_id=result.call_id,
                        added=added,
                        status=result.status,
                        candidate_meta=candidate_meta,
                    )
                    ordered_pair = tuple(record["source_rows"])
                    key = (record["call_id"], ordered_pair, added)
                    if latest_by_key.get(key) != record:
                        output_records.append(record)
                        latest_by_key[key] = record

    _append_jsonl(path, output_records)
    latest: dict[tuple[tuple[int, int], bool], dict[str, Any]] = {}
    for record in existing + output_records:
        if record["bundle_id"] not in active_call_ids:
            continue
        if record["call_id"] not in active_call_ids[record["bundle_id"]]:
            continue
        key = (tuple(record.get("source_rows", [])), bool(record.get("added")))
        latest[key] = record
    return list(latest.values())
