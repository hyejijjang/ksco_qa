"""Apps Script 연동 확인용 샘플 03_final.jsonl 만들기 (M1 게이트, 가상 데이터).

sample_task(가상 DataList 16행) + gate_records(가상 G0·G1·G2 기록)로 mock run의 G3를 돌려
tests/fixtures/apps_script_sample.jsonl에 쓴다. 최종 판정 규칙의 모든 경로(PASS·중복 FAIL·RESELECT_B·
G2 FAIL·자료 확인·중복 확인·사람 검토, G0/G2 호출·검증 실패)가 들어 있다.

다시 만들기: uv run python tests/fixtures/make_apps_script_sample.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from fixtures.gate_records import write_gate_records  # noqa: E402
from fixtures.sample_task import TASK_NAME, build_sample_task  # noqa: E402

from ksco_qa.config import Config  # noqa: E402
from ksco_qa.g3.export import FINAL_JSONL, run_g3  # noqa: E402
from ksco_qa.g3.records import load_inputs  # noqa: E402
from ksco_qa.p0 import run_p0  # noqa: E402
from ksco_qa.run import prepare_run  # noqa: E402

SAMPLE = HERE / "apps_script_sample.jsonl"


def make(target: Path = SAMPLE) -> dict:
    with tempfile.TemporaryDirectory() as d:
        task = build_sample_task(Path(d) / "sample_task")
        cfg = Config()
        ctx = prepare_run(task, cfg, "mock", now=datetime(2026, 10, 22, 9, 0, 0))
        run_p0(task, cfg, ctx.run_dir, ctx.result_path("00_mapping_audit.csv"))
        write_gate_records(ctx.run_dir, load_inputs(ctx.run_dir).row_cards)
        report = run_g3(ctx, cfg, {"G0": "sample", "G1B": "sample", "G2": "sample"},
                        source_file=f"{TASK_NAME}_DataList.xlsx")
        shutil.copy(ctx.result_path(FINAL_JSONL), target)
    return report


if __name__ == "__main__":
    report = make()
    print(SAMPLE, report["status"], report["summary"]["final_status"])
