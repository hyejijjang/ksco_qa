"""콘솔 진행 표시 (설계 10.4).

- 진행 막대: 단계별 완료/전체 호출, 실패 수, 누적 비용, 예상 남은 시간을 한 줄로 갱신한다 (터미널일 때만).
- 단계 요약: 단계가 끝나면 호출·실패·입력·출력 토큰·비용·시간을 한 줄 남긴다.
- 비용·토큰은 API usage 실측값만 쓴다 (재개로 기록을 재사용한 호출도 그 기록의 실측값).
- 전체 호출 수는 시작된 호출 수다. 단계 안에서 호출을 한꺼번에 시작하므로 처음부터 거의 전부 잡히고,
  G0 재판정처럼 뒤에 시작되는 호출은 그때 전체에 더해진다.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import TextIO

BAR_WIDTH = 24


@dataclass
class StageStats:
    started: int = 0
    done: int = 0
    failed: int = 0
    reused: int = 0
    input: int = 0
    output: int = 0
    cost: float = 0.0
    t0: float = field(default_factory=time.monotonic)


def _bar_chars(stream: TextIO) -> tuple[str, str]:
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        "█░".encode(encoding)
        return "█", "░"
    except (UnicodeEncodeError, LookupError):
        return "#", "-"


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}초"
    return f"{seconds // 60}분 {seconds % 60:02d}초"


def _tokens(n: int) -> str:
    return f"{n / 1_000_000:.2f}M" if n >= 100_000 else f"{n / 1000:.1f}k"


class Progress:
    def __init__(self, stream: TextIO | None = None, *, live: bool | None = None) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._live = self._stream.isatty() if live is None else live
        self._full, self._empty = _bar_chars(self._stream)
        self._stages: dict[str, StageStats] = {}
        self._line_len = 0
        self._cost_carry = 0.0  # 이미 끝난 단계의 비용 (누적 표시용)

    def call_started(self, stage: str) -> None:
        stats = self._stages.setdefault(stage, StageStats())
        stats.started += 1
        self._draw(stage)

    def call_finished(self, stage: str, *, failed: bool, reused: bool,
                      input_tokens: int, output_tokens: int, cost: float | None) -> None:
        stats = self._stages.setdefault(stage, StageStats())
        stats.done += 1
        stats.failed += int(failed)
        stats.reused += int(reused)
        stats.input += input_tokens
        stats.output += output_tokens
        stats.cost += cost or 0.0
        self._draw(stage)

    def total_cost(self) -> float:
        return self._cost_carry + sum(s.cost for s in self._stages.values())

    def line(self, stage: str) -> str:
        s = self._stages[stage]
        total = max(s.started, 1)
        filled = round(BAR_WIDTH * s.done / total)
        bar = self._full * filled + self._empty * (BAR_WIDTH - filled)
        text = f"{stage:<4} {bar} {s.done}/{s.started} · 실패 {s.failed} · 누적 ${self.total_cost():.4f}"
        elapsed = time.monotonic() - s.t0
        fresh = s.done - s.reused
        if 0 < fresh and s.done < s.started:
            text += f" · 남은 약 {_duration(elapsed / fresh * (s.started - s.done))}"
        return text

    def summary(self, stage: str, note: str | None = None) -> str:
        s = self._stages[stage]
        label = f"{stage}({note})" if note else stage
        text = (f"{label} 완료 — 호출 {s.done} · 실패 {s.failed} · 입력 {_tokens(s.input)} · "
                f"출력 {_tokens(s.output)} · ${s.cost:.4f} · {_duration(time.monotonic() - s.t0)}")
        if s.reused:
            text += f" (기록 재사용 {s.reused})"
        return text

    def flush(self, note: str | None = None) -> None:
        """단계가 끝나면 부른다. 이번에 호출이 있었던 단계마다 요약 한 줄을 남기고 비운다.
        note는 같은 stage 호출을 다른 단계가 낸 경우의 표시 (예: G1c가 낸 G1B 재판정)."""
        self._clear()
        for stage in list(self._stages):
            print(self.summary(stage, note), file=self._stream, flush=True)
        self._cost_carry = self.total_cost()
        self._stages.clear()

    def _draw(self, stage: str) -> None:
        if not self._live:
            return
        text = self.line(stage)
        pad = max(self._line_len - len(text), 0)
        self._stream.write("\r" + text + " " * pad)
        self._stream.flush()
        self._line_len = len(text)

    def _clear(self) -> None:
        if self._live and self._line_len:
            self._stream.write("\r" + " " * self._line_len + "\r")
            self._stream.flush()
        self._line_len = 0
