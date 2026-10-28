# Declaration Options

Rules that apply only when the declaration uses the option. Read this file before step 4 of the workflow.

## Tracker kind other than `github`

Use one path for the duplicate search in step 4, the create in step 7, and the read-back in step 8: the tracker's
connected tool when that tool reaches the declared location; otherwise that tracker kind's official CLI, such as
`az boards` for an Azure DevOps location or `glab` for GitLab, only when it is already authenticated. Never log in,
and never pass, print, or store a credential. When neither path can do all three at the declared location, show
the draft and file nothing.

## HTML body

- In the draft, use `<h2>` for the section headings, `<ul>` or `<ol>` for lists, and `<code>` for code.
- In step 8, confirm on the rendered item that no raw tag, such as `<h2>`, and no escaped entity, such as `&lt;`,
  shows.

## Tag template

Applies when `target.label_mode` is `template`.

- Split `target.labels` at `;` and expand `{skill}` to the owning skill's name; for an instruction file, use its
  file name without extension. Apply every resulting tag in order.
- For a new-skill proposal, `{skill}` expands to the proposed skill's name followed by the tag `new-skill`.
- In step 6, show the tags where the preview names the label.
- On GitHub, repeat `--label` in step 7 for each tag.
- In step 8, confirm every tag.
