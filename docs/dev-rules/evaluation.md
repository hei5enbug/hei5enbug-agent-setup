# Evaluation rules

These repository development rules extend `AGENTS.md`, which keeps the quality rule, the deterministic-first order,
the record rule, and its 2026-11-19 exceptions.

## Cases

Absolute rule (owner decision, 2026-11-11): an evaluation that costs model calls uses only the fewest fixed
representative and boundary cases that decide its acceptance criteria, about three by default and rarely more than
ten, and states each criterion as a pass or fail per case, never as a rate over a large sample. An evaluation that
fixes the model, effort, or prompt of a skill or agent may add cases that separate difficulty levels. Deterministic
tests that cost no model tokens have no such limit. Write issue acceptance criteria under the same rule.

## Choosing the most efficient candidate

Efficiency rule (owner decision, 2026-11-15): when an evaluation chooses the most efficient of several candidates:

1. Keep only candidates that pass every case and, where it measures quality beyond pass or fail, have the highest
   measured quality, as the quality rule in `AGENTS.md` requires.
2. On any case, drop a candidate that is slower than the fastest remaining one by more than 1.5 times and by more
   than 60 seconds.
3. Among the rest, choose the lowest list-price cost per passing case.
4. Treat costs within 10 percent or within $0.05 of each other as a tie, and choose the faster one.

## Writing surfaces

`config/writing-surfaces.json` lists each kind of text people read that this plugin writes, with the files that hold
its rules, the skills and instructions that write it, and its writing task in `evals/e2e`. Before changing how a listed
file writes such text, or `scripts/text_review.py`, run those tasks on the baseline and the changed revision. Accept
the change only when no task whose `text-review-clean` check passes on the baseline fails on the changed one and the
number of passing tasks does not fall. Under the 2026-11-19 owner decisions in `AGENTS.md`, the owner's blind A/B
comparison of the before and after texts takes the place of the `text-review-clean` check: a task passes only when the
owner judges the after text the same or better.

## Korean writing model

Before changing the model of the `language` capability or of `scripts/text_review.py`, run `evals/korean-writing` on
the candidates and the current model and record the result in its README. Change the model only when the decision
rule there picks a winner.
