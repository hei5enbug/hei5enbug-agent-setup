---
name: confluence-ops
description: >-
  House rules for working with Confluence pages, comments, attachments, and labels. Load this
  before choosing a tool for any Confluence read, search, create, update, comment, attachment, or
  label task. Covers routing work to confluence-cli instead of Atlassian Rovo tools, keeping
  credentials off the command line, writing comments as storage XHTML or ADF instead of Markdown,
  building user mentions that actually render, and verifying every comment after it is written.
compatibility: >-
  Prefers the confluence-cli tool on PATH. Without it, the rules about comment markup,
  verification, and credentials still apply to whatever Confluence write path the host offers.
  Every rule below states what to do when the preferred path is missing.
---

# Confluence House Rules

Confluence looks forgiving and is not. It silently rewrites markup, renders a mention as plain
text when the markup is slightly wrong, and shows no error when a comment lands malformed. Each
rule below exists because one of those failures is easy to cause and hard to notice.

## Choosing the Tool

Use `confluence-cli` for Confluence work, not the Atlassian Rovo Confluence tools.

Within `confluence-cli`, prefer a typed command. Reach for `confluence api` only when no typed
command can perform the Confluence REST API v2 operation you need.

```
Confluence task
   ├─ typed command exists?      → use it            (confluence read, confluence update, ...)
   ├─ no typed command?          → confluence api    (REST API v2)
   └─ confluence-cli missing?    → say so, then use the host's Confluence tool
```

Do not assume the command syntax. Discover it with `confluence --help` or
`confluence <command> --help` before running anything that writes.

When `confluence-cli` is not installed, tell the user it is missing before falling back to
another Confluence tool. Do not switch paths silently — the rest of these rules assume the CLI,
and the user should know which path produced the result.

## Credentials

Never print, log, write into a file, or pass a Confluence credential as a command-line argument.

A token on the command line ends up in shell history, in process listings, and in any transcript
of the session. The CLI's own documentation shows examples like `confluence init --token "..."`.
Do not copy that form.

Read credentials only through one of these:

| Source | How |
|---|---|
| Configured profile | `confluence --profile <name> <command>` |
| Environment | `CONFLUENCE_DOMAIN`, `CONFLUENCE_API_TOKEN`, and the rest, already exported |
| Protected credential file | The profile config or `~/.netrc`, read by the CLI itself |

If no credential is configured, ask the user to set one up. Do not offer to run a command that
takes the token as an argument.

## Comments

### Send markup, not Markdown

When exact rendering matters, send the comment body as storage XHTML or ADF. Confluence does not
parse Markdown in a comment body, so `**bold**` and `- item` arrive as literal characters.

Keep every block a separate node. A paragraph, a list, a heading, and a code block each need
their own element. Do not merge them into one paragraph with line breaks inside it — Confluence
collapses that into a wall of text.

### Mentions

A user mention is a link element wrapping a user element, addressed by account id:

```xml
<ac:link><ri:user ri:account-id="ACCOUNT_ID" /></ac:link>
```

Plain text such as `@name` is not a mention. It renders as ordinary text and notifies nobody.
Get the account id from the Confluence or Jira user lookup first; never guess it.

### Verify after every write

After you create or update a comment, read it back in rendered form and confirm two things:

1. The mention renders as a real user link, not as text.
2. The block structure survived — paragraphs, lists, headings, and code blocks are still separate.

Read it back with the typed comments command in view format. If the typed command cannot request
a rendered body, use `confluence api` against the comment endpoint with `body-format=view`.

Checking the request you sent is not verification. Confluence rewrites markup on the way in, so
only the stored, rendered body tells you what the reader will see.

### Ask before removing

Ask the user before deleting a comment or marking one resolved. Both actions are visible to
everyone on the page and are awkward to undo.

## Self-Containment

This skill reads no sibling skill file and calls no other skill. If a rule here ever needs to
move into a shared reference, declare that file, say what it holds, and say what to do when it
is absent.
