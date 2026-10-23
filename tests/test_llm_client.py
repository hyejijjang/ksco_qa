"""LLM 래퍼 — MockClient로 재시도·재호출·calls.jsonl·비용·재개 경로 검증 (설계 6.3, 6.4, 7.3, 10.3)."""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from types import SimpleNamespace

import openai
import pytest

try:  # openai SDK 3.x는 httpx2를 쓴다
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

from ksco_qa.config import Config
from ksco_qa.llm.client import (
    MAX_TRANSIENT_RETRIES,
    BudgetExceeded,
    CallsLogWriter,
    ForbiddenContext,
    LLMClient,
    compute_cost,
)
from ksco_qa.llm.mock import MockClient, MockFaults
from ksco_qa.llm.openai_transport import (
    API_KEY_MISSING_MSG,
    ApiKeyMissing,
    OpenAITransport,
    require_api_key,
    to_raw_response,
)
from ksco_qa.llm.types import TransientError, Usage

PRICES = {"PRICE_INPUT": 1.0, "PRICE_CACHED_INPUT": 0.1, "PRICE_OUTPUT": 4.0}
ROW = {"source_row": 2, "id": "T-001", "job_leaf": "회계 사무원", "original_task": "원본 Task"}


def g0_validator(out: dict) -> list[str]:
    if out["job_evaluated"] != ROW["job_leaf"]:
        return [f"job_evaluated가 '{out['job_evaluated']}'인데 이 행의 직업은 '{ROW['job_leaf']}'이다"]
    return []


class Counting:
    """전송 계층 호출 수를 센다."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.requests = []

    async def create(self, request):
        self.requests.append(request)
        return await self.inner.create(request)


def make(run_dir: Path, faults: MockFaults | None = None, **cfg_kwargs):
    cfg = Config(**(PRICES | cfg_kwargs))
    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)

    transport = Counting(MockClient(faults))
    client = LLMClient(cfg, run_dir, CallsLogWriter(run_dir), transport, llm="mock", run_id="mock-test",
                       forbidden_terms=("accounting", "KSCO-33"), sleep=fake_sleep, rng=random.Random(0))
    return client, transport, sleeps


def call(client: LLMClient, **kw):
    kw.setdefault("stage", "G0")
    kw.setdefault("unit_id", 2)
    kw.setdefault("variable_input", ROW)
    kw.setdefault("validator", g0_validator)
    return asyncio.run(client.call(**kw))


def lines(run_dir: Path) -> list[dict]:
    return [json.loads(l) for l in (run_dir / "calls.jsonl").read_text(encoding="utf-8").splitlines()]


def test_ok_call_writes_record_raw_and_cost(tmp_path: Path) -> None:
    client, _, _ = make(tmp_path)
    res = call(client)
    assert res.status == "OK" and res.parsed["job_evaluated"] == "회계 사무원"
    [rec] = lines(tmp_path)
    assert rec["status"] == "OK" and rec["llm"] == "mock" and rec["model"] == "mock"
    assert rec["attempt_kind"] == "first" and rec["attempt"] == 1
    assert rec["reasoning_effort"] == "medium"
    u = Usage(**rec["usage"])
    assert rec["cost_usd"] == pytest.approx(compute_cost(u, Config(**PRICES)))
    assert rec["cost_usd"] > 0
    raw = json.loads((tmp_path / rec["raw_file"]).read_text(encoding="utf-8"))
    assert raw["parsed"] == res.parsed and raw["response"]["mock"] is True


def test_cost_formula() -> None:
    usage = Usage(input=1000, cached_input=400, output=200, reasoning=300)
    assert compute_cost(usage, Config(**PRICES)) == pytest.approx((600 * 1.0 + 400 * 0.1 + 500 * 4.0) / 1e6)
    assert compute_cost(usage, Config()) is None


def test_resume_skips_succeeded_call(tmp_path: Path) -> None:
    client, transport, _ = make(tmp_path)
    first = call(client)
    client2, transport2, _ = make(tmp_path)  # 새 프로세스처럼 다시 연다
    again = call(client2)
    assert again.from_cache and again.parsed == first.parsed and again.call_id == first.call_id
    assert transport2.requests == []
    assert len(lines(tmp_path)) == 1


def test_escalate_is_a_new_call(tmp_path: Path) -> None:
    client, transport, _ = make(tmp_path)
    a = call(client)
    b = call(client, attempt_kind="escalate", reasoning_effort="high")
    assert a.call_id != b.call_id and len(transport.requests) == 2
    assert lines(tmp_path)[1]["reasoning_effort"] == "high"
    assert transport.requests[1].timeout_s == 600


def test_rate_limit_retried_with_backoff(tmp_path: Path) -> None:
    client, transport, sleeps = make(tmp_path, MockFaults(rate_limit=1.0, repeats=2))
    res = call(client)
    assert res.status == "RETRIED" and res.parsed is not None
    [rec] = lines(tmp_path)
    assert rec["status"] == "RETRIED" and rec["transient_retries"] == 2
    assert sleeps == [1.0, 1.0]  # mock 429는 retry_after=1을 준다
    assert len(transport.requests) == 3


def test_rate_limit_exhausted_fails(tmp_path: Path) -> None:
    client, transport, sleeps = make(tmp_path, MockFaults(rate_limit=1.0, repeats=MAX_TRANSIENT_RETRIES + 1))
    res = call(client)
    assert res.status == "FAILED" and res.parsed is None
    assert len(sleeps) == MAX_TRANSIENT_RETRIES
    [rec] = lines(tmp_path)
    assert rec["status"] == "FAILED" and rec["usage"] is None and rec["raw_file"] is None


def test_backoff_without_retry_after_is_exponential(tmp_path: Path) -> None:
    class Flaky:
        def __init__(self) -> None:
            self.n = 0

        async def create(self, request):
            self.n += 1
            if self.n <= 3:
                raise TransientError("503")
            return await MockClient().create(request)

    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)

    client = LLMClient(Config(), tmp_path, CallsLogWriter(tmp_path), Flaky(), llm="mock", sleep=fake_sleep,
                       rng=random.Random(0))
    assert asyncio.run(client.call(stage="G0", unit_id=2, variable_input=ROW)).status == "RETRIED"
    assert [int(s) for s in sleeps] == [1, 2, 4]


def test_timeout_retried_once(tmp_path: Path) -> None:
    client, _, _ = make(tmp_path, MockFaults(timeout=1.0, repeats=1))
    assert call(client).status == "RETRIED"
    client2, _, _ = make(tmp_path / "b", MockFaults(timeout=1.0, repeats=2))
    assert call(client2).status == "FAILED"


def test_schema_fail_recalled_once_then_ok(tmp_path: Path) -> None:
    client, transport, _ = make(tmp_path, MockFaults(schema_fail=1.0, repeats=1))
    res = call(client)
    assert res.status == "OK"
    recs = lines(tmp_path)
    assert [r["status"] for r in recs] == ["SCHEMA_FAIL", "OK"]
    assert recs[0]["call_id"] == recs[1]["call_id"] and [r["attempt"] for r in recs] == [1, 2]
    assert recs[0]["validation_errors"]


def test_schema_fail_twice_is_failed(tmp_path: Path) -> None:
    client, _, _ = make(tmp_path, MockFaults(schema_fail=1.0, repeats=2))
    res = call(client)
    assert res.status == "FAILED" and res.parsed is None
    assert [r["status"] for r in lines(tmp_path)] == ["SCHEMA_FAIL", "FAILED"]


def test_validation_fail_feedback_recall_then_ok(tmp_path: Path) -> None:
    client, transport, _ = make(tmp_path, MockFaults(validation_fail=1.0, repeats=1))
    res = call(client)
    assert res.status == "OK" and res.attempt_kind == "feedback"
    recs = lines(tmp_path)
    assert [(r["status"], r["attempt_kind"]) for r in recs] == [("VALIDATION_FAIL", "first"), ("OK", "feedback")]
    assert recs[0]["call_id"] != recs[1]["call_id"]
    feedback_msg = transport.requests[1].messages[-1]["content"]
    assert "MOCK 다른 직업" in feedback_msg and "회계 사무원" in feedback_msg


def test_validation_fail_twice_returns_validation_fail(tmp_path: Path) -> None:
    client, _, _ = make(tmp_path, MockFaults(validation_fail=1.0, repeats=2))
    res = call(client)
    assert res.status == "VALIDATION_FAIL" and res.parsed is None and res.validation_errors
    assert [r["status"] for r in lines(tmp_path)] == ["VALIDATION_FAIL", "VALIDATION_FAIL"]


def test_resume_after_validation_fail_reuses_feedback_result(tmp_path: Path) -> None:
    client, _, _ = make(tmp_path, MockFaults(validation_fail=1.0, repeats=1))
    first = call(client)
    client2, transport2, _ = make(tmp_path)
    again = call(client2)
    assert again.from_cache and again.status == "OK" and again.parsed == first.parsed
    assert transport2.requests == []


def test_failed_call_is_retried_on_resume(tmp_path: Path) -> None:
    client, _, _ = make(tmp_path, MockFaults(schema_fail=1.0, repeats=2))
    assert call(client).status == "FAILED"
    client2, transport2, _ = make(tmp_path)
    assert call(client2).status == "OK" and len(transport2.requests) == 1
    assert [r["attempt"] for r in lines(tmp_path)] == [1, 2, 3]


def test_budget_exceeded_stops_after_logging(tmp_path: Path) -> None:
    client, _, _ = make(tmp_path, BUDGET_USD=1e-9)
    with pytest.raises(BudgetExceeded):
        call(client)
    assert len(lines(tmp_path)) == 1


@pytest.mark.parametrize("value", ["accounting 폴더", "KSCO-33 Task", r"C:\Users\x\a.csv"])
def test_forbidden_context_blocked_before_sending(tmp_path: Path, value: str) -> None:
    client, transport, _ = make(tmp_path)
    with pytest.raises(ForbiddenContext):
        call(client, variable_input=ROW | {"reference_note": value})
    assert transport.requests == []


def test_calls_log_is_append_only_and_tolerates_torn_line(tmp_path: Path) -> None:
    client, _, _ = make(tmp_path)
    call(client)
    path = tmp_path / "calls.jsonl"
    before = path.read_text(encoding="utf-8")
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"call_id": "torn"')  # 줄 중간에 죽은 상황
    client2, _, _ = make(tmp_path)
    call(client2, unit_id=3, variable_input=ROW | {"source_row": 3})
    text = path.read_text(encoding="utf-8")
    assert text.startswith(before)
    valid = [json.loads(l) for l in text.splitlines() if l and not l.startswith('{"call_id": "torn"')]
    assert len(valid) == 2


def test_concurrent_calls_all_logged(tmp_path: Path) -> None:
    client, _, _ = make(tmp_path, CONCURRENCY=3)

    async def many():
        rows = [ROW | {"source_row": r} for r in range(2, 22)]
        return await asyncio.gather(*(client.call(stage="G0", unit_id=r["source_row"], variable_input=r,
                                                  validator=g0_validator) for r in rows))

    results = asyncio.run(many())
    assert all(r.status == "OK" for r in results)
    assert len(lines(tmp_path)) == 20
    assert len({r.call_id for r in results}) == 20


# --- API 키·OpenAI 전송 계층 (실제 API 호출 없음) ---


def test_require_api_key_missing(no_api_key) -> None:
    with pytest.raises(ApiKeyMissing, match=API_KEY_MISSING_MSG):
        require_api_key()


def test_require_api_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert require_api_key() == "sk-test"


def test_openai_usage_mapping_excludes_reasoning_from_output() -> None:
    resp = SimpleNamespace(
        output_text='{"a": 1}',
        output=[SimpleNamespace(content=[SimpleNamespace(type="output_text")])],
        usage=SimpleNamespace(
            input_tokens=100, input_tokens_details=SimpleNamespace(cached_tokens=40),
            output_tokens=50, output_tokens_details=SimpleNamespace(reasoning_tokens=20),
        ),
        model_dump=lambda mode: {"id": "resp"},
    )
    raw = to_raw_response(resp)
    assert raw.usage == Usage(input=100, cached_input=40, output=30, reasoning=20)
    assert raw.text == '{"a": 1}' and raw.refusal is None


def test_openai_refusal_detected() -> None:
    resp = SimpleNamespace(
        output_text="", output=[SimpleNamespace(content=[SimpleNamespace(type="refusal", refusal="no")])],
        usage=None, model_dump=lambda mode: {},
    )
    assert to_raw_response(resp).refusal == "no"


def _status_error(cls, status: int, headers: dict | None = None):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.invalid/v1/responses"),
                              headers=headers or {})
    return cls("err", response=response, body=None)


@pytest.mark.parametrize(
    "error, expected",
    [
        (lambda: _status_error(openai.RateLimitError, 429, {"retry-after": "3"}), ("transient", 3.0)),
        (lambda: _status_error(openai.InternalServerError, 503), ("transient", None)),
        (lambda: openai.APITimeoutError(request=httpx.Request("POST", "https://api.invalid")), ("timeout", None)),
        (lambda: openai.APIConnectionError(request=httpx.Request("POST", "https://api.invalid")), ("transient", None)),
    ],
)
def test_openai_error_mapping(error, expected) -> None:
    transport = OpenAITransport.__new__(OpenAITransport)

    async def raise_error(**kwargs):
        raise error()

    fake = SimpleNamespace(responses=SimpleNamespace(create=raise_error))
    transport._client_for_loop = lambda: fake
    req = SimpleNamespace(model="m", reasoning_effort="medium", messages=[], schema_name="g0", schema={})
    kind, retry_after = expected
    if kind == "timeout":
        with pytest.raises(TimeoutError):
            asyncio.run(transport.create(req))
    else:
        with pytest.raises(TransientError) as e:
            asyncio.run(transport.create(req))
        assert e.value.retry_after == retry_after


def test_openai_transport_new_client_per_event_loop(monkeypatch) -> None:
    """단계마다 asyncio.run으로 루프가 바뀐다. 닫힌 루프에 묶인 클라이언트를 다시 쓰면 안 된다 (G0 → G1B 실 run에서 실패)."""
    created = []

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.loop = asyncio.get_running_loop()
            created.append(self)
            self.responses = SimpleNamespace(create=self._create)

        async def _create(self, **kwargs):
            if asyncio.get_running_loop() is not self.loop:
                raise RuntimeError("Event loop is closed")
            return SimpleNamespace(output=[], usage=None, output_text="{}",
                                   model_dump=lambda mode: {})

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeAsyncOpenAI)
    transport = OpenAITransport("sk-test")
    req = SimpleNamespace(model="m", reasoning_effort="medium", messages=[], schema_name="g0", schema={})

    async def two_calls():
        await transport.create(req)
        await transport.create(req)

    asyncio.run(two_calls())
    asyncio.run(transport.create(req))
    assert len(created) == 2
