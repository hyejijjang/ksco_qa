"""enums.yaml ↔ schemas/*.json enum 일치, structured outputs strict 형식 검사 (설계 7.2, 7.5)."""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from jsonschema import Draft202012Validator

from ksco_qa.dictionaries import (
    SCHEMA_NAMES,
    enum_values,
    g0_check_keys,
    g2_new_keys,
    g2_overlap_keys,
    load_enums,
    load_schema,
)

# 스키마 안 enum 위치(JSON pointer) → 기대 허용값.
# 모델 출력 verify_status는 PASS/REVIEW/FAIL만 (SKIPPED는 코드가 규칙으로 기록, 설계 5.6·7.2).
EXPECTED_ENUMS: dict[str, dict[str, Any]] = {
    "g0": {
        "/properties/action": lambda: enum_values("revision_action"),
        "/$defs/check_status": lambda: enum_values("check_status_model"),
    },
    "g1b": {
        "/$defs/pair/properties/verdict": lambda: enum_values("pair_verdict"),
    },
    "g2": {
        "/properties/verify_status": lambda: [v for v in enum_values("verify_status") if v != "SKIPPED"],
        "/properties/overlap_review/properties/mode": lambda: enum_values("g2_overlap_mode"),
        "/properties/b_coverage_status": lambda: enum_values("b_coverage_status"),
        "/properties/reference_action": lambda: enum_values("reference_action"),
        "/properties/reference_readiness": lambda: enum_values("reference_readiness"),
        "/$defs/check_status": lambda: enum_values("check_status_model"),
        "/$defs/disagree_item/properties/indicator": g2_overlap_keys,
    },
}


def walk(node: Any, pointer: str = "") -> Iterator[tuple[str, Any]]:
    yield pointer, node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{pointer}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{pointer}/{i}")


def resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    if ref is None:
        return node
    target: Any = schema
    for part in ref.removeprefix("#/").split("/"):
        target = target[part]
    return target


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_is_valid_json_schema(name: str) -> None:
    Draft202012Validator.check_schema(load_schema(name))


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_enums_match_enums_yaml(name: str) -> None:
    schema = load_schema(name)
    found = {p: n["enum"] for p, n in walk(schema) if isinstance(n, dict) and "enum" in n}
    expected = EXPECTED_ENUMS[name]
    assert set(found) == set(expected), "스키마의 enum 위치가 테스트 매핑과 다르다"
    for pointer, values in found.items():
        assert [v for v in values if v is not None] == expected[pointer](), pointer


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_strict_mode_shape(name: str) -> None:
    """strict 모드: 모든 object는 additionalProperties=false, 모든 속성 required. 모든 텍스트에 길이 상한."""
    schema = load_schema(name)
    assert schema["type"] == "object"
    for pointer, node in walk(schema):
        if not isinstance(node, dict) or "type" not in node:
            continue
        types = node["type"] if isinstance(node["type"], list) else [node["type"]]
        if "object" in types:
            assert node.get("additionalProperties") is False, pointer
            assert sorted(node["required"]) == sorted(node["properties"]), pointer
        if "string" in types and "enum" not in node:
            assert isinstance(node.get("maxLength"), int), f"{pointer}: maxLength 없음"


def test_check_keys_match_criteria() -> None:
    g0 = load_schema("g0")["$defs"]
    assert list(g0["checks"]["properties"]) == g0_check_keys()
    assert list(g0["issues"]["properties"]) == g0_check_keys()
    g2 = load_schema("g2")["$defs"]
    assert list(g2["overlap_checks"]["properties"]) == g2_overlap_keys()
    assert list(g2["new_checks"]["properties"]) == g2_new_keys()
    assert list(g2["issues"]["properties"]) == g2_overlap_keys() + g2_new_keys()


def test_g2_disagree_item_structure() -> None:
    """g2.md: disagree에 지표, G0 값, 새 값, 이유를 적는다."""
    item = load_schema("g2")["$defs"]["disagree_item"]
    assert item["required"] == ["indicator", "g0_value", "new_value", "reason"]
    assert item["properties"]["g0_value"] == {"$ref": "#/$defs/check_status"}
    assert item["properties"]["new_value"] == {"$ref": "#/$defs/check_status"}


def test_g2_key_for_maps_g0_names() -> None:
    from ksco_qa.dictionaries import g2_key_for

    assert g2_key_for("reasoning_validity") == "reasoning_requirement"
    assert g2_key_for("no_answer_leakage") == "answer_leakage"
    assert g2_key_for("job_fit") == "job_fit"
    assert [g2_key_for(k) for k in g0_check_keys()] == g2_overlap_keys()


def test_low_overlap_not_active() -> None:
    """CLAUDE.md 설계 보완: LOW_OVERLAP은 생성 규칙이 정해질 때까지 사용하지 않는다."""
    assert "LOW_OVERLAP" not in enum_values("overlap_status")
    assert enum_values("overlap_status") == ["NONE", "HIGH_OVERLAP", "UNDETERMINED"]


def test_design_7_5_enums_present() -> None:
    enums = load_enums()
    assert enums["match_status"] == ["MATCHED", "AMBIGUOUS", "CONFLICT", "NOT_FOUND", "INACCESSIBLE", "INVENTORY_INCOMPLETE"]
    assert enums["revision_action"] == ["KEEP", "REGENERATE", "REVIEW_B", "RESELECT_B"]
    assert enums["verify_status"] == ["PASS", "REVIEW", "FAIL", "SKIPPED"]
    assert enums["final_status"] == ["PASS", "REVIEW", "FAIL"]
    assert len(enums["next_action"]) == 7
    assert enums["check_status_map"] == {"P": "PASS", "R": "REVIEW", "F": "FAIL", "NA": "N_A"}
    assert list(enums["check_status_map"].values()) == enums["check_status_final"]


def test_g0_sample_output_validates() -> None:
    sample = {
        "job_evaluated": "통계 및 설문 조사 사무원",
        "action": "REGENERATE",
        "checks": {k: "P" for k in g0_check_keys()} | {"grounding": "R"},
        "reason": "r",
        "evidence_loc": "Sheet1!A1:F3",
        "expected_reference_spec": "s",
        "regenerated_task_new": "새 Task",
        "issues": {k: None for k in g0_check_keys()} | {"grounding": "근거 없는 기간 추가"},
        "task_card": {"input": "i", "operations": ["o"], "criteria": ["c"], "output": "x"},
    }
    validator = Draft202012Validator(load_schema("g0"))
    assert list(validator.iter_errors(sample)) == []
    bad = sample | {"action": "DESIGNABLE"}
    assert list(validator.iter_errors(bad))
