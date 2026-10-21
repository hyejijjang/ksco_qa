"""설정 로더 (설계 10.2 / CLAUDE.md 설계 보완)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ksco_qa.config import (
    Config,
    ConfigError,
    config_hash,
    require_for_model_calls,
    resolve_config,
    save_resolved,
)

FULL = {
    "MODEL_G0": "m0",
    "MODEL_G1B": "m1",
    "MODEL_G2": "m2",
    "PRICE_INPUT": 0.1,
    "PRICE_CACHED_INPUT": 0.01,
    "PRICE_OUTPUT": 0.5,
}


def write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_defaults_match_design_10_2(tmp_path: Path) -> None:
    cfg = resolve_config(tmp_path)
    assert (cfg.MODEL_G0, cfg.MODEL_G1B, cfg.MODEL_G2) == (None, None, None)
    assert (cfg.EFFORT_G0, cfg.EFFORT_G1B, cfg.EFFORT_G2) == ("medium", "high", "medium")
    assert cfg.G0_ESCALATE is True
    assert cfg.G2_OVERLAP_MODE == "AGREE_CHECK"
    assert cfg.FILE_ACCESS == "profile"
    assert cfg.CONCURRENCY == 10
    assert cfg.G1_TARGET_CANDS == (3, 8)
    assert cfg.G1_PAIRS_PER_CALL == 40
    assert cfg.NOT_FOUND_STOP_RATIO == 0.30
    assert (cfg.PRICE_INPUT, cfg.PRICE_CACHED_INPUT, cfg.PRICE_OUTPUT) == (None, None, None)
    assert cfg.BUDGET_USD is None
    assert cfg.MODE == "online"


def test_merge_order_global_task_overrides(tmp_path: Path) -> None:
    g = write_yaml(tmp_path / "global.yaml", {"CONCURRENCY": 5, "EFFORT_G0": "low", "G0_ESCALATE": "on"})
    task = tmp_path / "task"
    task.mkdir()
    write_yaml(task / "task_config.yaml", {"CONCURRENCY": 7})
    cfg = resolve_config(task, g, overrides={"EFFORT_G0": "high", "MODE": None})
    assert cfg.CONCURRENCY == 7
    assert cfg.EFFORT_G0 == "high"
    assert cfg.MODE == "online"


def test_yaml_on_is_true(tmp_path: Path) -> None:
    (tmp_path / "task_config.yaml").write_text("G0_ESCALATE: off\n", encoding="utf-8")
    assert resolve_config(tmp_path).G0_ESCALATE is False


@pytest.mark.parametrize(
    "data",
    [
        {"UNKNOWN_KEY": 1},
        {"OPENAI_API_KEY": "sk-x"},
        {"G2_OVERLAP_MODE": "SOMETHING"},
        {"FILE_ACCESS": "tools"},
        {"MODE": "offline"},
        {"G1_PAIRS_PER_CALL": 41},
        {"G1_TARGET_CANDS": [8, 3]},
        {"NOT_FOUND_STOP_RATIO": 1.5},
    ],
)
def test_invalid_values_rejected(tmp_path: Path, data: dict) -> None:
    write_yaml(tmp_path / "task_config.yaml", data)
    with pytest.raises(ConfigError):
        resolve_config(tmp_path)


def test_tools_with_batch_rejected(tmp_path: Path) -> None:
    write_yaml(tmp_path / "task_config.yaml", {"FILE_ACCESS": "profile+tools"})
    assert resolve_config(tmp_path).FILE_ACCESS == "profile+tools"
    with pytest.raises(ConfigError, match="online"):
        resolve_config(tmp_path, overrides={"MODE": "batch"})


def test_require_for_model_calls() -> None:
    with pytest.raises(ConfigError) as e:
        require_for_model_calls(Config())
    for key in FULL:
        assert key in str(e.value)
    with pytest.raises(ConfigError, match="PRICE_OUTPUT"):
        require_for_model_calls(Config(**(FULL | {"PRICE_OUTPUT": None})))
    require_for_model_calls(Config(**FULL))


def test_save_resolved_is_write_once(tmp_path: Path) -> None:
    cfg = Config(**FULL)
    path = save_resolved(cfg, tmp_path / "run")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert Config(**loaded) == cfg
    save_resolved(cfg, tmp_path / "run")  # 같은 내용이면 통과
    with pytest.raises(ConfigError):
        save_resolved(Config(**(FULL | {"CONCURRENCY": 3})), tmp_path / "run")


def test_config_hash_changes_with_values() -> None:
    assert config_hash(Config()) == config_hash(Config())
    assert config_hash(Config()) != config_hash(Config(CONCURRENCY=11))
