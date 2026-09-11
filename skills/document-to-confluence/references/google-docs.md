# Google Docs source

Use this adapter for a native Google Doc.
Access it through an authenticated Google Drive or Docs connector, never anonymous URL fetching.

## Stable capture

Record the file ID and strongest available revision identifier or modified time.
Read all requested tabs and their native structure.
If native structure is unavailable, export to DOCX or HTML and apply that adapter while retaining the
Google Drive revision as the source marker.

## Content selection

Preserve headings, paragraphs, lists, tables, links, images, footnotes, bookmarks, and tab order.
Resolve supported smart chips to useful visible text and a stable link when readers can access the target.
Preserve dates and people names as displayed unless the user requests another representation.

Comments, suggestions, resolved threads, and version history are review data rather than page body content.
Include them only when the user requests them.
Do not silently accept or reject suggestions.

## Assets and access

Export or download embedded images through the authenticated connector when possible.
Do not assume that a Google Drive sharing permission carries over to Confluence.
For links to private Drive content, confirm that intended page readers can open them or replace the link with
an approved attachment or explanation.

## Fidelity check

Compare the requested tab count, headings, paragraphs, list nesting, table dimensions, links, images,
footnotes, and smart chips with the normalized block inventory.
Read the source revision again immediately before publishing and rebuild changed blocks.
