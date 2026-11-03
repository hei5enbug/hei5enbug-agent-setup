# Orca worktree status

Read this before the first file change, pull request, or blocking question of a task in a session that runs in an
Orca terminal, which `ORCA_TERMINAL_HANDLE` marks. Keep the session's Orca worktree showing what the session is doing
and whether it still has work, so the sidebar and the board answer that without reading each terminal.

Find the worktree with `orca worktree current --json` and update it with
`orca worktree set --worktree id:<worktree id> <flags> --json`. These flags change only Orca metadata, never files,
Git state, or a running terminal. Update on the events below only, never by polling, and never update a worktree
created for another session's task.

## Name

In a worktree created for the task, set `--display-name "<ticket key> <short summary>"`, or a short task name without
a ticket, when the task starts. Change it again only when the task's scope changes, and only while the worktree shows
`displayNameMode: automatic` or still carries the name this session last set; any other name is the user's, so keep it.
Never rename the repository's main clone, the entry with `isMainWorktree: true`, which other sessions share.

## Board status and comment

| Event | `--workspace-status` | `--comment` |
|---|---|---|
| The session starts working, or review feedback reopens the work | `in-progress` | the current step |
| The session opens a pull request or requests review | `in-review` | the pull request or review it waits for |
| The session waits on the user, such as a decision or an approval | unchanged | what it waits for, plus `--unread` |
| A blocker stops the work | unchanged | the blocker |
| The work the session was assigned has nothing left at all, whatever the last step was | `completed` | the final result |

A merge alone does not complete the work while a deployment, a verification, or a reply assigned to the session
remains. The comment is one line.

Orca stores any status id without checking it and lists no board columns. Use only the default ids `todo`,
`in-progress`, `in-review`, and `completed`. When a worktree of the same repository already carries another id, the
board is customized: leave the status unchanged and keep only the comment current.

In the main clone, update the status and the comment the same way; the last session to update it wins.

In a group of worktrees for one ticket, each session updates its own worktree, and the root also follows "Status" in
[Orca worktree groups](orca-groups.md).
