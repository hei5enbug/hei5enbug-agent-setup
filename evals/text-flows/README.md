# Text flow comparison

This evaluation compares who writes, reviews, and fixes the text people read, for three kinds of text: the PR description
(`T13`), the issue body (`T15`), and the final report (`T20`). Each flow is a variant of the plugin run through the golden
harness in `evals/e2e`, one run per flow and text kind. `tf_pages.py` only reads the finished runs and costs no model call.

| Flow | Who writes | Who reviews | Who fixes | Host |
|---|---|---|---|---|
| F1, the current flow | Claude | the Codex model of the sol winner, through `text_review.py` | Claude | Claude Code |
| F2 | Claude | Claude Opus, after the `language` capability had the Codex model edit the draft in place | Claude | Claude Code |
| F3 | the Codex model of the sol winner | Claude Opus, through `text_review.py` | the Codex model | Codex |
| F4 | Claude | Claude Sonnet, through `text_review.py` | Claude | Claude Code |
| F5 | Claude | the Codex model, which also applies its findings in place | the Codex model | Claude Code |

A flow differs from F1 only by one text edit of `instructions/shared-text.md` or by the reviewer literal of
`scripts/text_review.py`, so the harness records it as a variant of one change.

## Judging

1. Form checks: every required check of the task except `text-review-clean` and `ran-text-review`. A flow whose text fails a form
   check does not pass that text kind.
2. Quality: the owner ranks the texts of each kind blind. `tf_pages.py` writes one page per kind with neutral labels in an order
   fixed per kind by a seed, and `key.json` beside the pages names the flow of each label. The pages never name a flow.
   Each page renders every text as Markdown with `marked@12.0.2` (GitHub-flavored, line breaks kept) from the raw text in a
   `text/markdown` block, shows the plain text when the renderer fails to load, and prints a one-line answer to copy under
   "Show my answer".
   A flow that the owner ranks below F1 on any kind is never chosen.
3. Among the flows that pass the form checks and are not ranked below F1, the lowest list-price cost per passing text wins, and
   within 10 percent or $0.05 the faster flow wins (`docs/dev-rules/evaluation.md`).

```text
python3 evals/text-flows/tf_pages.py --run-root <root> --campaign <name> \
  --flows F1=f1:claude,F2=f2:claude,F3=f3:codex,F4=f4:claude,F5=f5:claude --out <folder>
```
