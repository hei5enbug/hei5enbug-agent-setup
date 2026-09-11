---
name: skill-builder
description: >-
  Create, modify, validate, and evaluate agent skills across AI agent hosts. Use when users want to
  build a skill from scratch, improve an existing skill, test skill behavior against a baseline,
  benchmark quality and variance, package a skill, or optimize its description for reliable
  triggering. Apply this skill to portable SKILL.md instruction bundles as well as host-specific
  skill packages, while preserving the target host's required metadata and conventions.
compatibility: >-
  Core authoring works in any agent host. Bundled scripts require Python and filesystem access.
  Model-backed description optimization accepts any command that reads a prompt from stdin and
  writes a response to stdout.
---

# Skill Builder

Use this English `SKILL.md` and its English references as the only executable sources.
`SKILL.ko.md` and other `.ko.md` files are non-authoritative human translations; never load them during execution.

Create and improve skills through an iterative draft → test → review → improve loop.

## Portability contract

Keep the workflow stable across agent products by adapting to capabilities, not product names.

1. Inspect the current host before choosing mechanics.
   Check for independent workers, filesystem access, subprocess execution, browser/display access, connected research tools, and artifact presentation.
2. Preserve the core stages even when a capability is absent: capture intent, draft, test, review, improve, and package or hand off.
3. Use neutral terms such as **agent**, **host**, **worker**, and **model runner** in portable instructions.
   Mention a specific product only inside an explicitly scoped adapter or when the user's target requires it.
4. Do not assume hidden environment variables, private tool names, installation directories, or CLI syntax. Discover them or accept them as configuration.
5. Keep outputs and schemas consistent across hosts. When a metric is unavailable, use `null` or omit an optional field; never fabricate data.
6. Preserve host-specific manifests and metadata when modifying an installed skill.
   Put shared behavior in `SKILL.md` and isolate unavoidable host integration in a small adapter or clearly labeled reference.
7. Do not infer an installation root, manifest format, or package layout from the current authoring host when the user has not selected a target.
   Use a task-local writable path for drafts, or ask for the destination when it materially affects the result.
8. Keep every skill self-contained by default. A skill may read a sibling skill's reference file when
   the shared rules are long enough that a copy would drift, but must never invoke a sibling skill or
   depend on its scripts.
   Address the file relative to the directory holding the loaded `SKILL.md`, as
   `../<skill-name>/references/<file>.md`. Never write an absolute path or a host installation root.
   Declare every sibling file you read, what it supplies, and what to do when it is absent.
   When absent, proceed without those rules and say so; a summarized copy is not a fallback.
   Keep rules required for correctness or safety within the skill itself.
   Copy the rule instead when the shared text is only a few lines.
9. Target the same quality contract on every host, not identical output.
   Judge each host against shared acceptance criteria. Wording differences that satisfy the same
   criteria are not defects, and chasing sentence-level parity overdesigns the skill.

Use this capability mapping:

| Capability | Preferred path | Fallback |
|---|---|---|
| Independent workers | Run with-skill and baseline cases in parallel | Run sequentially and disclose reduced independence |
| Filesystem | Use iteration workspaces and bundled scripts | Present prompts, outputs, grades, and feedback inline |
| Browser/display | Open the generated review page | Generate static HTML; if files cannot be presented, review inline |
| Model subprocess | Use a configured runner for repeated trials when useful | Use direct prompts with the same rubric; disclose reduced isolation |
| Timing/token metrics | Capture host-reported values immediately | Store `null` or omit optional values |
| Artifact presentation | Present or attach the package with the host's native mechanism | Return an exact filesystem path |

## Core loop

- Determine what the skill should do, when it should trigger, and what success looks like.
- Draft or inspect the skill and its bundled resources.
- Create realistic test prompts and execute both skill-enabled and baseline runs when possible.
- Evaluate outputs qualitatively and with objective assertions where appropriate.
- Generate a review surface early so the user can inspect examples.
- Revise from feedback and benchmark patterns without overfitting to individual prompts.
- Repeat until feedback is satisfied or further changes are not meaningful.
- Validate and package the final skill when the environment supports it.

Figure out where the user is in this loop and continue from there. If the user wants a lightweight pass rather than formal evaluation, adapt the depth while preserving the requested outcome.

Edit and check small behavior-preserving corrections directly; run relevant old/new cases for behavior changes.
Before launching any worker or model runner, read only "Evaluation model adapters" in
`references/execution-methods.md` and apply the current host's required model and effort.
When an execution-method or recurring-cost comparison will run, follow
`references/execution-methods.md`; do not load it merely to decline an unmeasured change.
Stop when the required checks pass and no unresolved finding justifies another iteration.

## Communicating with the user

Match the user's technical level.
Terms such as “evaluation” and “benchmark” are usually fine; explain formats such as JSON and concepts such as assertions when context suggests they may be unfamiliar.

Lead with decisions and results. Explain why a test or structural choice matters, especially when a missing host capability reduces rigor.
The user's output contract overrides reporting defaults.
When it requests only an artifact or exact format, output exactly that and omit any preface,
explanation, citation, or status.

## Creating or updating a skill

### Capture intent

Extract answers from the conversation and existing files before asking for information the user already supplied.

1. What should this skill enable an agent to do?
2. When should it trigger, including likely user phrases and contexts?
3. What output or side effect should it produce?
4. What constraints, dependencies, edge cases, or safety boundaries apply?
5. Would test cases add value? Objectively verifiable work usually benefits from tests; highly subjective work may rely more on human review.
6. Which hosts must support the skill, and which parts truly need host-specific integration?
7. What quality criteria, execution-time limits, and recurring token costs must the improvement preserve or reduce?

When updating an existing skill, preserve its original directory name and `name` field unless the user explicitly requests a rename.
Snapshot the original before editing so it can serve as the baseline.

### Interview and research

Ask only for gaps that materially change the implementation. Investigate available connected tools, local references, examples, and comparable skills when useful.
Run independent research in parallel when the host supports it; otherwise research inline.

### Write `SKILL.md`

Include:

- **name**: stable skill identifier
- **description**: what the skill does and when to use it; this is the primary trigger signal
- **compatibility**: required tools, dependencies, and supported environments when relevant
- **body**: the executable workflow, constraints, references, and output contracts

Make the description specific enough to trigger on real intent without becoming a list of keywords. Avoid tuning it to one model family's routing habits.

### Anatomy of a portable skill

```text
skill-name/
├── SKILL.md            # required: metadata and core workflow
├── scripts/            # optional tooling with a complete input and output contract
├── references/         # optional documentation loaded as needed
├── assets/             # optional templates and output resources
└── adapters/           # optional host-specific integration boundaries
```

Keep host-specific manifests when the target requires them. Do not duplicate the core workflow across adapters.
Do not create a product-specific manifest merely because the current agent host supports one; add it only for a requested target or preserve it when updating an existing package.

### Multiple target hosts

When a skill must run on more than one host, keep one canonical skill body as the single source of
truth. Never fork a per-host copy and maintain the copies separately; forks drift apart almost
immediately.

- Keep behavior rules, quality criteria, terminology, output contracts, and review checklists in
  the shared body.
- Put only genuine host differences in an adapter: trigger and discovery metadata, tool names,
  script invocation, host-required metadata, and workflows that use a host-only capability.
- Evaluate every target host against the same eval corpus and acceptance criteria so results stay
  comparable.
- Attribute a failure before editing. When all hosts fail a case, fix the shared rule. When one
  host fails, first check whether the shared rule is ambiguous and clarify it. Add an adapter rule
  only when the clarified shared rule still fails on that host. Rerun the corpus on every host
  after either change.
- Do not weaken or pad shared rules to a lowest common denominator because one host follows them
  poorly. Contain that host's gap in its adapter.

### Translated mirrors

Keep English as the canonical executable language. Give every human-readable English Markdown
instruction or document an adjacent, meaning-equivalent Korean `.ko.md` mirror. Do not duplicate
code, schemas, eval fixtures, generated artifacts, or documents already written in another language.

A mirror is part of the same change as its source. Whenever you edit an authoritative file, update
its mirror in the same task. Do not defer the update or leave a mirror describing a rule the source
no longer contains.

A stale mirror is a defect even though no agent reads it. Readers use it to learn how the skill
behaves, so an outdated mirror teaches a rule the skill does not follow.

Each mirror must link its source and state its non-authoritative, human-only status. `SKILL.md` must
tell the agent not to read mirrors during execution. When a rule reverses, verify that the mirror
states the new rule rather than merely adding text near the old one. When a source file is deleted
or renamed, delete or rename its mirror in the same task.

### Automation boundary

Choose by the operation's requirements, not by model size or a fixed tool-first order.

| Operation | Default method | Boundary |
|---|---|---|
| Meaning, intent, ambiguity, or output quality | Model judgment from a prompt | Do not turn contextual signals into deterministic verdicts. |
| Calculation, schema checks, or file transformation | Existing host capability or terminal tool | Prefer a supported parser or validator over custom code. |
| Repeated model evaluation and result collection | Model plus execution script when useful | The model judges; the script schedules, records, and aggregates. |

For exact mechanics, try existing tools and simple compositions before adding a bundled script.
A new script needs an unmet input/output contract and a benefit that justifies writing, testing,
dependencies, and maintenance.
For a small, one-off task, direct prompt execution remains an option even when scripts are available.

Deterministic execution does not prove a rule correct.
Bundle validators only for exact predicates over declared inputs: every reported failure must be
a real violation and every supported violation must fail.
Report unsupported inputs explicitly.
Keep semantic, subjective, probabilistic, and contextual judgments with the model or user.
Existing heuristic analyzers may supply evidence, never the sole verdict; do not create new heuristic checkers.
A script may call a model, but must preserve the uncertainty of its output.
Test valid, invalid, boundary, and unsupported inputs for bundled validators; examples alone do not prove completeness.

Read [Execution methods](references/execution-methods.md) when planning or running a paired comparison,
adding a script, or supporting a claim with execution measurements.
For a small unmeasured proposal, apply the recurring-cost rules below without loading the reference
and retain the baseline until a later comparison validates the candidate.

### Recurring execution cost

Apply these rules to Skill Builder itself and every skill it creates or improves.
On every improvement, inspect the cost of normal use: loaded instructions and references,
repeated reads, tool output, model calls, worker startup, retries, and unnecessary steps.
Remove avoidable work while preserving conditions, exceptions, evidence, and output quality.
Move substantial mode-specific instructions into references with explicit read conditions.

Write the selected method and its switching conditions into the target skill itself.
During each normal use, load only needed resources, reuse still-valid evidence, and run applicable checks.
Re-read when inputs or relevant state change; never skip freshness checks to save tokens.
Do not introduce unconditional "read once" or "never reread" rules; scope reuse to unchanged inputs.
Without execution-cost evidence, label a proposed reduction unverified and retain the baseline as the default.
When the baseline has no correctness defect, do not rewrite it as an unmeasured wording optimization.
Unless the user requests candidate wording, answer an unmeasured optimization briefly with the retained baseline,
the unverified status, and the measurement needed to reconsider it; do not develop a speculative alternative.
Do not add a dependency on Skill Builder, self-editing, or a new benchmark to each normal invocation.
Compare changed execution behavior during improvement, then reuse the validated choice until
requirements, inputs, tools, or model behavior materially change.
Keep unchanged behavior when no supported improvement is available.

### Progressive disclosure

Use three levels:

1. **Metadata** — name and description, always available to the router
2. **`SKILL.md` body** — loaded when the skill is selected
3. **Bundled resources** — read or executed only when needed

Keep `SKILL.md` under roughly 500 lines when practical. Move deep detail into clearly linked references, and add a table of contents to reference files longer than about 300 lines.

Organize multi-domain skills by variant:

```text
cloud-deploy/
├── SKILL.md
└── references/
    ├── aws.md
    ├── gcp.md
    └── azure.md
```

Tell the agent how to select the relevant reference so it does not load every variant.

### Safety and lack of surprise

The skill must match the user's stated intent. Do not create malware, exploit workflows, covert data access, misleading behavior, or unexpected external side effects.
Make material writes and external actions visible in the instructions.

### Writing patterns

Use imperative instructions and explain the reasoning behind important constraints. Prefer adaptable principles over repeated all-caps mandates.

A rule that constrains form must name every surface it governs, or be stated independently of surface.

For exact output contracts, provide a template:

```markdown
## Report structure
Use this exact structure:
# [Title]
## Executive summary
## Key findings
## Recommendations
```

Use examples when they resolve ambiguity:

```markdown
## Commit message format
Input: Added user authentication with JWT tokens
Output: feat(auth): implement JWT-based authentication
```

## Test cases

Create 2–3 realistic prompts for the first iteration.
Vary the input types the skill will actually meet rather than testing one shape repeatedly.
As the set grows, include at least one case where the correct behavior is minimal or no change at
all. An overaggressive skill rewrites acceptable input and fails this case.
Share them for confirmation when user judgment is needed; if the user has already authorized execution and the expected behavior is clear, proceed and report the chosen cases.

Save cases to `evals/evals.json` when filesystem access is available:

```json
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "A realistic user task",
      "expected_output": "A concise description of success",
      "files": []
    }
  ]
}
```

Read `references/schemas.md` when assertions or benchmark artifacts are needed.

## Running and evaluating test cases

Treat this as one continuous workflow. Use native host workers when available; do not depend on a product-specific testing command.

Every command in this file uses `<skill-builder-path>`: the absolute path of the directory that contains this loaded `SKILL.md`.
Resolve it once, run the scripts by that absolute path, and never change the user's working directory to run them.
The bundled scripts need Python 3.12 or later with PyYAML installed; a missing PyYAML stops with an install hint and exit code 2.

### Step 1: Prepare the workspace and baseline

With filesystem access, create `<skill-name>-workspace/` beside the skill. Organize results as `iteration-N/<descriptive-eval-name>/`.

For a new skill, the baseline receives no skill. For an existing skill, snapshot the original before editing and use that snapshot as the baseline.
Keep the active and baseline prompts, inputs, model settings, and requested outputs identical.

Write `eval_metadata.json` in each eval directory:

```json
{
  "eval_id": 0,
  "eval_name": "descriptive-name",
  "prompt": "The user's task prompt",
  "assertions": []
}
```

### Step 2: Launch skill-enabled and baseline runs

Run independent pairs concurrently only within host limits and without shared files or resource contention.
Keep model configuration and measurement conditions comparable using `references/execution-methods.md`.

Skill-enabled task template:

```text
Execute this task.
- Skill path: <path-to-skill>
- Task: <eval prompt>
- Input files: <paths or none>
- Save outputs to: <workspace>/iteration-N/<eval-name>/with_skill/outputs/
- Outputs to save: <artifacts the user cares about>
```

Use `without_skill/outputs/` for a new-skill baseline or `old_skill/outputs/` for an existing-skill baseline.

If independent workers are unavailable, run the same pairs sequentially.
Keep the baseline instructions isolated from the revised skill as much as the host permits and record that the comparison has lower independence.
If even sequential execution or persistent outputs are unavailable, perform a focused sanity check inline and ask the user to judge the examples directly.

### Step 3: Draft assertions while runs execute

Create objective, descriptive assertions for machine-verifiable requirements.
A machine assertion must define an exact predicate and scope under "Automation boundary"; otherwise grade it qualitatively.
Avoid forcing quantitative assertions onto subjective qualities.
Update both `eval_metadata.json` and `evals/evals.json`, then explain what the assertions measure.

### Step 4: Capture available metrics

Save host-reported timing and token data immediately in each run's `timing.json`. Follow `references/schemas.md`. If the host does not expose a value, use `null` or omit the optional field.

For cost comparisons, include parent and worker calls, reads, tool execution, and retries without double counting.
Separate recurring execution from development and grading overhead as defined in `references/execution-methods.md`.

### Step 5: Grade and aggregate

1. Read `agents/grader.md` and grade each run, using an independent worker when possible or grading inline otherwise. Save `grading.json`.
   Its expectation objects must use `text`, `passed`, and `evidence`.
2. Use a deterministic script only for assertions that satisfy "Automation boundary".
   Deterministic execution alone does not make a proxy or heuristic assertion valid.
3. Aggregate the iteration:

   ```bash
   python <skill-builder-path>/scripts/aggregate_benchmark.py <workspace>/iteration-N --skill-name <name>
   ```

   `tokens` comes only from `timing.json`; when the host reported none it stays `null` and the viewer shows N/A. Character counts are a different unit and are never substituted.
   Runs without a readable, schema-valid `grading.json` are listed under `incomplete` and excluded
   from every average and delta. The delta covers only the eval IDs both configurations completed.

4. Put each skill-enabled configuration before its baseline counterpart.
5. Read the relevant section of `agents/analyzer.md` and inspect non-discriminating assertions, high variance, regressions hidden by averages, and time/token tradeoffs.

### Step 6: Generate the review surface

Use the bundled generator rather than creating custom review HTML:

```bash
python <skill-builder-path>/eval-viewer/generate_review.py \
  <workspace>/iteration-N \
  --skill-name "my-skill" \
  --benchmark <workspace>/iteration-N/benchmark.json
```

For iteration 2+, add `--previous-workspace <workspace>/iteration-(N-1)`.

- With browser access, open the generated review page.
- In a headless host, add `--static <output-path>` and present the HTML artifact.
- Without presentable files, show each prompt, output, grade, and benchmark summary inline and collect feedback in the conversation.

Tell the user how to review outputs and where quantitative results appear. Generate the review surface before making subjective revisions so the user sees the evidence early.

### Step 7: Read feedback

When file-based feedback is available, read `feedback.json`. Check its `status` first: only when it is `complete` does an empty feedback entry mean the output was acceptable. With `in_progress` or no file, the review has not finished, so ask the user rather than treating silence as approval. Prioritize specific complaints. Stop any temporary viewer server after review.

## Improving the skill

1. Generalize from feedback instead of patching only the tested examples.
   Write the decision procedure, not the instances: a test the agent can apply to a case the skill never saw, followed by two or three pairs marked as illustrations rather than the full set.
2. Keep the prompt lean and remove instructions that create repeated unproductive work, but compress only where meaning survives.
   Preserve every constraint, threshold, and scope, and make each rule unambiguous to a coding agent with no other context.
   When a cut would cost clarity, move the detail to a reference instead of deleting it.
3. Explain why constraints matter so capable models can adapt to novel cases.
4. When multiple runs recreate the same helper logic, first compare available host capabilities, established tools, and simple tool compositions.
   Bundle a script only when it satisfies "Automation boundary" and provides a measurable correctness, maintenance, or performance benefit.
5. When multiple runs repeat a contextual judgment, improve the skill's decision procedure and examples instead of converting the judgment into a script.
6. Keep portable behavior in the core and isolate host-specific mechanics in adapters.
   For a multi-host skill, decide where a fix belongs with the failure-attribution rule in
   "Multiple target hosts".

After revising behavior, rerun the affected cases in a new iteration.
Compare against the original or previous version according to the user's decision.
Present the comparison inline for a small review, or link the review surface to the previous iteration.
Repeat only for unresolved findings within the trial budget; report inconclusive comparisons honestly.

## Advanced: blind comparison

For rigorous A/B comparison, read `agents/comparator.md` and `agents/analyzer.md`. Give outputs to an independent judge without revealing which configuration produced them.
The comparator may return `TIE`; the analyzer accepts `A`, `B`, or `TIE` and, on a tie, analyzes both skills without inventing a winner.
If no independent worker exists, skip blind comparison and disclose that limitation.

## Description optimization

After skill behavior is stable, read [Description optimization](references/description-optimization.md)
when tuning the frontmatter description or running trigger evaluations.
Choose direct prompts or the model runner by workload and the execution-method comparison rules.

## Package and present

Validate first:

```bash
python <skill-builder-path>/scripts/quick_validate.py <path-to-skill-folder>
```

Validation requires PyYAML and rejects an empty `name` or `description`. Each bundled `scripts/check_*.py` detector gets 60 seconds; one that runs longer is reported as `TIMEOUT` and fails the check.

When Python and filesystem access are available, package with:

```bash
python <skill-builder-path>/scripts/package_skill.py <path-to-skill-folder> [output-directory] [--check-installed]
```

The output directory must lie outside the skill folder. The package never contains `.env` files, `.git`, earlier `.skill` files, `evals/`, `*-workspace/` directories, or symbolic links; each skipped link is reported.
The packager builds and verifies a temporary ZIP beside the destination, then replaces the final
`.skill` file. A failed build removes the temporary file and preserves any existing package.
Pass `--check-installed` only when you want other installed copies of the skill compared file by file; without it the packager never reads the user's home directory.

Packaging one skill excludes files in sibling skills. Ship the bundle with the sibling directory
layout preserved, or copy the referenced rules into the skill and update its references before
packaging it alone.

Use the host's native artifact presentation mechanism when available; otherwise provide the exact output path.
If the installed source is read-only, copy it to a writable temporary location, preserve its original name, edit and package the copy, then return the result.

## Reference files

- `agents/grader.md` — assertion-based output grading
- `agents/comparator.md` — blind A/B comparison
- `agents/analyzer.md` — benchmark and variance analysis
- `references/schemas.md` — eval, grading, timing, and benchmark schemas
- `references/execution-methods.md` — method selection, comparison models, trials, and recurring cost decisions
- `references/description-optimization.md` — trigger evaluation and description optimization when requested

## Completion checklist

- Intent, triggers, outputs, and constraints are explicit.
- Core instructions use capability-based language and avoid accidental vendor coupling.
- Every example was graded against the skill's own rules: good examples satisfy all of them, bad examples violate the rule they illustrate.
- Required host-specific behavior is isolated and documented.
- For a multi-host skill, every host was evaluated on the same eval corpus, and each adapter rule
  traces to a host difference that a shared clarification could not fix.
- Every translated mirror in the skill matches its current source, including reversed rules,
  deletions, and renames.
- Every sibling reference is declared with its relative path, its purpose, and its missing-file
  behavior; the skill invokes no sibling skill and depends on no sibling scripts.
- Every bundled script has a complete input and output contract and reports unsupported inputs explicitly.
- Every bundled validator is sound and complete within its declared scope; contextual judgments remain with the model or user.
- Existing host capabilities and established tools were compared before custom code was added.
- Performance claims are measured on representative inputs and are not inferred from an implementation language.
- Every launched worker and model runner used the current host's required model and effort without
  cross-host substitution; unavailable runs were marked unverified.
- Uncertain or changed methods were compared using actual outputs or explicitly marked unverified;
  unavailable metrics were not invented.
- Skill Builder and the target skill were checked for recurring execution cost without weakening quality.
- The target skill records its method and switching conditions without requiring per-use benchmarks.
- Time/token tradeoffs follow the quality criteria and user limits; development and evaluation costs stay separate.
- Realistic skill-enabled and baseline tests were run, or capability limitations were disclosed.
- Assertions and metrics are evidence-backed.
- The user received a review surface or equivalent inline review.
- The final skill validates and is packaged or handed off in the requested form.
