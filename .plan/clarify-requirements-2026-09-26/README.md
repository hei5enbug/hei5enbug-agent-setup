# Clarify Requirements integration candidate

The user approved the unified workflow and name, then selected candidate-only preparation because native
question UI participation is unavailable. This directory contains a runnable, self-contained candidate.
The plugin still discovers the existing two skills under `skills/`; this candidate is outside that path.
Neither installed plugins nor user decision maps are changed. The repository version remains `0.6.0`.

The candidate combines evidence gathering, one human question when needed, answer checking, uncertainty
reassessment, and recording into one loop. Strict specification gates and persistent maps are conditional
capabilities of that loop. Ordinary tickets do not inherit the numeric specification threshold merely
because they use a map. Existing `.decision-navigator/` data, types, statuses, and atomic locks remain valid.

| Artifact | Purpose |
|---|---|
| [Candidate entrypoint](candidate/clarify-requirements/SKILL.md) | Executable English workflow; its adjacent Korean mirror is for human readers. |
| [Coverage](coverage.md) | Trace both original contracts and the agreed integration requirements to candidate files and evaluation cases. |
| [Verification record](verification.md) | Inspect completed checks, limited native observations, and remaining promotion gates. |
| [Remaining work](remaining-work.md) | Track the open work, prerequisites, completion evidence, and eventual replacement steps. |
| [Trial receipts](trial-results.json) | Inspect source hashes, individual runs, native usage, and diagnostic failures. |
| [Baseline](baseline.json) | Identify the original commit and skill directories. |
| [Candidate evals](candidate/clarify-requirements/evals/evals.json) | Preserve 20 original cases and add 9 integration boundaries. |
| [Case mapping](candidate/clarify-requirements/evals/source-cases.json) | Map original case IDs to candidate IDs. |
| [Read-only comparison runner](run_readonly_trials.py) | Run bounded native Codex CLI comparisons with actual file reads in disposable workspaces. |

## Local use and checks

From the repository root, validate and run the candidate's deterministic tests:

```bash
python3 skills/skill-builder/scripts/quick_validate.py .plan/clarify-requirements-2026-09-26/candidate/clarify-requirements
python3 -m pytest .plan/clarify-requirements-2026-09-26/candidate/clarify-requirements/tests
```

For a trial, use a disposable filesystem copy and explicitly point the native main session at that copy's
SKILL.md. Do not install the candidate into a live user's skill directory to evaluate it. The map fixture
must also be copied into the trial workspace; never resolve or claim the checked-in fixture itself.
The package helper may produce a `.skill` file outside the candidate directory. Its normal exclusions
keep evaluation fixtures and workspaces out of the archive as specified by the existing packaging contract.

For reproducible noninteractive comparisons, first export the commit in baseline.json to a temporary
directory, then run the following with absolute paths. The output directory must be empty.

```bash
python3 .plan/clarify-requirements-2026-09-26/run_readonly_trials.py \
  --baseline-root <exported-baseline> \
  --candidate <absolute-candidate-directory> \
  --output-dir <empty-temporary-directory> --case frontier --pairs 3
```

`missing-scoring` is the other read-only case. The runner freezes both instruction closures, alternates
old/new ordering, and records usage, actual command counts, failures, and wall time. It requests exactly
`gpt-5.6-luna` with `xhigh`; absent resolved-model telemetry remains null. These runs do not exercise native
question UI, writes, human confirmations, or installed-plugin discovery. Raw transcripts remain in the
temporary workspace. Summaries must distinguish requested settings from observed runtime evidence.

## Native UI evaluation

The existing adapter requires Sonnet 5/high in Claude Code and gpt-5.6-luna/xhigh in Codex. It prohibits
launching Sonnet from Codex. Start the Claude lane in Claude Code, and use native main sessions on both
hosts. Codex strict interviews use Plan mode as specified by ask-ui.md. Do not replace the operator with
an agent or count an inline simulation as native UI coverage.

Use candidate cases 1–13 and their operator guides for strict interviews; mapped human cases are 14–20.
The operator keeps answer guides outside the model prompt and supplies answers only when asked.
If the question sequence differs, record the actual question/answer alignment instead of injecting an
unrelated scheduled answer. Preserve raw human wait time and mark noncomparable timing separately.
Use the same inputs, permissions, acceptance criteria, and model/effort for old/new pairs. Freeze a budget
of three pairs per affected case before starting. Keep baseline and candidate references isolated.

## Promotion conditions and migration

Candidate preparation does not establish target-model quality or execution-cost equivalence. Promotion
requires the agreed native lanes, required human cases, preserved critical criteria, and sufficient complete
time/usage evidence. Missing evidence is not success; noisy or incomplete comparisons do not justify adoption.

After those conditions pass, the replacement is `skills/clarify-requirements/`. Retire the two old registered
skill directories together and migrate their README/host metadata references to the one new name; do not
create three independently maintained workflows. Keep the existing map storage path and lock helper contract.
Update the hardcoded fixture paths in `tests/test_korean_mirrors.py`, and retain the moved skill tests/evals.
Historical source links should point to their frozen commit when the old source directories are retired.

The skill merge is a minor-version change under AGENTS.md. Verify the latest published release at promotion,
choose one planned next minor version, and keep both plugin manifests, pyproject.toml, and uv.lock aligned.
Do not bump versions for candidate iterations. Run all README development checks and the required plugin
validation before delivery; any later release or live session refresh follows its own authorization.
