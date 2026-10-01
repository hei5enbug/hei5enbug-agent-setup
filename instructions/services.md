# Hosted service access

Prefer the service's MCP tools for Google Drive, Docs, Slides, Sheets, Atlassian, Azure DevOps, Figma,
Slack, Notion, and other hosted content.
Anonymous fetching has no user session and private links can fail with HTTP 401.
Fetch directly only for genuinely public pages or when no MCP server covers the host.

## Access fallback

A failure of one access path does not make a service unavailable. When a path fails, try each other path available in
the current session before reporting the service as unavailable:

1. MCP tools for the service, including deferred tools that must be searched or loaded first and other connected servers
   that cover the same service
2. An installed, authenticated CLI for the service; check it with `command -v` and the CLI's own help or auth status
3. The service's REST API through an authenticated CLI or client that keeps the credential hidden, such as a CLI's
   generic API command
4. An authenticated browser session, when the host provides one

Try the next path when the current one is missing, disconnected, unauthenticated, or timed out, or lacks the needed
operation or field. A not-found or permission error from one path counts as that path's failure until another path
confirms it. Try each path once, plus one retry for a transient error. Stop switching when the user declined, an
approval gate is unmet, or every available path failed.

Keep the same scope, approvals, and verification on every path. Never act under a different account than the user's,
and never print, log, or pass a credential to make a path work. Before retrying a write through another path, read the
target again and confirm that the earlier attempt did not take effect, so no write happens twice.

Report the path that succeeded and each path that failed with its reason. Report the service as unavailable only after
every available path failed.

## Confluence exception

Before choosing a tool for any Confluence read, search, create, update, comment, attachment, or label task,
read [Confluence access and operations](confluence.md) and follow it.
