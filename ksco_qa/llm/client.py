"""LLM 클라이언트 래퍼 (설계 6장, 7.3, 8.2, 10.3).

맡는 일: 스키마 강제·검증, 단계별 모델·추론 강도, 재시도·백오프·동시성,
코드 검증 → 피드백 재호출, call_id 중복 방지·재개, usage 실측 → 비용.
실제 전송은 Transport(OpenAI 또는 Mock)가 한다. 테스트는 MockClient를 쓴다.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from jsonschema import Draft202012Validator

from ksco_qa.config import Config
from ksco_qa.dictionaries import PROMPT_DIR, enum_values, load_schema
from ksco_qa.llm.call_id import canonical_json, input_hash, make_call_id, sha256_hex
from ksco_qa.llm.types import CallResult, LLMRequest, RawResponse, TransientError, Transport, Usage

# 단계 → (프롬프트 파일, 스키마 이름)
STAGE_FILES = {"G0": ("g0.md", "g0"), "G1B": ("g1b.md", "g1b"), "G2": ("g2.md", "g2")}

SUCCESS_STATUSES = ("OK", "RETRIED")
MAX_TRANSIENT_RETRIES = 5  # 6.4: 429·5xx·네트워크 최대 5회
MAX_BACKOFF_S = 60.0
TIMEOUT_S = 300.0  # 6.4: 호출당 기본 300초
TIMEOUT_HIGH_S = 600.0  # 6.4: high는 600초

# 6.3 재호출 메시지 머리 (M1 결정 28). 아래에 위반 항목을 "- <항목>"으로 나열한다.
FEEDBACK_HEADER = "직전 응답이 아래 검증 규칙을 위반했다. 입력은 같다. 아래 항목을 고친 전체 응답을 처음부터 다시 출력하라."

_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_STAGES_RE = re.compile(r"<!--\s*stages:\s*([A-Z0-9 ]+?)\s*-->")
RULES_INCLUDE = "<!-- include rules.md -->"

# 호출에 절대 경로를 넣지 않는다 (CLAUDE.md 원칙 5)
_DRIVE_PATH_RE = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")

Validator = Callable[[dict[str, Any]], list[str]]


class BudgetExceeded(Exception):
    """누적 비용이 BUDGET_USD를 넘음 (10.2)."""


class ForbiddenContext(Exception):
    """호출 메시지에 Task 이름·폴더 이름·절대 경로가 들어감 (CLAUDE.md 원칙 5)."""


def strip_comments(text: str) -> str:
    """<!-- --> 주석을 지우고 빈 줄을 정리한다 (M1 결정 26)."""
    return _BLANK_LINES_RE.sub("\n\n", _COMMENT_RE.sub("", text)).strip() + "\n"


def select_overlap_section(text: str, mode: str) -> str:
    """g2.md에서 G2_OVERLAP_MODE에 해당하는 '## 겹치는 10개 지표 — <모드>' 섹션 하나만 남긴다 (결정 26)."""
    modes = enum_values("g2_overlap_mode")
    if mode not in modes:
        raise ValueError(f"G2_OVERLAP_MODE {mode!r}는 허용값이 아니다: {modes}")
    sections = re.split(r"(?m)^(?=## )", text)
    kept, found = [], False
    for section in sections:
        heading = section.split("\n", 1)[0]
        mode_in_heading = [m for m in modes if heading.startswith("## ") and m in heading]
        if mode_in_heading and mode_in_heading[0] != mode:
            continue
        found |= mode in mode_in_heading
        kept.append(section)
    if not found:
        raise ValueError(f"g2.md에 '{mode}' 섹션이 없다")
    return "".join(kept)


def select_rules(text: str, stage: str) -> str:
    """rules.md에서 이 단계에 보낼 줄만 남긴다. "<!-- stages: G0 G2 -->"는 다음 표시까지의 줄에 적용된다 (2026-10-26)."""
    text = _COMMENT_RE.sub(lambda m: m.group(0) if _STAGES_RE.fullmatch(m.group(0)) else "", text)
    kept, stages = [], None
    for line in text.splitlines():
        marker = _STAGES_RE.fullmatch(line.strip())
        if marker:
            stages = marker.group(1).split()
            continue
        if stages is None or stage in stages:
            kept.append(line)
    return "\n".join(kept).strip() + "\n"


def include_rules(text: str, stage: str) -> str:
    """단계 프롬프트의 "<!-- include rules.md -->" 자리에 공통 해석 규칙을 넣는다 (g0·g2가 같은 규칙 파일을 쓴다)."""
    if RULES_INCLUDE not in text:
        return text
    rules = select_rules((PROMPT_DIR / "rules.md").read_text(encoding="utf-8"), stage)
    return text.replace(RULES_INCLUDE, rules)


def load_prompt(stage: str, g2_overlap_mode: str | None = None) -> str:
    """common.md + 단계 프롬프트(+ rules.md 해석 규칙) = 고정 지시 (6.2-1, 8.1). 주석은 지우고, G2는 모드 섹션 하나만."""
    common = (PROMPT_DIR / "common.md").read_text(encoding="utf-8")
    stage_text = include_rules((PROMPT_DIR / STAGE_FILES[stage][0]).read_text(encoding="utf-8"), stage)
    if stage == "G2":
        if g2_overlap_mode is None:
            raise ValueError("G2 프롬프트에는 g2_overlap_mode가 필요하다")
        stage_text = select_overlap_section(stage_text, g2_overlap_mode)
    return strip_comments(common) + "\n" + strip_comments(stage_text)


def schema_version(stage: str) -> str:
    return sha256_hex(canonical_json(load_schema(STAGE_FILES[stage][1])))[:16]


def prompt_version(stage: str, g2_overlap_mode: str | None = None) -> str:
    """실제로 보내는 고정 지시 + 스키마의 해시 (8.2, 결정 26). 발췌는 프롬프트 파일 안에 있다."""
    schema = canonical_json(load_schema(STAGE_FILES[stage][1]))
    return sha256_hex(load_prompt(stage, g2_overlap_mode) + "\n" + schema)[:16]


def build_messages(
    stage: str,
    variable_input: dict[str, Any],
    feedback: list[str] | None = None,
    g2_overlap_mode: str | None = None,
) -> list[dict[str, str]]:
    """고정 지시 → 가변 입력 (+ 재호출이면 직전 검증 실패 사유) (6.2, 6.3)."""
    user = json.dumps(variable_input, ensure_ascii=False, sort_keys=True)
    if feedback:
        user += "\n\n" + FEEDBACK_HEADER + "\n" + "\n".join(f"- {e}" for e in feedback)
    return [
        {"role": "developer", "content": load_prompt(stage, g2_overlap_mode)},
        {"role": "user", "content": user},
    ]


def compute_cost(usage: Usage, cfg: Config) -> float | None:
    """cost = 비캐시 입력·P_in + 캐시 입력·P_cache + (출력 + 추론)·P_out (11.1). 단가가 없으면 None."""
    if None in (cfg.PRICE_INPUT, cfg.PRICE_CACHED_INPUT, cfg.PRICE_OUTPUT):
        return None
    uncached = usage.input - usage.cached_input
    total = (
        uncached * cfg.PRICE_INPUT
        + usage.cached_input * cfg.PRICE_CACHED_INPUT
        + (usage.output + usage.reasoning) * cfg.PRICE_OUTPUT
    )
    return total / 1_000_000


def parse_and_validate(resp: RawResponse, schema: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """거절·빈 응답·JSON 파싱 실패·스키마 위반을 오류 목록으로 돌려준다 (6.3, 6.4)."""
    if resp.refusal:
        return None, [f"거절: {resp.refusal}"]
    if not resp.text or not resp.text.strip():
        return None, ["빈 응답"]
    try:
        obj = json.loads(resp.text)
    except json.JSONDecodeError as e:
        return None, [f"JSON 파싱 실패: {e}"]
    errors = sorted(Draft202012Validator(schema).iter_errors(obj), key=lambda e: list(e.absolute_path))
    if errors:
        return None, [f"스키마 위반 /{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in errors]
    return obj, []


class CallsLogWriter:
    """calls.jsonl 단일 writer (CLAUDE.md 원칙 6). 추가 전용, 한 줄씩 flush (7.3, 10.3).

    프로세스가 줄 중간에 죽어 마지막 줄이 깨졌으면 그 줄은 무시하고 새 줄부터 이어 쓴다.
    """

    def __init__(self, run_dir: Path) -> None:
        self.path = Path(run_dir) / "calls.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._by_call: dict[str, list[dict[str, Any]]] = {}
        self.total_cost = 0.0
        self._needs_newline = False
        if self.path.exists():
            data = self.path.read_bytes()
            self._needs_newline = bool(data) and not data.endswith(b"\n")
            for line in data.decode("utf-8").splitlines():
                try:
                    self._index(json.loads(line))
                except json.JSONDecodeError:
                    continue

    def _index(self, record: dict[str, Any]) -> None:
        self._by_call.setdefault(record["call_id"], []).append(record)
        if record.get("cost_usd") is not None:
            self.total_cost += record["cost_usd"]

    def append(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                if self._needs_newline:
                    f.write("\n")
                    self._needs_newline = False
                f.write(line)
                f.flush()
            self._index(record)

    def records(self, call_id: str) -> list[dict[str, Any]]:
        return list(self._by_call.get(call_id, []))

    def next_attempt(self, call_id: str) -> int:
        return len(self._by_call.get(call_id, [])) + 1

    def success(self, call_id: str) -> dict[str, Any] | None:
        for record in reversed(self._by_call.get(call_id, [])):
            if record["status"] in SUCCESS_STATUSES:
                return record
        return None

    def succeeded_call_ids(self) -> set[str]:
        """재개 기준: calls.jsonl의 성공 기록 (10.3)."""
        return {cid for cid in self._by_call if self.success(cid) is not None}


class LLMClient:
    """판정 호출 래퍼 (6.1, 6.3, 6.4). online 모드 기준이며 Transport만 바꿔 mock으로 돈다."""

    def __init__(
        self,
        cfg: Config,
        run_dir: Path,
        log_writer: CallsLogWriter,
        transport: Transport,
        *,
        llm: str = "openai",
        run_id: str = "",
        forbidden_terms: tuple[str, ...] = (),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
        progress: Any = None,
    ) -> None:
        self._cfg = cfg
        self.progress = progress  # ksco_qa.progress.Progress (없으면 진행 표시 안 함)
        self._run_dir = Path(run_dir)
        self._log = log_writer
        self._transport = transport
        self._llm = llm
        self._run_id = run_id
        self._forbidden = tuple(t for t in forbidden_terms if t)
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._sem: asyncio.Semaphore | None = None
        self._sem_loop: asyncio.AbstractEventLoop | None = None

    # --- 설정 ---

    def model_for(self, stage: str) -> str:
        if self._llm == "mock":
            return "mock"
        model = getattr(self._cfg, f"MODEL_{stage}")
        if model is None:
            raise ValueError(f"MODEL_{stage}가 설정되지 않음")
        return model

    def effort_for(self, stage: str) -> str:
        return getattr(self._cfg, f"EFFORT_{stage}")

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._sem is None or self._sem_loop is not loop:
            self._sem = asyncio.Semaphore(self._cfg.CONCURRENCY)
            self._sem_loop = loop
        return self._sem

    def _check_forbidden(self, messages: list[dict[str, str]]) -> None:
        for m in messages:
            text = m["content"]
            folded = text.casefold()
            for term in self._forbidden:
                if term.casefold() in folded:
                    raise ForbiddenContext(f"호출 메시지에 금지된 맥락이 들어 있다: {term!r}")
            if _DRIVE_PATH_RE.search(text):
                raise ForbiddenContext("호출 메시지에 절대 경로가 들어 있다")

    # --- 호출 ---

    async def call(
        self,
        *,
        stage: str,
        unit_id: str | int,
        variable_input: dict[str, Any],
        attempt_kind: str = "first",
        reasoning_effort: str | None = None,
        validator: Validator | None = None,
    ) -> CallResult:
        """판정 호출 1회 (6.3, 6.4).

        스키마 실패는 같은 call_id로 재호출 1회 후 FAILED.
        코드 검증 실패는 피드백을 붙여(attempt_kind=feedback) 재호출 1회, 또 실패하면 VALIDATION_FAIL.
        """
        if attempt_kind not in ("first", "escalate"):
            raise ValueError("attempt_kind는 first 또는 escalate (feedback은 래퍼가 정한다)")
        effort = reasoning_effort or self.effort_for(stage)
        if self.progress is not None:
            self.progress.call_started(stage)
        results: list[CallResult] = []
        try:
            result = await self._call_with_schema_retry(
                stage, str(unit_id), variable_input, effort, attempt_kind, None, validator, results
            )
            if result.status == "VALIDATION_FAIL":
                result = await self._call_with_schema_retry(
                    stage, str(unit_id), variable_input, effort, "feedback", result.validation_errors, validator,
                    results,
                )
        finally:
            self._report_progress(stage, results)
        return result

    def _report_progress(self, stage: str, results: list["CallResult"]) -> None:
        """call() 1회(스키마 재호출·피드백 재호출 포함)를 진행 표시에 1건으로 반영한다. 토큰·비용은 실측 usage만."""
        if self.progress is None:
            return
        usages = [r.usage for r in results if r.usage is not None]
        costs = [compute_cost(u, self._cfg) for u in usages]
        last = results[-1] if results else None
        self.progress.call_finished(
            stage,
            failed=last is None or last.status not in SUCCESS_STATUSES,
            reused=bool(results) and all(r.from_cache for r in results),
            input_tokens=sum(u.input for u in usages),
            output_tokens=sum(u.output + u.reasoning for u in usages),
            cost=None if any(c is None for c in costs) else sum(costs),
        )

    async def _call_with_schema_retry(
        self,
        stage: str,
        unit_id: str,
        variable_input: dict[str, Any],
        effort: str,
        attempt_kind: str,
        feedback: list[str] | None,
        validator: Validator | None,
        results: list["CallResult"] | None = None,
    ) -> CallResult:
        results = results if results is not None else []
        model = self.model_for(stage)
        mode = self._cfg.G2_OVERLAP_MODE if stage == "G2" else None
        messages = build_messages(stage, variable_input, feedback, mode)
        self._check_forbidden(messages)
        ih = input_hash(variable_input if feedback is None else {"input": variable_input, "feedback": feedback})
        pv = prompt_version(stage, mode)
        call_id = make_call_id(
            stage=stage, unit_id=unit_id, model=model, reasoning_effort=effort,
            attempt_kind=attempt_kind, prompt_version=pv, input_hash=ih,
        )
        cached = self._from_log(call_id, attempt_kind)
        if cached is not None:
            results.append(cached)
            return cached
        common = dict(stage=stage, unit_id=unit_id, model=model, effort=effort, attempt_kind=attempt_kind,
                      messages=messages, variable_input=variable_input, call_id=call_id, pv=pv, ih=ih,
                      validator=validator)
        result = await self._attempt(**common, final=False)
        results.append(result)
        if result.status != "SCHEMA_FAIL":
            return result
        result = await self._attempt(**common, final=True)
        results.append(result)
        return result

    def _from_log(self, call_id: str, attempt_kind: str) -> CallResult | None:
        """재개: 성공 기록이나 확정된 VALIDATION_FAIL이 있으면 다시 호출하지 않는다."""
        ok = self._log.success(call_id)
        if ok is not None:
            raw = json.loads((self._run_dir / ok["raw_file"]).read_text(encoding="utf-8"))
            return CallResult(call_id, ok["status"], raw["parsed"], _usage(ok), attempt_kind, from_cache=True)
        records = self._log.records(call_id)
        if records and records[-1]["status"] == "VALIDATION_FAIL":
            last = records[-1]
            return CallResult(call_id, "VALIDATION_FAIL", None, _usage(last), attempt_kind,
                              list(last["validation_errors"]), from_cache=True)
        return None

    async def _attempt(
        self, *, stage: str, unit_id: str, model: str, effort: str, attempt_kind: str,
        messages: list[dict[str, str]], variable_input: dict[str, Any], call_id: str, pv: str, ih: str,
        validator: Validator | None, final: bool,
    ) -> CallResult:
        schema_name = STAGE_FILES[stage][1]
        schema = load_schema(schema_name)
        attempt = self._log.next_attempt(call_id)
        request = LLMRequest(
            call_id=call_id, stage=stage, unit_id=unit_id, attempt=attempt, model=model,
            reasoning_effort=effort, schema_name=schema_name, schema=schema, messages=messages,
            variable_input=variable_input, timeout_s=TIMEOUT_HIGH_S if effort == "high" else TIMEOUT_S,
        )
        started_at = datetime.now(timezone.utc)
        t0 = time.monotonic()
        resp, transport_errors, transient_retries, timeouts = await self._send(request)

        parsed: dict[str, Any] | None = None
        errors: list[str] = []
        if resp is None:
            status = "FAILED"
            errors = transport_errors
        else:
            parsed, errors = parse_and_validate(resp, schema)
            if errors:
                status = "FAILED" if final else "SCHEMA_FAIL"
            else:
                errors = validator(parsed) if validator else []
                if errors:
                    status = "VALIDATION_FAIL"
                else:
                    status = "RETRIED" if (transient_retries or timeouts) else "OK"

        raw_file = None
        if resp is not None:
            raw_file = f"raw/{call_id}__{attempt}.json"
            raw_path = self._run_dir / raw_file
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(
                json.dumps({"response": resp.raw, "parsed": parsed}, ensure_ascii=False), encoding="utf-8"
            )

        usage = resp.usage if resp is not None else None
        record = {
            "run_id": self._run_id,
            "call_id": call_id,
            "stage": stage,
            "unit_id": unit_id,
            "attempt": attempt,
            "attempt_kind": attempt_kind,
            "llm": self._llm,
            "model": model,
            "reasoning_effort": effort,
            "prompt_version": pv,
            "schema_version": schema_version(stage),
            "input_hash": ih,
            "started_at": started_at.isoformat(),
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "usage": usage.to_dict() if usage else None,
            "cost_usd": compute_cost(usage, self._cfg) if usage else None,
            "status": status,
            "validation_errors": errors,
            "transient_retries": transient_retries,
            "timeouts": timeouts,
            "tool_calls": None,
            "raw_file": raw_file,
        }
        self._log.append(record)
        self._check_budget()
        return CallResult(call_id, status, parsed if status in SUCCESS_STATUSES else None, usage, attempt_kind, errors)

    async def _send(self, request: LLMRequest) -> tuple[RawResponse | None, list[str], int, int]:
        """429·5xx·네트워크: 지수 백오프 + 무작위 지연, 최대 5회, retry_after 우선.
        타임아웃: 재시도 1회 (6.4)."""
        retries = 0
        timeouts = 0
        while True:
            try:
                async with self._semaphore():
                    resp = await asyncio.wait_for(self._transport.create(request), timeout=request.timeout_s)
                return resp, [], retries, timeouts
            except TransientError as e:
                if retries >= MAX_TRANSIENT_RETRIES:
                    return None, [f"일시 오류 재시도 {MAX_TRANSIENT_RETRIES}회 초과: {e.kind}"], retries, timeouts
                if e.retry_after is not None:
                    delay = e.retry_after
                else:
                    delay = min(MAX_BACKOFF_S, 2.0 ** retries) + self._rng.uniform(0, 1)
                retries += 1
                await self._sleep(delay)
            except TimeoutError:
                if timeouts >= 1:
                    return None, ["타임아웃 재시도 1회 후에도 초과"], retries, timeouts
                timeouts += 1

    def _check_budget(self) -> None:
        budget = self._cfg.BUDGET_USD
        if budget is not None and self._log.total_cost > budget:
            raise BudgetExceeded(f"누적 비용 ${self._log.total_cost:.4f}가 BUDGET_USD ${budget}를 넘었다")


def _usage(record: dict[str, Any]) -> Usage | None:
    u = record.get("usage")
    return Usage(**u) if u else None


class BatchSubmitter:
    """--mode batch: 단계별 Batch API 제출 → 완료 대기 → 결과 수집 (6.5). 골격."""

    def __init__(self, cfg: Config, run_dir: Path, log_writer: CallsLogWriter) -> None:
        raise NotImplementedError

    def submit(self, stage: str, requests: list[dict[str, Any]]) -> str:
        raise NotImplementedError

    def wait_and_collect(self, batch_id: str) -> list[CallResult]:
        raise NotImplementedError
