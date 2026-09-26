---
name: clarify-requirements
description: >-
  Clarify goals, requirements, and open decisions through evidence, one question at a time,
  and uncertainty reassessment. Produce confirmed decisions or an approved specification;
  optionally continue a local decision map across sessions. Use only when the user explicitly
  invokes clarify-requirements or asks to run this clarification workflow.
compatibility: >-
  Conversation works without filesystem access. Local maps require filesystem access and Python 3
  for atomic claims. Native question UI and independent workers use the documented host fallbacks.
---

# Clarify Requirements

Use English instructions only; `.ko.md` mirrors are human references. This skill is self-contained and
invokes no sibling skill. Resolve `references/` and `scripts/` from this skill's directory. Report a missing
required resource and stop its dependent action; never invent its rules.

## Establish the requested outcome

Start only on an explicit request for this workflow. An ordinary question, vague requirement, large project,
or risky change is not a trigger. Answer such requests directly without offering this workflow.
Match the user's language and preserve literal identifiers, paths, commands, schema keys, and status tokens.

Capture the goal, constraints, requested output, and existing authorization. Preserve decisions, evidence,
constraints, and non-goals when summarizing large inputs. Distinguish existing-artifact changes (brownfield)
from new work (greenfield). Resolve output from the request and any existing map's Destination; ask one
clarifying question before writes when interpretations materially differ.

| Requested operation | Read before its first dependent action |
|---|---|
| Rigorous interview or execution-ready specification | `references/specification-gates.md`; it owns numeric scoring, review, round limits, and closure. |
| Create/continue a map, including a named ticket | `references/decision-map.md` and `references/local-tracker.md` before map access. |
| Specification inside a map | Both rows; name the scored scope. One ready ticket never proves the entire destination ready. |
| One decision without a map/specification | The common loop below; do not add numeric specification gates or map overhead. |

Discovery is read-only except for authorized records, prototypes, or prerequisite tasks. Keep state in
conversation unless persistence at a stated location is requested or approved. A map request authorizes
its local workflow and stated records, not an external tracker. Complexity alone grants no write permission.
Honor valid prior authorization within its exact scope; a score, specification approval, or agent-written
note never implies permission to execute the destination.

## One clarification loop

1. **Select a gap.** Separate facts, confirmed decisions, assumptions, contradictions, non-goals, and open
   questions. Resolve prerequisites first. Strict work selects the weakest component/dimension under its
   scoring contract. Mapped work selects and claims an eligible ticket before its first action; keep that
   claim throughout its question rounds instead of selecting or claiming again on each iteration.
2. **Investigate and reassess.** Inspect relevant code, configuration, history, documents, and behavior;
   cite paths, symbols, commands, or observations. Prefer primary sources for external facts and verify
   current facts when needed. Surface conflicts and distinguish facts from inference. Read the map's
   type-specific research/prototype/task reference when applicable. Evidence may resolve an agent-only
   ticket without a human question; a human judgment requires the person's own answer.
3. **Ask one question if needed.** Ask only for unresolved judgment, intent, scope, tradeoff, or interpretation,
   never for a discoverable fact. All user questions stay in the main session. Strict work follows
   `references/ask-ui.md` for every question and confirmation, including its mode gates and fallbacks.
   Ordinary decisions use a supported question UI or a plain question followed by waiting. Give concrete
   examples for vague/conflicting answers and an evidence-backed recommendation with a short reason.
   Respect tool option limits, keep choices distinct, allow free text, and never answer for the human.
4. **Verify the answer.** Extract decision, reasoning, user constraints, non-goals, and verified context.
   If meaning could be lost, confirm interpretation before scoring or resolution; do not invent requirements.
   An explicitly delegated choice stays a visible assumption until confirmed. Strict work uses
   `references/auto-answer-uncertain.md` and the scoring contract's confidence rules.
5. **Reassess and record.** Tie uncertainty changes to evidence or answers, not elapsed rounds. Contradiction,
   inconsistency, evasiveness, or scope expansion can increase uncertainty. Keep disputed versions and update
   affected topology before pursuing expanded scope. Strict work applies its numeric updates, reporting,
   milestone review, and round controls here. Ordinary decisions state concrete gaps without invented
   numeric precision. Record each confirmed answer once; maps index their tickets. Continue within the
   requested scope and the map's session limit.

## Finish or pause

For a single decision, confirm human judgments and report the answer, evidence, uncertainty, and consequences.
Strict specifications follow every gate and template in `specification-gates.md`. Mapped work follows its
resolution transaction and completes only when the destination is clear with no open decisions or in-scope
unspecified areas. Unanswered human decisions remain open even if another ticket or a numeric score passed.

Preserve unresolved gaps on early exit or round limits and provide the strict workflow's risk-marked result
when applicable. Mark missing evidence unverified. Preserve the prescribed recovery point and locks after
uncertain map writes; do not retry an uncertain side effect or force-release an old-looking lock.
Return authorized artifact paths and verification limits. Resolve the next action separately from result
approval and execute only within explicit valid authorization.

## Context and capabilities

Reuse instructions/evidence only while revision, relevant tool contract, and available context remain valid.
Reapply rules at required steps; after changes or context loss, reload before dependent actions. Strict
scoring/UI rules must be available at every applicable action. Re-read mutable tickets/maps after their
locks are acquired regardless of earlier reads. Load relevant ticket bodies on demand, not the whole archive.

Keep the active gap and relevant evidence in context without discarding authoritative sources. Persist only
where authorized. After resume, reconcile decisions, permissions, revisions, pending actions, and open gaps
against authoritative state; stop dependent actions if recovery cannot establish them.
Workers return bounded evidence to the main session. Use required independent review contexts when available
and the documented sequential lenses otherwise. Tool/worker failure changes capability, not the contract.
Without filesystem/Python, report map access/claims unavailable; continue only conversational work that is
possible from available facts. Never pretend a claim, save, independent review, or parallel run occurred.
