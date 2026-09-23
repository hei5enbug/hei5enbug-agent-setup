# Prove quality preservation before adopting an optimization

Use this procedure when implementing the candidates in [Findings](findings.md).
At plan creation, there were no live trial results. Later measurements and limits are in the
[execution record](execution-results.md).
Static file measurements establish where to investigate; they cannot establish model adherence or token savings.

## Model and execution contract

The user's Sonnet(high) and Luna(xhigh) requirement is concretized by the repository's
[evaluation model adapters](../../skills/skill-builder/references/execution-methods.md).
Do not silently replace that mapping with a newer model, stronger model, lower effort, or an alias of unknown identity.

| Lane | Native execution environment | Required executor configuration | Unavailable behavior |
|---|---|---|---|
| Claude | Claude Code | Sonnet 5, `high`; record the resolved full model ID. | Mark the lane unverified and retain the affected baseline. |
| Codex | Codex | `gpt-5.6-luna`, `xhigh`; verify the actual model and effort. | Mark the lane unverified and retain the affected baseline. |

If the user later chooses a different exact Sonnet/Luna version, freeze that as a new matrix before comparing.
Do not infer model availability from a name in a Markdown file.
Keep the authoring session's model unchanged. Skill Builder workers, graders, and runners follow their host adapter.
Tiki-taka's opponent and plan/design independent reviewers keep their own existing model contracts.
They are required collaborators, not substitutes for testing the skill's main executor on the target lightweight model.

A Codex run is not a substitute for a native Claude run.
Run the Claude lane in Claude Code; do not launch Sonnet workers from a Codex Skill Builder invocation.
Use identical fixtures and criteria across hosts while preserving actual differences in tools and hooks.

For main-session-only questions and HITL work, start a dedicated native main session for each trial on the
lane's target model and effort; the plan-authoring session remains unchanged.
Use Claude Code's native question UI and Codex Plan mode as required by the existing skill contract.
A human test operator supplies the frozen answers through that UI, including separate closure and execution choices.
Do not make an executor worker impersonate the user or count an inline fallback as native UI coverage.
Noninteractive cases may use permitted isolated workers; grading workers still follow their host adapter.
If a native main session or test operator is unavailable, mark the dependent cases unverified.
Record human-answer wait time separately and compare only pairs with equivalent scripted response timing;
retain the raw end-to-end wall time rather than silently subtracting delays from reported completion time.

## Baseline and artifacts

Before editing, snapshot the relevant plugin/standalone skill, all required references, scripts, manifests,
and active session instructions at the audited commit or a newly recorded current commit.
Do not let old `SKILL.md` resolve a new reference file through the live checkout.
Use isolated working directories and output directories for old and new executions.

Follow the plan's `B0`/`B1` baseline sequence: S2 starts from the post-S1 experimental snapshot.
Record the old/new hashes for every later candidate and test the final combination against the original `B0` too.
F01's focused regression checks do not establish live quality, latency, or token savings.

Store these records in a development evaluation workspace, outside normal skill loading:

| Record | Required contents |
|---|---|
| Frozen requirements | Stable criterion ID, authoritative source/heading, required behavior, applicable modes, and case IDs. |
| Case definition | Exact request, source files/revisions, user-answer script, tool/service fixtures, permissions, and expected artifacts. |
| Run manifest | Host version, actual model ID, effort, source hashes, tool versions, environment conditions, trial order, and capability gaps. |
| Raw execution | Prompt, transcript, tool results, errors, final artifacts, and requested side effects or their explicitly simulated receipts. |
| Load trace | Ordered instruction/reference reads, revisions, returned bytes, repeated reads, and context-loss/reload events. |
| Existing grading/timing | `grading.json` and `timing.json` in their current formats; use `new_skill` and `old_skill` directories for an existing skill. |
| Comparison | Per-case quality, time, usage, context coverage, retry counts, acceptance decision, and evidence paths. |

Use existing schemas and aggregation; keep extra fields in a separate run manifest rather than silently changing
`benchmark.json`. Its average pass rate is descriptive and does not authorize adoption.
For descriptions, keep query train/holdout separation and label the portable result as a routing simulation.

## Cases and preservation checks

Preserve the existing 48 behavior cases and 20 trigger cases after correcting the F03 expectation defects.
Self-contained text cases can run as written. Cases referencing an absent document, repository, or service require
an actual fixture. The executor must produce the artifact; it cannot merely describe the expected approach.

Create the four missing behavior suites at:

- `skills/deep-interview/evals/evals.json`
- `skills/flowchart-design/evals/evals.json`
- `skills/tiki-taka/evals/evals.json`
- `standalone-skills/omo-model-config/evals/evals.json`

Extend existing suites for the remaining scenarios below. Store necessary inputs under each suite's `evals/files/`.
Do not duplicate existing cases when their actual fixture and assertions already cover a row.
Each named variant is a separate executable case when it exercises a different branch.

| Case family | Fixture and variants | Mandatory outcome |
|---|---|---|
| V01 — Routing | Positive and near-miss requests for each changed description, including Korean wording; explicit-only skill named versus merely relevant keywords. | Correct skill selection and refusal to auto-start explicit-only workflows; no lost intent category. |
| V02 — Interview rounds | Scripted 10-round brownfield interview with multiple components, an evasive answer, contradiction, and scope expansion. | One question per round, all-component scoring, non-monotonic ambiguity, round-10 checkpoint, retained evidence. |
| V03 — Interview closure | Threshold crossing with an unconfirmed agent assumption; separate user exits early and round-20 variants. | No unconfirmed assumption crosses the final gate; all confirmations and the separate execution bridge remain. |
| V04 — UI and context restoration | Each supported UI adapter; no UI; Codex outside the required mode; missing selected reference; resume/compaction or unavailable active payload/scoring rules. | Correct native main-session/setup/fallback route, rule-availability check, option bounds and free text, required pause, reload before acting or explicit missing-reference stop. |
| V05 — Interview panel | Band crossing upward/downward and delegated decision; native independent workers and unavailable-worker variants. | All existing lenses and main-session decision ownership; no skipped milestone or unauthorized persistence. |
| V06 — Diagram semantics | Linear, branch/merge, bounded retry, error exit, and ambiguous source meaning. | Same graph, directions, branches, retry limits, and ambiguity handling across revisions. |
| V07 — Diagram delivery | SVG only; SVG+PNG with gradient, long Korean/monospace labels, shadow, removed node/group; canvas/DSL and no-renderer variants. | Correct reference selection, bounds/spacing/exceptions, text equivalent, final crop and inspection, honest unavailable checks. |
| V08 — Small skill edit | Existing typo-only case and a package-only request; missing browser/Python/runner variants. | Direct minimal route when applicable; correct failure/fallback; no needless full benchmark or sibling invocation. |
| V09 — Evaluation artifacts | Old/new outputs, invalid grading, missing tokens, incomplete pair, `TIE`, headless viewer, and unavailable required model. | Original schema and comparison semantics; no fabricated metric, hidden failure, or substitute model. |
| V10 — Optimizer prompt | Two prior attempts plus current failures; long distinct queries; a candidate over 1,024 characters; invalid retry. | Each train datum remains available once in its role; holdout never leaks; coverage precedes conciseness; one retry and invalid-candidate rejection. Scored selection stays in `run_loop`; adoption quality is checked separately. |
| V11 — Packaging | Valid package; failing bundled check; symlink; forbidden output path; source changed since earlier validation. | Validation once during packaging, all failures/warnings visible, integrity and atomicity retained, changed sources rechecked. |
| V12 — Commit scope | Empty/unborn repository, staged-only, named paths, mixed staged/unstaged, related and unrelated untracked files. | Only requested change set; no-change short circuit; no unsupported behavioral claim. |
| V13 — Commit style | Existing Korean/English pair, tied or insufficient history, explicit language override, convention after match ten, required placeholder, branch-only ID. | Language precedence, identifier provenance, prefix-first ordering/disclosure, five single subjects, no trailers. |
| V14 — Rewrite | Existing seven cases plus a source over 8,000 characters, `--strict`, scoped follow-up, and output-only request. | Every invariant, exact literals, ambiguity, strict passes, retry bound, local edits, no-change and exact-output behavior. |
| V15 — Technical design | Create/Improve/Review, Korean/English, missing sibling signals, literal translationese; independent review approved/declined/unavailable. | Design concern coverage; correct modes; preserved literals; approval branch and result reporting; no full sibling skill load. |
| V16 — Confluence formats | Real Markdown, HTML, scanned/two-column PDF, DOCX, and multi-tab Google Docs fixtures covering the existing source cases. | Ordered normalized blocks, all scoped content, uncertain OCR retained as uncertainty, only relevant source references. |
| V17 — Confluence update/assets | Existing image/table page with page-only text; source/page revision change; multiple images at same/different widths; partial render/upload failure. | Full-body preservation, freshness conflict handling, all asset results, every image inspected, upload ordering, stored-result verification. |
| V18 — Decision maps | 100 tickets with long resolved answers, a blocked frontier, duplicate claim race, post-claim edit, malformed metadata, and shared-map update. | Metadata-first selection with correct eligibility, atomic ownership, required re-reads, preserved answers and scope. |
| V19 — Decision types | Research without workers, HITL grilling, UI/logic prototype, and out-of-scope ticket variants. | Relevant reference route, human confirmation, one-ticket/session exception, local artifacts, no unauthorized execution/tracker access. |
| V20 — Debate | Agreement in first exchange, unresolved last statement, synthesis-only, disconnected wait, uncertain failure and one recovery, unavailable opponent. | Same models/effort, exact-session/delta prompts, impact inspection, caps, no synthesis writes, no duplicate opponent invocation. |
| V21 — Refresh | Existing eight cases plus successful completion, blocked preview and active transaction. | Exact-plan approval, all identity/idle checks, correct recovery reference, no polling/retry/resume shortcuts or secret IDs in chat. |
| V22 — Standalone config | A frozen 20-file upstream fixture, targeted/full update, migration, unavailable source, mismatched SHA, no viable model, external sync declined. | All required sources and targets covered, same-SHA authority, correct gates and formatting, unchanged unrelated config, consent preserved. |
| V23 — Shared context | Startup/resume/compact/subagent events, missing reference, installed path with spaces, standalone packaging without session rules. | Correct current rules and valid links; no translation loading, stale cache, or undeclared dependency. |
| V24 — Prefix reuse | F11-fixed baseline versus F25 ordering; same skill body and task, one single-use request and a fixed sequence of three requests with changing evaluation data. | Complete intent and output preserved; stable prefix measured separately; all sequence calls, cache creation, reuse, and failures counted. |
| V25 — Cache freshness | Source correction, tool/schema change, reported expiry/miss, short ineligible prefix, and host without cache telemetry. | Fresh instructions and valid tool contracts win over hits; no padding or forced stale reuse; unknown cache state stays unknown. |
| V26 — Tool discovery | Small and large catalogs; correct tool late in the catalog; similar names; changed schema; unavailable search; metadata-only discovery. | Selected schema is loaded before invocation; no missed operation, invented tool, altered service/permission policy, or custom loader; discovery overhead included. |
| V27 — Bounded exploration | Known symbol with an indirect consumer outside the diff, configuration-dependent failure, and an output containing a false-positive text match. | Relevant impact path found; search continues when evidence demands it; semantic verdict is not inferred from a match; logs and exit status survive filtering. |
| V28 — Context recovery | A permitted transition after a completed stage, with an unresolved constraint, partial failure, old test result, changed source revision, and missing state artifact; active debate/refresh variants. | Checkpoint preserves obligations and uncertainty; state is revalidated; unsupported transition stops; no duplicate side effect, lost approval boundary, or exact-session bypass. |
| V29 — Proportional work | Clear small edit versus ambiguous ordinary request versus explicitly invoked Deep Interview; authorized disjoint investigation versus overlapping work. | Small edit stays direct; necessary clarification remains; no automatic interview; explicit workflow retains every gate; delegation respects scope and counts all participants. |

For all moved references, include a case whose requested output needs that reference.
Include a missing-reference case and a case that does not need it.
This distinguishes useful conditional loading from simply forgetting the instruction.

External writes and session restarts must use an explicitly authorized disposable environment for live integration.
Replay fixtures are suitable for deterministic branch coverage but must be labeled simulated.
If a change affects live connector/host behavior that cannot be verified safely, keep that candidate at baseline.
Do not update real Confluence pages, user model configs, or Orca sessions merely to execute this plan's tests.
An escalated model's successful repair is not a passing target-model trial.
Record the target failure and total repair cost.
These scenarios do not authorize changing the required evaluation models, effort, or existing fallback policy.

## Trial budget and execution order

First select the candidate and enumerate the concrete affected cases from the matrix and existing suites.
Freeze their fixtures and acceptance criteria before either output is produced.
Start with three cases: ordinary success, the most consequential exception, and minimal/no-change behavior.
When no-change is inapplicable, use a missing-capability or invalid-input case.

Run three matched trials per case per native model lane. Alternate order `old/new`, `new/old`, `old/new`.
For `K` cases, the executor budget is `K × 2 versions × 2 hosts × 3 trials = 12K` executions.
Pilot cases are part of that total and their valid runs are reused when inputs/settings are unchanged.
Record grading and required opponent/reviewer calls separately; do not hide them in the executor count.

Stop a candidate when a critical failure is confirmed. Correct the candidate or retain baseline.
After a correction, start a new bounded comparison only for affected cases; previous versions remain labeled.
Do not add runs until an average happens to pass. If the frozen budget ends inconclusively, retain baseline.
Once targeted cases pass, run all affected branches and combined-plugin integration before adoption.

For changed descriptions, begin with 20 balanced positive/negative cases per description and three decisions per
case/description/host, using equal old/new conditions. Reuse the existing trigger corpus where applicable.
Native routing and portable simulation answer different questions; retain both labels and evidence.
Keep the optimizer's original train/holdout rules and independent samples.

Run timing comparisons under comparable load and avoid concurrent trials competing for resources.
Do not adopt the runner's `--num-workers 10` default blindly for a latency comparison.
Use a fixed worker count of 1 for measured pairs; record any separate throughput experiment explicitly.
This is an evaluation setting, not a change to host-wide worker limits or shipping CLI defaults.

V24 uses two concrete cases: one request and a sequence of exactly three requests.
For a sequence case, one of the `12K` executions means that full three-request sequence; record its API/model-call
count as well. Warm-up is part of the sequence cost, not free setup. Do not issue keep-alive calls to manufacture hits.
Keep candidate content stable within its sequence, alternate old/new sequence order, and record cross-run reuse.
Do not assume a new host session is cold: provider caches may already contain the prefix.
Classify cold/warm/unknown from exposed usage, and preserve unknown when telemetry cannot establish the condition.
Do not add random prefix padding, alter a permission, or reset a live user's session merely to force a cache miss.

F25 follows a frozen post-F11 snapshot; vary block order only. F26 and F27 each get separate comparisons before
integration so discovery or recovery overhead cannot be attributed to a cache improvement.

## Metrics and adoption gates

Measure the complete path from request to a usable artifact, including required review and any repair.
Measure development/setup/grading overhead separately, except when that work is itself the skill's requested output.

| Gate | Pass rule |
|---|---|
| Absolute quality | Every critical criterion passes in every candidate trial, with artifact or action evidence. A baseline failure does not excuse a candidate failure. |
| Relative quality | No case loses a baseline-satisfied requirement or material semantic/visual quality. Resolve disagreements from source and artifacts; otherwise retain baseline. |
| Routing | No lost positive or newly incorrect negative case; no weaker explicit-only or near-miss boundary. Report per category, not only aggregate accuracy. |
| Completion time | For each case, model, and comparable context/cache condition, candidate median and observed maximum are no greater than baseline across the three trials. |
| Total model usage | Same comparison for complete input/output/reasoning usage where reported, summing non-overlapping parent/worker/retry records only. |
| Monetary cost, when claimed | Same per-case median/observed-maximum comparison using applicable reported charges or labeled verified-rate estimates. Include cache writes, reads, all participants, retries, and recovery; do not present list-price estimates as subscription spend. |
| Context | Count initial/repeated instruction and tool payloads; verify no new context loss or compaction. Compare peak retained context only when the host reports it. |
| Actual benefit | At least one intended complete-path cost measure improves; shorter source alone is insufficient. No other required performance gate regresses. |
| Completeness | Both native lanes and every affected mode/exception have sufficient evidence; missing telemetry or unavailable capabilities cannot count as zero cost or success. |
| Integration | The adopted combination passes shared context, packaging, missing-reference, and cross-skill routing checks. |

The time/usage gate is deliberately conservative. Three trials do not prove a population-wide latency bound.
Do not interpret overlapping noise as a demonstrated improvement or relax the gate after seeing results.
Unclear results keep the current default and record the tested limitation.

Report input, output, cache-read/write, and reasoning categories separately when exposed.
Do not add cached/reasoning counts twice if they are already subsets of the host total.
Do not substitute bytes, words, output-only tokens, or one provider's accounting for another's.
Compare old/new within the same model lane; do not pool Sonnet and Luna usage into one apparent saving.
Token reductions alone do not establish monetary savings.
Conversely, a cache-only cost improvement may retain identical logical input and active context.
It can pass the benefit gate through measured applicable cost or completion time while all other required gates
remain non-regressing. Label the result as cache reuse, not fewer logical tokens or a larger context window.

Cold and reused-context runs are separate conditions. Restore the same starting state for each pair.
The compaction case must show that a required instruction is reloaded when it is no longer available.
Read-trace savings are useful evidence even if peak context is unavailable, but then report no measured peak reduction.
Missing complete usage prevents adopting a claim of total token savings.

## Cache, tool, and checkpoint evidence

Extend the evaluation sidecar manifest, not the shipping benchmark schema, with the relevant fields below.

| Area | Additional evidence |
|---|---|
| Cache | Provider/host version, actual model/effort, unchanged-prefix hash or observed identity, full logical input, cache read/write categories, cache state, request order and reuse interval. |
| Charges | Applicable billing basis, currency, verified rate source/date or reported charge, and each disjoint usage category. If rates or category coverage are missing, cost stays unavailable. |
| Tool loading | Advertised names/descriptions versus loaded schemas, selected tool/schema revision, search attempts, discovery time, failures, and fallback taken. |
| Delegation | Parent and worker usage, startup, duplicated reads, returned evidence, reconciliation, retries, and ownership boundaries; do not double-count included totals. |
| Recovery | Checkpoint source/revision, required-state checklist, restore reads, stale-evidence handling, summary/rebuild cost, pending-action reconciliation, and completed resumed artifact. |

Cache creation and cached reads have different billing rules across providers and models.
Use the applicable current schema and rate table.
Do not add cache counters to an input total that already includes them.
When the provider exposes compatible counts, report cached-read share against the corresponding logical input;
state the denominator. Otherwise record the raw categories without inventing a hit ratio.
API cache controls and opaque compaction state are not portable repository settings.
The official sources and their limits are listed in [Strategy assessment](strategy-assessment.md).

For F27, compare every checkpoint obligation with the original task and authoritative artifacts before transition,
then verify it again after restoration. Test negation, exceptions, approvals, unresolved decisions, and action status
explicitly; “summary looks complete” is not a sufficient assertion.
Retain source evidence under the workflow's existing retention rules rather than creating an unauthorized transcript.
If recovery cannot establish whether a write completed, stop the dependent action.
Follow the existing recovery contract.

## Deterministic checks and acceptance record

Use exact checks for file/reference existence, metadata validity, parseable output, graph IDs/edges,
known source literals, scope-limited diffs, lock state, and script exit behavior.
Use model/human review for meaning, naturalness, diagram legibility, completeness, and whether a reference applies.
Do not substitute token count, string presence, or output length for successful completion.

Extend the existing regression suites only for changed behavior:

| Surface | Existing regression locations |
|---|---|
| Prompt projection, runner behavior, report handling | `skills/skill-builder/tests/test_evaluation.py`, `test_model_runner.py`, `test_viewer.py`, `test_benchmark.py` |
| Package ownership and schema references | `skills/skill-builder/tests/test_package_skill.py`, `test_schema_single_source.py`, `test_sibling_references.py` |
| Instruction routing and mirrors | `tests/test_session_context.py`, `test_instruction_duplication.py`, `test_planning_contract.py`, `test_korean_mirrors.py` |
| Content conversion and diagram tools | `skills/document-to-confluence/tests/` |
| Debate state and progress | `skills/tiki-taka/tests/` |
| Map locks and refresh lifecycle | `skills/decision-navigator/tests/test_local_lock.py`, `tests/test_session_lifecycle.py`, `tests/test_orca_plugin_refresh.py` |

Follow `instructions/testing.md` when editing tests. Do not turn semantic prose duplication into a regex verdict.
Run all [README development checks](../../README.md#development-checks) before release readiness.

For every candidate, record `adopt`, `reject`, or `unverified`, the old/new hashes, exact model/effort,
per-case evidence, total recurring cost, and any limitation. Keep rejected variants out of the runtime default.
After adoption, rerun only when a changed input, tool, requirement, or model undermines the recorded evidence.
