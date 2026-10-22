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
├── docs/
│   └── ko/
│       ├── AGENTS.ko.md
│       ├── README.ko.md
│       ├── agents/
│       ├── instructions/
│       └── skills/
├── hooks/hooks.json
├── hooks/mod/
├── config/claude-mod.json
├── config/model-registry.json
├── instructions/
│   ├── claude-agents.md
│   ├── codex-agents.md
│   ├── confluence.md
│   ├── cross-repository.md
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
│   ├── approve_wrapper.sh
│   ├── datagrip_guard.py
│   ├── hook_python.sh
│   ├── host_settings.py
│   ├── language_guard.py
│   ├── plugin_toggles.py
│   ├── role_runner.py
│   ├── session_context.py
│   └── verify_spawn.py
├── tests/
├── LICENSE
├── pyproject.toml
├── agents/
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
lists only these five English definitions, so the Korean mirrors in `docs/ko/` are not registered.

Codex discovers subagents only in `~/.codex/agents/` and `.codex/agents/`, so a plugin cannot register one.
Instead, the session hook copies `standalone-agents/codex-scout.toml`, `codex-worker.toml`,
`codex-designer.toml`, and `codex-reviewer.toml` to matching `~/.codex/agents/<role>.toml` files when absent. They
define four roles that also exist on Claude Code, with a fixed sandbox; no role file sets a reasoning effort, so each
spawn passes one. The Codex `reviewer` role has no model key; the skill instructions pass its model and
effort explicitly when it is the fallback. The plugin `worker` replaces the
built-in Codex `worker`, and `scout` leaves the built-in `explorer` untouched. A file you edited is never
overwritten, and the agents become available in the next Codex session. Because an edited copy never changes,
the files set no model; the Codex instructions pass the pinned model on every spawn instead, and the `worker` role
file sets no effort either, so the spawn passes the `codex_worker_model` and `codex_worker_effort` settings. A role
file you edited that pins another pair still wins, and the agent guard denies a mismatching spawn. The hook also
removes an `explorer.toml` and a `researcher.toml`, and replaces a `worker.toml`, `scout.toml`, `designer.toml`, or
`reviewer.toml`, that an earlier version wrote, but only while the file is
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
the built-in subagent block, role pinning, and the GPT refusal. The [Approval guard](#approval-guard) holds approvals
on both hosts. The mod was tested with Claude Code
2.1.292. When the mod does not load, such as on an older Claude Code, with `disableAllHooks`, or under a managed
policy, these guards are absent and the host's normal permission flow applies.

Role pinning pins each plugin role's model and effort on every request: `scout` uses `claude-sonnet-5-5` with `medium`,
`worker` uses `worker_model` with `worker_effort` (default `claude-haiku-5-5` with `high`), `sonnet-worker` uses `claude-sonnet-5-5` with `high`, `designer` uses
`claude-opus-5-5` with `xhigh`, and `reviewer` uses `claude-opus-5-5` with `high`. A subagent that answers on another model is stopped: its later requests
end with a refusal, its tool calls are denied, and its result is replaced with a warning. The session context then
gets the line `hei5enbug-agent-setup mod: role pinning active` from the registered mod `prompt.context` hook only when
role pinning is active. This line lets the main session send assignments directly and skip per-delegation settings and
subagent record checks.

### Response language

A language guard, `scripts/language_guard.py`, checks that every reply and every progress update is written in the
response language. Claude Code takes the language from the `language` setting, read from the local project settings,
then the project settings, then the user settings; without one, nothing is enforced. Codex reads
`HEI5ENBUG_RESPONSE_LANGUAGE` and uses Korean when it is unset. Only languages with a distinctive script are
checked: Korean, Japanese, Chinese, Russian, Ukrainian, Greek, Arabic, Hebrew, Thai, and Hindi. For any other
language, such as English or French, the instruction alone applies.

The check ignores code, quotes, and URLs. A text passes when at least 30% of its letters are in the target script,
and very short text always passes. A `Stop` hook asks for a rewrite when a reply fails, at most 3 times per turn.
Delegated child sessions are not checked: a session with `HEI5ENBUG_ASSIGNED_ROLE` or `HEI5ENBUG_PARENT_SESSION`
set, such as a role runner child, returns its answer to the coordinating session, which replies to the user.
A `PostToolUse` hook adds a reminder after a progress update in another language. It runs asynchronously, so the
reminder reaches the model on the next turn. Put text the user asks for in another language in a code block or block
quote.

### DataGrip query guard

A `PreToolUse` hook and a `PermissionRequest` hook, both `scripts/datagrip_guard.py`, run before the DataGrip MCP tool
`execute_sql_query`. The guard reads the connection from `.idea/dataSources.xml` in the DataGrip project that
`projectPath` names. PostgreSQL and SQL Server reads on non-production, recognized connections
run without approval, and PostgreSQL reads run inside a read-only transaction with
`SET LOCAL statement_timeout = '60s';`. A production connection needs a recorded plan before a PostgreSQL read and gets
lock safeguards on a SQL Server read; see the production read rules under [Approval guard](#approval-guard). With
`approval_guard` on, non-destructive PostgreSQL and SQL Server writes share the session write approval
(`write:session`) with all other writes. Unknown connections, other database types, and text the guard cannot parse
use that approval too; a `승인` in a connection name has no effect of its own.
A statement whose code names `delete`, `drop`, or `truncate`, and statements the SQL classifier treats as destructive,
including those led by `DO`, `EXEC`, `EXECUTE`, or `CALL`, ask every time. The code is the text left after string
literals, comments, and quoted or bracketed identifiers are removed, so a `SELECT` that only mentions `delete` in one of
them stays a read. On a non-production PostgreSQL connection (see "Production database reads"), when the `pglast`
parser confirms the text, a `DELETE` whose own statement has a `WHERE`, and a `DO` block whose body parses as
PL/pgSQL and has no `DROP`, `TRUNCATE`, `EXECUTE`, `ALTER`, `GRANT`, `REVOKE`, `CALL`, nested `DO`, `DELETE`
without `WHERE`, or risky function call (`set_config` and `pg_sleep` are allowed there, quoted names included in the
check), are session writes instead. SQL Server, which allows statements without semicolons, and text the parser
cannot confirm keep asking every time. SQL Server reads may also carry `SET NOCOUNT`, `LOCK_TIMEOUT`, `DEADLOCK_PRIORITY`, `TRANSACTION
ISOLATION LEVEL READ UNCOMMITTED|READ COMMITTED|SNAPSHOT`, `ARITHABORT`, `ANSI_NULLS`, `ANSI_WARNINGS`, `ANSI_PADDING`,
`QUOTED_IDENTIFIER`, `CONCAT_NULL_YIELDS_NULL`, `XACT_ABORT`, `STATISTICS IO|TIME`, and `SHOWPLAN_XML|ALL|TEXT`
statements.
On Codex, a write opens Codex's native approval window when it is ready, and is denied with a code otherwise;
an every-time query is always denied with a code; see [Approval guard](#approval-guard). With the toggle off, every
write asks as before. In Codex, trust the hook in `/hooks`.

Optionally, install the `pglast` parser once:

```bash
uv venv --python 3.12 "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser"
uv pip install --python "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser/bin/python" pglast==8.4
```

Without it, PostgreSQL falls back to a stricter text check that may ask more often but still never lets a write run
without approval.

### Approval guard

A `PreToolUse` hook runs `scripts/approval_guard.py` before Bash, MCP, Claude file tools (`Read`, `Edit`, `Write`,
`MultiEdit`, `NotebookEdit`), and Codex `apply_patch` calls. It also handles `PermissionRequest`, `PostToolUse`,
`PostToolUseFailure`, and `UserPromptSubmit`. Reads run without approval on both hosts. A call lands in one of three
tiers, or is denied or passed:

- **Read** runs without approval.
- **Session approval** asks once per session and then covers every later call of its kind until the session ends.
  There are two. `write:session` covers every write, whatever its command or target, including production changes,
  git pushes, MCP, DataGrip, and tabularis writes; unclassifiable calls are writes unless their text contains a
  destructive action. `sensitive:session` covers every sensitive read, meaning a call that may expose a protected
  value. Approving one never approves the other, and a call that needs both asks once for both.
- **Every time** asks on every call and keeps no approval, so the next run asks again. The list below holds these
  actions. Their Claude prompt starts with `Asks every time:`. When such a call also needs a session approval,
  approving it grants that approval too, and the prompt says so.
- **Request** asks for a bundle of session approvals before the actual calls.
- **Secret** is denied on both hosts because the command would print a secret value.
- **Forbidden** is denied on both hosts: running the guard scripts or editing the approval state (see the
  self-approval rules below).
- **Pass** is a call the guard does not cover, so the host's own permission flow decides.

The every-time list holds the actions that affect remote or production systems or destroy local data that cannot be
recovered, so one approval never covers the next run. Local actions that are disposable or recoverable are not on it;
the local-scope rules below describe them.

1. Destructive `git push`: force, force-with-lease, delete, mirror, or prune pushes, and `+` or `:` refspecs, except
   the lease-protected feature-branch push described in the local-scope rules.
2. Discarding uncommitted work: forced `git clean` without a dry run, `git stash drop` or `git stash clear`, and
   `git reset --hard`, forced checkout or checkout of `.`, or restore of `.` or `:/` on the worktree whenever the
   repository has an uncommitted change to a tracked file or its state cannot be read.
3. Recursive removal of a protected or external path, or with an unresolved target, except the recoverable work-tree
   removal described in the local-scope rules.
4. Destructive database statements through `psql`, `sqlcmd`, DataGrip, tabularis, or an MCP SQL field.
5. Remote infrastructure deletion: the destructive verbs of `kubectl`, `oc`, `helm`, `az`, `terraform`, `tofu`, `aws`,
   `gcloud`, and `gsutil`, such as `delete`, `drain`, `uninstall`, `destroy`, `purge`, and `terminate`; `--force` and
   `--prune` before a `--`; destructive commands inside `kubectl` or `oc` `exec`; and destructive `gh` calls.
6. Package publishing: `npm`, `pnpm`, `yarn`, `uv`, `poetry`, `cargo` `publish`, `twine upload`, and `gem push`.
7. Removal in `docker` and `podman` against a remote engine: `rm`, `rmi`, `prune`, `compose down -v`, and destructive
   commands inside `exec`; `curl` with a destructive method such as DELETE; and MCP tools or actions whose name has a
   delete word.
8. Codex runs without sandbox protection.
9. Calls the guard failed to classify, and unclassifiable calls whose text names a destructive action, including a
   script or the code input of an execution tool.

Local-scope rules keep disposable or recoverable local work off the every-time list:

- **Temporary roots** are `/tmp`, `/private/tmp`, `/var/folders`, `/private/var/folders`, `$TMPDIR`, `~/.cache`, and
  Claude Code job folders `~/.claude/jobs/<id>/tmp`. Recursive removal inside a temporary root passes. Redirections
  (`>`, `>>`, heredocs), `mkdir`, `touch`, `tee`, and the destination of `cp` or `mv` pass when every destination is
  inside a temporary root, resolved through symlinks; their sources may be anywhere, but `cp` or `mv` into an existing
  folder is judged by `<folder>/<source name>`, so a symlink there that leaves the roots, or a source name that
  cannot be known (a glob or variable), disqualifies it. When the whole command is made of such writes and a few
  harmless commands such as `cat`, `echo`, `ls`, and `cd`, Claude Code's own permission prompt is answered with allow
  without any session approval. A destination that is not provably inside a temporary root, such as `./README.md`,
  keeps its normal flow. Scripts that write there are still writes.
- **Recoverable work-tree removal**: a recursive `rm` is a session write, described as "Recursive removal of tracked
  files" or "Recursive removal of ignored files", when every target lies inside the Git work tree that holds the
  command's folder and Git reports each as tracked with no staged, unstaged, or untracked change under it, or as
  untracked and ignored (`git check-ignore`). Git runs with untracked-file reporting and ignore settings forced on the
  command line, so repository configuration cannot hide a file. The work-tree root, `.git`, a symbolic link, a path that
  does not exist, an `assume-unchanged` or `skip-worktree` entry,
  untracked files that Git does not ignore, a command earlier in the same text that may change files (a loop header
  counts, a plain `[ ... ]` test does not), a Git variable that could redirect the repository, and any Git failure or
  timeout keep asking every time.
- **Local container engine**: `docker` and `podman` removal and pruning (`rm`, `rmi`, `container`, `image`, `volume`,
  `network` `rm` or `prune`, `system prune`, `compose down` with or without `-v`) and `exec` commands that remove files
  are session writes when the engine is local. An engine is remote when a `--host`, `-H`, `--remote`, `-r`, `--url`,
  `--connection`, or `--identity` option comes before the subcommand (in any spelling, such as `-Htcp://h` or
  `--remote=true`), when `CONTAINER_HOST` or `CONTAINER_CONNECTION` is set, or when `DOCKER_HOST` is anything but a
  `unix://` socket, a path, or a bare `localhost`, `127.0.0.1`, or `::1` host. A named Docker context (`--context` or
  `-c`, else `DOCKER_CONTEXT`, else `currentContext` in the Docker config from `--config`, `DOCKER_CONFIG`, or
  `~/.docker/config.json`) is local only when `<config dir>/contexts/meta/<sha256 of the name>/meta.json` has an
  `Endpoints.docker.Host` starting with `unix://` or `npipe://`, so Docker Desktop's `desktop-linux` counts as local. A
  missing, unreadable, or malformed meta file, no host, or another scheme such as `tcp://` or `ssh://` is remote. The
  `default` context is local. For podman, a `containers.conf` (`CONTAINERS_CONF`, the user and system files and their
  `.d` folders) that sets `active_service` or `remote = true`, or a saved system connection default, is remote, and so
  is an unreadable one. Remote engines keep asking every time. A function,
  variable, `eval`, or `sh -c` text whose only destructive words are local `docker` or `podman` removal is a session
  write too.
- **Lease-protected push**: `git push` is a session write, not every time, when its only force-like flags are
  `--force-with-lease` (bare, `=<ref>`, or `=<ref>:<expect>`) and `--force-if-includes`, the remote is named explicitly
  and is not `upstream` (a URL, a path, or a remote git cannot read keeps every time), and every destination branch is
  explicit and not `main`, `master`, `develop`, `trunk`, or the remote's HEAD branch when
  `git symbolic-ref refs/remotes/<remote>/HEAD` can be read. The destination comes from `src:dst`, `dst`, or the lease
  ref; `HEAD`, `@`, an empty or implicit destination, a glob, or a `refs/` name other than `refs/heads/` keeps every
  time. `--force`, `-f`, `--delete`, `-d`, `--mirror`, `--prune`, `--all`, `--tags`, a `+` or `:dst` refspec, an unknown
  option, a global option other than `-C`, a redirecting `GIT_*` variable, and `exec` inside a container also keep every
  time. Example: `git push --force-with-lease origin feature/ABC-1` is a session write while
  `git push --force-with-lease origin main` asks every time.
- **Clean tracked tree**: `git reset --hard`, `git checkout -f`, `git checkout .`, and `git restore .` are session
  writes when `git status --porcelain --untracked-files=no` in the repository (`-C` is followed) prints nothing within
  3 seconds. These keep them every time: an error or timeout; any global option except `-C` and the harmless
  `--no-pager`, `-P`, `--no-optional-locks`, `--paginate`, and `-p` (so `-c`, `--config-env`, `--git-dir`,
  `--work-tree`, `--namespace`, and `--bare` all count); and any `GIT_*` variable except `GIT_EDITOR`,
  `GIT_SEQUENCE_EDITOR`, `GIT_PAGER`, `GIT_TERMINAL_PROMPT`, `GIT_ASKPASS`, `GIT_SSH`, `GIT_SSH_COMMAND`, `GIT_TRACE*`,
  `GIT_PROGRESS_DELAY`, `GIT_FLUSH`, and `GIT_MERGE_AUTOEDIT`. So does a command
  inside `kubectl`/`oc`/`docker`/`podman` `exec`, and so does any earlier segment in the same command that is not a
  plain read without file output (`printf x >> a; git reset --hard` asks every time).

A call that needs approval shows one line in the response language, at most 100 characters. Claude Code takes the
language from the `language` setting and uses English without one. Codex uses `HEI5ENBUG_LANGUAGE`, else the response
language guard's `HEI5ENBUG_RESPONSE_LANGUAGE`, whose default is Korean. A
description that does not fit is shortened but keeps at least 20 characters. A compound call keeps every description,
each cut to 40 characters, and its line has no length limit. Claude shows these lines:

| Prompt | Korean | English |
|---|---|---|
| Write | `쓰기 승인: kubectl apply on (default) dev/web. 한 번 승인하면 이 세션의 쓰기는 더 묻지 않습니다.` | `Write: kubectl apply on (default) dev/web. Approve once; later writes in this session will not ask.` |
| Every time | `매번 승인: git push --force (origin main).` | `Asks every time: git push --force (origin main).` |
| Sensitive read | `민감 조회 승인: cat .env (값이 노출될 수 있음). 한 번 승인하면 이 세션의 민감 조회는 더 묻지 않습니다.` | `Sensitive read: cat .env (may show a value). Later ones in this session won't ask.` |

A line for a call that also grants another session approval ends with a short note naming it, such as "Also approves
writes for this session." A request shows its `--why` text as the description.

| CLI | Read | Secret (denied) | Sensitive (session) | Every time | Target in the prompt |
|---|---|---|---|---|---|
| `kubectl`, `oc` | `get`, `describe`, `logs`, `diff`, `config view`, `config get-contexts`, `config current-context`, any call with `--dry-run=client` or `--dry-run=server` | `get secret` with an output format that prints values (a `jsonpath` or `custom-columns` template that reads only names, namespaces, UIDs, labels, owner references, finalizers, timestamps, resource versions, `type`, `kind`, `apiVersion`, or `immutable` is a read; `annotations` stay secret because they can hold the last applied manifest), `get --raw` on a `secrets` path, `config view --raw`, `create token` | `exec ... env` or `printenv` | `delete`, `drain`, `--force` or `--prune` before a `--`, destructive commands inside `exec` | kubeconfig, then context / namespace |
| `helm` | `list`, `status`, `get notes`, `repo list` | none | `get all`, `get manifest`, `get values` | `uninstall` | kubeconfig, then context / namespace |
| `az` | `list`, `show`, `exists`, `query`, `query-*`, `version`; `rest` GET without `--resource` on `https://management.azure.com` or an unresolved variable URL | `keyvault secret show` and `download`, `list-keys`, `account get-access-token`, `rest` GET on a Key Vault `/secrets` or `/keys` URL | none | `delete`, `purge`, `rest` DELETE | subscription / resource group |
| `terraform`, `tofu` | `plan`, `show`, `validate`, `state list`, `fmt -check`, `output` without `-json` or `-raw` | none | `state show`, `state pull`, `output -json`, `output -raw` | `destroy`, `apply -destroy`, `state rm` | directory : workspace |
| `aws` | `describe-*`, `list-*`, `get-*` other than secret reads, `s3 ls` | `secretsmanager get-secret-value` and `batch-get-secret-value`, `ssm get-parameter*` with `--with-decryption`, `kms decrypt` | none | `delete-*`, `terminate-*`, `s3 rm`, `s3 sync --delete` | profile / region |
| `gcloud`, `gsutil` | the first verb in the command path is `list`, `describe`, `get-*`, `ls`, or `cat` | `secrets versions access`, `auth print-access-token` | none | `delete`, `gsutil rm`, `gsutil rb` | project |
| `docker`, `podman` | `ps`, `images`, `logs`, `<object> ls` | none | `inspect`, `exec ... env` or `printenv` | against a remote engine: `rm`, `rmi`, `prune`, `compose down -v`, destructive commands inside `exec` (local engine: session write) | context |
| `psql`, `sqlcmd` | a query that is a read; covered `psql` reads run with `default_transaction_read_only=on` and `statement_timeout=60000` | none | none | destructive SQL, including text that names `delete`, `drop`, or `truncate`, and statements led by `DO`, `EXEC`, `EXECUTE`, or `CALL` | host / database |
| `curl` | GET/HEAD without data, form, upload, or JSON flags | none | credentials in argv (`-u`, `--user`, an `Authorization` header) | destructive methods such as DELETE | method / scheme and host |
| `kustomize` | every call | none | none | none | none |
| `mysql`, `mongosh`, `redis-cli` | none; explicit local hosts pass | none | none | unclassified text containing a destructive action | none |
| `git` | `status`, `show`, `log`, `diff`, `ls-remote`, `ls-tree`, `ls-files`, `cat-file`, `rev-list`, `show-ref`, `for-each-ref`, `merge-base`, `blame`, `shortlog`, `diff-tree`, `describe`, `rev-parse`, tag listing and verification | none | none | force, delete, mirror, or prune pushes (a lease-protected push to a feature branch is a session write); forced `clean` without a dry run; `stash drop` and `stash clear`; `reset --hard`, forced checkout or checkout of `.`, and restore of `.` or `:/` except index-only restore, unless the tracked tree is clean (then a session write) | command |
| `gh` | read verbs such as `view`, `list`, `ls`, `status`, `checks`, `diff`, `search`, `watch`, `browse`; `auth status`, `config get`/`list`, version/help, `api` GET and inline GraphQL queries | `auth token` | none | `delete` in any area, `api` DELETE | command |

Other covered non-destructive CLI operations use the session write approval. That includes a local
`kubectl`/`oc config` change such as `use-context` or `delete-context`, `helm repo remove`, and deleting or forcing a
local git tag. Files, stdin, and interactive use of remote SQL clients are unclassified writes unless destructive
text puts them on the every-time list. Explicit local hosts
(`localhost`, `127.0.0.1`, `::1`, or a socket path) pass for `psql`, `mysql`, `redis-cli`, and `mongosh`.
`gh api` data flags and `--input` imply a write unless an explicit GET overrides them. An inline GraphQL field is a
read only when, after removing `#` comments and leading whitespace, it starts with `query` or `{` and contains no
`mutation` word. Mutations and query files are writes. Unknown `gh` actions are writes; `gh pr checkout` and
`gh repo clone` pass to the host. Git tag creation and pushes, and `gh` writes such as release creation, editing,
and uploads, use the same approval on both hosts.

Package publishing (`npm`, `pnpm`, `yarn`, `uv`, `poetry`, `cargo`, `twine upload`, and `gem push`) asks every time,
including when options precede the publishing subcommand.
Recursive `rm` asks every time for protected or external paths, including the session folder, its ancestors, the home
folder, `/`, `.git` and its contents, and unresolved targets. Removal within the session folder or a temporary root
(see the local-scope rules) otherwise passes. A target that is exactly a `$(mktemp -d ...)` or backtick substitution,
or starts with `${TMPDIR:-<default>}`, is first resolved to a temporary root (`TMPDIR` when set, else the default) and
then checked like any other path, so those checks still block the home folder, the session folder, and `.git`.
A variable assigned earlier in the same command text resolves when its value is one static word (a literal, `~`,
`$HOME`, `$TMPDIR`, `${TMPDIR:-<default>}`, or another resolved variable), including assignments inside `if`, `case`,
`{ }`, and `( )` bodies that every path through the text reaches, and the words of a `for` loop. The removal is checked
against every possible value and the strictest result wins. An assignment that runs only when an earlier command in a
`&&` or `||` list succeeds or fails is conditional: a later command in that list sees only the new value when every
link before it is `&&`, and after any `||`, like everything after the list (`;`, a newline, or `&`), it sees the new
value together with the value from before, which is the empty string for a variable the environment does not provide.
An unquoted reference splits on whitespace, so each word of its value is checked as a separate target.
An unquoted operand that expands to nothing is dropped
and a quoted empty operand removes nothing, but an empty value that turns the target into a path outside the session
folder and the temporary roots, such as `$D/y` becoming `/y`, still asks. A later `cd` changes only relative
targets. Command substitution,
backticks, `read`, arithmetic, unknown variables, `set --`, `shift`, and values assigned on only some paths stay
unresolved and ask every time. When the guard reads a shell script that a command runs, it judges the script as one
text, so a variable assigned on one line resolves on the next. In that script `$0`, the folder idioms
`$(dirname "$0")`, `$(cd "$(dirname "$0")" && pwd)`, `${BASH_SOURCE[0]%/*}`, and `$1` to `$9` resolve to the script's
path, its folder, and the call's literal arguments, with each possible value when an argument is a loop variable.
The script path is the one the command used, made absolute without resolving symbolic links, as the shell sees it.
Commands inside `kubectl`/`oc`/`docker`/`podman` `exec` also use the normal classifier: destructive commands ask every
time (file removal inside a local `docker` or `podman` container is a session write), secret output is denied, and
other `exec` calls are writes.
Any `codex` invocation with sandbox bypass flags or `danger-full-access`, including a configuration override,
asks every time. Worker access outside the session folder through `codex exec` (or `e`) with `--add-dir` or
`-C`/`--cd` before or after the subcommand, or through `role_runner.py --add-dir`, is a write.

A write is described by `<cli>:<subcommand>@<target>`, where the subcommand is the words before the first flag. The
prompt shows it as `<cli> <subcommand> on <target>`, and one `write:session` approval covers every such write.
For `kubectl`, `oc`, and `helm`, the target is the kubeconfig (`--kubeconfig`, then `KUBECONFIG`, else `(default)`)
followed by the context and namespace; a context that is not given is read through the same kubeconfig. Any other
parseable subcommand
is a write, so `kubectl apply` and `helm upgrade` ask only until the first write is approved for the session. The body
of a `$(...)` or backtick substitution is classified like a command of its own and merged into the call. A substitution
whose command verb is an unexpanded variable is an unclassified write unless it contains a destructive action.
Commands inside `eval`, `xargs`, or `sh -c` with any flag cluster that contains `c` are classified too.
When a region itself prints a secret, the whole command is denied. A heredoc on a covered command is an unclassified
write unless it contains a destructive action. A heredoc body is data and is not scanned when its command is `cat`,
`tee`, `echo`, `printf`, `head`, `tail`, `wc`, `sort`, `uniq`, `cut`, `tr`, `base64`, `xxd`, `od`, `grep`, `egrep`,
`fgrep`, `rg`, `jq`,
`column`, `fold`, `fmt`, `nl`, `tac`, `rev`, `cmp`, `diff`, `git`, or `gh`, its output is not piped onward, and every
file it writes is not later run by `bash`, `sh`, `zsh`, or `source` in the same command text. File suffixes do not
change that rule. Other receivers keep the body scanned. Only the substitutions that an
unquoted delimiter lets the shell run are still classified. A segment whose program word comes from a substitution or
an unexpanded variable and that names a covered CLI is unclassified. A `command -v` lookup runs nothing and is not
classified.

A compound command is judged as a whole. A secret segment denies it. When any segment is on the every-time list, the
call asks every time, and approving it also grants the session approvals that its other segments need. Otherwise any
write makes the whole command a write, even with an unverified segment or file output. A covered read
stays a read only when every other segment is a filter such as `grep`, `head`, or `jq`, and output redirections go
only to `/dev/null` or `2>&1`. Wrappers such as `sudo`, `env`, `nice`, and `time` are skipped, with their options,
before the executable is read. Targets for write and every-time calls come from flags or the environment. When neither
is set, `kubectl config current-context` and `az account show` run for those calls only, with a 3-second limit.

A `psql` read is rewritten to run in a subshell with `PGOPTIONS` extended by
`-c default_transaction_read_only=on -c statement_timeout=60000`, so the server refuses writes even when the guard's
read check misses
a function call, and the option never reaches later commands.

The guard reads shell files invoked by `bash`, `sh`, `zsh`, `./`, `source`, or `.`, Python files,
Makefile recipes for the selected/default target and one level of prerequisites, and the script text in
`package.json` for `npm`, `pnpm`, or `yarn run <name>`. Files resolve from the event's `cwd` and are limited to 256 KiB.
Plain `NAME=value` statements earlier in the same command text, separated by `;`, `&&`, or newlines, are substituted
into later simple commands, including the body of a `for ... do ... done` loop, with sh word splitting for unquoted
expansions. This holds only when the value is one static word with no command substitution (a `$(mktemp -d ...)`
resolves like a removal target), and the assignment is unconditional: not `export`, not inside parentheses, a block, a
function, a brace group, a pipe, or the background, and not after `||` or `&&` unless the left side is only assignments.
An assignment inside such a context makes the name unknown afterwards. `read`, `export`, `for NAME in`, and similar
commands drop the substitution.
`xargs` followed by a simple command is classified as that command with its input as one unknown operand and the
segment's own assignments (`DOCKER_HOST=ssh://h xargs docker rm` asks every time). A read, or a file reader such as
`cat` or `grep`, becomes a sensitive read because the unknown operand could name a protected file, and `xargs rm -rf`
asks every time; a shell, `eval`, a nested `xargs`, an unknown option, or a
placeholder in the command name keeps the old opaque handling.
A `cd <dir>` moves that base for the later segments only when it runs unconditionally in the current shell: outside
parentheses, after nothing or `;`, and before nothing, `;`, or `&&`. `$NAME` or `${NAME}` that an earlier standalone
assignment set is expanded in the path; a prefix assignment (`NAME=value cmd`) never expands its own command's
arguments. An unassigned variable leaves the script unreadable, so it is unclassified.
Shell lines and Makefile recipes use the CLI classifier. A Python script file or `python3 -` heredoc whose syntax tree
is provably read-only is a read: it imports only listed standard modules, calls no process, network, environment,
dynamic-execution, or file-mutating function (including `replace`, `remove`, `touch`, and `mkdir` names), opens files
only in a literal read mode (every name bound to an `open` function is checked, so `from io import open as f` gets no
exemption), and names no credential-like path or word. Anything the check cannot decide keeps the old result, and a
protected file passed as an argument, or as the value of an option (`--file=.env`), does too. Inline code is
classified, never the heredoc, whichever way `-c` is spelled (`-c code`, `-ccode`, `-Ic code`). Python inline code,
heredocs, stdin files, and script files
are writes when they run a process or import a cloud/database SDK. Literal process commands, including keyword
arguments, are classified. Destructive process commands, SDK call names, or destructive text in Python that runs a
process or imports an SDK ask every time. Other Python passes, even when its strings name CLI
commands (`python3 -c` code never becomes a read); an explicit `--execute` still makes it a write. Node and other
non-shell, non-Python executables pass.
Reads need no approval; writes need the session write approval; destructive, forced, and secret calls keep their normal
rules. Unreadable or larger script files are unclassified. An inspected shell script naming a covered CLI or importing
`boto3`, `azure`, `kubernetes`, `psycopg`, `psycopg2`, `pymysql`, `sqlalchemy`, `pymongo`, `redis`, or `google.cloud`
without a classifiable call is unclassified too. These calls are writes unless their text contains a destructive
action, which asks every time. A script that names none of these passes. The plugin's own
`python3 <plugin root>/scripts/host_settings.py check` is a read, and `apply` is a session write, when the script
belongs to this guard's plugin root and no interpreter options precede it.

MCP tool names split at `_`, `-`, and camelCase. Destructive name words ask every time. String fields `sql`,
`statement`, and `queryText`, and a `query` field whose text starts like a SQL statement (a search phrase does not), use
the DataGrip SQL classifiers: reads run freely, destructive statements ask every time,
and other SQL is a session write. Execution name words (`repl`, `exec`, `execute`, `eval`, `run`, `code`, `script`,
`command`) classify their code input like a command or a Python script, by its `language` field or its look: a secret
or forbidden result is denied as usual, a result that asks every time asks every time, and anything else, including a
tool without code, is a session write. An explicit
`action` input overrides ordinary name verbs: a destructive action asks every time, and destructive SQL fields
take precedence over other actions. Without SQL, a read action is a read and a write action is a write. Without that
input, a name starting with a read verb is a read even if a later word names a write, and a name written as one
lowercase run, such as `getjiraissue`, is a read when a read verb leads and no write or delete word follows;
otherwise a write word takes precedence over read words. Names with no known verb are writes. The
session write approval covers every non-destructive MCP write for that session, including DataGrip and tabularis writes.

For `mcp__tabularis__run_query`, `connection_id` resolves an ID or name from tabularis' `connections.json`.
The config directory is `~/Library/Application Support/tabularis` on macOS, `$XDG_CONFIG_HOME/tabularis` or
`~/.config/tabularis` on Linux, and `%APPDATA%\tabularis` on Windows. `HEI5ENBUG_TABULARIS_DIR` overrides it for tests.
The guard extracts only `id`, `name`, and `params.driver`; it never prints other connection fields or passwords.
`postgresql` uses the PostgreSQL classifiers; `sqlserver` and `sqlserver-entra` use the SQL Server classifiers.
Reads on non-production connections run without approval; non-destructive writes are session writes. Another driver,
an unknown connection, an unreadable file, or unparseable query text uses the session write approval.
`delete`, `drop`, or `truncate` in the code (not in literals, comments, or quoted identifiers) and statements the SQL
classifier treats as destructive, including those led by `DO`, `EXEC`, `EXECUTE`, or `CALL`, ask every time, except
the targeted `DELETE` and safe `DO` on non-production PostgreSQL connections described above, which are session
writes. Those
queries use `sql:always:tabularis:<id>:<digest>` keys. Other tabularis tools keep the name rules.

**Production database reads.** For `run_query` and DataGrip `execute_sql_query`, a connection is non-production when
its name, split at case changes, spaces, `_`, `-`, `.`, and brackets, has a word `dev`, `develop`, `development`,
`test`, `testing`, `qa`, `stg`, `stage`, `staging`, `sandbox`, `local`, or `demo`, or contains `개발`, `테스트`,
`스테이징`, `검증`, or `로컬`, and has no word `prod`, `production`, `prd`, or `live` and no `운영`. Every other
connection is production, including unknown ones and names with `승인`.
- A PostgreSQL `EXPLAIN [(options)] <read>` without `ANALYZE` is a read on any connection. After one succeeds on a
  production connection, the `PostToolUse` hook records the estimated cost and rows (JSON `Plan` `Total Cost` and
  `Plan Rows`, or the first text plan line) per host, session, tool, connection, and exact read text (only leading and
  trailing whitespace and trailing semicolons removed) in a state file for 30 minutes. Errors and unparseable results
  record nothing.
- A PostgreSQL production read with such a record at or under both limits runs; without one, it is denied with the
  exact `EXPLAIN (FORMAT JSON) <read>` to run first; over a limit, or with an unparseable record, it asks every time.
- A SQL Server production read runs without a plan (neither tool can return an estimated plan there) with the prefix
  `SET LOCK_TIMEOUT 5000;` and `SET DEADLOCK_PRIORITY LOW;` always placed first. A read that sets `LOCK_TIMEOUT` outside
  0 to the limit, or `DEADLOCK_PRIORITY` to anything but `LOW` or an integer of -5 or lower, asks every time. tabularis
  `limit` becomes the smaller of the request (default 100) and the maximum result rows.
- Limits default to `postgres_max_cost` 10000, `max_estimated_rows` 100000, `max_result_rows` 1000, and
  `sqlserver_lock_timeout_ms` 5000. `$XDG_CONFIG_HOME/hei5enbug-agent-setup/db-read-limits.json` (default `~/.config`)
  may hold `{"default": {...}, "connections": {"<connection name or id>": {...}}}`; a connection entry overrides the
  default per key, and unknown keys, non-positive or non-numeric values, and an invalid file are ignored. Changing that
  file or its folder through an edit tool or a shell command asks every time, also with quoted or escaped names and,
  from inside that folder, for a write whose target the guard cannot resolve. A path assembled from an unresolvable
  value elsewhere is not detected.
- With `approval_guard` off nothing is recorded, so reads are not gated.

`curl` without a request method other than GET/HEAD and without `-d`, `--data*`, `-F`, `--form`, `-T`,
`--upload-file`, or `--json` is a read. Otherwise it is a write shown as `curl <METHOD> on <scheme://host>`; destructive
methods such as DELETE ask every time. `-u`/`--user` or an `Authorization` header in argv adds a sensitive read
approval to the method's own outcome: a read needs `sensitive:session`, a write needs both `write:session` and
`sensitive:session`, and a destructive method still asks every time. A description that a prompt shows or the pending
state stores masks `-u`/`--user` values, `Authorization`, `Cookie`, and `X-Api-Key` header values, URL user information,
and `key=value` or `--key value` pairs whose key names a secret.

Claude `Read` and Bash reads (`cat`, `less`, `head`, `tail`, `grep`, `rg`) of `~/.kube/config`, any `KUBECONFIG` path,
`~/.aws/credentials`, `~/.aws/config`, `~/.azure/**`, `~/.config/gcloud/**`, `~/.pgpass`, `~/.docker/config.json`,
`~/.netrc`, or `.env*` files are sensitive, except templates whose names end in `.example`, `.sample`, `.template`,
or `.dist`. So are unfiltered `printenv`, `env` without a command,
`kubectl exec ... env|printenv`, `docker inspect`, `docker exec ... env`, `terraform` state and JSON or raw output, and
`helm get all`, `get manifest`, and `get values`. The first sensitive read of a session asks once; after that, every
sensitive read runs for the rest of the session. The secret denial stays: a command that would print a secret value is
denied even after the approval.
`printenv` with only non-secret variable names is a read. Supported `grep`/`rg` filters on `env` or `printenv` are
reads when no matched name is secret; count-only output is also a read. So is a pipe that keeps only the variable
names or hides the values: `cut -d= -f1`, `awk -F= '{print $1}'`, `grep -o` with a pattern anchored to the name,
`grep -c`, and a `sed` substitution that replaces everything after the first `=`. Filters that cannot be checked stay
sensitive.
A supported filter keeps its verdict inside a command list, and the guard aggregates it with the other elements as
usual, unless the list can change the environment first, such as with `export`, an assignment, `source`, or `eval`.
`python3 <plugin root>/skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py status ...` is a read when the
resolved script belongs to this guard's plugin root and no interpreter options precede it.

On Claude Code, a call that needs approval gets a `PreToolUse` `ask` with the one-line reason above, and a call the
session already approved gets `allow`. The guard also answers the host's own `PermissionRequest` prompts, so one
session write approval absorbs them:

- An edit tool (`Edit`, `Write`, `MultiEdit`, `NotebookEdit`) on a path inside the project folder (`CLAUDE_PROJECT_DIR`,
  else the working directory) or inside `permissions.additionalDirectories` from the local project, project, or user
  settings is allowed. Paths that hold a `$`, the guard's state folders, protected paths such as `.env*` and credential
  files, the host's protected folders and files (`.git`, `.claude`, `.vscode`, `.idea`, `.husky`, shell startup files,
  `.gitconfig`, `.gitmodules`, `.mcp.json`, `.claude.json`, `.ripgreprc`) anywhere in the absolute path, even inside an
  allowed folder that is itself one of them, and anything outside those folders are left to the host.
- A Bash command the guard does not cover is allowed too, except one that runs `ssh`, `scp`, `rsync`, `sudo`, `su`, or
  `doas`, removes recursively, force-pushes, writes with `dd of=`, runs `mkfs`, or names a destructive action. Calls
  that the guard classified and the session already approved are allowed as well. Reads, every-time calls, and
  anything else get no decision, so the host decides.
- Before the session write approval exists, the first such edit shows the host's native prompt. The guard notes that
  request, and when the edit completes it records `write:session`. So the first edit approved in the native prompt
  grants the write approval, and a later `kubectl apply` does not ask again. When the request budget described below is
  used up, the edit prompt is denied with the stop message instead of shown again.

Limitation: in auto mode the host's classifier can still deny a call that the guard allowed, and the plugin does not
override that denial. A `PermissionDenied` hook could not reverse it either, because its `retry` only tells the model
it may try again.

On Codex, `PreToolUse` cannot ask, so the native approval window carries the approval when it is ready:

- For a Bash call that needs approval, `PreToolUse` allows it with the command rewritten to
  `<plugin root>/scripts/approve_wrapper.sh '<original command>'`. The wrapper is a two-line script that runs
  `bash -c` on its one argument. The plugin-owned rules file `~/.codex/rules/hei5enbug.rules` holds one `prefix_rule`
  with `decision="prompt"` for the wrapper's path, so Codex shows its approval window with the original command. The
  guard unwraps the wrapper before it classifies, so the verdict is the one for the original command, and a wrapper
  call with a destructive inner command still asks every time. `sh`, `bash`, or `zsh` running the wrapper with one plain
  word, alone or behind wrappers such as `env`, `command`, `exec`, or `nohup`, is classified by that word's text. Any
  other
  command that names the wrapper path, such as one with another argument count, `source`, a substitution, or `xargs`,
  asks every time as "Unrecognized approval wrapper call", and the wrapper's own file is never classified.
- For an MCP call, `default_tools_approval_mode = "prompt"` on the server makes Codex show the window. Reads are not
  wrapped, and `PermissionRequest` answers them with `allow`, which skips the window. DataGrip queries follow the
  same path through `datagrip_guard.py`. Only calls that ask once per session use the window; every-time MCP and
  DataGrip calls, such as destructive tools and queries, keep the code flow even when the window is ready. The window's
  mode comes from `config.toml`, so a session started with a command-line override that moves an MCP server away from
  `prompt` can run that server's non-destructive writes without approval. `apply_patch` edits stay with Codex.
- `PermissionRequest` skips the window once the session holds the approval the call needs. Otherwise it notes what the
  window would grant. Codex runs the call only after the user chose to proceed, so when it completes, `PostToolUse` or
  `PostToolUseFailure` records `write:session` or `sensitive:session`. An every-time Bash call asks in the window every
  time and leaves no approval. A user who declines leaves no approval either.

The native window needs all of these: the hook event reports permission mode `default`, the session is not a role
runner child, the session has a usable ID, `rules/hei5enbug.rules` holds exactly the text this plugin version writes,
and an MCP tool's approval mode in `~/.codex/config.toml` is `prompt`. Otherwise the code flow below applies. That
covers sessions that cannot show a window, such as `codex exec` and bypass-permissions runs, child workers, and the
time before [Host settings](#host-settings) wrote the rules file or the MCP mode. A Codex hook that is not trusted
runs no guard at all, so no flow applies; see the trust warning below.

Prepare a bundle before running writes:

```bash
python3 <plugin root>/scripts/approval_guard.py request --key write:session --why 'Deploy the requested change and update the issue'
```

`--key` takes `write:session` or `sensitive:session`, and may repeat. Claude asks showing the reason, then records the
session keys only when that asked call reaches `PostToolUse` or `PostToolUseFailure`. A failed approved write still
grants the session approval. A call allowed by an existing approval does not grant it again. Codex denies with one code
for the bundle and records it when the user types `승인 <CODE>`, or `승인` alone if only one request is pending.
The command prints the keys and exits 0; it never writes approval state itself. The older `<cli>:<kind>@<target>`
and `mcp:session` forms are still accepted and approve the same session write approval. Destructive or forced kinds,
`sql:always:*`, and destructive `mcp:<tool>` keys cannot be pre-approved, so no every-time action can be requested.
Explicit `unclassified` request-key forms are rejected too; the session write approval still covers non-destructive
unclassified calls.

When the code flow applies on Codex, a call that needs approval is denied with a code on two lines. In English:

```text
Approval required: kubectl apply on (default) dev/web. Approving also covers later writes in this session. Ask the user to reply `approve K7M2QX` (or just `approve` when only one is pending).
After the user replies with the code, retry this exact call immediately and continue the task without asking again.
```

In Korean, the first line reads as follows, and the second line stays the same:

```text
승인 필요: kubectl apply on (default) dev/web. 승인하면 이 세션의 쓰기도 더 묻지 않습니다. 사용자에게 `승인 K7M2QX` 입력을 요청하세요(대기 요청이 하나면 `승인`만).
```

The user types `승인 <CODE>` or `approve <CODE>` in chat. `승인` or `approve` alone works only when exactly one request
is pending. A `UserPromptSubmit` hook records the approval, and the agent
immediately retries the exact call and continues the task without asking again. Both hosts add the approved
descriptions and that retry instruction to `UserPromptSubmit` context. A code covers every key of the denied call: its
every-time keys as one-time approvals and its session keys as session approvals. Session approvals last until the
session ends; the state of a session idle for seven days is removed.
If a Codex one-time approval is in flight without `PostToolUse` or `PostToolUseFailure`, the next attempt for the
same key may reuse it once without a new code. The approval moves to that retry; another interruption needs a new
approval request. `PermissionRequest` allows only the call holding the approval, and `PostToolUse` or
`PostToolUseFailure` releases it.

Each session counts issued approval requests per key until a call completes or the user sends a new prompt. Claude
asks, Codex native windows, and Codex code responses count, including repeating a pending code. After three
requests without `PostToolUse` or `PostToolUseFailure` since the user's last prompt, a fourth request is denied. In
English the message is: “This approval was requested three times since the user's last message without the call
completing (declines included); stop retrying and tell the user.” An approval already given is honored, including a
retry approved by the third code. `PostToolUse` or `PostToolUseFailure` resets the count for the finished call's
keys, and `UserPromptSubmit` resets every count, so a write the user asks for after a stop is asked again. Already
approved session keys do not use another key's request budget.

The agent cannot approve anything itself. A Bash command that runs `approval_guard.py`, `datagrip_guard.py`, or
`approval_state.py` as a program, with `-m`, or through Python code that imports it, is denied on both hosts.
Commands naming the approval or heartbeat state directory are denied unless every simple command is an allowed read:
`ls`, `cat`, `head`, `tail`, `grep`, `wc`, `stat`, `file`, `find`, or `echo`. `find` may use only read options such
as `-type`, `-name`, `-maxdepth`, or `-print`, and no glob characters. The command must have no braces,
substitutions, assignment prefixes, or output redirection except to `/dev/null`. The only variables allowed are
`$HOME`, `${HOME}`, `$XDG_STATE_HOME`, `${XDG_STATE_HOME}`, and `${XDG_STATE_HOME:-<absolute path>}`, and each must
start a word as a path prefix followed by `/`, as in `ls "$HOME/.local/state/hei5enbug-agent-setup/approvals"`. The
guard expands them before it checks the path. Any other `$`, `$(`, backtick, `<(`, `>(`, or brace is denied, and the
denial names the trigger, for example `It was denied because of "$(".`
Plain reads of guard files, such as `cat` or `rg`, are not denied. The validated `request` command above is the only
execution exception. File edits inside either state directory, including paths named in an `apply_patch` patch,
are denied on both hosts.

Commands that need a secret value use the secret helper: `python3 <plugin root>/scripts/secret_exec.py --secret
DB_PASSWORD=k8s:<context>/<namespace>/<secret>/<key> -- <command>`. The sources are `k8s:`, `keyvault:<vault>/<name>`,
`aws:<secret id>[#<json key>]`, and `gcp:<project>/<name>[/<version>]`. `--file VAR=<source>` passes the path of a
temporary file instead of the value. The value reaches the command only through environment variables or temporary
files, and the helper masks it in the command's output. When a fetch fails, the helper prints only the source and the
fetch command's exit code, never the fetch's stderr. Each fetch has a 30-second timeout; a timeout exits 2 and
names the source with `timed out`.

A role runner child with `HEI5ENBUG_PARENT_SESSION=<host>:<session_id>` also reads the parent's approved keys without
changing its state. Malformed values are ignored. Children cannot record codes from `UserPromptSubmit` or run
`request`; a call that needs a session approval the parent lacks is denied with instructions to request it in the main
session (`request --key write:session` or `--key sensitive:session`) and retry. Children use the parent's
`write:session` and `sensitive:session` approvals while the parent session holds them, and Codex children never use
the native window. Every every-time action in a child is denied; the main session runs it itself. Claude children
that may edit receive `Bash` in both `--tools` and `--allowedTools`; their guard still denies unapproved writes and
every-time actions.

Do not add Claude `permissions.ask` rules for covered writes: they prompt every time even after a session approval.
Claude `defaultMode: dontAsk` denies approvals the guard asks for. Codex `rules/*.rules` files of your own that
`prompt` or forbid reads the guard allows, such as `kubectl get`, still apply. [Host settings](#host-settings) reports
these settings and never edits them.

Every event carrying a valid session ID touches `$XDG_STATE_HOME/hei5enbug-agent-setup/heartbeats/<host>-<session_id>`
and its `.<EventName>` file before the toggle check, on a best-effort basis. `PreToolUse` also writes the SHA-256 of
the current `hooks/hooks.json` as one line in `heartbeats/confirmed-<host>`. When this hash is missing or differs,
`UserPromptSubmit` adds a warning once per session and records that it was shown in the session state. The warning
explains that the guard has not been seen checking a tool call since its hooks changed, asks Codex users to trust
the plugin hooks in `/hooks`, and states that writes may run without approval until then. A classifier exception
asks every time with “The approval guard failed to check this call” and writes
`approval_guard: classifier error: <ExceptionName>` to stderr. Turning the guard off still prints nothing.

The approval guard is a guardrail, not a security boundary: an agent with full shell access could bypass it. Calls the
guard does not cover follow the host's own permission flow. Approval state lives under `$XDG_STATE_HOME/hei5enbug-
agent-setup/approvals/` (default `~/.local/state`), one file per host and session. An approval lasts until its session
ends, and a session file that has been idle for 7 days is deleted when another approval is written. Set
`approval_guard` to `false`, or `HEI5ENBUG_APPROVAL_GUARD=false` on Codex, to turn the guard off. In Codex, trust the
hooks in `/hooks`.

### Host settings

Some host settings add approval prompts or stop the guard from running. `scripts/host_settings.py` checks them and, on
Codex only, fixes a short allowlist:

```bash
python3 <plugin root>/scripts/host_settings.py check [--host claude|codex] [--json]
python3 <plugin root>/scripts/host_settings.py apply [--host claude|codex] [--json]
```

Both commands also take `--claude-dir`, `--codex-home`, and `--codex-bin`. The host defaults to the one that runs the
command. `check` is a read and writes nothing. It reports one line per problem:

- Claude Code: `defaultMode` is `dontAsk`, and `permissions.ask` rules that match Bash or MCP tools, up to three named.
- `[features] plugin_hooks` is not `true` in `~/.codex/config.toml`, on either host.
- Codex only: the plugin hooks are unconfirmed (the heartbeat hash differs), `config.toml` is not valid TOML,
  `rules/hei5enbug.rules` is missing, unreadable, outdated, or not plugin-owned, MCP servers lack the `prompt` approval
  mode, the mode
  step is skipped because `approval_guard` is off, or guard-covered MCP tools carry a per-tool `prompt` that would ask
  even for reads.
- Codex only: a `prompt` or `forbidden` rule in your own `rules/*.rules` files for a read prefix such as `kubectl get`,
  `helm list`, `az show`, or `git status`.

`apply` changes only this allowlist, and only on Codex. On Claude Code it changes nothing and reports that.

- `[features] plugin_hooks`, through `codex features enable plugin_hooks` when `codex features list` shows it. Without
  that command, `apply` says to set it by hand.
- The plugin-owned `~/.codex/rules/hei5enbug.rules`, created or updated to the text of the plugin version. It holds the
  `prompt` rule for the wrapper script used by [Approval guard](#approval-guard). `apply` only reports, and writes
  nothing, when that path is a symbolic link or an existing file lacks the plugin-owned header line.
- `default_tools_approval_mode = "prompt"` on every `[mcp_servers.<name>]` table, and `approval_mode = "prompt"` on each
  per-tool table that already sets another mode, while `approval_guard` is on. It edits only those lines and writes
  nothing when the result would not parse as intended.

Before it changes a file, `apply` copies it to `<file>.bak-hei5enbug-<YYYYMMDD>`, once per day. It prints one line per
change, and a second run changes nothing. It never edits your own rules files, Claude Code settings, or hook trust.

At session start, the `host_settings` option decides what the hook does. `apply` (the default) runs `apply` on Codex
first and adds one notice naming what changed, then reports the remaining problems from `check`. `report` only reports.
Any other value means `apply`. Claude Code reads the option from `/config`; Codex reads `HEI5ENBUG_HOST_SETTINGS`.


## Feature options

Seven boolean features can be turned off, and each defaults to on. The implementation worker route, the worker
models and efforts, the review model, the host settings mode, the hook Python interpreter, and the plugins refreshed
with this one (`refresh_plugins`) are string options in Claude Code. Choose `auto`, `codex`, `haiku`, `sol`,
or `sonnet` for the route; an unset or unrecognized value uses `auto`, where the main session picks the worker per
assignment. Choose `apply` or `report` for the host settings mode; an unset or unrecognized value uses `apply`. It
decides whether `SessionStart` may change allowlisted Codex settings; see [Host settings](#host-settings). The review
model runs independent validation and skill review roles at `high`, or at `xhigh` under the effort rule in
[model routing](instructions/model-routing.md#keep-role-settings-fixed). Choose one of the
seven pinned model IDs; an unset or unrecognized value uses `gpt-6-astra`. Set plugin options in `/config` or with
`claude plugin configure`. On Codex, set environment variables before starting the
session. A value of `false`, `0`, `off`, or `no`, in any letter case, turns a boolean feature off.

The Claude Code `worker` agent runs on `worker_model` and `worker_effort`; the mod spawns it on them, and an invalid
value keeps the registry pin. The session context reports them as `Worker agent model: <model> at <effort>.`
Codex has no plugin settings UI, so its session hook reads `codex_worker_model` and `codex_worker_effort` read-only
from Claude Code's saved settings (`pluginConfigs` in `~/.claude/settings.json`, or under `CLAUDE_CONFIG_DIR`). The
environment variables override them, and an invalid value falls back to the defaults with a one-line notice. The
session context reports them as `Codex worker model: <model> at <effort>.` They apply from the next Codex session,
and reading them never writes Codex or Claude settings. Only the allowlisted changes in [Host settings](#host-settings)
write Codex settings.

| Feature | Claude Code `/config` key | Codex environment variable |
|---|---|---|
| Block built-in subagents | `agent_guard` | `HEI5ENBUG_AGENT_GUARD` |
| Pin role models | `role_pinning` | Not applicable |
| Implementation worker route | `implementation_worker` (`auto`, `codex`, `haiku`, `sol`, or `sonnet`) | Not applicable |
| Claude Code worker model and effort | `worker_model` (default `claude-haiku-5-5`) and `worker_effort` (default `high`) | Not applicable |
| Codex worker model and effort | `codex_worker_model` (`gpt-5.6-luna` or `gpt-6.1-sol`, default `gpt-5.6-luna`) and `codex_worker_effort` (`high` or `xhigh`, default `high`) | `HEI5ENBUG_CODEX_WORKER_MODEL` and `HEI5ENBUG_CODEX_WORKER_EFFORT` |
| Review model | `review_model` (a pinned model ID, default `gpt-6-astra`) | Not applicable |
| Response language guard | `language_guard` | `HEI5ENBUG_LANGUAGE_GUARD` |
| DataGrip query guard | `datagrip_guard` | `HEI5ENBUG_DATAGRIP_GUARD` |
| Approval guard | `approval_guard` | `HEI5ENBUG_APPROVAL_GUARD` |
| Orca worktrees for other repositories | `orca_worktree` | `HEI5ENBUG_ORCA_WORKTREE` |
| Host settings mode | `host_settings` (`apply` or `report`, default `apply`) | `HEI5ENBUG_HOST_SETTINGS` |
| Hook Python interpreter | `python` (an absolute path, default empty) | `HEI5ENBUG_PYTHON` |
| Plugins refreshed with this one | `refresh_plugins` (comma-separated `plugin@marketplace` IDs, default empty) | `HEI5ENBUG_REFRESH_PLUGINS` |
| Subagent permission block in `~/.codex/AGENTS.md` | Not applicable | `HEI5ENBUG_SUBAGENT_POLICY` |
| Question tool flag | Not applicable | `HEI5ENBUG_CODEX_ASK_TOOL` |

The hook Python interpreter is the absolute path of a Python 3.12 or later interpreter. Install `pglast` into it
to run the SQL guard's parser. Every hook starts through `scripts/hook_python.sh`, which runs its script with this
interpreter. It uses the Claude Code `python` option first and then `HEI5ENBUG_PYTHON`, and only a path that starts
with `/` and names an existing executable file counts. An empty, relative, missing, or invalid value falls back to
`python3` on the `PATH`, so an unset option behaves as before. Setting the path skips a version-manager shim, such
as a pyenv shim, which adds about 150 ms to each hook process on one measured machine and can select a different
Python per project.

Without a matching launcher environment, the Mod refuses pinned GPT requests before a provider request. This refusal
has no toggle. The session instructions and operating rules also have no toggle, except the `orca_worktree` line,
which loads the cross-repository rules; disable the plugin itself to turn them off.

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
Python 3.12 or later must be available as `python3` on the host's `PATH`, or as the interpreter that the hook Python
interpreter option names (see "Feature options"). The hook uses only the Python standard library.
Root `AGENTS.md` governs development of this repository only; the hook never reads it.

Both hosts discover `hooks/hooks.json` automatically. Codex sets `PLUGIN_ROOT` to the installed plugin
directory; the loader uses that value to select Codex rules. Both hosts provide `CLAUDE_PLUGIN_ROOT`
for locating the script. No user or project instruction file is copied, linked, or overwritten.

| When | Behavior |
|---|---|
| Session starts or resumes | `SessionStart` supplies the installed instruction files and adds one-line notices from `host_settings.py check` when needed: up to three problems, then a count of the rest. Examples are Claude `defaultMode` `dontAsk`, Claude `permissions.ask` rules that match Bash or MCP tools, or an existing Codex config without `[features] plugin_hooks = true` (checked on both hosts). On Codex with the `host_settings` option on `apply`, it first runs `apply`, which may change allowlisted Codex settings (see [Host settings](#host-settings)) and adds one notice naming what it changed. Notices must fit the context limit. In an Orca terminal it also writes a marker with the plugin directory and an instructions digest. |
| Session clears or compacts | `SessionStart` supplies them again. |
| A subagent starts | `SubagentStart` supplies a short role context: `core.md`, plus the "Assigned workers" rules for implementation agents. |
| A role runner child session starts | It receives `core.md` only; the runner puts the role rules before the assignment. |
| A tool call finishes | `PostToolUse` adds a language reminder after a progress update in another language. |
| A reply ends | `Stop` asks for a rewrite when the reply is not in the response language. |
| A user submits a prompt on Claude Code | `UserPromptSubmit` compares the main session's "Implementation worker route", "Worker agent model", and "Review model" lines with the ones recorded at session start, and supplies the new lines once when a `/config` change altered them. |
| A DataGrip query is about to run | `PreToolUse` and `PermissionRequest` run the DataGrip query guard before `execute_sql_query`. |
| A Bash, MCP, or covered file tool call runs | `PreToolUse` runs the approval guard, including file-state protection and sensitive reads. `PermissionRequest` absorbs host prompts on Claude Code and skips Codex's native window once approved; `PostToolUse` and `PostToolUseFailure` record approvals. `UserPromptSubmit` resets the approval request counts, records user approval, and supplies immediate-retry context on both hosts. |
| A matching task begins | The agent reads the required reference under `instructions/`. |
| A plugin update is installed | A new session reads that installed version. A repository push alone changes nothing locally. |

Core rules remain in session context across requests. Service access, protected-value access, agent use,
documentation, implementation execution, and requested planning or design details load only before the
matching action, even if it arises later in a request. The session context distinguishes implementation plans
from design documents and keeps their trigger boundary. `instructions/implementation-planning.md` owns the
six-stage implementation plan workflow and template. `technical-design-writer` owns design-document behavior,
and `instructions/independent-model-validation.md` owns their shared one-pass cross-family validation
contract. The context header defines `$I` as the installed plugin's `instructions` folder, and the loader writes
each session file's conditional link to a file there as `$I/<path>`, so the context does not grow with the install
path. A link to another file inside the plugin keeps an absolute path. The loader does not read conditional
reference bodies at startup.

Codex requires review and trust of the current plugin hook definition before running it.
Disabled hooks or enterprise policies that prohibit plugin hooks prevent automatic loading.
After installation or update, use the host's hook controls to check that these hooks are enabled and,
in Codex, trusted. A hook that an update adds or changes, such as the agent guard, the language guard, or the DataGrip
query guard, stays skipped in Codex until you trust it in `/hooks`. `hooks/hooks.json` changed in this release,
because every hook command now starts through `scripts/hook_python.sh`. Codex users must trust the changed hooks once
in `/hooks` after updating. The Claude Code mod is not a Codex hook, so this trust step does not apply to
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
to a file and runs `python3 <plugin>/scripts/role_runner.py <role-or-capability>` or `python3 <plugin>/scripts/role_runner.py
agent --name <name> --fallback`, both with `--assignment <file> --result <file>`, from the session folder. It adds
`--model <id>` for `reviewer`, `--add-dir <dir>` for `worker`, a writing capability, or a `write` agent, `--mcp` for a
capability or agent that needs MCP tools or network, `--host claude|codex` to pick a capability's host entry, `--fallback`
for its fallback entry, and `--resume <session_id>` to continue a run from the `evidence.session` in its status line.
`--effort <level>` raises a run within its entry's range, whose lower bound is the default. Repeating `--assignment`
and `--result` runs up to six read-only assignments of one target in parallel, with one status line each, and the
runner exits with the highest of their exit codes. A read-only child runs without the host's skill catalog: Codex
gets `-c skills.max_context_tokens=1`, and Claude gets `--disable-slash-commands`. The runner
puts the role rules before the assignment, runs the role on its pinned model, effort, and permissions (`codex exec`, or
`claude -p` for a Claude model), checks the host rollout or transcript record, and prints a final JSON status line.
Without `--mcp`, a Codex child gets `-c mcp_servers.<name>.enabled=false` for every server `codex mcp list --json` names,
and a Claude child keeps `--strict-mcp-config`. A Claude child that may edit also receives `Bash` in `--tools` and
`--allowedTools`; the guard denies writes the main session has not approved and every irreversible action.
Each child receives `HEI5ENBUG_PARENT_SESSION` so it can use the main
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

After a substantial change and its checks are ready, the main session runs one independent review under
[independent model validation](instructions/independent-model-validation.md), without asking while the Codex weekly
usage that `scripts/codex_usage.py` reads is at most 70 percent. On Claude Code, the `review_model`
setting (default `gpt-6-astra`) reviews a Claude-authored result, and a GPT-authored result goes to `claude-fable-5-1`;
Codex uses its mapping in that file. Every reviewer runs at `high`, or at `xhigh` for several components, a
public contract, security, concurrency, or a hook or guard. When the configured reviewer shares the author's
model family, the result says the review is not cross-family. When the usage is above 70 percent or unknown, or the
reviewer runs on Claude, approval is required for the particular result, and a decline is not asked again. An unavailable reviewer, or a role runner exit code 3 or 4, means independent validation
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

Ask for `orca-plugin-refresh` after a release to update this plugin, and any other plugins you name, and apply the
installed versions to idle Orca-managed sessions without restarting them. The skill runs only when you ask for it.
`update --json` installs the new version in Claude Code and Codex. Add `--also <plugin@marketplace>` for each other
plugin; without it, the `HEI5ENBUG_REFRESH_PLUGINS` environment variable (comma-separated IDs) and then the saved
`refresh_plugins` option name them, and the first non-empty source wins. Each companion is updated and validated
per host and reported as `updated`, `current`, `not_installed`, `local_source`, `deferred`, or `error`. A plugin
that loads from a local folder is never installed, so uncommitted code is not deployed. A companion error never
blocks this plugin or the session apply. `apply-installed --json` validates the installed roots and companions
without marketplace or install commands. Both create a run ID for `apply --run-id <run_id> --json`.

Each host has its own install gate. Claude Code always installs, because an update adds the new version beside the
old one and running sessions keep their loaded directory until `/reload-plugins`. A Codex update deletes the old
install, so it waits until no Codex turn is running: it defers when the command itself runs inside a Codex turn,
when a Codex session file from the last 30 minutes does not end in a finished turn, or when those files cannot be
read. A deferred Codex host stays untouched, its companions are reported as `deferred`, and the result gives its
current root and a `recovery_command` to run after the Codex turn ends. Busy sessions are retried for up to one
hour. Manual updates and another process deleting a loaded directory remain outside this protection. See the
[refresh workflow](skills/orca-plugin-refresh/SKILL.md) for commands and limits.

| Part | Claude Code | Codex |
|---|---|---|
| Skills, agents, and hooks | The skill sends `/reload-plugins` | The next turn picks up the new install automatically |
| Session instructions | The skill sends `/compact` when they are stale | The skill sends `/compact` when they are stale; the session loads them on its next turn |

The skill decides that instructions are stale from the session-start marker: it is missing, holds another digest,
or points at a plugin directory that was replaced or removed. It sends a command only to an idle terminal whose
input line is empty and confirms every result from the session transcript or the screen. For a Claude Code session,
the skill may type and delete one character to tell a grey prompt suggestion from typed text; it never sends to a
session with typed text. A busy session is retried for up to one hour and is then
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
instructions. Every human-readable English Markdown file has a meaning-equivalent `.ko.md` mirror under
`docs/ko/`, following its source path relative to the repository root.
Each mirror links its source, is non-authoritative, and must never be loaded during agent execution.
Update, move, and delete each source and mirror together.

Code, schemas, test fixtures, generated artifacts, and non-English documents do not need Korean duplicates.
Korean may remain in an executable English file only as target-language data, such as trigger phrases,
examples, required output labels, or evaluation fixtures. Structural checks verify mirror coverage and
execution-path isolation; semantic equivalence still requires human or model review.

## Skills

| Skill | What it does |
|---|---|
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | Maps a multi-session effort into decision tickets and resolves them one at a time until the implementation route is clear. [Korean guide](docs/ko/skills/decision-navigator/SKILL.ko.md). |
| [`deep-interview`](skills/deep-interview/SKILL.md) | Runs a Socratic interview that scores requirement ambiguity after every answer and will not move to execution until it drops below the threshold. [Korean guide](docs/ko/skills/deep-interview/SKILL.ko.md). |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | A shared design standard so flow charts built in SVG, HTML/CSS, Figma, or draw.io all read as one design system. [Korean guide](docs/ko/skills/flowchart-design/SKILL.ko.md). |
| [`docs-rewrite`](skills/docs-rewrite/SKILL.md) | Rewrites existing text so it reads naturally while every claim, number, and level of certainty stays identical, and repairs AI-sounding Korean. [Korean guide](docs/ko/skills/docs-rewrite/SKILL.ko.md). |
| [`document-to-confluence`](skills/document-to-confluence/SKILL.md) | Converts Markdown, HTML, PDF, DOCX, and Google Docs content into Confluence pages, preserves document structure and assets, and keeps pages synchronized with source revisions without losing web edits or inline comments. [Korean guide](docs/ko/skills/document-to-confluence/SKILL.ko.md). |
| [`session-retro`](skills/session-retro/SKILL.md) | Reviews a day's Claude Code and Codex sessions of a repository with read-only scouts, turns corrections, failures, and repeated work into evidence-backed skill improvements per plugin, asks the open decisions, and writes plans on request. [Korean guide](docs/ko/skills/session-retro/SKILL.ko.md). |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Creates, tests, and packages agent skills through a draft → test → review → improve loop. [Korean guide](docs/ko/skills/skill-builder/SKILL.ko.md). |
| [`orca-plugin-refresh`](skills/orca-plugin-refresh/SKILL.md) | Updates this plugin and other plugins you name in Claude Code and Codex, with a per-host install gate, and applies the installed versions to idle Orca-managed sessions without restarting them. [Korean guide](docs/ko/skills/orca-plugin-refresh/SKILL.ko.md). |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Reads the staged and unstaged changes, or the scope you name, plus recent commit history, then suggests five commit messages that match the repo's style. When you ask it to commit, it commits with the single best subject instead. [Korean guide](docs/ko/skills/suggest-commit/SKILL.ko.md). |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Writes or reviews technical design documents and RFCs without taking ownership of implementation planning. [Korean guide](docs/ko/skills/technical-design-writer/SKILL.ko.md). |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Runs a turn-limited debate between the current agent and an opposing Claude/Codex session to surface and resolve issues. [Korean guide](docs/ko/skills/tiki-taka/SKILL.ko.md). |

## Related

- `omo-model-config` was removed; its last version is in the [`v1.3.0` tag](https://github.com/hei5enbug/hei5enbug-agent-setup/tree/v1.3.0/standalone-skills/omo-model-config).

## License

This repository is licensed under the Apache License 2.0. See [`LICENSE`](./LICENSE) for the full text.
