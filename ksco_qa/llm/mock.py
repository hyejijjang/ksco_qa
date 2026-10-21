"""MockClient — OpenAI 대신 응답하는 가짜 전송 계층 (개발·테스트용).

- schemas/의 JSON 스키마를 만족하는 응답을 만든다.
- 결정적이다: 같은 call_id → 같은 응답 (call_id 기반 시드).
- usage를 가짜 값으로 채워 calls.jsonl·비용 집계 경로까지 돈다.
- MockFaults로 429·타임아웃·스키마 실패·검증 실패를 일부러 만든다.

기본 응답은 단계별 코드 검증(설계 5.2, 5.4, 5.6)에 걸리지 않게 맞춘다.
가변 입력에서 다음 키를 찾아 쓴다: job_leaf(G0), pairs(G1B),
reference_mode·g2_overlap_mode·g0_checks(G2, g0_checks는 G0·G2 지표 이름 모두 허용).
모든 텍스트에 "MOCK"이 들어가 실제 판정과 구분된다.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Any

from ksco_qa.dictionaries import g2_key_for, g2_new_keys
from ksco_qa.llm.types import LLMRequest, RawResponse, TransientError, Usage

FAULT_KINDS = ("rate_limit", "timeout", "schema_fail", "validation_fail")
SCHEMA_FAIL_VARIANTS = ("invalid_json", "schema_violation", "empty", "refusal")


@dataclass
class MockFaults:
    """고장 주입. 비율(0~1)은 (단계, unit_id)별로 결정적으로 적용된다.

    repeats: 고장이 걸린 단위에서 연속으로 몇 번 고장을 낼지.
      rate_limit: 6 이상이면 재시도 5회를 넘어 FAILED.
      schema_fail: 2 이상이면 재호출까지 실패해 FAILED.
      validation_fail: 2 이상이면 피드백 재호출까지 실패해 VALIDATION_FAIL.
      timeout: 2 이상이면 재시도 1회까지 실패해 FAILED.
    """

    rate_limit: float = 0.0
    timeout: float = 0.0
    schema_fail: float = 0.0
    validation_fail: float = 0.0
    repeats: int = 1
    _fired: dict[tuple[str, str, str], int] = field(default_factory=dict, repr=False)

    @classmethod
    def parse(cls, items: list[str] | None) -> "MockFaults":
        """CLI --mock-fault 값 (예: schema_fail=0.2, repeats=2)."""
        faults = cls()
        for item in items or []:
            key, sep, value = item.partition("=")
            key = key.strip()
            if not sep or key not in (*FAULT_KINDS, "repeats"):
                raise ValueError(f"--mock-fault 형식은 <{'|'.join(FAULT_KINDS)}|repeats>=<값>: {item!r}")
            if key == "repeats":
                faults.repeats = int(value)
                if faults.repeats < 1:
                    raise ValueError("repeats는 1 이상")
            else:
                rate = float(value)
                if not 0.0 <= rate <= 1.0:
                    raise ValueError(f"{key} 비율은 0~1: {rate}")
                setattr(faults, key, rate)
        return faults

    def fire(self, kind: str, stage: str, unit_id: str) -> bool:
        rate = getattr(self, kind)
        if rate <= 0.0 or _unit_float(kind, stage, unit_id) >= rate:
            return False
        key = (kind, stage, unit_id)
        count = self._fired.get(key, 0)
        if count >= self.repeats:
            return False
        self._fired[key] = count + 1
        return True


def _unit_float(*parts: str) -> float:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _find_key(obj: Any, key: str) -> Any:
    """가변 입력 안에서 key를 처음 만나는 곳의 값 (구조가 단계마다 달라도 찾게)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _find_key(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_key(v, key)
            if found is not None:
                return found
    return None


class _Generator:
    """JSON 스키마를 만족하는 값을 rng로 만든다 (strict 모드 스키마 부분집합)."""

    def __init__(self, schema: dict[str, Any], rng: random.Random) -> None:
        self.schema = schema
        self.rng = rng

    def resolve(self, node: dict[str, Any]) -> dict[str, Any]:
        while "$ref" in node:
            target: Any = self.schema
            for part in node["$ref"].removeprefix("#/").split("/"):
                target = target[part]
            node = target
        return node

    def gen(self, node: dict[str, Any], label: str = "") -> Any:
        node = self.resolve(node)
        if "anyOf" in node:
            return self.gen(self.rng.choice(node["anyOf"]), label)
        if "enum" in node:
            return self.rng.choice([v for v in node["enum"] if v is not None])
        types = node["type"] if isinstance(node["type"], list) else [node["type"]]
        if types == ["null"] or ("null" in types and self.rng.random() < 0.3):
            return None
        base = next(t for t in types if t != "null")
        if base == "object":
            return {k: self.gen(v, k) for k, v in node["properties"].items()}
        if base == "array":
            n = self.rng.randint(0, min(2, node.get("maxItems", 2)))
            return [self.gen(node["items"], label) for _ in range(n)]
        if base == "string":
            return self.text(label, node.get("maxLength"))
        if base == "integer":
            return self.rng.randint(1, 1000)
        if base == "number":
            return round(self.rng.random(), 4)
        if base == "boolean":
            return self.rng.random() < 0.5
        raise ValueError(f"mock이 지원하지 않는 타입: {base}")

    def text(self, label: str, max_length: int | None) -> str:
        s = f"MOCK {label} {self.rng.randrange(10**8):08d}"
        return s[:max_length] if max_length else s


class MockClient:
    """Transport 구현. LLMClient(래퍼) 아래에 꽂아 쓴다."""

    def __init__(self, faults: MockFaults | None = None) -> None:
        self.faults = faults or MockFaults()

    async def create(self, request: LLMRequest) -> RawResponse:
        stage, unit = request.stage, request.unit_id
        if self.faults.fire("rate_limit", stage, unit):
            raise TransientError("429", retry_after=1.0)
        if self.faults.fire("timeout", stage, unit):
            raise TimeoutError("mock timeout")

        rng = random.Random(request.call_id)  # 문자열 시드는 실행·PYTHONHASHSEED와 무관하게 결정적
        output = self._respond(request, rng)
        if self.faults.fire("validation_fail", stage, unit):
            self._break_validation(stage, output)
        text: str | None = json.dumps(output, ensure_ascii=False)
        refusal = None
        if self.faults.fire("schema_fail", stage, unit):
            variant = SCHEMA_FAIL_VARIANTS[int(_unit_float("variant", request.call_id, str(request.attempt)) * 4)]
            text, refusal = self._break_schema(variant, output)

        fixed = len(request.messages[0]["content"])
        variable = sum(len(m["content"]) for m in request.messages[1:])
        usage = Usage(
            input=(fixed + variable) // 2,
            cached_input=fixed // 2,
            output=len(text or "") // 2,
            reasoning=rng.randint(100, 2000),
        )
        raw = {"mock": True, "call_id": request.call_id, "attempt": request.attempt, "output_text": text,
               "refusal": refusal, "usage": usage.to_dict()}
        return RawResponse(text=text, refusal=refusal, usage=usage, raw=raw)

    # --- 응답 생성 ---

    def _respond(self, request: LLMRequest, rng: random.Random) -> dict[str, Any]:
        gen = _Generator(request.schema, rng)
        out = gen.gen(request.schema)
        fix = {"G0": self._fix_g0, "G1B": self._fix_g1b, "G2": self._fix_g2}[request.stage]
        fix(out, request.variable_input, gen)
        return out

    @staticmethod
    def _fill_issues(issues: dict[str, Any], checks: dict[str, str]) -> None:
        for key in issues:
            issues[key] = f"MOCK {key} 문제" if checks.get(key) in ("R", "F") else None

    def _fix_g0(self, out: dict[str, Any], inp: dict[str, Any], gen: _Generator) -> None:
        out["job_evaluated"] = _find_key(inp, "job_leaf") or out["job_evaluated"]
        if out["action"] == "KEEP":  # F가 있는데 KEEP 금지 (5.2)
            out["checks"] = {k: ("R" if v == "F" else v) for k, v in out["checks"].items()}
        self._fill_issues(out["issues"], out["checks"])
        if out["action"] == "REGENERATE":
            out["regenerated_task_new"] = gen.text("regenerated_task_new", 1000)
        else:
            out["regenerated_task_new"] = None
        if out["action"] in ("KEEP", "REGENERATE"):
            if out["task_card"] is None:
                out["task_card"] = gen.gen(gen.schema["$defs"]["task_card"], "task_card")
        else:
            out["task_card"] = None

    def _fix_g1b(self, out: dict[str, Any], inp: dict[str, Any], gen: _Generator) -> None:
        pair_schema = gen.schema["$defs"]["pair"]
        pairs = []
        for row_1, row_2 in _find_key(inp, "pairs") or []:
            item = gen.gen(pair_schema, "pair")
            item["row_1"], item["row_2"] = row_1, row_2
            item["conclusion"] = None if item["verdict"] == "DISTINCT" else gen.text("conclusion", 200)
            pairs.append(item)
        out["pairs"] = pairs
        out["added_pairs"] = []

    def _fix_g2(self, out: dict[str, Any], inp: dict[str, Any], gen: _Generator) -> None:
        overlap = out["overlap_review"]["checks"]
        new = out["new_checks"]
        if out["verify_status"] == "PASS":  # F가 있는데 PASS 금지 (5.6)
            for checks in (overlap, new):
                for k, v in checks.items():
                    if v == "F":
                        checks[k] = "R"
        mode = _find_key(inp, "g2_overlap_mode")
        if mode is not None:
            out["overlap_review"]["mode"] = mode
        # disagree: 입력에 G0 값이 있을 때(AGREE_CHECK의 KEEP 행)만, G0 값과 다른 지표마다 1개
        g0_checks = _find_key(inp, "g0_checks")
        disagree = []
        if isinstance(g0_checks, dict):
            g0_by_g2 = {g2_key_for(k): v for k, v in g0_checks.items()}
            for key, new_value in overlap.items():
                g0_value = g0_by_g2.get(key)
                if g0_value is not None and g0_value != new_value:
                    disagree.append({"indicator": key, "g0_value": g0_value, "new_value": new_value,
                                     "reason": gen.text("disagree", 200)})
        out["overlap_review"]["disagree"] = disagree
        reference_mode = _find_key(inp, "reference_mode")
        if reference_mode == "GENERATE_REFERENCE":
            out["reference_action"] = "GENERATE"
        if reference_mode == "UNRESOLVED_REFERENCE":  # 00 6.2 기본값
            out["reference_readiness"] = "HOLD"
        if reference_mode != "PROVIDED_REFERENCE":  # reference_conflict는 PROVIDED일 때만 (결정 29)
            out["reference_conflict"] = None
        if not out["reference_conflict"]:
            out["reference_conflict_note"] = None
        elif out["reference_conflict_note"] is None:
            out["reference_conflict_note"] = gen.text("reference_conflict_note", 300)
        self._fill_issues(out["issues"], {**overlap, **new})
        out["proposed_fix"] = gen.text("proposed_fix", 500) if out["verify_status"] in ("REVIEW", "FAIL") else None

    # --- 고장 ---

    @staticmethod
    def _break_validation(stage: str, out: dict[str, Any]) -> None:
        """스키마는 지키지만 코드 검증에 걸리는 응답."""
        if stage == "G0":
            out["job_evaluated"] = "MOCK 다른 직업"
        elif stage == "G1B":
            out["pairs"] = out["pairs"][1:]
        elif stage == "G2":
            out["verify_status"] = "PASS"
            first = next(iter(g2_new_keys()))
            out["new_checks"][first] = "F"

    @staticmethod
    def _break_schema(variant: str, out: dict[str, Any]) -> tuple[str | None, str | None]:
        if variant == "invalid_json":
            return json.dumps(out, ensure_ascii=False)[:-1], None
        if variant == "schema_violation":
            broken = dict(out)
            broken["MOCK_UNKNOWN_FIELD"] = "DESIGNABLE"
            return json.dumps(broken, ensure_ascii=False), None
        if variant == "empty":
            return "", None
        return None, "MOCK 거절"
