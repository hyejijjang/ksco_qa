"""진행 표시 (설계 10.4): 막대·단계 요약·실측 usage 집계."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

from ksco_qa.llm.mock import MockFaults
from ksco_qa.progress import Progress
from tests.test_llm_client import ROW, call, g0_validator, make


class Tty(io.StringIO):
    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


def test_bar_line_and_summary() -> None:
    out = Tty()
    p = Progress(out)
    for _ in range(4):
        p.call_started("G0")
    p.call_finished("G0", failed=False, reused=False, input_tokens=4000, output_tokens=2000, cost=0.01)
    p.call_finished("G0", failed=True, reused=False, input_tokens=0, output_tokens=0, cost=None)
    line = p.line("G0")
    assert "2/4" in line and "실패 1" in line and "$0.0100" in line and "남은 약" in line
    assert "█" * 12 + "░" * 12 in line
    assert out.getvalue().startswith("\r")  # 한 줄을 덮어 쓰며 갱신
    p.flush()
    last = out.getvalue().splitlines()[-1]
    assert last.startswith("G0 완료 — 호출 2 · 실패 1 · 입력 4.0k · 출력 2.0k · $0.0100")


def test_cumulative_cost_carries_across_stages() -> None:
    p = Progress(Tty())
    p.call_started("G0")
    p.call_finished("G0", failed=False, reused=False, input_tokens=1, output_tokens=1, cost=0.5)
    p.flush()
    p.call_started("G2")
    assert "누적 $0.5000" in p.line("G2")


def test_not_a_tty_prints_only_summaries() -> None:
    out = io.StringIO()
    p = Progress(out)
    p.call_started("G1B")
    p.call_finished("G1B", failed=False, reused=False, input_tokens=1, output_tokens=1, cost=0.0)
    assert out.getvalue() == ""
    p.flush()
    assert out.getvalue().startswith("G1B 완료")


def test_ascii_fallback_bar() -> None:
    class Cp(Tty):
        encoding = "ascii"

    p = Progress(Cp())
    p.call_started("G0")
    assert "-" * 24 in p.line("G0")


def test_client_reports_measured_usage_once_per_call(tmp_path: Path) -> None:
    client, _, _ = make(tmp_path)
    client.progress = Progress(Tty())
    call(client)
    stats = client.progress._stages["G0"]
    [rec] = [json.loads(l) for l in (tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert (stats.started, stats.done, stats.failed, stats.reused) == (1, 1, 0, 0)
    assert stats.input == rec["usage"]["input"]
    assert stats.output == rec["usage"]["output"] + rec["usage"]["reasoning"]
    assert abs(stats.cost - rec["cost_usd"]) < 1e-12


def test_feedback_retry_counts_as_one_unit_with_both_usages(tmp_path: Path) -> None:
    client, _, _ = make(tmp_path, MockFaults.parse(["validation_fail=1.0", "repeats=1"]))
    client.progress = Progress(Tty())
    call(client)
    stats = client.progress._stages["G0"]
    recs = [json.loads(l) for l in (tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 2 and stats.done == 1
    assert abs(stats.cost - sum(r["cost_usd"] for r in recs)) < 1e-12


def test_resumed_call_counts_as_reused(tmp_path: Path) -> None:
    client, _, _ = make(tmp_path)
    call(client)
    client2, _, _ = make(tmp_path)
    client2.progress = Progress(Tty())
    call(client2)
    stats = client2.progress._stages["G0"]
    assert stats.reused == 1 and stats.done == 1


def test_summary_note_labels_other_stage_calls() -> None:
    out = io.StringIO()
    p = Progress(out)
    p.call_started("G1B")
    p.call_finished("G1B", failed=False, reused=False, input_tokens=1, output_tokens=1, cost=0.0)
    p.flush("G1c 누락 쌍 재판정")
    assert out.getvalue().startswith("G1B(G1c 누락 쌍 재판정) 완료")
