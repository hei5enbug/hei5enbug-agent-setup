# Implementable body

Rules that let a coding agent implement the issue without asking again. Read this before drafting when the proposal
relies on another issue or another plugin's release, shares a file with another open issue's proposal, assigns a new
file name, number, or identifier, or states a fact that can change before implementation.

## Dependencies and order

Under the condition that the proposal depends on another issue, another plugin's release, or a file that another open
issue also proposes to create or change, read each one's current state at filing and add one line at the start of the
Proposal that names it with:

- its link;
- its state on that date, such as open, closed, or released, written with the date;
- what this issue takes from it;
- the order in which the related issues are implemented.

On GitHub, read an issue with `gh issue view <number> --repo <location> --json state,title,url,body`. Find another
plugin's tracker with `scripts/find_tracker.py` on that plugin, and never guess it. Find the open issues that propose
the same file by comparing each open issue from the step 5 search. Under the condition that a state cannot be read,
write it as unverified with the date.

Illustration, not a complete list: "Depends on example-org/tool-kit issue 7: open on 2026-01-15; this issue takes its
parser and adds the report; implement issue 7 first."

## Parts already provided

Under the condition that an open issue or a dependency already provides part of the proposal, leave that part out of
the Proposal and say where it lives: the issue link, or the release and the file it ships. Read what the closed issue
or the release shipped instead of its title.

## New names and numbers

Under the condition that the proposal assigns a new file name, number, or other identifier, check at filing that it is
free: list the folder or the series, or search the tracker. Under the condition that it is taken, the name is not new:
propose changing the existing file, or ask the user when neither fits. Under the condition that it can be taken before
implementation, such as the next number in a series of records, write "the next free number" and name the series
instead of the number.

## Facts that change

Under the condition that a fact will change before implementation, such as the planned version, the level of the next
version bump, a commit, or another issue's state, leave it out when the implementer can read it from the repository or
the tracker, also when the user stated it. Otherwise write it with its date.
