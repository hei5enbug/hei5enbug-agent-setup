# 사양서 템플릿

> 영어 원본: [spec-template.md](spec-template.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

수치 준비 상태와 종료 감사를 통과한 뒤 이 템플릿을 사용한다.
비어 있는 선택 섹션은 생략할 수 있지만 해결되지 않은 위험은 생략하지 않는다.

```markdown
# Deep Interview Spec: <제목>

## Metadata
- Interview ID: <id>
- Project type: <greenfield|brownfield>
- Threshold: <값과 출처>
- Final ambiguity: <값>
- Gate status: <passed|risk-accepted|pending>
- Active/deferred components: <개수>
- Degraded capabilities: <없음 또는 목록>

## Goal
<전체 결과를 설명하는 확인된 한 문장.>

## Topology
| Component | Status | Outcome | Evidence |
|---|---|---|---|

## Constraints
- <확인된 경계, 호환성 규칙, 위험 통제 또는 보존 요구사항>

## Non-Goals
- <명시적으로 제외한 결과>

## Acceptance Criteria
- Given <선행 조건>, when <동작>, then <관찰 가능한 결과>.

## Brownfield Context
- <경로·심볼·런타임 근거와 보존해야 할 동작>

## Ontology
| Entity | Type | Meaning | Relationships |
|---|---|---|---|

## Assumptions and Decisions
| Item | Status | Source | Consequence |
|---|---|---|---|

## Deferrals
| Component or decision | Reason | Re-entry condition |
|---|---|---|

## Risks and Open Questions
- <해결되지 않은 충돌, 외부 의존성 또는 검증 공백>

## Verification Plan
- <각 조건을 증명하는 테스트, 검사, 지표 또는 아티팩트>

## Execution Boundary
- Approved next action: <save|plan|execute|handoff|stop|pending>
- Allowed scope: <명시적 범위>
- Prohibited changes: <명시적 제외>

## Interview Record
| Round | Component | Target | Confirmed decision | Evidence |
|---|---|---|---|---|
```

완료 전에 모든 완료 조건이 활성 구성 요소와 연결되고 모든 활성 구성 요소에 조건이 하나 이상 있는지 확인한다.
추론한 가정과 사용자가 확인한 결정을 눈에 보이게 구분한다.
