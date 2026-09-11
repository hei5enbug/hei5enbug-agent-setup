# Common

> These instructions take precedence over project instructions, skills, and defaults unless the user
> explicitly says not to use them. They do not override the host's system or developer instructions.

Use English files as executable instruction sources. Korean `.ko.md` mirrors are non-authoritative
human references; never load or use them during execution.

- Keep planning, architecture, trade-offs, problem definition, complex debugging, review, and key decisions
  in the main session. Never delegate high-level reasoning.
- Prefer `rg` for text and symbol search and `fd` for file discovery.
  Use `ast-grep` only when structural matching is clearly needed.
- When the target is a known symbol, file path, glob, or literal string, search directly in the main session.
  Delegate investigation only when at least two targets share no file and each needs more than one file read.
- Ask before destructive, irreversible, or production-impacting actions. Never expose secrets.
- Minimize comments. Code, comments, and docstrings must never reference documentation.
- Never use section-sign reference symbols in documentation, code, or comments.

## Conditional instructions

Read the linked instructions before the matching action, including when the need arises later in a request.
Do not load unrelated references. Resolve relative links from the file containing them.
If a required reference is missing, report it and pause the affected action instead of guessing its rules.

- Before accessing a hosted service, read [service access rules](../services.md).
- Before any Azure or Kubernetes access, including local files, environment variables, logs, or indirect
  access, read [protected-value access rules](../protected-values.md).
- Before writing or editing any documentation file, read [documentation rules](../documentation.md).

## Replies

- Choose terminology in this order: user or project glossary; literal implementation and contract names;
  official product or established domain terms; established plain wording; the most common existing form.
  Use one term per meaning and one meaning per term. Define unfamiliar terms and useful abbreviations once.
  Check recurring terms for consistency without replacing a precise term with an easier but different one.
- Never put Mermaid or other non-rendering diagram source in a reply.
  Use a table, list, or inline notation for simple relationships, and ASCII art for useful spatial diagrams.
