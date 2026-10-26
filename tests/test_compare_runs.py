"""compare-runs — 같은 표본 여러 run의 행별 비교표 (2026-10-26)."""

from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pytest

from ksco_qa.compare import CompareError, WorkResultRow
from ksco_qa.compare_runs import build_run_comparison, classify_g2_issue, compare_runs, file_input
from ksco_qa.dictionaries import g0_check_keys


def _lines(items) -> str:
    return "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items)


def _checks(**flags: str) -> dict[str, str]:
    return {key: flags.get(key, "P") for key in g0_check_keys()}


def _g0(row: int, action: str, task: str | None = None, **flags: str) -> dict:
    return {"source_row": row, "id": f"T-{row}", "action": action, "decided_by": "MODEL", "escalated": False,
            "output": {"action": action, "checks": _checks(**flags), "regenerated_task_new": task, "reason": f"이유 {row}"}}


def _g2(row: int, status: str, coverage: str = "SUFFICIENT", **issues: str) -> dict:
    checks = {k: "R" for k in issues}
    return {"source_row": row, "id": f"T-{row}", "status": status,
            "output": {"overlap_review": {"checks": {k: v for k, v in checks.items() if k == "input_contract"}},
                       "new_checks": {k: v for k, v in checks.items() if k != "input_contract"},
                       "b_coverage_status": coverage, "issues": issues}}


def _write_run(run_dir: Path, g0: list[dict], *, g1=(), g2=(), finals: dict | None = None, escalations: int = 0,
               cost: float = 0.1, input_tokens: int = 1000, cards_extra: dict | None = None) -> None:
    (run_dir / "g0").mkdir(parents=True)
    (run_dir / "g1").mkdir()
    (run_dir / "g2").mkdir()
    (run_dir / "g0" / "records.jsonl").write_text(_lines(g0), encoding="utf-8")
    (run_dir / "g1" / "rows.jsonl").write_text(_lines(g1), encoding="utf-8")
    (run_dir / "g2" / "records.jsonl").write_text(_lines(g2), encoding="utf-8")
    cards = [{"source_row": r["source_row"], "id": r["id"], "job_leaf": "회계 사무원", "original_task": f"원본 {r['id']}",
              **(cards_extra or {}).get(r["source_row"], {})} for r in g0]
    (run_dir / "row_cards.jsonl").write_text(_lines(cards), encoding="utf-8")
    calls = [{"stage": "G0", "attempt_kind": "escalate"}] * escalations
    calls += [{"stage": "G0", "attempt_kind": "first", "unit_id": str(r["source_row"]),
               "usage": {"input": 100}, "cost_usd": 0.01} for r in g0]
    (run_dir / "calls.jsonl").write_text(_lines(calls), encoding="utf-8")
    (run_dir / "run_report.json").write_text(json.dumps({
        "usage": {"total": {"cost_usd": cost, "input": input_tokens}},
        "validation": {"template_sentences": []}}), encoding="utf-8")
    if finals is not None:
        (run_dir / "03_final.jsonl").write_text(_lines(
            {"source_row": row, "id": f"T-{row}", "final": {"status": s}} for row, s in finals.items()), encoding="utf-8")


def test_classify_g2_issue_types() -> None:
    assert classify_g2_issue("input_contract", "아무 문장") == "A"
    assert classify_g2_issue("task_clarity", "Task는 '제공된 자료'라고만 지칭한다") == "A"
    assert classify_g2_issue("evaluation_alignment", "file_profile은 표1-4의 머리글·앞 2행만 요약해 확정하기 어렵다") == "B"
    assert classify_g2_issue("grounding", "세부 계정과목은 확인할 수 없다. 근거: file_profile p2") == "B"
    assert classify_g2_issue("evaluation_alignment", "금액 열이 없어 차변·대변 균형을 검증할 수 없다") == "C"


def test_file_input_kinds() -> None:
    assert file_input({"file_profile": "x"}) == "프로필 모드"
    assert file_input({"file_fulltext_note": "a.pdf: 원본 전문 첨부 (약 1,000토큰)"}) == "전문"
    assert file_input({"file_fulltext_note": "a.pdf: 원본 전문 첨부 (약 1토큰); b.csv: 미첨부 (약 50,000토큰 이상 > 기준 30,000) — file_profile 참고"}) \
        == "일부 전문 (나머지 프로필)"
    assert file_input({"file_fulltext_note": "b.csv: 미첨부 (약 50,000토큰 이상 > 기준 30,000) — file_profile 참고"}) \
        == "프로필 (크기 초과·미첨부)"


def test_three_run_comparison(tmp_path: Path) -> None:
    w = tmp_path / "_work"
    _write_run(w / "a", [_g0(2, "REGENERATE", "옛 Task", grounding="R"), _g0(3, "REVIEW_B"), _g0(4, "KEEP")],
               g2=[_g2(2, "REVIEW", "PARTIAL_CRITICAL", input_contract="입력 미기재", evaluation_alignment="file_profile은 일부만 요약")],
               finals={2: "REVIEW", 3: "REVIEW", 4: "REVIEW"}, escalations=2)
    stale = _g0(2, "REVIEW_B")  # 추가 전용 기록: 같은 행은 마지막 줄이 이긴다
    _write_run(w / "b", [stale, _g0(2, "KEEP"), _g0(3, "REVIEW_B"), _g0(4, "KEEP")],
               g2=[_g2(2, "PASS"), _g2(4, "REVIEW", task_clarity="금액 열이 없어 검증할 수 없다")],
               finals={2: "PASS", 3: "REVIEW", 4: "REVIEW"}, cost=0.06, input_tokens=600)
    full = {3: {"file_fulltext": "본문", "file_fulltext_note": "x.pdf: 원본 전문 첨부 (약 10토큰)"},
            2: {"file_fulltext": None, "file_fulltext_note": "y.csv: 미첨부 (약 9토큰 이상 > 기준 1) — file_profile 참고"}}
    _write_run(w / "c", [_g0(2, "KEEP"), _g0(3, "KEEP"), _g0(4, "KEEP")], g2=[_g2(2, "PASS"), _g2(3, "PASS"), _g2(4, "PASS")],
               finals={2: "PASS", 3: "PASS", 4: "PASS"}, cards_extra=full)
    work = {"T-2": WorkResultRow("T-2", "PASS", "PASS", None, None, "문제 없음"),
            "T-3": WorkResultRow("T-3", "PASS", "PASS", None, None, None),
            "T-4": WorkResultRow("T-4", "REVIEW", "REVIEW", None, None, None)}

    result = build_run_comparison([("이전", w / "a"), ("profile", w / "b"), ("fulltext", w / "c")], work,
                                  {"C 유형": ["T-4"]})
    assert result["labels"] == ["이전", "profile", "fulltext"]
    row2, row3, row4 = result["rows"]
    assert (row2["이전 G0 action"], row2["profile G0 action"]) == ("REGENERATE", "KEEP")
    assert row2["이전 G2 R 지표(유형)"] == "input_contract:R(A), evaluation_alignment:R(B)"
    assert row4["profile G2 R 지표(유형)"] == "task_clarity:R(C)" and row4["표시"] == "C 유형"
    assert (row3["fulltext 파일 입력"], row2["fulltext 파일 입력"], row2["profile 파일 입력"]) == \
        ("전문", "프로필 (크기 초과·미첨부)", "프로필 모드")
    assert (row2["이전 입력 토큰(G0+G2)"], row2["이전 비용(G0+G2)"]) == (100, 0.01)

    s = result["summary"]
    assert s["사람 PASS 중 우리 PASS"] == {"이전": "0/2", "profile": "1/2", "fulltext": "2/2"}
    assert s["사람 REVIEW 중 우리 REVIEW"] == {"이전": "1/1", "profile": "1/1", "fulltext": "0/1"}
    assert s["기준선: 전부 REVIEW로 답하면 전체 일치"]["profile"] == "1/3 (33%)"
    assert s["G2 R 유형 A (입력 미기재)"]["이전"] == 1 and s["G2 R 유형 B (프로필 범위 밖)"]["이전"] == 1
    assert s["G2 R 유형 C (그 밖)"]["profile"] == 1
    assert s["b_coverage"]["이전"] == {"PARTIAL_CRITICAL": 1}
    assert s["REVIEW_B 변화: T-3"] == {"이전": "REVIEW_B / 프로필 모드", "profile": "REVIEW_B / 프로필 모드",
                                    "fulltext": "KEEP / 전문"}
    assert s["C 유형: T-4"]["profile"] == "G2 REVIEW · task_clarity:R(C)"
    assert s["행당 입력 토큰"]["profile"] == 200 and s["G0 재판정 호출"]["이전"] == 2


def test_run_without_final_records_is_marked(tmp_path: Path) -> None:
    w = tmp_path / "_work"
    _write_run(w / "a", [_g0(2, "KEEP")])
    _write_run(w / "b", [_g0(2, "KEEP")], finals={2: "PASS"})
    s = build_run_comparison([("a", w / "a"), ("b", w / "b")],
                             {"T-2": WorkResultRow("T-2", None, "PASS", None, None, None)})["summary"]
    assert s["사람 판정 대비 최종"]["a"].startswith("최종 기록 없음")
    assert s["사람 PASS 중 우리 PASS"] == {"b": "1/1"}
    with pytest.raises(CompareError):
        build_run_comparison([("a", w / "a")], {})


def test_compare_runs_reads_latest_run_copy_and_writes_workbook(tmp_path: Path) -> None:
    work_root = tmp_path / "task" / "03_results" / "_work"
    _write_run(work_root / "r1", [_g0(2, "REGENERATE", "옛 Task")], finals={2: "REVIEW"})
    _write_run(work_root / "r2", [_g0(2, "KEEP")], finals={2: "REVIEW"})
    (work_root / "r2" / "03_final.2.jsonl").write_text(_lines([{"source_row": 2, "id": "T-2", "final": {"status": "PASS"}}]),
                                                      encoding="utf-8")  # export로 다시 내보낸 최신 사본
    csv = tmp_path / "work.csv"
    csv.write_text("id,AI 판정,최종 판정,Regenerate Task,원본 Task(백업),검수 메모\nT-2,PASS,PASS,,,메모\n", encoding="utf-8")
    path = compare_runs(tmp_path / "task", ["이전=r1", "새=r2"], csv, marks=["C 유형=T-2"])
    assert path == work_root / "r2" / "compare_2runs.xlsx"
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["요약", "행별", "지표별 RF"]
    summary = {r[0]: r[1:] for r in wb["요약"].iter_rows(values_only=True) if r[0]}
    assert summary["사람 PASS 중 우리 PASS"] == ("0/1", "1/1")
    header = [c.value for c in wb["행별"][1]]
    row = dict(zip(header, [c.value for c in wb["행별"][2]]))
    assert (row["이전 G0 action"], row["새 G0 action"], row["검수 메모"], row["표시"]) == ("REGENERATE", "KEEP", "메모", "C 유형")
