# Execution Methods

Select prompt execution, existing tools, or a bundled script using output quality and measured total cost.
Apply this procedure while improving Skill Builder itself and skills built with it.
Normal skill use follows the selected method without repeating the experiment.

## Decision and comparison scope

Assign meaning, intent, ambiguity, and quality judgments to a model from the start.
Use existing tools for exact calculations, parsing, schema checks, and file transformations.
Split mixed work so a tool handles exact operations and a model handles contextual decisions.
An orchestration script can run prompts repeatedly; that is a model-assisted method, not deterministic judgment.

Use host search or file discovery for locating files and text; use structural search only for syntax-aware queries.
Tools such as `fd`, `rg`, and `ast-grep` are examples, not required dependencies.
Discover capabilities rather than assuming availability or installation layout.

Before adding a script, define supported inputs, outputs, success, failure, and unsupported cases.
Compare existing tools and simple compositions against the unmet contract.
Add a script only when its expected reuse or reliability benefit justifies development,
testing, dependencies, and maintenance.
Never infer speed, accuracy, or lower cost from an implementation language or model name.

Run a paired comparison when an execution choice is uncertain, a method changes, or an optimization
changes what instructions are loaded or what work runs.
For a small wording correction with unchanged behavior, review the change directly.
Do not invent an inferior script alternative for an inherently contextual decision.
When only one method can meet the contract, document why; do not claim measured superiority.

## Evaluation model adapters

These settings govern Skill Builder's trial execution and other non-review participants, and its read-only review
roles. They do not change the main session's model or effort. The main session owns the task definition and rubric,
reviews the same material once, and makes the final decision.

Before launch, classify each worker by its purpose and the destination of its output.

| Worker purpose | Output destination | Role |
|---|---|---|
| Draft or revise the actual skill under development | Repository or working tree that holds the skill | Implementation |
| Produce disposable trial artifacts for grading | Evaluation workspace | Trial execution |
| Promote a trial artifact into the actual skill | Repository or working tree that holds the skill | Implementation |
| Trial execution and other non-review work, such as research or optimization | Evaluation workspace or inline result | Non-review participant |
| Review persona, grading, comparison, or analysis | Evaluation workspace or inline result | Read-only review |

When the host session instructions include implementation execution rules, implementation workers follow those rules
instead of the table below. Otherwise, as in standalone use, the table below governs every worker, including
implementation. Evaluation participants use the model adapter below. The Skill Builder review and participant
contract takes precedence over generic host skill-worker routing and target-skill metadata.

A skill-assigned review role, such as a review persona, grader, comparator, or analyzer, is read-only judgment work.
It returns findings only and bases every finding or grade on quoted evidence. It returns the JSON its agent file
defines instead of writing a file, and the main session saves that JSON to the path the agent file names. Use the
other model family first, following the host's skill-worker instructions. If that CLI is missing, unauthenticated,
limited, fails to start the pinned model, times out, or lacks model evidence, use the `reviewer` fallback in the table
below and report the substitution once. The main session reviews the same material once and makes the final decision.
Do not run another review round.

| Executing host | Trial and other non-review participants | Effort | Review route |
|---|---|---|---|
| Codex | `gpt-6.1-sol` | `xhigh` | `claude -p` with `claude-opus-5-5`, `high`; fallback `reviewer` with `gpt-6.1-sol`, `xhigh` |
| Claude Code | `claude-opus-5-5` | `high` | `codex exec` with `gpt-6.1-sol`, `xhigh`; fallback `reviewer` with `claude-opus-5-5`, `high` |
| Other hosts | Available upper model | Highest suitable supported effort | Use a verified cross-family reviewer route and its documented fallback; otherwise mark review unavailable. |

Trial execution and other non-review participants stay on the host's model family at its upper model. Review roles
use the other family. Do not send a review role to `scout`, use `reviewer` to write trial outputs, or lower a role's
required effort. A runner invocation alone does not verify its effective settings.

For trial output writers, use the model and effort that the host adapter pins. Keep their outputs in the evaluation
workspace. Do not promote trial output unless the main session selects it through the skill's acceptance process.
Record the actual model and effort for every participant. If a required setting cannot be verified, mark the dependent
run unverified and do not silently substitute another model or lower the effort.

Keep model and effort fixed on both sides of an ordinary method comparison. Only a specifically approved model or
effort experiment may vary its one frozen candidate setting, in the disposable evaluation workspace. It must not
change production settings or promote trial output to the repository.

## Paired trials

When plugin session rules apply, read [work efficiency](../../../instructions/work-efficiency.md#model-evaluations)
before model trials; it owns the shared batch limits, preflight, continuation, and stopping rules. If that
required reference is unavailable, stop the affected evaluation. Standalone use retains the procedure below.

1. Freeze the task, quality criteria, input artifacts, output contract, and current skill snapshot.
   Include correctness, completeness, required exceptions, and any user latency or cost limits.
   Set a small trial budget before starting; use 2–3 representative cases initially, including a boundary case.
   Add a case requiring no change when the skill edits acceptable input.
2. Run both methods on identical inputs with separate outputs and contexts.
   A method trial changes only the method; an old/new trial changes only the skill version.
   Keep task instructions, permissions, and unrelated model settings constant.
   Prompt execution must produce the requested artifact; tool execution must actually run the tool.
   Neither a proposed command nor a prediction of the other method counts as a completed trial.
3. Use isolated workers when available and authorized; otherwise run sequentially and disclose reduced independence.
   Never show a trial the other output or the expected verdict.
   Avoid concurrent trials sharing files or competing for constrained resources.
   If performance matters, measure under comparable load rather than assuming parallel launches are comparable.
4. Inspect actual outputs against the frozen criteria in the main session.
   Use exact checks only for exact predicates; judge semantic quality from the artifacts and input evidence.
   Check boundary cases and individual failures, not just average scores.
5. Repeat affected pairs when verdicts, timing, or token measurements vary enough to change the choice.
   Stop at the trial budget; report inconclusive results instead of rerunning indefinitely.
   Reuse these trials for old/new validation where they answer the same question; avoid duplicate experiments.

## Measurement and decision

Keep raw inputs, prompts or commands, outputs, and the actual model/tool configuration with the trial record.
Separate recurring execution cost from development and evaluation overhead.

| Measure | Record |
|---|---|
| Quality | Evidence for each acceptance criterion and any regression against the baseline. |
| Execution time | Wall-clock time from task start through the usable artifact, including reads, startup, tools, and retries. |
| Model tokens | Reported input/output and other token categories when available, across the parent, workers, and retries. |
| Development cost | Observed writing, debugging, setup, and testing time/tokens, separate from recurring execution. |
| Evaluation overhead | Trial setup, grading, and comparison costs, separate from the task being measured. |

Use host-reported metrics or measured timestamps; never substitute character counts for tokens.
Sum only non-overlapping usage records; do not add worker usage again if the parent total already includes it.
Mark missing or partially covered totals as unavailable or incomplete, never zero.
For monetary costs, use supplied or verified rates and token categories; token counts alone are not a price.
Do not claim lower cost across different models from total token counts alone.

Reject methods that fail required quality criteria or introduce a material quality regression.
Among qualifying methods, compare total execution time and tokens under the user's limits.
Prefer a method that improves one without worsening the other beyond observed variation.
If one saves tokens but is slower, use an explicit user preference or an existing latency budget
to justify the tradeoff; otherwise retain the baseline and report the tradeoff.
If both fail, revise the method or instructions; do not lower the quality criteria to select a winner.
With missing measurements or inconclusive trials, keep claims limited to what was actually checked.
Present unmeasured cost reductions as candidates; retain the baseline default until the comparison supports adoption.

Save a concise `method-comparison.md` in the evaluation workspace, or present the same record inline:

- Task, frozen criteria, cases, configurations, trial budget, and evidence paths.
- Per-case quality verdicts, execution time, token coverage, retries, and separate development/evaluation costs.
- Selected method, reason, switching conditions, unverified claims, and remaining limits.

Use existing `grading.json` and `timing.json` formats when running the full evaluation workflow.
Read `schemas.md` in this directory before writing those files.
Do not overload skill/baseline configuration names with method names in existing benchmark artifacts;
keep method labels and additional cost breakdowns in `method-comparison.md`.

## Applying the result

Put the chosen method and concise switching conditions in the target skill's own instructions.
Keep experiment transcripts and measurements outside the instructions loaded on every invocation.
Check for unnecessary reference reads, repeated tool output, excess model calls, and redundant checks.
Retain requirements, exceptions, output quality, and checks whose inputs may have changed.
For example, reuse a parsed manifest only while its source is unchanged; refresh it when the source changes.
Never replace this condition with an unconditional "read once" or "never reread" rule.
Validate behavior-changing reductions against the original with the same cases and criteria.
Do not require downstream skills to invoke Skill Builder or benchmark themselves during normal use.
Reopen the comparison only during an authorized improvement when requirements, inputs, tools,
or model behavior change enough to undermine the recorded choice.
