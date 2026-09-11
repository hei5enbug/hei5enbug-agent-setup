# Confluence access and operations

Apply these rules before any Confluence read, search, create, update, comment, attachment, or label action.

## Tool selection

Use the installed `confluence-cli` instead of Atlassian Rovo Confluence tools.
Prefer a typed `confluence` command.
Use `confluence api` only when no typed command can perform the required Confluence REST API v2 operation.

Discover syntax with `confluence --help` or `confluence <command> --help` before a write.
If `confluence-cli` is unavailable, report that limitation before using another connected Confluence tool.

Use [document-to-confluence](../skills/document-to-confluence/SKILL.md) when importing, publishing,
synchronizing, or repairing document content in a Confluence page.

## Credentials

Never print, log, write to a file, or pass a Confluence credential as a command-line argument.
Let the CLI read credentials through its configured profile, environment, or protected credential file.
If no credential is configured, ask the user to configure one without supplying the value in the conversation.

## Comments

Use storage XHTML or Atlassian Document Format (ADF) when exact rendering matters.
Confluence does not interpret Markdown in a comment body.
Keep paragraphs, lists, headings, and code blocks as separate nodes.

Create a user mention with an account ID, never a guessed display name:

```xml
<ac:link><ri:user ri:account-id="ACCOUNT_ID" /></ac:link>
```

After creating or updating a comment, read it again with `body-format=view`.
Verify that each mention renders as a user link and that block structure remains intact.
The submitted request is not evidence of the stored rendering because Confluence rewrites markup.

## Removal

Ask for explicit approval before deleting or resolving a comment and before deleting an attachment.
Identify each target and confirm that no page body still references an attachment before proposing deletion.
