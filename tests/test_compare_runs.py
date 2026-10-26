"""compare-runs — 같은 표본 두 run의 행별 비교표 (2026-10-26)."""

from __future__ import annotations

import json
from pathlib import Path

import openpyxl

from ksco_qa.compare import WorkResultRow
from ksco_qa.compare_runs import build_run_comparison, compare_runs
from ksco_qa.dictionaries import g0_check_keys


def _checks(**flags: str) -> dict[str, str]:
    return {key: flags.get(key, "P") for key in g0_check_keys()}


def _write_run(run_dir: Path, g0: list[dict], *, g1: list[dict] = (), escalations: int = 0, cost: float = 0.1) -> None:
    (run_dir / "g0").mkdir(parents=True)
    (run_dir / "g1").mkdir()
    lines = lambda items: "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items)
    (run_dir / "g0" / "records.jsonl").write_text(lines(g0), encoding="utf-8")
    (run_dir / "g1" / "rows.jsonl").write_text(lines(g1), encoding="utf-8")
    cards = [{"source_row": r["source_row"], "id": r["id"], "job_leaf": "회계 사무원", "original_task": f"원본 {r['id']}"}
             for r in g0]
    (run_dir / "row_cards.jsonl").write_text(lines(cards), encoding="utf-8")
    calls = [{"stage": "G0", "attempt_kind": "escalate"}] * escalations
    (run_dir / "calls.jsonl").write_text(lines(calls), encoding="utf-8")
    (run_dir / "run_report.json").write_text(json.dumps({"usage": {"total": {"cost_usd": cost}},
                                                         "validation": {"template_sentences": []}}), encoding="utf-8")


def _g0(row: int, action: str, task: str | None = None, **flags: str) -> dict:
    return {"source_row": row, "id": f"T-{row}", "action": action, "decided_by": "MODEL", "escalated": False,
            "output": {"action": action, "checks": _checks(**flags), "regenerated_task_new": task, "reason": f"이유 {row}"}}


def test_run_comparison_rows_dimensions_and_summary(tmp_path: Path) -> None:
    old, new = tmp_path / "_work" / "old", tmp_path / "_work" / "new"
    _write_run(old, [_g0(2, "REGENERATE", "옛 Task", grounding="R", input_contract="R"),
                     _g0(3, "REGENERATE", "옛 Task 3", output_specification="R")],
               g1=[{"source_row": 2, "status": "REVIEW"}, {"source_row": 3, "status": "REVIEW"}], escalations=2)
    stale = _g0(2, "REVIEW_B")  # 추가 전용 기록: 같은 행은 마지막 줄이 이긴다
    _write_run(new, [stale, _g0(2, "KEEP", grounding="R"), _g0(3, "REGENERATE", "새 Task 3", reasoning_validity="F")],
               g1=[{"source_row": 2, "status": "UNIQUE"}, {"source_row": 3, "status": "REVIEW"}], cost=0.05)
    work = {"T-2": WorkResultRow("T-2", "PASS", "PASS", None, None, "문제 없음"),
            "T-3": WorkResultRow("T-3", "REVIEW", "REVIEW", None, None, None)}

    result = build_run_comparison(old, new, work)
    row2, row3 = result["rows"]
    assert (row2["이전 action"], row2["새 action"], row2["action 변경"]) == ("REGENERATE", "KEEP", True)
    assert (row2["이전 R/F 차원"], row2["새 R/F 차원"]) == ("grounding:R, input_contract:R", "grounding:R")
    assert (row2["이전 R/F 수"], row2["새 R/F 수"]) == (2, 1)
    assert (row2["사람 최종 판정"], row2["검수 메모"], row2["원본 Task"]) == ("PASS", "문제 없음", "원본 T-2")
    assert (row2["이전 G1"], row2["새 G1"]) == ("REVIEW", "UNIQUE")
    assert (row3["이전 재생성 Task"], row3["새 재생성 Task"]) == ("옛 Task 3", "새 Task 3")

    dims = {d["차원"]: d for d in result["dimensions"]}
    assert (dims["grounding"]["이전 R"], dims["grounding"]["새 R"]) == (1, 1)
    assert (dims["reasoning_validity"]["새 F"], dims["output_specification"]["이전 R"]) == (1, 1)

    s = result["summary"]
    assert s["사람 최종 PASS 중 REGENERATE (이전)"] == 1 and s["사람 최종 PASS 중 REGENERATE (새)"] == 0
    assert (s["G0 재판정 호출 (이전)"], s["G0 재판정 호출 (새)"]) == (2, 0)
    assert s["새 G1"] == {"UNIQUE": 1, "REVIEW": 1}


def test_compare_runs_writes_workbook(tmp_path: Path) -> None:
    work_root = tmp_path / "task" / "03_results" / "_work"
    _write_run(work_root / "r1", [_g0(2, "REGENERATE", "옛 Task")])
    _write_run(work_root / "r2", [_g0(2, "KEEP")])
    csv = tmp_path / "work.csv"
    csv.write_text("id,AI 판정,최종 판정,Regenerate Task,원본 Task(백업),검수 메모\nT-2,PASS,PASS,,,메모\n", encoding="utf-8")
    path = compare_runs(tmp_path / "task", "r1", "r2", csv)
    assert path == work_root / "r2" / "compare_vs_r1.xlsx"
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["행별", "차원별 RF", "요약"]
    header = [c.value for c in wb["행별"][1]]
    row = dict(zip(header, [c.value for c in wb["행별"][2]]))
    assert (row["이전 action"], row["새 action"], row["검수 메모"]) == ("REGENERATE", "KEEP", "메모")
