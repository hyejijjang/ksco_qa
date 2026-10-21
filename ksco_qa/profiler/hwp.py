"""HWP(구버전) — 판독 도구 없음 → NOT_INSPECTED로 확정 (설계 부록 B HWP 행 / M1 결정 13)."""

from __future__ import annotations

from pathlib import Path

from ksco_qa.profiler.base import ProfileError, ProfileParts


def profile(path: Path) -> ProfileParts:
    raise ProfileError("HWP(구버전) 판독 도구 없음")
