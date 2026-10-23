"""OpenAI 전송 계층 (설계 6.3, 6.4).

API 키는 실제 API를 부르는 실행에서만 확인한다. import·테스트·estimate·export·compare에는 키가 필요 없다.
키는 환경 변수 OPENAI_API_KEY로만 받는다 (.env를 읽지 않는다).
실제 API로는 아직 검증하지 않았다 (회사 정책상 키는 구현 후 투입).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from ksco_qa.llm.types import LLMRequest, RawResponse, TransientError, Usage

API_KEY_ENV = "OPENAI_API_KEY"
API_KEY_MISSING_MSG = "OPENAI_API_KEY가 설정되지 않음"


class ApiKeyMissing(Exception):
    pass


def require_api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise ApiKeyMissing(API_KEY_MISSING_MSG)
    return key


def _retry_after(error: Any) -> float | None:
    response = getattr(error, "response", None)
    value = response.headers.get("retry-after") if response is not None else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


class OpenAITransport:
    """Responses API + structured outputs(strict). 재시도는 래퍼가 하므로 SDK 재시도는 끈다."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: Any = None
        self._client_loop: asyncio.AbstractEventLoop | None = None

    def _client_for_loop(self) -> Any:
        """단계마다 asyncio.run으로 루프가 바뀌므로, 루프가 바뀌면 클라이언트를 새로 만든다.
        AsyncOpenAI의 연결은 처음 쓴 루프에 묶여 있어 닫힌 루프의 연결을 다시 쓰면 실패한다."""
        from openai import AsyncOpenAI

        loop = asyncio.get_running_loop()
        if self._client is None or self._client_loop is not loop:
            self._client = AsyncOpenAI(api_key=self._api_key, max_retries=0)
            self._client_loop = loop
        return self._client

    async def create(self, request: LLMRequest) -> RawResponse:
        import openai

        try:
            resp = await self._client_for_loop().responses.create(
                model=request.model,
                reasoning={"effort": request.reasoning_effort},
                input=request.messages,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": request.schema_name,
                        "schema": request.schema,
                        "strict": True,
                    }
                },
            )
        except openai.RateLimitError as e:
            raise TransientError("429", _retry_after(e)) from e
        except openai.APITimeoutError as e:
            raise TimeoutError(str(e)) from e
        except openai.APIConnectionError as e:
            raise TransientError("network") from e
        except openai.APIStatusError as e:
            if e.status_code >= 500:
                raise TransientError(str(e.status_code), _retry_after(e)) from e
            raise
        return to_raw_response(resp)


def to_raw_response(resp: Any) -> RawResponse:
    refusal = None
    for item in getattr(resp, "output", None) or []:
        for content in getattr(item, "content", None) or []:
            if getattr(content, "type", None) == "refusal":
                refusal = content.refusal
    usage = None
    u = getattr(resp, "usage", None)
    if u is not None:
        cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", None) or 0
        reasoning = getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", None) or 0
        # API의 output_tokens는 추론 토큰을 포함한다 → 추론을 빼서 Usage.output으로 기록
        usage = Usage(input=u.input_tokens, cached_input=cached, output=u.output_tokens - reasoning, reasoning=reasoning)
    return RawResponse(text=resp.output_text, refusal=refusal, usage=usage, raw=resp.model_dump(mode="json"))
