"""run 준비·재개·mock 격리 (설계 4.2, 10.3 / CLAUDE.md 설계 보완)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ksco_qa.config import Config
from ksco_qa.g3.export import execution_notes, execution_notes_object
from ksco_qa.p0 import P0Stop, find_datalist
from ksco_qa.run import RunError, prepare_run, work_root

T0 = datetime(2026, 10, 21, 9, 0, 0)
T1 = datetime(2026, 10, 21, 10, 0, 0)


def test_find_datalist(sample_task: Path) -> None:
    path, name = find_datalist(sample_task)
    assert name == "KSCO-99" and path.name == "KSCO-99_DataList.xlsx"
    (sample_task / "~$KSCO-99_DataList.xlsx").write_bytes(b"lock")
    assert find_datalist(sample_task)[1] == "KSCO-99"


def test_find_datalist_zero_or_many(tmp_path: Path, sample_task: Path) -> None:
    with pytest.raises(P0Stop):
        find_datalist(tmp_path)
    (sample_task / "KSCO-98_DataList.xlsx").write_bytes(b"x")
    with pytest.raises(P0Stop):
        find_datalist(sample_task)


def test_mock_run_is_isolated(sample_task: Path) -> None:
    ctx = prepare_run(sample_task, Config(), "mock", now=T0)
    assert ctx.run_id.startswith("mock-20261021-090000-")
    assert ctx.run_dir == work_root(sample_task) / ctx.run_id
    assert ctx.results_dir == ctx.run_dir
    assert ctx.result_path("03_final.jsonl") == (ctx.run_dir / "03_final.jsonl").resolve()
    with pytest.raises(RunError):
        ctx.result_path("../../03_final.jsonl")
    assert (ctx.run_dir / "config.resolved.yaml").is_file()
    assert sorted(p.name for p in (sample_task / "03_results").iterdir()) == ["_work"]


def test_real_run_writes_final_outputs_to_03_results(sample_task: Path) -> None:
    ctx = prepare_run(sample_task, Config(), "openai", now=T0)
    assert not ctx.run_id.startswith("mock-")
    assert ctx.results_dir == sample_task / "03_results"


def test_same_config_and_input_resumes(sample_task: Path) -> None:
    a = prepare_run(sample_task, Config(), "mock", now=T0)
    b = prepare_run(sample_task, Config(), "mock", now=T1)
    assert a.run_id == b.run_id


def test_config_or_input_change_makes_new_run(sample_task: Path) -> None:
    a = prepare_run(sample_task, Config(), "mock", now=T0)
    b = prepare_run(sample_task, Config(CONCURRENCY=3), "mock", now=T1)
    assert a.run_id != b.run_id
    (sample_task / "01_output_files" / "new.csv").write_text("x", encoding="utf-8")
    c = prepare_run(sample_task, Config(), "mock", now=T1)
    assert c.run_id not in (a.run_id, b.run_id)


def test_code_change_makes_new_run(sample_task: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ksco_qa.run as run

    versions = iter(("code-v1", "code-v2"))
    monkeypatch.setattr(run, "code_fingerprint", lambda: next(versions))
    first = prepare_run(sample_task, Config(), "mock", now=T0)
    second = prepare_run(sample_task, Config(), "mock", now=T1)
    assert first.run_id != second.run_id


def test_explicit_resume_rejects_changed_code(sample_task: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ksco_qa.run as run

    monkeypatch.setattr(run, "code_fingerprint", lambda: "code-v1")
    first = prepare_run(sample_task, Config(), "mock", now=T0)
    monkeypatch.setattr(run, "code_fingerprint", lambda: "code-v2")
    with pytest.raises(RunError, match="code_version"):
        prepare_run(sample_task, Config(), "mock", resume=first.run_id)


def test_mock_and_real_never_share_a_run(sample_task: Path) -> None:
    m = prepare_run(sample_task, Config(), "mock", now=T0)
    r = prepare_run(sample_task, Config(), "openai", now=T0)
    assert m.run_id != r.run_id
    with pytest.raises(RunError, match="llm"):
        prepare_run(sample_task, Config(), "openai", resume=m.run_id)
    with pytest.raises(RunError, match="llm"):
        prepare_run(sample_task, Config(), "mock", resume=r.run_id)


def test_explicit_resume(sample_task: Path) -> None:
    a = prepare_run(sample_task, Config(), "mock", now=T0)
    assert prepare_run(sample_task, Config(), "mock", resume=a.run_id).run_id == a.run_id
    with pytest.raises(RunError, match="config_hash"):
        prepare_run(sample_task, Config(CONCURRENCY=2), "mock", resume=a.run_id)
    with pytest.raises(RunError):
        prepare_run(sample_task, Config(), "mock", resume="no-such-run")


def test_sample_is_separate_run(sample_task: Path) -> None:
    full = prepare_run(sample_task, Config(), "mock", now=T0)
    s = prepare_run(sample_task, Config(), "mock", sample_n=3, now=T0)
    assert s.run_id.startswith("mock-sample3-") and s.run_id != full.run_id


def test_execution_notes_string_and_object() -> None:
    cfg = Config(MODEL_G0="m0", MODEL_G1B="m1", MODEL_G2="m2")
    pv = {"G0": "a1", "G1B": "b2", "G2": "c3"}
    real = execution_notes(run_id="r1", llm="openai", cfg=cfg, prompt_versions=pv)
    assert real == (
        "API 파이프라인; run_id=r1; G0=m0/medium; G1B=m1/high; G2=m2/medium; prompt=G0:a1,G1B:b2,G2:c3; "
        "G2_OVERLAP_MODE=AGREE_CHECK; review_independence=SEPARATE_CALL"
    )
    mock = execution_notes(run_id="mock-x", llm="mock", cfg=cfg, prompt_versions=pv)
    assert mock.startswith("API 파이프라인(MOCK); run_id=mock-x; G0=mock/medium")
    obj = execution_notes_object(run_id="mock-x", llm="mock", cfg=cfg, prompt_versions=pv)
    assert obj["llm"] == "MOCK" and set(obj["models"].values()) == {"mock"}
