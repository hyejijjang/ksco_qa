"""같은 표본을 여러 번 돌린 run의 행별 비교표 (2026-10-26, M2 게이트 사람 검토용).

run마다 G0 action·차원별 R/F·재생성 Task, G1·G2·최종 상태, G2 R 유형(A/B/C), b_coverage, 파일 입력(전문/프로필),
입력 토큰·비용을 나란히 놓고, Work 결과(사람 최종 판정·검수 메모)를 붙인다. 첫 run이 기준(이전)이다.
모델을 부르지 않고 run 폴더 기록만 읽는다. Work 결과 열은 비교에만 쓰고 모델 입력에는 넣지 않는다 (CLAUDE.md M1 결정).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from ksco_qa.compare import CompareError, WorkResultRow, load_work_result
from ksco_qa.dictionaries import g0_check_keys, g2_check_keys
from ksco_qa.g3.export import FINAL_JSONL, final_copy_paths

COMMON_HEADERS = ["source_row", "id", "job_leaf", "표시", "사람 AI 판정", "사람 최종 판정", "검수 메모",
                  "Work Regenerate Task", "원본 Task"]
RUN_FIELDS = ["G0 action", "G0 R/F 차원", "재판정", "재생성 Task", "G1", "G2", "G2 R 지표(유형)", "b_coverage",
              "최종", "파일 입력", "입력 토큰(G0+G2)", "비용(G0+G2)"]

# G2 R 유형 (2026-10-26 분석) — 키워드 분류라 근사값이다.
# A: 입력 자료 미기재, B: 프로필 범위 밖 미확인(00 6.3 기준대로 둠), C: 그 밖(실제 설계 문제 후보)
_INPUT_RE = re.compile(r"제공된 자료|입력 ?자료|원천 ?(자료|입력)|입력 계약|입력 파일|어떤 자료")
_PROFILE_RE = re.compile(
    r"(file_profile|file_fulltext|프로필|요약|관찰).{0,150}?"
    r"(확인(할 수 없|되지 않|하지 못|해 주지 않|시킬 뿐)|대조할 수 없|뿐|만 (제공|제시|요약)|일부|축약|"
    r"나타나지 않|포함되지 않|제시되지 않)"
    r"|확인(할 수 없|되지 않|하지 못).{0,60}(file_profile|file_fulltext|프로필)")


def classify_g2_issue(indicator: str, text: str) -> str:
    if indicator == "input_contract" or (_INPUT_RE.search(text) and not _PROFILE_RE.search(text)):
        return "A"
    if _PROFILE_RE.search(text):
        return "B"
    return "C"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _by_row(records: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """추가 전용 기록이므로 같은 행은 마지막 줄이 이긴다."""
    return {int(r["source_row"]): r for r in records}


def _final_records(run_dir: Path) -> dict[int, dict[str, Any]]:
    """run 폴더의 03_final.jsonl 사본(가장 최근), 없으면 03_results/03_final.jsonl 중 이 run이 내보낸 것."""
    copies = final_copy_paths(run_dir)
    if copies:
        return _by_row(_jsonl(copies[-1]))
    records = _jsonl(run_dir.parent.parent / FINAL_JSONL)  # 사본을 남기기 전(2026-10-26 이전) run
    if records and f"run_id={run_dir.name};" in str(records[0].get("final", {}).get("execution_notes")):
        return _by_row(records)
    return {}


def load_run(run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    if not (run_dir / "g0" / "records.jsonl").is_file():
        raise CompareError(f"G0 기록이 없다: {run_dir / 'g0' / 'records.jsonl'}")
    report = run_dir / "run_report.json"
    return {
        "run_id": run_dir.name,
        "cards": _by_row(_jsonl(run_dir / "row_cards.jsonl")),
        "g0": _by_row(_jsonl(run_dir / "g0" / "records.jsonl")),
        "g1": _by_row(_jsonl(run_dir / "g1" / "rows.jsonl")),
        "g2": _by_row(_jsonl(run_dir / "g2" / "records.jsonl")),
        "final": _final_records(run_dir),
        "calls": _jsonl(run_dir / "calls.jsonl"),
        "report": json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {},
    }


def _g0_flagged(record: dict[str, Any] | None) -> list[str]:
    checks = ((record or {}).get("output") or {}).get("checks") or {}
    return [f"{key}:{checks[key]}" for key in g0_check_keys() if checks.get(key) in ("R", "F")]


def g2_checks(record: dict[str, Any] | None) -> dict[str, str]:
    out = (record or {}).get("output") or {}
    return {**((out.get("overlap_review") or {}).get("checks") or {}), **(out.get("new_checks") or {})}


def g2_flagged(record: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    """(지표, R|F, 유형) — R/F인 G2 지표마다 issues 문장으로 A/B/C를 붙인다."""
    issues = ((record or {}).get("output") or {}).get("issues") or {}
    checks = g2_checks(record)
    return [(key, checks[key], classify_g2_issue(key, issues.get(key) or ""))
            for key in g2_check_keys() if checks.get(key) in ("R", "F")]


def file_input(card: dict[str, Any]) -> str:
    """fulltext 모드에서 원본 전문이 붙은 행과 크기 초과로 프로필만 쓴 행을 구분한다."""
    if "file_fulltext_note" not in card:
        return "프로필 모드"
    notes = [n for n in str(card.get("file_fulltext_note") or "").split("; ") if n]
    attached = sum("원본 전문 첨부" in n for n in notes)
    if notes and attached == len(notes):
        return "전문"
    if attached:
        return "일부 전문 (나머지 프로필)"
    return "프로필 (크기 초과·미첨부)"


def _row_usage(run: dict[str, Any], row: int) -> tuple[int, float]:
    calls = [c for c in run["calls"] if c.get("stage") in ("G0", "G2") and str(c.get("unit_id")) == str(row)]
    return (sum((c.get("usage") or {}).get("input") or 0 for c in calls),
            round(sum(c.get("cost_usd") or 0 for c in calls), 6))


def _run_row(run: dict[str, Any], row: int) -> dict[str, Any]:
    g0 = run["g0"].get(row)
    out = (g0 or {}).get("output") or {}
    g2 = run["g2"].get(row)
    tokens, cost = _row_usage(run, row)
    card = run["cards"].get(row, {})
    return {
        "G0 action": (g0 or {}).get("action"),
        "G0 R/F 차원": ", ".join(_g0_flagged(g0)),
        "재판정": (g0 or {}).get("escalated"),
        "재생성 Task": out.get("regenerated_task_new"),
        "G1": (run["g1"].get(row) or {}).get("status"),
        "G2": (g2 or {}).get("status"),
        "G2 R 지표(유형)": ", ".join(f"{k}:{v}({t})" for k, v, t in g2_flagged(g2)),
        "b_coverage": ((g2 or {}).get("output") or {}).get("b_coverage_status"),
        "최종": (run["final"].get(row) or {}).get("final", {}).get("status"),
        "파일 입력": file_input(card) if card else None,
        "입력 토큰(G0+G2)": tokens,
        "비용(G0+G2)": cost,
    }


def _class_recall(run: dict[str, Any], rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    """전체 일치율은 다수 클래스(REVIEW)에 끌려가므로 사람 판정 클래스별로 본다."""
    judged = [r for r in rows if r["사람 최종 판정"]]
    if not run["final"]:
        return {"사람 판정 대비 최종": "최종 기록 없음 (run 폴더 사본·이 run의 03_final.jsonl 없음)"}
    out = {}
    for c in sorted({r["사람 최종 판정"] for r in judged}):
        members = [r for r in judged if r["사람 최종 판정"] == c]
        out[f"사람 {c} 중 우리 {c}"] = f"{sum(r[f'{label} 최종'] == c for r in members)}/{len(members)}"
    hits = sum(r[f"{label} 최종"] == r["사람 최종 판정"] for r in judged)
    out["전체 일치"] = f"{hits}/{len(judged)} ({hits / len(judged):.0%})" if judged else None
    return out


def _run_summary(run: dict[str, Any], rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    def counts(field: str) -> dict[str, int]:
        return dict(Counter(r[f"{label} {field}"] for r in rows if r[f"{label} {field}"] is not None))

    types = Counter(t for g2 in run["g2"].values() for _, _, t in g2_flagged(g2))
    human_pass = [r for r in rows if r["사람 최종 판정"] == "PASS"]
    total = run["report"].get("usage", {}).get("total", {})
    n = len(rows) or 1
    return {
        "run_id": run["run_id"],
        **_class_recall(run, rows, label),
        "G0 action": counts("G0 action"),
        "사람 최종 PASS 중 REGENERATE": sum(r[f"{label} G0 action"] == "REGENERATE" for r in human_pass),
        "G0 재판정 호출": sum(c.get("stage") == "G0" and c.get("attempt_kind") == "escalate" for c in run["calls"]),
        "G1": counts("G1"),
        "G2": counts("G2"),
        "G2 R 유형 A (입력 미기재)": types["A"],
        "G2 R 유형 B (프로필 범위 밖)": types["B"],
        "G2 R 유형 C (그 밖)": types["C"],
        "b_coverage": counts("b_coverage"),
        "최종": counts("최종"),
        "파일 입력": counts("파일 입력"),
        "입력 토큰 합계": total.get("input"),
        "행당 입력 토큰": round(total["input"] / n) if total.get("input") is not None else None,
        "비용 USD": total.get("cost_usd"),
        "행당 비용 USD": round(total["cost_usd"] / n, 6) if total.get("cost_usd") is not None else None,
        "템플릿 감지": run["report"].get("validation", {}).get("template_sentences"),
    }


def build_run_comparison(runs: list[tuple[str, Path]], work: dict[str, WorkResultRow],
                         marks: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """runs = [(이름, run 폴더), …]. 첫 run이 기준. marks = {표시 이름: [id, …]} (예: "C 유형")."""
    if len(runs) < 2:
        raise CompareError("비교할 run이 둘 이상 필요하다")
    loaded = [(label, load_run(path)) for label, path in runs]
    mark_of: dict[str, list[str]] = {}
    for name, ids in (marks or {}).items():
        for row_id in ids:
            mark_of.setdefault(row_id, []).append(name)
    base = loaded[-1][1]
    rows = []
    for row in sorted(base["g0"]):
        row_id = base["g0"][row]["id"]
        card = base["cards"].get(row, {})
        w = work.get(row_id)
        r = {"source_row": row, "id": row_id, "job_leaf": card.get("job_leaf"), "표시": ", ".join(mark_of.get(row_id, [])),
             "사람 AI 판정": w.ai_verdict if w else None, "사람 최종 판정": w.final_verdict if w else None,
             "검수 메모": w.review_memo if w else None, "Work Regenerate Task": w.regenerated_task if w else None,
             "원본 Task": card.get("original_task")}
        for label, run in loaded:
            r.update({f"{label} {k}": v for k, v in _run_row(run, row).items()})
        rows.append(r)

    dimensions = []
    for stage, keys in (("G0", g0_check_keys()), ("G2", g2_check_keys())):
        for key in keys:
            d = {"단계": stage, "지표": key}
            for label, run in loaded:
                if stage == "G0":
                    values = Counter(((g.get("output") or {}).get("checks") or {}).get(key) for g in run["g0"].values())
                else:
                    values = Counter(g2_checks(g).get(key) for g in run["g2"].values())
                d[f"{label} R"], d[f"{label} F"] = values["R"], values["F"]
            dimensions.append(d)

    summary: dict[str, dict[str, Any]] = {}
    for label, run in loaded:
        for metric, value in _run_summary(run, rows, label).items():
            summary.setdefault(metric, {})[label] = value
    judged = [r for r in rows if r["사람 최종 판정"]]
    for c in sorted({r["사람 최종 판정"] for r in judged}):
        n = sum(r["사람 최종 판정"] == c for r in judged)
        summary[f"기준선: 전부 {c}로 답하면 전체 일치"] = {label: f"{n}/{len(judged)} ({n / len(judged):.0%})"
                                                for label, _ in loaded}
    review_b_ids = [r["id"] for r in rows if any(r[f"{label} G0 action"] == "REVIEW_B" for label, _ in loaded)]
    for r in rows:
        if r["id"] in review_b_ids:
            summary[f"REVIEW_B 변화: {r['id']}"] = {label: f"{r[f'{label} G0 action']} / {r[f'{label} 파일 입력']}"
                                                   for label, _ in loaded}
    for name, ids in (marks or {}).items():
        for r in rows:
            if r["id"] in ids:
                summary[f"{name}: {r['id']}"] = {label: f"G2 {r[f'{label} G2']} · {r[f'{label} G2 R 지표(유형)']}"
                                               for label, _ in loaded}
    # 사람 판정 대비 지표와 기준선을 run_id 바로 아래에 모은다
    top = ("사람 판정", "사람 PASS", "사람 REVIEW", "사람 FAIL", "전체 일치", "기준선")
    first = ["run_id"] + [k for k in summary if k.startswith(top)]
    summary = {k: summary[k] for k in first + [k for k in summary if k not in first]}
    return {"labels": [label for label, _ in loaded], "rows": rows, "dimensions": dimensions, "summary": summary}


def _cell(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_run_comparison_xlsx(path: Path, comparison: dict[str, Any]) -> Path:
    labels = comparison["labels"]
    workbook = Workbook()
    summary = workbook.active
    summary.title = "요약"
    summary.append(["지표", *labels])
    for metric, values in comparison["summary"].items():
        summary.append([metric, *(_cell(values.get(label)) for label in labels)])
    summary.append([])
    summary.append(["G2 R 유형은 issues 문장 키워드 분류(근사): A 입력 자료 미기재 · B 프로필 범위 밖 미확인 · C 그 밖"])
    sheet = workbook.create_sheet("행별")
    headers = COMMON_HEADERS + [f"{label} {field}" for field in RUN_FIELDS for label in labels]
    sheet.append(headers)
    for row in comparison["rows"]:
        sheet.append([_cell(row.get(h)) for h in headers])
    dims = workbook.create_sheet("지표별 RF")
    headers = ["단계", "지표"] + [f"{label} {k}" for label in labels for k in ("R", "F")]
    dims.append(headers)
    for row in comparison["dimensions"]:
        dims.append([row[h] for h in headers])
    path = Path(path)
    workbook.save(path)
    return path


def parse_run_option(value: str) -> tuple[str, str]:
    """"이름=run_id" 또는 "run_id"."""
    label, _, run_id = value.partition("=")
    return (label.strip(), run_id.strip()) if run_id else (value.strip(), value.strip())


def parse_mark_option(value: str) -> tuple[str, list[str]]:
    """"C 유형=task_0000012,task_0000030"."""
    name, _, ids = value.partition("=")
    if not ids:
        raise CompareError(f"--mark는 '이름=id,id' 형식이어야 한다: {value}")
    return name.strip(), [i.strip() for i in ids.split(",") if i.strip()]


def compare_runs(task_folder: Path, runs: list[str], work_result: Path, out: Path | None = None,
                 marks: list[str] | None = None) -> Path:
    work_root = Path(task_folder) / "03_results" / "_work"
    parsed = [parse_run_option(r) for r in runs]
    for _, run_id in parsed:
        if not (work_root / run_id).is_dir():
            raise CompareError(f"run 폴더가 없다: {work_root / run_id}")
    comparison = build_run_comparison([(label, work_root / run_id) for label, run_id in parsed],
                                      load_work_result(work_result), dict(parse_mark_option(m) for m in marks or []))
    default = work_root / parsed[-1][1] / f"compare_{len(parsed)}runs.xlsx"
    return write_run_comparison_xlsx(out or default, comparison)
