# Orca worktree status

Read this before the first file change of a task in a session that runs in an Orca terminal, which
`ORCA_TERMINAL_HANDLE` marks, and again before that task's final report. Keep the session's Orca worktree and tab
named for its task, and remove the finished child worktrees it leaves behind.

No hook or session writes a board status, a worktree comment, or the unread flag on its own; the user sets them, or
approves such a write in a request, such as the resume note of `session-triage`. The one exception is `completed` in "Cleanup when the task ends". Orca itself notifies the user when a session asks a question.

Find the worktree with `orca worktree current --json` and name it with
`orca worktree set --worktree id:<worktree id> --display-name <name> --json`. These flags change only Orca metadata,
never files, Git state, or a running terminal. Never update a worktree created for another session's task.

## Name

In a worktree created for the task, set `--display-name "<ticket key> <short summary>"`, or a short task name without
a ticket, when the task starts. Change it again only when the task's scope changes, and only while the worktree shows
`displayNameMode: automatic` or still carries the name this session last set; any other name is the user's, so keep it.

## Tab title

At the same events as the display name, and in the main clone too, set the session's own tab title with
`orca terminal rename --terminal "$ORCA_TERMINAL_HANDLE" --title "<ticket key> <short summary>" --json`, or a short
task name without a ticket. In the main clone the tab title is the only place that names the task. The plugin hook
shows the session its last set title with each prompt: when a prompt asks for work the title does not name, retitle the
tab before starting it, and keep a title the user said they set by hand.

When the plugin's Stop hook names a name or tab title command, run it and end the turn without repeating the reply.

## Cleanup when the task ends

Before its final report, check each child worktree of the session's own repository and each worktree, in any
repository, of the task's ticket group, whichever session started it. The group is every worktree that carries the
ticket's issue link as a reference or its exact key in its display name or branch. Run both lookups of "Grouping" in
[Orca worktree groups](orca-groups.md), the reference lookup and the exact-key search, and check the worktrees of
both, even when the reference lookup finds some. A task with no ticket checks only the repository's child worktrees.
Never remove a main clone, the current worktree, a worktree with child worktrees, or a remote branch.

A worktree is finished when its base holds the content of every commit of its branch, including commits applied under
another hash, and it has no terminal or only idle ones with no open question, or when no agent session runs in it and
its branch is pushed: after `git fetch`, `git rev-list --count @{upstream}..HEAD` is 0, so a branch with no upstream
does not pass. For a finished worktree:

1. Confirm that `git status --porcelain` is empty and that `git status --porcelain --ignored` lists only regenerable
   caches or build output, such as `__pycache__`, `.pytest_cache`, or `node_modules`.
2. Close its terminals, which `orca terminal list --worktree id:<worktree id> --json` lists, with
   `orca terminal close --terminal <handle> --json`, or `orca orchestration worker-release --dispatch <id> --json`
   for a worker.
3. Confirm that no process has its working directory inside, for example with `lsof -d cwd -Fpn`, and that
   `orca ports --worktree id:<worktree id> --json` lists no listener. Stop a process that the worktree's own session
   started. Closing a terminal does not stop a process that detached into a session of its own, such as a daemon or a
   container.
4. Remove the worktree and its local branch with `orca worktree rm --worktree id:<worktree id> --delete-branch --json`.

A process that is left keeps the worktree and its branch in place, and the report names it. A worktree that is not
finished or fails a check stays as it is, with no question, and the report lists it with the reason, such as a commit
that is not pushed or the failed check.

Then set `completed` with `orca worktree set --worktree id:<workspace id> --workspace-status completed --json` on each
workspace in that scope that the session keeps and that has no terminal of any kind, so no Claude Code or Codex
session and no shell, and no uncommitted or unpushed change, such as a main clone or the ticket's folder. Orca stores
any status id without checking it: when a worktree of the same repository already carries an id other than `todo`,
`in-progress`, `in-review`, or `completed`, the board is customized, so leave its status unchanged. A plugin hook
denies `completed` for a worktree with uncommitted or unpushed work. The report names every worktree the session
checked: each removed one, and each kept one with its reason.
