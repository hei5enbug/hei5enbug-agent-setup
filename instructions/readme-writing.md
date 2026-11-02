# README writing

A first-time visitor should learn what the project is, whether it fits their needs, and how to reach a first success.
Apply every [documentation rule](documentation.md); this file adds only README-specific rules.
Repository conventions, including translated mirrors, badges, and required sections,
take precedence over these defaults.

## Default order

| Section | Include when | Reader goal |
|---|---|---|
| Title and value statement | Required | Explain in one sentence what the project does and for whom. |
| Main capabilities | Required | Show the few reasons to use it. |
| Supported platforms and prerequisites | Required | Let the reader decide whether they can run or use it. |
| Installation and first use | Required | Give the shortest runnable route to a useful result; for a non-runnable project, show how to use its content. |
| Features, commands, or workflows | When there are several to choose from | Help the reader choose, with one-line purposes. |
| Documentation map | When deeper documents exist | Link each topic with the question it answers. |
| Development or contribution | When contributors need a separate entry point | Give required checks or link the contribution guide. |
| Help, related resources, and license | Required; list only the routes that exist | Show where to get help, contribute, and learn the usage terms. |

## Keep the page useful

- Keep the README an orientation page. Move a topic that needs more than about one screen, roughly 40 lines,
  into a linked document.
- Put a runnable quick start before reference material. Separate installation, first use, and advanced configuration.
- State prerequisites and supported platforms before commands. Put copyable commands in code blocks with a language tag.
- Add a short contents list when the page has more than six second-level sections or takes several screens to scroll.
- Add a screenshot or GIF only when it shows output or an interface that prose cannot, and give every image alt text.
- Preserve required commands and sections when restructuring. Move detailed content with its links and mirrors;
  the README should still lead the reader to it.
- Keep badges only when they serve the reader and follow repository conventions; do not add service-dependent badges
  merely to decorate the page.
- Do not restate deeper documentation or state the project's own release version. Instead of a change-history
  section, link the changelog or release notes, which overrides the change-history rule in documentation rules.
- Keep repository-internal agent rules in their instruction source, outside the reader page.
