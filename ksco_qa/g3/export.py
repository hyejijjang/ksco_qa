"""G3 최종 레코드·내보내기 (설계 5.7, 7.4, 9.2 / 06_Result_Schema.md / CLAUDE.md M1 결정 G3).

모델을 부르지 않고 run 폴더의 단계 기록(g3.records)만 읽는다. 판정을 만들지 않는다:
단계 판정은 기록 그대로 옮기고, 최종 판정은 final_rules로만 정한다.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from ksco_qa.config import Config
from ksco_qa.dictionaries import criterion_for
from ksco_qa.g3.final_rules import FinalInputs, NoRuleMatched, decide_final

SCHEMA_VERSION = "ksco-taskqa/canonical-1.0"
CALL_STAGES = ("G0", "G1B", "G2")
SHEET_NAME = "DataList"

GATE_FILES = ("00_revision_regenerate.xlsx", "01_duplicate_audit.xlsx", "02_task_verify.xlsx")
FINAL_JSONL = "03_final.jsonl"
FINAL_OUTPUTS = ("00_mapping_audit.csv", *GATE_FILES, FINAL_JSONL)

# Gate별 xlsx 추가 열 = 00_Work_Run.md 4·5·6장 "행별 기록" 열 목록 그대로 (G1은 audit 열 + coverage 열, 설계 5.5)
REVISION_COLUMNS = ["source_row", "id", "revision_action", "original_task", "regenerated_task_new", "effective_task",
                    "revision_reason", "revision_evidence", "expected_reference_spec", "g0_self_check"]
DUPLICATE_COLUMNS = ["duplicate_status", "duplicate_type", "duplicate_group", "duplicate_of_row", "duplicate_of_id",
                     "overlap_status", "compared_rows", "duplicate_reason", "audit_completeness",
                     "candidate_count", "adjudicated_candidate_count", "unresolved_candidate_count",
                     "search_scope", "search_completed"]
VERIFY_COLUMNS = ["verify_status", "verify_flags", "verify_checks_json", "b_coverage_status", "reference_mode",
                  "reference_action", "reference_readiness", "scenario_blueprint_json", "reference_blueprint_json",
                  "reasoning_map_json", "evaluation_blueprint_json", "verify_reason", "proposed_fix"]

# revision.criterion: 00_Work_Run.md 4.2의 action 정의 원문 (굵은 글씨 표시만 뺌)
ACTION_CRITERION = {
    "KEEP": "기존 Task가 필수 조건을 충족하고, 바꾸더라도 문체 변경 정도의 이득만 있음. 원본 G열을 effective_task로 그대로 사용.",
    "REGENERATE": "원본 Task에 확인된 결함이 있고, Deliverable Files 및 직무정보 근거로 개선 가능. 이번 실행에서 새 Task를 실제 작성하고, 기존 대비 무엇을 왜 고쳤는지 기록. effective_task=regenerated_task_new.",
    "REVIEW_B": "Deliverable의 핵심 구조 또는 필수 근거를 확인할 수 없어서 채택/수정을 확정할 수 없음. effective_task=null.",
    "RESELECT_B": "연결된 Deliverable 자체가 해당 직업·Task의 유효한 결과물로 보기 어렵고 문장 수정으로 해결되지 않음. effective_task=null.",
}
CONCLUSION_REASON_CHARS = 150  # revision.conclusion = "{action}: {revision_reason 앞 150자}" (2026-10-22 결정)
REASON_CODE_TEXT = {
    "DUPLICATE": "확정 중복으로 제외", "RESELECT_B": "Deliverable 재선정 필요", "G2_FAIL": "Task 설계 품질 FAIL",
    "P0_NOT_FOUND": "Deliverable 파일 없음", "P0_AMBIGUOUS": "같은 이름 파일 여러 개", "P0_CONFLICT": "D/F열 결함",
    "P0_INACCESSIBLE": "파일 열 수 없음", "P0_INVENTORY_INCOMPLETE": "인벤토리 불완전", "NOT_INSPECTED": "파일 내용 미확인",
    "ORIGINAL_TASK_EMPTY": "원본 Task 없음", "G0_REVIEW_B": "G0 REVIEW_B", "G0_CALL_FAILED": "G0 호출 2회 실패",
    "G0_VALIDATION_FAILED": "G0 검증 2회 실패", "G1_REVIEW": "중복 판정 REVIEW", "G1_INCOMPLETE": "중복 검색 미완료",
    "G2_REVIEW": "Task 설계 품질 REVIEW", "G2_INCOMPLETE": "G2 미완료", "G2_CALL_FAILED": "G2 호출 2회 실패",
    "G2_VALIDATION_FAILED": "G2 검증 2회 실패",
    "REFERENCE_UNRESOLVED": "Reference 연결 불명", "REFERENCE_HOLD": "Reference 준비 보류",
    "REFERENCE_CONFLICT": "Reference 구조 충돌·정답 누출",
}
NEXT_ACTION_TEXT = {
    "HANDOFF_TO_AI_TEAM": "AI실 인계", "EXCLUDE_DUPLICATE": "중복 제외", "REVISE_TASK": "Task 수정",
    "RESELECT_DELIVERABLE": "Deliverable 재선정", "CHECK_ASSETS": "자료(파일·Reference) 확인",
    "CHECK_DUPLICATE": "중복 여부 확인", "REVIEW_MANUAL": "사람 검토",
}
CHECK_STATUS_MAP = {"P": "PASS", "R": "REVIEW", "F": "FAIL", "NA": "N_A"}


# --- 실행 방식 기록 ---


def execution_notes_object(*, run_id: str, llm: str, cfg: Config, prompt_versions: dict[str, str]) -> dict[str, Any]:
    """run_report.json에 남길 실행 방식 객체 (7.4). mock run이면 "MOCK"을 기록해 실제 결과와 구분한다."""
    mock = llm == "mock"
    return {
        "pipeline": "API 파이프라인",
        "llm": "MOCK" if mock else "OPENAI",
        "run_id": run_id,
        "mode": cfg.MODE,
        "models": {s: ("mock" if mock else getattr(cfg, f"MODEL_{s}")) for s in CALL_STAGES},
        "reasoning_effort": {s: getattr(cfg, f"EFFORT_{s}") for s in CALL_STAGES},
        "prompt_versions": dict(prompt_versions),
        "G2_OVERLAP_MODE": cfg.G2_OVERLAP_MODE,
        "review_independence": "SEPARATE_CALL",
    }


def execution_notes(*, run_id: str, llm: str, cfg: Config, prompt_versions: dict[str, str]) -> str:
    """final.execution_notes 문자열 (06에 타입 없음 → M1 결정 19).
    예: "API 파이프라인; run_id=…; G0=모델/추론강도; G1B=…; G2=…; prompt=G0:…,G1B:…,G2:…;
    G2_OVERLAP_MODE=…; review_independence=SEPARATE_CALL". mock이면 "API 파이프라인(MOCK)"."""
    o = execution_notes_object(run_id=run_id, llm=llm, cfg=cfg, prompt_versions=prompt_versions)
    parts = ["API 파이프라인(MOCK)" if o["llm"] == "MOCK" else "API 파이프라인", f"run_id={run_id}"]
    parts += [f"{s}={o['models'][s]}/{o['reasoning_effort'][s]}" for s in CALL_STAGES]
    parts.append("prompt=" + ",".join(f"{s}:{prompt_versions.get(s, '-')}" for s in CALL_STAGES))
    parts.append(f"G2_OVERLAP_MODE={o['G2_OVERLAP_MODE']}")
    parts.append(f"review_independence={o['review_independence']}")
    return "; ".join(parts)


# --- 지표 확장 (5.7-2) ---


def expand_checks(model_checks: dict[str, str], issues: dict[str, str | None] | None, evidence_loc: str | None,
                  gate: str) -> dict[str, dict[str, Any]]:
    """status는 모델 값(P/R/F/NA → PASS/REVIEW/FAIL/N_A), criterion은 criteria.yaml, evidence는 evidence_loc,
    conclusion은 R/F면 issues 문장, P면 "기준 충족 (<gate> 판정)", NA면 "해당 없음 (<gate> 판정)"."""
    out = {}
    for key, status in model_checks.items():
        if status in ("R", "F"):
            conclusion = (issues or {}).get(key)
        elif status == "P":
            conclusion = f"기준 충족 ({gate} 판정)"
        else:
            conclusion = f"해당 없음 ({gate} 판정)"
        out[key] = {"status": CHECK_STATUS_MAP[status], "evidence": evidence_loc,
                    "criterion": criterion_for(key), "conclusion": conclusion}
    return out


# --- Gate 객체 ---


def build_revision(card: dict[str, Any], g0: dict[str, Any] | None) -> dict[str, Any]:
    original = card.get("original_task")
    codes = ["ORIGINAL_TASK_EMPTY"] if card.get("original_task_empty") else []
    if g0 is None:
        return {"action": None, "original_task": original, "regenerated_task_new": None, "effective_task": None,
                "reason": None, "reason_codes": codes, "evidence": None, "criterion": None, "conclusion": None,
                "g0_self_check": {}, "expected_reference_spec": None, "decided_by": None, "escalated": False}
    action = g0["action"]
    out = g0.get("output") or {}
    regen = out.get("regenerated_task_new") if action == "REGENERATE" else None
    effective = original if action == "KEEP" else regen if action == "REGENERATE" else None
    if g0.get("failure") == "CALL_FAILED":
        codes.append("G0_CALL_FAILED")
    elif g0.get("failure") == "VALIDATION_FAILED":
        codes.append("G0_VALIDATION_FAILED")
    if g0.get("decided_by") == "RULE" and not card.get("inspected"):
        codes.append("NOT_INSPECTED")
    reason = out.get("reason") or g0.get("rule_reason")
    return {
        "action": action,
        "original_task": original,
        "regenerated_task_new": regen,
        "effective_task": effective,
        "reason": reason,
        "reason_codes": codes,
        "evidence": out.get("evidence_loc"),
        "criterion": ACTION_CRITERION.get(action),
        "conclusion": f"{action}: {(reason or '')[:CONCLUSION_REASON_CHARS]}",
        "g0_self_check": expand_checks(out["checks"], out.get("issues"), out.get("evidence_loc"), "G0")
        if out.get("checks") else {},
        "expected_reference_spec": out.get("expected_reference_spec"),
        "decided_by": g0.get("decided_by"),
        "escalated": bool(g0.get("escalated")),
    }


DUPLICATE_FIELDS = ("status", "duplicate_type", "overlap_status", "representative_row", "representative_id", "group",
                    "compared_rows", "candidate_rows", "candidate_count", "adjudicated_candidate_count",
                    "unresolved_candidate_count", "search_scope", "search_completed", "reason")


def build_duplicate(g1: dict[str, Any] | None) -> dict[str, Any]:
    g1 = g1 or {}
    dup = {k: g1.get(k) for k in DUPLICATE_FIELDS}
    for k in ("compared_rows", "candidate_rows"):
        dup[k] = list(dup[k] or [])
    dup["candidate_pairs"] = list(g1.get("candidate_pairs") or [])
    dup["decided_by"] = g1.get("decided_by")
    return dup


def build_verify(card: dict[str, Any], g2: dict[str, Any] | None) -> dict[str, Any]:
    base = {"status": None, "skip_reason": None, "checks": {}, "b_coverage_status": None,
            "reference_mode": card.get("reference_mode"), "reference_action": None, "reference_readiness": None,
            "blueprints": {}, "proposed_fix": None, "reason": None, "reason_codes": [],
            "review_independence": "SEPARATE_CALL", "reference_conflict": None, "reference_conflict_note": None,
            "flags": [], "decided_by": None}
    if g2 is None:
        return base
    out = g2.get("output") or {}
    base.update(status=g2.get("status"), skip_reason=g2.get("skip_reason"), flags=list(g2.get("flags") or []),
                decided_by=g2.get("decided_by"))
    failure = g2.get("failure")
    if failure is not None:
        # 호출 2회 실패·검증 2회 실패: REVIEW(RULE), 모델 출력은 쓰지 않는다 (2026-10-22 결정)
        code = {"CALL_FAILED": "G2_CALL_FAILED", "VALIDATION_FAILED": "G2_VALIDATION_FAILED"}[failure]
        base.update(status="REVIEW", decided_by="RULE", reason=g2.get("rule_reason") or code, reason_codes=[code])
        return base
    if out:
        checks = {**out["overlap_review"]["checks"], **out["new_checks"]}
        base.update(
            checks=expand_checks(checks, out.get("issues"), out.get("evidence_loc"), "G2"),
            b_coverage_status=out.get("b_coverage_status"),
            reference_action=out.get("reference_action"),
            reference_readiness=out.get("reference_readiness"),
            blueprints=dict(out.get("blueprints") or {}),
            proposed_fix=out.get("proposed_fix"),
            reason=out.get("reason"),
            reference_conflict=out.get("reference_conflict"),
            reference_conflict_note=out.get("reference_conflict_note"),
        )
        if out.get("reference_conflict"):
            base["reason_codes"].append("REFERENCE_CONFLICT")
    elif g2.get("status") == "SKIPPED":
        base["reason"] = g2.get("skip_reason")
    return base


def build_source_assets(p0: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    locators = list(p0.get("matched_locators") or [])
    return {
        "deliverable_files": {
            "expected_filename": card.get("expected_filename"),
            "source_columns_used": ["D", "F"],
            "match_method": p0.get("match_method"),
            "match_status": p0.get("match_status"),
            "matched_locator": " | ".join(locators) or None,
            "matched_locators": locators,
            "inspected": bool(p0.get("inspected")),
            "inspected_locations": list(p0.get("inspected_locations") or []),
            "evidence": p0.get("reason"),
        },
        "reference_files": {"mode": card.get("reference_mode"), "assets": []},
    }


def final_reason(rule: int, codes: tuple[str, ...], next_action: str, representative: Any = None,
                 representative_id: Any = None) -> str:
    """final.reason: 판단 근거와 필요한 조치 (06). 규칙 번호·원인 코드에서 기계적으로 만든다."""
    causes = ", ".join(REASON_CODE_TEXT.get(c, c) for c in codes)
    if rule == 1:
        base = f"확정 중복 (대표 행 {representative}, {representative_id})" if representative is not None else "확정 중복"
    elif rule == 5:
        base = "G0 채택·G1 UNIQUE·G2 PASS·자료 확인 완료"
    else:
        base = causes or "-"
    return f"규칙 {rule}: {base} → {NEXT_ACTION_TEXT[next_action]}"


def build_final(card: dict[str, Any], p0: dict[str, Any], revision: dict[str, Any], duplicate: dict[str, Any],
                verify: dict[str, Any], g0: dict[str, Any] | None, notes: str,
                inputs_g2: dict[str, Any] | None = None) -> dict[str, Any]:
    inputs = FinalInputs(
        match_status=p0.get("match_status") or card.get("match_status"),
        inspected=bool(p0.get("inspected")),
        reference_mode=card.get("reference_mode"),
        g0_action=revision["action"],
        g1_status=duplicate["status"],
        g1_search_completed=bool(duplicate["search_completed"]),
        g2_status=verify["status"],
        reference_readiness=verify["reference_readiness"],
        reference_conflict=bool(verify["reference_conflict"]),
        original_task_empty=bool(card.get("original_task_empty")),
        g0_failure=(g0 or {}).get("failure"),
        g2_failure=(inputs_g2 or {}).get("failure"),
    )
    try:
        d = decide_final(inputs)
    except NoRuleMatched as e:
        return {"status": None, "next_action": None, "reason_codes": [], "reason": f"판정 불가: {e}",
                "execution_notes": notes, "decided_by": "RULE", "rule": None}
    return {"status": d.status, "next_action": d.next_action, "reason_codes": list(d.reason_codes),
            "reason": final_reason(d.rule, d.reason_codes, d.next_action, duplicate.get("representative_row"),
                                   duplicate.get("representative_id")),
            "execution_notes": notes, "decided_by": "RULE", "rule": d.rule}


def apply_final_overrides(record: dict[str, Any], overrides: list[dict[str, Any]]) -> None:
    for o in overrides:
        if int(o["source_row"]) == record["source_row"]:
            record["final"][o["field"]] = o["new_value"]
            record["final"]["decided_by"] = "HUMAN"


def build_final_records(inputs: Any, *, task_name: str, source_file: str, notes: str) -> list[dict[str, Any]]:
    """06 최상위 키 12개 (+ 각 Gate 객체 decided_by, duplicate.candidate_pairs[], final.execution_notes)."""
    from ksco_qa.g3.records import apply_overrides

    final_overrides = apply_overrides(inputs)
    records = []
    for card in inputs.row_cards:
        row = int(card["source_row"])
        p0 = inputs.p0.get(row, {})
        g0 = inputs.g0.get(row)
        revision = build_revision(card, g0)
        duplicate = build_duplicate(inputs.g1.get(row))
        verify = build_verify(card, inputs.g2.get(row))
        record = {
            "schema_version": SCHEMA_VERSION,
            "dataset": task_name,
            "source_file": source_file,
            "source_sheet": SHEET_NAME,
            "source_row": row,
            "id": card["id"],
            "source": {"cells": (inputs.source_cells.get(row) or {}).get("cells", {})},
            "source_assets": build_source_assets(p0, card),
            "revision": revision,
            "duplicate": duplicate,
            "verify": verify,
            "final": build_final(card, p0, revision, duplicate, verify, g0, notes, inputs.g2.get(row)),
        }
        apply_final_overrides(record, final_overrides)
        records.append(record)
    return records


# --- 파일 쓰기 ---


def _cell(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _original_columns(record: dict[str, Any]) -> list[str]:
    cells = record["source"]["cells"]
    return sorted(cells, key=lambda c: (len(c), c))


def _write_gate_xlsx(path: Path, records: list[dict[str, Any]], extra_columns: list[str],
                     extra_values: Any) -> None:
    """원본 서식 복사 대신 새 워크북에 값만: 원본 A~끝 열 값 + 추가 열 (M1 결정). 시트는 원본 이름 하나."""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    letters = _original_columns(records[0]) if records else []
    headers = [records[0]["source"]["cells"][c]["header"] for c in letters] if records else []
    ws.append(headers + extra_columns)
    for r in records:
        cells = r["source"]["cells"]
        values = [cells.get(c, {}).get("value") for c in letters]
        ws.append(values + [_cell(v) for v in extra_values(r)])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def audit_completeness(dup: dict[str, Any]) -> str | None:
    """00 5장: 미완료 후보가 있으면 COMPLETE 선언 금지."""
    if dup["status"] is None:
        return None
    if dup["status"] == "NOT_EVALUATED":
        return "NOT_EVALUATED"
    complete = dup["search_completed"] and not dup["unresolved_candidate_count"]
    return "COMPLETE" if complete else "INCOMPLETE"


def write_gate_files(results: dict[str, Path], records: list[dict[str, Any]]) -> None:
    _write_gate_xlsx(results["00_revision_regenerate.xlsx"], records, REVISION_COLUMNS, lambda r: [
        r["source_row"], r["id"], r["revision"]["action"], r["revision"]["original_task"],
        r["revision"]["regenerated_task_new"], r["revision"]["effective_task"], r["revision"]["reason"],
        r["revision"]["evidence"], r["revision"]["expected_reference_spec"], r["revision"]["g0_self_check"]])
    _write_gate_xlsx(results["01_duplicate_audit.xlsx"], records, DUPLICATE_COLUMNS, lambda r: [
        r["duplicate"]["status"], r["duplicate"]["duplicate_type"], r["duplicate"]["group"],
        r["duplicate"]["representative_row"] if r["duplicate"]["status"] == "DUPLICATE" else None,
        r["duplicate"]["representative_id"] if r["duplicate"]["status"] == "DUPLICATE" else None,
        r["duplicate"]["overlap_status"], r["duplicate"]["compared_rows"], r["duplicate"]["reason"],
        audit_completeness(r["duplicate"]), r["duplicate"]["candidate_count"],
        r["duplicate"]["adjudicated_candidate_count"], r["duplicate"]["unresolved_candidate_count"],
        r["duplicate"]["search_scope"], r["duplicate"]["search_completed"]])
    _write_gate_xlsx(results["02_task_verify.xlsx"], records, VERIFY_COLUMNS, lambda r: [
        r["verify"]["status"], "; ".join(r["verify"]["flags"]), r["verify"]["checks"],
        r["verify"]["b_coverage_status"], r["verify"]["reference_mode"], r["verify"]["reference_action"],
        r["verify"]["reference_readiness"], r["verify"]["blueprints"].get("scenario"),
        r["verify"]["blueprints"].get("reference"), r["verify"]["blueprints"].get("reasoning_map"),
        r["verify"]["blueprints"].get("evaluation"), r["verify"]["reason"], r["verify"]["proposed_fix"]])


def write_final_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """03_final.jsonl — 원본 1행 = 객체 1개 = 물리적 1줄, UTF-8 (5.7-3)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# --- 사람 검토 목록 (9.2) ---

REVIEW_QUEUE_COLUMNS = ["source_row", "id", "categories", "revision_action", "duplicate_status", "verify_status",
                        "final_status", "next_action", "review_verdict", "review_reason", "reviewer"]


def review_seed(run_id: str) -> int:
    """표본 시드 = hash(run_id) (M1 결정 25)."""
    return int(hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16], 16)


def review_queue(records: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    """RESELECT_B·G2 FAIL 전체, 재판정·자동 검사로 REVIEW가 된 행 전체, REGENERATE 20%(최소 10행),
    DUPLICATE 그룹 20%(최소 5그룹), 최종 PASS 무작위 20행. 한 행이 여러 범주면 범주를 합쳐 한 줄."""
    rng = random.Random(review_seed(run_id))
    picked: dict[int, list[str]] = {}

    def add(rows: list[dict[str, Any]], category: str) -> None:
        for r in rows:
            picked.setdefault(r["source_row"], []).append(category)

    add([r for r in records if r["revision"]["action"] == "RESELECT_B"], "RESELECT_B")
    add([r for r in records if r["verify"]["status"] == "FAIL"], "G2_FAIL")
    auto = {"G0_CALL_FAILED", "G0_VALIDATION_FAILED", "G2_CALL_FAILED", "G2_VALIDATION_FAILED"}
    add([r for r in records if r["revision"]["escalated"] or auto & set(r["final"]["reason_codes"])], "AUTO_CHECK")
    regen = [r for r in records if r["revision"]["action"] == "REGENERATE"]
    add(rng.sample(regen, min(len(regen), max(10, round(len(regen) * 0.2)))), "REGENERATE_SAMPLE")
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        if r["duplicate"]["status"] == "DUPLICATE" and r["duplicate"]["group"] is not None:
            groups.setdefault(str(r["duplicate"]["group"]), []).append(r)
    names = sorted(groups)
    for name in rng.sample(names, min(len(names), max(5, round(len(names) * 0.2)))):
        add(groups[name], "DUPLICATE_GROUP_SAMPLE")
    passes = [r for r in records if r["final"]["status"] == "PASS"]
    add(rng.sample(passes, min(len(passes), 20)), "PASS_SAMPLE")

    by_row = {r["source_row"]: r for r in records}
    return [{
        "source_row": row, "id": by_row[row]["id"], "categories": "; ".join(cats),
        "revision_action": by_row[row]["revision"]["action"], "duplicate_status": by_row[row]["duplicate"]["status"],
        "verify_status": by_row[row]["verify"]["status"], "final_status": by_row[row]["final"]["status"],
        "next_action": by_row[row]["final"]["next_action"], "review_verdict": "", "review_reason": "", "reviewer": "",
    } for row, cats in sorted(picked.items())]


def write_review_queue(path: Path, rows: list[dict[str, Any]]) -> None:
    """_work/review_queue.csv — 검토자가 review_verdict(동의/불동의/판단 불가)·review_reason을 채운다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_QUEUE_COLUMNS)
        w.writeheader()
        w.writerows(rows)


# --- 실행 보고 ---


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Gate별 집계 (06 최소 검증 10번 대조 대상)."""
    def count(path: tuple[str, str]) -> dict[str, int]:
        return dict(Counter(str(r[path[0]][path[1]]) for r in records))

    pairs = {tuple(sorted((r["source_row"], p["row"]))) for r in records for p in r["duplicate"]["candidate_pairs"]}
    return {
        "rows": len(records),
        "mapping": dict(Counter(str(r["source_assets"]["deliverable_files"]["match_status"]) for r in records)),
        "g0_action": count(("revision", "action")),
        "g1_status": count(("duplicate", "status")),
        "g1_candidate_pairs": len(pairs),
        "g1_high_overlap_rows": sum(r["duplicate"]["overlap_status"] == "HIGH_OVERLAP" for r in records),
        "g1_unresolved_rows": sum(bool(r["duplicate"]["unresolved_candidate_count"]) for r in records),
        "g2_status": count(("verify", "status")),
        "final_status": count(("final", "status")),
        "next_action": count(("final", "next_action")),
    }


def calls_summary(run_dir: Path) -> dict[str, Any]:
    """calls.jsonl 실측 usage·비용 합계 (단계별)."""
    from ksco_qa.g3.records import read_jsonl

    by_stage: dict[str, dict[str, Any]] = {}
    for c in read_jsonl(Path(run_dir) / "calls.jsonl"):
        s = by_stage.setdefault(c["stage"], {"calls": 0, "input": 0, "cached_input": 0, "output": 0,
                                             "reasoning": 0, "cost_usd": 0.0, "cost_unknown_calls": 0})
        s["calls"] += 1
        for k in ("input", "cached_input", "output", "reasoning"):
            s[k] += (c.get("usage") or {}).get(k, 0)
        if c.get("cost_usd") is None:
            s["cost_unknown_calls"] += 1
        else:
            s["cost_usd"] += c["cost_usd"]
    total = {k: sum(v[k] for v in by_stage.values()) for k in
             ("calls", "input", "cached_input", "output", "reasoning", "cost_usd", "cost_unknown_calls")}
    return {"by_stage": by_stage, "total": total}


def write_run_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def run_g3(ctx: Any, cfg: Config, prompt_versions: dict[str, str], *, source_file: str) -> dict[str, Any]:
    """5.7 전체: 레코드 → Gate xlsx·03_final.jsonl → 검증 → review_queue·run_report.
    검증 실패가 하나라도 있으면 status=FAILED_VALIDATION (파일은 남김)."""
    from ksco_qa.g3.records import load_inputs
    from ksco_qa.g3.validate import validate_all

    inputs = load_inputs(ctx.run_dir)
    notes = execution_notes(run_id=ctx.run_id, llm=ctx.llm, cfg=cfg, prompt_versions=prompt_versions)
    records = build_final_records(inputs, task_name=ctx.task_name, source_file=source_file, notes=notes)
    results = {name: ctx.result_path(name) for name in FINAL_OUTPUTS}
    write_gate_files(results, records)
    write_final_jsonl(results[FINAL_JSONL], records)

    summary = summarize(records)
    validation = validate_all(results, inputs, summary)
    queue = review_queue(records, ctx.run_id)
    write_review_queue(ctx.run_dir / "review_queue.csv", queue)
    failed = {name: errors for name, errors in validation.items() if errors}
    report = {
        "run_id": ctx.run_id,
        "status": "FAILED_VALIDATION" if failed else "COMPLETED",
        "execution_notes": execution_notes_object(run_id=ctx.run_id, llm=ctx.llm, cfg=cfg,
                                                  prompt_versions=prompt_versions),
        "summary": summary,
        "validation": validation,
        "review_queue": {"rows": len(queue), "seed": f"{review_seed(ctx.run_id):016x}"},
        "usage": calls_summary(ctx.run_dir),
        "outputs": {name: str(Path(p).name) for name, p in results.items()},
    }
    write_run_report(ctx.run_dir / "run_report.json", report)
    return report

