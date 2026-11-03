# Rule-miss audit

Read this before auditing which written rules agents miss in session records. It extends steps 1 to 5 of the
workflow; the boundaries and the proof rules still apply.

1. Fix the window, the record folders, and the written-rule sources: the plugin's session instructions and
   references, the skills, and the project's `AGENTS.md` or `CLAUDE.md`. Use the `projects` folder of the Claude
   Code configuration directory, `$CLAUDE_CONFIG_DIR` or the host's default; count main sessions only.
2. Write a rules file that maps each enforcing hook's message to its written rule and source line, then run
   `scripts/rule_misses.py` with `--candidates`. Map every `unmatched` group that a written rule covers, and run it
   again.
3. Classify each candidate against the written rules: count a miss only when the user corrects the agent for
   breaking a written rule, or a final report lists a required step as not done or offers it instead of doing it.
   A new request, a question, or an unwritten preference is not a miss. A read-only reviewer may classify large
   candidate sets; give it the candidates and the rule files, and keep the evidence free of private details.
4. Report one row per rule: the rule, its `path:line`, sessions, hits, hits per 100 replies, current enforcement,
   the chosen level, and the always-read tokens before and after the fix. A rule with misses in two or more
   sessions is a class; one session is a watch item.
5. For each class, choose the first fix that works: a hook or test that blocks or records the miss and adds no
   always-read text; a one-line trigger at the point of action, such as the commit and push path or a conditional
   reference, instead of the always-read core; rewording an existing line. Never add an always-read paragraph. A
   rule that a hook already blocks or reminds needs no further fix unless its misses cause harm the hook misses.
6. Measure each fix on a paired old and new replay of real miss cases or fixtures built from them: the miss rate,
   the always-read size before and after, and output quality. Measure the size from the host's input-token count
   on an identical short prompt when the host reports one, otherwise in bytes, and say which. Accept a fix only
   when the miss rate drops, the always-read size does not grow, and quality does not drop beyond trial variance.
