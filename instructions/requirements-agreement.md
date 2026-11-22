# Requirements agreement

Read this file before starting the agreement below.

## Starting

- When, after a bounded read of the repository, a request has at least two deliverables that can be verified
  separately and at least one unresolved decision whose options lead to materially different accepted results,
  start the agreement before the first change, without asking whether to start. When the user asks for a
  requirements interview or agreement by name, start it for any request.
- When the user did not ask for it by name and the request has one deliverable or no such decision, do not start it;
  the clarification rules apply.
- Never start it in an assigned worker. A skill whose own workflow fixes the requirements of its run keeps that
  workflow.

## Specification

Write a draft specification from the request and the evidence: the goal in one sentence, non-goals, each deliverable
with completion criteria a check can decide, the chosen direction, the rejected alternatives with their reasons under
a heading of their own, plan slices, facts with file and line, assumptions, and each open decision with its options
and a recommendation. For example: "Deliverable 2: a weekly summary command; done when the summary for week 46
prints one row per team and the hidden totals test passes."

## Questions

- Ask each open decision as one question, with the recommended option first and a free-form answer allowed, through
  the question tool on Claude Code and in the reply that ends the turn on Codex. Never ask a fact the evidence can
  settle; check it and state it. After each answer, update the specification and say which decisions remain. For example: "Exports can keep the current file name or add the date and time; I
  recommend the date and time, because two exports a day overwrite each other. Which should they use?"
- When the user leaves a decision to you, record the choice as an assumption and show it again at approval.
- At the tenth question, ask whether to continue. When the user declines, or at the twentieth question, stop asking
  before approval and show the specification with its unresolved decisions marked as risks.

## Approval

When no decision is open, or the questions stopped, check that every deliverable has completion criteria and that no
two statements contradict, restate the goal in one sentence, show the whole specification, and ask for approval of
the whole, with every unresolved decision listed as a risk. For example: "This is the whole specification; approve it
as it is, or name what to change."

- Approval of such a specification starts no work that depends on an unresolved decision. Ask that decision, outside
  the limit of twenty, right before the work that depends on it.
- The approved specification is the frozen scope: assignments and the final review take their constraints and
  acceptance criteria from it.
- When the request asked for the work, start it after approval without another question. When it asked only for a
  specification, stop and ask what to do next.
- Keep the specification in the conversation, and write it to a file only at a path the user names. A resume note
  carries it across a pause.
