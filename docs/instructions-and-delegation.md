# Instructions and delegation

This page explains how instructions load and how work is assigned, verified, and kept within scope.

## Automatic instructions

On macOS and Linux, the plugin hooks combine `instructions/session/core.md` and `instructions/session/common.md` with
either `instructions/session/codex.md` or `instructions/session/claude-code.md` for the current host. `core.md` holds
the rules that apply to every agent. Python 3.12 or later must be available as `python3` on the host's `PATH`, or as the
interpreter that the hook Python interpreter option names (see [Feature options](configuration.md#feature-options)). The
hook uses only the Python standard library. Root `AGENTS.md` governs development of this repository only; the hook never
reads it.

`hooks/hooks.json` holds the hooks that run on both hosts. Claude Code discovers it automatically and merges the `hooks`
paths in `.claude-plugin/plugin.json`: the mod config, then `hooks/claude-hooks.json`, which holds the Claude Code-only
prompt notice. Codex loads the files `.codex-plugin/plugin.json` lists, `hooks/hooks.json` and `hooks/codex-hooks.json`,
which holds the Codex-only agent guard and DataGrip permission hook. Codex sets `PLUGIN_ROOT` to the installed plugin
directory; the loader uses that value to select Codex rules. Both hosts provide `CLAUDE_PLUGIN_ROOT` for locating the
script. No user or project instruction file is copied, linked, or overwritten.

| When | Behavior |
|---|---|
| Session starts or resumes | `SessionStart` supplies the installed instruction files and adds one-line notices from `host_settings.py check` when needed: up to three problems, then a count of the rest. Examples are Claude `defaultMode` `dontAsk`, Claude `permissions.ask` rules that match Bash or MCP tools, or an existing Codex config without `[features] plugin_hooks = true` (checked on both hosts). On Codex with the `host_settings` option on `apply`, it first runs `apply`, which may change allowlisted Codex settings (see [Host settings](configuration.md#host-settings)) and adds one notice naming what it changed. Notices must fit the context limit. In an Orca terminal it also writes a marker with the plugin directory and an instructions digest. |
| Session clears or compacts | `SessionStart` supplies them again. |
| A subagent starts | `SubagentStart` supplies a short role context: `core.md`, plus the "Assigned workers" rules for implementation agents. |
| A role runner child session starts | It receives `core.md` only; the runner puts the role rules before the assignment. |
| A tool call finishes | `PostToolUse` adds a language reminder after a progress update in another language. |
| A reply ends | `Stop` asks for a rewrite when the reply is not in the response language. |
| A user submits a prompt on Claude Code | `UserPromptSubmit` compares the main session's "Implementation worker route", "Worker agent model", and "Review model" lines with the ones recorded at session start, and supplies the new lines once when a `/config` change altered them. |
| A DataGrip query is about to run | `PreToolUse` runs the DataGrip query guard before `execute_sql_query` on both hosts; `PermissionRequest` runs it on Codex only. |
| A Bash, MCP, or covered file tool call runs | `PreToolUse` runs the approval guard, including file-state protection and sensitive reads. `PermissionRequest` absorbs host prompts on Claude Code and skips Codex's native window once approved; `PostToolUse` and `PostToolUseFailure` record approvals. `UserPromptSubmit` resets the approval request counts, records user approval, and supplies immediate-retry context on both hosts. |
| A matching task begins | The agent reads the required reference under `instructions/`. |
| A plugin update is installed | A new session reads that installed version. A repository push alone changes nothing locally. |

Core rules remain in session context across requests. Service access, protected-value access, agent use, documentation,
implementation execution, and requested planning or design details load only before the matching action, even if it
arises later in a request. The session context distinguishes implementation plans from design documents and keeps their
trigger boundary. `instructions/implementation-planning.md` owns the six-stage implementation plan workflow and
template. `technical-design-writer` owns design-document behavior, and `instructions/independent-model-validation.md`
owns their shared one-pass cross-family validation contract. The context header defines `$I` as the installed plugin's
`instructions` folder, and the loader writes each session file's conditional link to a file there as `$I/<path>`, so the
context does not grow with the install path. A link to another file inside the plugin keeps an absolute path. The loader
does not read conditional reference bodies at startup.

Codex requires review and trust of the current plugin hook definition before running it. Disabled hooks or enterprise
policies that prohibit plugin hooks prevent automatic loading. After installation or update, use the host's hook
controls to check that these hooks are enabled and, in Codex, trusted. A hook that an update adds or changes, such as
the agent guard, the language guard, or the DataGrip query guard, stays skipped in Codex until you trust it in `/hooks`.
Codex trust also covers the plugin's files, so every plugin update leaves all plugin hooks `modified`. The plugin
re-trusts only its own hooks, and only when the installed copy is a clean git checkout of the official repository, apart
from Codex's install marker, with no tracked file marked skip-worktree or assume-unchanged, and its HEAD is a commit the
official repository advertises right now for `main` or a `v*` tag (`git ls-remote`), or an ancestor of that `main` tip
fetched into a scratch repository. Local refs and tags count for nothing, and without network access it does not trust.
`orca-plugin-refresh` does this right after a Codex install, and the role runner does it when its readiness check or
preflight finds the guard untrusted. It records each hook's current hash through the `codex app-server` method
`config/value/write` and confirms the result with `hooks/list`. Otherwise, including for a locally edited copy and for
other plugins, trust the hooks again in `/hooks` after each update. The Claude Code mod is not a Codex hook, so this
trust step does not apply to it. Restart Claude Code or start a new Codex session after updating. The hook does not
bypass host trust settings or change an already running session to a new plugin version. The `orca-plugin-refresh` skill
uses those markers to apply an update to running Orca sessions without restarting them.

A missing or empty session file, an invalid local reference, main context larger than 9,600 UTF-8 bytes, or a role
context larger than 4,000 UTF-8 bytes produces an error on stderr and no partial context. The main limit stays under the
10,000 characters Claude Code passes from one hook field, and the session-start hook sets `additionalContextLimit` to
`0` so that Codex passes the whole context instead of a file path and a preview. Session-start hook errors do not
reliably block the host; resolve any reported loading error before relying on automatic instructions. Keep the session
files short and move details into conditional references. Windows execution and live model adherence are not covered by
the tests.

See the official [Codex hooks](https://learn.chatgpt.com/docs/hooks) and [Claude Code
hooks](https://code.claude.com/docs/en/hooks) contracts for lifecycle and trust behavior.

## Situation-based delegation

The main session chooses direct work or delegation using the rules in
[instructions/session/common.md](../instructions/session/common.md). Known-path lookups, implementation that changes at
most two files, and integration fixes stay in the main session. Bounded investigations, bulky evidence gathering, and
larger independent implementation use workers when the expected benefit exceeds coordination overhead. Closely dependent
work keeps one owner. This policy does not guarantee a lower bill on every task.

The main session retains requirements, design, task boundaries, acceptance, and the final report.
[instructions/implementation-execution.md](../instructions/implementation-execution.md) defines task preparation,
assignment fields, and acceptance for all implementation, including main-owned work.
[instructions/implementation-delegation.md](../instructions/implementation-delegation.md) defines worker ownership,
conflict-free scheduling, recovery, and assigned-worker rules; read it before delegating implementation. Direct work
uses the main session's current model and effort. A delegated task carries only its scope, relevant context,
allowed/protected paths, prerequisites, acceptance checks, and the host's pinned settings. Workers cannot start nested
agents.

UI code, visual design, and diagram work goes to the host's designer route instead, except the kinds the host session
file assigns to the main session. On Claude Code, the main session draws ASCII and Mermaid diagrams in documents, edits
existing SVG diagrams, and makes new SVG or PNG flowcharts of up to seven nodes. A text or style-value edit that keeps
the layout and component structure may still go to the implementation worker, and design documents and RFCs stay in the
main session.

`config/model-registry.json` is the single source of model pins and capability pins; the scripts and the mod read it.
Each capability's per-host entries are listed in the [capability pins](../instructions/model-routing.md#capability-pins)
section of the model routing contract. The five capabilities are `investigation`, `implementation`, `design`,
`language`, and `review`. Every fallback is the other model family; a fallback that needs the other host's model runs
through the role runner, and one the current host can run in-host uses the named agent.

| Host | Implementation agent | Model and effort |
|---|---|---|
| Codex | `role_runner.py implementation --host codex`, which runs Claude; fallback plugin `worker` role, verified from its rollout record | `claude-sonnet-5-5`, `high` (up to `xhigh`); fallback `codex_worker_model` and `codex_worker_effort` (default `gpt-5.6-luna`, `high`) |
| Claude Code | With `implementation_worker` `auto` (default), the main session picks per assignment: `hei5enbug-agent-setup:worker` for easy work and `hei5enbug-agent-setup:sonnet-worker` for normal or hard work; `role_runner.py implementation --fallback` when a Claude route fails or stops on a usage limit. A fixed setting forces `sonnet`, `sol`, `codex` (`role_runner.py worker`), or `haiku` (fallback `role_runner.py agent --name hei5enbug-agent-setup:worker --fallback`) | `worker_model` and `worker_effort` (default `claude-haiku-5-5`, `high`) (easy); `claude-sonnet-5-5`, `high` (normal or hard); `gpt-6.1-sol`, `high` (up to `xhigh`) (fallback); `gpt-5.6-luna`, `high` (up to `xhigh`) (`codex`) |
| Codex, designer | Plugin `designer` role with the pinned model, verified from its rollout record; fallback `role_runner.py agent --name designer --fallback` | `gpt-6-astra`, `high` (up to `xhigh`); fallback `claude-opus-5-5`, `high` (up to `xhigh`) |
| Claude Code, designer | `hei5enbug-agent-setup:designer`, verified from its subagent record or the mod's role pinning; fallback `role_runner.py design` | `claude-opus-5-5`, `xhigh`; fallback `gpt-6-astra`, `high` (up to `xhigh`) |
| Codex, local scout | Plugin `scout` role, verified from its rollout record | `gpt-5.6-luna`, `high` (up to `xhigh`) |
| Claude Code, local scout | `role_runner.py scout`; fallback `hei5enbug-agent-setup:scout` | `gpt-5.6-luna`, `high` (up to `xhigh`); fallback `claude-sonnet-5-5`, `medium` |
| Codex, public researcher | `role_runner.py researcher`, which uses web search and no shell network, verified from its session record | `gpt-5.6-luna`, `high` (up to `xhigh`) |
| Claude Code, public researcher | `role_runner.py researcher`, which uses web search and no shell network; fallback `hei5enbug-agent-setup:scout`, which has web search and fetch tools | `gpt-5.6-luna`, `high` (up to `xhigh`); fallback `claude-sonnet-5-5`, `medium` |
| Codex, skill review | `role_runner.py review`; fallback plugin `reviewer`, verified from its rollout record | `claude-opus-5-5`, `high` (up to `xhigh`); fallback `gpt-6.1-sol`, `high` (up to `xhigh`) |
| Claude Code, skill review | `role_runner.py reviewer` with the `review_model` setting; fallback `hei5enbug-agent-setup:reviewer` | `review_model` (default `gpt-6-astra`), `high` (up to `xhigh`); fallback `claude-opus-5-5`, `high` |
| Skill Builder trial execution and other non-review participants | Host's upper model from the Skill Builder adapter | Codex: `gpt-6.1-sol`, `xhigh`; Claude Code: `claude-opus-5-5`, `high` |

On Claude Code, `scripts/role_runner.py` runs the scout, researcher, reviewer, and Codex worker roles, and it runs a
registry capability, such as a Claude model capability, when `--instructions <file>` supplies its role definition. Its
agent mode runs a plugin agent's cross-family fallback, named by `--name <name>`. The main session writes the assignment
to a file and runs `python3 <plugin>/scripts/role_runner.py <role-or-capability>` or `python3
<plugin>/scripts/role_runner.py
agent --name <name> --fallback`, both with `--assignment <file> --result <file>`, from the session folder. It adds
`--model <id>` for `reviewer`, `--add-dir <dir>` for `worker`, a writing capability, or a `write` agent, `--mcp` for a
capability or agent that needs MCP tools or network, `--host claude|codex` to pick a capability's host entry,
`--fallback` for its fallback entry, and `--resume <session_id>` to continue a run from the `evidence.session` in its
status line. `--effort <level>` raises a run within its entry's range, whose lower bound is the default.
`--user-requested` marks a model or effort the user named for that work: with it, `--model <id>` is allowed for every
role, capability, and agent mode, a capability entry that is not `via: runner` runs through the runner on its own model,
and `--effort <level>` may be any level the model's effort rule allows; a model the runner cannot run or an effort the
model does not allow exits 2 with no fallback run, and the status line gains `"user_requested": true`. Repeating
`--assignment` and `--result` runs up to six read-only assignments of one target in parallel, with one status line each,
and the runner exits with the highest of their exit codes. A read-only child runs without the host's skill catalog:
Codex gets `-c skills.max_context_tokens=1`, and Claude gets `--disable-slash-commands`. The runner puts the role rules
before the assignment, runs the role on its pinned model, effort, and permissions (`codex exec`, or `claude -p` for a
Claude model), checks the host rollout or transcript record, and prints a final JSON status line. Without `--mcp`, a
Codex child gets `-c mcp_servers.<name>.enabled=false` for every server `codex mcp list --json` names, and a Claude
child keeps `--strict-mcp-config`. A Claude child that may edit also receives `Bash` in `--tools` and `--allowedTools`;
the guard denies writes the main session has not approved and every irreversible action. Each child receives
`HEI5ENBUG_PARENT_SESSION` so it can use the main session's approvals. Before a read-only Codex run, the runner asks
`codex app-server` for the folder's hooks (`hooks/list`). It requires an approval guard `PreToolUse` hook that is
enabled, synchronous, trusted or managed, and matches `Bash`; otherwise it exits 4 without a model call. After the run,
it requires `heartbeats/codex-<thread_id>.PreToolUse` whenever the rollout records a tool call. A Codex run that can
write first sends “Run the shell command `true` exactly once, then reply with OK only.” and requires that heartbeat
before it sends the assignment, so the guard has checked a tool call before any write can run. A plain,
`UserPromptSubmit`, or `SessionStart` heartbeat satisfies neither check. Codex trust also covers the plugin's files:
with Codex CLI 0.164.0, an edit to any plugin file, even `README.md`, marked every plugin hook `modified`, so after each
plugin update Codex skips the hooks. The runner then re-trusts this plugin's hooks from a verified official copy, as
described above, and checks again or preflights once more; when that is not allowed or fails, it exits 4 with the reason
in `auto_trust` until you trust them again in `/hooks`. Claude children require
`heartbeats/claude-<session_id>.UserPromptSubmit` or the existing plain heartbeat, since Claude does not gate plugin
hooks by trust. A missing required heartbeat exits 4. Exit code 0 means the result is verified, 2 a usage error to fix,
3 that the role could not run, and 4 that the required hook evidence was missing or the recorded model, effort, or
sandbox did not match, so the result is discarded. On 3 or 4 the main session uses the role's plugin agent fallback.
Independent validation has no fallback: the main session reports that it was not performed. A capability entry whose
`via` is `agent` is not run by the runner, which exits 2, so the main session uses the agent route for it.

Independent ready tasks may run together within the host limit and the shared execution ceiling. If a role, model,
effort, quota, permission to delegate, or settings evidence is unavailable, the main session reports that limitation and
continues authorized work after stopping any affected worker. It preserves partial work, user settings, permissions, and
acceptance checks. It never silently substitutes a worker model.

In its final stage, when no other work remains for the request, the main session runs one independent review of the
combined result under [independent model validation](../instructions/independent-model-validation.md), automatically and
without a question. A Claude-authored result goes to `gpt-6.1-sol` or `gpt-6-astra`, and a GPT-authored result goes to
`claude-opus-5-5` or `claude-fable-5-2`. The main session picks the lighter model at `high` for one bounded component,
and the stronger model or `xhigh` for several components, a public contract, security, concurrency, or a hook or guard.
Any earlier review, such as one of a single worker's change, needs the user's approval for that deliverable, and a
decline is not asked again. An assigned worker and a skill run inside a larger request never run their own final review.
An unavailable reviewer, or a role runner exit code 3 or 4, means independent validation was not performed; no other
model substitutes for it. Routine author inspection and tests always remain.

Codex requires a direct user request or applicable `AGENTS.md` or skill instructions to authorize subagents; hook
instructions alone cannot grant it. Without authorization, the main session continues directly.

## Work efficiency

[Work-efficiency rules](../instructions/work-efficiency.md) load only before substantial implementation. [Model
evaluation rules](../instructions/model-evaluation.md) load only before repeated model evaluation, and [failure and
maintenance rules](../instructions/failure-and-maintenance.md) load only before plugin maintenance or repeated-failure
diagnosis. Required results and checks define completion. Valid check evidence is reused until its relevant inputs
change; optional research and an unperformed optional review do not keep accepted work open. The work-efficiency rules
link the [resume-note rules](../instructions/pause-and-resume.md) for a pause, handoff, or expected compaction, and the
[cleanup offer](../instructions/session-cleanup.md) for files a finished session created. A session that does no
substantial implementation never loads them, so it gets neither the note nor the offer.

Additional model comparisons start with at most 3 representative cases, 15 minutes for the whole batch, and 6 top-level
starts for paired trials across both hosts. Probes and retries share that budget, including after resume. These limits
do not cap ordinary implementation, unit tests, required builds, or the final review. Expansion needs an unresolved
question and an explicitly authorized larger budget.

Permanent failures require changed conditions before another attempt; transient failures allow at most one unchanged
retry. Browser writes have one owner for the actual shared control resource under [service access
rules](../instructions/services.md#browser-ownership). These instructions guide agent behavior; they do not establish
universal adherence or measured time/token savings.

## Instruction language

English files are the canonical executable sources for plugin skills, references, agents, and session instructions.
Every human-readable English Markdown file has a meaning-equivalent `.ko.md` mirror under `docs/ko/`, following its
source path relative to the repository root. Each mirror links its source, is non-authoritative, and must never be
loaded during agent execution. Update, move, and delete each source and mirror together.

Code, schemas, test fixtures, generated artifacts, and non-English documents do not need Korean duplicates. Korean may
remain in an executable English file only as target-language data, such as trigger phrases, examples, required output
labels, or evaluation fixtures. Structural checks verify mirror coverage and execution-path isolation; semantic
equivalence still requires human or model review.

## Agent registration

The `agents/` directory ships with the Claude Code plugin, so installing the bundle adds the
`hei5enbug-agent-setup:scout`, `hei5enbug-agent-setup:worker`, `hei5enbug-agent-setup:sonnet-worker`,
`hei5enbug-agent-setup:designer`, and `hei5enbug-agent-setup:reviewer` subagents. No manual copy is needed. The manifest
lists only these five English definitions, so the Korean mirrors in `docs/ko/` are not registered.

Codex discovers subagents only in `~/.codex/agents/` and `.codex/agents/`, so a plugin cannot register one. Instead, the
session hook copies `standalone-agents/codex-scout.toml`, `codex-worker.toml`, `codex-designer.toml`, and
`codex-reviewer.toml` to matching `~/.codex/agents/<role>.toml` files when absent. They define four roles that also
exist on Claude Code, with a fixed sandbox; no role file sets a reasoning effort, so each spawn passes one. The Codex
`reviewer` role has no model key; the skill instructions pass its model and effort explicitly when it is the fallback.
The plugin `worker` replaces the built-in Codex `worker`, and `scout` leaves the built-in `explorer` untouched. A file
you edited is never overwritten, and the agents become available in the next Codex session. Because an edited copy never
changes, the files set no model; the Codex instructions pass the pinned model on every spawn instead, and the `worker`
role file sets no effort either, so the spawn passes the `codex_worker_model` and `codex_worker_effort` settings. A role
file you edited that pins another pair still wins, and the agent guard denies a mismatching spawn. The hook also removes
an `explorer.toml` and a `researcher.toml`, and replaces a `worker.toml`, `scout.toml`, `designer.toml`, or
`reviewer.toml`, that an earlier version wrote, but only while the file is byte-identical to that version's bundled
file, so a copy you edited stays. When the plugin is disabled, the installed `worker` role runs as an ordinary
implementation worker instead of refusing to edit.

Built-in subagents stay out on both hosts. On Claude Code the mod hides the built-in `general-purpose`, `Explore`,
`Plan`, and `claude` agents from the agent list (`agent.offer`) and denies them and every fork (`agent.spawn`). The
narrow-purpose built-ins `claude-code-guide` and `statusline-setup` pass, as do plugin agents and definitions from any
user, project, CLI, or managed source. On Codex the `PreToolUse` hook `scripts/agent_guard.py` keeps its existing
behavior: it denies an omitted type, `default`, `explorer`, and every type without a role file, including the built-in
`worker` before the plugin role exists. Skills that ask for an independent read-only worker use a role whose verified
model, effort, and tools match the skill contract. `scout` handles one bounded local investigation, including
local-evidence research tickets, and one bounded public research question with web search and fetch tools. A
skill-assigned review role uses the configured review model, then the `reviewer` fallback if that runner is unavailable.
The reviewer returns findings only; the main session reviews once and decides. Skills that write trial outputs use a
verified evaluation runner when required. See the conditional
[model routing contract](../instructions/model-routing.md).
