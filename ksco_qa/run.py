"""run 준비·재개·산출물 위치 (설계 4.2, 10.3 / CLAUDE.md 설계 보완).

- run_id = [mock-][sampleN-]<시각>-<설정 해시 8>-<입력 해시 8>. 시각은 표시용 라벨.
- 재개 기준은 설정 해시 + 입력 파일 해시 (+ llm 종류, sample N). --resume <run_id>로 명시 재개.
- mock run은 실제 run과 섞이지 않는다: run_id에 mock 표시, 실제 run이 mock run을 재개하지 않음,
  산출물은 03_results/가 아니라 _work/<run_id>/ 안에만 쓴다.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ksco_qa.config import Config, config_hash, save_resolved
from ksco_qa.p0 import P0_VERSION, find_datalist
from ksco_qa.profiler.base import PROFILER_VERSION

RESULTS_DIR_NAME = "03_results"
OUTPUT_FILES_DIR = "01_output_files"
RUN_META_NAME = "run_meta.json"


class RunError(Exception):
    pass


@dataclass(frozen=True)
class RunContext:
    task_folder: Path
    task_name: str
    run_id: str
    run_dir: Path
    results_dir: Path
    llm: str
    sample_n: int | None = None

    @property
    def is_mock(self) -> bool:
        return self.llm == "mock"

    def result_path(self, name: str) -> Path:
        """최종 산출물 경로. mock run은 run 폴더 밖을 가리키면 오류."""
        path = (self.results_dir / name).resolve()
        if self.is_mock and not path.is_relative_to(self.run_dir.resolve()):
            raise RunError(f"mock run은 _work/{self.run_id}/ 밖에 쓸 수 없다: {path}")
        return path


def work_root(task_folder: Path) -> Path:
    return Path(task_folder) / RESULTS_DIR_NAME / "_work"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def input_files_hash(task_folder: Path, datalist: Path) -> str:
    """DataList + 01_output_files 전체(상대 경로 NFC + 내용 해시)의 해시."""
    h = hashlib.sha256()
    h.update(b"datalist\0" + _file_sha256(datalist).encode() + b"\n")
    out_dir = Path(task_folder) / OUTPUT_FILES_DIR
    if out_dir.is_dir():
        files = [p for p in out_dir.rglob("*") if p.is_file()]
        entries = sorted((unicodedata.normalize("NFC", p.relative_to(out_dir).as_posix()), p) for p in files)
        for rel, p in entries:
            h.update(rel.encode("utf-8") + b"\0" + _file_sha256(p).encode() + b"\n")
    return h.hexdigest()


def make_run_id(llm: str, cfg_hash: str, in_hash: str, now: datetime, sample_n: int | None = None) -> str:
    prefix = ("mock-" if llm == "mock" else "") + (f"sample{sample_n}-" if sample_n else "")
    return f"{prefix}{now:%Y%m%d-%H%M%S}-{cfg_hash[:8]}-{in_hash[:8]}"


def _read_meta(run_dir: Path) -> dict | None:
    path = run_dir / RUN_META_NAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _find_resumable(work: Path, key: dict) -> str | None:
    if not work.is_dir():
        return None
    matches = []
    for run_dir in work.iterdir():
        meta = _read_meta(run_dir) if run_dir.is_dir() else None
        if meta and all(meta.get(k) == v for k, v in key.items()):
            matches.append((meta["created_at"], meta["run_id"]))
    return max(matches)[1] if matches else None


def prepare_run(
    task_folder: Path,
    cfg: Config,
    llm: str,
    *,
    resume: str | None = None,
    sample_n: int | None = None,
    now: datetime | None = None,
) -> RunContext:
    task_folder = Path(task_folder)
    datalist, task_name = find_datalist(task_folder)
    key = {
        "llm": llm,
        "config_hash": config_hash(cfg),
        "input_hash": input_files_hash(task_folder, datalist),
        "sample_n": sample_n,
        # 결정적 단계 코드가 바뀌면 P0 산출물이 달라지므로 새 run (추가 전용 기록과 충돌 방지)
        "code_version": f"p0-{P0_VERSION}/profiler-{PROFILER_VERSION}",
    }
    work = work_root(task_folder)

    if resume is not None:
        run_dir = work / resume
        meta = _read_meta(run_dir)
        if meta is None:
            raise RunError(f"재개할 run이 없다: {resume}")
        if meta["llm"] != llm:
            raise RunError(f"run {resume}은 llm={meta['llm']}로 만든 run이라 llm={llm}로 이어 갈 수 없다")
        for k in ("config_hash", "input_hash", "sample_n", "code_version"):
            if meta.get(k) != key[k]:
                raise RunError(f"run {resume}과 현재 {k}가 다르다 (설정 또는 입력 파일이 바뀜)")
        run_id = resume
    else:
        run_id = _find_resumable(work, key)
        if run_id is None:
            now = now or datetime.now()
            run_id = make_run_id(llm, key["config_hash"], key["input_hash"], now, sample_n)
            run_dir = work / run_id
            run_dir.mkdir(parents=True, exist_ok=False)
            meta = {"run_id": run_id, "created_at": now.isoformat(), **key}
            (run_dir / RUN_META_NAME).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        run_dir = work / run_id

    save_resolved(cfg, run_dir)
    results_dir = run_dir if llm == "mock" else task_folder / RESULTS_DIR_NAME
    return RunContext(task_folder, task_name, run_id, run_dir, results_dir, llm, sample_n)
