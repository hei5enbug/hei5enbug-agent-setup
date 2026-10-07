# hei5enbug-agent-setup

A personal harness for my work environment: skills, session instructions, and guard hooks for Claude Code and Codex.

## Overview

Each plugin skill lives in its own folder under `skills/` and is self-contained. The same `SKILL.md` works
unmodified on every supported host.

## Supported Hosts

- Claude Code
- Codex

OpenCode configuration remains source material only; this plugin does not install, maintain, or execute it.

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
├── hooks/mod/
├── config/claude-mod.json
├── instructions/
│   ├── claude-agents.md
│   ├── codex-agents.md
│   ├── confluence.md
│   ├── documentation.md
│   ├── implementation-execution.md
│   ├── implementation-planning.md
│   ├── independent-model-validation.md
│   ├── model-routing.md
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
│   ├── plugin_toggles.py
│   └── session_context.py
├── tests/
├── LICENSE
├── pyproject.toml
├── agents/
│   ├── ko/
│   │   ├── designer.ko.md
│   │   ├── researcher.ko.md
│   │   ├── scout.ko.md
│   │   └── worker.ko.md
│   ├── designer.md
│   ├── researcher.md
│   ├── scout.md
│   └── worker.md
├── standalone-agents/
│   ├── codex-designer.toml
│   ├── codex-researcher.toml
│   ├── codex-scout.toml
│   └── codex-worker.toml
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

The `agents/` directory ships with the Claude Code plugin, so installing the bundle adds the
`hei5enbug-agent-setup:scout`, `hei5enbug-agent-setup:worker`, `hei5enbug-agent-setup:researcher`, and
`hei5enbug-agent-setup:designer` subagents. No manual copy is needed. The manifest lists only these four English
definitions, so the Korean mirrors in `agents/ko/` are not registered as subagents.

Codex discovers subagents only in `~/.codex/agents/` and `.codex/agents/`, so a plugin cannot register one.
Instead, the session hook copies `standalone-agents/codex-scout.toml`, `codex-worker.toml`,
`codex-researcher.toml`, and `codex-designer.toml` to the matching `~/.codex/agents/<role>.toml` when each file is
absent. They define `scout`, `worker`, `researcher`, and `designer` agents, named as on Claude Code, with fixed
reasoning effort and sandbox. The plugin `worker` replaces the
built-in Codex `worker`, and `scout` leaves the built-in `explorer` untouched. A file you edited is never
overwritten, and the agents become available in the next Codex session. Because an edited copy never changes,
the files set no model; the Codex instructions pass the pinned model on every spawn instead. The hook also
removes an `explorer.toml` and replaces a `worker.toml` that an earlier version wrote, but only while the file is
byte-identical to that version's bundled file, so a copy you edited stays. When the plugin is disabled, the installed
`worker` role runs as an ordinary implementation worker instead of refusing to edit.

Built-in subagents stay out on both hosts. On Claude Code the mod hides the built-in `general-purpose`, `Explore`,
`Plan`, and `claude` agents from the agent list (`agent.offer`) and denies them and every fork (`agent.spawn`). The
narrow-purpose built-ins `claude-code-guide` and `statusline-setup` pass, as do plugin agents and definitions from any
user, project, CLI, or managed source. On Codex the `PreToolUse` hook `scripts/agent_guard.py` keeps its existing
behavior: it denies an omitted type, `default`, `explorer`, and every type without a role file, including the
built-in `worker` before the plugin role exists. Skills that ask for an independent
read-only worker use a role whose verified model, effort, and tools match the skill contract. Bounded local
evidence uses `scout`; public evidence can use `researcher`. Skills that write trial outputs use a verified
evaluation runner when required. See the conditional [model routing contract](instructions/model-routing.md).

### Claude Code mod

On Claude Code, `config/claude-mod.json` loads the mod `hooks/mod/register.js`, which holds the Claude-only guards:
the built-in subagent block, role pinning, session approvals, and the GPT refusal. It was tested with Claude Code
2.1.292. When the mod does not load, such as on an older Claude Code, with `disableAllHooks`, or under a managed
policy, these guards are absent and the host's normal permission flow applies.

Role pinning pins each plugin role's model and effort on every request: `scout` and `researcher` use
`claude-sonnet-5-5` with `medium`, `worker` uses `claude-sonnet-5-5` with `high`, and `designer` uses
`claude-opus-5-5` with `xhigh`. A subagent that answers on another model is stopped: its later requests end with a
refusal, its tool calls are denied, and its result is replaced with a warning. The session context then carries the
line `hei5enbug-agent-setup mod: role pinning active`, which lets the main session send assignments directly.

### GPT in Claude Code

The mod refuses requests to the pinned GPT models before any inference. This refusal is always on and has no toggle.
Claude Code's mod API does not expose tool input schemas, so this route cannot work yet.
The helper, its tests, and the design records are preserved on the `gpt-route` branch.

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

On Claude Code only, the mod lets you approve certain outward-facing writes once per session. For each Bash and MCP tool
call, its `tool.check` hook classifies the action and asks the first time a covered kind runs in the session. When the
call succeeds, its `tool.call` hook records the approved kind in the mod store (`$.store`) under the session ID, so
later actions of the same kind in that session run without a prompt. It covers creating git tags; pushing tags to a
configured remote; `gh release create` and `gh release edit` with only the tag and the flags `--title`, `--notes`,
`--target`, `--generate-notes`, `--notes-from-tag`, `--latest`, `--draft`, `--prerelease`, `--verify-tag`; and MCP tools
whose names contain a write verb. MCP tools whose names start with a read verb, such as get, list, search, read, fetch,
query, or download, are never covered and keep the normal permission flow, as does the DataGrip query tool, which the
DataGrip query guard handles. Each tool or command kind is approved separately.

Destructive actions always ask: force pushes, deleting remote branches or tags, deleting a tag, `gh release delete`,
`gh repo delete`, and MCP tools that delete, trash, or remove, even when the name starts with a read verb.
`gh release upload` always asks too, because it can publish any local file. So does a tag push to a URL, an unlisted
remote, or `--repo`, or one that mixes a branch into a `--tags` push, and so does a `gh release create` or
`gh release edit` with attached assets, `--notes-file`, or any other flag. A compound command that contains anything
the mod cannot verify always asks. A plain `echo` with literal text after a covered command, such as
`git tag v1 && echo done`, does not stop the approval from applying; an `echo` with a variable, command substitution,
glob, redirect, or pipe still asks. Subagents never inherit approvals. Approvals belong to one session, and the mod
drops stored entries older than 7 days. Ordinary pushes and all other commands keep the normal permission flow.

Do not add `permissions.ask` rules for these actions, because an ask rule prompts every time even after a session
approval.

## Feature toggles

Seven features can be turned off. All default to on. On Claude Code, set the plugin option in `/config`, or with
`claude plugin configure`. On Codex, set the environment variable before starting the session. A value of `false`,
`0`, `off`, or `no`, in any letter case, turns a feature off.

| Feature | Claude Code `/config` key | Codex environment variable |
|---|---|---|
| Block built-in subagents | `agent_guard` | `HEI5ENBUG_AGENT_GUARD` |
| One-time session approval | `session_approval` | Not applicable |
| Pin role models | `role_pinning` | Not applicable |
| Response language guard | `language_guard` | `HEI5ENBUG_LANGUAGE_GUARD` |
| DataGrip query guard | `datagrip_guard` | `HEI5ENBUG_DATAGRIP_GUARD` |
| Subagent permission block in `~/.codex/AGENTS.md` | Not applicable | `HEI5ENBUG_SUBAGENT_POLICY` |
| Question tool flag | Not applicable | `HEI5ENBUG_CODEX_ASK_TOOL` |

The GPT refusal is always on. The session instructions and operating rules have no toggle; disable the plugin itself
to turn them off.

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
| A Bash or MCP tool call runs | On Claude Code, the mod's `tool.check` and `tool.call` hooks run the session approval for Bash and MCP tools. |
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
in Codex, trusted. A hook that an update adds or changes, such as the agent guard, the language guard, or the DataGrip
query guard, stays skipped in Codex until you trust it in `/hooks`. `hooks/hooks.json` changed in this release, so
trust its hooks again after updating. The Claude Code mod is not a Codex hook, so this trust step does not apply to
it. Restart Claude Code or start a new Codex session after updating.
The hook does not bypass host trust settings or change an already running session to a new plugin version.
The `orca-plugin-refresh` skill uses those markers to apply an update to running Orca sessions without restarting them.

A missing or empty session file, an invalid local reference, or context larger than 9,000 UTF-8 bytes produces an error on
stderr and no partial context. Session-start hook errors do not reliably block the host; resolve any
reported loading error before relying on automatic instructions. Keep the session files short and move
details into conditional references. Windows execution and live model adherence are not covered by the tests.

See the official [Codex hooks](https://learn.chatgpt.com/docs/hooks) and
[Claude Code hooks](https://code.claude.com/docs/en/hooks) contracts for lifecycle and trust behavior.

## Situation-based delegation

The main session chooses direct work or delegation using the rules in
[instructions/session/common.md](instructions/session/common.md). Small edits and known-path lookups stay
in the main session. Bounded investigations, bulky evidence gathering, and substantial independent
implementation can use workers when the expected benefit exceeds coordination overhead. Closely dependent
work keeps one owner. This policy does not guarantee a lower bill on every task.

The main session retains requirements, design, task boundaries, acceptance, and the final report.
[instructions/implementation-execution.md](instructions/implementation-execution.md) defines ownership,
conflict-free scheduling, checks, and recovery. Direct work uses the main session's current model and effort.
A delegated task carries only its scope, relevant context, allowed/protected paths, prerequisites,
acceptance checks, and the host's pinned settings. Workers cannot start nested agents.

UI code, visual design, and diagram work goes to the host's designer route instead. A text or style-value edit that
keeps the layout and component structure may still go to the implementation worker, and design documents and RFCs
stay in the main session.

| Host | Implementation agent | Model and effort |
|---|---|---|
| Codex | Plugin `worker` role, verified from its rollout record | `gpt-6-luna`, `xhigh` |
| Claude Code | `hei5enbug-agent-setup:worker`, verified from its subagent record | `claude-sonnet-5-5`, `high` |
| Codex, designer | `claude -p` with the pinned model; when Claude is unavailable, the plugin `designer` role | `claude-opus-5-5`, `xhigh`; fallback `gpt-6-astra`, `xhigh` |
| Claude Code, designer | `hei5enbug-agent-setup:designer`, verified from its subagent record | `claude-opus-5-5`, `xhigh` |

Independent ready tasks may run together within the host limit and the shared execution ceiling. If a role,
model, effort, quota, permission to delegate, or settings evidence is unavailable, the main session reports
that limitation and continues authorized work after stopping any affected worker. It preserves partial work,
user settings, permissions, and acceptance checks. It never silently substitutes a worker model.

After a substantial change and its checks are ready, the main session recommends one optional cross-family
review under [independent model validation](instructions/independent-model-validation.md). Both reviewer
mappings use `xhigh`. Approval is required for the particular result, and a decline is not asked again.
An unavailable reviewer does not block the remaining work. Routine author inspection and tests always remain.

Codex requires a direct user request or applicable `AGENTS.md` or skill instructions to authorize subagents;
hook instructions alone cannot grant it. Without authorization, the main session continues directly.

### Codex automatic settings

On Codex, the session hook manages two settings, and both take effect from the next session. It keeps this marked
block at the end of `~/.codex/AGENTS.md`, creating the file when it is missing:

```text
<!-- hei5enbug:subagents -->
When hei5enbug-agent-setup is active, use subagents according to its situation-based delegation rules.
<!-- /hei5enbug:subagents -->
```

It also enables the `default_mode_request_user_input` feature when `codex features list` shows it off, so
`request_user_input` works in Default mode. Setting `HEI5ENBUG_SUBAGENT_POLICY=off` removes only the marked block and
never edits anything outside it. Setting `HEI5ENBUG_CODEX_ASK_TOOL=off` disables the feature again, but only when the
plugin enabled it; a feature you enabled yourself stays on. A failed step is retried at the next session start and
never stops the session instructions from loading. Hosts, hook trust, and available tools still govern execution.
See the official [Codex subagent contract](https://learn.chatgpt.com/docs/agent-configuration/subagents)
and the [evaluation conclusion](https://github.com/hei5enbug/hei5enbug-agent-setup/blob/gpt-route/docs/subagent-policy-decision.md).

## Work efficiency

[Work-efficiency rules](instructions/work-efficiency.md) load only before substantial implementation,
repeated model evaluation, plugin maintenance, or repeated-failure diagnosis. Required results and checks
define completion. Valid check evidence is reused until its relevant inputs change; optional research and
an unperformed optional review do not keep accepted work open.

Additional model comparisons start with at most 3 representative cases, 15 minutes for the whole batch,
and 6 top-level starts for paired trials across both hosts. Probes and retries share that budget, including
after resume. These limits do not cap ordinary implementation, unit tests, required builds, or the final
review. Expansion needs an unresolved question and an explicitly authorized larger budget.

Permanent failures require changed conditions before another attempt; transient failures allow at most one
unchanged retry. Browser writes have one owner for the actual shared control resource under
[service access rules](instructions/services.md#browser-ownership). These instructions guide agent behavior;
they do not establish universal adherence or measured time/token savings.

## Plugin updates

Both plugin manifests, `pyproject.toml`, and `uv.lock` must use the same semantic version.
The newest `v<version>` tag reachable from `HEAD` is the release baseline. The first change after it sets the next
version in these files within the same commit. A version that appears only in these files is the planned next
version, even when it is already on `main`, so fold every later unreleased change into it instead of bumping again.
A release adds no commit: after the development checks below pass on `HEAD`, tag `HEAD` `v<version>` and push the
tag.

After the release is available, end affected coding-agent sessions and run the update from a normal terminal.
Replacing a loaded plugin directory can leave a running session with missing hook paths.

Update Codex:

```bash
codex plugin marketplace upgrade hei5enbug
codex plugin add hei5enbug-agent-setup@hei5enbug
```

Update Claude Code:

```bash
claude plugin marketplace update hei5enbug
claude plugin update hei5enbug-agent-setup@hei5enbug
```

Start a new Codex thread or restart Claude Code after updating so the host loads the new skills and instructions.

### Apply an update to running Orca sessions

Ask for `orca-plugin-refresh` to apply an already-installed version to idle Orca-managed sessions without
restarting them. The skill runs only when you ask for it. `apply-installed --json` validates the installed
roots and creates a run ID for `apply --run-id <run_id> --json`, without marketplace or install commands.

Cache-replacing updates are a separate offline step. The default `update --json` defers; `update --offline --json`
is for a normal terminal after affected coding-agent sessions have ended. Active host/plugin environment or
connected coding-agent terminals contradict that attestation and still block the update. Unreadable, truncated,
or unsupported available inventory also defers. The result preserves each host's status and provides its current
root and an offline recovery command; deferred hosts remain untouched. Orca inventory cannot prove that
non-Orca sessions have ended. Manual updates and another process deleting a loaded directory remain outside
this protection. See the [refresh workflow](skills/orca-plugin-refresh/SKILL.md) for commands and limits.

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

The bundled scripts need Python 3.12 or later with PyYAML. The Node tests need Node.js. The mod tests and the plugin
validation need the Claude Code CLI, version 2.1.292 in CI. Run the checks that `.github/workflows/validate.yml`
runs on macOS and Linux, plus the plugin validation:

```bash
python3 -m pip install -e ".[dev]"
for skill in skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$skill"; done
python3 -m pytest
node --test skills/document-to-confluence/tests/test_render_diagrams.mjs
claude plugin validate .
claude plugin test .
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
| [`orca-plugin-refresh`](skills/orca-plugin-refresh/SKILL.md) | Updates this plugin safely offline and applies an installed version to idle Orca-managed Claude Code and Codex sessions without restarting them. [Korean guide](skills/orca-plugin-refresh/SKILL.ko.md). |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Reads the staged and unstaged changes, or the scope you name, plus recent commit history, then suggests five commit messages that match the repo's style. When you ask it to commit, it commits with the single best subject instead. [Korean guide](skills/suggest-commit/SKILL.ko.md). |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Writes or reviews technical design documents and RFCs without taking ownership of implementation planning. [Korean guide](skills/technical-design-writer/SKILL.ko.md). |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Runs a turn-limited debate between the current agent and an opposing Claude/Codex session to surface and resolve issues. [Korean guide](skills/tiki-taka/SKILL.ko.md). |

## Related

- `omo-model-config` was removed; its last version is in the [`v1.3.0` tag](https://github.com/hei5enbug/hei5enbug-agent-setup/tree/v1.3.0/standalone-skills/omo-model-config).

## License

This repository is licensed under the Apache License 2.0. See [`LICENSE`](./LICENSE) for the full text.
