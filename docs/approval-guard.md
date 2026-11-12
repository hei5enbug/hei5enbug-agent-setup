# Approval guard

This page explains which calls need approval, how approvals work on each host, and what the guard protects.

## Decision tiers

A `PreToolUse` hook runs `scripts/approval_guard.py` before Bash, MCP, Claude file tools (`Read`, `Edit`, `Write`,
`MultiEdit`, `NotebookEdit`), and Codex `apply_patch` calls. It also handles `PermissionRequest`, `PostToolUse`,
`PostToolUseFailure`, and `UserPromptSubmit`. Reads run without approval on both hosts. A call lands in one of three
tiers, or is denied or passed:

| Decision | Behavior |
|---|---|
| Read | runs without approval. |
| Session approval | asks once per session and then covers every later call of its kind until the session ends. There are two. `write:session` covers every write, whatever its command or target, including production changes, git pushes, MCP, DataGrip, and tabularis writes; unclassifiable calls are writes unless their text contains a destructive action. `sensitive:session` covers every sensitive read, meaning a call that may expose a protected value. Approving one never approves the other, and a call that needs both asks once for both. |
| Every time | asks on every call and keeps no approval, so the next run asks again. The list below holds these actions. Their Claude prompt starts with `Asks every time:`. When such a call also needs a session approval, approving it grants that approval too, and the prompt says so. |
| Request | asks for a bundle of session approvals before the actual calls. |
| Secret | is denied on both hosts because the command would print a secret value. |
| Forbidden | is denied on both hosts: running the guard scripts, editing the approval state, or writing installed plugin code (see the self-approval rules below). |
| Pass | is a call the guard does not cover, so the host's own permission flow decides. |

## Calls that ask every time

The every-time list holds the actions that affect remote or production systems or destroy local data that cannot be
recovered, so one approval never covers the next run. Local actions that are disposable or recoverable are not on it;
the local-scope rules below describe them.

1. Destructive `git push`: force, force-with-lease, delete, mirror, or prune pushes, and `+` or `:` refspecs, except the
   lease-protected feature-branch push described in the local-scope rules.
2. Discarding uncommitted work: forced `git clean` without a dry run, `git stash drop` or `git stash clear`, and `git
   reset --hard`, forced checkout or checkout of `.`, or restore of `.` or `:/` on the worktree whenever the repository
   has an uncommitted change to a tracked file or its state cannot be read.
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

## Local-scope exceptions

Local-scope rules keep disposable or recoverable local work off the every-time list:

- **Temporary roots** are `/tmp`, `/private/tmp`, `/var/folders`, `/private/var/folders`, `$TMPDIR`, `~/.cache`, and
  Claude Code job folders `~/.claude/jobs/<id>/tmp`. Recursive removal inside a temporary root passes. Redirections
  (`>`, `>>`, heredocs), `mkdir`, `touch`, `tee`, and the destination of `cp` or `mv` pass when every destination is
  inside a temporary root, resolved through symlinks; their sources may be anywhere, but `cp` or `mv` into an existing
  folder is judged by `<folder>/<source name>`, so a symlink there that leaves the roots, or a source name that cannot
  be known (a glob or variable), disqualifies it. When the whole command is made of such writes and a few harmless
  commands such as `cat`, `echo`, `ls`, and `cd`, Claude Code's own permission prompt is answered with allow without any
  session approval. A destination that is not provably inside a temporary root, such as `./README.md`, keeps its normal
  flow. Scripts that write there are still writes.
- **Recoverable work-tree removal**: a recursive `rm` is a session write, described as "Recursive removal of tracked
  files" or "Recursive removal of ignored files", when every target lies inside the Git work tree that holds the
  command's folder and Git reports each as tracked with no staged, unstaged, or untracked change under it, or as
  untracked and ignored (`git check-ignore`). Git runs with untracked-file reporting and ignore settings forced on the
  command line, so repository configuration cannot hide a file. The work-tree root, `.git`, a symbolic link, a path that
  does not exist, an `assume-unchanged` or `skip-worktree` entry, untracked files that Git does not ignore, a command
  earlier in the same text that may change files (a loop header counts, a plain `[ ... ]` test does not), a Git variable
  that could redirect the repository, and any Git failure or timeout keep asking every time.
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
  is an unreadable one. Remote engines keep asking every time. A function, variable, `eval`, or `sh -c` text whose only
  destructive words are local `docker` or `podman` removal is a session write too.
- **Lease-protected push**: `git push` is a session write, not every time, when its only force-like flags are
  `--force-with-lease` (bare, `=<ref>`, or `=<ref>:<expect>`) and `--force-if-includes`, the remote is named explicitly
  and is not `upstream` (a URL, a path, or a remote git cannot read keeps every time), and every destination branch is
  explicit and not `main`, `master`, `develop`, `trunk`, or the remote's HEAD branch when `git symbolic-ref
  refs/remotes/<remote>/HEAD` can be read. The destination comes from `src:dst`, `dst`, or the lease ref; `HEAD`, `@`,
  an empty or implicit destination, a glob, or a `refs/` name other than `refs/heads/` keeps every time. `--force`,
  `-f`, `--delete`, `-d`, `--mirror`, `--prune`, `--all`, `--tags`, a `+` or `:dst` refspec, an unknown option, a global
  option other than `-C`, a redirecting `GIT_*` variable, and `exec` inside a container also keep every time. Example:
  `git push --force-with-lease origin feature/ABC-1` is a session write while `git push --force-with-lease origin main`
  asks every time.
- **Clean tracked tree**: `git reset --hard`, `git checkout -f`, `git checkout .`, and `git restore .` are session
  writes when `git status --porcelain --untracked-files=no` in the repository (`-C` is followed) prints nothing within 3
  seconds. These keep them every time: an error or timeout; any global option except `-C` and the harmless `--no-pager`,
  `-P`, `--no-optional-locks`, `--paginate`, and `-p` (so `-c`, `--config-env`, `--git-dir`, `--work-tree`,
  `--namespace`, and `--bare` all count); and any `GIT_*` variable except `GIT_EDITOR`, `GIT_SEQUENCE_EDITOR`,
  `GIT_PAGER`, `GIT_TERMINAL_PROMPT`, `GIT_ASKPASS`, `GIT_SSH`, `GIT_SSH_COMMAND`, `GIT_TRACE*`, `GIT_PROGRESS_DELAY`,
  `GIT_FLUSH`, and `GIT_MERGE_AUTOEDIT`. `GIT_CONFIG_COUNT` entries the session inherited unchanged are also exempt when
  they only set `credential.interactive` or `credential.guiPrompt`, as some terminals export; a command that sets any
  `GIT_CONFIG_*` variable itself still counts. So does a command inside `kubectl`/`oc`/`docker`/`podman` `exec`, and so
  does any earlier segment in the same command that is not a plain read without file output (`printf x >> a; git reset
  --hard` asks every time).

## Prompts and CLI classification

A call that needs approval shows one line in the response language, at most 100 characters. Claude Code takes the
language from the `language` setting and uses English without one. Codex uses `HEI5ENBUG_LANGUAGE`, else the response
language guard's `HEI5ENBUG_RESPONSE_LANGUAGE`, whose default is Korean. A description that does not fit is shortened
but keeps at least 20 characters. A compound call keeps every description, each cut to 40 characters, and its line has
no length limit. Claude shows these lines:

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

Other covered non-destructive CLI operations use the session write approval. That includes a local `kubectl`/`oc config`
change such as `use-context` or `delete-context`, `helm repo remove`, and deleting or forcing a local git tag. Files,
stdin, and interactive use of remote SQL clients are unclassified writes unless destructive text puts them on the
every-time list. Explicit local hosts (`localhost`, `127.0.0.1`, `::1`, or a socket path) pass for `psql`, `mysql`,
`redis-cli`, and `mongosh`. `gh api` data flags and `--input` imply a write unless an explicit GET overrides them. An
inline GraphQL field is a read only when, after removing `#` comments and leading whitespace, it starts with `query` or
`{` and contains no `mutation` word. Mutations and query files are writes. Unknown `gh` actions are writes; `gh pr
checkout` and `gh repo clone` pass to the host. Git tag creation and pushes, and `gh` writes such as release creation,
editing, and uploads, use the same approval on both hosts.

Package publishing (`npm`, `pnpm`, `yarn`, `uv`, `poetry`, `cargo`, `twine upload`, and `gem push`) asks every time,
including when options precede the publishing subcommand. Recursive `rm` asks every time for protected or external
paths, including the session folder, its ancestors, the home folder, `/`, `.git` and its contents, and unresolved
targets. Removal within the session folder or a temporary root (see the local-scope rules) otherwise passes. A target
that is exactly a `$(mktemp -d ...)` or backtick substitution, or starts with `${TMPDIR:-<default>}`, is first resolved
to a temporary root (`TMPDIR` when set, else the default) and then checked like any other path, so those checks still
block the home folder, the session folder, and `.git`. A variable assigned earlier in the same command text resolves
when its value is one static word (a literal, `~`, `$HOME`, `$TMPDIR`, `${TMPDIR:-<default>}`, or another resolved
variable), including assignments inside `if`, `case`, `{ }`, and `( )` bodies that every path through the text reaches,
and the words of a `for` loop. The removal is checked against every possible value and the strictest result wins. An
assignment that runs only when an earlier command in a `&&` or `||` list succeeds or fails is conditional: a later
command in that list sees only the new value when every link before it is `&&`, and after any `||`, like everything
after the list (`;`, a newline, or `&`), it sees the new value together with the value from before, which is the empty
string for a variable the environment does not provide. An unquoted reference splits on whitespace, so each word of its
value is checked as a separate target. An unquoted operand that expands to nothing is dropped and a quoted empty operand
removes nothing, but an empty value that turns the target into a path outside the session folder and the temporary
roots, such as `$D/y` becoming `/y`, still asks. A later `cd` changes only relative targets. Command substitution,
backticks, `read`, arithmetic, unknown variables, `set --`, `shift`, and values assigned on only some paths stay
unresolved and ask every time. When the guard reads a shell script that a command runs, it judges the script as one
text, so a variable assigned on one line resolves on the next. In that script `$0`, the folder idioms `$(dirname "$0")`,
`$(cd "$(dirname "$0")" && pwd)`, `${BASH_SOURCE[0]%/*}`, and `$1` to `$9` resolve to the script's path, its folder, and
the call's literal arguments, with each possible value when an argument is a loop variable. The script path is the one
the command used, made absolute without resolving symbolic links, as the shell sees it. Commands inside
`kubectl`/`oc`/`docker`/`podman` `exec` also use the normal classifier: destructive commands ask every time (file
removal inside a local `docker` or `podman` container is a session write), secret output is denied, and other `exec`
calls are writes. Any `codex` invocation with sandbox bypass flags or `danger-full-access`, including a configuration
override, asks every time. Worker access outside the session folder through `codex exec` (or `e`) with `--add-dir` or
`-C`/`--cd` before or after the subcommand, or through `role_runner.py --add-dir`, is a write.

## Shell and script classification

A write is described by `<cli>:<subcommand>@<target>`, where the subcommand is the words before the first flag. The
prompt shows it as `<cli> <subcommand> on <target>`, and one `write:session` approval covers every such write. For
`kubectl`, `oc`, and `helm`, the target is the kubeconfig (`--kubeconfig`, then `KUBECONFIG`, else `(default)`) followed
by the context and namespace; a context that is not given is read through the same kubeconfig. Any other parseable
subcommand is a write, so `kubectl apply` and `helm upgrade` ask only until the first write is approved for the session.
The body of a `$(...)` or backtick substitution is classified like a command of its own and merged into the call. A
substitution whose command verb is an unexpanded variable is an unclassified write unless it contains a destructive
action. Commands inside `eval`, `xargs`, or `sh -c` with any flag cluster that contains `c` are classified too. When a
region itself prints a secret, the whole command is denied. A heredoc on a covered command is an unclassified write
unless it contains a destructive action. A heredoc body is data and is not scanned when its command is `cat`, `tee`,
`echo`, `printf`, `head`, `tail`, `wc`, `sort`, `uniq`, `cut`, `tr`, `base64`, `xxd`, `od`, `grep`, `egrep`, `fgrep`,
`rg`, `jq`, `column`, `fold`, `fmt`, `nl`, `tac`, `rev`, `cmp`, `diff`, `git`, or `gh`, its output is not piped onward,
and every file it writes is not later run by `bash`, `sh`, `zsh`, or `source` in the same command text. File suffixes do
not change that rule. Other receivers keep the body scanned. Only the substitutions that an unquoted delimiter lets the
shell run are still classified. A segment whose program word comes from a substitution or an unexpanded variable and
that names a covered CLI is unclassified. A `command -v` lookup runs nothing and is not classified.

A compound command is judged as a whole. A secret segment denies it. When any segment is on the every-time list, the
call asks every time, and approving it also grants the session approvals that its other segments need. Otherwise any
write makes the whole command a write, even with an unverified segment or file output. A covered read stays a read only
when every other segment is a filter such as `grep`, `head`, or `jq`, and output redirections go only to `/dev/null` or
`2>&1`. Wrappers such as `sudo`, `env`, `nice`, and `time` are skipped, with their options, before the executable is
read. Targets for write and every-time calls come from flags or the environment. When neither is set, `kubectl config
current-context` and `az account show` run for those calls only, with a 3-second limit.

A `psql` read is rewritten to run in a subshell with `PGOPTIONS` extended by `-c default_transaction_read_only=on -c
statement_timeout=60000`, so the server refuses writes even when the guard's read check misses a function call, and the
option never reaches later commands.

The guard reads shell files invoked by `bash`, `sh`, `zsh`, `./`, `source`, or `.`, Python files, Makefile recipes for
the selected/default target and one level of prerequisites, and the script text in `package.json` for `npm`, `pnpm`, or
`yarn run <name>`. Files resolve from the event's `cwd` and are limited to 256 KiB. Plain `NAME=value` statements
earlier in the same command text, separated by `;`, `&&`, or newlines, are substituted into later simple commands,
including the body of a `for ... do ... done` loop, with sh word splitting for unquoted expansions. This holds only when
the value is one static word with no command substitution (a `$(mktemp -d ...)` resolves like a removal target), and the
assignment is unconditional: not `export`, not inside parentheses, a block, a function, a brace group, a pipe, or the
background, and not after `||` or `&&` unless the left side is only assignments. An assignment inside such a context
makes the name unknown afterwards. `read`, `export`, `for NAME in`, and similar commands drop the substitution. `xargs`
followed by a simple command is classified as that command with its input as one unknown operand and the segment's own
assignments (`DOCKER_HOST=ssh://h xargs docker rm` asks every time). A read, or a file reader such as `cat` or `grep`,
becomes a sensitive read because the unknown operand could name a protected file, and `xargs rm -rf` asks every time; a
shell, `eval`, a nested `xargs`, an unknown option, or a placeholder in the command name keeps the old opaque handling.
A `cd <dir>` moves that base for the later segments only when it runs unconditionally in the current shell: outside
parentheses, after nothing or `;`, and before nothing, `;`, or `&&`. `$NAME` or `${NAME}` that an earlier standalone
assignment set is expanded in the path; a prefix assignment (`NAME=value cmd`) never expands its own command's
arguments. An unassigned variable leaves the script unreadable, so it is unclassified. Shell lines and Makefile recipes
use the CLI classifier. A Python script file or `python3 -` heredoc whose syntax tree is provably read-only is a read:
it imports only listed standard modules, calls no process, network, environment, dynamic-execution, or file-mutating
function (including `replace`, `remove`, `touch`, and `mkdir` names), opens files only in a literal read mode (every
name bound to an `open` function is checked, so `from io import open as f` gets no exemption), and names no
credential-like path or word. Anything the check cannot decide keeps the old result, and a protected file passed as an
argument, or as the value of an option (`--file=.env`), does too. Inline code is classified, never the heredoc,
whichever way `-c` is spelled (`-c code`, `-ccode`, `-Ic code`). Python inline code, heredocs, stdin files, and script
files are writes when they run a process or import a cloud/database SDK. Literal process commands, including keyword
arguments, are classified. Destructive process commands, SDK call names, or destructive text in Python that runs a
process or imports an SDK ask every time. Other Python passes, even when its strings name CLI commands (`python3 -c`
code never becomes a read); an explicit `--execute` still makes it a write. An `exec` or `eval` of a string literal is
judged by the code it runs, as if that code were written in place, so a harmless literal passes and one that reads a
credential or writes a protected location gets that decision. A namespace argument that is a dict literal of constants
gives those values to the names the code reads; any other namespace, such as `globals()` or a variable, is not unfolded
and keeps the session write. An `exec` or `eval` of a variable, `input()`, or standard input keeps the old result, a
session write, and still draws the credential, installed-code, and protected-location decisions for the rest of the
script. Node and other non-shell, non-Python executables pass. Reads need no approval; writes need the session write
approval; destructive, forced, and secret calls keep their normal rules. Unreadable or larger script files are
unclassified. An inspected shell script naming a covered CLI or importing `boto3`, `azure`, `kubernetes`, `psycopg`,
`psycopg2`, `pymysql`, `sqlalchemy`, `pymongo`, `redis`, or `google.cloud` without a classifiable call is unclassified
too. These calls are writes unless their text contains a destructive action, which asks every time. A script that names
none of these passes. The plugin's own `python3 <plugin root>/scripts/host_settings.py check` is a read, and `apply` is
a session write, when the script belongs to this guard's plugin root and no interpreter options precede it.

## MCP and database calls

MCP tool names split at `_`, `-`, and camelCase. Destructive name words ask every time. String fields `sql`,
`statement`, and `queryText`, and a `query` field whose text starts like a SQL statement (a search phrase does not), use
the DataGrip SQL classifiers: reads run freely, destructive statements ask every time, and other SQL is a session write.
Execution name words (`repl`, `exec`, `execute`, `eval`, `run`, `code`, `script`, `command`) classify their code input
like a command or a Python script, by its `language` field or its look: a secret or forbidden result is denied as usual,
a result that asks every time asks every time, and anything else, including a tool without code, is a session write. An
explicit `action` input overrides ordinary name verbs: a destructive action asks every time, and destructive SQL fields
take precedence over other actions. Without SQL, a read action is a read and a write action is a write. Without that
input, a name starting with a read verb is a read even if a later word names a write, and a name written as one
lowercase run, such as `getjiraissue`, is a read when a read verb leads and no write or delete word follows; otherwise a
write word takes precedence over read words. Names with no known verb are writes. The session write approval covers
every non-destructive MCP write for that session, including DataGrip and tabularis writes.

For `mcp__tabularis__run_query`, `connection_id` resolves an ID or name from tabularis' `connections.json`. The config
directory is `~/Library/Application Support/tabularis` on macOS, `$XDG_CONFIG_HOME/tabularis` or `~/.config/tabularis`
on Linux, and `%APPDATA%\tabularis` on Windows. `HEI5ENBUG_TABULARIS_DIR` overrides it for tests. The guard extracts
only `id`, `name`, and `params.driver`; it never prints other connection fields or passwords. `postgresql` uses the
PostgreSQL classifiers; `sqlserver` and `sqlserver-entra` use the SQL Server classifiers. Reads on non-production
connections run without approval; non-destructive writes are session writes. Another driver, an unknown connection, an
unreadable file, or unparseable query text uses the session write approval. `delete`, `drop`, or `truncate` in the code
(not in literals, comments, or quoted identifiers) and statements the SQL classifier treats as destructive, including
those led by `DO`, `EXEC`, `EXECUTE`, or `CALL`, ask every time, except the targeted `DELETE` and safe `DO` on
non-production PostgreSQL connections described in the [DataGrip query guard](guards.md#datagrip-query-guard), which are
session writes. Those queries use `sql:always:tabularis:<id>:<digest>` keys. Other tabularis tools keep the name rules.

### Production database reads

For `run_query` and DataGrip `execute_sql_query`, a connection is non-production when its name, split at case changes,
spaces, `_`, `-`, `.`, and brackets, has a word `dev`, `develop`, `development`, `test`, `testing`, `qa`, `stg`,
`stage`, `staging`, `sandbox`, `local`, or `demo`, or contains `개발`, `테스트`, `스테이징`, `검증`, or `로컬`, and has no word
`prod`, `production`, `prd`, or `live` and no `운영`. Every other connection is production, including unknown ones and
names with `승인`.
- A PostgreSQL `EXPLAIN [(options)] <read>` without `ANALYZE` is a read on any connection. After one succeeds on a
  production connection, the `PostToolUse` hook records the estimated cost and rows (JSON `Plan` `Total Cost` and `Plan
  Rows`, or the first text plan line) per host, session, tool, connection, and exact read text (only leading and
  trailing whitespace and trailing semicolons removed) in a state file for 30 minutes. Errors and unparseable results
  record nothing.
- A PostgreSQL production read with such a record at or under both limits runs; without one, it is denied with the exact
  `EXPLAIN (FORMAT JSON) <read>` to run first; over a limit, or with an unparseable record, it asks every time.
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

## Sensitive reads

`curl` without a request method other than GET/HEAD and without `-d`, `--data*`, `-F`, `--form`, `-T`, `--upload-file`,
or `--json` is a read. Otherwise it is a write shown as `curl <METHOD> on <scheme://host>`; destructive methods such as
DELETE ask every time. `-u`/`--user` or an `Authorization` header in argv adds a sensitive read approval to the method's
own outcome: a read needs `sensitive:session`, a write needs both `write:session` and `sensitive:session`, and a
destructive method still asks every time. A description that a prompt shows or the pending state stores masks
`-u`/`--user` values, `Authorization`, `Cookie`, and `X-Api-Key` header values, URL user information, and `key=value` or
`--key value` pairs whose key names a secret.

Claude `Read` and Bash reads (`cat`, `less`, `head`, `tail`, `grep`, `rg`) of `~/.kube/config`, any `KUBECONFIG` path,
`~/.aws/credentials`, `~/.aws/config`, `~/.azure/**`, `~/.config/gcloud/**`, `~/.pgpass`, `~/.docker/config.json`,
`~/.netrc`, `~/.config/gh/hosts.yml`, private keys under `~/.ssh` (not `*.pub`, `known_hosts`, or `config`), or `.env*`
files are sensitive, except templates whose names end in `.example`, `.sample`, `.template`, or `.dist`. Python code
gets the same decision: a heredoc, `-c` code, or script that opens, reads, or loads one of these files (the path may be
spelled through `Path.home()`, `os.path.expanduser`, `os.path.join`, an f-string, or a name assigned once), or that
prints or sends the value of an environment variable with a secret-like name (`os.environ[...]`, `os.environ.get`,
`os.getenv`), is a sensitive read. Testing whether such a variable is set, listing variable names, checking that a file
exists, and using the secret word only as search text stay silent. So are unfiltered `printenv`, `env` without a
command, `kubectl exec ... env|printenv`, `docker inspect`, `docker exec ... env`, `terraform` state and JSON or raw
output, and `helm get all`, `get manifest`, and `get values`. The first sensitive read of a session asks once; after
that, every sensitive read runs for the rest of the session. The secret denial stays: a command that would print a
secret value is denied even after the approval. `printenv` with only non-secret variable names is a read. Supported
`grep`/`rg` filters on `env` or `printenv` are reads when no matched name is secret; count-only output is also a read.
So is a pipe that keeps only the variable names or hides the values: `cut -d= -f1`, `awk -F= '{print $1}'`, `grep -o`
with a pattern anchored to the name, `grep -c`, and a `sed` substitution that replaces everything after the first `=`.
Filters that cannot be checked stay sensitive. A supported filter keeps its verdict inside a command list, and the guard
aggregates it with the other elements as usual, unless the list can change the environment first, such as with `export`,
an assignment, `source`, or `eval`. `python3 <plugin root>/skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py
status ...` is a read when the resolved script belongs to this guard's plugin root and no interpreter options precede
it.

## Claude Code approval flow

On Claude Code, a call that needs approval gets a `PreToolUse` `ask` with the one-line reason above, and a call the
session already approved gets `allow`. The guard also answers the host's own `PermissionRequest` prompts, so one session
write approval absorbs them:

- An edit tool (`Edit`, `Write`, `MultiEdit`, `NotebookEdit`) on a path inside the project folder (`CLAUDE_PROJECT_DIR`,
  else the working directory) or inside `permissions.additionalDirectories` from the local project, project, or user
  settings is allowed. Paths that hold a `$`, the guard's state folders, protected paths such as `.env*` and credential
  files, the host's protected folders and files (`.git`, `.claude`, `.vscode`, `.idea`, `.husky`, shell startup files,
  `.gitconfig`, `.gitmodules`, `.mcp.json`, `.claude.json`, `.ripgreprc`) anywhere in the absolute path, even inside an
  allowed folder that is itself one of them, and anything outside those folders are left to the host.
- A Bash command the guard does not cover is allowed too, except one that runs `ssh`, `scp`, `rsync`, `sudo`, `su`, or
  `doas`, removes recursively, force-pushes, writes with `dd of=`, runs `mkfs`, or names a destructive action. Calls
  that the guard classified and the session already approved are allowed as well. Reads, every-time calls, and anything
  else get no decision, so the host decides.
- Before the session write approval exists, the first such edit shows the host's native prompt. The guard notes that
  request, and when the edit completes it records `write:session`. So the first edit approved in the native prompt
  grants the write approval, and a later `kubectl apply` does not ask again. When the request budget described below is
  used up, the edit prompt is denied with the stop message instead of shown again.

Limitation: in auto mode the host's classifier can still deny a call that the guard allowed, and the plugin does not
override that denial. A `PermissionDenied` hook could not reverse it either, because its `retry` only tells the model it
may try again.

## Codex approval flow

On Codex, `PreToolUse` cannot ask, so the native approval window carries the approval when it is ready:

- For a Bash call that needs approval, `PreToolUse` allows it with the command rewritten to `<plugin
  root>/scripts/approve_wrapper.sh '<original command>'`. The wrapper is a two-line script that runs `bash -c` on its
  one argument. The plugin-owned rules file `~/.codex/rules/hei5enbug.rules` holds one `prefix_rule` with
  `decision="prompt"` for the wrapper's path, so Codex shows its approval window with the original command. The guard
  unwraps the wrapper before it classifies, so the verdict is the one for the original command, and a wrapper call with
  a destructive inner command still asks every time. `sh`, `bash`, or `zsh` running the wrapper with one plain word,
  alone or behind wrappers such as `env`, `command`, `exec`, or `nohup`, is classified by that word's text. Any other
  command that names the wrapper path, such as one with another argument count, `source`, a substitution, or `xargs`,
  asks every time as "Unrecognized approval wrapper call", and the wrapper's own file is never classified.
- For an MCP call, `default_tools_approval_mode = "prompt"` on the server makes Codex show the window. Reads are not
  wrapped, and `PermissionRequest` answers them with `allow`, which skips the window. DataGrip queries follow the same
  path through `datagrip_guard.py`. Only calls that ask once per session use the window; every-time MCP and DataGrip
  calls, such as destructive tools and queries, keep the code flow even when the window is ready. The window's mode
  comes from `config.toml`, so a session started with a command-line override that moves an MCP server away from
  `prompt` can run that server's non-destructive writes without approval. `apply_patch` edits stay with Codex.
- `PermissionRequest` skips the window once the session holds the approval the call needs. Otherwise it notes what the
  window would grant. Codex runs the call only after the user chose to proceed, so when it completes, `PostToolUse` or
  `PostToolUseFailure` records `write:session` or `sensitive:session`. An every-time Bash call asks in the window every
  time and leaves no approval. A user who declines leaves no approval either.

The native window needs all of these: the hook event reports permission mode `default`, the session is not a role runner
child, the session has a usable ID, `rules/hei5enbug.rules` holds exactly the text this plugin version writes, and an
MCP tool's approval mode in `~/.codex/config.toml` is `prompt`. Otherwise the code flow below applies. That covers
sessions that cannot show a window, such as `codex exec` and bypass-permissions runs, child workers, and the time before
[Host settings](configuration.md#host-settings) wrote the rules file or the MCP mode. A Codex hook that is not trusted
runs no guard at all, so no flow applies; see the trust warning below.

## Approval codes and request limits

Prepare a bundle before running writes:

```bash
python3 <plugin root>/scripts/approval_guard.py request --key write:session --why 'Deploy the requested change and update the issue'
```

`--key` takes `write:session` or `sensitive:session`, and may repeat. Claude asks showing the reason, then records the
session keys only when that asked call reaches `PostToolUse` or `PostToolUseFailure`. A failed approved write still
grants the session approval. A call allowed by an existing approval does not grant it again. Codex denies with one code
for the bundle and records it when the user types `승인 <CODE>`, or `승인` alone if only one request is pending. The command
prints the keys and exits 0; it never writes approval state itself. The older `<cli>:<kind>@<target>` and `mcp:session`
forms are still accepted and approve the same session write approval. Destructive or forced kinds, `sql:always:*`, and
destructive `mcp:<tool>` keys cannot be pre-approved, so no every-time action can be requested. Explicit `unclassified`
request-key forms are rejected too; the session write approval still covers non-destructive unclassified calls.

When the code flow applies on Codex, a call that needs approval is denied with a code on two lines. In English:

```text
Approval required: kubectl apply on (default) dev/web. Approving also covers later writes in this session. Ask the user to reply `approve K7M2QX` (or just `approve` when only one is pending).
After the user replies with the code, retry this exact call immediately and continue the task without asking again.
```

In Korean, the first line reads as follows, and the second line stays the same:

```text
승인 필요: kubectl apply on (default) dev/web. 승인하면 이 세션의 쓰기도 더 묻지 않습니다. 사용자에게 `승인 K7M2QX` 입력을 요청하세요(대기 요청이 하나면 `승인`만).
```

The user types `승인 <CODE>` or `approve <CODE>` in chat. `승인` or `approve` alone works only when exactly one request is
pending. A `UserPromptSubmit` hook records the approval, and the agent immediately retries the exact call and continues
the task without asking again. Both hosts add the approved descriptions and that retry instruction to `UserPromptSubmit`
context. A code covers every key of the denied call: its every-time keys as one-time approvals and its session keys as
session approvals. Session approvals last until the session ends; the state of a session idle for seven days is removed.
If a Codex one-time approval is in flight without `PostToolUse` or `PostToolUseFailure`, the next attempt for the same
key may reuse it once without a new code. The approval moves to that retry; another interruption needs a new approval
request. `PermissionRequest` allows only the call holding the approval, and `PostToolUse` or `PostToolUseFailure`
releases it.

Each session counts issued approval requests per key until a call completes or the user sends a new prompt. Claude asks,
Codex native windows, and Codex code responses count, including repeating a pending code. After three requests without
`PostToolUse` or `PostToolUseFailure` since the user's last prompt, a fourth request is denied. In English the message
is: “This approval was requested three times since the user's last message without the call completing (declines
included); stop retrying and tell the user.” An approval already given is honored, including a retry approved by the
third code. `PostToolUse` or `PostToolUseFailure` resets the count for the finished call's keys, and `UserPromptSubmit`
resets every count, so a write the user asks for after a stop is asked again. Already approved session keys do not use
another key's request budget.

## Writes a skill declares

A long run that the user started by approving a skill's start can reach new write keys while the user is away. A plugin
may declare the writes that its skill's start covers, and the guard then runs them without a question. A plugin with no
declaration behaves as described above.

### The declaration file

A plugin ships one `approval-grants.json` at its root. The guard reads it only from the version that the running Claude
Code installation lists as installed in `installed_plugins.json` (under `$CLAUDE_CONFIG_DIR/plugins`, or
`~/.claude/plugins`), because installed plugin code is what the guard protects from the agent. A rolled-back plugin
therefore applies its older declaration, and a plugin that file does not list, or a copy only in another host's cache,
has no declaration. The guard ignores a file that resolves outside the plugin caches, such as a link into a work tree. A
file with a wrong layout is refused as a whole.

```json
{
  "skills": {
    "demo-run": {
      "entries": [
        {"command": "az repos pr update --status completed"},
        {"command": "az repos pr update --id <id> --status completed --delete-source-branch false",
         "extra_options": false},
        {"command": "git push -u origin <branch:feature/*>"},
        {"command": "kubectl rollout restart <workload> -n <ns:@grant> --context <ctx:@grant>",
         "never": {"ctx": ["prod-ctx"]}},
        {"command": "curl -X DELETE https://<host:api.dev.example.com|api.stg.example.com>/<path>", "destructive": true},
        {"tool": "mcp__demo__demo_post_message", "arguments": {"channel": "C123"}}
      ]
    }
  }
}
```

An entry has exactly one of `command` (a command example) or `tool` (the full `mcp__<server>__<tool>` name, with
`arguments` that name the values a call must carry). `never` maps a placeholder name to values that are never accepted,
`destructive: true` lets the entry cover a call the guard classifies as destructive, and `extra_options: false` on a
command entry makes it match only a write that adds no option beyond the entry's own (see
[Matching a write or call](#matching-a-write-or-call)). `extra_options` takes `true` or `false`, and `true` is the
default. Any other key, or another value, makes that entry invalid, and the grant ignores it and reports why.

| Placeholder | Accepts |
|---|---|
| `<name>` | any value |
| `<name:a\|b>` | one of the listed values |
| `<name:glob>` | a value that matches the glob, such as `<branch:feature/*>` |
| `<name:@grant>` | a value the grant command passed for `name` |

A placeholder may stand for a whole argument or for part of one, such as a URL path. An option whose example value is a
JSON object accepts an inline JSON object with exactly the example's keys at every depth, where each value equals the
example's or is accepted by a placeholder written as a JSON string. An extra or missing key, a different type, a
repeated key, and a value read from a file such as `@body.json` never match.

### Grant, deny, and link

The skill runs the grant command after it starts:

```bash
python3 <plugin root>/scripts/approval_guard.py grant --skill demo-run --value ctx=dev-ctx --value ns=demo
```

`--skill` takes `<skill>` or `<plugin>:<skill>`, and `--value name=value` passes a value for an `@grant` placeholder and
may repeat. The `PreToolUse` hook decides the call, as it does for `request`, and stores the grant in the session's
state file with the skill's name and the time. The command prints the stored report: the entries kept, the entries
ignored with the reason, the values granted, and any value refused. Running it again in the same session replaces the
kept entries and adds values. A value on an entry's `never` list is refused and reported, and the rest of the grant is
recorded.

The hook grants only when all of these hold; otherwise it denies the call and grants nothing:

- The host is Claude Code, because the check needs its transcript. Codex is denied.
- The call comes from the main session: no `agent_id` on the event, so it is not a subagent, and no
  `HEI5ENBUG_PARENT_SESSION`, so it is not a worker or child.
- The main thread of the session's transcript shows that the skill started, by a command the user typed or by a `Skill`
  tool call. A start recorded in a subagent, in a tool result, or in text that a skill injected does not count.
- An installed plugin's `approval-grants.json` declares the skill. A skill name that two plugins declare needs the
  `<plugin>:<skill>` form.

The grant keeps an entry only when these hold, and ignores it otherwise:

- With every placeholder filled by an accepted value, the guard classifies the command example as a write, or as
  destructive when the entry sets `destructive: true`, and not as critical. It ignores a sensitive read, a secret
  access, and an unclassified command. A tool entry must classify as a write the same way.
- Every placeholder that reaches the target part of the key, such as a host, a database, a context, a namespace, or a
  push remote, lists its values or takes them from the grant. An open placeholder or a glob there ignores the entry.
- A push example names its remote and every refspec, uses only plain flags, and has no force or deletion form
  (`--force`, `--force-with-lease`, `-f`, `--delete`, `-d`, `--mirror`, or a refspec that starts with `+` or `:`). A
  plain `git push` reads its refspecs from configuration the guard does not read, so it is ignored.

A child process uses the grants of the session that `HEI5ENBUG_PARENT_SESSION` links it to, as it uses that session's
approved keys. A skill that starts a child runs `python3 <plugin root>/scripts/approval_guard.py link` in its own Bash
call, which prints the value for the current session, such as `claude:<session id>`. It then starts the child with that
text as the environment variable, for example `HEI5ENBUG_PARENT_SESSION=claude:<session id> claude -p ...`. A child
started without the link has no grants, and a non-interactive child asks as before.

### Matching a write or call

The guard first classifies the write as it does everywhere else. A critical write never matches. A write classified as
destructive matches only an entry with `destructive: true`. A write matches a kept entry when it is one simple command
with no pipe, redirection, shell expansion, or environment prefix, and all of these hold:

- Every literal part of the example equals the write's, including a positional argument, an option value, and the text
  around a placeholder inside one argument. The write has the same number of positional arguments.
- The write carries every option of the example, each exactly as many times as the example has it. `--option value` and
  `--option=value` are equal, and an alias such as `-n` for `--namespace` is a different option. The write may carry
  more options, except one that can change the operation or target from outside the command line: an option whose name
  names a config, file, input, kubeconfig, URL, next request, request, or output, `-K`, `-f`, `-o`, `-:`, or any extra
  option whose value starts with `@` or `file:`. An entry with `"extra_options": false` refuses every extra option: the
  write must carry exactly the entry's options, though a placeholder such as `<id>` still matches its value. The second
  entry of the example above matches `az repos pr update --id 7 --status completed --delete-source-branch false` but
  refuses the same write with `--bypass-policy true --bypass-policy-reason x` or `--auto-complete true`.
- Every filled value is accepted by its placeholder and is not on the `never` list. A placeholder that repeats takes one
  value.
- The example filled with the write's values classifies to the same key as the write. For a key that is a digest of the
  command text, such as a `git` or `gh` key, the filled example's words must equal the write's words one for one.
- A push names its refspecs explicitly, carries no force or deletion form, and no filled value contains `:` or starts
  with `+`, so `+feature/demo` and `staging-1:refs/tags/release-1` never match.

An MCP call matches a tool entry when the tool name is equal, the call carries every argument the entry lists, and each
value is accepted. A call the guard classifies as destructive matches only an entry with `destructive: true`, and a
critical call never matches. A DataGrip `execute_sql_query` call and a `mcp__tabularis__run_query` call match the same way, after
`datagrip_guard.py` and the approval guard classify the query as in [MCP and database calls](#mcp-and-database-calls): a
non-destructive write on a non-production data source or connection needs a matching entry, and a destructive statement
needs one with `destructive: true`. A production or unidentified data source or connection never matches, so its write
or statement asks as before. The grant keeps such an
entry only when its `projectPath` and `connectionId` name a non-production data source that resolves when the grant
runs.

A matching call runs without a prompt and leaves no session approval behind. The call's record for the Claude Code mod
names the skill, as `<plugin>:<skill>` in its `source` field, as the source of the approval. A write that matches no
kept entry behaves as before.

### What this trusts

The guard checks that the skill started in the main session and that the write matches a kept entry. It relies on the
declaring plugin for two things: the skill starts only on the user's request or approval, and no entry accepts or is
granted a production target. A grant is a guardrail on top of the user's approval of the skill, not a security boundary.
The kept entries and granted values last until the session ends, and a skill the user did not start never gets them.

## Protected state and code

The agent cannot approve anything itself. A Bash command that runs `approval_guard.py`, `datagrip_guard.py`,
`approval_state.py`, or one of the `approval_state_*.py`, `datagrip_sql.py`, and `guard_*.py` modules they import as a
program, with `-m`, or through Python code that imports it, is denied on both hosts. Commands naming the approval or
heartbeat state directory are denied unless every simple command is an allowed read: `ls`, `cat`, `head`, `tail`,
`grep`, `wc`, `stat`, `file`, `find`, or `echo`. `find` may use only read options such as `-type`, `-name`, `-maxdepth`,
or `-print`, and no glob characters. The command must have no braces, substitutions, assignment prefixes, or output
redirection except to `/dev/null`. The only variables allowed are `$HOME`, `${HOME}`, `$XDG_STATE_HOME`,
`${XDG_STATE_HOME}`, and `${XDG_STATE_HOME:-<absolute path>}`, and each must start a word as a path prefix followed by
`/`, as in `ls "$HOME/.local/state/hei5enbug-agent-setup/approvals"`. The guard expands them before it checks the path.
Any other `$`, `$(`, backtick, `<(`, `>(`, or brace is denied, and the denial names the trigger, for example `It was
denied because of "$(".` Plain reads of guard files, such as `cat` or `rg`, are not denied. The validated `request`,
`grant`, and `link` commands are the only execution exceptions. File edits inside either state directory, including paths
named in an `apply_patch` patch, are denied on both hosts.

Installed plugin code is protected the same way. A write into the Claude or Codex plugin caches
(`~/.claude/plugins/cache`, `$CLAUDE_CONFIG_DIR/plugins/cache`, `~/.codex/plugins/cache`) or the running plugin root is
denied on both hosts, whether it is a redirection, `tee`, `sed -i`, the destination of `cp`, `mv`, `install`, `rsync`,
or `ln`, Python code in a heredoc, `-c` option, or script file that writes, moves, or removes such a path, or a `Write`,
`Edit`, `MultiEdit`, `NotebookEdit`, or `apply_patch` call whose target lies there. The guard resolves `..`, repeated
slashes, `~`, known variables, and symbolic links before it compares, and it knows a cache both by its configured
location and by where its link leads, so a cache that links into a git work tree stays protected. Reading that code
stays allowed.

Python code in a heredoc, `-c` option, or script file that writes, moves, or removes a path in a security-sensitive
location asks every time: `~/.ssh`, `~/.aws`, `~/.gnupg`, the shell startup files `~/.zshrc`, `~/.bashrc`, `~/.profile`,
`~/.bash_profile`, and `~/.zprofile`, a `.git/hooks` folder, and the Claude and Codex settings files (`settings.json`
and `settings.local.json` in a `.claude` folder or `$CLAUDE_CONFIG_DIR`, `~/.claude.json`, and `config.toml` or
`hooks.json` in a `.codex` folder or `$CODEX_HOME`). A file or folder that is a symbolic link counts under its own name
and under its target. The guard follows the path through keyword arguments such as `dst=`, `path=`, and `target=` and
through `with_suffix`, `with_name`, and `with_stem`, which change the path. Ordinary Python writes in the work tree or
elsewhere are not asked about.

Commands that need a secret value use the secret helper: `python3 <plugin root>/scripts/secret_exec.py --secret
DB_PASSWORD=k8s:<context>/<namespace>/<secret>/<key> -- <command>`. The sources are `k8s:`, `keyvault:<vault>/<name>`,
`aws:<secret id>[#<json key>]`, and `gcp:<project>/<name>[/<version>]`. `--file VAR=<source>` passes the path of a
temporary file instead of the value. The value reaches the command only through environment variables or temporary
files, and the helper masks it in the command's output. When a fetch fails, the helper prints only the source and the
fetch command's exit code, never the fetch's stderr. Each fetch has a 30-second timeout; a timeout exits 2 and names the
source with `timed out`.

A role runner child with `HEI5ENBUG_PARENT_SESSION=<host>:<session_id>` also reads the parent's approved keys without
changing its state. Malformed values are ignored. Children cannot record codes from `UserPromptSubmit` or run `request`
or `grant`; a call that needs a session approval the parent lacks is denied with instructions to request it in the main session
(`request --key write:session` or `--key sensitive:session`) and retry. Children use the parent's `write:session` and
`sensitive:session` approvals while the parent session holds them, and Codex children never use the native window. Every
every-time action in a child is denied; the main session runs it itself. Claude children that may edit receive `Bash` in
both `--tools` and `--allowedTools`; their guard still denies unapproved writes and every-time actions.

Do not add Claude `permissions.ask` rules for covered writes: they prompt every time even after a session approval.
Claude `defaultMode: dontAsk` denies approvals the guard asks for. Codex `rules/*.rules` files of your own that `prompt`
or forbid reads the guard allows, such as `kubectl get`, still apply. [Host settings](configuration.md#host-settings)
reports these settings and never edits them.

## Hook verification and approval scope

Every event carrying a valid session ID touches `$XDG_STATE_HOME/hei5enbug-agent-setup/heartbeats/<host>-<session_id>`
and its `.<EventName>` file before the toggle check, on a best-effort basis. `PreToolUse` also writes a SHA-256 of the
hook files that host loads, `hooks/hooks.json` plus the other hook files its plugin manifest lists, as one line in
`heartbeats/confirmed-<host>`, so a change to one host's own hook file never warns the other host. When this hash is
missing or differs, `UserPromptSubmit` adds a warning once per session and records that it was shown in the session
state. The warning explains that the guard has not been seen checking a tool call since its hooks changed, asks Codex
users to trust the plugin hooks in `/hooks`, and states that writes may run without approval until then. A classifier
exception asks every time with “hei5enbug-agent-setup approval guard failed; approve only if the call looks right” and
writes one line to stderr that names the plugin and the approval guard, the exception name, and the next step. Turning the guard off still prints nothing.

The approval guard is a guardrail, not a security boundary: an agent with full shell access could bypass it. Calls the
guard does not cover follow the host's own permission flow. Approval state lives under `$XDG_STATE_HOME/hei5enbug-
agent-setup/approvals/` (default `~/.local/state`), one file per host and session. An approval lasts until its session
ends, and a session file that has been idle for 7 days is deleted when another approval is written. Set `approval_guard`
to `false`, or `HEI5ENBUG_APPROVAL_GUARD=false` on Codex, to turn the guard off. In Codex, trust the hooks in `/hooks`.

The `approval_scope` option chooses how often the guard asks. `tiered`, the default, works as described above. `session`
asks once per session: the first approval of any kind covers every later call in that session, except four kinds that
still ask every time and whose approval covers only that call. They are discarding uncommitted work (`git reset --hard`,
`git clean`, a `git checkout` or `git restore` that drops working-tree changes, and `git worktree remove --force`, and
removing files that hold uncommitted changes or untracked files that are not ignored), deleting statements on a
production database connection, production infrastructure deletion such as `kubectl delete` on a production context, and
Python that writes a security-sensitive location (see the self-approval rules above). A connection or context counts as
production when its name has a production word or no development word, so an unknown name stays production. Denied calls
stay denied in both scopes.
