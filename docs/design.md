# KSCO Task QA 파이프라인 — API 구현 설계·기획안

Oct 16, 2026 · @Daniel Kim

---

## 1. 개요

ChatGPT Work에서 대화 단위로 돌리던 KSCO Task QA(P0→G0→G1→G2→G3)를, 고정 코드와 API 호출로 이루어진 배치 파이프라인으로 옮긴다. 판정 기준(00_Work_Run.md Canonical 1.0, 06_Result_Schema.md)은 바꾸지 않는다. 바꾸는 것은 실행 방식뿐이다.

### 목적

- 사람이 대화를 열고 "이어서"를 보내는 수작업을 없앤다. 명령 한 번으로 한 Task 폴더를 끝까지 처리한다.
- 판정 단위를 호출 단위로 분리해 행끼리 판단이 섞이지 않게 한다.
- 같은 입력이면 같은 방식으로 판정되도록 실행을 재현 가능하게 만든다. 모델·프롬프트 버전·파라미터를 남긴다.
- 토큰·비용·시간을 실측해, Task별 예산을 미리 산정할 수 있게 한다.

### 범위

| 구분 | 포함 | 제외 |
|---|---|---|
| 단계 | P0 매핑, G0 수정·재생성, G1 중복 검수, G2 설계 품질 검수, G3 판정·내보내기 | 새 Deliverable 수집, Scenario·Reference·Rubric 실물 제작 |
| 대상 | KSCO 28·33·34 등 같은 열 구조의 DataList | 열 구조나 판정 기준이 다른 검수 (별도 기준 문서 필요) |
| 산출물 | Gate별 최종 파일 4개 + 03_final.jsonl + 04_sheet_paste.xlsx | 03_final.xlsx, QA_SUMMARY.md, 후보·coverage CSV, 검증용 부산물 |
| 연동 | 기존 검수 툴(Apps Script)이 하던 판정 자체를 대체. DataList 기존 열(R=AI 판정, T=Regenerate Task 등)에 붙여 넣을 04_sheet_paste.xlsx를 같은 형식으로 만들고, 03_final.jsonl은 06 스키마대로 기록·Work 비교용으로 남긴다 (2026-10-22 정정) | 검수 툴이 03_final.jsonl을 읽는 연동, Apps Script 수정 |

00_Work_Run.md 7.3의 부산물 5종(00_input_snapshot.xlsx, 01_duplicate_candidates.csv, 01_duplicate_coverage.csv, 03_final.xlsx, QA_SUMMARY.md)은 만들지 않는다. run_report.json과 01_duplicate_audit.xlsx(coverage 열 포함)로 대체한다 (2026-10-22 결정).

### 성공 기준

1. accounting(KSCO-33, 398행)을 명령 한 번으로 끝까지 처리한다. 사람 개입은 시작과 결과 확인뿐이다.
2. 최종 산출물 5개가 06 스키마 최소 검증 10항목을 모두 통과한다. 원본 행 수, source_row, id가 1:1로 맞는다.
3. 템플릿 판정(같은 사유 문장 반복)과 직무 기준 오판(다른 직업 기준 판단)이 자동 검사에서 0건이다.
4. 같은 데이터의 Work 실행 결과와 비교했을 때, 판정 불일치 행의 원인을 모두 설명할 수 있다 (9장).
5. 실행마다 실측 토큰·비용·소요 시간이 남는다.

---

## 2. Work 실행에서 얻은 교훈

두 번의 Work 실행에서 실제로 생긴 문제 10가지가 이 설계의 요구사항이다. 첫 실행은 KSCO-34(412행)를 한 대화에서 돌렸고, 두 번째는 KSCO-33 accounting(398행)을 분할 방식으로 돌렸다.

| # | 실제로 생긴 일 | 원인 | API 설계 반영 |
|---|---|---|---|
| 1 | G0가 파일 매칭 여부만으로 KEEP/REVIEW_B를 정했고, REGENERATE는 코드에 박힌 1행뿐이었다 (KSCO-34) | 한 대화에서 412행을 감당하지 못해 모델이 판정을 코드로 대체 | 호출 1회 = 판정 단위 1개. 판정은 모델 출력에서만 나오고, 코드는 판정을 만들지 않는다 |
| 2 | G2 평가 대상이 전부 PASS, 16개 지표 사유가 같은 문장 틀에 값만 끼운 형태 (KSCO-34) | 1번과 같음 | 템플릿 감지 검사(9장)를 단계마다 실행 |
| 3 | G1 후보가 34,882쌍(행당 평균 169개), 판정은 유사도 임계값 if문 (KSCO-34) | "공통 서명" 같은 넓은 신호가 전체 쌍의 약 40%를 후보로 만듦 | 후보 생성 규칙과 규모 상한을 고정 코드로 (행당 평균 3~8개 목표) |
| 4 | G0 배치 04에서 통계‧데이터 사무원 32행을 "회계직무와 맞지 않는다"며 RESELECT_B 처리. 같은 유형의 배치 05는 40행 모두 KEEP (accounting) | 앞 배치의 회계 직업과 폴더 이름에 끌려감 | G0·G2는 행 1개 = 호출 1개. 출력에 job_evaluated를 두고 코드로 대조 |
| 5 | B열 id가 398행 중 6행에만 있었음 (accounting) | Google Sheets 수식으로 만든 id가 xlsx로 내보낼 때 값으로 넘어오지 않음 | 사전 검사에서 id 누락·중복이면 실행 전에 중단 |
| 6 | 시트 max_row가 1,073행인데 실제 데이터는 398행 (accounting) | A열 체크박스(FALSE)가 빈 행까지 채워져 있음 | 데이터 행 = B~I열 중 하나라도 값이 있는 행 |
| 7 | I열(직무정보)이 IMPORTRANGE 수식 (accounting) | Google Sheets 내보내기 파일 | 셀 값은 캐시된 계산값으로 읽고, 수식 원문은 source.cells.formula로만 보존 |
| 8 | usage_log.jsonl이 272KB에서 272B로 덮어써져 토큰 기록 소실. 남아 있던 값도 16,000·9,000처럼 어림값 (accounting) | Work에서는 실제 토큰을 알 수 없고, S5가 로그를 정리하다 덮어씀 | API 응답의 usage를 호출마다 추가 전용으로 기록 |
| 9 | 최종 JSONL의 duplicate.overlap_status가 398행 전부 null (accounting) | 내보내기 코드를 매번 새로 짜면서 필드 누락 | 고정 내보내기 코드 + "전 행 null 필드 = 실패" 검사 |
| 10 | 실행마다 p0_run.py, s2_batch01.py 등 스크립트가 새로 생김 | Work 모델이 결정적 단계를 매번 새로 구현 | P0·후보 생성·그룹 확정·G3를 고정 모듈로 |

반대로 Work에서 잘 된 점도 유지한다. 행마다 판단하게 했을 때는 사유가 구체적이었다. 예를 들어 "제목은 3점척도인데 실제 점수 열은 0~4 다섯 범주", "메달 Task에 정답 분포 수치 포함" 같은 문제를 잡아냈다. 이런 발견은 모델이 필요할 때 Deliverable 원본을 직접 열어 본 덕분이 커서, 6장의 파일 열람 방식을 정할 때 반영한다.

accounting Work 실행의 최종 결과는 PASS 183 / REVIEW 101 / FAIL 114(중복 제외 105 포함)이다. API 버전의 비교 기준으로 쓴다.

---

## 3. 설계 원칙

판단은 모델이 하고, 나머지는 전부 고정 코드가 한다. 아래 8가지가 모든 설계 결정의 기준이다.

1. **결정적 단계는 고정 코드** — 매핑, 파일 프로필, 후보 생성, 그룹 확정, 최종 판정, 내보내기, 검증은 버전 관리되는 모듈이다. 실행마다 같은 코드가 돈다.
2. **모델은 판단만** — 모델 출력은 판정 값과 그 근거뿐이다. 코드는 모델 없이 판정을 만들거나 채우지 않는다. 실패한 호출은 빈칸으로 두고 재시도한다.
3. **판정 단위는 서로 독립** — G0·G2는 행 1개, G1은 코드가 정한 쌍 묶음 1개가 호출 1회다. 한 호출은 다른 행의 판정을 보지 못한다.
4. **출력은 스키마로 강제** — 모든 판정 호출은 JSON 스키마(structured outputs)를 쓴다. 형식 오류·enum 오류는 호출 단계에서 막는다.
5. **재현 가능** — 호출마다 모델 ID, 추론 강도, 프롬프트 버전 해시, 입력 해시를 기록한다. 같은 run을 다시 돌리면 끝난 호출은 건너뛴다.
6. **중간 산출물은 추가 전용** — 호출 결과·사용량 로그는 덮어쓰지 않는다. 재판정도 새 레코드로 남기고 최신 것을 쓴다.
7. **비용은 실측** — 토큰과 비용은 API usage 값만 쓴다. 추정은 실행 전 예산 산정에만 쓴다.
8. **Work와 비교 가능** — 최종 산출물의 파일명·스키마는 Work 분할본과 같다. `final.execution_notes`에 실행 방식을 남겨 어느 쪽 결과인지 구분한다.

---

## 4. 전체 아키텍처

파이프라인은 단계 7개와 공통 구성 요소 3개로 이루어진다. 모델을 부르는 단계는 G0·G1b·G2뿐이고, 세 단계 모두 같은 클라이언트 래퍼를 거친다.

> 판단은 모델 호출 3단계만, 나머지는 고정 코드가 처리한다.
> [코드 단계] / [모델 호출 단계] / [공통 구성 요소]

```
[입력] DataList.xlsx · 01_output_files · task_config
   ↓
[P0 사전 검사·매핑·프로필] (코드)        헤더·id 검사, D.F 매핑, row_card 생성
   ↓
[G0 Task 수정·재생성] (모델)             행 1개 = 호출 1회, 검증 실패 시 high 재판정
   ↓
[G1a 중복 후보 생성] (코드)              6개 신호 합집합, 행당 3~8개, 쌍 묶음 생성
   ↓
[G1b 쌍 판정] (모델)                     묶음 1개(≤ 40쌍) = 호출 1회
   ↓
[G1c 그룹 확정] (코드)                   대표 선정, 대표-구성원 직접 판정 확인
   ↓
[G2 설계 품질 검수] (모델)               행 1개 = 호출 1회, G0와 별도 컨텍스트
   ↓
[G3 판정·내보내기·검증] (코드)           7.1 규칙, criterion 사전, 06 검증 10항목
   ↓
[최종 산출물 5개] audit · revision · duplicate · verify · final.jsonl

공통 구성 요소
- 프롬프트·스키마 저장소: 판정 기준 원문 발췌, 단계별 프롬프트 g0·g1b·g2, 출력 JSON 스키마,
  criterion·enum 사전, 버전 해시
- LLM 클라이언트 래퍼 (G0·G1b·G2가 사용): 스키마 강제(structured outputs), 단계별 모델·추론 강도,
  재시도·백오프·동시성 제어, 코드 검증 → 피드백 재호출, call_id로 중복 호출 방지·재개,
  usage 실측 → 비용 계산, online 또는 Batch API 모드
- run 저장소 (_work/run_id) (G3가 읽음): calls.jsonl 호출·사용량 기록, 단계별 판정 레코드, raw 응답,
  overrides, review_queue, run_report 요약·비용. 추가 전용, 덮어쓰지 않음
```

파이프라인 구성 · 단계 7개, 공통 구성 요소 3개

단계는 위에서 아래로 한 번씩만 지나간다. 앞 단계가 검증을 통과해야 다음 단계가 시작된다. G3는 모델을 부르지 않고 run 저장소의 레코드만 읽는다.

### 4.1 구성 요소

| 구성 요소 | 역할 | 얼마나 자주 바뀌나 |
|---|---|---|
| 설정 로더 | 전역 설정 + Task별 task_config를 합쳐 run 설정 확정 | 드물다 |
| P0 모듈 | 헤더·id 검사, 인벤토리, 매핑, Reference 분기, row_card | 드물다 |
| 파일 프로파일러 | 형식별 구조 요약 (부록 B), 파일 해시 캐시 | 새 형식이 나오면 추가 |
| 프롬프트·스키마 저장소 | 판정 기준 발췌, 단계별 프롬프트, 출력 스키마, 사전 (8장) | 튜닝 시 자주 |
| LLM 클라이언트 래퍼 | 호출·재시도·스키마 강제·사용량 기록·중복 방지 (6장) | 모델·공급사 교체 시 |
| 단계 실행기 | G0·G1b·G2 호출 단위 만들기, 동시 실행, 코드 검증 | 드물다 |
| G1a·G1c 모듈 | 후보 생성·묶음, 그룹·대표 확정 | 임계값만 조정 |
| G3 모듈 | 최종 판정, Excel·JSONL 내보내기, 검증 | 스키마가 바뀔 때만 |
| 비교 도구 | 두 결과(Work·API, 버전 간)의 일치도 리포트 (9.3) | 드물다 |
| run 저장소 | 호출 기록, 판정 레코드, 원문, 사람 검토 반영분 | — |

### 4.2 실행 디렉터리 구조

Task 폴더 구성은 Work 분할본과 같다. 최종 산출물 5개만 `03_results/`에 두고, 나머지는 run별 폴더에 둔다. 이 문서에서 `_work/`는 `03_results/_work/<run_id>/`를 줄여 부른 것이다.

```
<Task 폴더>/                         예: accounting
  KSCO-33_DataList.xlsx              DataList (정확히 1개)
  01_output_files/                   Deliverable Files
  task_config.yaml                   (선택) Task별 설정
  03_results/
    00_mapping_audit.csv             P0
    00_revision_regenerate.xlsx      G0
    01_duplicate_audit.xlsx          G1
    02_task_verify.xlsx              G2
    03_final.jsonl                   G3
    _work/<run_id>/
      config.resolved.yaml           확정 설정
      row_cards.jsonl
      file_profiles/
      source_cells.jsonl
      calls.jsonl                    호출·사용량 (추가 전용)
      raw/<call_id>.json             응답 원문
      g0/records.jsonl
      g1/candidates.jsonl
      g1/pairs.jsonl
      g2/records.jsonl
      overrides.jsonl                사람 검토 반영
      review_queue.csv               사람 검토 목록
      run_report.json                요약·검증·비용
```

파이프라인 코드와 프롬프트는 Task 폴더가 아닌 별도 저장소에 두고, 모든 Task가 같은 버전을 쓴다. Work 분할본처럼 Task마다 프롬프트를 복사하지 않는다.

---

## 5. 단계별 상세 설계

P0·G1a·G1c·G3는 코드만, G0·G1b·G2는 모델 호출로 처리한다. 각 단계는 앞 단계의 검증이 통과해야 시작한다.

### 5.1 P0 — 사전 검사·매핑·파일 프로필 (코드)

입력: Task 폴더의 `*_DataList.xlsx`(정확히 1개), `01_output_files/`, 선택 task_config.

처리 순서

1. **설정 확정** — DataList 파일을 찾고 TASK_NAME을 파일명에서 얻는다. 0개나 2개 이상이면 중단한다.
2. **헤더 검증** — DataList 시트의 B=id, C=직업명, D=산출물, E=레퍼런스, F=출력포맷, G=태스크, I=직무정보를 확인한다. 다르면 중단한다.
3. **값 읽기** — 캐시된 계산값으로 읽는다. 같은 파일을 한 번 더 읽어 수식·하이퍼링크 원문을 셀별로 보관한다 (G3의 source.cells용).
4. **데이터 행 확정** — B~I열 중 하나라도 값이 있는 행만 데이터 행이다.
5. **식별 검사** — id 누락·중복이 있으면 행 목록을 출력하고 중단한다. I열이 비거나 "매칭 실패" 문자열이면 경고만 남긴다.
6. **인벤토리** — `01_output_files/` 전체와 ZIP 멤버를 목록화한다. 이름은 NFC로 정규화한다.
7. **매핑** — 예상 파일명 `{D}.{F}`와 전체 이름이 정확히 같은 파일을 찾는다. 허용되는 정규화는 NFC와 확장자 대소문자뿐이다. 상태는 MATCHED / AMBIGUOUS / CONFLICT / NOT_FOUND / INACCESSIBLE / INVENTORY_INCOMPLETE.
8. **이상 감지** — NOT_FOUND가 데이터 행의 30%를 넘으면 중단하고 경로·ZIP·권한 문제를 보고한다 (임계값은 설정값).
9. **Reference 분기** — E열이 비어 있으면 GENERATE_REFERENCE. 값이 있고 연결 파일을 열 수 있으면 PROVIDED_REFERENCE, 열 수 없으면 UNRESOLVED_REFERENCE. E열 형식이 정해져 있지 않아 해석 규칙은 결정 필요 사항이다 (14장).
10. **파일 프로필** — 매칭된 파일마다 구조 요약을 만든다 (부록 B). 같은 파일 해시는 캐시를 재사용한다.
11. **row_card 생성** — 행마다 이후 호출에 들어갈 입력을 만든다 (7장).

출력: `03_results/00_mapping_audit.csv`(최종), `_work/row_cards.jsonl`, `_work/file_profiles/`, `_work/source_cells.jsonl`.

완료 조건: 데이터 행 수 = row_card 수 = mapping_audit 행 수. 모든 행에 매핑 상태가 있다.

### 5.2 G0 — Task 수정·재생성 (모델, 행 1개 = 호출 1회)

- **대상**: inspected=true 행. inspected=false 행은 코드가 REVIEW_B로 기록한다 (사유 = P0 상태). 이것은 규칙 판정이라는 표시(decided_by=RULE)를 남긴다.
- **입력**: 그 행의 row_card만. 다른 행 정보는 넣지 않는다.
- **모델이 하는 일**: 10개 차원 P/R/F/NA, action 4종 중 하나, REGENERATE면 새 Task 한 줄, task_card(입력·작업·기준·출력), job_evaluated.
- **코드 검증 (호출 직후)**:
  - job_evaluated = row_card 직업명인가
  - F가 있는데 KEEP인가 (모순)
  - REGENERATE인데 새 Task가 비었거나 원본과 같은가
  - 한 행 안에서 차원별 issues 문장이 복사되었는가
  - 위반 시 피드백을 붙여 1회 재호출. 두 번째도 위반이면 REVIEW로 두고 사람 검토 목록에 올린다.
- **출력**: `_work/g0/records.jsonl` (추가 전용). 단계 종료 시 최종 `03_results/00_revision_regenerate.xlsx`.
- **완료 조건**: 전 데이터 행에 action이 있고, REGENERATE 행에는 새 Task가 있다.

### 5.3 G1a — 중복 후보 생성 (코드)

- **대상**: effective_task가 있는 행 (KEEP=원본 G열, REGENERATE=새 Task).
- **신호 (합집합)**:

| 신호 | 규칙 | 제거 가능 |
|---|---|---|
| exact | 공백·구두점 제거 후 effective_task 동일 | 아니오 |
| param | 연도·숫자·기간·지역/기관명을 지운 뒤 Task 동일 | 아니오 |
| same_deliverable | expected_filename 동일, 또는 숫자 제거 D열 동일 | 아니오 |
| tfidf_task | effective_task 문자 2~4gram TF-IDF, 행별 상위 5개 중 유사도 ≥ 0.30 | 임계값 조정 |
| card | task_card 토큰 TF-IDF 또는 임베딩, 행별 상위 5개 중 ≥ 0.40 | 임계값 조정 |
| tfidf_orig | original_task 기준 tfidf_task와 동일 (보조) | 임계값 조정 |

- **규모 관리**: 목표는 행당 평균 3~8개다. 전체 쌍이 active 행 수 × 10을 넘으면 조정 가능 신호의 임계값을 0.05씩 올린다. 최종 임계값과 신호별 쌍 수를 기록한다.
- **묶음 만들기**: 후보 그래프의 연결 요소를 기준으로 묶음당 최대 40쌍, 행 20개로 자른다. 큰 연결 요소는 쌍을 유지한 채 나눠 같은 쌍이 두 묶음에 들어가지 않게 한다.
  - Work는 배치당 120쌍이었다. API는 호출을 더 잘게 나눠 한 호출 안의 판단 수를 줄인다.
- **중간 산출물**: `_work/g1/candidates.jsonl`에 후보 쌍과 신호, `bundles.jsonl`에 G1b 호출 묶음, `search.jsonl`에 전체 검색 범위·신호 수·최종 임계값을 추가 전용으로 기록한다.

### 5.4 G1b — 쌍 판정 (모델, 묶음 1개 = 호출 1회)

- **입력**: 묶음에 든 행들의 effective_task·task_card·직업·D/F, 그리고 판정할 쌍 목록.
- **모델이 하는 일**: 쌍마다 verdict 6종 중 하나와 근거 1문장. 묶음 안에서 목록에 없는 유사 쌍을 찾으면 added_pairs로 추가한다.
- **기준 질문**: "둘 중 하나를 제거해도 같은 핵심 업무 능력을 사실상 평가할 수 있는가?"
- **코드 검증**: 입력 쌍이 출력에 하나도 빠짐없이 한 번씩 있는가. 빠진 쌍만 모아 재호출한다.
- **출력**: `_work/g1/pairs.jsonl` (추가 전용).

### 5.5 G1c — 그룹 확정 (코드 + 필요하면 추가 호출)

1. EXACT·SEMANTIC·PARAMETER_VARIANT 쌍으로 연결 요소를 만든다.
2. 그룹마다 대표 행을 정한다. 순서는 P0 inspected → G0 job_fit=P → G0 P 개수 → 작은 source_row.
3. 대표와 구성원 사이에 직접 판정된 확정 중복 쌍이 있는지 확인한다. 없으면 그 쌍을 모아 G1b를 한 번 더 호출한 뒤 1로 돌아간다. 최대 2회를 돌고, 그래도 없으면 그 구성원은 REVIEW다.
4. 상태를 부여한다: 대표 UNIQUE, 제외 대상 DUPLICATE(대표 행·id 필수), 미판정 후보가 남은 행 REVIEW, Task 없는 행 NOT_EVALUATED.
5. overlap_status를 모든 행에 채운다: HIGH_OVERLAP 쌍이 있으면 HIGH_OVERLAP, 쌍이 있으나 모두 DISTINCT면 NONE, 미평가 행은 UNDETERMINED.

출력: `03_results/01_duplicate_audit.xlsx` (audit 열 + coverage 열).

### 5.6 G2 — Task 설계 품질 검수 (모델, 행 1개 = 호출 1회)

- **대상**: G0가 KEEP/REGENERATE이고 G1이 DUPLICATE가 아닌 행. 나머지는 코드가 SKIPPED(사유 포함)로 기록한다.
- **입력**: row_card + effective_task. G0 판정은 아래 모드에 따라 넣거나 뺀다.
- **독립성**: G0와 다른 호출이라 컨텍스트가 자동으로 분리된다. review_independence=SEPARATE_CALL로 기록한다.
- **겹치는 10개 지표 처리 (설정 G2_OVERLAP_MODE)**:
  - AGREE_CHECK(Work와 동일, 기본): REGENERATE 행은 G0 값을 넣지 않고 10개를 새로 판정한다. KEEP 행은 G0 값을 넣고 동의/이의만 받는다.
  - FULL_RECHECK: 모든 행에서 G0 값을 넣지 않고 16개 전부 새로 판정한다. 비용은 늘지만 독립성이 가장 높다.
- **모델이 하는 일**: 고유 6개 지표, b_coverage_status, reference_action·readiness, verify_status, Blueprint 4종, proposed_fix.
- **코드 검증**:
  - F가 있는데 PASS인가
  - GENERATE_REFERENCE인데 reference_action이 GENERATE가 아닌가
  - Blueprint에 수치·기관명을 창작한 흔적이 있는가 (row_card에 없는 숫자 패턴 검출 → 경고)
- **출력**: `_work/g2/records.jsonl`. G3에서 `03_results/02_task_verify.xlsx`.

### 5.7 G3 — 최종 판정·내보내기·검증 (코드)

1. **최종 판정**: 7.1 우선순위를 그대로 적용한다 (부록 C).
2. **16개 지표 확장**: status는 모델 값, criterion은 고정 사전(부록 A), evidence는 evidence_loc, conclusion은 R/F면 issues 문장, P면 "기준 충족 (G2 판정)".
3. `02_task_verify.xlsx`와 `03_final.jsonl`을 쓴다. JSONL은 원본 1행 = 객체 1개 = 1줄이다.
4. 검증(9장)을 돌리고 실패가 하나라도 있으면 run 상태를 FAILED_VALIDATION으로 둔다. 파일은 남기되 완료로 보고하지 않는다.
5. `_work/run_report.json`(요약·검증·비용)을 남기고 사람이 읽을 요약을 콘솔에 출력한다.
6. `04_sheet_paste.xlsx`는 DataList의 원래 열·값·행 순서를 유지하고, 헤더 이름으로 열을 찾아 `AI 판정`, `Regenerate Task`, `원본 Task(백업)`, `검수 메모`, `검수자`, `검수일시`만 채운다. `최종 판정`과 `태스크`는 수정하지 않는다. 검수 열이 없으면 지정 순서대로 오른쪽에 추가한다. 기본 설정 `OVERWRITE_EXISTING_REVIEW=false`에서는 검수 구간에 기존 값이 있는 행을 건너뛰고 run_report에 기록하며, true일 때만 위 6개 열을 덮어쓴다. 원본·결과 id의 행별 일치 여부와 기존 값 행 목록도 run_report에 기록한다.

---

## 6. LLM 호출 설계

호출은 작게, 서로 독립적으로, 동시에 보낸다. 모델 공급사에 종속되지 않도록 호출은 하나의 클라이언트 래퍼를 거친다. 래퍼가 재시도·사용량 기록·스키마 검증을 맡는다.

### 6.1 호출 단위와 설정

| 단계 | 호출 1회의 단위 | 추론 강도 (기본값) | 출력 상한 | 동시 호출 |
|---|---|---|---|---|
| G0 | 행 1개 | medium | 약 1,500 토큰 (추론 제외) | 10~20 |
| G0 재판정 | 검증에 걸린 행 1개 | high | 같음 | 5 |
| G1b | 쌍 묶음 1개 (≤ 40쌍, ≤ 20행) | high | 약 4,000 토큰 | 5~10 |
| G2 | 행 1개 | medium | 약 2,500 토큰 | 10~20 |

- 출력 상한과 동시 호출 수는 설정값이다. 실제 출력 길이를 보고 조정한다.
- 추론 강도는 단계별로 따로 설정한다. Work에서는 전체가 high 하나였다.
- G0를 medium으로 돌리되, 코드 검증에 걸리거나 REGENERATE·RESELECT_B·REVIEW_B가 나온 행만 high로 한 번 더 본다 (설정 G0_ESCALATE). 두 판정이 다르면 high 쪽을 채택하고 차이를 기록한다.

### 6.2 메시지 구성

한 호출은 세 부분으로 나뉜다. 앞의 두 부분은 모든 호출에서 글자 하나 다르지 않게 두어 프롬프트 캐시를 타게 한다.

1. **고정 지시 (캐시 대상)** — 역할, 판정 기준(해당 단계의 00_Work_Run.md 장 발췌), 절대 규칙, 출력 규칙(출력 다이어트), 직무 기준 경고.
2. **고정 출력 스키마** — structured outputs로 전달하는 JSON 스키마 (7장).
3. **가변 입력** — 그 행의 row_card(JSON), 단계에 따라 G0 판정, 재호출이면 직전 검증 실패 사유.

- 호출마다 현재 Task 이름이나 폴더 이름(예: accounting)을 넣지 않는다. 배치 04 같은 직무 기준 오판의 원인이 될 수 있기 때문이다.
- few-shot 예시는 넣지 않는 것을 기본으로 한다. 예시 문장을 베끼는 템플릿 판정을 유도할 수 있기 때문이다. 넣는다면 판정 형식을 보여주는 추상 예시 1개만 둔다.

### 6.3 구조화 출력과 스키마 검증

- 모든 판정 호출은 JSON 스키마 강제 모드로 보낸다. enum은 스키마의 enum으로 제한한다.
- 스키마로 막을 수 없는 규칙(예: F가 있으면 KEEP 금지)은 코드 검증이 맡는다.
- 검증 실패 시 재호출 메시지에 실패 항목을 구체적으로 적는다 (예: "job_evaluated가 'X'인데 이 행의 직업은 'Y'이다").

### 6.4 재시도·타임아웃·동시성

| 상황 | 처리 |
|---|---|
| 429(속도 제한), 5xx, 네트워크 오류 | 지수 백오프 + 무작위 지연, 최대 5회. 응답의 재시도 대기 시간이 있으면 따른다 |
| 타임아웃 | 호출당 기본 300초 (high는 600초). 초과 시 재시도 1회 |
| 스키마 파싱 실패·빈 응답·거절 | 재호출 1회. 또 실패하면 status=FAILED로 기록하고 사람 검토 목록에 올린다 |
| 코드 검증 실패 | 피드백을 붙여 재호출 1회 (6.3). 또 실패하면 판정을 REVIEW로 두고 사유를 남긴다 |
| 단계 전체 실패율 > 10% | 단계를 멈추고 보고한다 (프롬프트·입력 문제 가능성) |

- 동시 호출 수는 계정의 분당 요청 수·토큰 수 한도에 맞춘다. 래퍼가 분당 토큰을 세어 한도에 닿기 전에 속도를 줄인다.
- 모든 호출은 call_id = hash(단계, 단위 ID, 프롬프트 버전, 입력 해시)를 갖는다. 같은 call_id의 성공 기록이 있으면 다시 호출하지 않는다.

### 6.5 동기 호출 vs Batch API

| 모드 | 언제 | 장점 | 단점 |
|---|---|---|---|
| 동기 병렬 (`--mode online`, 기본) | 같은 날 결과가 필요할 때, 처음 돌리는 Task | 수십 분 안에 끝남. 실패를 바로 보고 고침 | Batch보다 비쌈 |
| Batch API (`--mode batch`) | 밤새 돌려도 되는 반복 실행, 대량 재평가 | 보통 더 저렴 | 결과까지 수 시간 걸릴 수 있음. 단계 사이 대기가 길어짐 |

- G1a·G1c·G3는 코드라 두 모드가 같다. Batch 모드는 G0 제출 → 완료 대기 → G1a → G1b 제출 → … 순서로 단계마다 한 번 기다린다.
- Batch API의 할인율·처리 시간·지원 기능(구조화 출력, 추론 강도)은 사용할 시점의 공식 문서로 확인한다.

### 6.6 Deliverable 파일 열람 방식

Work에서는 모델이 필요할 때 원본 파일을 직접 열었고, 그 덕분에 점수 범주 불일치 같은 문제를 찾았다. API에서는 세 가지 방식이 가능하다.

| 방식 | 내용 | 장점 | 단점 |
|---|---|---|---|
| A. 프로필만 | P0가 만든 file_profile만 입력 | 단순, 빠름, 저렴 | 프로필에 없는 세부는 못 봄 |
| B. 프로필 + 열람 도구 (권장) | 프로필을 넣고, 모델이 필요하면 read_sheet(시트·행 범위), read_pages(PDF 페이지) 도구를 부르게 함 | Work에 가장 가까움. 필요한 행만 비용이 늘어남 | 호출이 여러 턴이 됨. 구현이 가장 복잡함 |
| C. 원본 첨부 | PDF 등을 파일 입력으로 직접 첨부 | 정보 손실 없음 | 큰 파일은 비용이 크고 한도를 넘을 수 있음. CSV 40MB급은 불가 |

- 권장은 B다. 도구 호출은 행당 최대 3회, 호출당 반환 최대 8,000자로 제한한다.
- 도구를 쓴 행은 evidence_loc에 열람 위치를 남기고, 사용량을 따로 집계한다.
- 1차 구현은 A로 시작하고, Work 결과와 비교해 불일치가 프로필 부족 때문일 때 B를 붙이는 순서도 가능하다 (13장).

---

## 7. 데이터 계약

모든 중간 레코드는 (source_sheet, source_row)와 id로 식별하고, UTF-8 JSONL로 추가만 한다. 최종 JSONL은 06_Result_Schema.md(canonical-1.0)를 그대로 따른다.

### 7.1 row_card (P0 → G0·G2 입력)

| 필드 | 출처 | 비고 |
|---|---|---|
| source_row, id | 엑셀 물리 행 번호, B열 | 식별자 |
| job | C열 전체 경로 | 예: 통계‧데이터 관련 사무원:…:통계 및 설문 조사 사무원 |
| job_leaf | C열 마지막 직업명 | job_evaluated 대조 기준 |
| deliverable_title, format | D열, F열 | |
| expected_filename, match_status, inspected | P0 | |
| reference_mode, reference_note | P0, E열 원문 | |
| original_task | G열 원문 | 수정 금지 |
| jobinfo | I열 캐시값 | 평균 약 1,100자 |
| file_profile | P0 | 최대 1,500자, 관찰 위치 포함 |

O열(개인 태깅)·L·M열은 row_card에 넣지 않는다. 모델이 볼 수 없으니 판단에 쓸 수도 없다.

### 7.2 단계별 모델 출력 스키마

| 단계 | 필수 필드 | 선택 필드 |
|---|---|---|
| G0 | job_evaluated, action(4종), checks(10개 차원 → P/R/F/NA), reason, evidence_loc, expected_reference_spec | regenerated_task_new(REGENERATE일 때 필수), issues(R/F 차원만), task_card(KEEP·REGENERATE일 때 필수) |
| task_card | input, operations[], criteria[], output | — |
| G1b | pairs[]: row_1, row_2, verdict(6종), evidence | conclusion(DISTINCT 아닐 때), added_pairs[] |
| G2 | verify_status(PASS/REVIEW/FAIL), overlap_review{mode, checks(10개), disagree}, new_checks(6개), b_coverage_status, reference_action, reference_readiness, blueprints{scenario, reference, reasoning_map, evaluation}, reason, evidence_loc | issues, proposed_fix(R/F일 때) |

- 모든 텍스트 필드에 길이 상한을 둔다 (예: reason ≤ 300자, issues 항목당 ≤ 200자). 출력 다이어트를 스키마로 강제하기 위해서다.
- criterion 필드는 모델 출력에 없다. G3가 고정 사전에서 채운다.

### 7.3 호출 기록 (`_work/calls.jsonl`)

호출마다 한 줄을 추가한다. 비용 집계·재개·디버깅이 모두 이 파일에서 나온다.

| 필드 | 내용 |
|---|---|
| run_id, call_id, stage, unit_id, attempt | 실행·호출 식별. unit_id = source_row 또는 묶음 ID |
| model, reasoning_effort, prompt_version, schema_version | 재현용 |
| input_hash | row_card 등 가변 입력의 해시 |
| started_at, ended_at, latency_ms | 시간 |
| usage.input, usage.cached_input, usage.output, usage.reasoning | API가 돌려준 실측값 |
| cost_usd | 실측 토큰 × 설정 단가 |
| status | OK / RETRIED / SCHEMA_FAIL / VALIDATION_FAIL / FAILED |
| validation_errors[] | 코드 검증에서 걸린 항목 |
| tool_calls | 열람 도구 사용 횟수·위치 (6.6 B방식) |

응답 원문은 `_work/raw/<call_id>.json`으로 따로 보관한다. 판정 레코드(g0/records.jsonl 등)는 검증을 통과한 파싱 결과만 담는다.

### 7.4 최종 JSONL (`03_final.jsonl`)

- 최상위 키: schema_version, dataset, source_file, source_sheet, source_row, id, source, source_assets, revision, duplicate, verify, final (06 스키마 그대로).
- source.cells: A열~마지막 열을 열 문자 키로, {header, value, formula, hyperlink}.
- duplicate: 06의 모든 필드 + candidate_pairs[](상대 행, 신호, 유사도, verdict, 근거). overlap_status는 null 금지.
- final.execution_notes: "API 파이프라인", run_id, 단계별 모델·추론 강도, 프롬프트 버전, G2_OVERLAP_MODE, review_independence.
- decided_by: 각 Gate 객체에 MODEL / RULE / HUMAN을 둔다. 코드가 규칙으로 정한 판정(예: NOT_FOUND → REVIEW_B, DUPLICATE → G2 SKIPPED)과 모델 판정을 구분하기 위해서다. 06 스키마에 없는 추가 필드다 (03_final.jsonl은 기록·Work 비교용이라 외부 도구 호환 확인은 하지 않는다, 2026-10-22 정정).

### 7.5 enum 사전

| 필드 | 허용값 |
|---|---|
| match_status | MATCHED, AMBIGUOUS, CONFLICT, NOT_FOUND, INACCESSIBLE, INVENTORY_INCOMPLETE |
| reference_mode | GENERATE_REFERENCE, PROVIDED_REFERENCE, UNRESOLVED_REFERENCE |
| revision.action | KEEP, REGENERATE, REVIEW_B, RESELECT_B |
| pair_verdict | EXACT, SEMANTIC, PARAMETER_VARIANT, HIGH_OVERLAP, DISTINCT, UNCERTAIN |
| duplicate.status | UNIQUE, DUPLICATE, REVIEW, NOT_EVALUATED |
| duplicate_type | EXACT, SEMANTIC, PARAMETER_VARIANT, EXPRESSION_ONLY, NONE, UNDETERMINED |
| overlap_status | NONE, LOW_OVERLAP, HIGH_OVERLAP, UNDETERMINED |
| verify.status | PASS, REVIEW, FAIL, SKIPPED |
| b_coverage_status | SUFFICIENT, PARTIAL_NONCRITICAL, PARTIAL_CRITICAL, MISSING |
| reference_action | GENERATE, REUSE, SUPPLEMENT, ADAPT, REPLACE, CHECK_ACCESS |
| reference_readiness | BLUEPRINT_READY, READY_AS_IS, READY_WITH_ACTION, HOLD |
| final.status | PASS, REVIEW, FAIL |
| next_action | HANDOFF_TO_AI_TEAM, EXCLUDE_DUPLICATE, REVISE_TASK, RESELECT_DELIVERABLE, CHECK_ASSETS, CHECK_DUPLICATE, REVIEW_MANUAL |
| 지표 상태(모델 출력) | P, R, F, NA → G3에서 PASS, REVIEW, FAIL, N_A로 변환 |

KSCO-34 첫 실행에서 나온 DESIGNABLE처럼 사전에 없는 값은 스키마 단계에서 막히고, G3 검증에서 한 번 더 확인한다.

---

## 8. 프롬프트 관리

프롬프트는 코드와 같은 저장소에서 버전을 붙여 관리하고, 버전이 바뀌면 이전 호출 결과를 재사용하지 않는다.

### 8.1 구성

| 파일 | 내용 | 쓰는 곳 |
|---|---|---|
| criteria/00_Work_Run.md, criteria/06_Result_Schema.md | 판정 기준 원문 (수정하지 않음) | 발췌의 원천 |
| prompts/common.md | 역할, 절대 규칙, 출력 다이어트, 직무 기준 경고 | G0·G1b·G2 공통 앞부분 |
| prompts/g0.md | 4장 발췌 + 행 단위 지시 | G0 |
| prompts/g1b.md | 5.2 발췌 + 쌍 단위 지시 | G1b |
| prompts/g2.md | 6장 발췌 + 겹치는 지표 처리 모드별 지시 | G2 |
| schemas/g0.json, g1b.json, g2.json | 출력 JSON 스키마 | structured outputs |
| dictionaries/criteria.yaml | 16개 지표 criterion 고정 문장 (부록 A) | G3 |
| dictionaries/enums.yaml | enum 사전 (7.5) | 스키마 생성·G3 검증 |

- Work 분할본의 S2_G0_Batch.md 등은 "배치를 열고 저장하라"는 실행 지시가 섞여 있다. API 프롬프트는 판정 지시만 남기고, 파일·배치·저장 이야기는 뺀다.
- 발췌는 원문을 그대로 자른다. 요약하거나 다시 쓰면 기준이 말없이 바뀔 수 있다.

### 8.2 버전 관리

- prompt_version = 단계 프롬프트 + common + 스키마 + 기준 발췌를 합친 텍스트의 해시이다. 사람이 붙이는 버전 이름(예: g0-v1.2)도 함께 남긴다.
- 해시가 바뀌면 call_id도 바뀌므로 해당 단계는 새로 호출된다. 앞 단계 결과는 그대로 쓴다.
- 하류 단계는 상류 결과 해시도 입력에 포함한다. 예를 들어 G0가 다시 돌면 G1·G2도 다시 돈다.

### 8.3 변경 절차

1. 문제를 발견한다 (예: Work와 비교했을 때 특정 유형에서 판정이 다름).
2. 프롬프트를 고친다. 판정 기준 자체를 바꾸는 변경은 00_Work_Run.md를 먼저 고치고 팀에 공유한다.
3. 고정 평가셋(9.3, 약 60행)으로 돌려 이전 버전과 비교한다.
4. 변경 내용·평가 결과를 prompts/CHANGELOG.md에 남기고 반영한다.

평가셋 없이 프롬프트를 바꾸면, 한 유형을 고치다가 다른 유형을 망칠 수 있다. 그래서 이 절차는 생략하지 않는다.

---

## 9. 품질 보증

품질은 세 겹으로 확인한다. 호출마다 코드 검사, 실행마다 사람의 샘플 검토, 프롬프트·모델을 바꿀 때마다 고정 평가셋 비교다.

### 9.1 자동 검사

| 시점 | 검사 | 실패 시 |
|---|---|---|
| P0 | 헤더 일치, id 누락·중복, 데이터 행 수, NOT_FOUND 비율 | 실행 중단 |
| G0 호출마다 | job_evaluated 대조, F+KEEP 모순, REGENERATE 새 Task 여부·원본과 다름, 차원별 issues 복사 | 피드백 재호출 1회 → REVIEW |
| G0 단계 끝 | 같은 reason 문장 3회 이상 반복, 직업별 action 분포 이상 (한 직업에서만 RESELECT_B·REVIEW_B ≥ 50%) | 해당 행 high 재판정 + 보고 |
| G1a | 신호별 쌍 수, 행당 후보 수 분포, 상한 초과 | 임계값 조정 후 재생성 |
| G1b 호출마다 | 입력 쌍 전부 1회씩 판정 | 빠진 쌍 재호출 |
| G1c | 대표-구성원 직접 판정 존재, DUPLICATE의 대표 행 존재 | 추가 호출 → REVIEW |
| G2 호출마다 | F+PASS 모순, reference_mode와 action 정합, Blueprint에 row_card에 없는 수치 | 재호출 1회 / 경고 |
| G3 | 06 최소 검증 1~10, 5개 파일 행 수 일치, enum 검사, 전 행 null 필드, source.cells와 원본 대조, 템플릿 감지(같은 문장 10행 이상) | FAILED_VALIDATION |

### 9.2 사람 검토 샘플링

모든 행을 사람이 볼 수는 없으므로, 틀릴 가능성이 큰 곳과 무작위 표본을 함께 본다. G3가 검토 목록을 `_work/review_queue.csv`로 만든다.

| 대상 | 비율 | 이유 |
|---|---|---|
| RESELECT_B, G2 FAIL | 전체 | 건수가 적고, 판정 오류 시 데이터가 빠짐 |
| 자동 검사에서 재판정·REVIEW로 떨어진 행 | 전체 | 모델이 두 번 문제를 낸 행 |
| REGENERATE | 20% (최소 10행) | 새 Task가 사실을 창작하지 않았는지 |
| DUPLICATE 그룹 | 그룹의 20% (최소 5그룹) | 과도한 중복 제외 여부. accounting은 105행이 제외됨 |
| 최종 PASS | 무작위 20행 | 너그러운 통과 여부 |

검토자는 각 행에 동의 / 불동의 / 판단 불가와 한 줄 사유를 남긴다. 불동의는 decided_by=HUMAN으로 판정을 덮는 별도 파일(`_work/overrides.jsonl`)로 반영하고, G3를 다시 돌린다. 모델 호출은 다시 하지 않는다.

### 9.3 Work 결과와의 일치도 + 고정 평가셋

첫 검증 (M5): accounting(398행) 전체를 API로 돌려 Work 결과와 비교한다.

| 지표 | 비교 대상 | 제안 목표치 |
|---|---|---|
| G0 action 일치율 / Cohen's kappa | 398행 | 일치율 ≥ 80% |
| G1 확정 중복 쌍 일치 (양방향) | 두 결과의 DUPLICATE 쌍 | 차이나는 쌍 전부 사유 확인 |
| G2 verify_status 일치율 | 양쪽 모두 평가한 행 | ≥ 75% |
| 최종 status 일치율 | 398행 | ≥ 80% |

- 목표치는 제안값이다. Work 결과도 정답이 아니므로, 일치율보다 불일치 사유의 분류가 더 중요하다.
- 불일치 행은 모두 네 가지로 분류한다: API 맞음 / Work 맞음 / 둘 다 가능(기준 모호) / 둘 다 틀림. Work 맞음이 많은 유형은 프롬프트나 파일 프로필을 고친다. 기준 모호는 00_Work_Run.md 보완 후보로 올린다.
- Work 결과 중 알려진 오류(배치 04 재처리 전 값)는 비교에서 최종값만 쓴다.

고정 평가셋: 첫 검증에서 사람이 판정을 확정한 약 60행을 고른다. 유형별로 골고루 포함한다.

- 직업 5종 각각
- 파일 형식 CSV·XLSX·PDF·HWPX
- REGENERATE, RESELECT_B, REVIEW_B 사례
- 통계연보처럼 지역만 다른 중복 그룹 2~3개
- 배치 04의 통계‧데이터 사무원 행 (직무 기준 오판 재발 감시용)

프롬프트·모델·추론 강도를 바꿀 때마다 이 60행으로 돌려 일치율을 비교한다. 비용은 전체 실행의 약 15%다.

---

## 10. 운영 설계

한 Task는 명령 하나로 끝까지 돈다. 중간에 멈추면 같은 명령을 다시 실행해 이어 간다.

### 10.1 실행 모드

| 모드 | 하는 일 | 쓰는 때 |
|---|---|---|
| estimate | P0만 실행하고 호출 수·예상 토큰·예상 비용을 출력. 모델 호출 없음 | 새 Task를 돌리기 전 예산 확인 |
| sample N | 무작위 N행으로 전 단계를 실행 (별도 run) | 프롬프트·설정 시험, 새 Task 첫 확인 |
| run (기본) | P0 → G3 전체. 끝난 호출은 건너뜀 | 본 실행, 중단 후 재개 |
| run --stage G2 | 지정 단계부터 끝까지 | 프롬프트 수정 후 하류만 다시 |
| rerun-failed | status가 FAILED·VALIDATION_FAIL인 호출만 다시 | 일시 오류 후 |
| export | G3만 다시 (모델 호출 없음) | 사람 검토 overrides 반영, 스키마 수정 |
| compare --with <폴더> | 두 결과의 일치도 리포트 (9.3) | Work 비교, 버전 간 비교 |
| --mode batch | 모델 호출을 Batch API로 제출하고 완료를 기다림 | 비용 절감이 필요한 반복 실행 |

### 10.2 설정

Task 폴더의 task_config(없으면 기본값)와 전역 설정 파일을 합친다. 확정된 값은 run 폴더에 저장해 나중에 재현할 수 있게 한다.

| 키 | 기본값 | 설명 |
|---|---|---|
| MODEL_G0, MODEL_G1B, MODEL_G2 | (결정 필요) | 단계별 모델 ID |
| EFFORT_G0, EFFORT_G1B, EFFORT_G2 | medium, high, medium | 추론 강도 |
| G0_ESCALATE | on | 검증 실패·비KEEP 행을 high로 재판정 |
| G2_OVERLAP_MODE | AGREE_CHECK | AGREE_CHECK / FULL_RECHECK |
| FILE_ACCESS | profile | profile / profile+tools |
| CONCURRENCY | 10 | 동시 호출 수 |
| G1_TARGET_CANDS, G1_PAIRS_PER_CALL | 3~8, 40 | 후보 규모, 묶음 크기 |
| NOT_FOUND_STOP_RATIO | 0.30 | P0 중단 기준 |
| PRICE_* | (결정 필요) | 입력·캐시 입력·출력 단가 (USD / 1M 토큰) |
| BUDGET_USD | (선택) | 누적 비용이 이 값을 넘으면 멈춤 |

API 키는 환경 변수로만 받는다. 설정 파일·로그·산출물에 쓰지 않는다.

### 10.3 재개·재실행

- run은 run_id(시각 + 설정 해시)로 구분한다. 같은 설정으로 다시 실행하면 같은 run을 이어 간다.
- 재개는 calls.jsonl의 성공 기록을 기준으로 한다. 파일 존재나 진행 파일을 믿지 않는다.
- 프로세스가 중간에 죽어도 기록은 한 줄씩 추가되므로 잃는 것은 진행 중이던 호출뿐이다.

### 10.4 로깅·진행 표시·비용

- 콘솔: 단계별 진행률(완료/전체), 실패 수, 누적 비용, 예상 남은 시간을 한 줄로 갱신한다.
- 단계 끝마다 요약을 출력한다. 예: `G0 완료 — KEEP 327 / REGEN 50 / REVIEW_B 20 / RESELECT_B 1 · 재판정 34 · 입력 1.9M · 출력 0.6M · $x.xx`
- 비용은 calls.jsonl의 실측 usage로만 계산한다. 캐시 입력과 추론 토큰을 따로 보여준다.
- run_report.json과 콘솔 최종 보고에 단계별·전체 토큰, 비용, 시간, 행당·쌍당 평균을 남긴다. Work에서 남기지 못했던 값이다.

### 10.5 산출물 정리

- 최종 산출물 5개만 `03_results/`에 둔다. 나머지는 모두 run 폴더 안에 둔다.
- run 폴더는 지우지 않고 보관한다. 비교·감사에 쓰고, 용량이 문제면 `raw/`만 압축한다.

---

## 11. 비용·시간 추정

accounting(398행) 기준으로 호출 약 730회, 입력 약 5.7M·출력 약 2.4M 토큰, 소요 약 1~1.5시간으로 추정한다. 아래는 실측 전 추정이다. estimate 모드와 sample 30 실행으로 실제 값을 잡은 뒤 다시 계산한다.

### 11.1 산식

```
cost = T_in(uncached) · P_in + T_in(cached) · P_cache + (T_out + T_reasoning) · P_out
```

- 단가 P는 1M 토큰당 USD다. 추론 토큰은 출력 단가로 과금되는 것이 일반적이다.
- 고정 지시·스키마가 입력의 절반 정도라, 캐시가 적용되면 입력의 약 55%가 캐시 단가로 계산된다고 가정한다.

### 11.2 단계별 추정 (accounting 398행)

| 단계 | 호출 수 | 호출당 입력 | 호출당 출력+추론 | 입력 합계 | 출력 합계 | 소요 (동시 10) |
|---|---|---|---|---|---|---|
| P0 (코드) | 0 | — | — | — | — | 5~10분 (대용량 CSV 프로필) |
| G0 | 379 | 약 7k | 약 2.3k | 2.65M | 0.87M | 약 30분 |
| G0 재판정 (high, 약 15%) | 60 | 약 7k | 약 4.8k | 0.42M | 0.29M | 약 15분 |
| G1b | 20 (약 800쌍) | 약 14k | 약 8.4k | 0.28M | 0.17M | 약 10분 |
| G2 | 272 | 약 8.5k | 약 3.8k | 2.31M | 1.03M | 약 30분 |
| 합계 | 약 730 | | | 약 5.7M | 약 2.4M | 약 1~1.5시간 |

가정: G0 대상은 inspected 행(398 − 자동 REVIEW_B 19), G2 대상은 Work 결과 기준 SKIPPED 126행을 뺀 행, G1 후보는 행당 평균 약 4개, 호출당 지연 30~120초.

### 11.3 단가에 따른 비용

| 단가 가정 (입력 / 캐시 / 출력, USD per 1M) | accounting 1회 비용 | 비고 |
|---|---|---|
| 0.10 / 0.01 / 0.50 | 약 $1.5 | Artificial Analysis에 게시된 GPT-6 Luna (high) 단가 기준. 실제 요금제 확인 필요 |
| 2.00 / 0.20 / 8.00 | 약 $25 | 가상 단가. 고성능 모델을 쓸 경우의 크기 감 |

- 비용의 대부분은 출력·추론 토큰에서 나온다. 출력 다이어트와 단계별 추론 강도가 가장 큰 절감 수단이다.
- G2_OVERLAP_MODE=FULL_RECHECK이면 G2 출력이 약 30% 늘어난다고 본다.
- FILE_ACCESS=profile+tools이면 도구를 쓴 행만 입력이 호출당 최대 약 6k 늘어난다.
- Batch API를 쓰면 보통 더 저렴하다. 할인율은 사용 시점에 확인한다.

참고로 Work 실행은 accounting 하나에 약 3시간(15:00~18:00, 대화 여러 개)이 걸렸고, 토큰은 실측하지 못했다.

---

## 12. 리스크와 대응

가장 큰 리스크는 "파일 프로필만으로는 Work만큼 깊게 보지 못하는 것"과 "행 단위 분리로 G1의 의미 탐색이 약해지는 것"이다. 둘 다 9.3의 Work 비교로 크기를 재고 대응한다.

| 리스크 | 영향 | 가능성 | 대응 |
|---|---|---|---|
| 파일 프로필이 얇아 판정이 피상적이 됨 (점수 범주 불일치 같은 세부를 놓침) | 높음 | 중간 | 부록 B대로 앞·중간·끝 샘플과 범주 값 목록을 넣음. 부족하면 열람 도구(6.6 B) 추가 |
| G1 후보를 코드로만 만들어 표현이 다른 의미 중복을 놓침 | 중간 | 중간 | task_card 임베딩 신호 추가, 묶음 안 added_pairs. Work의 중복 105행과 비교 |
| 폴더·Task 이름 등 바깥 맥락에 끌려 직무 기준 오판 (배치 04 유형) | 높음 | 낮음 | 호출에 Task 이름을 넣지 않음, job_evaluated 대조, 직업별 분포 이상 검사 |
| 모델 버전 교체로 판정 경향이 바뀜 | 중간 | 중간 | 모델 ID를 날짜 고정형으로 지정, 변경 시 고정 평가셋 재실행 |
| 구조화 출력을 지키지만 내용이 빈약함 (짧은 형식적 사유) | 중간 | 중간 | 사유에 관찰 위치·직업명 포함 요구, 템플릿 감지, 사람 샘플 검토 |
| 대용량 CSV(수십 MB)·HWP 등 프로필 단계 실패 | 낮음 | 높음 | 스트리밍 읽기, 형식별 파서, 실패 시 NOT_INSPECTED로 기록하고 진행 |
| 속도 제한·장애로 실행이 길어짐 | 낮음 | 중간 | 백오프 재시도, 재개, 동시 호출 수 자동 조절 |
| 비용 초과 | 낮음 | 낮음 | estimate 모드로 사전 산정, BUDGET_USD 상한에서 멈춤 |
| DataList에 붙여 넣을 결과 형식이 기존 열과 다름 (R=AI 판정, T=Regenerate Task 등) | 중간 | 중간 | 04_sheet_paste.xlsx를 KSCO-28 DataList R·T열 값 형식에 맞추고 M1 게이트에서 확인 (2026-10-22 정정: 검수 툴이 JSONL을 읽는 연동은 없음) |
| 공공데이터지만 외부 API로 전송됨 (보안 정책) | 중간 | 낮음 | 회사의 외부 LLM API 사용 정책 확인. 비식별화 필(N열) 행은 전송 전 확인 |
| Work 결과를 정답처럼 쓰다 Work의 오류를 따라감 | 중간 | 중간 | 불일치는 분류만 하고, 정답은 사람이 확정한 고정 평가셋으로만 정함 |

---

## 13. 구현 계획

결정적 코드(M1)를 먼저 만들고, 모델 호출은 G0 → G1 → G2 순서로 붙인다. M1은 Work 결과를 입력으로 쓸 수 있어 모델 없이도 검증된다.

> M4에서 accounting을 완주하고 M5에서 Work와 비교해 전환을 결정한다.

| 단계 | 내용 | 게이트 |
|---|---|---|
| M0 준비 | 모델·단가·파일 열람 방식 등 14장 결정 사항 확정, 고정 평가셋 후보 60행 선정, 실행 환경 준비 | 결정 사항 전부 확정 |
| M1 결정적 코드 | P0 매핑·파일 프로필·row_card, G3 판정·내보내기·검증. Work 결과는 DataList R~V열 판정뿐이라 입력으로 쓸 수 없어, 가상 단계 기록(G0·G1·G2)으로 mock run을 끝까지 돌린다 | mock run 산출물 + 06 최소 검증 10항목 통과 + 04_sheet_paste.xlsx가 DataList 기존 열(AI 판정, Regenerate Task 등)과 같은 형식 (2026-10-22 재정의) |
| M2 호출 기반 + G0 | 클라이언트 래퍼·재시도·호출 기록·재개, G0 프롬프트. sample 30으로 G0 실행, 사람이 판정 검토 | 직무 기준 오판·템플릿 판정 0건 |
| M3 G1 중복 검수 | 후보 생성·묶음·쌍 판정·그룹 확정. Work의 중복 제외 105행과 비교 | 행당 후보 3~8개, 차이 나는 쌍 전부 설명 |
| M4 G2 + 전체 연결 | G2 프롬프트, P0~G3를 한 번의 run으로 연결. accounting 398행 1회 완주, 비용·시간 실측 | 명령 한 번으로 완주, 검증 통과 |
| M5 Work 비교 검증 | 일치도 측정, 불일치 4분류, 프롬프트·프로필 개선. 고정 평가셋 60행 판정 확정 | 제안 목표치 충족 또는 차이 사유 문서화 |
| M6 운영화 | finpro 등 두 번째 Task 적용, Batch 모드. 운영 가이드, 프롬프트 변경 절차 정착 | 두 번째 Task 완주 |

구현 마일스톤 · 7단계, 단계마다 게이트 1개. 각 단계는 게이트를 통과해야 다음으로 넘어간다. API로 전환할지는 M5 결과로 결정한다.

| 단계 | 주요 산출물 | 예상 공수 (1인 기준, 추정) |
|---|---|---|
| M0 준비 | 14장 결정 기록, 평가셋 후보 목록 | 1일 |
| M1 결정적 코드 | P0·프로필·G3 모듈, enum·criterion 사전, 검증 스위트 | 3~4일 |
| M2 호출 기반 + G0 | 클라이언트 래퍼, calls.jsonl, G0 프롬프트·스키마·검증 | 3일 |
| M3 G1 | 후보 생성·묶음·그룹 확정 모듈, G1b 프롬프트 | 2~3일 |
| M4 G2 + 연결 | G2 프롬프트, 실행 모드 8종, run_report | 2일 |
| M5 비교 검증 | 일치도 리포트, 불일치 분류표, 고정 평가셋 | 3일 (사람 검토 포함) |
| M6 운영화 | 두 번째 Task 결과, 운영 가이드 | 2일 |

합계는 약 16~18일이다. 튜닝 반복 횟수에 따라 M5가 가장 크게 달라질 수 있다. M1과 M2는 두 사람이 나눠 동시에 진행할 수 있다.

---

## 14. 결정이 필요한 사항

M0에서 아래 9가지를 정해야 구현을 시작할 수 있다. 제안안은 이 문서의 기본값이다.

| # | 결정 사항 | 선택지 | 제안안 | 영향 |
|---|---|---|---|---|
| 1 | 모델과 요금제 | Work에서 쓴 GPT Luna 계열 / 다른 모델 | Work와 같은 계열 (비교가 쉬움) | 비용(11장), 비교 가능성 |
| 2 | 파일 열람 방식 | 프로필만 / 프로필+도구 / 원본 첨부 | 1차 프로필만 → M5 결과 보고 도구 추가 | 품질, 구현 난도 |
| 3 | G2 겹치는 10개 지표 | AGREE_CHECK / FULL_RECHECK | AGREE_CHECK (Work와 동일) | 비용 약 30%, 독립성 |
| 4 | E열 Reference 해석 규칙 | 셀에 파일명 / 링크 / 자유 텍스트 중 무엇을 PROVIDED로 볼지 | 비어 있으면 GENERATE, 그 외는 UNRESOLVED로 두고 사람 확인 | accounting은 전부 비어 있었음 |
| 5 | id 누락 정책 | 실행 중단 / source_row를 열쇠로 진행 | 중단 (시트에서 값으로 채운 뒤 다시) | 결과를 시트에 붙일 때 안전성 |
| 6 | 실행 환경 | 개인 PC / 사내 서버 | 개인 PC에서 시작, 정착 후 서버 | Deliverable 파일 접근, 장시간 실행 |
| 7 | 외부 API 전송 승인 | 회사 정책 확인 필요 | M0에서 확인 | 시작 가능 여부 |
| 8 | ~~Apps Script 연동~~ → 시트 반영 형식 | (2026-10-22 정정) 파이프라인이 검수 툴 판정을 대체하므로 JSONL 연동은 없음. DataList 기존 열에 붙여 넣을 04_sheet_paste.xlsx 형식으로 대신 | KSCO-28 DataList R·T열 값 기준 | 시트 반영 방식 |
| 9 | 동기 vs Batch API 기본값 | online / batch | online (처음에는 실패를 바로 봐야 함) | 비용, 대기 시간 |

---

## 15. 부록

### A. 16개 지표 criterion 고정 사전

G3가 verify.checks와 g0_self_check의 criterion을 이 문장으로 채운다. 앞의 10개는 G0와 G2가 함께 쓴다.

| 지표 | 단계 | criterion |
|---|---|---|
| job_fit | G0·G2 | 해당 직업의 직무 범위에서 수행 가능한 업무여야 함 |
| deliverable_fit | G0·G2 | Deliverable의 목적·필수 표/섹션·파일 형식과 결과 요구가 부합해야 함 |
| grounding | G0·G2 | 근거 없는 결과항목·기간·기관·업무 규칙을 추가하지 않아야 함 |
| input_contract | G0·G2 | 최종 Agent에 제공될 Reference의 최소 종류·필드를 정의할 수 있어야 함 |
| reasoning_validity / reasoning_requirement | G0 / G2 | 필요한 집계·계산·대조·규정 적용·판단 규칙을 식별할 수 있어야 함 |
| reconstructability | G0·G2 | 합리적 입력을 전제할 때 출력의 핵심 구조를 생성할 수 있어야 함 |
| no_answer_leakage / answer_leakage | G0 / G2 | Deliverable의 정답 수치·결론이 Task·입력에 유출되지 않아야 함 |
| no_external_search | G0·G2 | 최종 Agent에게 외부 정보 검색을 요구하지 않아야 함 |
| reference_burden | G0·G2 | 향후 Reference 준비 규모·난이도가 설명 가능하고 실현 가능해야 함 |
| output_specification | G0·G2 | 출력 형식과 확인 가능한 구조가 충분히 명시되어야 함 |
| task_clarity | G2 | 요청 목적·대상 범위·핵심 처리·결과 요구가 모호하지 않아야 함 |
| agentic_value | G2 | 단순 복사가 아닌 다단계 자료 처리·판단·구성을 요구해야 함 |
| difficulty_fit | G2 | 난이도가 필요한 처리·판단 능력과 균형을 이루어야 함 (길이로 판단하지 않음) |
| scenario_feasibility | G2 | 사건·수치를 창작하지 않고 현실적 업무 맥락·범위를 구성할 수 있어야 함 |
| reference_design_feasibility | G2 | Reference의 파일 유형·최소 필드·단위·범위·예외를 설계할 수 있어야 함 |
| evaluation_alignment | G2 | 수행 결과를 Deliverable과 객관적으로 대조·검산할 수 있어야 함 |

### B. 파일 형식별 프로필 규칙

accounting의 형식 분포는 CSV 240, XLSX 124, PDF 19, HWPX 9, XLS 2, ODT 2, PPTX 1, HWP 1이었다. 프로필은 행당 1,500자(설정 PROFILE_MAX_CHARS, 기본 1,500) 이내로, 관찰 위치를 반드시 포함한다. 관찰 위치에는 프로필에 실제로 담은 범위만 적는다 (예: "문단 1-15 (각 80자)", "표1-5 머리글·행 라벨·앞 2행", "p1-2 상세"). 읽기만 하고 담지 않은 범위를 "전체"로 적지 않는다 (문서형·PDF·PPTX, 2026-10-21).

| 형식 | 담는 내용 | 주의 |
|---|---|---|
| CSV | 인코딩, 열 수·헤더, 데이터 행 수, 앞·중간·끝 샘플 각 3행, 범주형 열의 고유값 목록(최대 20개), 숫자 열의 최소·최대, 합계·소계 행 여부 | UTF-8 → CP949 순서로 시도. 수십 MB 파일은 스트리밍으로 행 수만 세고 샘플만 읽음 |
| XLSX·XLS·ODS | 시트 목록, 시트별 사용 범위, 머리글 영역(병합 셀 포함), 수식·합계 열, 앞·끝 샘플 | 머리글이 여러 행인 통계표가 많음. 수식은 캐시값과 원문을 모두 확인 |
| PDF | 쪽 수, 텍스트가 거의 없는 쪽 비율(스캔 여부). "행 4 이하·열 2 이하", "1열", "1행(칸 절반 이상이 숫자면 예외)" 표는 레이아웃 칸으로 표에서 빼되 글자는 쪽 텍스트에 남기고 "레이아웃 칸 N개 제외"로 적음. 쪽마다 한 줄 "pN: 첫 줄(제목) · 표k R×C · 머리글: …"(표 크기는 한 번만). 첫 줄이 머리글 줄(앞 쪽 표의 머리글과 같거나 제목 없이 바로 표 시작)이면 "(pM 표 이어짐)". 상세 쪽 = 셀 수(행×열)가 큰 표가 있는 쪽부터, 표가 이어진 쪽은 뒤로(표가 없으면 앞·중간·끝). 상세 쪽은 표 크기·머리글(전체), 첫 5줄(각 80자)·금액 범위·합계·계·소계 줄 유무·단위·기준일, 표의 행 라벨(최대 15개)·데이터 앞 2행 | pdfplumber로 텍스트·표 추출(2026-10-21, pymupdf·pypdf 대체). 1,500자 초과 시 상세 쪽 밖 표 머리글 앞 3칸("…+N칸") → 데이터 행 2→1 → 첫 줄 5→3→1 → 행 라벨 15→8 → 상세 쪽 수(맨 마지막). 쪽 수·표 개수·크기·쪽 위치·상세 쪽 표 머리글·관찰 위치는 줄이지 않음 |
| HWPX·DOCX·ODT | 문서 제목(스타일상 제목 또는 첫 문단), 본문 문단을 순서대로 앞 80자. 레이아웃 칸(1열 표 또는 1행 표 — 1행 표라도 칸 절반 이상이 숫자면 데이터 표, 2열 이상 여러 행 표는 데이터 표)은 표에서 빼고 글자를 문단 흐름에 남기며 "레이아웃 칸 N개 제외"로 적음. 상세 표 = 셀 수(행×열)가 큰 표부터: 위치(몇 번째 문단 다음)·크기·병합 여부·제목 행·머리글·행 라벨(최대 15개)·데이터 앞 2행. 나머지 표는 "표k R×C · <표 제목 30자> · 머리글: …" 한 줄(표 제목 = 위로 최대 3문단 안에서 (1)·1.·Ⅰ.·가.·"~표"·"~계산서"·"~명세서" 패턴에 맞는 가장 가까운 문단, 기간·기준일 줄은 건너뜀). 상세 표 앞뒤 문단은 반드시 포함. 제목에서 연속으로 반복되는 같은 문구는 한 번만 | HWPX·ODT는 XML을 직접 파싱. 머리글의 글자 사이 공백은 원문 그대로, 같은 머리글(공백 무시) 표가 여럿이면 앞 문단을 붙여 구분. 1,500자 초과 시 비상세 표 머리글 앞 3칸 → 데이터 행 2→1 → 문단 80→40자 → 행 라벨 15→8 → 상세 표와 붙지 않은 문단을 뒤에서부터 → 비상세 표 머리글 생략(크기만) → 비상세 표 앞 문단 제목 생략 → 상세 표 수 → 본문 끝 줄부터 빼고 관찰 위치에 실제로 남은 범위와 "이후 생략". 확장자는 zip 기반인데 zip이 아니면 NOT_INSPECTED + 경고 EXTENSION_MISMATCH |
| PPTX | 슬라이드 수, 슬라이드별 제목, 표·도표 여부 | 넘치면 뒤 슬라이드부터 빼고 관찰 위치에 담은 슬라이드만 적음 |
| HWP (구버전) | 읽을 수 있으면 본문 텍스트 요약 | 도구가 없으면 NOT_INSPECTED + 사유 |
| ZIP | 멤버별로 위 규칙 적용 | 멤버 경로를 matched_locator에 기록 |

표 공통 규칙 (PDF·HWPX·DOCX·ODT 표, XLSX·XLS·ODS 시트, 2026-10-21)
- 머리글 행: 위에서부터 제목 행을 최대 3행 건너뛴다. 제목 행 = "단위" 포함, 또는 칸 절반 이상이 빈칸, 또는 한 칸이 행 전체에 병합.
  건너뛴 제목 행 내용(예: "단위: 원")은 표 줄에 "제목 행: …"으로 남긴다. 머리글 바로 아래 같은 글자만 반복되는 행("금 액 | 금 액")은 머리글 이어짐으로 본다.
- 열 건너뛰기: 첫 열부터 연번 열(머리글 연번·순번·번호·No·NO 또는 값의 80% 이상이 1부터 증가하는 정수), 날짜 열(2열부터), 번호 열(값의 80% 이상이 Ⅰ. (1) 1. 가. ① 같은 번호 패턴)이면
  건너뛰고 다음 열을 본다 (최대 3번째 열). 연번·날짜·번호가 아닌 열을 만나면 거기서 멈춘다. 번호 열은 번호만 있는 칸만 건너뛰고 같은 열의 이름 칸(상위 과목)은 행 라벨로 쓴다.
- 행 라벨: 행마다 남은 칸 중 처음 나오는 이름 칸을 쓴다 — 빈칸·번호만 있는 칸·금액 칸·날짜 칸은 건너뛰고, "Ⅰ. 유동자산"처럼 번호가 붙어 있으면 번호를 뗀다
  (병합으로 행마다 칸 위치가 다른 재무표에서 상위·하위 과목을 함께 잡기 위함). 소계·합계·총계 줄과 띄어 쓴 "~ 계" 줄(지역본부 계)은 빼고 "합계 행 있음"으로 표시.
- 상위 과목 우선: 번호를 떼기 전에 번호 단계를 기록한다(Ⅰ.·Ⅱ. = 1단계, 1.·2. = 2단계, (1)·(2) = 3단계, 가.·① 등 = 4단계). 번호가 없는 행은 같은 열의 번호 있는 행 단계로 추정하고, 안 되면 맨 아래 단계. 번호 단계가 둘 이상인 표만 1단계 전부 → 2단계 → … 순서로 채우고 (같은 단계 안에서는 원래 순서, 1단계는 개수 제한을 넘어도 전부), 프로필에 "행 라벨(상위 우선): 첫 열 · 1단계 2/23: …"을 적는다(열 표시는 첫 열이면 "첫 열", 그 외 "N열"). 예산이 모자라면 상세 쪽·상세 표 수를 줄이기 직전에 "1단계 전부 + 하위 3개"로 줄인다. 번호 체계가 없거나 한 단계뿐인 표는 원래 순서.
- 프로필에 어느 열을 썼는지 적는다. 예: "행 라벨: 2열, 1열 연번", "행 라벨: 1-3열, 1열 번호". 첫 열을 그대로 쓰면 "첫 열".

### C. 최종 판정 규칙

위에서부터 먼저 맞는 규칙 하나만 적용한다. 원문은 00_Work_Run.md 7.1이고 이 표는 요약이다.

| 순서 | 조건 | final.status | next_action |
|---|---|---|---|
| 1 | G1 DUPLICATE | FAIL | EXCLUDE_DUPLICATE |
| 2 | G0 RESELECT_B | FAIL | RESELECT_DELIVERABLE |
| 3 | G2 FAIL | FAIL | REVISE_TASK |
| 4 | P0 미해결, G0 REVIEW_B, G1 REVIEW·미완료, G2 REVIEW·미완료, Reference 접근 불명(UNRESOLVED·readiness HOLD·CONFLICT) | REVIEW | 아래 원인별 매핑 |
| 5 | G0 KEEP·REGENERATE + G1 UNIQUE·완료 + G2 PASS + 매핑 오류 없음 + reference_readiness≠HOLD | PASS | HANDOFF_TO_AI_TEAM |

규칙 4의 next_action (M1 결정, 2026-10-21)
- P0 미해결·G0 REVIEW_B·Reference 접근 불명 → CHECK_ASSETS, G1 REVIEW·미완료 → CHECK_DUPLICATE, G2 REVIEW·미완료·호출 실패 → REVIEW_MANUAL.
- 원인이 여럿이면 CHECK_ASSETS > CHECK_DUPLICATE > REVIEW_MANUAL 순으로 하나만 쓰고, 원인 전부는 reason_codes에 남긴다.
- 예외: G0가 두 번 다 실패했거나 검증에 두 번 걸린 행(REVIEW_B, decided_by=RULE)은 REVIEW_MANUAL.

HIGH_OVERLAP만으로는 FAIL이 되지 않는다. 서로 다른 이유의 FAIL은 reason_codes와 next_action으로 구분해 집계한다.
