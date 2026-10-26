<!--
해석 규칙 — 00_Work_Run.md에 없는 팀 해석 (2026-10-26 ③ + 규칙 5·6). 00 발췌와 섞지 않는다. 변경 이력은 CHANGELOG.
g0.md·g2.md가 "<!-- include rules.md -->" 자리에 이 파일을 넣는다 (같은 규칙을 두 번 쓰지 않는다).
"<!-- stages: G0 G2 -->" 표시는 다음 표시까지의 줄을 어느 단계에 보낼지 정한다. 첫 표시 앞의 줄은 모든 단계에 보낸다.
G2에는 겹치는 지표 규칙 1(input_contract)·2(grounding)·4(output_specification)·5(answer_leakage)만 보낸다.
규칙 3(action)·6(재생성 작성)은 G0 전용. B 유형(프로필 범위 밖 미확인 → evaluation_alignment·deliverable_fit·b_coverage)은
규칙으로 바꾸지 않고 00 6.3 기준대로 둔다 (2026-10-26 결정).
-->
### 해석 규칙
<!-- stages: G0 G2 -->
1. input_contract: Task에 입력 자료가 적혀 있지 않은 것 자체는 결함이 아니다. 필요한 Reference의 최소 종류·필드를 설명할 수 있으면 P이고, 설명조차 할 수 없을 때만 R이다.
<!-- stages: G0 -->
   설명한 Reference의 최소 종류·필드는 expected_reference_spec에 쓴다.
<!-- stages: G2 -->
   이 규칙은 task_clarity에도 적용한다. Task가 입력을 "제공된 자료"로만 지칭하는 것은 결함이 아니다(G0 재생성 규칙이 그렇게 쓰도록 정한 표현이다). 입력의 최소 종류·필드는 reference_blueprint에서 판단한다.
<!-- stages: G0 G2 -->
2. grounding: Task가 파일 내용과 모순될 때만 R 또는 F다. file_profile 범위 밖이라 확인하지 못한 항목은 P로 두고 reason에 "프로필 범위 밖 미확인: <항목>"을 쓴다. Task의 목적 문구("공개하기 위해" 등)는 grounding 판정 대상이 아니다.
<!-- stages: G0 -->
   핵심 결과 항목을 확인하지 못하면 REVIEW_B를 검토한다.
3. KEEP을 막는 것은 F뿐이다. REGENERATE는 Task 문장을 고쳐서 R 또는 F가 실제로 해소될 때만 고른다. 문장 수정으로 풀리지 않는 R이면 KEEP으로 두고 issues에 적는다.
<!-- stages: G0 G2 -->
4. output_specification: 산출물 파일명·확장자·인코딩은 D·F열로 이미 정해진 값이므로 Task에 없다는 이유로 R을 주지 않는다. 판단 대상은 결과의 구성(표·섹션·열·항목)이 확인 가능하게 정해졌는가이다.
5. 정답 유출(G0 no_answer_leakage, G2 answer_leakage): 출력할 표·섹션의 구성 항목(분류명, 열 이름, 구분 체계)을 Task에 적는 것은 정답 유출이 아니라 출력 명세다. 유출은 Deliverable의 정답 수치·결론값(합계 금액, 비율 결과, 판정 결론 등)을 Task에 미리 적는 경우만 해당한다.
<!-- stages: G0 -->
6. REGENERATE 시 원본 Task에 있던 구체 항목(file_profile에서 확인되거나 모순되지 않는 분류명·과목명·처리 단계)은 유지한다. 결함이 있는 부분만 고치고, 구체 항목을 "제공된 자료의 항목" 같은 일반 표현으로 바꾸지 않는다.
