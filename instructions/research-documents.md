# Research and verification documents

Apply these rules when writing or revising a document that reports what an investigation, analysis, or check found
in answer to a question. They apply in any format or destination, with or without a skill.
When `docs-rewrite` rewrites one of these documents, apply only the rules on importance-only phrases and pointing
phrases, and follow that skill's research-document reference for ambiguous references and heading changes.

1. Use the prose to state the result or pattern the reader can infer from a table or figure. Leave its values
   in the table or figure. For example, after a response-time table, state that only demo-b exceeded its target.
   For these documents, this rule replaces the figure-and-table bullet in
   [Readable shared text](shared-text.md#readable-shared-text).
2. Delete a phrase that only signals importance and state the confirmed fact directly. For example, write
   "TTL이 1분이다" in place of "핵심은 TTL이 1분이라는 점이다".
3. Include an estimate, proposal, or assumption only if it uses confirmed facts and has been verified.
   If the user requests one that remains unverified, include it and mark it as unverified. When no available
   source can verify an assumption, omit it and the conclusion it supports unless the user asks for that
   conclusion. You may ask the user whether to include it.
4. Use a word of range or likeness, such as "대부분", "모두", or "비슷하다", only when the data in the document
   or a cited source lets the reader check the range or the basis for comparison.
5. When a pointing phrase such as "이것" or "해당 결과" could refer to more than one thing, name the thing.
6. Write each section heading as a short noun phrase that names its subject. For example, write
   "A와 B의 차이" in place of "A는 B와 다르다".
7. Keep only information that helps answer the document's question or lets the reader judge the answer.
8. Put each limitation next to the conclusion it affects and state how it affects that conclusion.
9. In Korean, give the most weight to natural Korean expressions and terms. Keep an English word when it reads
   more naturally in context.

## Final review

As the last step, run the Independent text review in [Shared text](shared-text.md#independent-text-review) with
`--kind shared-document` and this file passed with `--rules`. Have the independent reviewer check logic and
expression.
You may save a local report at the user's requested path before the review if you run the review and apply its
fixes to that file before handing it over.

For Exit 1, use these rules to decide when to ask and follow the other Exit 1 steps in Shared text. Apply a finding
without asking when it has one clear fix that adds, removes, or moves no fact, number, claim, section, or conclusion.
Ask before applying a finding when more than one reasonable fix exists or the fix would add, remove, or move any
of those items beyond the user's request.
