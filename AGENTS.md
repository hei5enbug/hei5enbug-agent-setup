# Repository development

> These instructions apply only when developing this repository. Plugin hooks load only `instructions/session/`, not
> this file. Everything under `instructions/` is plugin runtime behavior shipped to users, not a repository development
> rule, and it also governs work on this repository. When the host did not load those rules, first read
> `instructions/session/core.md`, `instructions/session/common.md`, and the file for the current host.

- Goal (owner, 2026-11-20): every skill, agent, and instruction produces the output its requirements define, at no
  lower quality, for the least cost and wall time.
- Review requirements before implementation. When an incorrect or undefined term, several plausible interpretations,
  a contradiction, or a missing decision could materially change the result, scope, contract, or acceptance criteria,
  explain the interpretations and their impact, then ask the user. When code, schemas, a glossary, or an existing
  agreement leaves only one interpretation, apply it and state the basis. Until a decision only the user can make is
  resolved, edit no file and change no external state; continue only read-only investigation that does not
  presuppose the answer.
- Before changing hooks, agents, skills, settings, or plugin structure, check the current official Claude Code and
  Codex documentation for that area, including features such as mods, hook events, settings, and agent options.
  Prefer a supported feature that covers the need over custom code, and state which features you checked and why
  you chose the approach.
- Every change must improve, or at least preserve, both the recurring token and context cost of normal use and the
  quality of its output. When they conflict, quality wins (owner, 2026-10-27): choose the option with the higher
  measured quality, never adopt one that lowers quality to save tokens, and record any added cost with its
  measurement in the change report. Preserve correctness and required validation while reducing unnecessary
  instruction loading, repeated reads, tool calls, and duplicated content. Reuse loaded instructions and validation
  results only while their relevant inputs remain unchanged. During local work, run the checks the change affects;
  broaden them for unresolved risks.
- Place each piece of work in the first of these that passes its cases and that the quality and efficiency rules in
  `docs/dev-rules/evaluation.md` keep: a deterministic script, check, test, or hook; a skill or agent pinned to the
  model those rules choose; the main session. A skill whose process and output
  barely vary always runs on the cost-effective model its measurement chose. This is the order of candidates to
  measure, not permission to change a model without a record: before measuring a rule, skill, agent, or hook change,
  check whether a deterministic script, check, test, or hook can do or enforce the same thing, and measure it as a
  candidate when it can.
- A change to a rule, skill, agent, hook, or route of this plugin is adopted or rejected only on a record under
  `evals/e2e/records/` that `evals/e2e/harness/cli.py record` wrote from a before and an after variant differing only
  by that change, run on both Claude Code and Codex and judged by the comparison rule in `evals/e2e/README.md`. A
  candidate with no record stays open as undecided: never close or drop it, and never call an existing rule
  sufficient, on a judgment alone. The owner decisions of 2026-11-19 on measuring and adopting changes are the
  exceptions to this whole bullet:
  - Run the regression cases of several changes to one area once, on their bundle, and split them per change only
    when the bundle fails. Run the cases that show each change's own effect per change.
  - For text people read, scripts check the form requirements, and the owner decides expression quality by a blind
    A/B comparison of the before and after texts. A case passes only when the owner judges the after text the same
    or better.
  - Adopt a change that alters no text a model reads (an instruction, a skill, or an agent definition) on
    deterministic tests and one real run, without a record.
  - Only while the owner excludes Codex and GPT models: adopt on a Claude Code record alone and list each Codex run
    it still owes in the change report; run each text review once, on `claude-sonnet-5-5` or `claude-opus-5-5` chosen
    per run through the text review script's model option, without changing the pinned review model; skip a review
    only where an owner-approved skip rule allows, and skip none before the owner approves one; and defer the final
    review until a GPT reviewer is available.
- Before designing or running an evaluation that costs model calls, writing issue acceptance criteria, choosing among
  measured candidates, changing how a rules file, skill, or instruction listed in `config/writing-surfaces.json` writes
  text people read or changing `scripts/text_review.py`, or changing the model of the `language` capability or of `scripts/text_review.py`, read
  `docs/dev-rules/evaluation.md`.
- Keep on an always-loaded surface, meaning a skill description, a `SKILL.md` body, or a session instruction file,
  only the rules that every run of that surface needs. Move a rule needed only under a condition to a reference file,
  and leave one entry line on the surface in the form "Before <action>, read <reference>." Reading that reference and
  stopping when it is missing follow the session core's conditional-instruction rule. A change that implements an
  issue reports its quality evaluation result and the before-and-after size, in lines or tokens, of the
  always-loaded text it changes. Put a development rule that only one action needs in `docs/dev-rules/` behind a root
  trigger line, never in a nested `AGENTS.md`, which Codex does not load below its working directory.
- Maintain a complete, meaning-equivalent Korean mirror of every human-readable English Markdown file at
  `docs/ko/<repository-relative source path with the final .md replaced by .ko.md>`, and update, move, or delete each
  source and its mirror together. Start each mirror with its title, then a quoted block that links the English source
  by relative path and states that the mirror is non-authoritative and never read during execution. Keep every
  `.ko.md` file out of `skills/`, `agents/`, and `instructions/`, and never link to one from a file under those
  folders; only a root reader document such as `README.md` may link Korean mirrors.
  Do not duplicate code, schemas, test fixtures, generated artifacts, or non-English documents.
- Before changing a skill, read `skills/skill-builder/SKILL.md` unless its current contents are already loaded: for a
  direct edit only its "Portability contract", "Core loop", and "Translated mirrors" sections, and the whole file to
  create a skill or to take its evaluation path. Follow its direct-edit or evaluation path as the change requires. For
  plugin structure, manifests, or hooks, use `plugin-creator` when the host provides it and preserve the existing
  plugin contracts.
- Keep shared behavior in one canonical source and isolate only actual host differences. A rule the session
  instructions already state belongs there alone; reference it instead of restating it.
- [Rule enforcement](docs/rule-enforcement.md) pairs each written rule with the check that enforces it. When a user
  correction repeats a written rule that no check enforces, raise it a level in the same change as that file
  describes and update its row. Remove a written rule once its check makes the mistake impossible.
- Before creating an issue, search the existing ones. Write issues, pull requests, comments, and commit messages in
  English and follow the existing issue conventions. "Public boundary" at the end of this file governs what any file,
  commit, or message may contain.
- By default, repository implementation goes to a Claude Code plugin worker subagent, bounded read-only evidence to
  `scout`, and coordinator-approved mechanical documentation edits to `writer`, and a change that is not trivial gets
  one final review after all its work. Before delegating repository work to a subagent, a CLI process, or a Codex role,
  before changing a role in `.codex/agents/` or a plugin agent definition, or before choosing or running that final
  review, read `docs/dev-rules/delegation.md`.
- An assignment to a subagent states completely the target, constraints, checks, return format, and every field the
  delegation rules require, and nothing unrelated.
- Before committing, changing any version, tagging, publishing a release, or installing the plugin, read
  `docs/dev-rules/release.md`.
- Before changing this repository, when `PINS_VERIFIED_ON` in `tests/test_model_pins.py` is more than 14 days old,
  read `docs/dev-rules/model-pins.md`.
- When tests skip because the Orca CLI is not installed, ask the user whether to install Orca and rerun them before
  you report the checks as passing.

## Public boundary (protected)

This repository, every commit in its history, and every tag, branch, issue, pull request, review, and comment on it
are public. None of them may contain:

- a local absolute path from a real machine, or a real user name, host name, or home folder;
- a secret, credential, token, private key, account identifier, internal URL, or other security-sensitive detail;
- content specific to a private organization or to a plugin that is not public: its names, products, services,
  repositories, infrastructure, schemas, ticket keys, people, or channels.

Write examples, fixtures, and evaluation data with clearly fictional values only, such as `example.com`,
`/home/test`, `/tmp/work`, `<plugin-root>`, `ABC-123`, and `demo` schemas. Keep this repository generic: it never
names or describes a plugin that depends on it.

Before every commit, run `python3 -m pytest tests/test_public_boundary.py` and inspect the staged diff and the
message for these values; fix every finding before committing. When such a value is found in published history,
stop and report it to the owner, and rewrite history only with the owner's explicit approval.

Change, weaken, move, or remove this section only when the owner explicitly asks for that change in the current
conversation and names this section. Make that change alone in its own commit, with no other change, and update the
section hash in `tests/test_public_boundary.py` in the same commit. A request for any other work never authorizes it.
Keep this section last in this file.
