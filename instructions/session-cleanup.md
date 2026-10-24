# Session cleanup

The [work efficiency](work-efficiency.md) rules link this file. Read it when the user's requested work is complete,
or the session has no remaining work in its own scope, and the session created files that are not tracked project
content.

## When to offer

Offer once, at the end of the work, only when all of these hold; otherwise ask nothing:

- At least one item qualifies under "What qualifies".
- No background task, child agent, or process still uses an item.
- The session did requested work; it was not only a greeting or a status check, and the request was not aborted.

## What qualifies

Offer only an item this session created and can show it created: its own scratch or temporary folder, or a file or
folder whose creation appears in this session's commands or tool calls. Never offer another session's files, user
files, tracked project files, shared host caches, configuration, or history. Never include a worktree or its branch;
[cross-repository work](cross-repository.md) covers removing those.

## Asking

List each item with its path, its size, and why it counts as this session's, such as the command that created it.
Then ask once whether to remove them. This question is the approval that irreversible deletion needs. Delete only the
items the user confirms. When the user declines or does not answer, keep everything and do not ask about the same
items again.

## Deleting

When a deletion is blocked, such as by a read-only subdirectory, report the block, change permissions only inside the
confirmed item, and delete it again. Afterward confirm that each deleted path is gone and report the freed size.
