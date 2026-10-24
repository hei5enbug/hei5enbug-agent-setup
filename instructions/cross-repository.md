# Cross-repository work

Read this before changing files in a Git repository other than the working repository, the one that holds the
session's working directory, before starting an agent session in Orca, and before messaging another agent session.
Reading another repository needs none of it.

Make the change in a worktree of the target repository on this task's branch, never in a checkout on another branch,
such as a main clone on the default branch, which may hold other work. The target's session owns the change, so its
own instructions, hooks, and branch rules apply.

## Orca worktree

Use the Orca CLI when `orca status --json` reports a reachable runtime. For a flag this file does not give, run
`orca skills get orca-cli` once.

### Session placement

Start every new agent session under a workspace that Orca already lists for its repository, in this repository as
in another one; never create an independent top-level worktree while one exists. A repository's workspace is the
entry whose path is its clone in `orca worktree list --repo id:<repoId> --json`. The parent is the current Orca
worktree when it belongs to that repository, and that workspace otherwise.

- A session in the working repository that edits no file runs as a new terminal in the current worktree, or with Orca
  orchestration as `worker-start --worktree current`.
- A session that edits files gets a child worktree through steps 2 to 6 below, or with Orca orchestration
  `worker-start --worktree new-child --base-branch <base>`, never `new-top-level`.
- Pass `--no-parent` only for a repository that Orca lists no workspace for.

1. Find the target in `orca repo list --json`. Register an existing local clone with `orca repo add --path <path>`.
   When no local clone exists, ask the user where to clone it.
2. Choose the branch name and base before creating anything, from the first source that covers the target: a loaded
   skill or plugin rule, the target's `AGENTS.md` or `CLAUDE.md`, then a short task-named branch on the repository's
   default base. Fetch the base from its remote first.
3. `<host>` is `claude` on Claude Code and `codex` on Codex. `<clone>` is the target's path in `orca repo list`, and
   the target's workspace is the entry with that path in `orca worktree list --repo id:<repoId> --json`. Look for a
   worktree on the chosen branch in `git -C <clone> worktree list --porcelain`, then take the first case that applies:
   - The worktree has its own entry in the Orca list: check `orca terminal list --worktree id:<worktree id> --json`.
     If an agent terminal is open there, ask the user whether to send the brief to it. Otherwise start one with
     `orca terminal create --worktree id:<worktree id> --command <host> --json` and continue at step 5.
   - The worktree has no entry of its own: it sits inside the workspace, and Orca cannot tell which of the
     workspace's terminals runs in it. Show the user the workspace's terminal titles and ask whether to send the brief
     to one of them or to start a new terminal as in the next case.
   - No worktree is on the branch: run `orca worktree create --repo id:<repoId> --name <branch> --base-branch <base>
     --agent <host> --parent-worktree <parent> --json` with the parent from "Session placement". Pass no `--prompt`.
4. After `orca worktree create`, Orca names the new branch itself, with its configured prefix and `/` replaced. When
   the result's `branch` differs from the chosen name and that branch does not exist yet, run
   `git -C <worktree path> branch -m <branch>`. When it already exists locally or on `origin`, run
   `git -C <worktree path> switch <branch>`, then delete Orca's unused branch with
   `git -C <worktree path> branch -D <Orca branch>`. Confirm the name in `orca worktree list`, because
   `orca worktree show` can still report the old one.
5. Use the handle that `orca terminal create` returned. After `orca worktree create`, find the agent terminal with
   `orca terminal list --worktree id:<worktree id> --json`. Run
   `orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json`, and send only when
   `wait.satisfied` is true and "Messaging another session" allows it. Wait once more with a longer timeout, and if it
   is still false, report the handoff as not started.
6. Send the brief with `orca terminal send --terminal <handle> --text "<brief>" --enter --json`. The brief states the
   goal, the evidence found so far with file paths, the branch and base, and the acceptance checks. The handoff is
   done when the send reports `accepted: true`; do not wait for the work to finish.

## Messaging another session

- `tui-idle` means only that no turn is running. Before each send, read the target with
  `orca terminal read --terminal <handle> --screen`, and send only when no approval prompt or question is open and the
  input line is empty. When the target waits on the user, report that instead of waiting; never answer its prompt.
- Text on the input line can be the host's grey suggestion. Send `--text x`: when the line then shows only `x`, delete
  it with `--text $'\x7f'` and send. Otherwise delete the `x`, send nothing, and tell the user their text is there.
- Judge a reply by its last message and status line, never by its task list, which can stay stale.

## Without Orca

When the Orca CLI or runtime is unavailable, ask once whether to use a plain Git worktree. On approval, choose the
branch as in step 2, and pick a path outside every existing checkout. Run
`git -C <target> worktree add -b <branch> <path> <base>` for a new branch, or
`git -C <target> worktree add <path> <branch>` for one that exists locally or on `origin`. Read the target's
`AGENTS.md` or `CLAUDE.md`, and make the change there from this session. Without approval,
stop the cross-repository change and report it.

## New worktree contents

A new worktree has no ignored files, such as `.env` or local settings, and no installed dependencies. Never copy a
protected value into it; the session that needs the file reports it to the user.

## After the handoff

- When the working repository has nothing left for the current request, recommend in one line that the user continue
  in the target worktree's session and end this one. Never end a session yourself.
- Otherwise continue the remaining work, and read the target with `orca terminal read --terminal <handle> --json` only
  when its result is needed.
- When a child session's work is merged into its base, offer once to close its terminal and remove its worktree and
  branch, naming each. Before offering, confirm that the worktree has no uncommitted change and that the base holds
  the content of every one of its commits, including commits applied under another hash. Remove only what the user
  approves; otherwise remove a worktree or branch only when the user asks.
