# Repository development

> These instructions apply only when developing this repository.
> Plugin hooks load only `instructions/session/` and do not load this file.

- Review requirements before implementation. If an incorrect or undefined term, multiple plausible
  interpretations, a contradiction, or a missing decision could materially change the result, scope,
  contract, or acceptance criteria, explain the possible interpretations and their impact, then ask the user.
  When code, schemas, a glossary, or an existing agreement leaves only one interpretation, apply it and state
  the basis. Until a decision only the user can make is resolved, do not edit files or change external state.
  Continue only read-only investigation that does not presuppose the answer.
- When changing skills, instructions, or hooks, consider their recurring token and context cost.
  Preserve correctness and required validation while reducing unnecessary instruction loading, repeated reads,
  tool calls, and duplicated content.
- English files are the canonical executable sources. Maintain a complete, meaning-equivalent Korean `.ko.md`
  mirror for every human-readable English Markdown file. Update, move, or delete both together.
  Korean mirrors are non-authoritative human references and must never be loaded during agent execution.
  Do not duplicate code, schemas, test fixtures, generated artifacts, or non-English documents.
- Before changing a skill, read `skills/skill-builder/SKILL.md`. Before changing documentation, read
  `instructions/documentation.md`. For plugin structure, manifests, or hooks, use `plugin-creator` when the host
  provides it and preserve the existing plugin contracts.
- Keep shared behavior in one canonical source and isolate only actual host differences.
- Treat the latest published version as the release baseline. Keep all unreleased work on one planned next
  version and never bump the semantic version for local iterations. Use a cachebuster for local reinstalls.
  Before a release, run every development check in `README.md` and keep both plugin manifests,
  `pyproject.toml`, and `uv.lock` on the same version.
- Before using another agent, read the applicable rules in `instructions/codex-agents.md` or
  `instructions/claude-agents.md`.
