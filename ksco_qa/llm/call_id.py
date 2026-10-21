"""call_id·입력 해시 (설계 6.4, 7.3, 8.2 / CLAUDE.md 설계 보완).

call_id = hash(stage, unit_id, model, reasoning_effort, attempt_kind, prompt_version, input_hash)
같은 call_id의 성공 기록이 calls.jsonl에 있으면 다시 호출하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ksco_qa.dictionaries import enum_values


def canonical_json(obj: Any) -> str:
    """키 정렬·공백 없는 UTF-8 JSON. 해시 입력의 표준 형태."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def input_hash(obj: Any) -> str:
    """가변 입력(row_card 등)의 해시."""
    return sha256_hex(canonical_json(obj))


def make_call_id(
    *,
    stage: str,
    unit_id: str | int,
    model: str,
    reasoning_effort: str,
    attempt_kind: str,
    prompt_version: str,
    input_hash: str,
) -> str:
    if stage not in enum_values("call_stage"):
        raise ValueError(f"stage {stage!r}는 허용값이 아니다: {enum_values('call_stage')}")
    if attempt_kind not in enum_values("attempt_kind"):
        raise ValueError(f"attempt_kind {attempt_kind!r}는 허용값이 아니다: {enum_values('attempt_kind')}")
    for name, value in (("model", model), ("reasoning_effort", reasoning_effort),
                        ("prompt_version", prompt_version), ("input_hash", input_hash)):
        if not value:
            raise ValueError(f"{name}가 비어 있다")
    parts = [stage, str(unit_id), model, reasoning_effort, attempt_kind, prompt_version, input_hash]
    return sha256_hex(canonical_json(parts))
