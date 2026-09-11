# HTML source

Use this adapter for HTML files, HTML fragments, exported web pages, and authorized rendered web content.
The source HTML is input; `references/confluence-body.md` defines the output body.

## Safe capture

Parse static HTML without executing untrusted scripts.
Do not submit the document or its assets to an external renderer without user authorization.
When meaningful content appears only after script execution, use an approved browser capability and record
the retrieval time and page state. Report content that cannot be captured.

## Semantic extraction

Prefer semantic elements and accessibility data over visual coordinates:

- derive hierarchy from headings and labelled regions;
- preserve paragraphs, lists, quotations, code, tables, links, figures, captions, and alternative text;
- use `aria-label` or equivalent accessible text only when it represents visible meaning;
- ignore navigation, cookie banners, controls, and application chrome outside the requested content scope;
- preserve meaningful `pre` whitespace and explicit line breaks;
- capture CSS background images only when they convey document content.

CSS can express meaningful grouping or order. Inspect the rendered page when styles change reading order,
hide content, create pseudo-element text, or turn generic containers into tables or callouts.
Do not copy scripts, stylesheets, event handlers, forms, or active embeds into Confluence.

## Links and assets

Resolve relative URLs against the source base URL or file location.
Download remote assets only when access is authorized and the destination permits reuse.
Keep the original link when it is stable and accessible to page readers.
Record assets that cannot be retrieved or published.

## Fidelity check

Compare visible source blocks with the normalized block inventory.
Check headings, paragraphs, lists, table dimensions, links, figures, captions, and meaningful line breaks.
Inspect both DOM order and rendered order when CSS affects layout.
