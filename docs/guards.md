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
very short text always passes. A `Stop` hook asks for a rewrite when a reply fails, at most 3 times per turn. Delegated
child sessions are not checked: a session with `HEI5ENBUG_ASSIGNED_ROLE` or `HEI5ENBUG_PARENT_SESSION` set, such as a
role runner child, returns its answer to the coordinating session, which replies to the user. A `PostToolUse` hook adds
a reminder after a progress update in another language. It runs asynchronously, so the reminder reaches the model on the
next turn. Put text the user asks for in another language in a code block or block quote.

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
`origin` does. Leading `NAME=value` words apply to their own command only. A `git`
commit or tag is in scope when the `origin` of its repository is a protected repository: the checkout of the
working directory, or the git directory that the command sets with `--git-dir`, `GIT_DIR`, or `GIT_WORK_TREE`. A
`git push` is in scope when any destination it reaches is protected: an explicit URL or remote name, resolved through
the remote's push URL, or, without one, the branch's push remote and then `origin`.
Variables in these values are expanded from the command's own assignments, and a target that cannot be resolved is
treated as protected: an unresolved `--repo`, `GH_REPO`, or push destination is scanned, and an unresolved git
directory blocks. The directories that select the repository (`-C`, `--git-dir`, `--work-tree`, `GIT_DIR`, and
`GIT_WORK_TREE`) are not scanned as published text.

A write that reads its body from stdin, such as `--body-file -`, `-F -`, or `git commit -F -`, is scanned with its
source: a heredoc as part of the command, a pipeline's earlier commands, including ones on earlier lines that end with
`|`, with the files that a `cat` or a `<` redirect names after wildcard expansion, and `echo` or `printf` text. Any other command that feeds the pipeline blocks the write, because its output
cannot be checked before it runs. The hook also blocks a `git` or `gh` command when its scanner is missing or fails.

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
