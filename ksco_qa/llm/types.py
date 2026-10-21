"""LLM 호출 공통 자료형 (설계 6장, 7.3)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Usage:
    """API usage 실측값 (7.3 usage.*). 추정값을 넣지 않는다.

    input은 캐시 포함 전체 입력, cached_input은 그중 캐시 적중분.
    output은 추론을 뺀 출력, reasoning은 추론 토큰 (11.1 산식의 T_out, T_reasoning).
    """

    input: int
    cached_input: int
    output: int
    reasoning: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class LLMRequest:
    """전송 계층에 넘기는 요청 1건."""

    call_id: str
    stage: str
    unit_id: str
    attempt: int
    model: str
    reasoning_effort: str
    schema_name: str
    schema: dict[str, Any]
    messages: list[dict[str, str]]
    variable_input: dict[str, Any]
    timeout_s: float


@dataclass(frozen=True)
class RawResponse:
    """전송 계층의 응답. text는 모델 출력 원문(JSON 문자열), refusal은 거절 메시지."""

    text: str | None
    refusal: str | None
    usage: Usage | None
    raw: dict[str, Any]


class TransientError(Exception):
    """429·5xx·네트워크 오류 (6.4). retry_after는 응답이 알려 준 재시도 대기 시간(초)."""

    def __init__(self, kind: str, retry_after: float | None = None) -> None:
        super().__init__(kind)
        self.kind = kind
        self.retry_after = retry_after


class Transport(Protocol):
    """OpenAI 또는 Mock. 요청 1건을 보내고 응답 1건을 돌려준다.
    일시 오류는 TransientError, 시간 초과는 TimeoutError로 알린다."""

    async def create(self, request: LLMRequest) -> RawResponse: ...


@dataclass
class CallResult:
    """판정 호출 1회의 최종 결과. parsed는 스키마·코드 검증을 통과했을 때만 채운다."""

    call_id: str
    status: str  # enums.yaml call_status
    parsed: dict[str, Any] | None
    usage: Usage | None
    attempt_kind: str
    validation_errors: list[str] = field(default_factory=list)
    from_cache: bool = False
