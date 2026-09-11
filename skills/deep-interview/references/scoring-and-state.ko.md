# 점수와 상태

> 영어 원본: [scoring-and-state.md](scoring-and-state.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

최초 점수 계산 전과 인터뷰 상태가 바뀔 때마다 이 참조를 읽는다.

## 상태 형태

사용자가 저장을 요청하지 않으면 다음 논리 상태를 대화에 유지한다.

```json
{
  "interview_id": "<id>",
  "type": "greenfield|brownfield",
  "language": "<language>",
  "initial_idea": "<prompt-safe summary>",
  "threshold": 0.01,
  "threshold_source": "default|user|user-capped",
  "rounds": [],
  "topology": {"status": "pending|confirmed", "components": [], "deferrals": []},
  "established_facts": [],
  "ontology_snapshots": [],
  "current_ambiguity": 1.0,
  "weakest_component_id": null,
  "weakest_dimension": null,
  "agent_answer_streak": 0,
  "degraded_capabilities": [],
  "gate_status": "pending|passed|risk-accepted"
}
```

활성 구성 요소마다 `id`, `name`, `description`, `evidence`, `status`와 적용되는 각 차원의 점수를 저장한다.
각 라운드에는 질문, 확인한 답, 대상, 근거, 이전·새 점수, trigger와 온톨로지 변경을 저장한다.

## 차원

`0.0`에서 `1.0`으로 점수를 매긴다. 근거가 있는 이유 한 문장과 `0.9` 미만일 때 구체적인 공백을 둔다.

- **Goal**: 결과와 핵심 엔터티 관계가 모호하지 않다.
- **Constraints**: 경계, 위험, 호환성, 비목표와 되돌릴 수 없는 결정이 명시돼 있다.
- **Acceptance**: 검토자가 관찰 가능한 근거로 성공을 확인할 수 있다.
- **Context**: 브라운필드 소유권, 기존 동작, 의존성과 보존 요구사항을 이해했다.

활성 구성 요소마다 독립적으로 점수를 매긴다. 차원의 전체 값은 모든 활성 구성 요소에서 해당 차원의 최솟값이다.
가중 평균이나 평균 대안은 없다. 구성 요소 하나가 빠지면 전체 차원이 낮게 유지되며 같은 입력은 같은 결과를 낸다.

## 공식

- 그린필드: `ambiguity = 1 - (goal * 0.40 + constraints * 0.30 + acceptance * 0.30)`
- 브라운필드: `ambiguity = 1 - (goal * 0.35 + constraints * 0.25 + acceptance * 0.25 + context * 0.15)`

표시할 때만 소수 둘째 자리로 반올림하고 내부에서는 전체 정밀도를 유지한다.

## 비단조 trigger

다음 trigger가 생기면 별도 벌점을 더하지 않고 영향을 받는 구성 요소와 차원의 점수를 낮춘다.

- `contradiction`: 확인된 사실과 충돌한다.
- `inconsistency`: 요구사항을 함께 만족할 수 없다.
- `evasive`: 답이 대상 공백을 해결하지 않는다.
- `scope_expansion`: 새 결과, 구성 요소, 엔터티, 통합 또는 제약이 생겼다.

trigger가 생기면 이전 점수, 새 점수, 영향을 받은 구성 요소와 차원, 근거와 다툼이 있는 사실을 기록한다.
다른 확인 근거가 손실을 실제로 상쇄하지 않으면 전체 모호성이 높아져야 하며 예외는 설명한다.

## 에이전트가 제공한 답

에이전트가 추론한 답은 사용자 결정이 아니라 가정이다. 신뢰도가 높고 불확실성을 무시할 수 있는 경우가
아니면 영향을 받는 점수의 상한을 `0.85`로 둔다. 신뢰도가 높은 가정도 실행이 최종 임계값을 넘으려면
사용자가 명시적으로 확인해야 한다.

## 온톨로지 추적

핵심 도메인, 지원 엔터티와 외부 엔터티를 필드 및 관계와 함께 추적한다.
각 라운드를 이전 snapshot과 비교한다.

- stable: 같은 엔터티와 의미
- changed: 이름이 바뀌거나 형태가 실질적으로 바뀜
- new: 이번 라운드에 도입
- removed: 명시적으로 제거되거나 대체됨

온톨로지가 불안정하면 기능 질문보다 식별과 관계 질문을 먼저 한다.

## 단계

- `initial`: 모호성이 `0.60`보다 높다.
- `progress`: `0.60` 이하이고 `0.30`보다 높다.
- `refined`: `0.30` 이하이고 임계값보다 높다.
- `ready`: 임계값 이하다.

어느 방향이든 단계가 바뀌면 다음 질문 전에 독립 검토를 실행한다.

## 진행 보고서

차원, 점수, 가중치, 가중값과 공백을 간결한 표로 보고한다. 이전·새 모호성, 활성·보류 범위,
trigger, 온톨로지 변경과 다음 대상을 이어서 밝힌다. 식별자와 수치는 유지하고 설명을 사용자 언어로 번역한다.
