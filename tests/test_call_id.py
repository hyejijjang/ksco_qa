"""call_id = hash(stage, unit_id, model, reasoning_effort, attempt_kind, prompt_version, input_hash)."""

from __future__ import annotations

import pytest

from ksco_qa.llm.call_id import input_hash, make_call_id

BASE = dict(
    stage="G0",
    unit_id=12,
    model="model-a",
    reasoning_effort="medium",
    attempt_kind="first",
    prompt_version="pv1",
    input_hash="ih1",
)


def test_deterministic() -> None:
    assert make_call_id(**BASE) == make_call_id(**BASE)


@pytest.mark.parametrize(
    "field, value",
    [
        ("model", "model-b"),
        ("reasoning_effort", "high"),
        ("attempt_kind", "escalate"),
        ("attempt_kind", "feedback"),
        ("stage", "G2"),
        ("unit_id", 13),
        ("prompt_version", "pv2"),
        ("input_hash", "ih2"),
    ],
)
def test_changes_with_each_component(field: str, value: object) -> None:
    assert make_call_id(**(BASE | {field: value})) != make_call_id(**BASE)


def test_all_attempt_kinds_distinct() -> None:
    ids = {make_call_id(**(BASE | {"attempt_kind": k})) for k in ("first", "escalate", "feedback")}
    assert len(ids) == 3


@pytest.mark.parametrize("field, value", [("attempt_kind", "retry"), ("stage", "G1a"), ("model", "")])
def test_rejects_invalid(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        make_call_id(**(BASE | {field: value}))


def test_input_hash_ignores_key_order() -> None:
    assert input_hash({"a": 1, "b": "가"}) == input_hash({"b": "가", "a": 1})
    assert input_hash({"a": 1}) != input_hash({"a": 2})
