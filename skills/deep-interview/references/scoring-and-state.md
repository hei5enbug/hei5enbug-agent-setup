# Scoring and State

Load this reference before initial scoring and whenever interview state changes.

## State Shape

Keep this logical state in conversation unless the user requests persistence:

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

Each active component stores `id`, `name`, `description`, `evidence`, `status`, and scores for every applicable dimension. Each round stores its question, confirmed answer, target, evidence, prior/new scores, triggers, and ontology changes.

## Dimensions

Score from `0.0` to `1.0` with a one-sentence evidence-based rationale and a concrete gap below `0.9`:

- **Goal**: the outcome and core entity relationships are unambiguous.
- **Constraints**: boundaries, risks, compatibility, non-goals, and irreversible decisions are explicit.
- **Acceptance**: a reviewer could verify success with observable evidence.
- **Context**: brownfield ownership, existing behavior, dependencies, and preservation requirements are understood.

Score each active component independently. Use the weakest or coverage-weighted component value for each global dimension; never average away an uncovered component.

## Formula

- Greenfield: `ambiguity = 1 - (goal * 0.40 + constraints * 0.30 + acceptance * 0.30)`
- Brownfield: `ambiguity = 1 - (goal * 0.35 + constraints * 0.25 + acceptance * 0.25 + context * 0.15)`

Round to two decimals only for display. Retain full precision internally.

## Non-Monotonic Triggers

Lower the affected component/dimension score when any trigger occurs; do not add a separate penalty:

- `contradiction`: conflicts with an established fact.
- `inconsistency`: requirements cannot hold together.
- `evasive`: the answer does not resolve the targeted gap.
- `scope_expansion`: a new outcome, component, entity, integration, or constraint appears.

When triggered, record prior score, new score, affected component/dimension, evidence, and disputed facts. Overall ambiguity should rise unless other confirmed evidence genuinely offsets the loss; explain any exception.

## Agent-Supplied Answers

An answer inferred by the agent is an assumption, not a user decision. Unless confidence is high and uncertainty negligible, cap the affected score at `0.85`. Even a high-confidence assumption must receive explicit user confirmation before it can move the run across the final threshold.

## Ontology Tracking

Track core domain, supporting, and external entities with fields and relationships. Compare each round with the prior snapshot:

- stable: same entity and meaning;
- changed: renamed or materially reshaped;
- new: introduced this round;
- removed: explicitly eliminated or superseded.

Use ontology instability as a reason to ask identity/relationship questions before feature questions.

## Milestones

- `initial`: ambiguity above `0.60`
- `progress`: `0.60` through above `0.30`
- `refined`: `0.30` through above threshold
- `ready`: at or below threshold

Crossing a band in either direction triggers independent review before the next question.

## Progress Report

Report a compact table of dimensions, score, weight, weighted value, and gap. Then state prior/new ambiguity, active/deferred coverage, any trigger, ontology changes, and the next target. Translate prose to the user's language while keeping identifiers and numeric values stable.
