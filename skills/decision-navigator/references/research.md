# Research workflow

Use this workflow for a research ticket whose answer depends on facts outside the current working
directory.

## Execution

1. Restate the ticket's exact question and the evidence needed to answer it.
2. Prefer primary sources: official documentation, specifications, source code, and first-party
   APIs.
3. Trace every important claim to the source that owns it.
4. Write one Markdown findings file. Cite claims close to the supporting source.
5. Record a direct answer, remaining uncertainty, and consequences for blocked tickets.
6. Link the findings from the ticket before resolving it.

## Workers and fallback

When plugin session rules apply, follow the host's agent rules and
[shared routing contract](../../../instructions/model-routing.md). Use a verified researcher for bounded public
sources and scout for local evidence. Private or authenticated access stays with the authorized main session.
The evidence worker returns findings; main makes decisions and writes the findings file and ticket links.

Without plugin rules, use an independent read-only worker when the host supports one. Give it only the ticket
question, relevant context, and evidence rules; main writes the persistent result. Research tickets may run
concurrently only when their files and tools do not conflict.

When workers are unavailable, run the same steps sequentially. Do not omit the research or pretend
it ran in parallel.

## Capturing the result

Write findings under `.decision-navigator/<effort>/artifacts/research/` using a descriptive filename. Link
the exact relative path from the research ticket. Do not publish the findings to an external issue,
comment, branch, or connected document service.
