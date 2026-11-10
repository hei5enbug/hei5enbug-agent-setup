# Response language, DataGrip, and public boundary guards

This page explains how response-language checks, DataGrip query safeguards, and the public boundary check behave on
each host.

## Response language

A language guard, `scripts/language_guard.py`, checks that every reply and every progress update is written in the
response language. Claude Code takes the language from the `language` setting, read from the local project settings,
then the project settings, then the user settings; without one, nothing is enforced. Codex reads
`HEI5ENBUG_RESPONSE_LANGUAGE` and uses Korean when it is unset. Only languages with a distinctive script are checked:
Korean, Japanese, Chinese, Russian, Ukrainian, Greek, Arabic, Hebrew, Thai, and Hindi. For any other language, such as
English or French, the instruction alone applies.

The check ignores code, quotes, and URLs. A text passes when at least 30% of its letters are in the target script, and
very short text always passes. A `Stop` hook asks for a rewrite when a reply fails, at most 3 times per turn. Claude
Code shows that request as `Stop hook feedback`, not as a hook error, and Codex receives it as a continuation prompt.
Delegated child sessions are not checked: a session with `HEI5ENBUG_ASSIGNED_ROLE` or `HEI5ENBUG_PARENT_SESSION` set,
such as a role runner child, returns its answer to the coordinating session, which replies to the user. A `PostToolUse`
hook adds a reminder after a progress update in another language, before the model's next request in the same turn.
Claude Code runs it synchronously, because it adds a background hook's output to the same turn only when the hook
finishes before the next model request. Codex runs it in the background and adds its output to the next model request
of the turn. Put text the user asks for in another language in a code block or block quote.

## DataGrip query guard

A `PreToolUse` hook on both hosts and a `PermissionRequest` hook on Codex only, both `scripts/datagrip_guard.py`, run
before the DataGrip MCP tool `execute_sql_query`. The guard reads the connection from `.idea/dataSources.xml` in the
DataGrip project that `projectPath` names. PostgreSQL and SQL Server reads on non-production, recognized connections run
without approval, and PostgreSQL reads run inside a read-only transaction with `SET LOCAL statement_timeout = '60s';`. A
production connection needs a recorded plan before a PostgreSQL read and gets lock safeguards on a SQL Server read; see
the [production read rules](approval-guard.md#production-database-reads). With `approval_guard` on, non-destructive
PostgreSQL and SQL Server writes share the session write approval (`write:session`) with all other writes. Unknown
connections, other database types, and text the guard cannot parse use that approval too; a `승인` in a connection name
has no effect of its own. A statement whose code names `delete`, `drop`, or `truncate`, and statements the SQL
classifier treats as destructive, including those led by `DO`, `EXEC`, `EXECUTE`, or `CALL`, ask every time. The code is
the text left after string literals, comments, and quoted or bracketed identifiers are removed, so a `SELECT` that only
mentions `delete` in one of them stays a read. On a non-production PostgreSQL connection (see [production database
reads](approval-guard.md#production-database-reads)), when the `pglast` parser confirms the text, a `DELETE` whose own
statement has a `WHERE`, and a `DO` block whose body parses as PL/pgSQL and has no `DROP`, `TRUNCATE`, `EXECUTE`,
`ALTER`, `GRANT`, `REVOKE`, `CALL`, nested `DO`, `DELETE` without `WHERE`, or risky function call (`set_config` and
`pg_sleep` are allowed there, quoted names included in the check), are session writes instead. SQL Server, which allows
statements without semicolons, and text the parser cannot confirm keep asking every time. SQL Server reads may also
carry `SET NOCOUNT`, `LOCK_TIMEOUT`, `DEADLOCK_PRIORITY`, `TRANSACTION ISOLATION LEVEL READ UNCOMMITTED|READ
COMMITTED|SNAPSHOT`, `ARITHABORT`, `ANSI_NULLS`, `ANSI_WARNINGS`, `ANSI_PADDING`, `QUOTED_IDENTIFIER`,
`CONCAT_NULL_YIELDS_NULL`, `XACT_ABORT`, `STATISTICS IO|TIME`, and `SHOWPLAN_XML|ALL|TEXT` statements. On Codex, a write
opens Codex's native approval window when it is ready, and is denied with a code otherwise; an every-time query is
always denied with a code; see [Approval guard](approval-guard.md#approval-guard). With the toggle off, every write asks
as before. In Codex, trust the hook in `/hooks`.

Optionally, install the `pglast` parser once:

```bash
uv venv --python 3.12 "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser"
uv pip install --python "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser/bin/python" pglast==8.4
```

Without it, PostgreSQL falls back to a stricter text check that may ask more often but still never lets a write run
without approval.

## Public boundary check

A `PreToolUse` hook on `Bash` calls `scripts/public_boundary_hook.py` in every project on both hosts, with the
`approval_guard` option on or off. It loads the scanner from the plugin's `.githooks/` folder and blocks a `git` or
`gh` write before it runs when the text, commits, or tags it would publish contain a home path, a secret shape, an
email address, or a private word. The block reports each finding's kind and location, never the matched value. A
command that has no `git` or `gh` word, a read-only command, and a command aimed at another repository pass with no
output; nothing beyond the standard library loads until a `git` or `gh` word appears.

A repository is protected when an installed plugin declares it public: its root `issue-target.json` has
`"public": true` and a `tracker` of kind `github` with the location `<owner>/<repo>`. Installed plugins are those in
Claude Code's `plugins/installed_plugins.json` under `CLAUDE_CONFIG_DIR` (default `~/.claude`), the newest cached
version of each plugin under `plugins/cache/<marketplace>/<plugin>/<version>` in `CODEX_HOME` (default `~/.codex`),
and the running plugin's own root (`CLAUDE_PLUGIN_ROOT`, or `PLUGIN_ROOT` on Codex). A `gh` write is in scope when
`--repo` or `-R` names a protected repository, or, without it, when `GH_REPO` does (set inline for that command, by an
earlier `export` in the same command, or in the hook's environment), or, without either, when the working directory's
`origin` does. An issue or pull-request URL operand, such as `gh issue comment <url>`, names its own repository, and the
`{owner}` and `{repo}` placeholders of a `gh api` endpoint take `GH_REPO` or the `origin` of the working directory, as
`gh` does. A repository name that carries a host protects only the `github.com` repository: `git.example.com/<owner>/<repo>`
is a different repository. A repository given without a host, and the current repository, take the host that `GH_HOST`
sets, inline, by `export`, or in the hook's environment, and `github.com` otherwise. A `gh` close, reopen, or merge that leaves a comment or message is a write too. Leading `NAME=value` words apply to their own command only. A `git`
commit or tag is in scope when the `origin` of its repository is a protected repository: the checkout of the
working directory, or the git directory that the command sets with `--git-dir`, `GIT_DIR`, or `GIT_WORK_TREE`. A
`git push` is in scope when any destination it reaches is protected: an explicit URL or remote name, resolved through
the remote's push URL, or, without one, the branch's push remote and then `origin`. A push scans every commit reachable
from each ref it sends: HEAD when it names none, and every local branch as well when `push.default=matching` or a
`remote.<name>.push` setting may send more; every branch for `--all`; tags for `--tags`; and HEAD and every branch
for a named ref that does not exist yet. Redirections such as `2>&1` are not refs. It leaves out only the
remote-tracking refs of a configured destination remote that is protected, so a commit an unrelated remote already
holds is still scanned.
Variables in these values, including those in `git -c` settings, are expanded from the command's own assignments, and a
target that cannot be resolved is treated as protected: an unresolved `--repo`, `GH_REPO`, or push destination is
scanned, and an unresolved git directory blocks, as does an unresolved `-C` or `cd` value before a `git` write or a
`gh` write that does not name its repository. The directories that select the repository (`-C`, `--git-dir`, `--work-tree`, `GIT_DIR`, and
`GIT_WORK_TREE`) are not scanned as published text.

A write that reads its body from stdin, such as `--body-file -`, `-F -`, or `git commit -F -`, is scanned with its
source: a heredoc as part of the command, a pipeline's earlier commands, including ones on earlier lines that end with
`|`, with the files that a `cat` or a `<` or `0<` redirect names after wildcard expansion, and `echo` or `printf` text.
Any other command that feeds the pipeline blocks the write, because its output cannot be checked before it runs. A body
or message built with a command substitution is scanned when the substitution is a heredoc, an `echo` or `printf`
with literal text, or a `cat` of named files, and blocks otherwise. An input file that is not a regular file, such as
a named pipe, and a file whose name cannot be resolved also block the write, without waiting on the file. A `gh api`
`-f` or `--raw-field` value is literal text, and only `-F` or `--field` reads an `@file`. The hook also blocks a `git` or `gh` command when its scanner is missing or fails.

The hook blocks these forms because it cannot check what they would publish: an unresolved `cd` or `git -C` directory, a
command substitution other than a heredoc, a literal `echo` or `printf`, or a `cat` of named files, an unresolved stdin
file name, and an input file that is not a regular file. Write the path literally, or pass the body through a heredoc or
a file, instead.

Private words come from the file `HEI5ENBUG_PUBLIC_BOUNDARY_WORDS` names, and from every installed plugin that
declares one in a root file `public-boundary.json`, exactly `{"version": 1, "private_words_file": "<path>"}`. The path
is relative and must stay inside that plugin root; a text word file holds one word or phrase per line, with `#` comment
lines, and a `.json` file holds `words`, optional `patterns`, and optional `allowed_identity_emails`, as
[the declaration](development.md#private-word-list-declaration) describes. An invalid declaration or an unreadable
file is reported as a problem that names the plugin and the reason, never a word, and the write is blocked because it
could not be checked. This repository never holds a list.

When a public write is scanned and no list was found, the hook says so each time. A write that passes prints JSON with
`systemMessage` for the user and `hookSpecificOutput.additionalContext` for the model; a blocked write adds the same
sentence to the error output.

The project hooks in `.claude/settings.json` and `.codex/hooks.json` stay for a session in a checkout of this
repository whose installed plugin is older or missing, so both hooks may run for one call there.
The `skill-issue-creator` skill calls `skills/skill-issue-creator/scripts/scan_draft.py` to scan an issue draft with
the same scanner before it is posted. It also reads the list that the plugin owning the tracker declares, passed as
`--plugin-root`, even when that plugin is not installed.

## Required checks at commit and push

A `PreToolUse` hook on `Bash`, `scripts/required_checks_hook.py`, runs on both hosts. When a command runs `git commit`
or `git push`, including with global options such as `-C` or `-c`, or inside `&&`, `;`, `|`, or a subshell, it adds one
reminder to the model's context: before a commit or push, the reply lists each check that the project instructions or a
changed skill require, as done or as not done with its reason, and a check not done is never waived by judging the
change small. Any other command, malformed input, and a missing command produce no output. The hook never blocks or
approves anything; it only adds context. It exists because, in 7 of 1,259 Claude Code main sessions between 2026-10-04
and 2026-11-03, the agent finished, committed, or pushed with a required check skipped by its own judgment or offered
instead of run.

## Orca session start

A `PreToolUse` hook on `Bash` and `EnterWorktree`, `scripts/orca_placement_hook.py`, runs on both hosts. A command that
has no reason to be denied produces no output, and so do text that only mentions these words, malformed input, and a
missing command. The hook also checks the inside of a `$(...)` or backtick command substitution, and in a
here-document body checks only such substitutions. On Codex, trust the hook in `/hooks`.

- **Top-level worktree.** `orca worktree create` with `--no-parent`, or `orca orchestration worker-start` with
  `--worktree new-top-level`, is denied with the parent to use instead, following "Session placement" in
  `instructions/cross-repository.md`. Moving an existing worktree to the top level with `orca worktree set --no-parent`
  stays allowed for a repository with no workspace or an explicit user request. It exists because on 2026-11-06 a
  coordinating session created three worktrees for two tickets with `--no-parent` and no ticket reference, so
  `orca reference find` found none of them and later sessions could not join the group.
- **Parent of another repository.** `orca worktree create`, a `worker-start` that creates a worktree with
  `--worktree new-child`, and `orca worktree set --parent-worktree` are denied when the parent belongs to another
  repository than the worktree, because each worktree sits under its own repository's workspace and a ticket's
  worktrees are tied by reference, name, and Run (`instructions/orca-groups.md`). The hook compares Orca repository
  ids from `id:<repoId>` and `id:<repoId>::<path>` selectors, and Git directories for `path:` selectors; `active` is
  the current worktree, whose repository id it reads once from `orca worktree current`. A name or branch selector, an
  unreadable repository, or an unreadable Orca allows the command.
- **Done with work left.** `orca worktree set --workspace-status completed` is denied when the target worktree, the
  current one or one that a `--worktree` selector names by `id:<repoId>::<path>` or `path:`, has uncommitted changes or
  commits its upstream lacks, and the reason lists what remains. A clean worktree, another status, or a target that
  cannot be resolved is allowed.
- **Worktree the host creates.** In an Orca terminal, `EnterWorktree` without a `path` creates a worktree that Orca
  never lists, so it is denied with the `orca worktree create` command to use. Entering an existing `path`, and any
  call outside Orca, stays allowed.
- **Main clone name.** `orca worktree set --display-name` with a non-empty name is denied when every worktree its
  `--worktree` selector names is a repository's main clone in `orca worktree list`; `active` and `current` are read
  from `orca worktree current`. Every session in a main clone would otherwise show under one task's name, so the
  reason names `orca terminal rename` for labeling the session. An empty name, which restores Orca's automatic name,
  an unlisted target, and an unreadable Orca are allowed. It exists because on 2026-11-06 a session pinned a ticket
  name on its repository's main clone, which a written rule already forbade.
- **Low memory.** A command that starts an agent session through Orca is denied when the available memory is below the
  `session_memory_min_mb` option, 2048 MB by default, so the agent queues the session and starts it after another one
  finishes instead of pushing the machine into swap. It covers `orca worktree create` with `--agent`,
  `orca orchestration worker-start`, `orca agent launch`, and `orca terminal create` whose `--command` runs `claude`
  or `codex`, also after a prefix such as `cd '<path>' &&`, and it checks inside a command substitution but not
  inside single quotes or after an escaped `$`; nothing else is gated. The placement denies take precedence when both
  apply. Available memory comes from the macOS memory-pressure free percentage times physical memory, or from
  `MemAvailable` on Linux, and is read only after such a command is found. When it cannot be read within one second,
  or on another platform, the command is allowed. Set the option to `0`, `off`, `false`, or `no` to turn the rule off;
  a value that is not a non-negative integer uses 2048. On Codex, set `HEI5ENBUG_SESSION_MEMORY_MIN_MB`.

## Orca status

One hook script, `scripts/orca_status_hook.py`, keeps the session's Orca worktree in step with its work. It runs only
when `ORCA_TERMINAL_HANDLE` is set, never in a subagent or an assigned worker, and any failed read of Orca, Git, or
the transcript lets the event pass. It reads Claude Code transcripts only, because Codex records tool calls as script
text, so on Codex only the writes that follow a tool call or a prompt apply, and the session writes the question row
itself as `instructions/orca-worktree-status.md` says. A question tool call answered in the same turn writes nothing.

The writes need no model turn and apply to the session's own current worktree. Each happens at most once per event.

| Event | Hook | Write |
|---|---|---|
| A pull or merge request is created: `gh pr create`, `az repos pr create`, `glab mr create`, and the tool output shows its link or Azure DevOps request id; `--help`, `-h`, and `--dry-run` never count | `PostToolUse` | Status `in-review`, comment `Waiting for review: <link>` |
| A turn ends with a question, its last line ending in `?`, and ran no `orca worktree set` | `Stop` | `--unread`, comment `Waiting for you: <first line, about 80 characters> · <earlier comment>` |
| The user's next prompt, while the comment is still the one the hook wrote | `UserPromptSubmit` | The earlier comment, kept in the session's state file |
| An edit, or `git commit`, inside the current worktree, whose status is `completed`, `todo`, or unset; a commit counts where `git -C <dir>` or a leading `cd <dir> &&` puts it | `PostToolUse` | Status `in-progress`, comment unchanged |

Labels are Korean (`리뷰 대기`, `답변 대기`) when the Claude Code `language` setting names Korean, and English
otherwise. A status id outside the four defaults is left alone: the board is customized, so only the comment is
written. After a check inside the worktree, the resumed-work write waits 60 seconds before it reads Orca again; an
edit or commit elsewhere neither writes nor starts that wait. The `orca_status_writes` option turns these writes off,
in `/config` on Claude Code and with `HEI5ENBUG_ORCA_STATUS_WRITES` on Codex. The state lives in
`$XDG_STATE_HOME/hei5enbug-agent-setup/orca-status/<session id>.json`.

Two things still need the model, so the `Stop` hook keeps the turn going once per state with a reminder of at most two
sentences that names the exact command and asks the model to end the turn without repeating the reply. Claude Code shows
that reminder as `Stop hook feedback`, not as a hook error. A task worktree that is not the main clone, still shows its
automatic name, and has a file edited or committed in this session is reminded of `orca worktree set --display-name`. A
session that ran `orca worktree set` and never `orca terminal rename` is reminded of the tab title; when both apply, one
reminder carries both commands. Each reminder fires at most once per session, and a stop that continues from a hook
never gets another. One reminder costs about 265,000 cache-read and output tokens on one measured machine, so these are
the only recurring model cost. Orca cannot report a tab title, so the hook judges the title only by the session's own
`orca terminal rename` commands.
