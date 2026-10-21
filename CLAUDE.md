# KSCO Task QA 파이프라인

ChatGPT Work에서 대화로 돌리던 KSCO Task QA(P0→G0→G1→G2→G3)를 고정 코드 + LLM API 배치 파이프라인으로 옮기는 저장소.
전체 설계: `docs/design.md` (KSCO Task QA 파이프라인 — API 구현 설계·기획안). 작업 전 해당 장을 먼저 읽을 것.

## 판정 기준 (수정 금지)
- `criteria/00_Work_Run.md` (Canonical 1.0), `criteria/06_Result_Schema.md` (canonical-1.0)
- 이 두 파일은 절대 수정하지 않는다. 프롬프트 발췌는 원문을 그대로 잘라 쓴다 (요약·재작성 금지).

## 핵심 원칙 (설계 3장)
1. 결정적 단계(P0, 파일 프로필, G1a 후보 생성, G1c 그룹 확정, G3 판정·내보내기·검증)는 고정 모듈. 실행마다 스크립트를 새로 만들지 않는다.
2. 판정은 모델 출력에서만 나온다. 코드가 판정을 만들거나 채우지 않는다. 규칙 판정은 `decided_by=RULE`로 표시.
3. G0·G2는 행 1개 = 호출 1회, G1b는 쌍 묶음 1개(≤40쌍, ≤20행) = 호출 1회. 다른 행 정보를 넣지 않는다.
4. 모든 판정 호출은 JSON 스키마 강제(structured outputs). enum은 `dictionaries/enums.yaml`이 유일한 출처.
5. 호출에 Task 이름·폴더 이름(예: accounting)·절대 경로를 넣지 않는다. 경로는 `01_output_files/` 기준 상대 경로만.
6. `_work/` 아래 기록(calls.jsonl, records.jsonl 등)은 추가 전용. 덮어쓰기 금지. calls.jsonl 쓰기는 단일 writer가 전담.
7. 토큰·비용은 API usage 실측값만 기록한다.

## 설계 보완 사항 (설계 문서보다 우선)
- call_id = hash(stage, unit_id, model, reasoning_effort, attempt_kind, prompt_version, input_hash). attempt_kind ∈ {first, escalate, feedback}
- 재개 기준은 설정 해시 + 입력 파일 해시. run_id의 시각은 표시용 라벨이며, `--resume <run_id>`로 명시 재개도 지원.
- `FILE_ACCESS=profile+tools`는 online 모드에서만 허용 (Batch와 함께 쓰면 설정 검증에서 오류).
- overlap_status의 LOW_OVERLAP은 생성 규칙이 정해질 때까지 사용하지 않는다.

## 저장소 구조
```
criteria/      판정 기준 원문 (읽기 전용)
prompts/       common.md, g0.md, g1b.md, g2.md, CHANGELOG.md
schemas/       g0.json, g1b.json, g2.json
dictionaries/  criteria.yaml (부록 A), enums.yaml (7.5)
ksco_qa/       config, p0, profiler, llm(client wrapper), stages(g0,g1a,g1b,g1c,g2), g3, compare, cli
tests/         fixtures/ (작은 샘플 DataList, Work 결과 일부)
docs/design.md
```

## 개발 규칙
- Python 3.11+, uv. 실행: `uv run ksco-qa <mode> <task_folder>`
- 테스트: `uv run pytest`. 모듈을 추가·수정하면 테스트도 같이 작성하고 통과시킨 뒤 끝낸다.
- 실제 Task 데이터(DataList, Deliverable)는 저장소 밖에 있다. 저장소에 복사하거나 커밋하지 않는다. 테스트는 `tests/fixtures/`의 작은 샘플만 쓴다.
- API 키는 환경 변수(`OPENAI_API_KEY`)로만 받는다. `.env`를 읽거나 출력하지 않는다.
- 실제 모델 API를 호출하는 명령(run, sample, rerun-failed)은 사람이 직접 실행한다. 테스트에서는 LLM 클라이언트를 mock한다.
- 마일스톤(M1~M6) 단위로 작업하고, 각 마일스톤의 게이트(설계 13장)를 통과했는지 확인한 뒤 보고한다.
