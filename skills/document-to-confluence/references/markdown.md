# Markdown source

Use this adapter for Markdown files, Markdown fragments, and Markdown supplied in the prompt.

## Extraction

Preserve ATX and setext heading levels, paragraph boundaries, list nesting, block quotations,
fenced code blocks, tables, links, images, footnotes, and diagram fences.
Treat frontmatter as document metadata only when its keys have an agreed publishing purpose.
Do not publish build settings or repository control values as page content.

Resolve relative assets against the source file's directory.
Resolve relative links only to determine their intended target.
Replace a repository-relative destination with a published page link or useful wording before publishing.
Never expose an absolute local path.

## Diagrams and embedded HTML

Keep fenced diagram source as a diagram block in the common model.
Apply `references/diagrams.md` before publishing it.

Treat raw HTML as an unsupported Markdown extension until it is inspected.
If the HTML is intentional document content, apply `references/html.md` to that block.

## Fidelity check

Run `scripts/text_parity.py` only when the source stays within its declared subset.
Use `--drop` for source text deliberately replaced by a non-text artifact, such as diagram source.
When the script reports an unsupported construct, compare that construct manually instead of treating it as a match.

Confirm the source file revision immediately before saving the page.
