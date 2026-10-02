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
│   ├── datagrip_guard.py
│   ├── language_guard.py
│   ├── session_approval_guard.py
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
    ├── orca-plugin-refresh/
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

A `PreToolUse` hook, `scripts/agent_guard.py`, keeps built-in subagents out on both hosts. On Claude Code it denies an
omitted subagent type and every built-in type: `general-purpose`, `Explore`, `Plan`, `claude`, and forks. The
narrow-purpose built-ins `claude-code-guide` and `statusline-setup` pass, as do plugin agents and definitions from any
user, project, CLI, or managed source. On Codex it denies an omitted type, `default`, `explorer`, and every type
without a role file, including the built-in `worker` before the plugin role exists. Skills that ask for an independent
read-only worker use `scout`, and skills that write trial outputs run a separate `claude -p` or `codex exec` process.

### Response language

A language guard, `scripts/language_guard.py`, checks that every reply and every progress update is written in the
response language. Claude Code takes the language from the `language` setting, read from the local project settings,
then the project settings, then the user settings; without one, nothing is enforced. Codex reads
`HEI5ENBUG_RESPONSE_LANGUAGE` and uses Korean when it is unset. Only languages with a distinctive script are
checked: Korean, Japanese, Chinese, Russian, Ukrainian, Greek, Arabic, Hebrew, Thai, and Hindi. For any other
language, such as English or French, the instruction alone applies.

The check ignores code, quotes, and URLs. A text passes when at least 30% of its letters are in the target script,
and very short text always passes. A `Stop` hook asks for a rewrite when a reply fails, at most 3 times per turn.
A `PostToolUse` hook adds a reminder after a progress update in another language. Put text the user asks for in
another language in a code block or block quote.

### DataGrip query guard

A `PreToolUse` hook and a `PermissionRequest` hook, both `scripts/datagrip_guard.py`, run before the DataGrip MCP tool
`execute_sql_query`. The guard reads the connection from `.idea/dataSources.xml` in the DataGrip project that
`projectPath` names. A connection whose name contains `승인` always asks for approval. PostgreSQL and SQL Server reads
run without approval, and PostgreSQL reads run inside a read-only transaction. Writes, queries the guard cannot
classify, unknown connections, and other database types always ask. The guard never denies a call. In Codex, trust the
hook in `/hooks`.

Optionally, install the `pglast` parser once:

```bash
uv venv --python 3.12 "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser"
uv pip install --python "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser/bin/python" pglast==8.4
```

Without it, PostgreSQL falls back to a stricter text check that may ask more often but still never lets a write run
without approval.

### Session approvals

On Claude Code only, a session approval guard, `scripts/session_approval_guard.py`, lets you approve certain
outward-facing writes once per session. It covers creating git tags; pushing tags to a configured remote;
`gh release create` and `gh release edit` with only the tag and the flags `--title`, `--notes`, `--target`,
`--generate-notes`, `--notes-from-tag`, `--latest`, `--draft`, `--prerelease`, `--verify-tag`; and MCP tools whose
names contain a write verb. After you approve one, the same kind of action runs without a prompt for the rest of that
session. Each tool or command kind is approved separately.

Destructive actions always ask: force pushes, deleting remote branches or tags, deleting a tag, `gh release delete`,
`gh repo delete`, and MCP tools that delete, trash, or remove. `gh release upload` always asks too, because it can
publish any local file. So does a tag push to a URL, an unlisted remote, or `--repo`, or one that mixes a branch into
a `--tags` push, and so does a `gh release create` or `gh release edit` with attached assets, `--notes-file`, or any
other flag. A compound command that contains anything the guard cannot verify always asks. Subagents never inherit
approvals. Approvals expire with the session and are stored in the plugin data directory. Ordinary pushes and all
other commands keep the normal permission flow.

Do not add `permissions.ask` rules for these actions, because an ask rule prompts every time even after a session
approval.

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
| Session starts or resumes | `SessionStart` supplies the installed instruction files. In an Orca terminal it also writes a marker with the plugin directory and an instructions digest. |
| Session clears or compacts | `SessionStart` supplies them again. |
| A subagent starts | `SubagentStart` supplies the same host's instructions. |
| A tool call finishes | `PostToolUse` adds a language reminder after a progress update in another language. |
| A reply ends | `Stop` asks for a rewrite when the reply is not in the response language. |
| A DataGrip query is about to run | `PreToolUse` and `PermissionRequest` run the DataGrip query guard before `execute_sql_query`. |
| A Bash or MCP tool call runs | On Claude Code, `PreToolUse` and `PostToolUse` run the session approval guard for Bash and MCP tools. |
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
in Codex, trusted. A hook that an update adds, such as the agent guard, the language guard, or the DataGrip query
guard, stays skipped in Codex until you trust it in `/hooks`. The session approval guard runs only on Claude Code,
so this trust step does not apply to it. Restart Claude Code or start a new Codex session after updating.
The hook does not bypass host trust settings or change an already running session to a new plugin version.
The `orca-plugin-refresh` skill uses those markers to apply an update to running Orca sessions without restarting them.

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
The newest `v<version>` tag reachable from `HEAD` is the release baseline. The first change after it sets the next
version in these files within the same commit. A version that appears only in these files is the planned next
version, even when it is already on `main`, so fold every later unreleased change into it instead of bumping again.
A release adds no commit: after the development checks below pass on `HEAD`, tag `HEAD` `v<version>` and push the
tag.

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

### Apply an update to running Orca sessions

Ask for `orca-plugin-refresh` to update this plugin in both hosts and apply it to every idle Orca-managed session
without restarting it. The skill runs only when you ask for it.

| Part | Claude Code | Codex |
|---|---|---|
| Skills, agents, and hooks | The skill sends `/reload-plugins` | The next turn picks up the new install automatically |
| Session instructions | The skill sends `/compact` when they are stale | The skill sends `/compact` when they are stale; the session loads them on its next turn |

The skill decides that instructions are stale from the session-start marker: it is missing, holds another digest,
or points at a plugin directory that was replaced or removed. It sends a command only to an idle terminal whose
input line is empty and confirms every result from the session transcript or the screen. For a Claude Code session,
the skill may type and delete one character to tell a grey prompt suggestion from typed text; it never sends to a
session with typed text. A busy session is retried until the time budget ends and is then
reported as skipped. The session that runs the skill is handled last by a detached helper after its turn ends.
Sessions outside Orca need `/reload-plugins` or `/compact` by hand. The skill supports macOS and Linux user-scope
installations from the `hei5enbug` marketplace.

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
| [`orca-plugin-refresh`](skills/orca-plugin-refresh/SKILL.md) | Updates this plugin in both hosts and applies it to idle Orca-managed Claude Code and Codex sessions without restarting them. [Korean guide](skills/orca-plugin-refresh/SKILL.ko.md). |
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
