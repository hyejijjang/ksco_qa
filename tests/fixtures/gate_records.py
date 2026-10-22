"""sample_task용 가상 G0·G1·G2 단계 기록 (g3.records 계약 형식, 실제 모델 결과 아님).

행마다 최종 판정 규칙의 다른 경로를 타도록 만든다. EXPECTED_FINAL에 기대 (status, next_action).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ksco_qa.dictionaries import g0_check_keys, g2_new_keys, g2_overlap_keys

# id → G0 (action, decided_by, failure)
G0_PLAN = {
    "T-001": ("KEEP", "MODEL", None), "T-002": ("REGENERATE", "MODEL", None), "T-003": ("KEEP", "MODEL", None),
    "T-005": ("RESELECT_B", "MODEL", None), "T-006": ("KEEP", "MODEL", None), "T-007": ("REGENERATE", "MODEL", None),
    "T-008": ("KEEP", "MODEL", None), "T-009": ("KEEP", "MODEL", None), "T-010": ("REGENERATE", "MODEL", None),
    "T-011": ("REVIEW_B", "RULE", "CALL_FAILED"), "T-012": ("KEEP", "MODEL", None),
}
# id → G2 status, 또는 ("FAILURE", 종류) = 호출 2회 실패·검증 2회 실패 → G3가 REVIEW(RULE)로 기록
G2_PLAN = {"T-001": "PASS", "T-003": "PASS", "T-006": "PASS", "T-007": "FAIL", "T-008": "REVIEW",
           "T-009": ("FAILURE", "VALIDATION_FAILED"), "T-010": "PASS", "T-012": ("FAILURE", "CALL_FAILED")}
# 모델 글이 행마다 다르게 (같은 문장 반복 = 템플릿 판정, 검증에서 걸린다)
G0_REASONS = ["월별 합계와 증감률 열이 원본 Task 요구와 맞음", "지역별 비율 집계가 산출물 표 구성과 일치",
              "보고서 본문과 부속 표의 범위가 Task에 드러남", "업종 구분 표가 Task 지시와 대응",
              "응답 원자료의 필드가 Task 입력과 연결됨", "슬라이드 제목 구조가 보고 Task와 맞음",
              "안내문 구성 요소가 Task에 모두 들어 있음", "기관 목록 필드가 Task 출력과 대응",
              "재무 표의 계정 구조가 Task 계산과 맞음", "안내 페이지의 표가 Task 결과물과 일치",
              "집계 기준 열이 산출물에서 확인됨", "결산 서류 목록이 Task와 대응"]

EXPECTED_FINAL = {
    "T-001": ("PASS", "HANDOFF_TO_AI_TEAM"),
    "T-002": ("FAIL", "EXCLUDE_DUPLICATE"),
    "T-003": ("PASS", "HANDOFF_TO_AI_TEAM"),
    "T-004": ("REVIEW", "CHECK_ASSETS"),
    "T-005": ("FAIL", "RESELECT_DELIVERABLE"),
    "T-006": ("REVIEW", "CHECK_ASSETS"),
    "T-007": ("FAIL", "REVISE_TASK"),
    "T-008": ("REVIEW", "CHECK_DUPLICATE"),
    "T-009": ("REVIEW", "REVIEW_MANUAL"),
    "T-010": ("PASS", "HANDOFF_TO_AI_TEAM"),
    "T-011": ("REVIEW", "REVIEW_MANUAL"),
    "T-012": ("REVIEW", "REVIEW_MANUAL"),
    "T-013": ("REVIEW", "CHECK_ASSETS"),
    "T-014": ("REVIEW", "CHECK_ASSETS"),
    "T-015": ("REVIEW", "CHECK_ASSETS"),
    "T-016": ("REVIEW", "CHECK_ASSETS"),
}


def g0_output(card: dict[str, Any], action: str) -> dict[str, Any]:
    checks = {k: "P" for k in g0_check_keys()}
    issues = {k: None for k in g0_check_keys()}
    if action != "KEEP":
        checks["deliverable_fit"] = "R"
        issues["deliverable_fit"] = f"{card['id']} 산출물 구성과 Task 결과 요구가 일부 다름 (파일 1행)"
    return {
        "job_evaluated": card["job_leaf"],
        "action": action,
        "checks": checks,
        "reason": G0_REASONS[int(card["id"].split("-")[1]) % len(G0_REASONS)],
        "evidence_loc": "file_profile 관찰 위치 1행",
        "expected_reference_spec": f"{card['id']} 원자료 표 (월·금액 필드)",
        "regenerated_task_new": f"{card['id']} 새 Task: 자료를 집계해 표를 작성한다." if action == "REGENERATE" else None,
        "issues": issues,
        "task_card": {"input": "원자료", "operations": ["집계"], "criteria": ["합계 검산"], "output": "표"}
        if action in ("KEEP", "REGENERATE") else None,
    }


def g2_output(card: dict[str, Any], status: str) -> dict[str, Any]:
    overlap = {k: "P" for k in g2_overlap_keys()}
    new = {k: "P" for k in g2_new_keys()}
    issues = {k: None for k in g2_overlap_keys() + g2_new_keys()}
    if status in ("REVIEW", "FAIL"):
        new["task_clarity"] = "F" if status == "FAIL" else "R"
        issues["task_clarity"] = f"{card['id']} 요청 범위가 모호함 (Task 2번째 문장)"
    unresolved = card["reference_mode"] == "UNRESOLVED_REFERENCE"
    return {
        "verify_status": status,
        "overlap_review": {"mode": "AGREE_CHECK", "checks": overlap, "disagree": []},
        "new_checks": new,
        "b_coverage_status": "SUFFICIENT",
        "reference_action": "CHECK_ACCESS" if unresolved else "GENERATE",
        "reference_readiness": "HOLD" if unresolved else "BLUEPRINT_READY",
        "reference_conflict": None,
        "reference_conflict_note": None,
        "blueprints": {"scenario": f"{card['id']} 업무 맥락", "reference": "원자료 설계", "reasoning_map": "집계 → 표",
                       "evaluation": "합계 검산"},
        "reason": f"{card['job_leaf']} 업무로 {card['deliverable_title']} 설계 가능 ({card['id']})",
        "evidence_loc": "file_profile 1행",
        "issues": issues,
        "proposed_fix": f"{card['id']} 범위를 명시" if status in ("REVIEW", "FAIL") else None,
    }


def build_gate_records(row_cards: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_id = {c["id"]: c for c in row_cards}
    g0, g1, g2 = [], [], []
    for card in row_cards:
        rid, row = card["id"], card["source_row"]
        if rid in G0_PLAN:
            action, decided_by, failure = G0_PLAN[rid]
            g0.append({"source_row": row, "id": rid, "action": action, "decided_by": decided_by, "failure": failure,
                       "rule_reason": "G0 호출 2회 실패" if failure else None,
                       "output": None if failure else g0_output(card, action), "escalated": action != "KEEP"})
        else:  # inspected=false → RULE REVIEW_B
            g0.append({"source_row": row, "id": rid, "action": "REVIEW_B", "decided_by": "RULE", "failure": None,
                       "rule_reason": f"NOT_INSPECTED: {card['match_status']}", "output": None, "escalated": False})

        task = G0_PLAN.get(rid, ("REVIEW_B",))[0] in ("KEEP", "REGENERATE")
        dup: dict[str, Any] = {"source_row": row, "id": rid, "decided_by": "MODEL" if task else "RULE",
                               "representative_row": None, "representative_id": None, "group": None,
                               "compared_rows": [], "candidate_rows": [], "candidate_pairs": [],
                               "candidate_count": 0, "adjudicated_candidate_count": 0, "unresolved_candidate_count": 0,
                               "search_scope": "전체 데이터 행 (effective_task 있는 행)", "search_completed": True}
        if not task:
            dup.update(status="NOT_EVALUATED", duplicate_type="UNDETERMINED", overlap_status="UNDETERMINED",
                       search_completed=False, reason="Task 없음")
        elif rid in ("T-001", "T-002"):
            other = by_id["T-002" if rid == "T-001" else "T-001"]
            pair = {"row": other["source_row"], "signals": ["param", "tfidf_task"], "similarity": 0.91,
                    "verdict": "PARAMETER_VARIANT", "evidence": f"{rid}와 연도만 다르고 집계 규칙이 같음"}
            dup.update(status="UNIQUE" if rid == "T-001" else "DUPLICATE", duplicate_type="PARAMETER_VARIANT",
                       overlap_status="NONE", group="G1-1", representative_row=by_id["T-001"]["source_row"],
                       representative_id="T-001", compared_rows=[other["source_row"]],
                       candidate_rows=[other["source_row"]], candidate_pairs=[pair], candidate_count=1,
                       adjudicated_candidate_count=1, reason="연도만 다른 확정 중복 그룹")
        elif rid == "T-008":
            dup.update(status="REVIEW", duplicate_type="UNDETERMINED", overlap_status="UNDETERMINED",
                       candidate_count=1, unresolved_candidate_count=1, search_completed=False,
                       candidate_rows=[by_id["T-009"]["source_row"]], reason="미판정 후보 1개")
        else:
            dup.update(status="UNIQUE", duplicate_type="NONE",
                       overlap_status="HIGH_OVERLAP" if rid == "T-003" else "NONE", reason="후보 없음 또는 모두 DISTINCT")
        g1.append(dup)

        if dup["status"] == "DUPLICATE":
            g2.append({"source_row": row, "id": rid, "status": "SKIPPED", "skip_reason": "DUPLICATE_TASK",
                       "decided_by": "RULE", "failure": None, "flags": [], "output": None})
        elif isinstance(G2_PLAN.get(rid), tuple):
            kind = G2_PLAN[rid][1]
            g2.append({"source_row": row, "id": rid, "status": None, "skip_reason": None, "decided_by": "RULE",
                       "failure": kind, "rule_reason": f"G2 {kind}: 2회 실패", "flags": [], "output": None})
        elif rid in G2_PLAN:
            status = G2_PLAN[rid]
            g2.append({"source_row": row, "id": rid, "status": status, "skip_reason": None, "decided_by": "MODEL",
                       "failure": None, "flags": [], "output": g2_output(card, status)})
        else:
            g2.append({"source_row": row, "id": rid, "status": "SKIPPED", "decided_by": "RULE", "failure": None,
                       "skip_reason": f"G0 {G0_PLAN.get(rid, ('REVIEW_B',))[0]}", "flags": [], "output": None})
    return {"g0/records.jsonl": g0, "g1/rows.jsonl": g1, "g2/records.jsonl": g2}


def write_gate_records(run_dir: Path, row_cards: list[dict[str, Any]]) -> None:
    for name, rows in build_gate_records(row_cards).items():
        path = Path(run_dir) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
