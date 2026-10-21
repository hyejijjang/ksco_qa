# 최종 Excel / JSONL 데이터 계약 (Canonical 1.0)

이 문서는 `00_Work_Run.md` 7장의 출력 형식을 명확히 풀어쓴 **참조 스키마**다. 단계별 JSON 생성 시 `source`는 항상 원본을 그대로 보존하고, 나머지 Gate 결과는 별도 객체로 기록한다.

## 원본 DataList 매핑 (고정)

| 원본 열 | 역할 | 검수에서 사용 |
|---|---|---|
| A | AI_Sending | 원본 보존만 |
| B | id | 식별자; `source_row`와 복합 관리 |
| C | 직업명 | G0/G1/G2 |
| D | 산출물명 | **파일명 구성의 stem** |
| E | 레퍼런스 | Reference 선언/실파일 연결 정보 |
| F | 출력포맷 | **파일명 구성의 extension** |
| G | 태스크 | 기존 `original_task`; 수정 금지 |
| H | 검색 | 원본 보존; Task 지시의 웹검색 의무로 혼동 금지 |
| I | 직무정보 | G0/G2 |
| J/K | 비고·기타 | 확인 가능한 맥락이 있을 때만 보조, 사실 근거로 과장 금지 |
| L/M | 원본파일·링크 | 원본 보존만; Deliverable 매핑 제외 |
| N | 비식별화 필 | 원본 보존; 개인정보 위험 단서로 검토 가능 |
| **O** | **개인 태깅** | **원본 보존만. 매핑·판정·검수 입력 금지** |
| P 이후 | Tag 및 기존 추가 열 | 원본 보존; 무단 삭제/이동 금지 |

## JSONL 레코드 규격

- 파일: `03_results/03_final.jsonl`, UTF-8, 원본 데이터 행 수와 1:1, 객체 1개당 물리적 한 줄.
- 공통 최상위 키: `schema_version`, `dataset`, `source_file`, `source_sheet`, `source_row`, `id`, `source`, `source_assets`, `revision`, `duplicate`, `verify`, `final`.
- `schema_version` 예: `ksco-taskqa/canonical-1.0`. **기존 3.0용 Apps Script는 이 스키마를 자동으로 지원한다고 가정하지 않는다**. 연동 코드를 필드 매핑에 맞춰 점검해야 한다.
- `source.cells`는 A~원본 마지막 열 전체를 열 문자 키로 저장. 값 예: `"D":{"header":"산출물","value":"2024년 매출현황","formula":null,"hyperlink":null}`. O열도 원본 셀로만 포함.
- Excel 수식 및 하이퍼링크를 가능한 범위에서 보존. 확인할 수 없는 수식 캐시는 추측하지 않는다.

### source_assets

| 필드 | 의미 |
|---|---|
| `deliverable_files.expected_filename` | D+F로 구성한 예상 파일명 |
| `deliverable_files.source_columns_used` | `["D","F"]` 고정 |
| `deliverable_files.match_method` | `D_F_EXACT_FILENAME` 또는 `null` |
| `deliverable_files.match_status` | MATCHED/AMBIGUOUS/CONFLICT/NOT_FOUND/INACCESSIBLE/INVENTORY_INCOMPLETE |
| `deliverable_files.matched_locator` | 실제 경로 또는 null |
| `deliverable_files.inspected` | 파일 실제 열람 여부 bool |
| `deliverable_files.inspected_locations` | 페이지/시트/열 등 배열 |
| `reference_files.mode` | GENERATE_REFERENCE/PROVIDED_REFERENCE/UNRESOLVED_REFERENCE |
| `reference_files.assets` | 제공된 Reference 파일별 경로·역할·열람 위치 |

### revision (G0)

- `action`: KEEP/REGENERATE/REVIEW_B/RESELECT_B
- `original_task`, `regenerated_task_new`, `effective_task`
- `reason`, `reason_codes`, `evidence`, `criterion`, `conclusion`
- `g0_self_check`: 10개 평가 차원의 `status/evidence/criterion/conclusion`
- REGENERATE이면 `regenerated_task_new`와 `effective_task`의 정확 일치 필수.

### duplicate (G1)

- `status`: UNIQUE/DUPLICATE/REVIEW/NOT_EVALUATED
- `duplicate_type`: EXACT/SEMANTIC/PARAMETER_VARIANT/EXPRESSION_ONLY/NONE/UNDETERMINED
- `overlap_status`: NONE/LOW_OVERLAP/HIGH_OVERLAP/UNDETERMINED
- `representative_row`, `representative_id`, `group`, `compared_rows`, `candidate_rows`
- `candidate_count`, `adjudicated_candidate_count`, `unresolved_candidate_count`
- `search_scope`, `search_completed`, `reason`
- 중복 확정 제외 행은 대표 행/id 필수; 대표 행 자신은 DUPLICATE가 아님.

### verify (G2)

- `status`: PASS/REVIEW/FAIL/SKIPPED
- `skip_reason`: SKIPPED라면 필수
- `checks`: 16개 항목 객체 `status/evidence/criterion/conclusion` (SKIPPED라면 빈 객체 허용)
- `b_coverage_status`: SUFFICIENT/PARTIAL_NONCRITICAL/PARTIAL_CRITICAL/MISSING
- `reference_mode`: GENERATE_REFERENCE/PROVIDED_REFERENCE/UNRESOLVED_REFERENCE
- `reference_action`: GENERATE/REUSE/SUPPLEMENT/ADAPT/REPLACE/CHECK_ACCESS
- `reference_readiness`: BLUEPRINT_READY/READY_AS_IS/READY_WITH_ACTION/HOLD
- `blueprints`: `scenario`, `reference`, `reasoning_map`, `evaluation`
- `proposed_fix`, `reason`, `reason_codes`, `review_independence`

### final (G3)

- `status`: PASS/REVIEW/FAIL
- `next_action`: HANDOFF_TO_AI_TEAM/EXCLUDE_DUPLICATE/REVISE_TASK/RESELECT_DELIVERABLE/CHECK_ASSETS/CHECK_DUPLICATE/REVIEW_MANUAL
- `reason_codes`: 배열
- `reason`: 판단 근거와 필요한 조치.

## Excel 추가 열: 기존 원본 열 오른쪽

`source_row, expected_filename, deliverable_match_status, deliverable_inspected, reference_mode, revision_action, original_task, regenerated_task_new, effective_task, revision_reason, g0_self_check_json, duplicate_status, duplicate_type, duplicate_of_row, duplicate_of_id, overlap_status, candidate_count, adjudicated_candidate_count, unresolved_candidate_count, duplicate_reason, verify_status, verify_reason, verify_checks_json, b_coverage_status, reference_action, reference_readiness, scenario_blueprint_json, reference_blueprint_json, reasoning_map_json, evaluation_blueprint_json, final_status, final_reason_codes, next_action, final_reason`.

실제 파일에 있는 중복 헤더는 위치 기반으로 구분하며, **새로운 시트는 만들지 않는다**.

## 최소 검증

1. 원본 데이터 행 수 = 모든 Gate Excel의 원본 행 수 = JSONL 레코드 수.
2. `source_row`와 `id`가 원본 행에 대응; 행 정렬·삭제·삽입 없음.
3. 각 JSONL `source.cells`의 전체 원본 셀과 최종 Excel의 기존 영역 대조.
4. `D_F_EXACT_FILENAME` 외의 매핑 방법이 MATCHED로 기록되지 않았는가?
5. G0 REGENERATE 행에 `regenerated_task_new`가 있는가?
6. `duplicate.status=DUPLICATE`이면 대표행 존재, `verify.status=SKIPPED`, `final.status=FAIL`인가?
7. G1 미평가 후보가 있는데 `search_completed=true`라고 잘못 표기하지 않았는가?
8. Reference 부재를 이유로 자동 REVIEW하지 않았는가?
9. `final.status=PASS`이면 G0 채택, G1 중복검사 완료/UNIQUE, G2 PASS, 핵심 자료 확인이 충족되는가?
10. QA_SUMMARY의 각 Gate 집계가 행 수/후보쌍 수와 맞는가?
