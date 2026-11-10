# Open issue review

Rules for checking a plugin's open issues against the current state and making them ready to implement. Read this
after step 3 when the user asks whether the open issues are still right, or asks to make them ready to implement. It
replaces steps 1, 2, and 4 to 9 of the skill.

## Collect

List the open issues of the declared tracker, then keep each one the current account wrote; compare `author.login`
with the current user as [update in place](update-in-place.md) does. On GitHub, run
`gh issue list --repo <location> --state open --json number,title,url,author,body --limit 100`. Never edit an issue
that someone else wrote; name it in the report as not checked.

## Check each issue

Read the whole body, then check:

- each rule or fact it quotes against the current owning file;
- each dependency's current state, read as [implementable body](implementable-body.md) does;
- overlap with the other open issues: the same file proposed or changed by more than one, and a part another issue or
  a dependency already provides;
- each choice that only the user can make and the body leaves to the implementer;
- each acceptance criterion against the skill's seeded-input rule in step 6.

## Ask once

Collect every choice found across all issues and ask them in one call of the host's question UI. Edit no issue that
depends on an unanswered choice; edit the others in the same turn, without waiting for the answers.

## Edit

Under the condition that the user's request changes behavior, a public contract, or several components in the
issues, apply step 7's review over all edited bodies once before the first write.

Edit each body in place as [update in place](update-in-place.md) describes: keep what is still true, remove or fix a
stale quote, and add the dependency line and order of [implementable body](implementable-body.md). Relate issues that
overlap by naming each other with one implementation order, in every one of them. Apply the public leak check for a
public tracker and the approval rule for `preview_required` as that file says.

## Report

Report every checked issue, one line each, as exactly one of: unchanged; edited, and how; or still waiting for a
decision, and which one. Add the issues not checked and why.
