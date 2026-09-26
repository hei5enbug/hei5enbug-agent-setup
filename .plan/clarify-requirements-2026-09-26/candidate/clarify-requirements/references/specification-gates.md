# Strict specification gates

Use these controls inside the common clarification loop for a rigorous interview or execution-ready
specification. They do not apply merely because an ordinary decision uses a map. For a mapped specification,
name the active scope before scoring and distinguish ticket readiness from the entire destination.

## Establish and confirm topology

Load `scoring-and-state.md` before initial scoring. Resolve the ambiguity threshold to `0.01`: honor an
explicit stricter threshold, cap a looser value at `0.01`, and record the source or cap. Before the first
question emit `Deep Interview threshold: <percent> (source: <source>)`; retain this compatibility label.
Classify greenfield/brownfield and inspect the smallest relevant existing source surface for brownfield work.

Enumerate 1–6 top-level components that can independently succeed or fail. Group implementation details
beneath outcomes. Ask the user to confirm additions, removals, merges, splits, and deferrals. This is Round 0;
do not score it. Record active/deferred components, evidence, and reasons. Cover every applicable clarity
dimension of every active component; depth on one never compensates for an uncovered component.

## Use evaluation to choose the next question

Use the common loop in `../SKILL.md`; do not start a second interview procedure. Select the lowest-scoring
active component/dimension and rotate across similarly weak components. Prioritize ontology (entities and
relationships), goal, constraints, acceptance, then brownfield context when applicable.
One question concerns one decision; conjunctions and nested bullets must not disguise multiple questions.

Apply `ask-ui.md` before each question or confirmation, using the active host's supported tool and mode.
Include `Round <n> | Component: <name> | Targeting: <dimension> | Why now: <reason> | Ambiguity: <score>%`.
When useful, offer distinct choices in evidence-backed recommendation order with short tradeoffs and free
text. Use an open question when choices would reduce information. All asks remain in the main session.

After substantive free text, extract Decision, Reasoning, User-stated constraints, User-stated non-goals,
and Verified context. Confirm interpretation before scoring if meaning could have been lost. Do not add
unstated requirements. For an explicitly delegated choice use `auto-answer-uncertain.md`; retain the result
as an assumption and apply the confidence cap and confirmation rule in `scoring-and-state.md`.

Reapply the scoring contract whenever state changes. Score every active component, update facts and
ontology, and report dimension scores/gaps, prior/new ambiguity, contradiction/inconsistency/evasiveness/
scope-expansion triggers, the next target, and active/deferred coverage. Keep full numeric precision;
display rounding does not decide readiness. Elapsed rounds never justify lowering ambiguity.

If an answer disputes an established fact, retain both versions, mark it disputed, lower the affected
score, and target the conflict. Update topology before pursuing expanded scope.
For a greenfield question that benefits from independent research, use `auto-research-greenfield.md`;
its capability is optional and never replaces the user's decision.

## Review and round controls

Crossing an ambiguity milestone band in either direction or proposing an agent-supplied assumption
triggers `lateral-review-panel.md`. Keep researcher, contrarian, simplifier, and architect lenses.
Use isolated read-only contexts when available, without revealing a desired conclusion; otherwise perform
the same lenses sequentially. Reviewers provide evidence, not user questions, approvals, or scope changes.
Fold the highest-leverage validated finding into the next single question.

After three consecutive agent-resolved decisions, route the next decision directly to the user.
At round 10, offer continue-or-stop before another question. At round 20, stop questioning and produce a
risk-marked specification. On early exit or a request to skip questions, preserve unresolved gaps and
produce a risk-marked draft; never imply the ambiguity gate passed. Request execution approval separately
when it has not already been given for the exact scope.

## Closure

When ambiguity reaches the threshold, perform these gates in order:

1. Audit every active component for goal, constraints, acceptance, and applicable brownfield context.
2. Enumerate unresolved contradictions, uncertain external dependencies, and unverified assumptions.
3. Restate the entire intended outcome in one sentence and obtain explicit goal confirmation.
4. Render `spec-template.md` and obtain explicit confirmation that the specification captures the agreement.
5. Resolve the execution bridge separately: save, plan, execute, hand off, or stop. Apply existing explicit
   authorization only to its exact approved scope; no execution choice follows implicitly from approval
   of the specification. Save only at an approved path.

Use `ask-ui.md` for the confirmations and bridge. Label the ambiguity gate `passed` only after the numeric
threshold and all closure gates pass. Early exits and capped outcomes remain `risk-accepted` or `pending`.
An unresolved mapped human decision remains open; a risk-marked draft is not a resolved ticket.

## Completion check

Confirm topology and independent component coverage; one decision per question; evidence before questions;
evidence-based scoring that can increase; confirmed assumptions before crossing readiness; required reviews
and round limits; explicit goal/specification confirmation; a separate authorized next action; and honest
fallbacks for missing UI, workers, parallelism, or persistence. A failure in any required item remains visible.
