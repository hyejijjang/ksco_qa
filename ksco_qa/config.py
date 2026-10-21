"""설정 로더 (설계 4.1 설정 로더, 10.2 설정, 10.3 재개).

병합 순서: 코드 기본값 ← 전역 설정 파일 ← Task 폴더의 task_config.yaml ← CLI 지정값.
확정된 설정은 run 폴더의 config.resolved.yaml로 저장한다.
API 키는 설정에 두지 않는다 (환경 변수 OPENAI_API_KEY로만 받음).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ksco_qa.dictionaries import enum_values

TASK_CONFIG_NAME = "task_config.yaml"
RESOLVED_CONFIG_NAME = "config.resolved.yaml"

# 모델을 실제로 부르는 실행(run, sample, rerun-failed)에 반드시 있어야 하는 키 (10.2 "결정 필요")
REQUIRED_FOR_MODEL_CALLS = (
    "MODEL_G0",
    "MODEL_G1B",
    "MODEL_G2",
    "PRICE_INPUT",
    "PRICE_CACHED_INPUT",
    "PRICE_OUTPUT",
)


class ConfigError(Exception):
    """설정 파일 형식 오류, 값 검증 실패, 실행에 필요한 값 누락."""


class Config(BaseModel):
    """설계 10.2 설정 키. 키 이름·기본값은 표 그대로."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # 단계별 모델 ID — 결정 필요 (14장 #1)
    MODEL_G0: str | None = None
    MODEL_G1B: str | None = None
    MODEL_G2: str | None = None

    # 추론 강도
    EFFORT_G0: str = "medium"
    EFFORT_G1B: str = "high"
    EFFORT_G2: str = "medium"

    G0_ESCALATE: bool = True
    G2_OVERLAP_MODE: str = "AGREE_CHECK"
    FILE_ACCESS: str = "profile"
    CONCURRENCY: int = Field(default=10, ge=1)
    G1_TARGET_CANDS: tuple[int, int] = (3, 8)
    G1_PAIRS_PER_CALL: int = Field(default=40, ge=1, le=40)  # CLAUDE.md 원칙 3: ≤40쌍
    NOT_FOUND_STOP_RATIO: float = Field(default=0.30, ge=0.0, le=1.0)
    # row_card.file_profile 예산 (행당 글자 수, 설계 7.1·부록 B). 파일이 여럿이면 나눠 쓴다
    PROFILE_MAX_CHARS: int = Field(default=1500, ge=200)

    # 단가 USD / 1M 토큰 — 결정 필요 (14장 #1)
    PRICE_INPUT: float | None = Field(default=None, ge=0)
    PRICE_CACHED_INPUT: float | None = Field(default=None, ge=0)
    PRICE_OUTPUT: float | None = Field(default=None, ge=0)

    BUDGET_USD: float | None = Field(default=None, gt=0)

    # 호출 모드 (6.5, CLI --mode). 기본 online (14장 #9 제안안)
    MODE: str = "online"

    @field_validator("G2_OVERLAP_MODE")
    @classmethod
    def _check_overlap_mode(cls, v: str) -> str:
        return _check_enum(v, "g2_overlap_mode")

    @field_validator("FILE_ACCESS")
    @classmethod
    def _check_file_access(cls, v: str) -> str:
        return _check_enum(v, "file_access")

    @field_validator("MODE")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        return _check_enum(v, "call_mode")

    @field_validator("G1_TARGET_CANDS")
    @classmethod
    def _check_target_cands(cls, v: tuple[int, int]) -> tuple[int, int]:
        lo, hi = v
        if not 0 < lo <= hi:
            raise ValueError(f"G1_TARGET_CANDS는 0 < 하한 ≤ 상한이어야 한다: {v}")
        return v

    @model_validator(mode="after")
    def _check_tools_online_only(self) -> "Config":
        # CLAUDE.md 설계 보완: FILE_ACCESS=profile+tools는 online 모드에서만 허용
        if self.FILE_ACCESS == "profile+tools" and self.MODE == "batch":
            raise ValueError("FILE_ACCESS=profile+tools는 MODE=online에서만 쓸 수 있다 (batch와 함께 쓸 수 없음)")
        return self


def _check_enum(value: str, enum_name: str) -> str:
    allowed = enum_values(enum_name)
    if value not in allowed:
        raise ValueError(f"{value!r}는 허용값이 아니다: {allowed}")
    return value


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """YAML 파일을 읽어 최상위 매핑을 돌려준다. 빈 파일은 빈 dict."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: 최상위는 키-값 매핑이어야 한다")
    return data


def resolve_config(
    task_folder: Path,
    global_config: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> Config:
    """기본값 ← 전역 설정 ← task_config.yaml ← overrides 순으로 합쳐 검증한다.

    overrides에서 값이 None인 키는 지정하지 않은 것으로 본다 (CLI 옵션 미지정).
    """
    merged: dict[str, Any] = {}
    if global_config is not None:
        merged.update(load_yaml_mapping(global_config))
    task_config = Path(task_folder) / TASK_CONFIG_NAME
    if task_config.is_file():
        merged.update(load_yaml_mapping(task_config))
    if overrides:
        merged.update({k: v for k, v in overrides.items() if v is not None})
    try:
        return Config(**merged)
    except ValidationError as e:
        raise ConfigError(str(e)) from e


def require_for_model_calls(cfg: Config) -> None:
    """모델을 부르는 실행 전에 MODEL_*·PRICE_* 누락을 막는다."""
    missing = [k for k in REQUIRED_FOR_MODEL_CALLS if getattr(cfg, k) is None]
    if missing:
        raise ConfigError(f"모델 호출에 필요한 설정이 비어 있다: {', '.join(missing)}")


def config_to_dict(cfg: Config) -> dict[str, Any]:
    data = cfg.model_dump()
    data["G1_TARGET_CANDS"] = list(cfg.G1_TARGET_CANDS)
    return data


def config_hash(cfg: Config) -> str:
    """재개 기준이 되는 설정 해시 (CLAUDE.md 설계 보완)."""
    canonical = json.dumps(config_to_dict(cfg), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def save_resolved(cfg: Config, run_dir: Path) -> Path:
    """run 폴더에 config.resolved.yaml을 쓴다.

    이미 있으면 덮어쓰지 않는다. 내용이 같으면 그대로 두고, 다르면 오류.
    """
    path = Path(run_dir) / RESOLVED_CONFIG_NAME
    text = yaml.safe_dump(config_to_dict(cfg), allow_unicode=True, sort_keys=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ConfigError(f"{path}가 이미 있고 현재 설정과 다르다 (덮어쓰기 금지)")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
