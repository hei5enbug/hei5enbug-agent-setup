# Evidence and improvement candidates

The inventory covers the repository at the commit recorded in [the plan](README.md).
An observed loading rule or duplicate prompt is evidence of a cost source, not proof of runtime savings.
All optimization benefits below remain unmeasured until [validation](validation.md) passes.
F01 is a demonstrated quality-policy contradiction. F02–F03 establish reliable acceptance evidence.
F17 explicitly preserves an existing optimization rather than claiming a new defect.

## Priority and coverage

| Priority | Items | Treatment |
|---|---|---|
| P0 | F01–F03 | Correct the quality conflict and establish trustworthy comparisons first. |
| P1 | F05–F06, F08–F09, F11, F14, F25 | Evaluate repeat reads, mode-independent bodies, repeated prompt data, avoidable collection, and cache-friendly prompt ordering. |
| P2 | F04, F07, F10, F12–F13, F15–F16, F18–F24, F26–F27 | Evaluate after P1; retain baseline when benefit is small, uncertain, or offset by more reads. |
| Preserve | F17 and the final table | Keep behavior already limiting cost or protecting required outcomes. |

| Skill | Body bytes | Findings | Existing behavior to protect |
|---|---:|---|---|
| `decision-navigator` | 13,816 | F18–F19 | Map index, relevant ticket reads, atomic claims, human decisions. |
| `deep-interview` | 11,970 | F05–F07 | One question, all-component scoring, milestone review, explicit closure. |
| `docs-rewrite` | 14,091 | F16 | Meaning invariants, ambiguity, strict review, no-change outcome. |
| `document-to-confluence` | 12,151 | F20–F21 | Source adapters, normalization, full-body preservation, stored-result verification. |
| `flowchart-design` | 27,852 | F08 | Semantic graph, layout exceptions, actual rendering and export checks. |
| `orca-plugin-refresh-resume` | 7,967 | F23 | Exact-plan approval, registry identity, leases, no duplicate resume. |
| `skill-builder` | 31,229 | F01–F03, F09–F13 | Baseline isolation, exact checks, artifact review, measured adoption. |
| `suggest-commit` | 15,830 | F14–F15 | Scope, language, evidence, identifier provenance, five subjects. |
| `technical-design-writer` | 12,981 | F03, F17 | Design coverage, mode separation, terminology, consent for review. |
| `tiki-taka` | 22,846 | F22 | Independent inspection, same opponent session, delta prompts, exchange cap. |
| Standalone `omo-model-config` | 13,595 | F24 | One upstream SHA, every required source, ordered resolution, scoped writes. |

F04 applies to all descriptions. Session, agent, hook, script, asset, test, and manifest dispositions appear below
and in [inventory.json](inventory.json); absence from a skill-specific finding is not an omitted audit area.
F25–F27 extend the investigation with cache reuse, native tool discovery, and verified context recovery.
[Strategy assessment](strategy-assessment.md) maps all ten user proposals to these findings and preserved behavior.

## Quality and measurement

### F01 — The optimizer explicitly permits accuracy loss

**Evidence:** [improve_description.py](../../skills/skill-builder/scripts/improve_description.py),
`improve_description`, line 122, tells the model to keep 100–200 words “even if that reduces accuracy.”
This contradicts [Execution Methods](../../skills/skill-builder/references/execution-methods.md),
“Measurement and decision,” and the user's constraint.

**Change:** Replace the accuracy-sacrifice/word-count sentence with an explicit priority: preserve complete
trigger/non-trigger intent coverage, then produce the shortest clear description within the 1,024-character limit.
Keep conciseness as a preference; the hard length limit is not a target to fill.
`improve_description` retains its existing validity check, one retry, and rejection of an unusable candidate.
It does not gain a semantic quality judge. `run_loop` retains its existing evaluated best-score selection.
The authoring workflow then checks per-case regressions and native routing before adopting that selected description.
S1 tests prompt priorities and existing retry/rejection behavior; live quality and cost use F02–F03's gates.

### F02 — Static limits do not measure the execution cost that matters

**Evidence:** [session_context.py](../../scripts/session_context.py), `render_context`, enforces 9,000 bytes.
[quick_validate.py](../../skills/skill-builder/scripts/quick_validate.py), `validate_skill`, checks metadata.
[model_runner.py](../../skills/skill-builder/scripts/model_runner.py), `run_model`, returns response text;
it does not provide model usage or effort receipts.
The [timing contract](../../skills/skill-builder/references/schemas.md), “timing.json,” already distinguishes tokens
from character counts and supports missing measurements.

**Change:** Capture native executor usage and wall time in an evaluation workspace, together with reference reads,
tool output, retries, actual model/effort, and context restoration events.
Use an existing host runner or a wrapper with a sidecar receipt; preserve the stdin/stdout response contract.
Do not invent usage from file size or introduce a metrics framework into ordinary skill runs.
Keep unavailable metrics null and block only the claims or adoption decisions that need them.
Separate logical usage, active context, monetary cost, and completion time as defined in the strategy assessment.
Record cache reads/writes, discovery overhead, and recovery costs without assuming that caching removes input tokens.

### F03 — Current evaluation coverage cannot establish the requested guarantee

**Evidence:** Seven plugin skills have 48 behavior cases in total; only `document-to-confluence` has a dedicated
20-case trigger file. `deep-interview`, `flowchart-design`, `tiki-taka`, and standalone `omo-model-config` have no
behavior `evals/evals.json`. Several artifact-dependent cases specify `files: []` without runnable source fixtures.
Unit tests for scripts do not establish live skill adherence.

[technical-design-writer/evals/evals.json](../../skills/technical-design-writer/evals/evals.json), case 6,
expects an independent reviewer without modeling the post-draft approval branch required by
[Independent model validation](../../instructions/independent-model-validation.md), “Confirmation gate.”
[decision-navigator/evals/evals.json](../../skills/decision-navigator/evals/evals.json), case 3,
says both “resolves one ticket” and “updates only map.md”; resolution also writes the ticket.

**Change:** Preserve valid cases, correct these ambiguous/stale outcomes against the authoritative contracts,
and add actual inputs and scripted user/service responses where a task needs them.
Add missing branch coverage from the validation matrix. Record unavailable native lanes explicitly.
Do not count a simulated write, an invented input, or a structural test as a successful live end-to-end run.

## Routing and interview context

### F04 — Descriptions contain workflow detail and long synonym lists

**Evidence:** All plugin descriptions total 4,779 characters / 5,006 bytes.
The descriptions of [docs-rewrite](../../skills/docs-rewrite/SKILL.md),
[technical-design-writer](../../skills/technical-design-writer/SKILL.md),
[deep-interview](../../skills/deep-interview/SKILL.md), and [tiki-taka](../../skills/tiki-taka/SKILL.md)
include long trigger lists or execution details in frontmatter.

**Change:** Start with those four descriptions, preserving objective, positive trigger, negative boundary,
and explicit-only status. Move details already enforced by the body out of the routing description.
Retain language examples that materially improve routing.
Put the decisive use case and explicit-only/negative boundary before optional examples so catalog shortening is tested.
Compare each proposed description with its original under both portable simulation and native host routing.
Do not assume every host includes compatibility metadata or loads every description in the same way.

### F05 — Deep Interview asks for identical reference reads every round

**Evidence:** [Deep Interview](../../skills/deep-interview/SKILL.md), resource list at lines 25–26 and
“Form the Question” / “Score and Report,” plus the opening instructions of
[ask-ui.md](../../skills/deep-interview/references/ask-ui.md) and
[scoring-and-state.md](../../skills/deep-interview/references/scoring-and-state.md).
The two references total 14,128 bytes. This is a possible repeat-read payload, not a per-round token measurement.

**Change:** Load before first use and apply on every question/state update.
Reload on revision, capability, or context loss.
Put this distinction in the two references and their entrypoint read conditions.
Before each question, verify the applicable single-question, payload-field, header-length, option-range,
recommendation, free-text, and answer-wait rules from currently available instructions and the actual tool schema.
Before scoring, locate the active dimensions, minimum aggregation, weights, threshold, and milestone/closure rules.
If a required rule is unavailable, reload its reference before acting; never trust only a cached “loaded” marker.
An observable resume or compaction unconditionally invalidates reuse for the next UI/scoring action.
Scoring, all-component coverage, the current tool schema, and every required confirmation still run each time.
Test at least a 10-round interview and a continuation after compaction.

### F06 — The UI reference includes every host's implementation

**Evidence:** [ask-ui.md](../../skills/deep-interview/references/ask-ui.md), “Per-host routing,”
contains two long similar JSON examples plus Codex and inline fallback rules; the file is 10,159 bytes.

**Change:** Evaluate this only if F05's load trace still shows a material remaining UI-read cost.
Keep one `ask-ui.md` file. Read “Core principle,” “The unified question model,” the selected “Per-host routing”
branch, “Answer handling (all hosts),” and “Quick selection checklist,” including each section's full rules.
Select by actual available capabilities and higher-priority host rules; omit only unrelated host examples.
Use a full-file read when reliable section reads are unavailable or cost more overall.
Keep the common checklist and main-session rule in that same file; do not add four small adapter files.
Retain the existing Codex mode gate and fallback conditions unless a separate authorized task changes them.
Do not let a smaller entrypoint hide free text, option limits, main-session ownership, or the wait for an answer.

### F07 — Interview history and review payloads can grow across rounds

**Evidence:** [scoring-and-state.md](../../skills/deep-interview/references/scoring-and-state.md),
“State Shape” and “Ontology Tracking,” retain rounds and ontology snapshots.
[lateral-review-panel.md](../../skills/deep-interview/references/lateral-review-panel.md) accepts inherited context
but does not specify an input packet that excludes unrelated history.

**Change:** Maintain a compact current-state view plus the retained decision/evidence history.
Report changes without repeatedly reproducing the entire interview record.
Give each existing review persona the confirmed scope, current scores, relevant decisions, contradictions,
evidence locations, and changed assumptions; allow it to inspect underlying evidence.
Preserve all four lenses, their isolation where supported, milestone crossings in both directions,
all-component scoring, and the full final specification. No unapproved state-file writes or lossy history deletion.

## Skill Builder and rendering

### F08 — Renderer-specific export mechanics load for every diagram

**Evidence:** [Flowchart Design](../../skills/flowchart-design/SKILL.md), “Visual Tokens,”
“Outer Frame and Export,” and “Final Checklist,” mix shared visual requirements with SVG attributes and
the PNG two-render crop procedure in a 27,852-byte entrypoint.

**Change:** Keep semantic normalization, token roles, spacing, branch/loop exceptions, labels, and the common
completion gate in `SKILL.md`. Move SVG mechanics to `references/svg-rendering.md` and raster export mechanics
to `references/png-export.md`; load either or both according to the actual artifact.
Keep a visible delivery-format checklist in the entrypoint, so PNG work cannot skip cropping or inspection.
Preserve ±5% spacing, symmetric gaps, glyph bounds, arrowheads/shadows, accessibility, and final image inspection.
Do not replace the two-render crop with a cheaper unverified heuristic.

### F09 — Skill Builder loads a full evaluation course for a small edit

**Evidence:** [Skill Builder](../../skills/skill-builder/SKILL.md) has 524 lines.
“Test cases,” “Running and evaluating test cases,” and “Package and present” all load even though the core
already permits direct small corrections and early exit from unnecessary evaluation.

**Change:** Keep intent, authoring, automation boundaries, portability, model-adapter routing, and selection rules
in the entrypoint. Move full evaluation steps to `references/evaluation-workflow.md` and packaging detail to
`references/packaging.md`; retain the existing description-optimization reference.
Make the mode decision explicit before any dependent action.
Preserve the direct-edit route, baseline snapshot, trial budget, complete mirror updates, and unavailable-run rules.
Test small edits and formal evaluation separately; a shorter body that causes extra reference reads can lose.

### F10 — Broad schema reads load unrelated artifact formats

**Evidence:** [schemas.md](../../skills/skill-builder/references/schemas.md) has 568 lines / 18,829 bytes.
The parent skill broadly says to read it for assertions or benchmark artifacts.
The grader, comparator, and analyzer already request only their named schema section.

**Change:** Align parent instructions with the existing section-specific behavior.
Select the section by the exact artifact being written and include its field rules, not only its JSON example.
Keep `schemas.md` as the canonical file and preserve its headings and consumers.
Use range-capable reads when available; a full read remains the correctness fallback.
Do not split eight schemas into eight files before measurements show that extra file routing is useful.

### F11 — Optimizer prompts repeat the current attempt and growing history

**Evidence:** [run_loop.py](../../skills/skill-builder/scripts/run_loop.py), `run_loop`, appends the current
evaluation to `history` before calling `improve_description`.
[improve_description.py](../../skills/skill-builder/scripts/improve_description.py) includes current description,
current failures, all history descriptions/results, and the full skill.
Its invalid-description retry repeats that prompt.

**Change:** Build a lossless prompt projection: one full query dictionary keyed by stable case ID,
one current description/result block, and one result row per prior attempt and case.
Preserve distinct attempts, all train outcomes, notes, and full authoritative skill context.
Exclude the already-present current attempt from the previous-attempt rendering only.
Keep raw history/JSON output unchanged for compatibility and keep holdout data hidden.
Retain the full context for a stateless retry; reducing retry context or dropping skill sections is deferred.

### F12 — Evaluation results can be printed twice into the parent context

**Evidence:** [run_loop.py](../../skills/skill-builder/scripts/run_loop.py), `main`, prints full result JSON
even with `--results-dir`; that JSON contains all attempts and query results.
`--verbose` additionally prints per-case results.
[generate_report.py](../../skills/skill-builder/scripts/generate_report.py)
prints complete HTML when no output path is supplied.

**Change:** In the evaluation workflow, route full stdout/stderr to named artifact files and read the existing
saved result for a concise summary, failures, and evidence paths. Always give report generation an output path.
Preserve exit status, runner errors, complete raw data, and user access to the review page.
Do not change CLI defaults, remove JSON keys, print base64/HTML to the model, or silently cap diagnostic output.

### F13 — Packaging repeats validation and prints every archive member

**Evidence:** “Package and present” in [Skill Builder](../../skills/skill-builder/SKILL.md) says to run
`quick_validate.py` before `package_skill.py`; the latter runs `validate_skill` and `run_bundled_checks` itself.
`package_skill` also prints an `Added:` line for every file.

**Change:** For an immediate package operation, let the packager own pre-package validation once.
Keep `quick_validate.py` for validation without packaging and all repository development checks.
Redirect the package log to an artifact and surface the result, warnings, skipped symlinks, and failures.
Never reuse a result after file changes, skip ZIP integrity checks, or suppress a failed bundled check.
Keep atomic publication and default exclusion of evals, secrets, symlinks, and workspaces.

## Everyday skills and document conversion

### F14 — Commit context collection does unnecessary work and truncates conventions

**Evidence:** [suggest-commit](../../skills/suggest-commit/SKILL.md), “Fast Context Pass,” gathers history and
conventions before its no-change exit and uses `grep ... | head -10`.
The final constraints also say one command is usually enough while the workflow lists separate commands.

**Change:** Determine requested scope, status, and HEAD first.
Exit before style collection when no relevant change exists.
Batch independent read operations through host orchestration, with separate return codes and no `&&` dependency.
When the host cannot batch independent tools, run the same commands sequentially and preserve each result.
Replace the closing “one fast context command” wording with this capability-based procedure in the same edit.
Use `rg` for convention discovery and inspect the governing paragraphs; do not treat the first ten matches as
the complete convention. Preserve the no-HEAD and staged/path-specific branches.
Keep the smallest relevant diff when names/statistics cannot support a behavioral claim.
Expand from a search hit through relevant callers, contracts, configuration, failure paths, and tests.
Stop when the affected behavior is covered, not when a preset read quota is met; search the whole repository for
consumers of a changed public/shared contract when required. Reuse existing LSP/AST tools only where they add evidence.

### F15 — Commit rules repeat the same decisions across long prose

**Evidence:** [suggest-commit](../../skills/suggest-commit/SKILL.md), “Analyze Commit Style,”
“Use Evidence-Bound Terminology,” “Subject Order,” and “Suggest 5 Messages,” repeatedly explain identifier
slots and subject shape across 267 lines.

**Change:** Use one ordered decision table for language, required slot, provenance, prefix, and final shape.
Keep the two decisive placeholder/provenance examples and a final five-subject checklist.
Do not outsource the decision table to another file for this short everyday task.
Preserve one subject, trailer restrictions under instruction precedence, required placeholder notes,
prefix-first disclosure, all five choices, and the distinction between human-supplied values and metadata.

### F16 — Rewrite-specific examples and special modes load on every edit

**Evidence:** [docs-rewrite](../../skills/docs-rewrite/SKILL.md) contains strict review, follow-up routing,
several full examples, and repeated invariant checks; Korean runs additionally read 11,366 bytes of patterns.

**Change:** Keep the invariant table, allowed/forbidden changes, ambiguity procedure, one contrastive example,
the claim-matching workflow, output contract, and final gate in the entrypoint.
Move additional examples and strict/follow-up procedures into `references/rewrite-modes.md`, with explicit
conditions for `--strict`, input over 8,000 characters, and follow-up scope.
Evaluate whether one extra read actually helps before adoption.
Keep all Korean pattern categories available; do not choose categories from keyword matches or remove protected content.
Preserve the extra fidelity review, two-retry cap, no-change behavior, and unchanged meaning.

### F17 — Korean design writing already selects only the needed pattern table

**Evidence:** [korean-writing.md](../../skills/technical-design-writer/references/korean-writing.md),
“Translationese assessment,” explicitly reads only `A. Translationese` from the sibling pattern reference.
The skill already loads `design-documents.md` only for Create/Improve and the Korean reference only for Korean work.

**Disposition:** Retain this source structure. In load-trace trials, verify that executors do not expand a section
read into the entire sibling skill. Keep the local design coverage and precision tables, semantic completion gate,
literal exceptions, and missing-sibling fallback. Do not infer a defect from file length or merge writing skills.

### F18 — Decision Navigator repeats its conceptual explanation

**Evidence:** [decision-navigator](../../skills/decision-navigator/SKILL.md), opening paragraphs,
“Plan, don't do,” “Fog of war,” “Out of scope,” and “Invocation,” explain related boundaries several times.
Map/ticket templates overlap with [local-tracker.md](../../skills/decision-navigator/references/local-tracker.md).

**Change:** Keep a short definition and explicit scope decision table in `SKILL.md`.
Make `local-tracker.md` the single detailed home for map/ticket syntax and transaction order; it is already required.
Preserve destination confirmation, names in links, HITL/AFK, all ticket types, one-ticket/session exceptions,
fog versus precise blocked tickets, and out-of-scope resolution.
Do not turn planning into execution or remove examples needed to distinguish those states.

### F19 — Frontier discovery has no bounded read procedure

**Evidence:** [local-tracker.md](../../skills/decision-navigator/references/local-tracker.md), “Frontier,”
says to scan ticket files in numeric order; the main skill correctly says not to load every ticket body.

**Change:** Specify one metadata pass over filename, title, `Type`, `Status`, `Blocked by`, and claim presence.
Read the chosen ticket and relevant dependency bodies after the atomic claim, then re-read mutable state as required.
Use existing filesystem/search tools; do not introduce a new index database or a second source of truth.
Treat malformed or missing metadata as unresolved evidence, never as an eligible ticket.
Benchmark a large map with long closed-ticket answers and concurrent claims.

### F20 — Confluence body detail is unconditional within a well-routed skill

**Evidence:** [document-to-confluence](../../skills/document-to-confluence/SKILL.md) already selects source
adapters correctly, but always loads
[confluence-body.md](../../skills/document-to-confluence/references/confluence-body.md),
which contains image, media-ID, TOC, table, width, and text detail.
Media identifiers and deletion explanations repeat in the attachment reference and higher-level policy.

**Change:** Use the existing normalized inventory to select named sections in `confluence-body.md`.
Always include checked-scope limitations, whole-body replacement, text rules, unsafe-source removal, and the final gate.
Load images/tables/TOC before creating or preserving those constructs, including untouched content on an existing page.
Keep short correctness warnings local; deduplicate only long explanations already read on that path.
Preserve all source adapters, normalized blocks, entire current-body reads, page/source version checks, and readback.

### F21 — Existing asset tools can avoid one invocation per item

**Evidence:** [image_size.py](../../skills/document-to-confluence/scripts/image_size.py), `main`, accepts
multiple images. [render_diagrams.mjs](../../skills/document-to-confluence/scripts/render_diagrams.mjs)
captures all matching elements in one browser session and returns per-file paths.
The skill workflow does not explicitly direct callers to use these batch capabilities.

**Change:** Group images sharing a display-width policy into one measurement call and compatible diagrams into
one render call. Reuse dimensions/render outputs only for unchanged file content, font/layout inputs, and settings.
Keep per-item errors, inspect every image, upload before use, and revalidate the final body.
No new batch script, cross-skill renderer dependency, or visual sampling shortcut is needed.

## Debate, refresh, and standalone configuration

### F22 — Debate recovery and question-file rules load on successful synthesis runs

**Evidence:** [tiki-taka](../../skills/tiki-taka/SKILL.md) contains “Resume failure recovery,”
“Deliverable writing rules,” and the full “Unresolved-question file” contract alongside normal debate execution.
The runner already limits progress, resumes exact sessions, and cleans temporary transcripts.

**Change:** Move recovery detail to `references/recovery.md` and unresolved-file authoring to
`references/unresolved-questions.md`. Keep uncertain-receipt stops, the distinction between disconnection and
failure, and the read trigger in the entrypoint. Keep answer-only mode's no-write rule before any file action.
Preserve models/effort, exchange counts, both parties' impact inspection, issue ledger, final-statement rules,
durable execution, fixed-contract-first/delta-later prompts, and normal cleanup.
Do not replace the opponent with a cheaper model or collapse required independent inspection.

### F23 — Refresh recovery detail loads even for a blocked preview

**Evidence:** [orca-plugin-refresh-resume](../../skills/orca-plugin-refresh-resume/SKILL.md) includes
manual resume, command-hash approval, lease recovery, and ambiguous completion handling in every invocation.
[orca_plugin_refresh.py](../../scripts/orca_plugin_refresh.py), `plan_output` and `_public_receipt`, already
provide compact safe output and private evidence paths.

**Change:** Move recovery instructions to `references/recovery.md`, selected by the returned state/error.
Read it for a failed worker or leftover lease, `needs_manual_command`, `manual_resume_requires_terminal_check`,
`complete_but_not_confirmed`, or `complete_but_not_delivered`; a merely blocked pre-apply preview still stops inline.
Keep preconditions, exact-plan approval, end-turn-after-apply, no polling during the transaction,
no blind retry/resend/resume, and the path to recovery in the main file.
Leave hook registration, registry writes, locks, identity checks, privacy, and worker checks unchanged.
Savings from this short skill may not justify an extra read; retain baseline if paired trials are inconclusive.

### F24 — Standalone routing repeatedly handles a large pinned source set

**Evidence:** [omo-model-config](../../standalone-skills/omo-model-config/SKILL.md),
“Required inputs and authority,” lists 20 mandatory upstream files plus relevant conditional tests.
“Freshness gate” intentionally requires a full re-fetch on disagreement.

**Change:** Fetch independent mandatory files together at the resolved SHA, retain their exact source identity,
and reuse the already-read sources for subsequent resolution/validation within that run.
Present target-specific evidence and the required final report rather than repeatedly dumping the entire corpus.
Do not replace the per-run current-SHA resolution, omit sources on targeted edits, or weaken the full re-fetch gate.
Retain all target enumeration, allowlist/order/provider/reasoning rules, and formatting preservation.
Retain external-sync consent.
No cross-run cache or speculative upstream parser is included in this plan.

## Cache reuse, tool discovery, and context recovery

### F25 — Changing optimizer data precedes a large stable skill body

**Evidence:** [improve_description.py](../../skills/skill-builder/scripts/improve_description.py),
`improve_description`, places current description, scores, and attempt history before unchanged `skill_content`.
Changing an early block limits reusable prefix length. This is a cache opportunity, not proven token reduction.
By contrast, `run_eval.py::build_routing_prompt` already puts the query after stable skill metadata.
`session_context.py::render_context` is deterministic for the same root and instruction files.
Official mechanism and host/API boundaries are recorded in [Strategy assessment](strategy-assessment.md).

**Change:** After F11's separate comparison, compare one additional variant in `improve_description.py`:
Put stable role/task/output rules and unchanged skill context first.
Put the current description, scores, failures, and history last.
Preserve every datum, authority boundary, and exact response contract; mark the current candidate distinctly from
the source skill's original frontmatter. Do not claim that changing block order is behavior-neutral without trials.
Keep model, effort, tool definitions, and serialization stable within a trial, except for intentional input changes.
Do not add timestamps to fixed instructions, pad short prompts, preload unrelated skills, or invent cache API flags
in the vendor-neutral runner. Preserve real source paths and refresh rules even when they invalidate a prefix.
Compare cold/unknown/warm conditions and complete cache creation plus reuse cost. A hit is not guaranteed.

### F26 — Tool discovery needs a host capability contract

**Evidence:** The plugin manifests distribute skills and do not implement an API tool registry.
The source/host capability tables in `document-to-confluence` select the task route but do not specify how to bound
discovery of a large deferred tool catalog. Current native host/tool-search behavior is documented in the assessment.
No existing source proves that all schemas are currently loaded; measure that before claiming waste.

**Change:** Put the shared hosted-tool discovery rule in the already-conditional `instructions/services.md`.
Existing capability guidance in `skill-builder/SKILL.md` and `document-to-confluence/SKILL.md` follows that active rule,
without copying it or adding a required dependency to a standalone package.
Use native discovery for the named service/action, inspect the selected tool's complete argument/output contract,
and reuse it while tool identity/schema remain valid.
If the host has no deferred discovery, use its current tools and existing capability fallback.
On ambiguous or missing search results, refine the service/action query or inspect the relevant catalog;
never invent a tool or silently omit a required operation. Keep permission scopes and service-access rules intact.
Do not add `defer_loading` to skill frontmatter, build a universal loader, or change installed MCP connections.
For an already-small or already-deferred catalog, no change is a valid result. Measure discovery misses and latency.

### F27 — Existing checkpoints need an explicit recovery completeness check

**Evidence:** Deep Interview's scoring state, Decision Navigator's map/tickets, and Tiki-taka's in-context
issue ledger already preserve work at different boundaries. F05 protects instruction reloads but does not alone
prove that task state survives a context transition. Summary/compaction mechanisms do not prove losslessness.

**Change:** Extend those existing state/recovery sections, not a new global memory system.
A checkpoint must preserve goal/scope, constraints and exceptions, confirmed versus inferred decisions,
source/revision pointers, completed outputs, failed attempts and why they failed, validation results and gaps,
open questions, authorization scope, pending side effects, active lock/session/transaction identity, and next action.
Keep secrets out of the checkpoint; use existing protected receipt paths when identity data is sensitive.
Before continuation, restore relevant instructions and verify checkpoint facts against their authoritative artifacts.
On stale or missing evidence, re-read or stop the dependent action; never turn an uncertain action into a retry.
Use approved persistence only; do not add a state file to a read-only interview or persist Tiki-taka's issue ledger.
Do not force a new session during debate/refresh, delete history, or bypass a claim or lease.
A new context is eligible only when the workflow permits it and required state can be recovered safely.
Measure summary creation, reload, re-exploration, cache rebuild, and resumed completion together.

## Costs deliberately retained

| Surface | Evidence | Decision |
|---|---|---|
| Session and subagent instruction injection | `hooks/hooks.json`; `session_context.py::render_context`; `tests/test_session_context.py` | Keep both event paths and resume/compact reloads. Inheritance does not prove an independent agent already has current rules. |
| Absolute installed-reference paths | `session_context.py::read_instruction` | Keep reliable path resolution and fail-on-missing behavior. Character savings do not justify broken links. |
| Host agent rules | `instructions/codex-agents.md`, `instructions/claude-agents.md`, agent definitions | Keep actual host differences and narrow evidence roles; do not change model/effort to save cost. |
| Service, protected-value, and test instructions | `instructions/services.md`, `protected-values.md`, `testing.md` | Already short conditional references; keep authority and access boundaries. |
| Plan/design workflow and independent validation | `implementation-planning.md`, `independent-model-validation.md` | Preserve ordered stages, per-deliverable approval, one pass, and unavailable-model behavior. |
| Runtime freshness and locks | Confluence workflow, local tracker, refresh worker and lifecycle hooks | Re-reading changed or concurrently mutable state is required work. |
| Lifecycle registry writes | `session_lifecycle.py::registry_lock` and `handle_event` | Usually no model context output; disk writes/fsync are not established token waste. Do not batch away identity/state transitions. |
| Debate progress and reconnection | `stream_agent.py`, `detached_job.py`, `opponent_runner.py` | Already bounded output and exact-session recovery. Replayed progress after reconnect is a low-volume candidate, deferred absent measurements. |
| Grader's complete transcript review | `skill-builder/agents/grader.md`, “Read the Transcript” | Keep full process inspection. Output-only grading can miss unauthorized actions or fabricated process claims. |
| Repeated independent trials | `run_eval.py`, `run_loop.py`, Execution Methods | Do not memoize stochastic decisions, cut repetitions, or expose held-out cases to save evaluation tokens. |
| Review HTML and embedded assets | `eval-viewer/generate_review.py`, `viewer.html`, `assets/` | Artifact bytes are not prompt tokens unless read into context. Present artifacts instead of deleting useful review capability. |
| Small deterministic helpers | `document-to-confluence/scripts/`, `decision-navigator/scripts/local_lock.py` | No evidence warrants rewriting parsers, removing checks, or adding a common helper framework. |
| Manifests, mirrors, translations, tests, prior plans | Inventory and discovery configuration | They are not all automatically loaded. Keep mirrors and development checks; no plugin-manifest restructuring. |

No universal prompt-length limit or target reduction percentage is proposed.
The optimization unit is a complete successful execution path, including any new reference reads it requires.
