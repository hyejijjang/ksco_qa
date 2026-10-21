# KSCO Task QA 파이프라인

Work Mode에서 대화 단위로 돌리던 KSCO Task QA(P0 → G0 → G1 → G2 → G3)를 고정 코드 + LLM API 배치 파이프라인으로 옮긴 저장소입니다.
명령 한 번으로 한 Task 폴더(KSCO 28·33·34 DataList)를 끝까지 처리하고, 실행마다 모델·프롬프트 버전·토큰·비용을 기록합니다.

전체 설계는 [`docs/design.md`](docs/design.md)를 참고하세요.
