# Repository development

> These instructions apply only when developing this repository.
> Plugin hooks load only `instructions/session/` and do not load this file.
> Everything under `instructions/` defines plugin runtime behavior that ships to users; it is not a
> repository development rule. Those runtime rules also govern work on this repository. When the host did
> not load them, read `instructions/session/core.md`, `instructions/session/common.md`, and the file for the
> current host first.

- Review requirements before implementation. If an incorrect or undefined term, multiple plausible
  interpretations, a contradiction, or a missing decision could materially change the result, scope,
  contract, or acceptance criteria, explain the possible interpretations and their impact, then ask the user.
  When code, schemas, a glossary, or an existing agreement leaves only one interpretation, apply it and state
  the basis. Until a decision only the user can make is resolved, do not edit files or change external state.
  Continue only read-only investigation that does not presuppose the answer.
- Before changing hooks, agents, skills, settings, or plugin structure, check the current official Claude Code and
  Codex documentation pages for the area you change, including features such as mods, hook events, settings, and
  agent options. Prefer a supported feature that covers the need over custom code, and state which features you
  checked and why you chose the approach.
- Every change to this repository must improve, or at least preserve, both the recurring token and context cost
  of normal use and the quality of its output. Never trade one for the other without measured evidence and the
  owner's decision.
  Preserve correctness and required validation while reducing unnecessary instruction loading, repeated reads,
  tool calls, and duplicated content. Reuse loaded instructions and validation results only while their relevant
  inputs remain unchanged. During local work, run checks affected by the change; broaden them for unresolved risks.
- Maintain a complete, meaning-equivalent Korean mirror for every human-readable English Markdown file at
  `docs/ko/<repository-relative source path with the final .md replaced by .ko.md>`. Update, move, or delete
  each source and its mirror together. Start each mirror with its title, then a quoted block linking the English
  source with a relative path and stating that the mirror is non-authoritative and never read during execution.
  Keep every `.ko.md` file out of `skills/`, `agents/`, and `instructions/`, and never link to a `.ko.md` file from
  a file under those folders. Only a root reader document such as `README.md` may link Korean mirrors.
  Do not duplicate code, schemas, test fixtures, generated artifacts, or non-English documents.
- Before changing a skill, read `skills/skill-builder/SKILL.md` unless its current contents are already loaded.
  For a direct edit, read only its "Portability contract", "Core loop", and "Translated mirrors" sections; read the
  whole file to create a skill or to take its evaluation path. Follow its direct-edit or evaluation path as
  appropriate to the change. For plugin structure, manifests, or hooks, use `plugin-creator` when the host provides
  it and preserve the existing plugin contracts.
- Keep shared behavior in one canonical source and isolate only actual host differences. A rule the session
  instructions already state belongs there alone; reference it instead of restating it.
- [Rule enforcement](docs/rule-enforcement.md) pairs each written rule with the check that enforces it. When a user
  correction repeats a written rule that no check enforces, raise it a level in the same change as that file
  describes and update its row. Remove a written rule once its check makes the mistake impossible.
- Before creating an issue, search the existing ones. Write issues, pull requests, comments, and commit messages in
  English and follow the existing issue conventions. "Public boundary" at the end of this file governs what any file,
  commit, or message may contain.
- For repository implementation, use a Claude Code plugin worker subagent by default. Codex
  project roles in `.codex/agents/` cover the other routes:

  | Role | Primary name | Model / effort | Fallback name | Model / effort |
  |---|---|---|---|---|
  | Bounded implementation and debugging, easy work | `haiku_worker` | `claude-haiku-5-5` / `xhigh` | `worker` | `gpt-6.1-sol` / `high` |
  | Bounded local, read-only evidence | `scout` | `gpt-5.6-luna` / `xhigh` | `haiku_scout` | `claude-haiku-5-5` / `xhigh` |
  | Mechanical documentation edits with approved content | `writer` | `gpt-6.1-sol` / `high` | `haiku_writer` | `claude-haiku-5-5` / `xhigh` |
  | One read-only final review of a completed bounded change | `code_reviewer` | `gpt-6.1-sol` / `high` | `opus_code_reviewer` | `claude-opus-5-5` / `high` |

  `haiku_worker` and `sonnet_worker` name the plugin's `hei5enbug-agent-setup:worker` and
  `hei5enbug-agent-setup:sonnet-worker` subagents. The other `haiku_*` names and `opus_code_reviewer` are
  assignment labels for separate Claude Code CLI processes, not registered `--agent` names. `worker`, `scout`, `writer`, and `code_reviewer` are Codex
  project roles. Each role has exactly one fallback in the other model family: Claude to GPT or GPT to
  Claude. A named fallback is preauthorized only when
  the primary executable, authentication, quota, role, requested settings, or reliable settings evidence
  is unavailable. Announce the reason and selected route. Stop any started primary, inspect its partial
  work, and transfer only verified unfinished work with the same scope, permissions, and checks. Try the
  one listed fallback at most once per assignment; if it is also unavailable, continue in the main session.
  Skip a fallback that shares a confirmed authentication, quota, or capability blocker with the primary.
  A fallback never resolves a missing user decision or bypasses a permission or failed acceptance check.

  This repository routing overrides the plugin's model and effort routes for these roles and assigns
  mechanical documentation work to `writer` and bounded final review to `code_reviewer`.
  All other plugin ownership, permission, and verification rules still apply. Request the listed model
  and effort explicitly when the host supports it, and verify
  the actual host rollout before relying on either a primary or fallback role. Do not override a pinned
  primary role's model to invoke its fallback; use the named route on its own host. The Codex project
  roles take effect in a fresh Codex session.

  For a Claude fallback, pass the corresponding primary Codex role's `developer_instructions` and the
  bounded assignment on stdin. This preserves one source for each role's scope. Run `claude -p` with
  the table's full model ID and effort, `--output-format json --permission-mode dontAsk --strict-mcp-config`.
  For `haiku_scout` and `opus_code_reviewer`, add `--tools Read Grep Glob --allowedTools Read Grep Glob`.
  For `haiku_writer`, add `--tools Read Grep Glob Edit Write --allowedTools Read Grep Glob` plus
  `Edit(//<absolute allowed path>)` for each assigned Markdown file and mirror; an Edit rule also covers Write,
  and `//` marks an absolute path. The main
  session runs its assigned checks. Never expose shell, network, or delegation tools to these fallbacks.
  Accept output only when JSON `modelUsage` names the requested model and the existing effective-settings
  checks confirm the effort. Reapply model, effort, tool limits, and assignment scope on a CLI resume.
  These are recovery choices, not measured claims of fallback quality or cost superiority.

  When comparing explicitly requested alternatives to the selected implementation route, prioritize
  fully solved tasks, then compare cost per solved task against the
  additional Code quality when completion is comparable. Include failed attempts in the cost; do not
  collapse quality and cost into an arbitrary ratio or ignore the reports' measurement limits.
  Route easy work to `scout` for bounded, local, read-only evidence and to `writer` for coordinator-approved
  mechanical Markdown and mirror edits. The `scout` pin `gpt-5.6-luna`/`xhigh` follows the user's explicit
  selection; earlier local comparisons do not establish its quality. `writer` moved to `gpt-6.1-sol`/`high` after a
  2026-10-17 blind comparison of three mirror-edit assignments: Sol passed 17 of 18 expectations with one needed
  fix and fewer tokens, and Luna passed 9 of 18 with 19 fixes. In Claude Code, run `writer` as
  `role_runner.py language` with its role definition as `--instructions`. The main session defines the cause,
  allowed edit paths, change requirements, and runnable acceptance checks before assigning implementation.

  The main session chooses the implementation worker by difficulty and usage:

  | Work | Worker |
  |---|---|
  | Easy: one cohesive change with a stated edit and checks that cover it fully | `haiku_worker`: the `hei5enbug-agent-setup:worker` subagent while the session line "Worker agent model" shows `claude-haiku-5-5` at `xhigh`; otherwise `sonnet_worker` |
  | Normal or hard: a behavioral change, several files, parsing, security, or concurrency | `sonnet_worker`: the `hei5enbug-agent-setup:sonnet-worker` subagent (`claude-sonnet-5-5` / `high`) |
  | Claude usage limit reached or a Claude worker unavailable | `worker` (`gpt-6.1-sol` / `high`): in Claude Code, `role_runner.py implementation --fallback --instructions <worker role definition>` run from the folder that holds the allowed paths; in Codex, the `worker` role |

  Spawn these plugin subagents instead of `claude -p` processes. On 2026-10-22 the auto-mode classifier blocked
  `claude -p` workers that edit the approval guard as self-modification, and `dontAsk` stopped them on commands the
  guard asks about, while the `sonnet-worker` subagent made the same kind of change unblocked and its subagent record
  showed `claude-sonnet-5-5` at `high`.

  On 2026-10-17, three real approval-guard tasks (classification, session state, a mod) ran once each on Sonnet
  `high` and Sol `high`. All six passed the coordinator's tests. A blind review needed 5 fixes in total for Sol and
  10 for Sonnet, and Sol used 30 to 54 percent of Sonnet's output tokens and finished faster. Two easy tasks then
  ran once each on Haiku, Sonnet, and Sol at `high`. A settings edit needed no fix on any model, and Haiku cost about
  a ninth of Sonnet's API price ($0.018 against $0.159). A script that reads usage records, with file and parsing edge
  cases, needed 1 fix from Sol, 4 from Haiku, and 6 from Sonnet. One run per model and task is thin evidence, and
  Sol's price was not measured in dollars. The plugin's `implementation_worker` `auto` route applies the same rule at
  runtime. On 2026-10-20 the user moved normal and hard work to Sonnet so that implementation stays on Claude while
  investigation and final review stay on GPT; Sol became the fallback.

  Do not override a plugin agent definition or put an Anthropic model in a Codex role. Reapply model and
  effort on a CLI resume; follow the existing readiness and actual host-record checks before relying on a
  worker's result. A worker reports new causes or missing decisions to the main session instead of widening
  scope.

  Run one read-only final review of the combined final diff, sized to the change and to its authoring family:

  | Change | Final review |
  |---|---|
  | Trivial: a typo, wording, version, or metadata edit, a translation, or a mechanical edit its checks fully cover | None |
  | Bounded, Claude-authored: one component with clear acceptance checks and no public contract, security, concurrency, hook, or guard change | `role_runner.py reviewer --model gpt-6.1-sol`, which runs at the runner's default `high` |
  | Complex, Claude-authored: several components, a public contract, security, concurrency, or a hook or guard | `role_runner.py reviewer --model gpt-6-astra --effort xhigh` |
  | GPT-authored, including work drafted on `gpt-6.1-sol` | `role_runner.py reviewer --model claude-opus-5-5`, or `claude-fable-5-1` with `--effort xhigh` when complex |

  It runs automatically once, after all work for the request is done and its checks pass, over the combined final
  diff; any earlier review needs the user's approval. Give the reviewer the final diff, requirements, and check
  evidence. When the `gpt-6-astra` reviewer is unavailable on a Claude-authored change, use the `code_reviewer` route
  instead. The main session verifies findings and decides acceptance; do not start a second review round. Its
  review accuracy was not measured by Frontier v4.

  Frontier v4 covers 23 challenging behavioral-reconstruction tasks with one attempt per model and effort.
  It defines no easy/normal/hard labels and evaluates no documentation; the routing above is this
  repository's policy, not a benchmark result or a claim of general model superiority.

  The user selected Haiku xhigh for bounded implementation and Sol high for bounded final reviews.
  This is a role preference, not a claim that Haiku wins completion or cost efficiency on Frontier v4,
  or that implementation scores establish review accuracy. The reports use different harness versions
  and cost bases, so costs are API/list-price estimates rather than subscription bills. See the
  [Haiku comparison](https://vulcanbench.com/benchmarks/swe-v4-haiku55-vs-frontier.html),
  [Luna comparison](https://vulcanbench.com/benchmarks/swe-v4-gpt55-luna-v35.html), and
  [VulcanBench methodology](https://vulcanbench.com/methodology.html). Keep problem definition, complex
  root-cause reasoning, plans, designs and RFCs, and acceptance decisions in the main session. The
  `designer` and `reviewer` roles keep their existing host routes.
- Before changing this repository, when `PINS_VERIFIED_ON` in `tests/test_model_pins.py` is more than 14 days old,
  resolve the newest generally available model of every family in `pins` in `config/model-registry.json`, except
  GPT Luna, then set `PINS_VERIFIED_ON` to that date. GPT Luna stays at the user-selected `gpt-5.6-luna`, `high` by
  default and `xhigh` under the effort rule (user selection 2026-10-20), until the user explicitly changes that
  selection.
  Use the official [Claude models overview](https://platform.claude.com/docs/en/about-claude/models/overview), the
  [OpenAI model catalog](https://developers.openai.com/api/docs/models), and each host's model catalog, and
  exclude previews. When a family has a newer release, update `pins` in `config/model-registry.json` and every
  reference in the same change until `tests/test_model_pins.py` passes. Runtime files name models only by these
  full IDs; never add an alias or a runtime lookup of the newest release.
- When tests skip because the Orca CLI is not installed, ask the user whether to install Orca and rerun them
  before you report the checks as passing.
- The release baseline is the newest `v<major>.<minor>.<patch>` tag reachable from `HEAD`. A version that appears only
  in the manifests is the planned next version, never a baseline, even when it is already on `main` or installed
  locally. Keep all unreleased work on that one planned version: the first change after the baseline sets it in the same
  commit, and a later change folds into it and re-chooses its level from the table below within its own commit instead
  of bumping again. Never bump the semantic version for local iterations. Install only a tagged release: when the user asks to install
  unreleased work, tag it first, so the next change starts the next planned version and no reinstall needs a
  cachebuster. Before changing any version, state the baseline tag and the planned version to the user. Keep both plugin manifests,
  `pyproject.toml`, and `uv.lock` on the same version. A release is a tag only; never make a separate commit to release
  or to change only the version. When the user publishes a release, run every development check in `README.md` on
  `HEAD`, tag `HEAD` `v<version>`, and push the tag. `tests/test_release_version.py` rejects a version below the
  baseline, more than one planned version since it other than a lower-level next version later re-chosen upward, a change
  since it while the planned version still equals it, and a
  commit since it that changes only version files.
  Choose the next semantic version from the highest-impact unreleased change:

  | Component | Use when |
  |---|---|
  | Major | The harness architecture or core control logic changes enough to replace its operating contract. |
  | Minor | A skill is added, removed, or merged, or its objective, requirements, or external contract changes. |
  | Patch | Existing skills keep their objectives and requirements while performance, reliability, evaluation quality, or output quality improves. Multiple such changes still produce one patch bump. |

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
