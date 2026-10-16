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
├── config/model-registry.json
├── instructions/
│   ├── claude-agents.md
│   ├── codex-agents.md
│   ├── confluence.md
│   ├── documentation.md
│   ├── failure-and-maintenance.md
│   ├── implementation-delegation.md
│   ├── implementation-execution.md
│   ├── implementation-planning.md
│   ├── independent-model-validation.md
│   ├── model-evaluation.md
│   ├── model-routing.md
│   ├── protected-values.md
│   ├── services.md
│   └── session/
│       ├── claude-code.md
│       ├── codex.md
│       ├── common.md
│       └── core.md
├── scripts/
│   ├── agent_guard.py
│   ├── approval_guard.py
│   ├── approval_state.py
│   ├── datagrip_guard.py
│   ├── language_guard.py
│   ├── plugin_toggles.py
│   ├── role_runner.py
│   ├── session_context.py
│   └── verify_spawn.py
├── tests/
├── LICENSE
├── pyproject.toml
├── agents/
│   ├── ko/
│   │   ├── designer.ko.md
│   │   ├── reviewer.ko.md
│   │   ├── scout.ko.md
│   │   ├── sonnet-worker.ko.md
│   │   └── worker.ko.md
│   ├── designer.md
│   ├── reviewer.md
│   ├── scout.md
│   ├── sonnet-worker.md
│   └── worker.md
├── standalone-agents/
│   ├── codex-designer.toml
│   ├── codex-reviewer.toml
│   ├── codex-scout.toml
│   └── codex-worker.toml
└── skills/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── docs-rewrite/
    ├── document-to-confluence/
    ├── orca-plugin-refresh/
    ├── session-retro/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

Each plugin skill folder holds its own `SKILL.md` plus any references or scripts it needs. The plugin manifests
package the same `skills/` directory for Codex and Claude Code without copying skills into host-specific directories.

The `agents/` directory ships with the Claude Code plugin, so installing the bundle adds the
`hei5enbug-agent-setup:scout`, `hei5enbug-agent-setup:worker`, `hei5enbug-agent-setup:sonnet-worker`,
`hei5enbug-agent-setup:designer`, and `hei5enbug-agent-setup:reviewer` subagents. No manual copy is needed. The manifest
lists only these five English definitions, so the Korean mirrors in `agents/ko/` are not registered.

Codex discovers subagents only in `~/.codex/agents/` and `.codex/agents/`, so a plugin cannot register one.
Instead, the session hook copies `standalone-agents/codex-scout.toml`, `codex-worker.toml`,
`codex-designer.toml`, and `codex-reviewer.toml` to matching `~/.codex/agents/<role>.toml` files when absent. They
define four roles that also exist on Claude Code, with fixed
reasoning effort and sandbox. The Codex `reviewer` role has no model key; the skill instructions pass its model and
effort explicitly when it is the fallback. The plugin `worker` replaces the
built-in Codex `worker`, and `scout` leaves the built-in `explorer` untouched. A file you edited is never
overwritten, and the agents become available in the next Codex session. Because an edited copy never changes,
the files set no model; the Codex instructions pass the pinned model on every spawn instead. The hook also
removes an `explorer.toml` and a `researcher.toml`, and replaces a `worker.toml`, that an earlier version wrote, but only while the file is
byte-identical to that version's bundled file, so a copy you edited stays. When the plugin is disabled, the installed
`worker` role runs as an ordinary implementation worker instead of refusing to edit.

Built-in subagents stay out on both hosts. On Claude Code the mod hides the built-in `general-purpose`, `Explore`,
`Plan`, and `claude` agents from the agent list (`agent.offer`) and denies them and every fork (`agent.spawn`). The
narrow-purpose built-ins `claude-code-guide` and `statusline-setup` pass, as do plugin agents and definitions from any
user, project, CLI, or managed source. On Codex the `PreToolUse` hook `scripts/agent_guard.py` keeps its existing
behavior: it denies an omitted type, `default`, `explorer`, and every type without a role file, including the
built-in `worker` before the plugin role exists. Skills that ask for an independent
read-only worker use a role whose verified model, effort, and tools match the skill contract. `scout` handles one
bounded local investigation, including local-evidence research tickets, and one bounded public research question with web search and fetch tools. A
skill-assigned review role uses the configured review model, then the `reviewer` fallback if that runner is unavailable.
The reviewer returns findings only; the main session reviews once and decides. Skills that write trial outputs use a
verified evaluation runner when required. See the conditional [model routing contract](instructions/model-routing.md).

### Claude Code mod

On Claude Code, `config/claude-mod.json` loads the mod `hooks/mod/register.js`, which holds the Claude-only guards:
the built-in subagent block, role pinning, session approvals, and the GPT refusal. It was tested with Claude Code
2.1.292. When the mod does not load, such as on an older Claude Code, with `disableAllHooks`, or under a managed
policy, these guards are absent and the host's normal permission flow applies.

Role pinning pins each plugin role's model and effort on every request: `scout` uses `claude-sonnet-5-5` with `medium`,
`worker` uses `claude-haiku-5-5` with `high`, `sonnet-worker` uses `claude-sonnet-5-5` with `high`, `designer` uses
`claude-opus-5-5` with `xhigh`, and `reviewer` uses `claude-opus-5-5` with `high`. A subagent that answers on another model is stopped: its later requests
end with a refusal, its tool calls are denied, and its result is replaced with a warning. The session context then
gets the line `hei5enbug-agent-setup mod: role pinning active` from the registered mod `prompt.context` hook only when
role pinning is active. This line lets the main session send assignments directly and skip per-delegation settings and
subagent record checks.

### GPT in Claude Code

The pinned main models `gpt-6.1-sol` and `gpt-5.6-luna` are available through a local gateway. Claude models and
subagents keep using your Claude login and existing role pins. GPT credentials stay in a dedicated protected
profile; the helper never reads Codex credentials. Browser sign-in uses your ChatGPT plan. An API-key profile uses
separately billed OpenAI API usage and must be selected explicitly. The launcher never changes profiles or billing
modes automatically.

GPT Luna is fixed to `gpt-5.6-luna` with `high` or `xhigh` by user policy. The mod and the gateway enforce the
registry's effort rule: each keeps `high` or `xhigh` and changes any other effort to `xhigh`. The mod also rejects
other Luna releases, and the direct helper rejects any effort outside that rule. hei5enbug roles use `xhigh`.
Automatic model refresh preserves this selection. Apply the same pin to new assignments and resumed sessions.

Run the helper from a source checkout with the `claude-gpt` extra, not from the installed plugin cache. Sign in,
check the active profile, then launch Claude Code with that profile:

```sh
uv run --extra claude-gpt python scripts/claude_gpt.py auth subscription
uv run --extra claude-gpt python scripts/claude_gpt.py status
uv run --extra claude-gpt python scripts/claude_gpt.py launch --profile <profile-id> -- [Claude arguments]
```

Install and enable `hei5enbug-agent-setup@hei5enbug` at the checkout's `<major>.<minor>.<patch>` version. The launcher
checks the enabled installation's version, ignoring a local cachebuster suffix. It refuses
conflicting Claude authentication, API-key, or gateway environment settings and `apiKeyHelper` configuration.

For local checkout verification, add `--plugin-dir /absolute/path/to/checkout` to the Claude arguments. This loads
that plugin for the session in place of the installed copy with the same name. The matching installation is still
required; a matching entry in `plugin list` alone does not prove which local Mod files the session loaded.

In the `/model` picker, press `s` to choose a GPT model without saving it as the default for new sessions. `Enter`
or `/model <name>` saves the user default; starting with `--model` keeps the saved default. `gpt-5.6-luna` has no
separate picker row, but you can start it with `--model gpt-5.6-luna`. The Mod cannot set a default model, and role
pins do not change. If you save a GPT default, an ordinary Claude session refuses the request before any provider
request; restore a Claude default with `/model claude-opus-5-5`.

When resuming with `--resume`, keep tools used earlier in the conversation available. Removing their definitions
with `--tools` causes `unknown_tool` before a GPT provider request. Restrict execution through Claude Code's
permissions instead; retaining a tool definition does not grant permission to run it.
Earlier tool calls must also match the available tool schemas, even if the tool returned an error. Invalid
historical arguments stop a GPT switch or resume before a provider request.

The gateway retries temporary failures for at most three total provider attempts, within 60 seconds of the first
recoverable failure. That deadline includes waits and active retry attempts; the initial healthy stream has no
recovery deadline. It waits 1 then 2 seconds, plus 0–0.5 seconds of jitter. Before visible text it retries the
same request; after visible text it can continue while keeping delivered text, though the wording may differ.
Completed tool calls are never replayed. Authentication, quota, invalid input, and other terminal errors stop.
Cancellation closes the active request. There is no automatic provider or billing fallback. For a ChatGPT plan
usage-limit error, check ChatGPT Settings > Usage; the helper does not predict a reset time. An unknown `429` stops
as an unclassified error, not as proof of a quota limit.

When Claude exits, the launcher stops the local gateway and releases its port. It does not edit the installed
plugin cache or Claude settings, though a default saved with `Enter` or `/model <name>` can remain. Exact
resumption of an interrupted response is not guaranteed.

### Response language

A language guard, `scripts/language_guard.py`, checks that every reply and every progress update is written in the
response language. Claude Code takes the language from the `language` setting, read from the local project settings,
then the project settings, then the user settings; without one, nothing is enforced. Codex reads
`HEI5ENBUG_RESPONSE_LANGUAGE` and uses Korean when it is unset. Only languages with a distinctive script are
checked: Korean, Japanese, Chinese, Russian, Ukrainian, Greek, Arabic, Hebrew, Thai, and Hindi. For any other
language, such as English or French, the instruction alone applies.

The check ignores code, quotes, and URLs. A text passes when at least 30% of its letters are in the target script,
and very short text always passes. A `Stop` hook asks for a rewrite when a reply fails, at most 3 times per turn.
A `PostToolUse` hook adds a reminder after a progress update in another language. It runs asynchronously, so the
reminder reaches the model on the next turn. Put text the user asks for in another language in a code block or block
quote.

### DataGrip query guard

A `PreToolUse` hook and a `PermissionRequest` hook, both `scripts/datagrip_guard.py`, run before the DataGrip MCP tool
`execute_sql_query`. The guard reads the connection from `.idea/dataSources.xml` in the DataGrip project that
`projectPath` names. A connection whose name contains `승인` always asks for approval. PostgreSQL and SQL Server reads
run without approval, and PostgreSQL reads run inside a read-only transaction with
`SET LOCAL statement_timeout = '60s';`. With `approval_guard` on, non-destructive PostgreSQL and SQL Server writes
share the single `mcp:session` approval with all other MCP writes. Text that names `delete`, `drop`, or `truncate`
anywhere, literals and comments included, a statement led by `DO`,
`EXEC`, `EXECUTE`, or `CALL`, a connection whose name contains `승인`, an unknown connection, another
database type, and text the guard cannot parse always ask. On Codex, a call that needs approval is denied with a code
instead; see [Approval guard](#approval-guard). With the toggle off, every write asks as before. In Codex, trust the
hook in `/hooks`.

Optionally, install the `pglast` parser once:

```bash
uv venv --python 3.12 "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser"
uv pip install --python "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser/bin/python" pglast==8.4
```

Without it, PostgreSQL falls back to a stricter text check that may ask more often but still never lets a write run
without approval.

### Approval guard

A `PreToolUse` hook runs `scripts/approval_guard.py` before Bash, MCP, Claude file tools (`Read`, `Edit`, `Write`,
`MultiEdit`, `NotebookEdit`), and Codex `apply_patch` calls. It also handles `PermissionRequest`, `PostToolUse`, and
`UserPromptSubmit`. Reads run without approval on both hosts. Calls have these outcomes:

- **Read** runs without approval.
- **Write** asks once per session for its key, such as `kubectl:apply@(default) dev/web`. Later calls with the same key
  run without asking.
- **Always** asks every time for destructive or forced actions, existing sensitive CLI reads, and unclassified calls.
- **Sensitive** warns that a call may expose a protected value, recommends `secret_exec.py`, and asks every time.
- **Request** asks for a bundle of non-destructive write keys before the actual calls.
- **Secret** is denied on both hosts because the command would print a secret value.
- **Pass** is a call the guard does not cover, so the host's own permission flow decides.

| CLI | Read | Secret (denied) | Always (asks every time) | Key target |
|---|---|---|---|---|
| `kubectl`, `oc` | `get`, `describe`, `logs`, `diff`, any call with `--dry-run=client` or `--dry-run=server` | `get secret` with an output format that prints values, `get --raw` on a `secrets` path, `config view --raw`, `create token` | `delete`, `drain`, `--force`, `--prune` | kubeconfig, then context / namespace |
| `helm` | `list`, `status`, `get notes`, `repo list` | none | `uninstall`, `get all`, `get manifest`, `get values` | kubeconfig, then context / namespace |
| `az` | `list`, `show`, `exists`, `query`, `version` | `keyvault secret show` and `download`, `list-keys`, `account get-access-token` | `delete`, `purge` | subscription / resource group |
| `terraform`, `tofu` | `plan`, `show`, `validate`, `state list`, `fmt -check`, `output` without `-json` or `-raw` | none | `destroy`, `apply -destroy`, `state rm`, `output -json`, `output -raw`, `state show` | directory : workspace |
| `aws` | `describe-*`, `list-*`, `get-*` other than secret reads, `s3 ls` | `secretsmanager get-secret-value` and `batch-get-secret-value`, `ssm get-parameter*` with `--with-decryption`, `kms decrypt` | `delete-*`, `terminate-*`, `s3 rm`, `s3 sync --delete` | profile / region |
| `gcloud`, `gsutil` | the first verb in the command path is `list`, `describe`, `get-*`, `ls`, or `cat` | `secrets versions access`, `auth print-access-token` | `delete`, `gsutil rm`, `gsutil rb` | project |
| `docker`, `podman` | `ps`, `images`, `logs`, `<object> ls` | none | `rm`, `rmi`, `prune`, `compose down -v` | context |
| `psql`, `sqlcmd` | a query that is a read; `psql` reads run with `default_transaction_read_only=on` and `statement_timeout=60000` | none | files, stdin, interactive use, text that names `delete`, `drop`, or `truncate`, and statements led by `DO`, `EXEC`, `EXECUTE`, or `CALL` | host / database |
| `curl` | GET/HEAD without data, form, upload, or JSON flags | none; credentials in argv are sensitive | destructive methods such as DELETE | method / scheme and host |
| `kustomize` | every call | none | none | none |
| `mysql`, `mongosh`, `redis-cli` | none | none | every call | none |

A write key is `<cli>:<subcommand>@<target>`, where the subcommand is the words before the first flag. For `kubectl`,
`oc`, and `helm`, the target is the kubeconfig (`--kubeconfig`, then `KUBECONFIG`, else `(default)`) followed by the
context and namespace; a context that is not given is read through the same kubeconfig. Any other parseable subcommand
is a write, so `kubectl apply` and `helm upgrade` ask once per session. A covered command inside an indirectly run
region (`$(...)`, backticks, `eval`, `xargs`, or `sh -c` with any flag cluster that contains `c`) is always. When such
a region itself prints a secret, the whole command is denied. A heredoc on a covered command is always. A `command -v`
lookup runs nothing and is not classified.

A compound command is judged as a whole. A secret segment denies it. When any segment is always, the call asks, and
its approval covers the always keys (once) and the write keys (session). Otherwise a write asks for its keys, unless a
segment is not verified or the output goes to a file, in which case the whole command always asks. A covered read
stays a read only when every other segment is a filter such as `grep`, `head`, or `jq`, and output redirections go
only to `/dev/null` or `2>&1`. Wrappers such as `sudo`, `env`, `nice`, and `time` are skipped, with their options,
before the executable is read. Targets for write and always calls come from flags or the environment. When neither is
set, `kubectl config current-context` and `az account show` run for those calls only, with a 3-second limit.

A `psql` read is rewritten to run in a subshell with `PGOPTIONS` extended by
`-c default_transaction_read_only=on -c statement_timeout=60000`, so the server refuses writes even when the guard's
read check misses
a function call, and the option never reaches later commands.

The guard reads shell files invoked by `bash`, `sh`, `zsh`, `./`, `source`, or `.`, Python `.py` files, Node `.js` and
`.mjs` files, Makefile recipes for the selected/default target and one level of prerequisites, and the script text in
`package.json` for `npm`, `pnpm`, or `yarn run <name>`. Files resolve from the event's `cwd` and are limited to 256 KiB.
Shell lines and Makefile recipes use the CLI classifier. Python/Node strings starting with a covered CLI and literal
argv lists are classified too. Reads need no approval; writes combine their keys; destructive, forced, and secret
calls keep their normal rules. Unreadable or larger files are unclassified. A script naming a covered CLI or importing
`boto3`, `azure`, `kubernetes`, `psycopg`, `psycopg2`, `pymysql`, `sqlalchemy`, `pymongo`, `redis`, or `google.cloud`
without a classifiable call asks every time. Its `script:<sha256>` key includes its path, argv, content, and the values
of `KUBECONFIG`, `AWS_PROFILE`, `CLOUDSDK_CORE_PROJECT`, and `DOCKER_CONTEXT`. A script with none of these passes.

MCP tool names split at `_`, `-`, and camelCase. Destructive name words always ask. String fields `sql`,
`statement`, and `queryText`, and a `query` field whose text starts like a SQL statement (a search phrase does not), use
the DataGrip SQL classifiers: reads run freely, destructive statements always ask,
and other SQL uses `mcp:session`. Execution name words (`repl`, `exec`, `execute`, `eval`, `run`, `code`, `script`,
`command`) are writes unless their input contains a destructive word, which always asks. For other names, a write
word takes precedence; names with only read verbs are reads, and names with no known verb are writes. One
`mcp:session` approval covers every non-destructive MCP write for that session, including DataGrip and tabularis writes.

For `mcp__tabularis__run_query`, `connection_id` resolves an ID or name from tabularis' `connections.json`.
The config directory is `~/Library/Application Support/tabularis` on macOS, `$XDG_CONFIG_HOME/tabularis` or
`~/.config/tabularis` on Linux, and `%APPDATA%\tabularis` on Windows. `HEI5ENBUG_TABULARIS_DIR` overrides it for tests.
The guard extracts only `id`, `name`, and `params.driver`; it never prints other connection fields or passwords.
`postgresql` uses the PostgreSQL classifiers; `sqlserver` and `sqlserver-entra` use the SQL Server classifiers.
Reads run without approval; non-destructive writes use `mcp:session`. A name containing `승인`, another driver, an
unknown connection, or an unreadable file always asks. So do raw `delete`, `drop`, or `truncate` words and statements
led by `DO`, `EXEC`, `EXECUTE`, or `CALL`. These queries use `sql:always:tabularis:<id>:<digest>` keys. Other tabularis
tools keep the name rules.

`curl` without a request method other than GET/HEAD and without `-d`, `--data*`, `-F`, `--form`, `-T`,
`--upload-file`, or `--json` is a read. Otherwise it is a write keyed by `curl:<METHOD>@<scheme://host>`; destructive methods such as DELETE always ask.
`-u`/`--user` or an `Authorization` header in argv makes it sensitive.

Claude `Read` and Bash reads (`cat`, `less`, `head`, `tail`, `grep`, `rg`) of `~/.kube/config`, any `KUBECONFIG` path,
`~/.aws/credentials`, `~/.aws/config`, `~/.azure/**`, `~/.config/gcloud/**`, `~/.pgpass`, `~/.docker/config.json`,
`~/.netrc`, or `.env*` files are sensitive. So are `printenv`, `env` without a command, `kubectl exec ... env|printenv`,
`docker inspect`, and `docker exec ... env`. Claude asks with “This may expose a protected value; prefer
secret_exec.py ...”; Codex denies with a one-time code. These approvals never become session approvals.

Prepare a bundle before running writes:

```bash
python3 <plugin root>/scripts/approval_guard.py request --key 'kubectl:apply@(default) dev/web' --key mcp:session --why 'Deploy the requested change and update the issue'
```

Claude asks showing every key and the reason, then records the keys in `PostToolUse`. Codex denies with one code for
the bundle and records it only when the user types `승인 <CODE>`. The command prints the keys and exits 0; it never
writes approval state itself. Keys must be `<cli>:<kind>@<target>` or `mcp:session`. Destructive or forced kinds,
sensitive reads, unclassified calls, `sql:always:*`, and destructive `mcp:<tool>` keys cannot be pre-approved.

On Codex, a call that needs approval is denied with a code:

```text
Approval required: kubectl apply on (default) dev/web. Ask the user to reply `승인 K7M2QX`; do not retry until they do.
After the user replies with the code, retry this exact call immediately and continue the task without asking again.
```

The user types `승인 <CODE>` or `approve <CODE>` in chat. A `UserPromptSubmit` hook records the code, and the agent
immediately retries the exact call and continues the task without asking again. Both hosts add the approved
descriptions and that retry instruction to `UserPromptSubmit` context. A code covers every key of the denied call: its
always keys as one-time approvals and its write keys as
session approvals. If a Codex one-time approval is in flight without `PostToolUse`, the next attempt for the same key
may reuse it once without a new code. The approval moves to that retry; another interruption needs a new approval
request. `PermissionRequest` allows only the call holding the approval, and `PostToolUse` releases it.

Each session counts issued approval requests per key until a call completes. Claude asks and Codex code responses
count, including repeating a pending code. After three requests without `PostToolUse`, a fourth request is denied:
“This call was approved but did not complete three times; stop retrying and report to the user.” An approval already
given is honored, including a retry approved by the third code. `PostToolUse` resets the count for the completed
call's keys. Already approved session keys do not use another key's request budget.

The agent cannot approve anything itself. A Bash command that names the
approval or heartbeat state directory, or that runs `approval_guard.py`, `datagrip_guard.py`, or `approval_state.py` as
a program,
with `-m`, or through Python code that imports it, is denied on both hosts. Plain reads of those files, such as `cat`
or `rg`, are not. The validated `request` command above is the only execution exception. File edits inside either
state directory, including paths named in an `apply_patch` patch, are denied on both hosts.

Commands that need a secret value use the secret helper: `python3 <plugin root>/scripts/secret_exec.py --secret
DB_PASSWORD=k8s:<context>/<namespace>/<secret>/<key> -- <command>`. The sources are `k8s:`, `keyvault:<vault>/<name>`,
`aws:<secret id>[#<json key>]`, and `gcp:<project>/<name>[/<version>]`. `--file VAR=<source>` passes the path of a
temporary file instead of the value. The value reaches the command only through environment variables or temporary
files, and the helper masks it in the command's output. When a fetch fails, the helper prints only the source and the
fetch command's exit code, never the fetch's stderr. Each fetch has a 30-second timeout; a timeout exits 2 and
names the source with `timed out`.

A role runner child with `HEI5ENBUG_PARENT_SESSION=<host>:<session_id>` also reads the parent's approved keys without
changing its state. Malformed values are ignored. Children cannot record codes from `UserPromptSubmit` or run
`request`; an unapproved write is denied with instructions to request approval in the main session and retry.

Every event carrying a valid session ID touches `$XDG_STATE_HOME/hei5enbug-agent-setup/heartbeats/<host>-<session_id>`
and its `.<EventName>` file before the toggle check, on a best-effort basis. `PreToolUse` also writes the SHA-256 of
the current `hooks/hooks.json` as one line in `heartbeats/confirmed-<host>`. When this hash is missing or differs,
`UserPromptSubmit` adds a warning once per session and records that it was shown in the session state. The warning
explains that the guard has not been seen checking a tool call since its hooks changed, asks Codex users to trust
the plugin hooks in `/hooks`, and states that writes may run without approval until then. A classifier exception
asks every time with “The approval guard failed to check this call”. Turning the guard off still prints nothing.

The approval guard is a guardrail, not a security boundary: an agent with full shell access could bypass it. Calls the
guard does not cover follow the host's own permission flow. Approval state lives under `$XDG_STATE_HOME/hei5enbug-
agent-setup/approvals/` (default `~/.local/state`), one file per host and session, and files older than 7 days are
deleted when another approval is written. Set `approval_guard` to `false`, or `HEI5ENBUG_APPROVAL_GUARD=false` on
Codex, to turn the guard off. In Codex, trust the hooks in `/hooks`.


### Session approvals

On Claude Code only, the mod lets you approve certain outward-facing writes once per session. For each Bash and MCP tool
call, its `tool.check` hook classifies the action and asks the first time a covered kind runs in the session. When the
call succeeds, its `tool.call` hook reuses that classification for the same tool call instead of classifying it again,
and records the approved kind in the mod store (`$.store`) under the session ID, so later actions of the same kind in
that session run without a prompt. It covers creating git tags; pushing tags to a
configured remote; `gh release create` and `gh release edit` with only the tag and the flags `--title`, `--notes`,
`--target`, `--generate-notes`, `--notes-from-tag`, `--latest`, `--draft`, `--prerelease`, `--verify-tag`; and MCP tools
and a Codex worker's access to a directory outside the session folder (`codex exec`
with `--add-dir` or `-C`, or `python3 <plugin>/scripts/role_runner.py worker` or a writing capability with `--add-dir`),
approved separately for each directory and asked once per session. MCP tools are covered by the [Approval
guard](#approval-guard) on both hosts, and the DataGrip query tool by the DataGrip query guard. Each tool or command
kind is approved separately.

Destructive actions always ask: force pushes, deleting remote branches or tags, deleting a tag, `gh release delete`,
`gh repo delete`. Destructive MCP tools always ask through the [Approval guard](#approval-guard).
`gh release upload` always asks too, because it can publish any local file. So does `codex exec` with
`danger-full-access`, `--dangerously-bypass-approvals-and-sandbox`, `--dangerously-bypass-hook-trust`, or a `-c`
override of sandbox settings. So does a tag push to a URL, an unlisted remote, or `--repo`, or one that mixes a branch
into a `--tags` push, and so does a `gh release create` or `gh release edit` with attached assets, `--notes-file`, or
any other flag. A `role_runner.py` call with an unknown option, an expansion or glob token, or a redirect counts as
unverifiable and always asks. A compound command that contains anything the mod cannot verify always asks. A plain
`echo` with literal text after a covered command, such as `git tag v1 && echo done`, does not stop the approval from
applying; an `echo` with a variable, command substitution, glob, redirect, or pipe still asks. The mod store is local to
each session. The approval guard can read parent approvals when the role runner supplies
`HEI5ENBUG_PARENT_SESSION`; see [Approval guard](#approval-guard). Approvals belong to one session, and the mod drops
stored entries older than 7 days. Ordinary pushes and
all other commands keep the normal permission flow.

Do not add `permissions.ask` rules for these actions, because an ask rule prompts every time even after a session
approval.


## Feature options

Seven boolean features can be turned off, and each defaults to on. The implementation worker route and the review
model are string options in Claude Code. Choose `codex`, `haiku`, or `sonnet` for the route; an unset or unrecognized
value uses `sonnet`. The review model runs independent validation and skill review roles at `xhigh`. Choose one of the
seven pinned model IDs; an unset or unrecognized value uses `gpt-6-astra`. Set plugin options in `/config` or with
`claude plugin configure`. On Codex, set environment variables before starting the
session. A value of `false`, `0`, `off`, or `no`, in any letter case, turns a boolean feature off.

| Feature | Claude Code `/config` key | Codex environment variable |
|---|---|---|
| Block built-in subagents | `agent_guard` | `HEI5ENBUG_AGENT_GUARD` |
| One-time session approval | `session_approval` | Not applicable |
| Pin role models | `role_pinning` | Not applicable |
| Implementation worker route | `implementation_worker` (`codex`, `haiku`, or `sonnet`) | Not applicable |
| Review model | `review_model` (a pinned model ID, default `gpt-6-astra`) | Not applicable |
| Response language guard | `language_guard` | `HEI5ENBUG_LANGUAGE_GUARD` |
| DataGrip query guard | `datagrip_guard` | `HEI5ENBUG_DATAGRIP_GUARD` |
| Approval guard | `approval_guard` | `HEI5ENBUG_APPROVAL_GUARD` |
| Subagent permission block in `~/.codex/AGENTS.md` | Not applicable | `HEI5ENBUG_SUBAGENT_POLICY` |
| Question tool flag | Not applicable | `HEI5ENBUG_CODEX_ASK_TOOL` |

Without a matching launcher environment, the Mod refuses pinned GPT requests before a provider request. This refusal
has no toggle. The session instructions and operating rules also have no toggle; disable the plugin itself to turn
them off.

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

On macOS and Linux, the plugin hooks combine `instructions/session/core.md` and `instructions/session/common.md` with
either `instructions/session/codex.md` or `instructions/session/claude-code.md` for the current host. `core.md` holds
the rules that apply to every agent.
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
| A subagent starts | `SubagentStart` supplies a short role context: `core.md`, plus the "Assigned workers" rules for implementation agents. |
| A role runner child session starts | It receives `core.md` only; the runner puts the role rules before the assignment. |
| A tool call finishes | `PostToolUse` adds a language reminder after a progress update in another language. |
| A reply ends | `Stop` asks for a rewrite when the reply is not in the response language. |
| A DataGrip query is about to run | `PreToolUse` and `PermissionRequest` run the DataGrip query guard before `execute_sql_query`. |
| A Bash, MCP, or covered file tool call runs | `PreToolUse` runs the approval guard, including file-state protection and sensitive reads. `PermissionRequest` (Codex) and `PostToolUse` read or record approvals. `UserPromptSubmit` records a user code and supplies immediate-retry context on both hosts. On Claude Code, the mod's `tool.check` and `tool.call` hooks run the session approval for Bash tools. |
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

A missing or empty session file, an invalid local reference, main context larger than 9,000 UTF-8 bytes, or a role
context larger than 4,000 UTF-8 bytes produces an error on stderr and no partial context. Session-start hook errors do
not reliably block the host; resolve any reported loading error before relying on automatic instructions. Keep the
session files short and move details into conditional references. Windows execution and live model adherence are not
covered by the tests.

See the official [Codex hooks](https://learn.chatgpt.com/docs/hooks) and
[Claude Code hooks](https://code.claude.com/docs/en/hooks) contracts for lifecycle and trust behavior.

## Situation-based delegation

The main session chooses direct work or delegation using the rules in
[instructions/session/common.md](instructions/session/common.md). Known-path lookups, implementation that changes at
most two files, and integration fixes stay in the main session. Bounded investigations, bulky evidence gathering, and
larger independent implementation use workers when the expected benefit exceeds coordination overhead. Closely
dependent work keeps one owner. This policy does not guarantee a lower bill on every task.

The main session retains requirements, design, task boundaries, acceptance, and the final report.
[instructions/implementation-execution.md](instructions/implementation-execution.md) defines task preparation,
assignment fields, and acceptance for all implementation, including main-owned work.
[instructions/implementation-delegation.md](instructions/implementation-delegation.md) defines worker ownership,
conflict-free scheduling, recovery, and assigned-worker rules; read it before delegating implementation.
Direct work uses the main session's current model and effort.
A delegated task carries only its scope, relevant context, allowed/protected paths, prerequisites,
acceptance checks, and the host's pinned settings. Workers cannot start nested agents.

UI code, visual design, and diagram work goes to the host's designer route instead, except the kinds the host session
file assigns to the main session. On Claude Code, the main session draws ASCII and Mermaid diagrams in documents, edits
existing SVG diagrams, and makes new SVG or PNG flowcharts of up to seven nodes. A text or style-value edit that keeps
the layout and component structure may still go to the implementation worker, and design documents and RFCs stay in
the main session.

`config/model-registry.json` is the single source of model pins and capability pins; the scripts and the mod read it.
Each capability's per-host entries are listed in the [capability pins](instructions/model-routing.md#capability-pins)
section of the model routing contract. The five capabilities are `investigation`, `implementation`, `design`,
`language`, and `review`. Every fallback is the other model family; a fallback that needs the other host's model runs through the role runner, and one the current host can run in-host uses the named agent.

| Host | Implementation agent | Model and effort |
|---|---|---|
| Codex | Plugin `worker` role, verified from its rollout record | `gpt-5.6-luna`, `xhigh` |
| Claude Code | `hei5enbug-agent-setup:sonnet-worker` (default, `implementation_worker` is `sonnet`); `role_runner.py worker` on `codex` or on request; `hei5enbug-agent-setup:worker` for Haiku on `haiku` or on request, with fallback `role_runner.py worker` | `claude-sonnet-5-5`, `high` (default); `gpt-5.6-luna`, `xhigh`; `claude-haiku-5-5`, `high`; fallback `gpt-5.6-luna`, `xhigh` |
| Codex, designer | Plugin `designer` role with the pinned model, verified from its rollout record; fallback `role_runner.py agent --name designer --fallback` | `gpt-6-astra`, `xhigh`; fallback `claude-opus-5-5`, `xhigh` |
| Claude Code, designer | `hei5enbug-agent-setup:designer`, verified from its subagent record or the mod's role pinning; fallback `role_runner.py design` | `claude-opus-5-5`, `xhigh`; fallback `gpt-6-astra`, `xhigh` |
| Codex, local scout | Plugin `scout` role, verified from its rollout record | `gpt-5.6-luna`, `xhigh` |
| Claude Code, local scout | `role_runner.py scout`; fallback `hei5enbug-agent-setup:scout` | `gpt-5.6-luna`, `xhigh`; fallback `claude-sonnet-5-5`, `medium` |
| Codex, public researcher | `role_runner.py researcher`, which uses web search and no shell network, verified from its session record | `gpt-5.6-luna`, `xhigh` |
| Claude Code, public researcher | `role_runner.py researcher`, which uses web search and no shell network; fallback `hei5enbug-agent-setup:scout`, which has web search and fetch tools | `gpt-5.6-luna`, `xhigh`; fallback `claude-sonnet-5-5`, `medium` |
| Codex, skill review | `role_runner.py review`; fallback plugin `reviewer`, verified from its rollout record | `claude-opus-5-5`, `high`; fallback `gpt-6.1-sol`, `xhigh` |
| Claude Code, skill review | `role_runner.py reviewer` with the `review_model` setting; fallback `hei5enbug-agent-setup:reviewer` | `review_model` (default `gpt-6-astra`), `xhigh`; fallback `claude-opus-5-5`, `high` |
| Skill Builder trial execution and other non-review participants | Host's upper model from the Skill Builder adapter | Codex: `gpt-6.1-sol`, `xhigh`; Claude Code: `claude-opus-5-5`, `high` |

On Claude Code, `scripts/role_runner.py` runs the scout, researcher, reviewer, and Codex worker roles, and it runs a
registry capability, such as a Claude model capability, when `--instructions <file>` supplies its role definition. Its
agent mode runs a plugin agent's cross-family fallback, named by `--name <name>`. The main session writes the assignment
to a file and runs `python3 <plugin>/scripts/role_runner.py <role-or-capability>` or `python3 <plugin>/scripts/role_runner.py
agent --name <name> --fallback`, both with `--assignment <file> --result <file>`, from the session folder. It adds
`--model <id>` for `reviewer`, `--add-dir <dir>` for `worker`, a writing capability, or a `write` agent, `--mcp` for a
capability or agent that needs MCP tools or network, `--host claude|codex` to pick a capability's host entry, `--fallback`
for its fallback entry, and `--resume <session_id>` to continue a run from the `evidence.session` in its status line. The runner
puts the role rules before the assignment, runs the role on its pinned model, effort, and permissions (`codex exec`, or
`claude -p` for a Claude model), checks the host rollout or transcript record, and prints a final JSON status line.
Without `--mcp`, a Codex child gets `-c mcp_servers.<name>.enabled=false` for every server `codex mcp list --json` names,
and a Claude child keeps `--strict-mcp-config`. Each child receives `HEI5ENBUG_PARENT_SESSION` so it can use the main
session's approvals. Before sending the assignment to Codex, the runner sends “Run the shell command `true` exactly
once, then reply with OK only.” and requires `heartbeats/codex-<thread_id>.PreToolUse`. This confirms that the guard
received a tool event; a plain, `UserPromptSubmit`, or `SessionStart` heartbeat does not satisfy that check. Claude
children require `heartbeats/claude-<session_id>.UserPromptSubmit` or the existing plain heartbeat, since Claude does
not gate plugin hooks by trust. A missing required heartbeat exits 4.
Exit code 0 means the result is verified, 2 a usage error to fix, 3 that the role could not run, and 4 that the
required hook evidence was missing or the recorded model, effort, or sandbox did not match, so the result is
discarded. On 3 or 4 the main session uses the
role's plugin agent fallback. Independent validation has no fallback: the main session reports that it was not
performed. A capability entry whose `via` is `agent` is not run by the runner, which exits 2, so the main session uses
the agent route for it.

Independent ready tasks may run together within the host limit and the shared execution ceiling. If a role,
model, effort, quota, permission to delegate, or settings evidence is unavailable, the main session reports
that limitation and continues authorized work after stopping any affected worker. It preserves partial work,
user settings, permissions, and acceptance checks. It never silently substitutes a worker model.

After a substantial change and its checks are ready, the main session recommends one optional independent review
under [independent model validation](instructions/independent-model-validation.md). On Claude Code, the `review_model`
setting (default `gpt-6-astra`) reviews a Claude-authored result, and a GPT-authored result goes to `claude-fable-5-1`;
Codex uses its mapping in that file. Every reviewer runs at `xhigh`. When the configured reviewer shares the author's
model family, the result says the review is not cross-family. Approval is required for the particular result, and a
decline is not asked again. An unavailable reviewer, or a role runner exit code 3 or 4, means independent validation
was not performed; no other model substitutes for it. Routine author inspection and tests always remain.

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
`request_user_input` is available in Default mode. This does not enforce blocking or disable client-side
automatic resolution. Required decisions follow the [clarification rule](instructions/session/common.md#clarification);
after an interrupted connection, use [connection recovery](instructions/connection-recovery.md).
Setting `HEI5ENBUG_SUBAGENT_POLICY=off` removes only the marked block and
never edits anything outside it. Setting `HEI5ENBUG_CODEX_ASK_TOOL=off` disables the feature again, but only when the
plugin enabled it; a feature you enabled yourself stays on. A failed step is retried at the next session start and
never stops the session instructions from loading. Hosts, hook trust, and available tools still govern execution.
See the official [Codex subagent contract](https://learn.chatgpt.com/docs/agent-configuration/subagents).

## Work efficiency

[Work-efficiency rules](instructions/work-efficiency.md) load only before substantial implementation.
[Model evaluation rules](instructions/model-evaluation.md) load only before repeated model evaluation, and
[failure and maintenance rules](instructions/failure-and-maintenance.md) load only before plugin maintenance or
repeated-failure diagnosis. Required results and checks define completion. Valid check evidence is reused until
its relevant inputs change; optional research and an unperformed optional review do not keep accepted work open.

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
| [`session-retro`](skills/session-retro/SKILL.md) | Reviews a day's Claude Code and Codex sessions of a repository with read-only scouts, turns corrections, failures, and repeated work into evidence-backed skill improvements per plugin, asks the open decisions, and writes plans on request. [Korean guide](skills/session-retro/SKILL.ko.md). |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Creates, tests, and packages agent skills through a draft → test → review → improve loop. [Korean guide](skills/skill-builder/SKILL.ko.md). |
| [`orca-plugin-refresh`](skills/orca-plugin-refresh/SKILL.md) | Updates this plugin safely offline and applies an installed version to idle Orca-managed Claude Code and Codex sessions without restarting them. [Korean guide](skills/orca-plugin-refresh/SKILL.ko.md). |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Reads the staged and unstaged changes, or the scope you name, plus recent commit history, then suggests five commit messages that match the repo's style. When you ask it to commit, it commits with the single best subject instead. [Korean guide](skills/suggest-commit/SKILL.ko.md). |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Writes or reviews technical design documents and RFCs without taking ownership of implementation planning. [Korean guide](skills/technical-design-writer/SKILL.ko.md). |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Runs a turn-limited debate between the current agent and an opposing Claude/Codex session to surface and resolve issues. [Korean guide](skills/tiki-taka/SKILL.ko.md). |

## Related

- `omo-model-config` was removed; its last version is in the [`v1.3.0` tag](https://github.com/hei5enbug/hei5enbug-agent-setup/tree/v1.3.0/standalone-skills/omo-model-config).

## License

This repository is licensed under the Apache License 2.0. See [`LICENSE`](./LICENSE) for the full text.
