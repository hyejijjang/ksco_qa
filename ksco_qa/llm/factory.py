"""LLM 클라이언트 조립: --llm openai / mock."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ksco_qa.config import Config
from ksco_qa.llm.client import CallsLogWriter, LLMClient
from ksco_qa.llm.mock import MockClient, MockFaults
from ksco_qa.progress import Progress

if TYPE_CHECKING:
    from ksco_qa.run import RunContext

LLM_CHOICES = ("openai", "mock")


def build_client(cfg: Config, ctx: "RunContext", faults: MockFaults | None = None) -> LLMClient:
    """openai는 이 시점에 API 키를 확인한다 (키가 없으면 ApiKeyMissing)."""
    if ctx.llm == "mock":
        transport = MockClient(faults)
    elif ctx.llm == "openai":
        from ksco_qa.llm.openai_transport import OpenAITransport, require_api_key

        transport = OpenAITransport(require_api_key())
    else:
        raise ValueError(f"--llm은 {LLM_CHOICES} 중 하나: {ctx.llm!r}")
    forbidden = (ctx.task_folder.name, ctx.task_name, str(ctx.task_folder.resolve()))
    return LLMClient(
        cfg, ctx.run_dir, CallsLogWriter(ctx.run_dir), transport,
        llm=ctx.llm, run_id=ctx.run_id, forbidden_terms=forbidden, progress=Progress(),
    )
