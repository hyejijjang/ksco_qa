from __future__ import annotations

from pathlib import Path

import pytest

from fixtures.sample_task import build_sample_task


@pytest.fixture
def sample_task(tmp_path: Path) -> Path:
    return build_sample_task(tmp_path / "sample_task")


@pytest.fixture
def no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
