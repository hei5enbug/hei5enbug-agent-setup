# 통합 후보의 계약 대응

> 영어 원본: [coverage.md](coverage.md)
> 이 문서는 사람이 읽기 위한 비권위 한국어 미러다. 실행 지침으로 사용하지 않는다.

기준은 baseline.json의 커밋이다. 이 문서는 원본과 후보의 대응이며 모든 동작이 실제 실행에서 통과했다는
주장이 아니다. 기존 평가 ID 대응은 evals/source-cases.json에 있다. 후보 1–13은 Deep Interview,
14–20은 Decision Navigator의 사례이며 21–29은 통합 경계를 다룬다.

| 필수 동작 | 후보의 기준 파일 | 사례 또는 직접 검사 |
|---|---|---|
| 명시적 호출, 먼저 인터뷰를 제안하지 않음 | SKILL.md 요청 결과 확정, agents/openai.yaml | 21. 실제 호스트 라우팅 평가가 더 필요하다. |
| 목표·제약·수용 기준·결정·비개발 목적지 | SKILL.md, references/decision-map.md | 1–3, 14, 20, 22. |
| 근거·불확실성·사람 질문 하나·확인·기록을 한 절차로 수행 | SKILL.md 공통 반복 | 1, 14–20, 22–25. |
| 지도가 있다는 이유로 일반 결정에 수치 기준을 추가하지 않음 | SKILL.md 분기표, specification-gates.md | 22, 24를 엄격한 1, 25와 비교한다. |
| 읽기 전용 기본, 승인된 저장, 정확한 실행 권한 | SKILL.md, decision-map.md | 2, 7, 14, 20, 23–25. |
| greenfield/brownfield, 기준 상한, 초기 상태 | specification-gates.md, scoring-and-state.md | 1, 3, 6. |
| 구성요소 1–6개 확인, 활성·보류 범위, 가장 약한 빈틈 선택 | specification-gates.md | 1, 6. |
| 기존 공식·구성요소 최솟값·확신 상한·전체 정밀도 | B0에서 보존한 scoring-and-state.md | 1, 3, 6. 수치 규칙은 바뀌지 않았다. |
| 근거·답 정규화, 증가할 수 있는 불확실성과 모순 처리 | SKILL.md, specification-gates.md, scoring-and-state.md | 1, 3, 6. |
| 실제 주 세션 질문 UI, 호스트 모드 조건, 자유 입력·대체 절차 | ask-ui.md, SKILL.md | 4, 8–11. 사람 참여 검증은 남아 있다. |
| 위임 가정, 에이전트 연속 결정 세 번 제한, 사용자 확인 | auto-answer-uncertain.md, specification-gates.md | 1, 3. |
| 단계 구간 통과·가정 제안 시 독립 네 관점 검토 | lateral-review-panel.md, specification-gates.md | 6, 13. 실제 격리·대체 절차 검증은 남아 있다. |
| 결정 주체를 바꾸지 않는 선택적 greenfield 조사 | auto-research-greenfield.md, specification-gates.md | 6, 13과 전환 전 대표 greenfield 실행. |
| 10라운드 확인, 20라운드 제한, 조기 종료·미완료 상태 | specification-gates.md | 1, 2, 7, 25. |
| 목표·명세 승인, 별도 실행 연결, 완전한 명세 필드 | specification-gates.md, spec-template.md | 3, 7, 25. |
| 지도 목적지, 답의 색인, 이름 링크, 미명세·범위 밖 구분 | decision-map.md | 14, 16–20. |
| 너비 우선 지도 작성, 생성 후 연결, 지도 작성 중 사람 티켓 미해결 | decision-map.md | 14, 20. |
| 독립 조사 예외 외 세션당 티켓 하나, AFK/HITL 결정 주체 | decision-map.md, research.md, prototype.md | 15, 16, 20, 24. |
| 기존 경로·유형·상태, 일시 잠금 추적 제외 | local-tracker.md, scripts/local_lock.py | 17–19와 복사한 실제 잠금 검사. |
| 원자적 잠금, 상태 재읽기, 손상 잠금, 소유권·강제 해제 승인 | 보존한 scripts/local_lock.py와 local-tracker.md | test_local_lock.py. 모델의 실제 조율 사례 19는 미검증이다. |
| 티켓→지도 잠금 순서, 지도 재읽기·병합, 잠금 안 번호 생성 | local-tracker.md, decision-map.md | 19, 28. 도우미 검사만으로 모델의 트랜잭션 준수를 증명하지 않는다. |
| 조사 근거, 시안에 대한 사람 반응, 선행 작업 | research.md, prototype.md와 두 분기, decision-map.md | 16, 20. |
| 용어집 갱신, ADR 기준·형식, 공유 파일 직렬 처리 | 보존한 domain-modeling.md, context-format.md, adr-format.md | 15, 20. |
| 외부 트래커 금지, 답 보존, 삭제 전 승인 | local-tracker.md, decision-map.md | 14, 17–20. |
| 리비전 기반 재사용, 압축·재개 대조, 기능·참조 누락 | SKILL.md와 기존 실패 계약 | 5, 8, 12, 16, 26–28. |
| 자체 완결 패키지, 조건부 영어 읽기, 완전한 한국어 미러 | 후보 트리, 기존 패키징 도구·미러 검사 | 로컬 메타데이터·패키지·링크·미러·입력 검사. |

## 해석 경계

정성적인 불확실성 재평가는 모든 결정 반복에 속한다. 수치 명세 평가는 엄격한 인터뷰나 실행 가능한 명세
요청에만 적용한다. 저장과 수치 기준은 독립적이다. 지도가 있다고 엄격한 평가를 요청한 것이 아니며,
엄격한 인터뷰가 길어졌다고 파일 쓰기를 허용한 것도 아니다. 조사 사실은 사람 질문 없이 해결할 수 있지만
사람 판단은 그렇지 않다.

원래 필드와 트랜잭션 수단을 유지한다. 의미 판단은 주 모델과 사람이 맡고, 결정적 검사는 도우미의 정확한
동작과 평가 입력 무결성만 확인한다. 후보를 준비했다고 설계 가정이 검증된 동작 보장으로 바뀌지는 않는다.

## 채택에 필요한 남은 근거

실제 사람 질문 흐름, 엄격한 종료, 재개 상태, 시안 반응, 지도 동시 쓰기, 두 대상 모델 호스트의 스킬 탐색이
기본 전환 조건으로 남아 있다. 입력과 원본 참조 전체를 고정해 바뀐 경로를 B0와 비교한다.
도구·작업 에이전트·재시도·사람 응답 대기까지 입력·출력 사용량과 경과 시간을 기록한다.
소스 바이트로 토큰 절감을 추론하거나 누락된 측정값을 0으로 세지 않는다. 결과를 보고 실패 기준을 느슨하게 바꾸지 않는다.

사용자는 2026-09-26에 후보까지만 준비하도록 선택했다. 이번 전달에는 기본 스킬 교체나 버전 변경이 없다.
이후 승인된 평가에서 남은 근거를 확보한 뒤 전환할 수 있다.
