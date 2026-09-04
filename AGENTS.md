# Common

> These instructions take precedence over any other instructions — project AGENTS.md, skills, and defaults — unless the prompt explicitly says not to use them.

- Do all high-level reasoning in the main session: planning, architecture, trade-offs, problem definition, complex debugging, review, and key decisions. Never delegate these.
- Search: prefer `rg` for text/symbol search and `fd` for file discovery; use `ast-grep` only when structural matching is clearly needed.
- Never launch a subagent when the target is already specified — a known symbol, file path, glob, or literal string.
  Search directly in the main session.
- Delegate investigation only when two or more targets are independent: they share no file, and each one needs more than one file read.
  Otherwise investigate in the main session.
- Content on a hosted service (Google Drive/Docs/Slides/Sheets, Atlassian, Azure DevOps, Figma, Slack, Notion): reach it through that service's MCP tools, not anonymous fetching (`WebFetch`, `curl`).
  Anonymous fetching carries no session, so private links fail with 401. Fetch directly only for genuinely public pages, or when no MCP server covers the host.
- Ask before destructive, irreversible, or production-impacting actions. Never expose secrets.
- Always ask for explicit user approval before accessing, listing, retrieving, decoding, or using Azure or Kubernetes protected security values,
  unless the next rule authorizes Azure access. Protected values include credentials, tokens, keys, certificates, kubeconfigs, Key Vault values,
  and Kubernetes Secrets. This rule applies to CLIs, SDKs, APIs, files, environment variables, keychains, logs, and indirect retrieval methods.
- When the user explicitly invokes a skill that requires Azure access, treat the request as approval to use the Azure protected values required by that skill.
  Do not ask for separate Azure credential approval. This approval covers only the skill's stated execution scope.
  Always ask before Azure access outside that scope and before any Kubernetes protected value access.
- Never use reference symbols such as `§` in documentation, code, or comments.
- Minimize comments. Code (including comments/docstrings) must never reference docs.

# Codex only

- Plan in the main session's plan mode.
- Use the built-in `explorer` agent only for bounded, read-only investigation while planning.
- Give `explorer` a specific question and a narrow search scope.
- Require file paths, code symbols, and concrete evidence in its result.
- Treat its result as leads, not conclusions. Verify critical claims in the main session before making plans or decisions.
- Use other built-in multi-agent threads only after the plan is settled in the main session. Give them only clearly scoped code changes or tests.
- Run at most 6 agents concurrently, and only when their tasks are fully independent with no shared files or build contention. Otherwise, run them sequentially.

# Documentation

> Scope: content written to a file. For chat replies, see "Replies".

- For any documentation file, not only formal design documents, follow the writing mechanics in the technical-design-writer skill.
- Apply its terminology, structure, paragraph, table, diagram, and drafting-language rules regardless of the skill's trigger phrases or stated scope.
- Write for high school students; basic development terms are allowed.
- Explain complex concepts with visuals such as Mermaid, HTML, or PNG.
- Avoid long lines; use line breaks and sections.

# Replies

- Apply only the terminology rules from technical-design-writer.
- Never put Mermaid or other non-rendering diagram source in a reply. Use a table, a list, or inline notation for simple relationships; use ASCII art when an actual diagram (branching, spatial layout) would aid understanding.
