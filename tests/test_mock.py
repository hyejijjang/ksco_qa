"""MockClient — 스키마 충족, 결정성, 기본 응답의 검증 정합, 고장 주입."""

from __future__ import annotations

import asyncio
import json

import pytest
from jsonschema import Draft202012Validator

from ksco_qa.dictionaries import g0_check_keys, g2_key_for, load_schema
from ksco_qa.llm.client import STAGE_FILES, build_messages
from ksco_qa.llm.mock import MockClient, MockFaults
from ksco_qa.llm.types import LLMRequest, TransientError

ROW_CARD = {"source_row": 2, "id": "T-001", "job_leaf": "회계 사무원", "reference_mode": "GENERATE_REFERENCE",
            "original_task": "원본 Task"}
G1B_INPUT = {"rows": [], "pairs": [[2, 3], [2, 5], [3, 5]]}
INPUTS = {"G0": ROW_CARD, "G1B": G1B_INPUT, "G2": {"row_card": ROW_CARD, "effective_task": "Task"}}


def request(stage: str, call_id: str, attempt: int = 1, unit_id: str = "2") -> LLMRequest:
    name = STAGE_FILES[stage][1]
    return LLMRequest(
        call_id=call_id, stage=stage, unit_id=unit_id, attempt=attempt, model="mock", reasoning_effort="medium",
        schema_name=name, schema=load_schema(name), messages=build_messages(stage, INPUTS[stage], g2_overlap_mode="AGREE_CHECK" if stage == "G2" else None),
        variable_input=INPUTS[stage], timeout_s=300,
    )


def cid(i: int) -> str:
    return f"{i:064x}"


def create(client: MockClient, req: LLMRequest):
    return asyncio.run(client.create(req))


@pytest.mark.parametrize("stage", ["G0", "G1B", "G2"])
def test_responses_satisfy_schema(stage: str) -> None:
    validator = Draft202012Validator(load_schema(STAGE_FILES[stage][1]))
    client = MockClient()
    for i in range(60):
        resp = create(client, request(stage, cid(i * 7919 + 1)))
        assert list(validator.iter_errors(json.loads(resp.text))) == []
        assert resp.usage.input > 0 and resp.usage.output > 0


@pytest.mark.parametrize("stage", ["G0", "G1B", "G2"])
def test_deterministic_by_call_id(stage: str) -> None:
    a = create(MockClient(), request(stage, cid(42)))
    b = create(MockClient(), request(stage, cid(42)))
    assert a.text == b.text and a.usage == b.usage
    others = {create(MockClient(), request(stage, cid(i))).text for i in range(100, 110)}
    assert len(others) > 1


def test_g0_default_passes_code_rules() -> None:
    for i in range(60):
        out = json.loads(create(MockClient(), request("G0", cid(i + 500))).text)
        assert out["job_evaluated"] == ROW_CARD["job_leaf"]
        assert not (out["action"] == "KEEP" and "F" in out["checks"].values())
        if out["action"] == "REGENERATE":
            assert out["regenerated_task_new"] and out["regenerated_task_new"] != ROW_CARD["original_task"]
        assert (out["task_card"] is not None) == (out["action"] in ("KEEP", "REGENERATE"))
        for k, v in out["checks"].items():
            assert (out["issues"][k] is not None) == (v in ("R", "F"))


def test_g1b_covers_every_input_pair_once() -> None:
    out = json.loads(create(MockClient(), request("G1B", cid(7))).text)
    assert [[p["row_1"], p["row_2"]] for p in out["pairs"]] == G1B_INPUT["pairs"]


def test_g2_default_passes_code_rules() -> None:
    for i in range(60):
        out = json.loads(create(MockClient(), request("G2", cid(i + 900))).text)
        checks = {**out["overlap_review"]["checks"], **out["new_checks"]}
        assert not (out["verify_status"] == "PASS" and "F" in checks.values())
        assert out["reference_action"] == "GENERATE"


def g2_request(call_id: str, variable_input: dict) -> LLMRequest:
    return LLMRequest(
        call_id=call_id, stage="G2", unit_id="2", attempt=1, model="mock", reasoning_effort="medium",
        schema_name="g2", schema=load_schema("g2"), messages=build_messages("G2", variable_input, g2_overlap_mode="AGREE_CHECK"),
        variable_input=variable_input, timeout_s=300,
    )


def test_g2_disagree_empty_without_g0_values() -> None:
    for i in range(30):
        out = json.loads(create(MockClient(), request("G2", cid(i + 1300))).text)
        assert out["overlap_review"]["disagree"] == []


def test_g2_disagree_matches_g0_and_checks() -> None:
    """KEEP 행(AGREE_CHECK): G0 값과 다른 지표마다 정확히 1개, g0_value·new_value가 입력·checks와 일치."""
    g0_checks = {k: "P" for k in g0_check_keys()} | {"reasoning_validity": "R", "no_answer_leakage": "F"}
    inp = {"row_card": ROW_CARD, "effective_task": "Task", "g2_overlap_mode": "AGREE_CHECK", "g0_checks": g0_checks}
    validator = Draft202012Validator(load_schema("g2"))
    g0_in_g2 = {g2_key_for(k): v for k, v in g0_checks.items()}
    seen_disagree = False
    for i in range(60):
        out = json.loads(create(MockClient(), g2_request(cid(i + 1700), inp)).text)
        assert list(validator.iter_errors(out)) == []
        assert out["overlap_review"]["mode"] == "AGREE_CHECK"
        checks = out["overlap_review"]["checks"]
        disagree = out["overlap_review"]["disagree"]
        assert len({d["indicator"] for d in disagree}) == len(disagree)
        for d in disagree:
            assert d["g0_value"] == g0_in_g2[d["indicator"]]
            assert d["new_value"] == checks[d["indicator"]]
            assert d["g0_value"] != d["new_value"]
        assert {d["indicator"] for d in disagree} == {k for k, v in checks.items() if v != g0_in_g2[k]}
        seen_disagree |= bool(disagree)
    assert seen_disagree


@pytest.mark.parametrize("mode", ["GENERATE_REFERENCE", "UNRESOLVED_REFERENCE", "PROVIDED_REFERENCE"])
def test_g2_reference_rules(mode: str) -> None:
    inp = {"row_card": ROW_CARD | {"reference_mode": mode}, "effective_task": "Task"}
    validator = Draft202012Validator(load_schema("g2"))
    for i in range(40):
        out = json.loads(create(MockClient(), g2_request(cid(i + 2100), inp)).text)
        assert list(validator.iter_errors(out)) == []
        if mode == "UNRESOLVED_REFERENCE":
            assert out["reference_readiness"] == "HOLD"
        if mode != "PROVIDED_REFERENCE":
            assert out["reference_conflict"] is None
        assert (out["reference_conflict_note"] is not None) == bool(out["reference_conflict"])


def test_rate_limit_fault_repeats_then_clears() -> None:
    client = MockClient(MockFaults(rate_limit=1.0, repeats=2))
    for _ in range(2):
        with pytest.raises(TransientError):
            create(client, request("G0", cid(1)))
    create(client, request("G0", cid(1)))


def test_timeout_fault() -> None:
    with pytest.raises(TimeoutError):
        create(MockClient(MockFaults(timeout=1.0)), request("G0", cid(1)))


def test_schema_fail_fault_breaks_schema() -> None:
    client = MockClient(MockFaults(schema_fail=1.0, repeats=100))
    validator = Draft202012Validator(load_schema("g0"))
    for i in range(20):
        resp = create(client, request("G0", cid(i), unit_id=str(i)))
        if resp.refusal or not resp.text:
            continue
        try:
            obj = json.loads(resp.text)
        except json.JSONDecodeError:
            continue
        assert list(validator.iter_errors(obj))


@pytest.mark.parametrize("stage", ["G0", "G1B", "G2"])
def test_validation_fail_fault_keeps_schema(stage: str) -> None:
    resp = create(MockClient(MockFaults(validation_fail=1.0)), request(stage, cid(3)))
    out = json.loads(resp.text)
    assert list(Draft202012Validator(load_schema(STAGE_FILES[stage][1])).iter_errors(out)) == []
    if stage == "G0":
        assert out["job_evaluated"] != ROW_CARD["job_leaf"]
    elif stage == "G1B":
        assert len(out["pairs"]) == len(G1B_INPUT["pairs"]) - 1
    else:
        assert out["verify_status"] == "PASS" and "F" in out["new_checks"].values()


def test_fault_rate_is_deterministic_per_unit() -> None:
    faults = MockFaults(rate_limit=0.5)
    hits = [faults.fire("rate_limit", "G0", str(u)) for u in range(200)]
    again = MockFaults(rate_limit=0.5)
    assert hits == [again.fire("rate_limit", "G0", str(u)) for u in range(200)]
    assert 60 < sum(hits) < 140


@pytest.mark.parametrize(
    "items, ok",
    [
        (["schema_fail=0.2", "repeats=2"], True),
        (["rate_limit=1"], True),
        (["schema_fail"], False),
        (["unknown=0.1"], False),
        (["timeout=1.5"], False),
        (["repeats=0"], False),
    ],
)
def test_parse_faults(items: list[str], ok: bool) -> None:
    if ok:
        MockFaults.parse(items)
    else:
        with pytest.raises(ValueError):
            MockFaults.parse(items)
