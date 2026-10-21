# 프롬프트 변경 이력

변경 절차 (설계 8.3): 문제 발견 → 프롬프트 수정 (기준 자체 변경은 00_Work_Run.md 먼저, 팀 공유)
→ 고정 평가셋(약 60행)으로 이전 버전과 비교 → 이 파일에 변경 내용·평가 결과 기록 후 반영.

prompt_version은 단계 프롬프트 + common + 스키마 + 기준 발췌를 합친 텍스트의 해시다 (설계 8.2).
사람이 붙이는 버전 이름(예: g0-v1.2)을 아래 항목 제목에 함께 적는다.

## 항목 형식

```
## <날짜> <버전 이름> (<단계>)
- 변경:
- 이유:
- 평가셋 결과: (이전 → 이후)
```

## 2026-10-21 로더·재호출 머리·G2 reference_conflict (공통, G2) — M1 결정 26·28·29
- 변경: 로더가 `<!-- -->` 주석을 지우고, prompt_version을 실제 전송 텍스트 기준으로 계산.
  g2.md는 G2_OVERLAP_MODE 섹션 하나만 보냄. FEEDBACK_HEADER 문구 교체.
  schemas/g2.json에 reference_conflict(bool|null), reference_conflict_note(string|null) 추가.
- 이유: M1 결정. g0.md·g2.md의 저장 문단·review_independence 문장·SKIPPED 글머리는 이미 삭제된 상태 확인.
- 평가셋 결과: 해당 없음 (실제 호출 전).

## 2026-10-21 g2 스키마 disagree 구조, g1b 제목 정리 (G2, G1b)
- 변경: schemas/g2.json disagree 항목을 {indicator, reason} → {indicator, g0_value, new_value, reason}.
  g1b.md의 중복된 "## 쌍 단위 지시" 제목 하나 삭제.
- 이유: g2.md AGREE_CHECK 지시("disagree에 해당 지표, G0 값, 새 값, 이유를 적는다")와 스키마 불일치.
- 평가셋 결과: 해당 없음 (실제 호출 전).

## 2026-10-21 skeleton (common, g0, g1b, g2)
- 변경: 섹션 머리와 원문 발췌 위치 표시(<!-- EXCERPT -->)만 만듦.
- 이유: 저장소 뼈대 생성.
- 평가셋 결과: 해당 없음. 발췌·지시가 비어 있어 호출에 쓸 수 없는 상태.
