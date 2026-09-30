# hei5enbug-agent-setup

**English** | [한국어](./README.ko.md) | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | [Español](./README.es.md) | [Deutsch](./README.de.md) | [Français](./README.fr.md)

A portable collection of custom skills for AI coding agents, built to be shared across multiple agent hosts without host-specific rewrites.

## Overview

Each plugin skill lives in its own folder under `skills/` and is self-contained. Skills kept outside the
plugin bundle live under `standalone-skills/`. The same `SKILL.md` works unmodified on every supported host.

## Supported Hosts

- Claude Code
- Codex
- OpenCode (via the [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) plugin)

## Structure

```
hei5enbug-agent-setup/
├── .agents/plugins/marketplace.json
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── .codex-plugin/plugin.json
├── .github/workflows/validate.yml
├── AGENTS.md
├── AGENTS.ko.md
├── CLAUDE.md
├── CLAUDE.ko.md
├── hooks/hooks.json
├── instructions/
│   ├── claude-agents.md
│   ├── codex-agents.md
│   ├── confluence.md
│   ├── documentation.md
│   ├── implementation-execution.md
│   ├── implementation-planning.md
│   ├── independent-model-validation.md
│   ├── protected-values.md
│   ├── services.md
│   └── session/
│       ├── claude-code.md
│       ├── codex.md
│       └── common.md
├── scripts/
│   ├── agent_guard.py
│   └── session_context.py
├── tests/
├── LICENSE
├── pyproject.toml
├── agents/
│   ├── ko/
│   │   ├── scout.ko.md
│   │   └── worker.ko.md
│   ├── scout.md
│   └── worker.md
├── standalone-agents/
│   ├── codex-scout.toml
│   └── codex-worker.toml
├── standalone-skills/
│   └── omo-model-config/
└── skills/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── docs-rewrite/
    ├── document-to-confluence/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

Each plugin skill folder holds its own `SKILL.md` plus any references or scripts it needs. The plugin manifests
package the same `skills/` directory for Codex and Claude Code without copying skills into host-specific directories.
The `standalone-skills/` directory is not included in either plugin's skill discovery path.

The `agents/` directory ships with the Claude Code plugin, so installing the bundle adds the
`hei5enbug-agent-setup:scout` and `hei5enbug-agent-setup:worker` subagents. No manual copy is needed. The manifest
lists only these two English definitions, so the Korean mirrors in `agents/ko/` are not registered as subagents.

Codex discovers subagents only in `~/.codex/agents/` and `.codex/agents/`, so a plugin cannot register one.
Instead, the session hook copies `standalone-agents/codex-scout.toml` and `standalone-agents/codex-worker.toml` to
`~/.codex/agents/scout.toml` and `~/.codex/agents/worker.toml` when each file is absent. They define `scout` and
`worker` agents, named as on Claude Code, with a fixed reasoning effort and sandbox. The plugin `worker` replaces the
built-in Codex `worker`, and `scout` leaves the built-in `explorer` untouched. A file you edited is never
overwritten, and the agents become available in the next Codex session. Because an edited copy never changes,
the files set no model; the Codex instructions pass the pinned model on every spawn instead. The hook also
removes an `explorer.toml` and replaces a `worker.toml` that an earlier version wrote, but only while the file is
byte-identical to that version's bundled file, so a copy you edited stays. When the plugin is disabled, the installed
`worker` role runs as an ordinary implementation worker instead of refusing to edit.

A `PreToolUse` hook, `scripts/agent_guard.py`, keeps built-in subagents out on both hosts. On Claude Code it
denies an omitted subagent type and every built-in type: `general-purpose`, `Explore`, `Plan`, `claude`,
`claude-code-guide`, `statusline-setup`, and forks. Plugin agents and definitions from any user, project, CLI, or
managed source pass. On Codex it denies an omitted type, `default`, `explorer`,
and every type without a role file, including the built-in `worker` before the plugin role exists. Skills that ask
for an independent read-only worker use `scout`, and skills that write trial outputs run a separate `claude -p` or
`codex exec` process.

## Plugin installation

Install the bundle once from the GitHub repository.

### Codex

```bash
codex plugin marketplace add hei5enbug/hei5enbug-agent-setup --ref main
codex plugin add hei5enbug-agent-setup@hei5enbug
```

### Claude Code

```bash
claude plugin marketplace add hei5enbug/hei5enbug-agent-setup
claude plugin install hei5enbug-agent-setup@hei5enbug
```

## Automatic instructions

On macOS and Linux, the plugin hooks combine `instructions/session/common.md` with either
`instructions/session/codex.md` or `instructions/session/claude-code.md` for the current host.
Python 3.12 or later must be available as `python3` on the host's `PATH`.
The hook uses only the Python standard library.
Root `AGENTS.md` and `CLAUDE.md` govern development of this repository only; the hook never reads them.

Both hosts discover `hooks/hooks.json` automatically. Codex sets `PLUGIN_ROOT` to the installed plugin
directory; the loader uses that value to select Codex rules. Both hosts provide `CLAUDE_PLUGIN_ROOT`
for locating the script. No user or project instruction file is copied, linked, or overwritten.

| When | Behavior |
|---|---|
| Session starts or resumes | `SessionStart` supplies the installed instruction files. |
| Session clears or compacts | `SessionStart` supplies them again. |
| A subagent starts | `SubagentStart` supplies the same host's instructions. |
| A prompt arrives, a turn stops, or a session ends | The Orca refresh registry records session metadata without prompt text. |
| A matching task begins | The agent reads the required reference under `instructions/`. |
| A plugin update is installed | A new session reads that installed version. A repository push alone changes nothing locally. |

Core rules remain in session context across requests. Service access, protected-value access, agent use,
documentation, implementation execution, and requested planning or design details load only before the
matching action, even if it arises later in a request. The session context distinguishes implementation plans
from design documents and keeps their trigger boundary. `instructions/implementation-planning.md` owns the
six-stage implementation plan workflow and template. `technical-design-writer` owns design-document behavior,
and `instructions/independent-model-validation.md` owns their shared one-pass cross-family validation
contract. The loader resolves each session file's conditional links to absolute paths inside the installed
plugin. It does not read conditional reference bodies at startup.

Codex requires review and trust of the current plugin hook definition before running it.
Disabled hooks or enterprise policies that prohibit plugin hooks prevent automatic loading.
After installation or update, use the host's hook controls to check that these hooks are enabled and,
in Codex, trusted. A hook that an update adds, such as the agent guard, stays skipped in Codex until you trust it
in `/hooks`. Restart Claude Code or start a new Codex session after updating.
The hook does not bypass host trust settings or change an already running session to a new plugin version.
The `orca-plugin-refresh-resume` skill uses the registry after a one-time session bootstrap to update this plugin and
resume registered idle sessions.

A missing or empty session file, an invalid local reference, or context larger than 9,000 UTF-8 bytes produces an error on
stderr and no partial context. Session-start hook errors do not reliably block the host; resolve any
reported loading error before relying on automatic instructions. Keep the session files short and move
details into conditional references. Windows execution and live model adherence are not covered by the tests.

See the official [Codex hooks](https://learn.chatgpt.com/docs/hooks) and
[Claude Code hooks](https://code.claude.com/docs/en/hooks) contracts for lifecycle and trust behavior.

## Implementation workers

Workers make every implementation change. Before the first change, the main session reads
`instructions/implementation-execution.md` and acts as the coordinator. It keeps requirements,
investigation, planning, design, review, decisions, and the final report, and it never edits.
It prepares an executable task assignment even when the user supplied no plan or a plan without worker
assignments.

Automatic task preparation is not a requested implementation plan.

| Aspect | Automatic task preparation | Requested implementation plan |
|---|---|---|
| Trigger | Any implementation change | The user explicitly asks for a plan |
| Result | Assignments in the host's task list or the conversation, with no plan directory | The requested plan deliverable |
| Workflow | Task ID, result, paths, prerequisites, resources, checks, and model/effort per task | The six stages in `instructions/implementation-planning.md` |
| Independent validation | Never runs | Runs only after the confirmation gate in `instructions/independent-model-validation.md` |

Independent ready tasks run together, up to six workers and never beyond the host's actual limit. Six is a
ceiling, not a target: one cohesive task uses one worker. Excess tasks wait in a queue. Dependent tasks and
tasks that share files or other mutable resources run in order. Workers edit only their assigned paths and
never start agents, plan, or request plan review.

| Host | Worker | Model and effort | Blocked when |
|---|---|---|---|
| Codex | Plugin `worker` role installed by the session hook, spawned with an explicit model and effort and checked in its rollout record before any edit | `gpt-6-luna` at `xhigh`, pinned in the repository | Worker tools, the `worker` role file, the model, or `xhigh` are unavailable; the role file resolves to other settings; the rollout record is missing or names other settings |
| Claude Code | Bundled `hei5enbug-agent-setup:worker` from `agents/worker.md`, whose definition pins the model, invoked without a per-invocation model and checked in its subagent record before any edit | `claude-sonnet-5-5` at `high`, pinned in the repository | The plugin worker or its subagent record is missing; the record names another model or effort; a forced subagent model, an effort override, or a cap prevents `high` |

When a requirement is not met, the coordinator stops the affected implementation and reports the exact
blocking capability. It never substitutes another model tier, lower effort, another host, a generic agent, or
main-session edits. The plugin never overwrites an existing Codex `worker.toml` and changes no user
settings. The `scout` agents described above stay read-only.

Codex spawns sub-agents only when the user, `AGENTS.md`, or skill instructions ask for them. These rules arrive
through a hook, so without such a request a Codex session asks once for permission to delegate to workers. To skip
that question, add a line such as "Delegate implementation changes to worker sub-agents." to the project's or your
global `AGENTS.md`.

## Plugin updates

Both plugin manifests, `pyproject.toml`, and `uv.lock` must use the same semantic version.
Update them together after the development checks below pass and before publishing a release.
The newest `v<version>` tag reachable from `HEAD` is the release baseline. A version that appears only in these
files is the planned next version, even when it is already on `main`, so fold every unreleased change into it
instead of bumping again. Tag the released commit `v<version>` when you publish it.

Update Codex after the release is available:

```bash
codex plugin marketplace upgrade hei5enbug
codex plugin add hei5enbug-agent-setup@hei5enbug
```

Update Claude Code after the release is available:

```bash
claude plugin marketplace update hei5enbug
claude plugin update hei5enbug-agent-setup@hei5enbug
```

Start a new Codex thread or restart Claude Code after updating so the host loads the new skills and instructions.

### Refresh Orca agent sessions

Use `orca-plugin-refresh-resume` to refresh this plugin in idle Orca-managed Claude Code and Codex sessions, then
resume each session with its existing native session ID. The skill shows a plan and requires approval before it
updates marketplaces or stops any agent. Busy, unregistered, or ambiguous sessions, and sessions with unsent input,
stop the operation before it changes installed plugins. Claude Code background tasks and scheduled wakeups also block
a refresh. The worker
rechecks terminal identity and idle state immediately before exit, but host hook timeouts prevent an absolute
guarantee that no new prompt can arrive. A failed or unconfirmed completion notice requires receipt inspection;
never blindly resend it or resume a session while its replacement terminal may still be running. The lifecycle hook
blocks a prompt only while a refresh transaction is active; a session it cannot identify or a registry it cannot
read never blocks ordinary work outside a transaction. When the cached marketplaces show no change, `apply` still
starts a worker without leases; it refreshes the marketplaces and reports `already_current`, or `stale_plan` when a
newer release appeared, which needs a new plan.

Codex differs in three ways. It registers a session only when a prompt starts, so a Codex session that never
received a prompt blocks the plan until it receives one or is closed. After `/exit`, the worker waits until Codex
releases the conversation, which can take about a minute, and resumes it with its last recorded model and reasoning
effort. A resumed Codex session registers its plugin version on its next prompt; until then its receipt shows
`plugin_registration: pending_next_turn`.

The first rollout needs one manual bootstrap. Install the new plugin release, review and trust the Codex plugin hooks,
then restart or resume each existing session once. Earlier sessions have no lifecycle registry entry, so the
workflow cannot safely identify their native session IDs. After that bootstrap, the hooks keep the registry current
and later plugin refreshes can resume the registered sessions automatically. This workflow supports macOS and
Linux user-scope installations from the `hei5enbug` marketplace.

## Development checks

The bundled scripts need Python 3.12 or later with PyYAML, and the Node tests need Node.js. Run the same three
checks that `.github/workflows/validate.yml` runs on macOS and Linux:

```bash
python3 -m pip install -e ".[dev]"
for skill in skills/*/ standalone-skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$skill"; done
python3 -m pytest
node --test skills/document-to-confluence/tests/test_render_diagrams.mjs
```

Tests that need the Orca CLI skip when it is not installed, so CI passes without Orca. After installing Orca,
run `python3 -m pytest` again to cover them.

## Instruction language

English files are the canonical executable sources for plugin skills, references, agents, and session
instructions. Every human-readable English Markdown file has a meaning-equivalent adjacent `.ko.md` mirror.
Each mirror links its source, is non-authoritative, and must never be loaded during agent execution.
Update, move, and delete each source and mirror together.

Code, schemas, test fixtures, generated artifacts, and non-English documents do not need Korean duplicates.
Korean may remain in an executable English file only as target-language data, such as trigger phrases,
examples, required output labels, or evaluation fixtures. Structural checks verify mirror coverage and
execution-path isolation; semantic equivalence still requires human or model review.

## Skills

| Skill | What it does |
|---|---|
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | Maps a multi-session effort into decision tickets and resolves them one at a time until the implementation route is clear. [Korean guide](skills/decision-navigator/SKILL.ko.md). |
| [`deep-interview`](skills/deep-interview/SKILL.md) | Runs a Socratic interview that scores requirement ambiguity after every answer and will not move to execution until it drops below the threshold. [Korean guide](skills/deep-interview/SKILL.ko.md). |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | A shared design standard so flow charts built in SVG, HTML/CSS, Figma, or draw.io all read as one design system. [Korean guide](skills/flowchart-design/SKILL.ko.md). |
| [`docs-rewrite`](skills/docs-rewrite/SKILL.md) | Rewrites existing text so it reads naturally while every claim, number, and level of certainty stays identical, and repairs AI-sounding Korean. [Korean guide](skills/docs-rewrite/SKILL.ko.md). |
| [`document-to-confluence`](skills/document-to-confluence/SKILL.md) | Converts Markdown, HTML, PDF, DOCX, and Google Docs content into Confluence pages, preserves document structure and assets, and keeps pages synchronized with source revisions. [Korean guide](skills/document-to-confluence/SKILL.ko.md). |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Creates, tests, and packages agent skills through a draft → test → review → improve loop. [Korean guide](skills/skill-builder/SKILL.ko.md). |
| [`orca-plugin-refresh-resume`](skills/orca-plugin-refresh-resume/SKILL.md) | Previews and updates this plugin in idle Orca-managed Claude Code and Codex sessions, then resumes each session with its saved native ID. [Korean guide](skills/orca-plugin-refresh-resume/SKILL.ko.md). |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Reads the staged and unstaged changes, or the scope you name, plus recent commit history, then suggests five commit messages that match the repo's style. When you ask it to commit, it commits with the single best subject instead. [Korean guide](skills/suggest-commit/SKILL.ko.md). |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Writes or reviews technical design documents and RFCs without taking ownership of implementation planning. [Korean guide](skills/technical-design-writer/SKILL.ko.md). |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Runs a turn-limited debate between the current agent and an opposing Claude/Codex session to surface and resolve issues. [Korean guide](skills/tiki-taka/SKILL.ko.md). |

## Related

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) remains available as standalone
  source and is not included in the plugin skill list. [Korean guide](standalone-skills/omo-model-config/SKILL.ko.md).
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — plugin system whose model
  routing the standalone skill updates

## License

This repository is licensed under the Apache License 2.0. See [`LICENSE`](./LICENSE) for the full text.
