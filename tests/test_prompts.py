"""프롬프트 로더 — 주석 제거, G2 모드 섹션 선택, 실제 전송 텍스트 기준 prompt_version (M1 결정 26·28)."""

from __future__ import annotations

from pathlib import Path

import pytest

import ksco_qa.llm.client as client
from ksco_qa.llm.client import FEEDBACK_HEADER, build_messages, load_prompt, prompt_version

G2_TEXT = """<!-- 머리 주석 -->
## 판정 기준
기준 본문

## 행 단위 지시
지시 본문 <!-- 줄 안 주석 -->

## 겹치는 10개 지표 — AGREE_CHECK
동의 확인 지시

## 겹치는 10개 지표 — FULL_RECHECK
전부 재판정 지시
"""


@pytest.fixture
def prompt_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "common.md").write_text("<!-- c -->\n## 역할\n공통\n", encoding="utf-8")
    (tmp_path / "g0.md").write_text("## 판정 기준\nG0 본문\n<!-- TODO -->\n", encoding="utf-8")
    (tmp_path / "g2.md").write_text(G2_TEXT, encoding="utf-8")
    monkeypatch.setattr(client, "PROMPT_DIR", tmp_path)
    return tmp_path


def test_comments_removed(prompt_dir: Path) -> None:
    text = load_prompt("G0")
    assert "<!--" not in text and "TODO" not in text
    assert "공통" in text and "G0 본문" in text


@pytest.mark.parametrize("mode, kept, dropped", [
    ("AGREE_CHECK", "동의 확인 지시", "전부 재판정 지시"),
    ("FULL_RECHECK", "전부 재판정 지시", "동의 확인 지시"),
])
def test_g2_sends_only_its_mode_section(prompt_dir: Path, mode: str, kept: str, dropped: str) -> None:
    text = load_prompt("G2", mode)
    assert kept in text and dropped not in text
    assert "기준 본문" in text and "지시 본문" in text and "<!--" not in text


def test_g2_requires_mode(prompt_dir: Path) -> None:
    with pytest.raises(ValueError):
        load_prompt("G2")


def test_prompt_version_tracks_sent_text_only(prompt_dir: Path) -> None:
    base = prompt_version("G0")
    (prompt_dir / "g0.md").write_text("## 판정 기준\nG0 본문\n<!-- 다른 주석 -->\n", encoding="utf-8")
    assert prompt_version("G0") == base  # 주석만 바뀜 → 같은 버전
    (prompt_dir / "g0.md").write_text("## 판정 기준\nG0 본문 수정\n", encoding="utf-8")
    assert prompt_version("G0") != base
    assert prompt_version("G2", "AGREE_CHECK") != prompt_version("G2", "FULL_RECHECK")


def test_feedback_message_format(prompt_dir: Path) -> None:
    msg = build_messages("G0", {"a": 1}, ["job_evaluated가 'X'인데 이 행의 직업은 'Y'이다"])[-1]["content"]
    assert msg.endswith(FEEDBACK_HEADER + "\n- job_evaluated가 'X'인데 이 행의 직업은 'Y'이다")
    assert FEEDBACK_HEADER.startswith("직전 응답이 아래 검증 규칙을 위반했다. 입력은 같다.")


def test_real_prompt_files_load() -> None:
    """저장소의 실제 프롬프트 파일이 로더 규칙을 통과하는지 (G2 두 모드 섹션 존재)."""
    for mode in ("AGREE_CHECK", "FULL_RECHECK"):
        assert "<!--" not in load_prompt("G2", mode)
    assert "<!--" not in load_prompt("G0") and "<!--" not in load_prompt("G1B")


def _excerpt_lines(text: str) -> list[str]:
    """제목(#) 줄과 빈 줄을 뺀 본문 줄."""
    return [line for line in text.splitlines() if line.strip() and not line.startswith("#")]


def test_criteria_excerpts_are_verbatim() -> None:
    """common.md 전체와 g0.md '판정 기준' 섹션은 00_Work_Run.md 원문 줄을 그대로 잘라 쓴다 (요약·재작성 금지)."""
    root = Path(__file__).resolve().parents[1]
    source = set((root / "criteria" / "00_Work_Run.md").read_text(encoding="utf-8").splitlines())
    common = client.strip_comments((root / "prompts" / "common.md").read_text(encoding="utf-8"))
    g0 = client.strip_comments((root / "prompts" / "g0.md").read_text(encoding="utf-8"))
    g0_criteria = g0.split("## 판정 기준", 1)[1].split("## 행 단위 지시", 1)[0]
    for name, text in (("common.md", common), ("g0.md 판정 기준", g0_criteria)):
        lines = _excerpt_lines(text)
        assert lines, name
        assert [line for line in lines if line not in source] == [], name


def test_g0_prompt_has_no_work_markers_and_keeps_rules_separate() -> None:
    """[확인]·TODO 작업용 표시가 전송 텍스트에 없고, 팀 해석 규칙은 00 발췌(판정 기준)와 분리돼 있다."""
    text = load_prompt("G0")
    assert "[확인" not in text and "TODO" not in text
    criteria, rows = text.split("## 행 단위 지시", 1)
    assert "### 해석 규칙" in rows and "해석 규칙" not in criteria
    assert "REGENERATE 작성 금지 조건" in rows


def test_rules_are_shared_and_selected_by_stage() -> None:
    """rules.md 하나를 g0·g2가 같이 쓴다. G2에는 규칙 1·2·4·5만, 규칙 3·6과 G0 전용 문장은 G0에만 (2026-10-26)."""
    g0, g2 = load_prompt("G0"), load_prompt("G2", "AGREE_CHECK")
    for text in (g0, g2):
        assert text.count("### 해석 규칙") == 1 and "stages:" not in text and "include rules.md" not in text
        for rule in ("1. input_contract", "2. grounding", "4. output_specification", "5. 정답 유출"):
            assert rule in text
    assert "3. KEEP을 막는 것은 F뿐이다" in g0 and "3. KEEP을 막는 것은" not in g2
    assert "6. REGENERATE 시 원본 Task에 있던 구체 항목" in g0 and "6. REGENERATE 시" not in g2
    assert "expected_reference_spec에 쓴다" in g0.split("### 해석 규칙")[1].split("###")[0]
    assert "REVIEW_B를 검토한다" not in g2 and "task_clarity에도 적용한다" in g2 and "task_clarity에도" not in g0
    assert "해석 규칙" not in load_prompt("G1B")


def test_select_rules_markers(prompt_dir: Path) -> None:
    rules = "<!-- 머리 -->\n### 규칙\n<!-- stages: G0 G2 -->\n1. 공통\n<!-- stages: G0 -->\n   G0만\n<!-- stages: G2 -->\n   G2만\n"
    assert client.select_rules(rules, "G0") == "### 규칙\n1. 공통\n   G0만\n"
    assert client.select_rules(rules, "G2") == "### 규칙\n1. 공통\n   G2만\n"
    (prompt_dir / "rules.md").write_text(rules, encoding="utf-8")
    (prompt_dir / "g0.md").write_text("## 행 단위 지시\n<!-- include rules.md -->\n끝\n", encoding="utf-8")
    base = prompt_version("G0")
    assert "1. 공통\n   G0만" in load_prompt("G0") and "G2만" not in load_prompt("G0")
    (prompt_dir / "rules.md").write_text(rules.replace("   G2만", "   G2만 수정"), encoding="utf-8")
    assert prompt_version("G0") == base  # G0에 안 가는 줄만 바뀜 → 같은 버전
