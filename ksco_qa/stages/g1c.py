"""G1c — 중복 그룹 확정 (코드 + 필요한 대표 직접 검증) (설계 5.5)."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from ksco_qa.config import Config
from ksco_qa.stages.g1a import make_bundles
from ksco_qa.stages.g1b import run_g1b

CONFIRMED_VERDICTS = ("EXACT", "SEMANTIC", "PARAMETER_VARIANT")
MAX_DIRECT_CHECK_ROUNDS = 2


def _pair_key(pair: tuple[int, int]) -> tuple[int, int]:
    return min(pair), max(pair)


def _record_pair(record: dict[str, Any]) -> tuple[int, int] | None:
    rows = record.get("source_rows")
    if not isinstance(rows, list) or len(rows) != 2:
        return None
    left, right = rows
    if not isinstance(left, int) or not isinstance(right, int) or left == right:
        return None
    return _pair_key((left, right))


def _successful_pairs(pairs: list[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
    latest: dict[tuple[int, int], dict[str, Any]] = {}
    for record in pairs:
        key = _record_pair(record)
        if key is not None:
            latest[key] = record
    return {
        pair: record
        for pair, record in latest.items()
        if record.get("status") in ("OK", "RETRIED") and record.get("verdict") in (
            *CONFIRMED_VERDICTS, "HIGH_OVERLAP", "DISTINCT", "UNCERTAIN"
        )
    }


def build_groups(pairs: list[dict[str, Any]]) -> list[set[int]]:
    """확정 verdict 쌍의 연결 요소를 반환한다."""
    adjacency: dict[int, set[int]] = defaultdict(set)
    for record in _successful_pairs(pairs).values():
        if record.get("verdict") not in CONFIRMED_VERDICTS:
            continue
        left, right = record["source_rows"]
        adjacency[left].add(right)
        adjacency[right].add(left)

    groups: list[set[int]] = []
    unseen = set(adjacency)
    while unseen:
        start = min(unseen)
        unseen.remove(start)
        group = {start}
        stack = [start]
        while stack:
            current = stack.pop()
            for neighbor in sorted(adjacency[current] & unseen):
                unseen.remove(neighbor)
                group.add(neighbor)
                stack.append(neighbor)
        groups.append(group)
    return sorted(groups, key=lambda group: min(group))


def choose_representative(
    group: set[int],
    row_cards: dict[int, dict[str, Any]],
    g0_records: dict[int, dict[str, Any]],
) -> int:
    """검사 가능성 → 직무 적합성 → G0 PASS 수 → 작은 원본 행 순."""
    if not group:
        raise ValueError("대표 행을 정할 그룹이 비어 있다")

    def rank(row: int) -> tuple[int, int, int, int]:
        card = row_cards.get(row, {})
        g0 = g0_records.get(row, {})
        output = g0.get("output") or {}
        checks = output.get("checks") or {}
        return (
            int(bool(card.get("inspected"))),
            int(checks.get("job_fit") == "P"),
            sum(value == "P" for value in checks.values()),
            -row,
        )

    return max(group, key=rank)


def missing_direct_pairs(
    group: set[int], representative: int, pairs: list[dict[str, Any]]
) -> list[tuple[int, int]]:
    """대표와 직접 판정이 아직 없는 그룹 구성원의 쌍."""
    adjudicated = set(_successful_pairs(pairs))
    return [
        _pair_key((representative, row))
        for row in sorted(group - {representative})
        if _pair_key((representative, row)) not in adjudicated
    ]


def assign_status(
    row_cards: list[dict[str, Any]],
    groups: list[set[int]],
    representatives: dict[int, int],
    pairs: list[dict[str, Any]],
    *,
    active_rows: set[int] | None = None,
    search_completed: bool = True,
) -> dict[int, dict[str, Any]]:
    """행별 G1 기록을 만들며 미완료 탐색·미판정 후보는 UNIQUE로 오인하지 않는다."""
    cards_by_row = {int(card["source_row"]): card for card in row_cards}
    successful = _successful_pairs(pairs)
    all_pair_records: dict[tuple[int, int], dict[str, Any]] = {}
    for pair in pairs:
        key = _record_pair(pair)
        if key is not None:
            all_pair_records[key] = pair
    active = active_rows if active_rows is not None else set(cards_by_row)

    row_to_group: dict[int, tuple[int, set[int]]] = {}
    for index, group in enumerate(groups, start=1):
        for row in group:
            row_to_group[row] = (index, group)

    output: dict[int, dict[str, Any]] = {}
    for row, card in cards_by_row.items():
        related_pairs = sorted(
            (pair for pair in all_pair_records if row in pair),
            key=lambda pair: pair[1] if pair[0] == row else pair[0],
        )
        candidate_pairs = []
        candidate_rows = []
        unresolved = 0
        adjudicated = 0
        for pair in related_pairs:
            record = all_pair_records[pair]
            other = pair[1] if pair[0] == row else pair[0]
            candidate_rows.append(other)
            if record.get("verdict") in CONFIRMED_VERDICTS + ("HIGH_OVERLAP", "DISTINCT", "UNCERTAIN") and record.get(
                "status"
            ) in ("OK", "RETRIED"):
                adjudicated += 1
            else:
                unresolved += 1
            candidate_pairs.append({
                "row": other,
                "signals": list(record.get("signals") or []),
                "similarity": record.get("similarity"),
                "verdict": record.get("verdict"),
                "evidence": record.get("evidence"),
            })

        group_info = row_to_group.get(row)
        representative = None
        group_name = None
        status: str
        duplicate_type: str
        reason: str
        if row not in active:
            status, duplicate_type = "NOT_EVALUATED", "UNDETERMINED"
            reason = "G0 유효 Task 없음"
        elif group_info is not None:
            group_index, group = group_info
            representative = representatives[group_index]
            group_name = f"G1-{group_index}"
            if row == representative:
                status = "UNIQUE"
                touching_confirmed = [
                    record for pair, record in successful.items()
                    if row in pair and pair[0] in group and pair[1] in group
                    and record.get("verdict") in CONFIRMED_VERDICTS
                ]
                duplicate_type = touching_confirmed[0]["verdict"] if touching_confirmed else "NONE"
                reason = f"중복 그룹 대표 (그룹 {group_name})"
            else:
                direct = successful.get(_pair_key((representative, row)))
                if direct is not None and direct.get("verdict") in CONFIRMED_VERDICTS:
                    status = "DUPLICATE"
                    duplicate_type = direct["verdict"]
                    reason = f"대표 행 {representative}와 직접 확인된 확정 중복"
                elif direct is not None:
                    status, duplicate_type = "REVIEW", "UNDETERMINED"
                    reason = f"그룹 연결과 대표 행 {representative}의 직접 판정이 일치하지 않음"
                else:
                    status, duplicate_type = "REVIEW", "UNDETERMINED"
                    reason = f"대표 행 {representative}와 직접 비교 미완료"
            if unresolved:
                status, duplicate_type = "REVIEW", "UNDETERMINED"
                reason = f"미판정 후보 {unresolved}개"
        elif unresolved:
            status, duplicate_type = "REVIEW", "UNDETERMINED"
            reason = f"미판정 후보 {unresolved}개"
        elif not search_completed:
            status, duplicate_type = "REVIEW", "UNDETERMINED"
            reason = "기록된 검색 범위의 탐색 미완료"
        else:
            status, duplicate_type = "UNIQUE", "NONE"
            reason = "모든 후보를 판정했으며 확정 중복 없음"

        if status == "NOT_EVALUATED":
            overlap_status = "UNDETERMINED"
        elif any(
            successful.get(pair, {}).get("verdict") == "HIGH_OVERLAP"
            for pair in related_pairs
        ):
            overlap_status = "HIGH_OVERLAP"
        elif unresolved or not search_completed:
            overlap_status = "UNDETERMINED"
        else:
            overlap_status = "NONE"

        row_search_complete = (
            status != "NOT_EVALUATED"
            and search_completed
            and unresolved == 0
            and not (status == "REVIEW" and "직접 비교 미완료" in reason)
        )
        output[row] = {
            "source_row": row,
            "id": card["id"],
            "status": status,
            "duplicate_type": duplicate_type,
            "overlap_status": overlap_status,
            "representative_row": representative,
            "representative_id": cards_by_row[representative]["id"] if status == "DUPLICATE" and representative else (
                card["id"] if status == "UNIQUE" and group_info is not None else None
            ),
            "group": group_name,
            "compared_rows": sorted(set(candidate_rows)),
            "candidate_rows": sorted(set(candidate_rows)),
            "candidate_pairs": candidate_pairs,
            "candidate_count": len(set(candidate_rows)),
            "adjudicated_candidate_count": adjudicated,
            "unresolved_candidate_count": unresolved,
            "search_scope": "전체 데이터 행 중 effective_task가 있는 행",
            "search_completed": row_search_complete,
            "reason": reason,
            "decided_by": "MODEL" if row in active else "RULE",
        }
    return output


def assign_overlap_status(source_row: int, pairs: list[dict[str, Any]], evaluated: bool) -> str:
    """해당 행 쌍 판정으로 HIGH_OVERLAP/NONE/UNDETERMINED를 채운다."""
    if not evaluated:
        return "UNDETERMINED"
    verdicts = [
        record.get("verdict")
        for record in _successful_pairs(pairs).values()
        if source_row in record["source_rows"]
    ]
    if "HIGH_OVERLAP" in verdicts:
        return "HIGH_OVERLAP"
    if verdicts:
        return "NONE"
    return "UNDETERMINED"


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


def _write_rows(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    latest = {
        int(record["source_row"]): record
        for record in _read_records(path)
    }
    additions = [record for record in rows if latest.get(int(record["source_row"])) != record]
    if additions:
        with open(path, "a", encoding="utf-8", newline="\n") as stream:
            for record in additions:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()


async def run_g1c(
    row_cards: list[dict[str, Any]],
    g0_records: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    cfg: Config,
    run_dir: Path,
    client: Any,
    *,
    candidate_pairs: list[dict[str, Any]] | None = None,
    search_completed: bool = True,
    effective: dict[int, str] | None = None,
) -> dict[int, dict[str, Any]]:
    """확정 중복 그룹을 만들고 대표-구성원 직접 검증을 최대 두 차례 수행한다."""
    cards_by_row = {int(card["source_row"]): card for card in row_cards}
    g0_by_row = {int(record["source_row"]): record for record in g0_records}
    if effective is None:
        from ksco_qa.stages.g1a import effective_tasks

        effective = effective_tasks(row_cards, g0_records)
    metadata = {
        _pair_key(tuple(map(int, candidate["rows"]))): candidate
        for candidate in (candidate_pairs or [])
    }

    def merged_pairs() -> list[dict[str, Any]]:
        records_by_pair: dict[tuple[int, int], dict[str, Any]] = {}
        for record in pairs:
            key = _record_pair(record)
            if key is not None:
                records_by_pair[key] = record
        for key, candidate in metadata.items():
            existing = records_by_pair.get(key)
            if existing is None:
                records_by_pair[key] = {
                    "source_rows": list(key),
                    "verdict": None,
                    "evidence": None,
                    "signals": list(candidate.get("signals") or []),
                    "similarities": candidate.get("similarities") or {},
                    "similarity": candidate.get("similarity"),
                    "status": "NOT_CALLED",
                    "added": False,
                }
            else:
                existing.setdefault("signals", list(candidate.get("signals") or []))
                existing.setdefault("similarities", candidate.get("similarities") or {})
                existing.setdefault("similarity", candidate.get("similarity"))
        return list(records_by_pair.values())

    for _ in range(MAX_DIRECT_CHECK_ROUNDS):
        current = merged_pairs()
        groups = build_groups(current)
        representatives = {
            index: choose_representative(group, cards_by_row, g0_by_row)
            for index, group in enumerate(groups, start=1)
        }
        missing = sorted({
            pair
            for index, group in enumerate(groups, start=1)
            for pair in missing_direct_pairs(group, representatives[index], current)
        })
        if not missing:
            break
        bundles = make_bundles(missing, cfg.G1_PAIRS_PER_CALL, max_rows=20)
        direct_candidates = [
            {"rows": list(pair), "signals": [], "similarities": {}, "similarity": None}
            for pair in missing
        ]
        new_records = await run_g1b(
            bundles,
            row_cards,
            cfg,
            run_dir,
            client,
            g0_records=g0_records,
            effective=effective,
            candidate_pairs=[*metadata.values(), *direct_candidates],
        )
        # Keep raw pair history append-only; consume the latest records for every pair.
        pair_path = Path(run_dir) / "g1" / "pairs.jsonl"
        pairs = [*pairs, *_read_records(pair_path)] if pair_path.is_file() else [*pairs, *new_records]

    current = merged_pairs()
    groups = build_groups(current)
    representatives = {
        index: choose_representative(group, cards_by_row, g0_by_row)
        for index, group in enumerate(groups, start=1)
    }
    active = set(effective)
    rows = assign_status(
        row_cards,
        groups,
        representatives,
        current,
        active_rows=active,
        search_completed=search_completed,
    )
    _write_rows([rows[row] for row in sorted(rows)], Path(run_dir) / "g1" / "rows.jsonl")
    return rows
