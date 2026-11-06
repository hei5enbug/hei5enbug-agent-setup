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

## Tab title

At the same events as the display name, and in the main clone too, set the session's own tab title with
`orca terminal rename --terminal "$ORCA_TERMINAL_HANDLE" --title "<ticket key> <short summary>" --json`, or a short
task name without a ticket. In the main clone the tab title is the only place that names the task. Orca does not report
a tab title back: keep one only when the user said they set it themselves, and otherwise replace it when the task
changes.

## Board status and comment

| Event | `--workspace-status` | `--comment` |
|---|---|---|
| The session starts working, or review feedback reopens the work | `in-progress` | the current step |
| The session opens a pull request or requests review | `in-review` | the pull request or review it waits for |
| The session waits on the user, such as a decision or an approval | unchanged | what it waits for, plus `--unread` |
| A blocker stops the work | unchanged | the blocker |
| Nothing of the assigned work is left, as defined below | `completed` | the final result |

`completed` means all of these hold: no pull request of the task waits for review or merge, no deployment,
verification, reply, or user decision remains, the worktree has no uncommitted or unpushed change, and no background
task of the session runs for it. A merge alone does not complete the work. A plugin hook denies `completed` for a
worktree with uncommitted or unpushed work. The comment is one line.

In Claude Code the plugin hook writes three of these itself, so do not repeat them there: `in-review` with the
request's link right after a pull or merge request is created; `--unread` with a comment that starts with a waiting
label and the question's first line when a turn ends with a question as its last line, which the next prompt of the
user restores to the earlier comment; and `in-progress` when an edit or commit in this worktree resumes work on a
worktree marked `completed`, `todo`, or unset. On a host where the hook cannot write a row, such as Codex for the
question row, whose transcripts it cannot read, write that row yourself as the table says. Write the other rows
yourself, and a pull request the hook did not see, such as one opened in a browser.

When the plugin's Stop hook names a name or tab title command, run it and end the turn without repeating the reply.

Orca stores any status id without checking it and lists no board columns. Use only the default ids `todo`,
`in-progress`, `in-review`, and `completed`. When a worktree of the same repository already carries another id, the
board is customized: leave the status unchanged and keep only the comment current.

In the main clone, update the status and the comment the same way; the last session to update it wins.

In a group of worktrees for one ticket, each session updates its own worktree, and the coordinator also follows
"Status" in [Orca worktree groups](orca-groups.md).
