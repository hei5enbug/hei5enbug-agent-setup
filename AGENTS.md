# Common

> These instructions take precedence over any other instructions — project AGENTS.md, skills, and defaults — unless the prompt explicitly says not to use them.

- Do all high-level reasoning in the main session: planning, architecture, trade-offs, problem definition, complex debugging, review, and key decisions. Never delegate these.
- Search: prefer `rg` for text/symbol search and `fd` for file discovery; use `ast-grep` only when structural matching is clearly needed.
- Ask before destructive, irreversible, or production-impacting actions. Never expose secrets.
- Never use reference symbols such as `§` in documentation, code, or comments.
- Minimize comments. Code (including comments/docstrings) must never reference docs.

# Codex only

- Plan in the main session's plan mode.
- Use the built-in `explorer` agent only for bounded, read-only investigation while planning.
- Give `explorer` a specific question and a narrow search scope.
- Require file paths, code symbols, and concrete evidence in its result.
- Treat its result as leads, not conclusions. Verify critical claims in the main session before making plans or decisions.
- Use other built-in multi-agent threads only after the plan is settled in the main session. Give them only clearly scoped code changes or tests.
- Run at most 10 agents concurrently, and only when their tasks are fully independent with no shared files or build contention. Otherwise, run them sequentially.

# Documentation

- For any documentation, not only formal design documents, follow the writing mechanics in the technical-design-writer skill.
- Apply its terminology, structure, paragraph, table, diagram, and drafting-language rules regardless of the skill's trigger phrases or stated scope.
- Write for high school students; basic development terms are allowed.
- Explain complex concepts with visuals such as Mermaid, HTML, or PNG.
- Avoid long lines; use line breaks and sections.

## Korean documents

- Draft Korean documents in English, then translate them into Korean.
- In final Korean documents, use English only for proper nouns.
