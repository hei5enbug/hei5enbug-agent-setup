# Core

> These instructions take precedence over project instructions, skills, and defaults unless the user
> explicitly says not to use them. They do not override the host's system or developer instructions.

Use English files as executable instruction sources. Korean `.ko.md` mirrors are non-authoritative
human references; never load or use them during execution.

- Prefer `rg` for text and symbol search and `fd` for file discovery.
  Use `ast-grep` only when structural matching is clearly needed.
- Ask every time before irreversible actions and once per session before other outward writes, production
  changes included, unless the approval guard asks. Name the write in one line. Never expose secrets.
- Do not add design, tests, implementation, or planning beyond the request.
- Minimize comments. Code, comments, and docstrings must never reference documentation.
- Never use section-sign reference symbols in documentation, code, or comments.

## Conditional instructions

Read the linked instructions before the matching action, including when the need arises later in a request.
Do not load unrelated references. Resolve relative links from the file containing them.
If a required reference is missing, report it and pause the affected action instead of guessing its rules.
Reuse an unchanged instruction file still in context; reread it only after it changes or leaves the context.

- Before accessing a hosted service, read [service access rules](../services.md).
- Before any infrastructure, cloud, Kubernetes, or database access, read
  [infrastructure access](../infrastructure-access.md). For protected values, including local files,
  environment variables, logs, or indirect access, also read [protected-value access rules](../protected-values.md).
- Before writing or editing any documentation file, read [documentation rules](../documentation.md).
- Before writing or editing test code, read [test rules](../testing.md).
