---
name: markdown-to-confluence
description: >-
  Convert a Markdown document into a Confluence page and keep it updated, including a native table
  of contents, inline images, attachments, and diagrams rendered to images. Use when publishing a
  design document, spec, report, or plan to Confluence, when a page's images render as attachment
  cards or fail to display, when diagram source appears as raw text on the page, when a page shows
  local file paths, or when an existing Confluence page must be updated in place.
compatibility: >-
  Needs a Confluence write path, either a connected integration tool or direct REST access. Without
  one, the skill still produces the exact body and attachment set for manual upload. Diagram
  rendering needs a headless browser and a browser automation module. Image measurement uses the
  Python standard library only. Every capability has a declared fallback.
---

# Markdown to Confluence

Publish a Markdown document as a Confluence page, and keep that page correct on every later edit.

## Why this skill exists

Confluence accepts an HTML body, but its converter rewrites some markup, rejects other markup
outright, and renders diagram source as plain text. Each failure looks like a formatting mistake
and is really a contract mistake, so guessing at the markup wastes a publish cycle every time.

`references/html-format.md` holds the markup contract. This file holds the procedure.

## Portability contract

Adapt to capabilities, never to product names.

1. Detect what this host can do before choosing mechanics. Do not assume an integration tool
   exists, and do not name one in your reasoning or output.
2. Do not assume installation paths, environment variables, or CLI syntax. Discover them, or accept
   them as configuration, or ask.
3. Keep every stage even when a capability is missing. The final fallback is always to hand the
   finished artifacts to the user.
4. When the host does not report a value, leave it empty. Never invent a page id, an attachment
   id, or a pixel dimension.
5. This skill is self-contained. Do not call, read, or depend on another skill's files.

### Capability map

| Capability | Preferred path | Fallback |
|---|---|---|
| Page read and write | Connected Confluence tool | REST call with user-supplied credentials; then write the body to a file and hand it over |
| Attachment upload | Connected attachment tool | REST multipart; then export the files and ask the user to upload them |
| Headless browser | Render diagrams with `scripts/render_diagrams.mjs` | Leave the diagram source in place and tell the user rendering is still required |
| Image measurement | `scripts/image_size.py` | Ask the user for pixel dimensions |
| Body validation | `scripts/validate_body.py` | Walk the checklist in `references/html-format.md` by hand |
| Ignored staging path | `git check-ignore` | Use a temporary directory, and if upload rejects the path, ask the user for an allowed one |
| Filesystem | Write artifacts to disk | Print the body inline in the conversation |

## Run configuration

Settle these before touching the page. Take each value from the conversation first, then from
discovery, and only then ask. Never hardcode any of them into a bundled file.

| Value | How to settle it |
|---|---|
| Target page | An existing page id, or a space key plus parent for a new page |
| Source document | The Markdown file or the text in the conversation |
| Staging directory | A writable path inside the repository that version control ignores; confirm with `git check-ignore` |
| Display width | Body images and table images use different widths; propose a default and confirm |
| Document language | Drives the diagram font stack; take it from the source text |
| Table of contents depth | Propose a default and confirm |

## Workflow

Skip any step the document does not need. A document with no images or diagrams goes straight
from step 3 to step 7.

### 1. Detect capabilities and settle configuration

Record which path each capability takes. State any fallback you had to use, because a fallback
changes what the user must do after you finish.

### 2. Read the current page

For an update, fetch the current body in HTML form before changing anything. Confluence has no
partial edit. Every save replaces the whole body, so an unread body means silent data loss.

Preserve anything already in the body that you did not intend to change, including generated
macro identifiers.

### 3. Convert the Markdown

Convert structure first, then fix what does not belong on a published page.

- Remove sections written for the document's authors rather than its readers.
- Remove local filesystem paths. Replace a path reference with a description of the thing.
- Replace relative Markdown links with in-page wording, because those links do not resolve on
  Confluence.
- Wrap the content of every table cell in a block element.
- Escape quotes and other reserved characters in text.

Keep the author's wording. This step changes containers, not sentences.

### 4. Render diagrams

Read `references/diagrams.md`.

Diagram source published as text stays text. Render each diagram to an image.

**Look at every rendered image before uploading it.** Overlapping labels, clipped glyphs, and
missing text are common and invisible to any automated check. If the host cannot show you an
image, say so and ask the user to check it.

### 5. Upload attachments

Read `references/attachments.md`.

Upload before you reference. A body that points at a missing attachment renders as a broken
placeholder, and repairing it costs another publish cycle.

### 6. Measure and size every image

Run `scripts/image_size.py` against each file with the chosen display width. Write the returned
`width` and `height` onto the `img` element.

An image whose stated ratio does not match its real ratio is stretched on the page. Never estimate
these numbers.

### 7. Validate the body

Run `scripts/validate_body.py`. Fix every finding. The checker covers exactly the mechanical failures
listed in its own scope declaration and nothing else, so also read the body once yourself for the
things it cannot judge, such as wording, ordering, and whether a diagram actually explains the
paragraph next to it.

### 8. Save

Send the complete body. Write a version message that names what changed in this save.

### 9. Confirm

Fetch the page again, or ask the user to look at it. Report which capability fallbacks were used
and what remains for the user to do.

### 10. Clean up only with approval

Deleting an attachment cannot be undone. List what you propose to delete and why, then wait for an
explicit answer. Never delete as a tidy-up gesture.

## Rules that hold on every document

These come from published-page failures, not from style preference. The reasoning behind each one
is in `references/html-format.md`.

- Write a plain `img` element for an inline image. The converter turns it into the correct figure
  node by itself. A hand-written `media-single` container is rejected outright.
- Never use a `media-group` container for a body image. It renders as an attachment card.
- Images work inside table cells. Do not dismantle a table to place an image.
- An attachment id and a media file id are different values. Referencing the wrong one creates an
  empty attachment named after the identifier string.
- Use the built-in table of contents macro rather than a hand-written list.
- Do not invent a macro identifier. Omit it on a new macro, and preserve one that already exists.

## Safety

- Publishing makes content visible to everyone with page access. Confirm the target page before
  the first save.
- Attachment deletion needs explicit approval.
- Never place credentials in the body, in a version message, or in a bundled file.

## References

Read these when the step calls for them, not upfront.

| File | Read it when |
|---|---|
| `references/html-format.md` | Writing or repairing body markup |
| `references/attachments.md` | Uploading, referencing, or deleting attachments |
| `references/diagrams.md` | The document contains diagrams |

## Bundled resources

| Path | Contract |
|---|---|
| `scripts/image_size.py` | Reads PNG, JPEG, and GIF dimensions using only the standard library. Reports unsupported input as a failure rather than skipping it |
| `scripts/validate_body.py` | Validates the mechanical body rules within its declared scope. Sound and complete inside that scope, silent outside it |
| `scripts/render_diagrams.mjs` | Captures elements from a local HTML file to images. Declares its browser dependency and fails loudly when it is missing |
| `assets/diagram-template.html` | Starting point for hand-built diagrams. Colors and layout are defaults, not requirements |

Run each script with `--help` for its exact interface.
