# Update in place

Rules for changing an existing issue instead of creating one. Read this before updating an issue in step 5, before
fixing a failed read-back in step 8, and before changing the issue after the step 9 preview.

Under the condition that `target.public` is true, run the [public leak check](public-leak-check.md) on the new body
or comment before every write below.

## Open issue covers the same gap

Decide by the author. On GitHub, compare `author.login` from `gh issue view <number> --repo <location> --json author`
with `gh api user --jq .login`; on another tracker, compare with the connected tool's current user.

- The current account wrote it: edit its body. Read the whole body, check each statement against the current rules,
  keep what is still true, and merge the new observations, Proposal rules, and Acceptance criteria into it in the
  section order of step 6. On GitHub, pass the body on stdin:

  ```text
  gh issue edit <number> --repo <location> --body-file - <<'EOF'
  <body>
  EOF
  ```

- Someone else wrote it: add a comment with the new observations, rules, and criteria, and leave their body alone. On
  GitHub, use `gh issue comment <number> --repo <location> --body-file -` with the text on stdin the same way, and keep
  the comment ID from the link it prints, the number after `#issuecomment-`.

Ask no question first; only the approval below, under the condition that `preview_required` is true, waits for the
user. Then read back what you wrote, and report its link and which change was made: an edited body as in step 8; a
comment by its ID, on GitHub with `gh api repos/<location>/issues/comments/<id> --jq '{user: .user.login, body}'`,
confirming that the current account wrote it and that its text shows no raw markup. Never pick the comment by its
position, because another comment can arrive after yours.

## Failed read-back or a change after the preview

Change only what this skill wrote, then read it back again: the body of an issue it created or the current account
wrote, with the same command; for a comment, that comment by its ID, on GitHub with
`gh api -X PATCH repos/<location>/issues/comments/<id> -F body=@-` and the text on stdin. Never edit the body of an
issue someone else wrote, or a comment through `--edit-last`, which edits the account's latest comment on the issue.

## Approval

Under the condition that `preview_required` is true, show the new body or comment text, and write it only after the
user approves that text in a later message. When the text changes after approval, show it again and wait for a new
approval. Under the condition that `preview_required` is false, write at once.

## Other trackers

Use the path that the declaration options choose for the same operation, at the declared location only.
