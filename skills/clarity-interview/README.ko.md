# Clarity Interview (명확화 인터뷰 스킬)

이 스킬은 모호하거나 중요한 요청을 바로 실행하지 않고, 목표·맥락·범위·제약·성공 기준·리스크를 먼저 질문으로 명확히 만든 뒤 실행 가능한 **Clarity Brief**로 정리합니다. 개발 요청뿐 아니라 리서치, 문서 작성, 의사결정, 커뮤니케이션, 운영 이슈, 업무 계획, 개인 작업 정리에도 사용할 수 있습니다.

## 목적

- 사용자의 요청 뒤에 있는 실제 목표와 기대 결과를 확인합니다.
- 실행 전에 범위, 산출물 형식, 이해관계자, 제약, 리스크를 명확히 합니다.
- 불필요한 장문 인터뷰가 아니라 결과를 바꾸는 핵심 질문만 묻습니다.
- 고위험이거나 되돌리기 어려운 작업은 Clarity Brief 확인 전 실행하지 않습니다.

## 생성 파일

문서는 사용자가 현재 요청 또는 이전 대화에서 **명시적으로 지정한 경로**에만 생성됩니다. 경로가 명시되지 않은 경우 파일을 만들지 않고 질문을 대화에 직접 제시하며, 사용자가 디스크에 저장하기를 원하면 저장할 경로를 요청합니다. `.specs/`, `.plans/`, `clarity-brief.md`, `requirements-<slug>.md` 같은 기본 경로를 임의로 추론하거나 디렉터리를 자동 생성하지 않습니다.

## 사용 시점

- 목표, 산출물, 대상 독자, 성공 기준이 불명확할 때
- 요청이 여러 방식으로 해석될 수 있을 때
- 결과가 의사결정, 문서화, 커뮤니케이션, 실행 계획에 재사용될 때
- 시간·비용·품질·리스크·이해관계자 사이의 트레이드오프가 있을 때
- 사용자가 “먼저 정리해줘”, “생각을 도와줘”, “계획을 세워줘”, “비교해줘”, “추천해줘”라고 요청할 때

단순 번역, 사소한 형식 수정, 명확한 단답형 질문, 낮은 위험의 뻔한 작업에는 전체 인터뷰를 사용하지 않습니다. 이 경우 최대 한 가지 질문만 하거나 명시적 가정을 적고 진행합니다.

## 작업 흐름

1. **요청 재진술**: 사용자의 요청을 1–2문장으로 다시 정리합니다.
2. **작업 분류**: task type, risk level, reversibility, affected scope, expected output을 판단합니다.
3. **알려진 사실 정리**: 사용자가 이미 제공한 정보를 중복 질문하지 않도록 정리합니다.
4. **모호성 식별**: 결과를 바꿀 수 있는 누락 정보와 상충 가능성을 찾습니다.
5. **핵심 질문 생성**: 아래 Exact Per-Question Format에 맞춰 3–5개의 고영향 질문만 작성합니다.
6. **답변 반영**: 답변을 결정 사항, 가정, 미해결 질문으로 변환합니다.
7. **Clarity Brief 작성**: 실행 가능한 brief와 다음 행동 계획을 만듭니다.
8. **모호성 점수화**: 0.0–1.0 점수로 진행 가능 여부를 판단합니다.
9. **확인 게이트**: 고위험·파일 수정·시스템 변경 전에는 사용자의 명시적 승인을 받습니다.

## 정확한 질문 형식 (Exact Per-Question Format)

각 질문은 반드시 아래 형식을 준수해야 합니다. 질문/선택지/답변란 형태는 모든 문서에서 동일하게 유지합니다.

## 질문 N: 주제

질문이 왜 필요한지 설명합니다.
답변에 따라 목표, 범위, 산출물, 접근 방식, 리스크, 성공 기준 중 무엇이 달라지는지 설명합니다.
각 선택지가 갖는 장점과 단점을 중립적으로 설명합니다.
이미 사용자가 제공한 정보와 연결해 중복 질문을 피합니다.
이 질문에 답하지 않으면 어떤 오해나 재작업이 발생할 수 있는지 설명합니다.
필요하면 추천 선택지의 이유와 트레이드오프도 간단히 설명합니다.

A) 선택지 A 설명
B) 선택지 B 설명 (추천)
C) 선택지 C 설명
D) 직접 입력 / Custom

**답변 / Your answer:**
<!-- 아래의 빈 공간에 답변을 입력해 주세요 -->



## Clarity Brief 구조

답변을 받은 뒤에는 아래 구조로 실행 가능한 brief를 작성합니다. 해당하지 않는 섹션은 짧게 `Not applicable`이라고 적습니다.

```md
# Clarity Brief

## 1. Restated Request
## 2. Intended Goal
## 3. Audience / User
## 4. Context
## 5. Scope
## 6. Non-goals
## 7. Confirmed Requirements
## 8. Assumptions
## 9. Open Questions
## 10. Constraints
## 11. Options Considered
## 12. Recommended Approach
## 13. Risks
## 14. Success Criteria
## 15. Verification Method
## 16. Next Action Plan
## 17. Ambiguity Score
```

## 모호성 점수

- `0.00 - 0.20`: 진행 가능
- `0.21 - 0.40`: 명시적 가정과 함께 진행 가능
- `0.41 - 0.70`: 한 번 더 집중 질문 필요
- `0.71 - 1.00`: 아직 과소명세 상태이므로 진행하지 않음

평가 기준은 goal clarity, scope clarity, audience clarity, output clarity, context clarity, constraint clarity, success criteria clarity, risk clarity, decision/action clarity, verification clarity입니다.

## Confirmation Gate

고위험 작업, 되돌리기 어려운 작업, 파일 수정, 시스템 변경, 공개 발행, 의사결정 확정 전에는 Clarity Brief를 보여주고 명시적 승인을 받아야 합니다. `승인합니다`, `확인했습니다`, `네, 이대로 진행하세요`, `Approved`, `Proceed with this brief`처럼 진행 의사가 분명한 답변만 승인으로 봅니다. 침묵, 부분 피드백, 단순 토론은 승인으로 간주하지 않습니다.

## 완료 상태

마지막에는 아래 중 하나의 상태로 끝냅니다.

- `Ready to execute`
- `Ready to draft`
- `Ready to research`
- `Ready to decide`
- `Ready to plan`
- `Needs one more clarification round`
- `Blocked by unresolved decision`
