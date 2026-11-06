# Orca worktree groups

Read this before starting Orca sessions for a task that changes more than one repository, and before a later session
joins such a task. A group is every Orca worktree created for one ticket or issue, identified by its key or link, or
for the current request when there is none. Every worktree sits under its own repository's workspace, never under
another repository's worktree; the ticket ties the group together, not Orca's lineage. A single-repository task
follows [cross-repository work](cross-repository.md) alone.

## Grouping

- The coordinator is the session that starts the task, wherever it runs. Which repository deploys or merges first
  decides that order, not the coordinator.
- Tie every member, the coordinator's own worktree included, in three ways: `--reference <issue link>`, a display name
  that starts with the ticket key, and one orchestration Run whose objective is `<ticket key> <summary>`. The full
  issue link needs no Jira connection; add it to a worktree created without it with `orca reference add`. When
  attaching still fails, keep the ticket key in the branch or display name and report the failure.
- Before creating anything for a ticket, look for its group: `orca reference find <issue link> --json`, where a bare
  ticket key works only while `orca jira connection --json` reports `connected: true`, and, when that lists none,
  `orca worktree list --json` for a display name or branch that contains the exact ticket key, not a longer key that
  begins with it. Find the Run with `orca orchestration run-list --json` by its objective: the ticket key, a space, and
  the summary; a longer key that only begins with the same characters is another ticket. When no Run exists, the
  coordinator creates it with `orca orchestration run-create --objective "<ticket key> <summary>" --json`.
- The coordinator makes each other repository's member a worker of the Run, so it can ask and report. Choose the branch
  and base as in step 2 of cross-repository work. Create the worktree without an agent under that repository's own
  workspace, `orca worktree create --repo id:<repoId> --name <branch> --base-branch <base> --parent-worktree
  id:<repoId>::<clone path> --reference <issue link> --json`, apply step 4 of cross-repository work, confirm the branch
  in `orca worktree list`, and set the display name. Only then start the worker, so it never runs before its branch is
  final: `orca orchestration worker-start --worktree path:<worktree path> --agent <host> --run <run id> --task-title
  "<ticket key> <repository>" --spec-file <brief file> --json`, with the brief written as step 6 of cross-repository
  work does.
- A later session that joins creates its worktree the same way with `--agent <host>`, hands off as cross-repository
  work does, and tells the coordinator through the Run.
- Start a member only when it can finish its part without waiting on another member. When its part needs a contract,
  schema, API, or decision that another member has not shared yet, create neither its worktree nor its worker: list it
  in the status table as waiting on that item, and start it once the item is shared. Start members without such a
  dependency together. When the plugin denies a start for low memory, list the member as waiting for memory and start
  it after another member finishes or is cleaned up, never polling memory.
- One coordinating session may cover several tickets; each ticket has its own reference, names, and Run.
- A repository whose part is done in its main checkout cannot be a member. Leave it there, name it in the
  coordinator's status, and move the work to a worktree only when the user asks.

## Sharing

- A member shares, as soon as it knows, anything another member's work depends on: a contract, schema, or API change,
  a decision, a pull request link, a deployment or merge order, or a blocker. It never shares routine progress.
- A worker sends it with `orca orchestration send --to @all --subject <topic> --body <text> --json`, which reaches the
  other members, and with no `--to`, which reaches the coordinator's Run. The coordinator sends to one member with
  `--to dispatch:<id>`. A member that is not a worker sends to `run:<run id>`. Never address a terminal handle, except
  for the answer in the next bullet: that mailbox is lost when the terminal closes. Never type a shared change into
  another session's input line; any terminal send still follows "Messaging another session".
- A member that needs another member's answer to continue asks the coordinator and ends its turn. A worker runs
  `orca orchestration ask --question <text>`, and the coordinator answers with
  `orca orchestration reply --id <message id> --body <text>`. `ask` fails outside a Dispatch, so a member that is not a
  worker sends `orca orchestration send --to run:<run id> --from $ORCA_TERMINAL_HANDLE --subject "Question: <topic>"
  --body <text> --json` and waits with `orca orchestration check --terminal $ORCA_TERMINAL_HANDLE --wait --timeout-ms
  1800000 --json`, in the background when the host notifies on background completion; the coordinator answers it with
  `orca orchestration send --to <that member's terminal handle> --subject "Answer: <topic>" --body <text> --json`
  while that terminal waits. The coordinator answers only when the answer follows from the task or the user's
  instructions; otherwise it asks the user.
- Before each next step, a member reads its new mail when Orca woke it with mail, and acts on any shared change first.

## Status

- The coordinator keeps a table of the members: repository, worktree, branch, pull request, checks, and open blockers,
  and for a member not started yet, the item it waits for.
- It updates the table on events, such as `worker_done`, a question, or a shared change, and reads a member with
  `orca orchestration worker-read` only after a long silence, never by continuous polling.
- It never answers a member's approval prompt or a question meant for the user; it reports it to the user.
- Before the coordinator stops, for example at a usage limit, it writes the table into a resume note under
  [pause and resume](pause-and-resume.md), so a resumed session continues from it.
- A member is finished when its board status is `completed`, or, on a board that Orca worktree status leaves
  unchanged because it is customized, when the member's final report says its work is done with nothing left.
- The coordinator's own board status is the group's summary under [Orca worktree status](orca-worktree-status.md): it
  becomes `completed` only after every member is finished and the coordinator itself has nothing left.

## Cleanup of finished members

When a member is finished, the coordinator cleans it up at once, whichever session started it. When the coordinator
itself finishes, it sweeps the whole group once more for a finished member it missed. This replaces "After the
handoff" in cross-repository work for group members; its checks still apply: the terminal is idle with no open
question, the worktree has no uncommitted change, the base holds the branch's content, and ignored files are only
regenerable caches or build output. When a check fails, remove nothing and ask the user once.

A member whose session has ended is cleaned up the same way before its pull request merges, once its work is on the
remote: apply the unused-worktree condition under "After the handoff" in cross-repository work, with this member's
steps below and the coordinator's worktree as the place for a non-regenerable ignored file.

1. Have the member stop its own background work, such as background shell tasks and monitors, and confirm none remain.
2. Find the listeners tied to the member's worktree with `orca ports --worktree id:<worktree id> --json`, and the
   processes whose working directory is inside it, for example with `lsof -d cwd -Fpn`. Stop those that the member's
   terminal or session started. Report a process the session did not start, such as one the user runs there, and leave
   it running unless the user approves. Closing a terminal stops the processes of its session, `nohup` jobs included,
   but not a process that detached into a session of its own, such as a daemon or a container.
3. Close the member's terminal: `orca orchestration worker-release --dispatch <id> --json` for a worker, otherwise
   `orca terminal close --terminal <handle> --json`.
4. Remove its worktree and local branch with `orca worktree rm --worktree id:<worktree id> --delete-branch --json`.
   When step 2 left a process running there, keep the worktree and branch and report them instead; remove them only
   after that process ends or the user approves stopping it.

Afterwards confirm that no terminal, process, or listener of the member remains, and report each item closed. For a
member that worked in a main checkout, stop only its background work, processes, and terminal; never touch the
checkout or its default branch.
