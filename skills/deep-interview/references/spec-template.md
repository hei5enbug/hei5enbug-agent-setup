# Specification Template

Use this template after numeric readiness and closure audits. Omit empty optional sections; never omit unresolved risks.

```markdown
# Deep Interview Spec: <title>

## Metadata
- Interview ID: <id>
- Project type: <greenfield|brownfield>
- Threshold: <value and source>
- Final ambiguity: <value>
- Gate status: <passed|risk-accepted|pending>
- Active/deferred components: <counts>
- Degraded capabilities: <none or list>

## Goal
<One confirmed sentence describing the complete outcome.>

## Topology
| Component | Status | Outcome | Evidence |
|---|---|---|---|

## Constraints
- <Confirmed boundary, compatibility rule, risk control, or preservation requirement>

## Non-Goals
- <Explicitly excluded outcome>

## Acceptance Criteria
- Given <precondition>, when <action>, then <observable result>.

## Brownfield Context
- <Path/symbol/runtime evidence and required behavior preservation>

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
- <Unresolved conflict, external dependency, or verification gap>

## Verification Plan
- <Test, inspection, metric, or artifact that proves each criterion>

## Execution Boundary
- Approved next action: <save|plan|execute|handoff|stop|pending>
- Allowed scope: <explicit scope>
- Prohibited changes: <explicit exclusions>

## Interview Record
| Round | Component | Target | Confirmed decision | Evidence |
|---|---|---|---|---|
```

Before finalizing, verify every acceptance criterion maps to an active component and every active component has at least one criterion. Keep inferred assumptions visibly distinct from user-confirmed decisions.
