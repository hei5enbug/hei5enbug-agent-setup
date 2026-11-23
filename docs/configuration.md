# Configuration

This page explains plugin options, host-setting checks, and the settings the plugin may change.

## Host settings

Some host settings add approval prompts, stop the guard from running, or let built-in subagents run.
`scripts/host_settings.py` checks them and fixes a short allowlist on each host:

```bash
python3 <plugin root>/scripts/host_settings.py check [--host claude|codex] [--json]
python3 <plugin root>/scripts/host_settings.py apply [--host claude|codex] [--json]
```

Both commands also take `--claude-dir` and `--codex-home`. The host defaults to the one that runs the
command. `check` is a read and writes nothing. It reports one line per problem:

- Claude Code: `defaultMode` is `dontAsk`, and `permissions.ask` rules that match Bash or MCP tools, up to three named.
- Claude Code: the user settings file lacks one of `Agent(general-purpose)`, `Agent(Explore)`, `Agent(Plan)`, or
  `Agent(claude)` in `permissions.deny`, while `agent_guard` is on.
- Claude Code: the effective `cleanupPeriodDays` is below 3650 or unset, so Claude Code deletes session transcripts after
  that many days (30 when unset). The first of the managed, project local, project shared, and user settings files that
  sets an integer wins. Neither command writes that setting.
- `[features] hooks = false` (or the deprecated alias `codex_hooks = false`) in `~/.codex/config.toml`, on either host.
  Codex enables hooks by default, so a missing key is no problem; `plugin_hooks` was removed in Codex 0.170.0 and is
  neither checked nor written.
- Codex only: the plugin hooks are unconfirmed (the heartbeat hash differs), `config.toml` is not valid TOML,
  `rules/hei5enbug.rules` is missing, unreadable, outdated, or not plugin-owned, MCP servers lack the `prompt` approval
  mode, the mode step is skipped because `approval_guard` is off, or guard-covered MCP tools carry a per-tool `prompt`
  that would ask even for reads.
- Codex only: a `prompt` or `forbidden` rule in your own `rules/*.rules` files for a read prefix such as `kubectl get`,
  `helm list`, `az show`, or `git status`.

`apply` changes only this allowlist.

- Claude Code: the missing entries among `Agent(general-purpose)`, `Agent(Explore)`, `Agent(Plan)`, and `Agent(claude)`,
  appended after the existing `permissions.deny` entries of the user settings file (`~/.claude/settings.json`, or under
  `CLAUDE_CONFIG_DIR`), while `agent_guard` is on. A missing file or key is created. Nothing else in the file is removed,
  reordered, or rewritten, except that the JSON is saved with the file's own indent. `apply` writes nothing when the file
  is not a JSON object or `permissions.deny` is not a list, and says so. Claude Code itself enforces
  the rules, so they also hold in a session where the mod did not load, once a session with the plugin has written them.
  Claude Code documents that a call that omits `subagent_type` fails with `subagent_type is required` when the session
  has no `general-purpose` subagent to fall back on. It does not document whether a `permissions.deny` entry for
  `Agent(general-purpose)` counts as having none, so this page makes no claim about that.
- Codex: the plugin-owned `~/.codex/rules/hei5enbug.rules`, created or updated to the text of the plugin version. It holds the
  `prompt` rule for the wrapper script used by [Approval guard](approval-guard.md#approval-guard). `apply` only reports,
  and writes nothing, when that path is a symbolic link or an existing file lacks the plugin-owned header line.
- Codex: `default_tools_approval_mode = "prompt"` on every `[mcp_servers.<name>]` table, and `approval_mode = "prompt"` on each
  per-tool table that already sets another mode, while `approval_guard` is on. It edits only those lines and writes
  nothing when the result would not parse as intended.

Before it changes an existing file, `apply` copies it to `<file>.bak-hei5enbug-<YYYYMMDD>`, once per day. It prints one
line per change, and a second run changes nothing. It never edits your own rules files, other Claude Code settings, or
hook trust.

At session start, the `host_settings` option decides what the hook does. `apply` (the default) runs `apply` first, on
both hosts, and adds one notice naming what changed, then reports the remaining problems from `check`. `report` only reports.
Any other value means `apply`. Claude Code reads the option from `/config`; Codex reads `HEI5ENBUG_HOST_SETTINGS`.

## Feature options

Seven boolean features can be turned off, and each defaults to on. The implementation worker route, the worker models
and efforts, the review model, the host settings mode, the minimum free memory for starting an agent session
(`session_memory_min_mb`), the request caps (`request_run_cap` and `request_retry_cap`), the hook Python interpreter, and the plugins refreshed with this one (`refresh_plugins`)
are string options in Claude Code. Choose `auto`, `codex`, `haiku`, `sol`, or `sonnet` for the
route; an unset or unrecognized value uses `auto`, where the main session picks the worker per assignment. Choose
`apply` or `report` for the host settings mode; an unset or unrecognized value uses `apply`. It decides whether
`SessionStart` may change allowlisted host settings; see [Host settings](#host-settings). The review model runs skill
review roles at `high`, or at `xhigh` under the effort rule in [model
routing](../instructions/model-routing.md#keep-role-settings-fixed); independent validation does not use it. Choose one
of the eight listed model IDs, the newest of each model family; an unset or unrecognized value uses `gpt-6.2-astra`. Set plugin options in `/config` or
with `claude plugin configure`. On Codex, set environment variables before starting the session. A value of `false`,
`0`, `off`, or `no`, in any letter case, turns a boolean feature off.

The Claude Code `worker` agent runs at `worker_effort`, on the model the main session passes per call under
`implementation_worker`; the mod enforces both, and an invalid effort keeps the registry pin. The session context
reports the effort as `Worker agent effort: <effort>.` Codex has
no plugin settings UI, so its session hook reads `codex_worker_model` and `codex_worker_effort` read-only from Claude
Code's saved settings (`pluginConfigs` in `~/.claude/settings.json`, or under `CLAUDE_CONFIG_DIR`). The environment
variables override them, and an invalid value falls back to the defaults with a one-line notice. The session context
reports them as `Codex worker model: <model> at <effort>.` They apply from the next Codex session, and reading them
never writes Codex or Claude settings. Only the allowlisted changes in [Host settings](#host-settings) write settings.

| Feature | Claude Code `/config` key | Codex environment variable |
|---|---|---|
| Block built-in subagents | `agent_guard` | `HEI5ENBUG_AGENT_GUARD` |
| Pin role models | `role_pinning` | Not applicable |
| Risk labels on tool calls | `risk_highlight` | Not applicable |
| Work board for subagents | `work_board` | Not applicable |
| Secret redaction in tool results | `secret_redaction` | Not applicable |
| Implementation worker route | `implementation_worker` (`auto`, `codex`, `haiku`, `sol`, `sonnet`, or `opus`) | Not applicable |
| Claude Code worker effort | `worker_effort` (default `high`) | Not applicable |
| Codex worker model and effort | `codex_worker_model` (`auto`, `gpt-6-luna`, `gpt-6.2-sol`, or `claude-sonnet-5-5`, default `auto`) and `codex_worker_effort` (`high` or `xhigh`, default `high`) | `HEI5ENBUG_CODEX_WORKER_MODEL` and `HEI5ENBUG_CODEX_WORKER_EFFORT` |
| Codex service tier | `codex_service_tier` (`default` or `fast`, default `default`) | `HEI5ENBUG_CODEX_SERVICE_TIER` |
| Review model | `review_model` (a pinned model ID, default `gpt-6.2-astra`) | Not applicable |
| Response language guard | `language_guard` | `HEI5ENBUG_LANGUAGE_GUARD` |
| DataGrip query guard | `datagrip_guard` | `HEI5ENBUG_DATAGRIP_GUARD` |
| Approval guard | `approval_guard` | `HEI5ENBUG_APPROVAL_GUARD` |
| Approval scope | `approval_scope` (`tiered` or `session`, default `tiered`) | `HEI5ENBUG_APPROVAL_SCOPE` |
| Orca worktrees for other repositories | `orca_worktree` | `HEI5ENBUG_ORCA_WORKTREE` |
| Host settings mode | `host_settings` (`apply` or `report`, default `apply`) | `HEI5ENBUG_HOST_SETTINGS` |
| Minimum free memory to start an agent session | `session_memory_min_mb` (MB, default `2048`; `0`, `off`, `false`, or `no` turns the gate off; see [Orca session start](guards.md#orca-session-start)) | `HEI5ENBUG_SESSION_MEMORY_MIN_MB` |
| Delegated runs per request | `request_run_cap` (default `40`; `0`, `off`, `false`, or `no` turns the cap off; see [Request caps and parallel limit](guards.md#request-caps-and-parallel-limit)) | `HEI5ENBUG_REQUEST_RUN_CAP` |
| Retries per request | `request_retry_cap` (default `5`; `0`, `off`, `false`, or `no` turns the cap off) | `HEI5ENBUG_REQUEST_RETRY_CAP` |
| Hook Python interpreter | `python` (an absolute path, default empty) | `HEI5ENBUG_PYTHON` |
| Plugins refreshed with this one | `refresh_plugins` (comma-separated `plugin@marketplace` IDs, default empty) | `HEI5ENBUG_REFRESH_PLUGINS` |
| Subagent permission block in `~/.codex/AGENTS.md` | Not applicable | `HEI5ENBUG_SUBAGENT_POLICY` |
| Question tool flag | Not applicable | `HEI5ENBUG_CODEX_ASK_TOOL` |

The Codex service tier `fast` adds `-c service_tier="fast"` to every Codex run that `role_runner.py` starts, a new run
or a resume, and to the reviewer runs of `text_review.py review`; the option `--service-tier fast` of both scripts sets
it for one call, and the option or the environment variable `HEI5ENBUG_CODEX_SERVICE_TIER` overrides the saved
setting. A Claude run is unchanged, and the pinned model and effort and their verification stay as they are. Any other
value is a usage error that names the allowed values.

The hook Python interpreter is the absolute path of a Python 3.12 or later interpreter. Install `pglast` into it to run
the SQL guard's parser. Every hook starts through `scripts/hook_python.sh`, which runs its script with this interpreter.
It uses the Claude Code `python` option first and then `HEI5ENBUG_PYTHON`, and only a path that starts with `/` and
names an existing executable file counts. An empty, relative, missing, or invalid value falls back to `python3` on the
`PATH`, so an unset option behaves as before. Setting the path skips a version-manager shim, such as a pyenv shim. On one
machine whose 10 logical cores carried a 1-minute load average of 60 to 69, `python3 -c pass` took 2.05 to 3.18 s
through the shim and 0.09 to 0.17 s through the real interpreter, `required_checks_hook.py` on one Bash input took 1.81
to 3.75 s against 0.24 to 0.73 s, and `orca_placement_hook.py` took 2.02 to 2.26 s against 0.56 to 0.81 s. A shim can
also select a different Python per project. The launcher caches compiled bytecode under
`$XDG_STATE_HOME/hei5enbug-agent-setup/pycache/` (default `~/.local/state`). This is a guard state folder, so the
approval guard denies agent writes there like those to `approvals/`, `heartbeats/`, and `interpreter/`. Without an
absolute state folder, hooks run without a cache.

Without a valid configured path, the launcher also caches the interpreter it resolves. It reads the first `python3` on
`PATH` without starting a process, and when `interpreter/cache` in the state folder names that same `python3` and an
executable file, it runs that absolute path. The resolver writes the cache and then a second file, `interpreter/verified`,
inside a folder only the current user can enter. The launcher trusts the cache only when both files belong to the current
user, neither is a symlink, and the cache is not newer than `verified`, so a rewrite of the cache by another account
makes it newer and the hook runs with `python3` from `PATH`. A hook also removes a cache that group or others can write.
The remaining limit is a write in the instant between the launcher's check and its read, which needs write access to a
file the current user owns. On a cold or stale cache, such as after another `python3` came first on `PATH` or the file
was deleted, the hook runs with `python3` from `PATH` as before, and one detached resolver runs that `python3` once, from
the root folder, to print its `sys.executable`, keeps the result only for Python 3.12 or later, and writes the cache. All
sessions share the lock file `interpreter/lock`, which holds the resolver's process ID, so at most one resolver runs and
a hook takes the lock over only when that process is gone. When resolution fails, nothing is cached and
`interpreter/failed` stops further attempts for a minute across all sessions. Resolution follows the user's default
`python3`, not a project's version file.

Without a matching launcher environment, the Mod refuses pinned GPT requests before a provider request. This refusal has
no toggle. The session instructions and operating rules also have no toggle, except the `orca_worktree` line, which
loads the cross-repository rules; disable the plugin itself to turn them off.

## Implementation worker settings

Each host keeps its implementation worker default in its plugin option, and the user can change it at any time. Claude
Code sets it in `/config` or with `claude plugin configure`; Codex reads the same option from Claude Code's saved
settings and lets an environment variable override it. A change applies from the next session.

| Host | Option | Values | Default | Effect |
|---|---|---|---|---|
| Claude Code | `implementation_worker` | `auto`, `haiku`, `sonnet`, `opus`, `codex`, `sol` | `auto` | `auto`: the main session picks the `worker` agent's model per assignment, `haiku` for easy work and `sonnet` for normal or hard work, and the mod denies any other model. `haiku`, `sonnet`, and `opus` run the `worker` agent on that model only. `codex` and `sol` run a GPT worker through the role runner. A GPT worker, `gpt-6-luna` for easy work or `gpt-6.2-sol` for hard work, is also the fallback when a Claude route fails or stops on a usage limit. |
| Codex | `codex_worker_model` | `auto`, `gpt-6-luna`, `gpt-6.2-sol`, `claude-sonnet-5-5` | `auto` | `auto`: the main session picks per assignment, `gpt-6-luna` for easy work and `gpt-6.2-sol` for hard or unsure work, and the agent guard allows exactly those two models. A fixed GPT value allows only that model. `claude-sonnet-5-5` runs the Claude Sonnet route first through the role runner, and the GPT worker is its fallback. Claude Sonnet is also the fallback when the GPT worker fails or stops on a usage limit. |
| Codex | `codex_worker_effort` | `high`, `xhigh` | `high` | The lowest effort a worker spawn may use; each spawn may also use `xhigh`. |

Before this setting, the Codex implementation worker ran Claude Sonnet through the role runner, and the GPT worker
was only its fallback. A Codex user who saved `gpt-6-luna` or `gpt-6.2-sol` keeps that model as a fixed worker, now the
first route. A user who saved nothing, or an unrecognized value, gets `auto`. A user who wants the earlier Claude route
sets `claude-sonnet-5-5`.

Claude Code no longer has the `worker_model` and `sonnet-worker` pair: one `worker` agent runs on the model the main
session passes per call, and the plugin ignores a saved `worker_model`. A user who saved nothing, or `claude-haiku-5-5`,
keeps the old behavior under `auto`. A user who saved `claude-sonnet-5-5` or `claude-opus-5-5` there sets
`implementation_worker` to `sonnet` or `opus`; a saved `claude-fable-5-2` has no equivalent.

## Codex automatic settings

On Codex, the session hook manages two settings, and both take effect from the next session. It keeps this marked block
at the end of `~/.codex/AGENTS.md`, creating the file when it is missing:

```text
<!-- hei5enbug:subagents -->
When hei5enbug-agent-setup is active, use subagents according to its situation-based delegation rules.
<!-- /hei5enbug:subagents -->
```

It also enables the `default_mode_request_user_input` feature when `codex features list` shows it off (Codex 0.170.0
lists it as under development and the Codex documentation does not cover it), so
`request_user_input` is available in Default mode. This does not enforce blocking or disable client-side automatic
resolution. Required decisions follow the [clarification rule](../instructions/session/common.md#clarification); after
an interrupted connection, use [connection recovery](../instructions/connection-recovery.md). Setting
`HEI5ENBUG_SUBAGENT_POLICY=off` removes only the marked block and never edits anything outside it. Setting
`HEI5ENBUG_CODEX_ASK_TOOL=off` disables the feature again, but only when the plugin enabled it; a feature you enabled
yourself stays on. A failed step is retried at the next session start and never stops the session instructions from
loading. Hosts, hook trust, and available tools still govern execution. See the official [Codex subagent
contract](https://learn.chatgpt.com/docs/agent-configuration/subagents).

## When a guard blocks every tool call

On Claude Code, the approval guard, the DataGrip query guard, and the Bash dispatcher that runs the public boundary check block a call when they fail.
A hook that cannot start, times out, exits with a code other than 0 or 2, or prints invalid output blocks each call it
covers. The transcript shows `failed; blocking because onFailure is "block"` (or `timed out` after a timeout)
followed by the hook's error output. Find the cause in that line and apply its fix:

| What you see | Cause | Fix |
|---|---|---|
| `could not run <hook>: python3 was not found` | No Python 3 on the PATH that hooks get, such as a session started from an app with a narrow PATH | Install Python 3 and restart the session, or set the Hook Python interpreter option to an absolute path |
| `failed` with `No such file or directory` or `Cannot find module` | A hook script is missing from the plugin folder, such as after an update while the session still runs the old version | Restart the session, or reinstall the plugin, then retry |
| `timed out` | The hook ran past its time limit, usually under heavy machine load | Close heavy jobs or wait for the load to drop, then retry |
| `failed` followed by a Python traceback | A bug in the hook, or an interpreter that cannot run it | Set the Hook Python interpreter option to Python 3.12 or later and retry; if the traceback stays, report it with its text |

When the cause is not clear and the work cannot wait, turn off the guard's feature option in
[Feature options](#feature-options) until the cause is fixed. The guard then stops protecting calls, so turn it back
on afterward.

On Codex, `onFailure` has no effect: a PreToolUse hook that fails is reported, and the tool call continues.
Read the hook error in the transcript there instead of expecting a block.
