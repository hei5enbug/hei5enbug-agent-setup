---
name: skill-creator
description: Create, modify, validate, and evaluate agent skills across AI agent hosts. Use when users want to build a skill from scratch, improve an existing skill, test skill behavior against a baseline, benchmark quality and variance, package a skill, or optimize its description for reliable triggering. Apply this skill to portable SKILL.md instruction bundles as well as host-specific skill packages, while preserving the target host's required metadata and conventions.
compatibility: Core authoring works in any agent host. Bundled scripts require Python and filesystem access; model-backed description optimization accepts any command that reads a prompt from stdin and writes a response to stdout.
---

# Skill Creator

Create and improve skills through an iterative draft → test → review → improve loop.

## Portability contract

Keep the workflow stable across agent products by adapting to capabilities, not product names.

1. Inspect the current host before choosing mechanics. Check for independent workers, filesystem access, subprocess execution, browser/display access, connected research tools, and artifact presentation.
2. Preserve the core stages even when a capability is absent: capture intent, draft, test, review, improve, and package or hand off.
3. Use neutral terms such as **agent**, **host**, **worker**, and **model runner** in portable instructions. Mention a specific product only inside an explicitly scoped adapter or when the user's target requires it.
4. Do not assume hidden environment variables, private tool names, installation directories, or CLI syntax. Discover them or accept them as configuration.
5. Keep outputs and schemas consistent across hosts. When a metric is unavailable, use `null` or omit an optional field; never fabricate data.
6. Preserve host-specific manifests and metadata when modifying an installed skill. Put shared behavior in `SKILL.md` and isolate unavoidable host integration in a small adapter or clearly labeled reference.
7. Do not infer an installation root, manifest format, or package layout from the current authoring host when the user has not selected a target. Use a task-local writable path for drafts, or ask for the destination when it materially affects the result.
8. Keep every skill self-contained. A skill may use its own bundled resources and declared host
   capabilities, but must not name, import, invoke, read, or depend on a sibling skill's files.
   Duplicate a small essential rule when necessary instead of creating a cross-skill handoff.

Use this capability mapping:

| Capability | Preferred path | Fallback |
|---|---|---|
| Independent workers | Run with-skill and baseline cases in parallel | Run sequentially and disclose reduced independence |
| Filesystem | Use iteration workspaces and bundled scripts | Present prompts, outputs, grades, and feedback inline |
| Browser/display | Open the generated review page | Generate static HTML; if files cannot be presented, review inline |
| Model subprocess | Run description optimization with a configured runner command | Evaluate and revise descriptions inline with the same rubric |
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

## Communicating with the user

Match the user's technical level. Terms such as “evaluation” and “benchmark” are usually fine; explain formats such as JSON and concepts such as assertions when context suggests they may be unfamiliar.

Lead with decisions and results. Explain why a test or structural choice matters, especially when a missing host capability reduces rigor.

## Creating or updating a skill

### Capture intent

Extract answers from the conversation and existing files before asking for information the user already supplied.

1. What should this skill enable an agent to do?
2. When should it trigger, including likely user phrases and contexts?
3. What output or side effect should it produce?
4. What constraints, dependencies, edge cases, or safety boundaries apply?
5. Would test cases add value? Objectively verifiable work usually benefits from tests; highly subjective work may rely more on human review.
6. Which hosts must support the skill, and which parts truly need host-specific integration?

When updating an existing skill, preserve its original directory name and `name` field unless the user explicitly requests a rename. Snapshot the original before editing so it can serve as the baseline.

### Interview and research

Ask only for gaps that materially change the implementation. Investigate available connected tools, local references, examples, and comparable skills when useful. Run independent research in parallel when the host supports it; otherwise research inline.

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
├── scripts/            # optional deterministic or repetitive tooling
├── references/         # optional documentation loaded as needed
├── assets/             # optional templates and output resources
└── adapters/           # optional host-specific integration boundaries
```

Keep host-specific manifests when the target requires them. Do not duplicate the core workflow across adapters.
Do not create a product-specific manifest merely because the current agent host supports one; add it only for a requested target or preserve it when updating an existing package.

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

The skill must match the user's stated intent. Do not create malware, exploit workflows, covert data access, misleading behavior, or unexpected external side effects. Make material writes and external actions visible in the instructions.

### Writing patterns

Use imperative instructions and explain the reasoning behind important constraints. Prefer adaptable principles over repeated all-caps mandates.

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

Create 2–3 realistic prompts for the first iteration. Share them for confirmation when user judgment is needed; if the user has already authorized execution and the expected behavior is clear, proceed and report the chosen cases.

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

### Step 1: Prepare the workspace and baseline

With filesystem access, create `<skill-name>-workspace/` beside the skill. Organize results as `iteration-N/<descriptive-eval-name>/`.

For a new skill, the baseline receives no skill. For an existing skill, snapshot the original before editing and use that snapshot as the baseline. Keep the active and baseline prompts, inputs, model settings, and requested outputs identical.

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

When independent workers exist, launch every with-skill and baseline run together so timing conditions are comparable.

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

If independent workers are unavailable, run the same pairs sequentially. Keep the baseline instructions isolated from the revised skill as much as the host permits and record that the comparison has lower independence. If even sequential execution or persistent outputs are unavailable, perform a focused sanity check inline and ask the user to judge the examples directly.

### Step 3: Draft assertions while runs execute

Create objective, descriptive assertions for machine-verifiable requirements. Avoid forcing quantitative assertions onto subjective qualities. Update both `eval_metadata.json` and `evals/evals.json`, then explain what the assertions measure.

### Step 4: Capture available metrics

Save host-reported timing and token data immediately in each run's `timing.json`. Follow `references/schemas.md`. If the host does not expose a value, use `null` or omit the optional field.

### Step 5: Grade and aggregate

1. Read `agents/grader.md` and grade each run, using an independent worker when possible or grading inline otherwise. Save `grading.json`. Its expectation objects must use `text`, `passed`, and `evidence`.
2. Prefer a deterministic script for assertions that can be checked programmatically.
3. Aggregate the iteration:

   ```bash
   python -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name <name>
   ```

4. Put each skill-enabled configuration before its baseline counterpart.
5. Read the relevant section of `agents/analyzer.md` and inspect non-discriminating assertions, high variance, regressions hidden by averages, and time/token tradeoffs.

### Step 6: Generate the review surface

Use the bundled generator rather than creating custom review HTML:

```bash
python <skill-creator-path>/eval-viewer/generate_review.py \
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

When file-based feedback is available, read `feedback.json`. Empty feedback means the output was acceptable; prioritize specific complaints. Stop any temporary viewer server after review.

## Improving the skill

1. Generalize from feedback instead of patching only the tested examples.
2. Keep the prompt lean; remove instructions that create repeated unproductive work.
3. Explain why constraints matter so capable models can adapt to novel cases.
4. Bundle scripts or references when multiple runs independently recreate the same helper logic.
5. Keep portable behavior in the core and isolate host-specific mechanics in adapters.

After revising, rerun the cases in a new iteration. Compare against the original or previous version according to the user's decision, generate a review surface with the previous iteration linked, and repeat until the user is satisfied or no meaningful improvement remains.

## Advanced: blind comparison

For rigorous A/B comparison, read `agents/comparator.md` and `agents/analyzer.md`. Give outputs to an independent judge without revealing which configuration produced them. If no independent worker exists, skip blind comparison and disclose that limitation.

## Description optimization

The frontmatter description is the primary routing signal in most skill hosts. Optimize it only after the skill behavior is stable.

### Build a trigger eval set

Create about 20 realistic queries with a balanced mix of `should_trigger: true` and `false`. Include:

- varied phrasings, lengths, detail levels, and mild typos
- uncommon but valid uses
- close competitors where this skill should win
- difficult near-misses that share vocabulary but need another workflow

Avoid trivial positives and obviously unrelated negatives. Save the array as JSON:

```json
[
  {"query": "a realistic user request", "should_trigger": true},
  {"query": "a difficult near-miss", "should_trigger": false}
]
```

Use `assets/eval_review.html` to let the user inspect and edit the set when browser or artifact presentation is available.

### Configure a portable model runner

The bundled optimizer does not assume a vendor CLI. Supply a command that reads the full prompt from standard input and writes only the model response to standard output:

```bash
python -m scripts.run_loop \
  --eval-set <trigger-eval.json> \
  --skill-path <path-to-skill> \
  --runner-command '<your-model-command>' \
  --max-iterations 5 \
  --verbose
```

The command may contain `{model}` in an argument; when it does, also pass `--model <model-id>`. Instead of repeating `--runner-command`, set `SKILL_CREATOR_RUNNER_COMMAND`. Use `--no-open` in a headless environment.

The runner contract deliberately uses stdin/stdout and executes without a shell. A host-specific wrapper can therefore adapt a CLI, local model server, or API client without changing the optimizer.

Trigger evaluation uses a stable routing simulation based only on the skill name, description, and query. This makes scores comparable across runners, but it is a proxy for a host's private routing implementation. When native host trigger tests are available, run them as an additional integration check rather than replacing the portable benchmark.

In every description-optimization handoff, explicitly label the reported score as a portable routing simulation and state that native trigger checks are still required before claiming equivalent behavior in a specific host.

The loop uses a stratified train/test split, repeated routing decisions, and held-out score selection to reduce overfitting. Apply `best_description` from the output and report before/after scores.

If no subprocess model runner is available, perform the same routing classification and revision loop inline. Keep held-out queries hidden during revision and label the result as an inline evaluation.

## Package and present

Validate first:

```bash
python scripts/quick_validate.py <path-to-skill-folder>
```

When Python and filesystem access are available, package with:

```bash
python -m scripts.package_skill <path-to-skill-folder> [output-directory]
```

Use the host's native artifact presentation mechanism when available; otherwise provide the exact output path. If the installed source is read-only, copy it to a writable temporary location, preserve its original name, edit and package the copy, then return the result.

## Reference files

- `agents/grader.md` — assertion-based output grading
- `agents/comparator.md` — blind A/B comparison
- `agents/analyzer.md` — benchmark and variance analysis
- `references/schemas.md` — eval, grading, timing, and benchmark schemas

## Completion checklist

- Intent, triggers, outputs, and constraints are explicit.
- Core instructions use capability-based language and avoid accidental vendor coupling.
- Required host-specific behavior is isolated and documented.
- The skill contains no sibling-skill names, paths, invocations, imports, or file dependencies.
- Realistic skill-enabled and baseline tests were run, or capability limitations were disclosed.
- Assertions and metrics are evidence-backed.
- The user received a review surface or equivalent inline review.
- The final skill validates and is packaged or handed off in the requested form.
