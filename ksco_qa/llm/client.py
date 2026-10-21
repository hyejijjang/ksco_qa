"""LLM 클라이언트 래퍼 — 골격 (설계 6장, 7.3, 8.2).

맡는 일: 스키마 강제(structured outputs), 단계별 모델·추론 강도, 재시도·백오프·동시성,
코드 검증 → 피드백 재호출, call_id 중복 방지·재개, usage 실측 → 비용, online/Batch 모드.
테스트에서는 이 클라이언트를 mock한다 (CLAUDE.md 개발 규칙).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ksco_qa.config import Config


@dataclass(frozen=True)
class Usage:
    """API usage 실측값 (7.3 usage.*). 추정값을 넣지 않는다."""

    input: int
    cached_input: int
    output: int
    reasoning: int


@dataclass
class CallResult:
    """호출 1회 결과. parsed는 스키마·코드 검증을 통과했을 때만 채운다."""

    call_id: str
    status: str  # enums.yaml call_status
    parsed: dict[str, Any] | None
    usage: Usage | None
    validation_errors: list[str] = field(default_factory=list)


def load_prompt(stage: str, g2_overlap_mode: str | None = None) -> str:
    """common.md + 단계 프롬프트를 이어 고정 지시를 만든다 (6.2-1, 8.1).

    Task 이름·폴더 이름·절대 경로는 넣지 않는다 (CLAUDE.md 원칙 5).
    """
    raise NotImplementedError


def prompt_version(stage: str, g2_overlap_mode: str | None = None) -> str:
    """단계 프롬프트 + common + 스키마 + 기준 발췌를 합친 텍스트의 해시 (8.2)."""
    raise NotImplementedError


def build_messages(stage: str, variable_input: dict[str, Any], feedback: list[str] | None = None) -> list[dict[str, Any]]:
    """고정 지시 → 가변 입력(row_card 등, 재호출이면 직전 검증 실패 사유) 순으로 메시지를 만든다 (6.2, 6.3)."""
    raise NotImplementedError


def compute_cost(usage: Usage, cfg: Config) -> float:
    """cost = 비캐시 입력·P_in + 캐시 입력·P_cache + (출력 + 추론)·P_out (11.1). 실측 usage만 쓴다."""
    raise NotImplementedError


class CallsLogWriter:
    """calls.jsonl 단일 writer (CLAUDE.md 원칙 6). 추가 전용, 한 줄씩 flush (7.3, 10.3)."""

    def __init__(self, run_dir: Path) -> None:
        raise NotImplementedError

    def append(self, record: dict[str, Any]) -> None:
        raise NotImplementedError

    def succeeded_call_ids(self) -> set[str]:
        """재개 기준: calls.jsonl의 성공 기록 (10.3)."""
        raise NotImplementedError


class LLMClient:
    """online 모드 호출 (6.1, 6.3, 6.4)."""

    def __init__(self, cfg: Config, run_dir: Path, log_writer: CallsLogWriter) -> None:
        raise NotImplementedError

    async def call(
        self,
        *,
        stage: str,
        unit_id: str | int,
        variable_input: dict[str, Any],
        schema_name: str,
        reasoning_effort: str,
        attempt_kind: str,
        feedback: list[str] | None = None,
    ) -> CallResult:
        """호출 1회. 429·5xx·네트워크는 지수 백오프 최대 5회, 타임아웃 300초(high 600초)·재시도 1회,
        스키마 파싱 실패·빈 응답·거절은 재호출 1회 후 FAILED (6.4). 원문은 raw/<call_id>.json (7.3)."""
        raise NotImplementedError


class BatchSubmitter:
    """--mode batch: 단계별 Batch API 제출 → 완료 대기 → 결과 수집 (6.5)."""

    def __init__(self, cfg: Config, run_dir: Path, log_writer: CallsLogWriter) -> None:
        raise NotImplementedError

    def submit(self, stage: str, requests: list[dict[str, Any]]) -> str:
        raise NotImplementedError

    def wait_and_collect(self, batch_id: str) -> list[CallResult]:
        raise NotImplementedError
