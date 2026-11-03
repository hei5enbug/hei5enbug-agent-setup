# Orca worktree groups

Read this before starting Orca sessions for a task that changes more than one repository, and before a later session
joins such a task. A group is every Orca worktree created for one ticket or issue, identified by its key or link, or
for the current request when there is none. A single-repository task follows [cross-repository work](cross-repository.md)
alone.

## Grouping

- The root is the worktree of the session that starts and coordinates the task. It stays where "Session placement"
  puts it. Which repository deploys or merges first decides that order, not the root.
- Before creating anything for a ticket, run `orca reference find <issue link or ticket key> --json`. When it lists
  worktrees, the group exists: its root is the listed worktree whose `parentWorktreeId` is not another listed one, and
  new members go under it. A bare Jira key needs Orca's Jira connection; when it finds nothing, retry with the full
  issue link. Otherwise this session's worktree becomes the root.
- From the root session, start each other repository's member as a worker of the root's orchestration Run, so it
  becomes the root's child and can ask and report:
  `orca orchestration worker-start --worktree new-child --repo id:<repoId> --name <branch> --base-branch <base>
  --agent <host> --task-title "<ticket key> <repository>" --spec-file <brief file> --json`. Choose the branch and base
  as in step 2 of cross-repository work, apply its step 4 to the branch that `orca worktree list` shows, and write the
  brief as its step 6 does. When `orca orchestration run-list --json` lists a Run whose objective starts with the
  ticket key, pass `--run <run id>` so every member joins it; otherwise create it first with
  `orca orchestration run-create --objective "<ticket key> <summary>" --json` so a later session can find it.
- Attach the ticket to every member, the root included: `--reference <link or key>` on `orca worktree create`, or
  `orca reference add` for a worktree created without it.
- A later session that joins the group creates its worktree with `orca worktree create --repo id:<repoId> --name
  <branch> --base-branch <base> --agent <host> --parent-worktree id:<root id> --reference <link or key> --json`, hands
  off as cross-repository work does, and tells the root through the root's Run, found by its objective in
  `orca orchestration run-list --json`.
- One coordinating session may cover several tickets: each ticket's worktrees sit under that session's worktree and
  carry their own reference. Another ticket otherwise gets its own group.
- A repository whose part is done in its main checkout cannot be a member. Leave it there, name it in the root's
  status, and move the work to a worktree only when the user asks.
- Never reparent a worktree on your own. Move the root only when the user asks, with
  `orca worktree set --worktree <member> --parent-worktree <new root>` for each member.
- A parent and its child must share an execution host; for a repository on another host, use the per-repository
  placement in cross-repository work.

## Sharing

- A member shares, as soon as it knows, anything another member's work depends on: a contract, schema, or API change,
  a decision, a pull request link, a deployment or merge order, or a blocker. It never shares routine progress.
- A worker sends it with `orca orchestration send --to @all --subject <topic> --body <text> --json`, which reaches the
  other members, and with no `--to`, which reaches the root's Run. The root sends to one member with
  `--to dispatch:<id>`. A member that is not a worker sends to `run:<run id>`. Never address a terminal handle, except
  for the answer in the next bullet: that mailbox is lost when the terminal closes. Never type a shared change into
  another session's input line; any terminal send still follows "Messaging another session".
- A member that needs another member's answer to continue asks the root and ends its turn. A worker runs
  `orca orchestration ask --question <text>`, and the root answers with
  `orca orchestration reply --id <message id> --body <text>`. `ask` fails outside a Dispatch, so a member that is not a
  worker sends `orca orchestration send --to run:<run id> --from $ORCA_TERMINAL_HANDLE --subject "Question: <topic>"
  --body <text> --json` and waits with `orca orchestration check --terminal $ORCA_TERMINAL_HANDLE --wait --timeout-ms
  1800000 --json`, in the background when the host notifies on background completion; the root answers it with
  `orca orchestration send --to <that member's terminal handle> --subject "Answer: <topic>" --body <text> --json`
  while that terminal waits. The root answers only when the answer follows from the task or the user's instructions;
  otherwise it asks the user.
- Before each next step, a member reads its new mail when Orca woke it with mail, and acts on any shared change first.

## Status

- The root keeps a table of its members: repository, worktree, branch, pull request, checks, and open blockers.
- It updates the table on events, such as `worker_done`, a question, or a shared change, and reads a member with
  `orca orchestration worker-read` only after a long silence, never by continuous polling.
- It never answers a member's approval prompt or a question meant for the user; it reports it to the user.
- Before the root stops, for example at a usage limit, it writes the table into a resume note under
  [pause and resume](pause-and-resume.md), so a resumed session continues from it.
- The root's own board status is the group's summary under [Orca worktree status](orca-worktree-status.md): it becomes
  `completed` only after every member is `completed` and the root itself has nothing left.

## Cleanup of finished members

When a member's status becomes `completed`, the root cleans it up at once, whichever session started it. When the
root itself finishes, it sweeps the whole group once more for a `completed` member it missed. This replaces "After the
handoff" in cross-repository work for group members; its checks still apply: the terminal is idle with no open
question, the worktree has no uncommitted change, the base holds the branch's content, and ignored files are only
regenerable caches or build output. When a check fails, remove nothing and ask the user once.

1. Have the member stop its own background work, such as background shell tasks and monitors, and confirm none remain.
2. Find the listeners tied to the member's worktree with `orca ports --worktree id:<worktree id> --json`, and the
   processes whose working directory is inside it, for example with `lsof -d cwd -Fpn`. Stop those that the member's
   terminal or session started. Report a process the session did not start, such as one the user runs there, and leave
   it running unless the user approves. Closing a terminal stops the processes of its session, `nohup` jobs included,
   but not a process that detached into a session of its own, such as a daemon or a container.
3. Close the member's terminal: `orca orchestration worker-release --dispatch <id> --json` for a worker, otherwise
   `orca terminal close --terminal <handle> --json`.
4. Remove its worktree and local branch with `orca worktree rm --worktree id:<worktree id> --delete-branch --json`.

Afterwards confirm that no terminal, process, or listener of the member remains, and report each item closed. For a
member that worked in a main checkout, stop only its background work, processes, and terminal; never touch the
checkout or its default branch.

Never remove the root, or offer to, while a member remains: Orca removes a parent at once, and its children lose their
lineage and become top-level entries.
