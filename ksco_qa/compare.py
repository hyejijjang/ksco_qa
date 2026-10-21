"""비교 도구 (설계 4.1 비교 도구, 9.3, 10.1 compare --with). M5에서 구현, 지금은 입력 형식만.

Work 결과는 별도 jsonl이 없다. 두 가지 입력을 받는다 (2026-10-21 사용자 확인):
- Work 결과 CSV (예: KSCO-33_work_result.csv): 열 id, AI 판정, 최종 판정, Regenerate Task, 원본 Task(백업), 검수 메모
- DataList.xlsx의 "DataList" 탭 R~V열 (R=AI 판정, S=최종 판정, T=Regenerate Task, U=원본 Task(백업), V=검수 메모), id는 B열
이 열들은 비교에만 쓰고 row_card(모델 입력)에는 절대 넣지 않는다 (CLAUDE.md M1 결정).
판정 값의 어휘(AI 판정·최종 판정에 어떤 값이 들어가는지)와 API 결과 필드와의 대응은 M5에서 정한다.
"""

from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Work 결과 필드 ← CSV 열 이름 / DataList 열 문자
WORK_RESULT_FIELDS = {
    "ai_verdict": ("AI 판정", "R"),
    "final_verdict": ("최종 판정", "S"),
    "regenerated_task": ("Regenerate Task", "T"),
    "original_task_backup": ("원본 Task(백업)", "U"),
    "review_memo": ("검수 메모", "V"),
}
WORK_RESULT_CSV_COLUMNS = ["id"] + [name for name, _ in WORK_RESULT_FIELDS.values()]


class WorkResultFormatError(Exception):
    """Work 결과 파일의 열 구조가 기대와 다름, id 누락·중복."""


@dataclass(frozen=True)
class WorkResultRow:
    id: str
    ai_verdict: str | None
    final_verdict: str | None
    regenerated_task: str | None
    original_task_backup: str | None
    review_memo: str | None
    source_row: int | None = None  # DataList에서 읽었을 때 엑셀 물리 행 번호


def _norm(value: Any) -> str:
    return unicodedata.normalize("NFC", "" if value is None else str(value)).strip()


def _value(value: Any) -> str | None:
    text = _norm(value)
    return text or None


def _check_ids(rows: list[WorkResultRow], source: str) -> dict[str, WorkResultRow]:
    out: dict[str, WorkResultRow] = {}
    for r in rows:
        if not r.id:
            raise WorkResultFormatError(f"{source}: id가 빈 행이 있다")
        if r.id in out:
            raise WorkResultFormatError(f"{source}: id 중복 {r.id}")
        out[r.id] = r
    return out


def load_work_result_csv(path: Path) -> dict[str, WorkResultRow]:
    """Work 결과 CSV를 id → 행으로 읽는다. 인코딩은 UTF-8(BOM 포함) → CP949 순서."""
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise WorkResultFormatError(f"{Path(path).name}: UTF-8·CP949로 읽을 수 없다")
    reader = csv.DictReader(text.splitlines())
    header = [_norm(h) for h in reader.fieldnames or []]
    if header != WORK_RESULT_CSV_COLUMNS:
        raise WorkResultFormatError(f"{Path(path).name}: 열이 {WORK_RESULT_CSV_COLUMNS}이어야 한다 (실제 {header})")
    rows = []
    for raw in reader:
        row = {_norm(k): v for k, v in raw.items()}
        rows.append(WorkResultRow(_norm(row["id"]), *(_value(row[name]) for name, _ in WORK_RESULT_FIELDS.values())))
    return _check_ids(rows, Path(path).name)


def load_work_result_datalist(path: Path) -> dict[str, WorkResultRow]:
    """DataList.xlsx의 "DataList" 탭 R~V열을 id(B열) → 행으로 읽는다. 1행 머리글이 기대와 다르면 오류."""
    import openpyxl

    from ksco_qa.p0 import DATA_COLUMNS, SHEET_NAME, is_blank, norm_id

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    if SHEET_NAME not in wb.sheetnames:
        raise WorkResultFormatError(f"{Path(path).name}: '{SHEET_NAME}' 탭이 없다")
    ws = wb[SHEET_NAME]
    rows_iter = ws.iter_rows(values_only=True)
    header = list(next(rows_iter, ()))
    col = {letter: ord(letter) - ord("A") for letter in "BCDEFGHIRSTUV"}
    wrong = [f"{letter}열 '{_norm(header[col[letter]]) if col[letter] < len(header) else ''}' (기대 '{name}')"
             for name, letter in WORK_RESULT_FIELDS.values()
             if col[letter] >= len(header) or _norm(header[col[letter]]) != name]
    if wrong:
        raise WorkResultFormatError(f"{Path(path).name}: Work 결과 열 머리글이 다르다: " + "; ".join(wrong))
    rows = []
    for r, values in enumerate(rows_iter, start=2):
        values = list(values) + [None] * (max(col.values()) + 1 - len(values))
        if all(is_blank(values[col[c]]) for c in DATA_COLUMNS):
            continue  # 데이터 행 = B~I 중 하나라도 값 (P0와 같은 기준)
        rows.append(WorkResultRow(norm_id(values[col["B"]]) or "",
                                  *(_value(values[col[letter]]) for _, letter in WORK_RESULT_FIELDS.values()),
                                  source_row=r))
    return _check_ids(rows, Path(path).name)


def load_work_result(path: Path) -> dict[str, WorkResultRow]:
    """compare --with 입력: .csv면 Work 결과 CSV, .xlsx면 DataList R~V열."""
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        return load_work_result_csv(path)
    if suffix == ".xlsx":
        return load_work_result_datalist(path)
    raise WorkResultFormatError(f"Work 결과는 .csv 또는 DataList .xlsx여야 한다: {Path(path).name}")


# --- 비교 (M5) ---


def load_final_jsonl(results_dir: Path) -> list[dict[str, Any]]:
    """03_results/03_final.jsonl을 읽는다 (API 결과, 3장 원칙 8)."""
    raise NotImplementedError


def g0_action_agreement(api: list[dict[str, Any]], work: dict[str, WorkResultRow]) -> dict[str, Any]:
    """9.3: G0 action 일치율 / Cohen's kappa (id 기준). Work 판정 어휘와 action 대응은 M5에서 정한다."""
    raise NotImplementedError


def duplicate_pair_diff(api: list[dict[str, Any]], work: dict[str, WorkResultRow]) -> dict[str, Any]:
    """9.3: G1 확정 중복 쌍 양방향 차이."""
    raise NotImplementedError


def verify_status_agreement(api: list[dict[str, Any]], work: dict[str, WorkResultRow]) -> dict[str, Any]:
    """9.3: 양쪽 모두 평가한 행의 G2 verify_status 일치율."""
    raise NotImplementedError


def final_status_agreement(api: list[dict[str, Any]], work: dict[str, WorkResultRow]) -> dict[str, Any]:
    """9.3: 최종 status 일치율."""
    raise NotImplementedError


def compare_results(api_results: Path, work_result: Path) -> dict[str, Any]:
    """API 결과(03_final.jsonl)와 Work 결과(CSV 또는 DataList R~V)의 일치도 리포트. 불일치 행은 4분류 대상 (9.3)."""
    raise NotImplementedError
