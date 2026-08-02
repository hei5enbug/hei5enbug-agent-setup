---
name: deep-interview
description: >-
  Conduct a rigorous Socratic requirements interview before implementation. Cover topology
  discovery, evidence-backed questions, ambiguity scoring, contradiction handling, closure gates,
  and an execution-ready specification. Use when the user asks for a deep interview, says not to
  assume, has a vague or high-impact idea, wants requirements validated before work starts, or asks
  for an Ouroboros/Socratic discovery process. Works across agent hosts with structured-question,
  exploration, independent-worker, and plain-text fallbacks.
compatibility: >-
  Works in any conversational agent host. Structured questions, repository exploration, independent
  workers, external research, and persistence are optional capabilities with in-context fallbacks.
---

# Deep Interview

Turn an uncertain idea into an execution-ready specification.
Ask one high-leverage question at a time, verify discoverable facts before asking, and do not implement until the user approves the final scope.

The accompanying `README.ko.md` is a Korean translation kept synchronized with this file for human readers. Do not read or use it during execution.

Read these resources only when their stage is reached:

- [`references/ask-ui.md`](references/ask-ui.md): before every user question.
- [`references/scoring-and-state.md`](references/scoring-and-state.md): before initial scoring and whenever scores or state change.
- [`references/spec-template.md`](references/spec-template.md): when producing the final specification.
- [`references/auto-research-greenfield.md`](references/auto-research-greenfield.md): when optional independent research can improve a greenfield question.
- [`references/auto-answer-uncertain.md`](references/auto-answer-uncertain.md): when the user explicitly delegates a decision.
- [`references/lateral-review-panel.md`](references/lateral-review-panel.md): at ambiguity milestones or before accepting agent-supplied assumptions.

## Non-Negotiable Contract

- Ask exactly one question per round.
- Keep all user-facing questions in the main conversation. Supporting agents may return evidence but must not question the user.
- Remain read-only during discovery. The only permitted write is a final specification or resumable state file at a user-approved path.
- Match the user's language. Preserve code identifiers, paths, commands, schema keys, and fixed status tokens.
- Separate facts from decisions. Discover facts from available evidence; ask the user about preferences, tradeoffs, scope, and intended behavior.
- Cite brownfield evidence with paths, symbols, commands, or observed behavior.
- Treat ambiguity as non-monotonic. Contradictions, evasive answers, and scope expansion may raise it.
- Require explicit user approval before handing the specification to any execution workflow.
- Never require a particular vendor, tool name, model, or subagent implementation.

## Capability Routing

At startup, identify available capabilities without assuming product names:

1. **Structured ask**: use the host's native single-question UI when available. Before using the plain-text fallback, follow any host-specific mode or setup gate in `references/ask-ui.md`.
   If the gate requires user action, explain it and end the turn until the user resumes in the supported mode.
2. **Read-only exploration**: use repository search/read tools; if unavailable, ask only for facts that cannot be observed.
3. **Independent reasoning**: use isolated read-only subagents when available; otherwise run the same persona passes sequentially in the main context.
4. **Parallelism**: parallelize independent evidence gathering when supported; sequential execution must produce the same logical result.
5. **Persistence**: keep state in conversation by default. Write state only when the user requests resumability and approves the path.

Capability absence changes efficiency, not the interview contract.

## Phase 0: Establish the Run

1. Parse the idea, explicit constraints, desired depth, and requested output.
2. Resolve the ambiguity threshold:
   - Honor a user threshold only if it is at least as strict as 1% ambiguity.
   - Cap looser thresholds at `0.01` and record that the value was capped.
   - Otherwise use `0.01`.
3. Emit the threshold and source before the first question:

```text
Deep Interview threshold: <percent> (source: <source>)
```

4. Classify the task:
   - **Brownfield** when existing artifacts are being changed.
   - **Greenfield** when no relevant existing implementation constrains the idea.
5. For brownfield work, inspect the smallest relevant source surface before asking questions. Summarize only durable facts and unresolved gaps.
6. Normalize very large inputs into a prompt-safe summary that preserves intent, constraints, decisions, evidence, and non-goals.
7. Initialize the state defined in `references/scoring-and-state.md`.

## Round 0: Lock the Topology

Enumerate 1-6 top-level components that can succeed or fail independently. Group implementation details beneath outcomes rather than treating every task as a component.

Ask the user to confirm whether components should be added, removed, merged, split, or deferred. Do not score this round. Store active and deferred components with evidence and a deferral reason.

Do not let depth in one component conceal ambiguity in another. Every active component must eventually satisfy all applicable clarity dimensions.

## Interview Loop

Repeat until the threshold is met, the user exits early, or the round cap is reached.

### 1. Select the Next Gap

Choose the active component and clarity dimension with the lowest score. Rotate across similarly weak components so one workstream does not monopolize the interview.

Prioritize questions in this order when applicable:

1. Ontology: what the core entities and relationships actually are.
2. Goal: what observable outcome must happen.
3. Constraints: boundaries, compatibility, risk, non-goals, and irreversible choices.
4. Acceptance: evidence or tests that prove success.
5. Context: how brownfield behavior and ownership must be preserved.

Ask about one decision only. Do not disguise multiple questions with conjunctions or nested bullets.

### 2. Gather Evidence First

Before asking about a potentially discoverable fact:

- Search the relevant source, configuration, history, documentation, or runtime output.
- State the observed evidence and ask only for confirmation when interpretation is still required.
- If evidence conflicts, present the conflict rather than choosing silently.
- For current external facts, use authoritative research when available; distinguish sourced facts from inference.

### 3. Form the Question

Read `references/ask-ui.md`. Include:

```text
Round <n> | Component: <name> | Targeting: <dimension> | Why now: <reason> | Ambiguity: <score>%
```

Offer 2-4 mutually distinct options when structured choices are useful. Put the strongest evidence-backed recommendation first, explain its tradeoff, and always allow free text.
Do not force choices when an open question will produce better information.

### 4. Normalize the Answer

For a substantive free-text answer, restate only what matters under these fields:

- Decision
- Reasoning
- User-stated constraints
- User-stated non-goals
- Verified context

Ask the user to confirm the interpretation before scoring if any meaning could have been lost. Do not add unstated requirements.

If the user delegates the choice, use `references/auto-answer-uncertain.md`.
Carry the result as an explicit assumption, cap confidence-derived clarity as described in the scoring reference, and require user confirmation before that assumption can cross the final threshold.

### 5. Score and Report

Read `references/scoring-and-state.md`. Score every active component, update established facts and ontology, then report:

- dimension scores and remaining gaps;
- prior and new ambiguity;
- any contradiction, inconsistency, evasiveness, or scope-expansion trigger;
- the component/dimension targeted next;
- active and deferred component coverage.

Never lower ambiguity merely because another round occurred.

### 6. Apply Round Controls

- After 3 consecutive agent-resolved decisions, route the next decision directly to the user.
- At round 10, offer a concise continue-or-stop checkpoint.
- At round 20, stop questioning and produce a risk-marked specification.
- If the user exits early, preserve unresolved gaps and mark the ambiguity gate as failed.

## Independent Review

Run the lateral review in `references/lateral-review-panel.md` when ambiguity crosses a milestone band or before adopting an agent-supplied assumption.

Use independent contexts when the host supports them. Do not leak the intended conclusion into reviewer prompts.
If isolation or subagents are unavailable, perform the same researcher, contrarian, simplifier, and architecture lenses sequentially.

Fold only the highest-leverage validated finding into the next single question. Reviewers cannot change scope, approve assumptions, or declare completion.

## Closure Gates

When ambiguity reaches the threshold:

1. **Coverage audit**: verify every active component has a clear goal, constraints, acceptance criteria, and brownfield context when applicable.
2. **Contradiction audit**: enumerate unresolved conflicts, uncertain external dependencies, and unverified assumptions.
3. **Goal restatement**: restate the entire intended outcome in one sentence and ask for explicit confirmation.
4. **Specification approval**: render the specification using `references/spec-template.md` and ask whether it accurately captures the agreement.
5. **Execution bridge**: ask separately whether to save, plan, execute, hand off, or stop. No execution option is implicit.

Only label the ambiguity gate `passed` when the numeric threshold and all closure gates pass. Early exits and hard-cap outcomes remain `risk-accepted` or `pending`.

## Failure Handling

- If a tool or subagent fails, continue with the equivalent in-context path and record the degraded capability internally.
- If evidence is unavailable, label the item `unverified`; do not invent a fact.
- If the user contradicts an established fact, preserve both versions, mark the fact disputed, lower the affected score, and target the conflict next.
- If scope expands, update topology before continuing depth questions.
- If the user asks to skip questions, produce a risk-marked draft specification and request execution approval separately.

## Completion Checklist

- Topology was explicitly confirmed.
- Every active component was covered independently.
- Every question addressed one decision.
- Discoverable facts were researched before being asked.
- Scores cite answer or evidence changes.
- Contradictions and scope expansions could raise ambiguity.
- Agent-supplied assumptions did not silently cross the threshold.
- The final goal and specification were explicitly confirmed.
- Execution remained separate and required approval.
- The workflow still functioned when structured UI, parallelism, subagents, or persistence were absent.
