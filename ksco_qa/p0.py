"""P0 — 사전 검사·매핑·파일 프로필 (코드) — 골격 (설계 5.1, 7.1 / 00_Work_Run.md 3장)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ksco_qa.config import Config

EXPECTED_HEADERS = {"B": "id", "C": "직업명", "D": "산출물", "E": "레퍼런스", "F": "출력포맷", "G": "태스크", "I": "직무정보"}


class P0Stop(Exception):
    """실행 중단 사유 (DataList 0개·2개 이상, 헤더 불일치, id 누락·중복, NOT_FOUND 비율 초과)."""


@dataclass
class InventoryEntry:
    name_nfc: str
    locator: str  # 01_output_files/ 기준 상대 경로, ZIP 멤버면 멤버 경로 포함
    in_zip: bool
    accessible: bool


@dataclass
class MatchResult:
    expected_filename: str | None
    match_status: str  # enums.yaml match_status
    matched_locator: str | None
    reason: str


def find_datalist(task_folder: Path) -> tuple[Path, str]:
    """5.1-1: *_DataList.xlsx를 정확히 1개 찾고 TASK_NAME을 파일명에서 얻는다."""
    raise NotImplementedError


def validate_headers(ws: Any) -> None:
    """5.1-2: B=id, C=직업명, D=산출물, E=레퍼런스, F=출력포맷, G=태스크, I=직무정보. 다르면 중단."""
    raise NotImplementedError


def read_datalist(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """5.1-3·4: 캐시 계산값으로 읽고, 다시 읽어 수식·하이퍼링크 원문을 셀별 보관.
    데이터 행 = B~I열 중 하나라도 값이 있는 행. 반환: (데이터 행, source_cells)."""
    raise NotImplementedError


def check_identifiers(rows: list[dict[str, Any]]) -> list[str]:
    """5.1-5: id 누락·중복이면 P0Stop. I열 비었거나 "매칭 실패"면 경고 목록을 돌려준다."""
    raise NotImplementedError


def build_inventory(output_dir: Path) -> list[InventoryEntry]:
    """5.1-6: 01_output_files/ 전체와 ZIP 멤버 목록화. 이름은 NFC 정규화."""
    raise NotImplementedError


def expected_filename(name_d: str, format_f: str) -> str | None:
    """5.1-7 / 00_Work_Run.md 3.1: {D}.{F}. F는 양끝 공백·앞 점 1개만 정리. 복수 형식·누락이면 None(CONFLICT)."""
    raise NotImplementedError


def match_deliverable(row: dict[str, Any], inventory: list[InventoryEntry]) -> MatchResult:
    """5.1-7: 전체 이름 정확 일치 (NFC·확장자 대소문자만 허용)."""
    raise NotImplementedError


def check_not_found_ratio(results: list[MatchResult], stop_ratio: float) -> None:
    """5.1-8: NOT_FOUND가 데이터 행의 stop_ratio를 넘으면 P0Stop (경로·ZIP·권한 문제 보고)."""
    raise NotImplementedError


def classify_reference(e_value: Any) -> tuple[str, str | None]:
    """5.1-9: Reference 분기. E열 해석 규칙은 결정 필요 (14장 #4)."""
    raise NotImplementedError


def build_row_card(row: dict[str, Any], match: MatchResult, reference: tuple[str, str | None], file_profile: str | None) -> dict[str, Any]:
    """5.1-11, 7.1: row_card. O·L·M열은 넣지 않는다."""
    raise NotImplementedError


def write_mapping_audit(path: Path, rows: list[dict[str, Any]]) -> None:
    """03_results/00_mapping_audit.csv (00_Work_Run.md 3.3 최소 열)."""
    raise NotImplementedError


def run_p0(task_folder: Path, cfg: Config, run_dir: Path) -> list[dict[str, Any]]:
    """5.1 전체. 완료 조건: 데이터 행 수 = row_card 수 = mapping_audit 행 수."""
    raise NotImplementedError
