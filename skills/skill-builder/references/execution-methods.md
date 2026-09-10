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

These settings govern every worker and model runner that Skill Builder launches for research,
drafting, execution, grading, comparison, analysis, or optimization.
They do not change the main session's model or effort.
The main session retains responsibility for the task definition, rubric, review, and final decision.

| Executing host | Required model | Required effort | Boundary |
|---|---|---|---|
| Codex | `gpt-5.6-luna` | `xhigh` | Never launch Sonnet from Codex. |
| Claude Code | Sonnet 5 | `high` | Never launch `gpt-5.6-luna` from Claude Code. |
| Other hosts | Available lightweight model | Highest supported suitable effort | Record the actual configuration. |

Use the same model and settings on both sides when both methods include a model.
For a tool-only method, record that no model performs the operation; include any model orchestration cost.
Discover the host's model selector and effort controls; do not invent model IDs or CLI flags.
For an alias such as Sonnet 5, record the resolved model ID and verify that it matches the required version.
Record the actual model and effort for every launched worker and model runner.
If either required setting is unavailable, do not substitute another model or lower the effort.
Mark the dependent run unverified and continue only work that does not require that worker or runner.

## Paired trials

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
