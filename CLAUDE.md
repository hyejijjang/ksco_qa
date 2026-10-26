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

### 2026-10-23 결정
- `FILE_ACCESS=fulltext`(비교 실험용): 행의 추정 토큰 합계 ≤ `FULLTEXT_MAX_TOKENS`(기본 30000)인 파일만 원본 전문을 row_card.file_fulltext로 보낸다(사유는 file_fulltext_note). 추정 토큰 = 글자 수 × 0.7(실측 0.61~0.64보다 넉넉히). profile 모드 row_card는 7.1 필드 그대로. 설계 14장 #2·CHANGELOG는 ②·③ 반영 후 같은 30행으로 profile vs fulltext를 비교해 사람 최종 판정 일치가 좋아질 때 고친다 (비교표: 행별 action·grounding·사람 판정·입력 토큰·비용).
- 기준치를 넘는 큰 CSV: 프로필 + Task 언급 항목 자동 대조(④). profile+tools는 M5에서 "큰 CSV가 프로필 부족으로 틀린 사례"가 확인될 때 재논의 (설계 12장).
- G1 의미 탐색: 결정 (a) — task_card 유사도(card 신호) + G1b added_pairs로 대신한다. active 행 전부에 task_card가 있으면 semantic_search_completed=true. M3 게이트에서 놓친 중복 쌍 수·사례를 재고 많으면 (b) LLM 의미 탐색 단계를 검토 (설계 13장).
- 모델은 GPT-6 Luna로 확정 (14장 #1, 2026-10-22). MODEL_G0/G1B/G2 = `gpt-6-luna` (2026-10-23 확정: 공식 문서에 날짜 고정 스냅샷이 없어 별칭 사용. 실제 응답 모델은 raw 응답에 남음). 단가 = OpenAI 공식 Standard 0.10 / 0.01 / 0.50 USD per 1M (입력 272K 이하, 2026-10-23 확인). 코드 기본값은 null로 두고 Task 폴더 task_config.yaml 또는 --config로 넣는다(run 시 누락이면 오류). 캐시 쓰기 요금($0.125/1M)은 usage에 없어 비용에 반영하지 않는다.

### 2026-10-26 결정 (30행 PoC 평가 반영)
PoC(2026-10-23, run 20261023-180904): G0 REGENERATE 26/30인데 Work는 재생성 0건·사람 최종 PASS 8건 → 프롬프트부터 고친 뒤 사람 검토(M2 게이트).
- 10/23 결정의 ②·③ 정의 (profile vs fulltext 비교는 ②·③ 반영 후, M2 사람 검토 다음):
  - ② 프롬프트 공백 채우기: common.md를 00 원문 발췌로 채운다(0장 역할, 1장 최종 Agent 제약·절대 금지, 2장 원칙 1~8, 3.2 Reference 분기). g0.md의 [확인] 작업용 표시를 지우고, P/R/F/NA 정의는 00 6장(6.4) 원문 문장을 그대로 쓴다. 발췌가 원문 그대로인지는 tests/test_prompts.py가 확인.
  - ③ 해석 규칙: g0.md "해석 규칙" 섹션(00 발췌와 분리, CHANGELOG에 "00에 없는 팀 해석"으로 기록). 1 input_contract(입력 자료 미기재 자체는 결함 아님, Reference 최소 종류·필드를 설명 가능하면 P → expected_reference_spec), 2 grounding(파일과 모순될 때만 R/F, 프로필 범위 밖은 P + reason "프로필 범위 밖 미확인: <항목>", 핵심 결과 항목 미확인이면 REVIEW_B 검토, 목적 문구는 대상 아님), 3 KEEP은 F만 막음·REGENERATE는 문장 수정으로 R/F가 해소될 때만·안 풀리는 R은 KEEP + issues, 4 output_specification(파일명·확장자·인코딩은 D·F열로 정해짐, 결과 구성이 확인 가능하게 정해졌는가만 판단).
- REGENERATE 작성 금지 조건(g0.md 출력 규칙): 핵심 처리·판단 제거·단순 복사 작업화 금지, 파일명·인코딩·구분자 등 B 파일 고유 정보 금지, 원본·직무정보·file_profile에 없는 입력 자료 창작 금지("제공된 자료" 수준, 구체 종류는 expected_reference_spec). 코드 검증: regenerated_task_new에 expected_filename({D}.{F}, 대소문자 무시) 또는 인코딩 문자열(cp949·ms949·euc-kr·utf-8(-sig)·utf-16·"인코딩")이 있으면 실패.
- G0_ESCALATE 대상: 코드 검증 실패, RESELECT_B, REVIEW_B만. REGENERATE는 재판정하지 않는다.
- 재실행은 기존 30행(33_accounting m2_g0_sample30, 회계 사무원만)으로, 결정 (a) 반영 상태로 G1까지 끝까지. 비교는 `ksco-qa compare-runs`(행별 action·차원별 R/F·재생성 Task 이전/새·사람 최종 판정·검수 메모).
- M2 게이트 재정의(설계 13장): 템플릿 판정 0건 + 사람 판정 대비 재생성 과다 해소 + 재생성 Task가 원본보다 나빠지지 않음. 직무 기준 오판 0건은 M4(398행 전체)로 옮긴다.
- 템플릿 감지는 차원별 evidence(설계상 evidence_loc 복사)를 대상에 넣지 않는다 (테스트로 확인).

### 2026-10-26 결정 (2차 run 20261026-170739 평가 반영)
- G0는 거의 통과(REGENERATE 11·KEEP 15·REVIEW_B 4, 사람 PASS 중 REGENERATE 8→2). 남은 문제는 G2: 사람 PASS 8행 중 최종 PASS 1행, 사람 REVIEW 22행 중 REVIEW 17행. G2 R 62건 = A 입력 자료 미기재 ~21 · B 프로필 범위 밖 미확인 ~20 · C 실제 설계 문제 후보 ~20.
- 해석 규칙은 prompts/rules.md 하나로 빼서 G0·G2가 같이 쓴다(로더가 `<!-- stages: … -->` 표시로 단계별 줄을 고른다). G2에는 규칙 1·2·4·5, 규칙 3·6은 G0 전용. 규칙 1은 G2 task_clarity에도 적용("제공된 자료"로만 지칭하는 것은 결함 아님, 입력 최소 종류·필드는 reference_blueprint에서 판단).
- 규칙 5 정답 유출: 표·섹션 구성 항목(분류명·열 이름·구분 체계)은 출력 명세, 유출은 정답 수치·결론값만. 규칙 6 재생성 시 원본의 구체 항목(분류명·과목명·처리 단계) 유지.
- B 유형(프로필 범위 밖 미확인 → evaluation_alignment·deliverable_fit·b_coverage)은 규칙으로 바꾸지 않는다. 00 6.3 기준대로 두고 profile vs fulltext 비교로 확인.
- 재실행: 같은 30행을 FILE_ACCESS=profile과 fulltext(FULLTEXT_MAX_TOKENS=30000, Task 폴더 fulltext.yaml을 --config로) 두 run으로. compare-runs는 run 여러 개(`--run 이름=run_id` 반복, 첫 run이 기준)를 받아 사람 판정 클래스별 일치·전부-REVIEW 기준선·G2 R 유형(A/B/C, 키워드 분류 근사)·b_coverage·REVIEW_B 변화·파일 입력(전문/프로필)·행당 토큰·비용을 낸다. C 유형 사례(task_0000012·030·031·033·035)는 `--mark "C 유형=…"`로 계속 추적.
- 실제 run도 run 폴더에 03_final.jsonl 사본을 남긴다(추가 전용: 이미 있으면 03_final.<n>.jsonl). 03_results/03_final.jsonl은 최신 run 것. compare-runs는 run 폴더 사본을 읽는다.

### M1 결정 (2026-10-21)
입력
- 설계 5.1 그대로: Task 폴더의 `*_DataList.xlsx` 1개 + `01_output_files/`. Google Sheets 링크 입력은 구현하지 않는다.
- 대상은 KSCO 28·33·34. B열 id는 시트에서 값으로 채워서 받는다.

P0
- E열: 1차 구현은 PROVIDED_REFERENCE를 판정하지 않는다. 비어 있으면 GENERATE_REFERENCE, 값이 있으면 UNRESOLVED_REFERENCE + reference_note에 E열 원문. Reference 파일 탐색 없음. G2에서 UNRESOLVED 행은 reference_readiness=HOLD, 최종 REVIEW가 기본값(00 6.2).
- 탭 이름 "DataList", 헤더 1행. 없으면 중단. 헤더 대조는 NFC + 앞뒤 공백·줄바꿈 제거 후 정확히 일치, B~I열만 검증(설계 5.1-2의 B·C·D·E·F·G·I). 나머지 열은 source.cells에만 보존.
- id 누락·중복은 실행 중단.
- I열이 비었거나, 시트 오류값(#REF!·#N/A 등)이거나, "매칭 실패"를 포함하면 경고만(JOBINFO_EMPTY / JOBINFO_SHEET_ERROR / JOBINFO_MATCH_FAILED).
- D열 원문은 바꾸지 않고 source.cells에 보존. 매칭 비교할 때만 앞뒤 공백 제거 + 경고 D_TRAILING_SPACE.
- 디스크와 ZIP 멤버에 같은 이름이 있으면 AMBIGUOUS. 파일·멤버는 있으나 열 수 없음(암호 ZIP 멤버, 권한 오류) → INACCESSIBLE. ZIP이 깨져 멤버 목록을 못 읽으면 NOT_FOUND가 될 행을 INVENTORY_INCOMPLETE로.
- inspected = MATCHED + 프로필 생성 성공. 프로필 실패는 inspected=false → G0에서 REVIEW_B(decided_by=RULE, 사유 NOT_INSPECTED).
- job_leaf = C열을 ':'(전각 '：' 포함)로 나눈 마지막 값을 strip, 구분자가 없으면 전체.
- row_card에는 설계 7.1 필드(+ original_task_empty)만. R(AI 판정)·S(최종 판정)·T(Regenerate Task)·U(원본 Task(백업))·V(검수 메모) 등 이전 검수 결과 열은 절대 모델 입력에 넣지 않는다 (테스트로 확인).
- F열이 "HWPX, XLSX"처럼 쉼표로 여러 형식이면 형식별로 {D}.{형식}을 각각 찾는다. 전부 찾으면 MATCHED(파일별 프로필), 일부만 찾으면 MATCHED + 경고 PARTIAL_FORMAT, 하나도 없으면 NOT_FOUND. "CSV/PDF"처럼 '/'로 묶인 것은 00 3.1대로 CONFLICT.
- G열이 빈 행: G0는 실행하되 row_card에 original_task_empty=true. KEEP이면 코드 검증 실패(REGENERATE·REVIEW_B·RESELECT_B만 허용). reason_codes에 ORIGINAL_TASK_EMPTY.

프로파일러
- 프로필 예산은 설정 PROFILE_MAX_CHARS(기본 1,500자, 행당·파일 여럿이면 나눔).
- (CSV·스프레드시트·JSON/XML/HTML) 1,500자 초과 시 줄이는 순서: 중간 샘플 → 범주값 목록(20→10개) → 끝 샘플 → 앞 샘플(1행까지). 파일 구조(열·시트·페이지 수)와 관찰 위치는 줄이지 않는다.
- 관찰 위치에는 프로필에 실제로 담은 범위만 적는다. 읽기만 하고 담지 않은 범위를 "전체"로 적지 않는다 (문서형·PDF·PPTX).
- 문서형(HWPX·DOCX·ODT): 제목, 본문 문단 순서대로 앞 80자. 레이아웃 칸(1열 표 또는 1행 표, 단 칸 절반 이상이 숫자인 1행 표는 데이터 표, 2열 이상 여러 행 표는 데이터 표)은 표에서 빼고 글자를 문단 흐름에 남김("레이아웃 칸 N개 제외"). 제목에서 연속 반복 문구는 한 번만. 상세 표 = 셀 수가 큰 표부터(위치·크기·제목 행·머리글·행 라벨·데이터 앞 2행), 나머지 표는 "표k R×C · <표 제목 30자> · 머리글: …" 한 줄(표 제목 = 위로 최대 3문단 안 제목 패턴 문단, 기간·기준일 줄 건너뜀), 상세 표 앞뒤 문단은 꼭 담음. 초과 시 비상세 표 머리글 3칸 → 데이터 행 2→1 → 문단 80→40자 → 행 라벨 15→8 → 비보호 문단 → 비상세 표 머리글 생략(크기만) → 비상세 표 앞 문단 제목 생략 → 상세 표 수 → 끝 줄부터(관찰 위치에 "이후 생략"). 확장자가 zip 기반(hwpx·docx·xlsx·pptx·odt·ods)인데 zip이 아니면 NOT_INSPECTED + 경고 EXTENSION_MISMATCH(mapping_audit warnings). 원본 파일 교체 여부는 사람이 판단.
- PDF는 pdfplumber(pymupdf·pypdf 대체, VC++ 재배포 패키지 없이 동작 확인): 쪽 수, 스캔 여부. "행 4 이하·열 2 이하", "1열", "1행(숫자 절반 이상이면 예외)" 표는 레이아웃 칸으로 빼고(글자는 쪽 텍스트에 남김) "레이아웃 칸 N개 제외". 쪽 줄 "pN: 첫 줄(제목) · 표k R×C · 머리글: …"(표 크기는 한 번만), 첫 줄이 머리글 줄이면 "(pM 표 이어짐)". 상세 쪽 = 셀 수가 큰 표가 있는 쪽부터, 표가 이어진 쪽은 뒤로. 상세 쪽은 표 크기·머리글 전체, 첫 5줄·금액 범위·합계 줄·단위·기준일, 행 라벨·데이터 앞 2행. 초과 시 비상세 쪽 머리글 3칸 → 데이터 행 2→1 → 첫 줄 5→3→1 → 행 라벨 15→8 → 상세 쪽 수(맨 마지막). 쪽 수·표 개수·크기·쪽 위치·상세 쪽 표 머리글·관찰 위치는 줄이지 않는다.
- 표 공통(PDF·HWPX·DOCX·ODT·XLSX): 머리글 행은 위에서부터 제목 행("단위" 포함·칸 절반 이상 빈칸·행 전체 병합)을 최대 3행 건너뛰고 찾는다(제목 행 내용은 표 줄에 남김). 첫 열부터 연번·날짜(2열부터)·번호 패턴(Ⅰ. (1) 1. 가. ①, 80% 이상) 열은 건너뛴다(최대 3번째 열, 아닌 열에서 멈춤, 번호 열은 번호만 있는 칸만 건너뛰고 같은 열의 상위 과목명은 살림). 행 라벨은 행마다 처음 나오는 이름 칸(빈칸·번호만·금액·날짜 칸 건너뜀, "Ⅰ. 유동자산"은 번호 떼기), 소계·합계·총계 줄은 빼고 "합계 행 있음". 프로필에 "행 라벨: N열, 1열 연번"처럼 적는다. 상위 과목 우선: 번호 단계(Ⅰ.=1, 1.=2, (1)=3, 가.·①=4, 번호 없는 행은 같은 열 단계로 추정·안 되면 맨 아래)가 둘 이상인 표는 1단계 전부(개수 제한 무시) → 2단계 → … 순서, "행 라벨(상위 우선): 첫 열 · 1단계 2/23: …"(열 표시는 첫 열이면 "첫 열", 그 외 "N열"). 단계가 없거나 하나뿐이면 원래 순서. "~ 계"처럼 띄어 쓴 소계 행(지역본부 계)은 빼지 않고 "지역본부 계(소계)"로 남긴다(2026-10-26 되돌림). 예산이 모자라면 상세 쪽·상세 표 수를 줄이기 직전에 행 라벨을 "1단계 전부 + 하위 3개"로.
- HWP(구버전)는 NOT_INSPECTED. CSV 스트리밍 기준 20MB.
- 부록 B에 추가: JSON(최상위 구조·키 목록·레코드 수·샘플), XML(루트·반복 요소·필드), HTML(제목 구조·표).

G3
- 최종 판정은 00 7.1이 원문, 부록 C는 요약. 둘 다 반영: 규칙 4에 G2 미완료, 규칙 5 PASS 조건에 reference_readiness≠HOLD.
- 규칙 4의 next_action: P0 미해결·G0 REVIEW_B·Reference 접근 불명(UNRESOLVED·HOLD·CONFLICT) → CHECK_ASSETS, G1 REVIEW·미완료 → CHECK_DUPLICATE, G2 REVIEW·미완료·호출 실패 → REVIEW_MANUAL. 원인이 여럿이면 CHECK_ASSETS > CHECK_DUPLICATE > REVIEW_MANUAL로 하나만 쓰고 원인 전부는 reason_codes에.
- reason_codes는 06에 목록이 없어 `enums.yaml`의 `reason_code`가 유일한 목록.
- G2가 두 번 다 실패하거나 검증에 두 번 걸린 행: verify.status=REVIEW, decided_by=RULE, reason_codes에 G2_CALL_FAILED 또는 G2_VALIDATION_FAILED, review_queue에 포함, 최종 next_action=REVIEW_MANUAL (G0와 같은 예외, 2026-10-22).
- G0가 두 번 다 실패하거나 검증에 두 번 걸린 행: action=REVIEW_B, decided_by=RULE, reason_codes에 G0_CALL_FAILED 또는 G0_VALIDATION_FAILED, review_queue에 포함. 최종 REVIEW, next_action은 이 경우만 예외로 REVIEW_MANUAL.
- final.execution_notes는 문자열(06에 타입 없음): "API 파이프라인; run_id=…; G0=모델/추론강도; G1B=…; G2=…; prompt=…; G2_OVERLAP_MODE=…; review_independence=SEPARATE_CALL". mock은 "API 파이프라인(MOCK)". 같은 내용을 run_report.json에 객체로도 남긴다.
- Gate별 xlsx 추가 열은 00_Work_Run.md 4·5·6장 "행별 기록" 열 목록 그대로. 원본 서식 복사 대신 새 워크북에 값만 쓴다(원본 A~끝 열 값 + 추가 열). 수식·하이퍼링크는 source.cells에만.
- revision.criterion = 00 4.2의 action 정의 원문, revision.conclusion = "{action}: {revision_reason 앞 150자}". NA 지표 conclusion = "해당 없음 (G0/G2 판정)". audit_completeness = COMPLETE / INCOMPLETE(미판정 후보·검색 미완료) / NOT_EVALUATED. verify_flags = G2 코드 검증 경고 목록. final.reason = "규칙 N: 원인 → 조치", 확정 중복은 대표 행 source_row와 id 함께 ("규칙 1: 확정 중복 (대표 행 2, task_0000006) → 중복 제외").
- G3 입력 형식(단계 기록 데이터 계약)은 ksco_qa/g3/records.py. G0·G1·G2 단계는 이 형식으로 run 폴더에 쓴다.
- 00 7.3의 부산물 5종(00_input_snapshot.xlsx, 01_duplicate_candidates.csv, 01_duplicate_coverage.csv, 03_final.xlsx, QA_SUMMARY.md)은 만들지 않는다.
- 파이프라인은 기존 검수 툴(Apps Script)이 하던 판정 자체를 대체한다. 검수 툴이 우리 JSONL을 읽는 구조가 아니다 (2026-10-22 정정). 03_final.jsonl은 06 스키마대로 계속 만든다 (기록·Work 비교용). DataList 기존 열(R=AI 판정 PASS/REVIEW/FAIL, T=Regenerate Task 등)에 붙여 넣을 04_sheet_paste.xlsx를 만든다 — 열 구성·값 형식은 KSCO-28 DataList의 R·T열 값 기준 (확정 대기).
- M1 게이트(재정의): mock run 산출물 + 06 최소 검증 10항목 통과 + 04_sheet_paste.xlsx가 DataList 기존 열과 같은 형식.
- QA_SUMMARY는 만들지 않으므로 06 최소 검증 10번은 run_report.json 집계와 대조.
- 템플릿 감지 대상: G0 reason·issues, G1b evidence, G2 reason·issues·proposed_fix. 숫자, 해당 행의 job·job_leaf·deliverable_title, 따옴표·괄호 안 값, 공백을 지운 뒤 완전 일치로 비교.
- overrides.jsonl 한 줄: {source_row, id, gate, field, old_value, new_value, reviewer, reason, decided_at}. 같은 (source_row, gate, field)는 마지막 줄이 이긴다.
- review_queue 표본 시드 = hash(run_id), run_report에 기록.
- UNRESOLVED_REFERENCE 행의 G2 기본값: reference_action=CHECK_ACCESS, reference_readiness=HOLD (코드 검증 대상).
- 여러 형식 행의 source_assets.deliverable_files.matched_locator는 06대로 문자열 하나(경로를 " | "로 이음), 전체 목록은 추가 필드 matched_locators[]. mapping_audit의 matched_locator도 " | ".
- 00 6.2의 CONFLICT: enum은 바꾸지 않고 G2 출력에 reference_conflict(bool, null 허용) + reference_conflict_note 추가. reference_mode=PROVIDED_REFERENCE일 때만 허용(1차 구현에서는 발생하지 않음). true면 reason_codes에 REFERENCE_CONFLICT, 최종은 Task FAIL이 아니라 REVIEW.

프롬프트
- 로더가 `<!-- -->` 주석을 지운다. prompt_version 해시는 실제로 보내는 텍스트 기준. g2.md는 G2_OVERLAP_MODE에 해당하는 섹션 하나만 보낸다.
- g0.md의 "행별 기록"·"G0 저장" 문단, g2.md의 review_independence 문장과 SKIPPED 대상 글머리표 3개는 삭제.
- FEEDBACK_HEADER: "직전 응답이 아래 검증 규칙을 위반했다. 입력은 같다. 아래 항목을 고친 전체 응답을 처음부터 다시 출력하라." 아래에 위반 항목을 "- job_evaluated가 'X'인데 이 행의 직업은 'Y'이다" 형식으로 나열.

Work 결과 비교 (M5)
- Work 결과는 별도 jsonl이 없다. compare 입력은 Work 결과 CSV(열: id, AI 판정, 최종 판정, Regenerate Task, 원본 Task(백업), 검수 메모) 또는 DataList.xlsx "DataList" 탭 R~V열(R=AI 판정, S=최종 판정, T=Regenerate Task, U=원본 Task(백업), V=검수 메모, id는 B열). 형식은 ksco_qa/compare.py load_work_result. 이 열들은 계속 row_card(모델 입력)에 넣지 않는다. 판정 값 어휘와 API 필드 대응은 M5에서 정한다.
- 테스트는 tests/fixtures의 가상 샘플만 쓴다 (실제 work_result.csv·DataList는 저장소에 복사하지 않는다).

개발 환경
- 키(OPENAI_API_KEY)는 구현이 끝난 뒤에 넣는다. 개발·검증은 `--llm mock`(MockClient)으로 한다. mock run은 run_id가 `mock-`로 시작하고 산출물은 `_work/<run_id>/` 안에만 쓴다.

## 저장소 구조
```
criteria/      판정 기준 원문 (읽기 전용)
prompts/       common.md, rules.md(해석 규칙, G0·G2 공용), g0.md, g1b.md, g2.md, CHANGELOG.md
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
