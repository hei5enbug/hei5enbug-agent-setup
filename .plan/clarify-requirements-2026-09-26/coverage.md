# Contract coverage for the integration candidate

The baseline is the commit recorded in baseline.json. This is a source-to-candidate trace, not a claim that
every behavior has passed native execution. Original evaluation IDs map through evals/source-cases.json.
Candidate cases 1–13 come from Deep Interview and 14–20 from Decision Navigator; 21–29 cover integration.

| Required behavior | Candidate authority | Cases or direct checks |
|---|---|---|
| Explicit invocation; no unsolicited interview offer | SKILL.md, Establish the requested outcome; agents/openai.yaml | 21; routing corpus still requires native evaluation. |
| Goals, constraints, acceptance, decisions, and non-engineering destinations | SKILL.md; references/decision-map.md | 1–3, 14, 20, 22. |
| One loop of evidence, uncertainty, one human question, verification, and recording | SKILL.md, One clarification loop | 1, 14–20, 22–25. |
| No numeric gate on ordinary decisions solely because a map exists | SKILL.md routing table; specification-gates.md | 22, 24; compare against strict cases 1, 25. |
| Read-only default; approved persistence and exact execution authority | SKILL.md; decision-map.md | 2, 7, 14, 20, 23–25. |
| Greenfield/brownfield, threshold cap, initial state | specification-gates.md; scoring-and-state.md | 1, 3, 6. |
| Confirm 1–6 components, active/deferred coverage, weakest gap selection | specification-gates.md | 1, 6. |
| Existing numeric formulas, component minima, confidence cap, full precision | scoring-and-state.md preserved from B0 | 1, 3, 6; numeric rules are unchanged. |
| Evidence/answer normalization and non-monotonic contradiction handling | SKILL.md; specification-gates.md; scoring-and-state.md | 1, 3, 6. |
| Native main-session ask UI, host mode gates, free text and fallback | ask-ui.md; SKILL.md | 4, 8–11; human/operator lane pending. |
| Opt-out assumptions, three-agent-decision limit, user confirmation | auto-answer-uncertain.md; specification-gates.md | 1, 3. |
| Independent four-lens review at milestone crossings or proposed assumptions | lateral-review-panel.md; specification-gates.md | 6, 13; actual isolation/fallback remains to be exercised. |
| Optional greenfield research without changing decision ownership | auto-research-greenfield.md; specification-gates.md | 6, 13 and representative greenfield execution before promotion. |
| Round 10 checkpoint, round 20 cap, early exit and incomplete-result status | specification-gates.md | 1, 2, 7, 25. |
| Goal/spec approval, separate execution bridge, complete spec fields | specification-gates.md; spec-template.md | 3, 7, 25. |
| Map destination, index-only answers, named links, fog/out-of-scope distinction | decision-map.md | 14, 16–20. |
| Chart breadth-first, create-then-wire, no human-ticket resolution while charting | decision-map.md | 14, 20. |
| One ticket per session except independent research; AFK/HITL ownership | decision-map.md; research.md; prototype.md | 15, 16, 20, 24. |
| Existing directories, types/statuses, ignore transient claims | local-tracker.md; scripts/local_lock.py | 17–19; copied real lock tests. |
| Atomic claim, status reread, corrupt lock handling, ownership and force-release approval | scripts/local_lock.py and local-tracker.md preserved | test_local_lock.py; native orchestration case 19 remains pending. |
| Ticket-before-map lock order, map reread/merge, numbered creation under lock | local-tracker.md; decision-map.md | 19, 28; helper tests do not prove model transaction adherence. |
| Research evidence, prototype human reaction, prerequisite tasks | research.md; prototype.md and its two branches; decision-map.md | 16, 20. |
| Glossary updates, ADR criteria/formats, shared-file serialization | domain-modeling.md; context-format.md; adr-format.md preserved | 15, 20. |
| No external tracker; preserve answers and approval before deletion | local-tracker.md; decision-map.md | 14, 17–20. |
| Revision-aware reuse, compaction/resume reconciliation, missing capability/reference | SKILL.md; existing failure contracts | 5, 8, 12, 16, 26–28. |
| Self-contained package, conditional English reads, complete Korean mirrors | Candidate tree; existing package helper and mirror checks | Local metadata, package, links, mirror and fixture checks. |

## Interpretation boundaries

Qualitative reassessment belongs to every decision loop. Numeric specification scoring applies only to a
rigorous interview or an execution-ready specification request. Persistence and quantitative gates are
independent: a map does not itself request strict scoring, and a long strict interview does not itself
authorize file writes. A research fact can resolve without a human question; a human judgment cannot.

The original source fields and transaction primitives are retained. Meaning judgments remain with the
main model and human; deterministic tests check exact helper behavior and fixture integrity only.
Candidate preparation does not automatically turn a design assumption into a verified behavior guarantee.

## Adoption evidence still required

Native human question flows, strict closure, resumed state, prototype feedback, concurrent map writes,
and skill discovery on both supported target-model hosts remain promotion gates. Evaluate the changed
paths against B0 with frozen inputs and the complete original reference closures. Record full input/output
usage and wall time, including tools, workers, retries, and human wait time. Do not infer token savings
from source bytes or count missing telemetry as zero. Do not relax failed criteria after observing results.

The user selected candidate-only preparation on 2026-09-26. No default replacement or version bump is part
of this delivery. A later approved evaluation can supply the missing evidence before promotion.
