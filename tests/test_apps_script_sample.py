"""tests/fixtures/apps_script_sample.jsonl (Apps Script 연동 확인용, M1 게이트)이 06 형식을 지키는지.

샘플을 다시 만들려면: uv run python tests/fixtures/make_apps_script_sample.py
"""

from __future__ import annotations

from pathlib import Path

from ksco_qa.g3 import validate as v

SAMPLE = Path(__file__).parent / "fixtures" / "apps_script_sample.jsonl"
TOP_KEYS = ["schema_version", "dataset", "source_file", "source_sheet", "source_row", "id", "source", "source_assets",
            "revision", "duplicate", "verify", "final"]


def test_sample_parses_one_object_per_line() -> None:
    records, errors = v.read_final_jsonl(SAMPLE)
    assert not errors and len(records) == len(SAMPLE.read_text(encoding="utf-8").splitlines())
    for r in records:
        assert list(r)[:12] == TOP_KEYS
        assert r["final"]["execution_notes"].startswith("API 파이프라인(MOCK);")


def test_sample_passes_record_level_06_checks() -> None:
    records, _ = v.read_final_jsonl(SAMPLE)
    for check in (v.check_match_method, v.check_regenerate_task, v.check_duplicate_consistency,
                  v.check_search_completed, v.check_reference_not_auto_review, v.check_pass_conditions,
                  v.check_enums, v.check_all_null_fields):
        assert check(records) == [], check.__name__


def test_sample_covers_every_final_path() -> None:
    records, _ = v.read_final_jsonl(SAMPLE)
    actions = {r["final"]["next_action"] for r in records}
    assert actions == {"HANDOFF_TO_AI_TEAM", "EXCLUDE_DUPLICATE", "RESELECT_DELIVERABLE", "REVISE_TASK",
                       "CHECK_ASSETS", "CHECK_DUPLICATE", "REVIEW_MANUAL"}
    codes = {c for r in records for c in r["final"]["reason_codes"]}
    assert {"G0_CALL_FAILED", "G2_CALL_FAILED", "G2_VALIDATION_FAILED", "ORIGINAL_TASK_EMPTY"} <= codes
