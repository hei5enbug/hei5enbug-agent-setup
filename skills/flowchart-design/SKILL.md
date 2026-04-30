---
name: flowchart-design
description: Cross-tool design standard for static flow diagrams. Use when authoring, revising, or exporting flow charts in SVG, HTML/CSS, Figma, or draw.io — especially when several charts must read as one design system. Triggers on requests like "design a flow chart", "unify these diagrams", "fix flow chart spacing", "PNG export padding", "retighten viewBox".
---

# Flowchart Design Standard

A shared specification for static flow charts authored across different tools (SVG, HTML/CSS, Figma, draw.io). The goal: any chart that follows this document looks like it came from the same design system as every other chart that follows it. The rules below describe **relative behavior, not absolute values** — node counts, edge geometry, and domain semantics differ from chart to chart, so concrete pixel sizes, step counts, and offsets must be decided by the author and applied **consistently within a chart set**, not copied from this document.

This standard prioritizes layout principles, spacing discipline, label rules, simplification criteria, and outer-frame handling over any project-specific terminology.

---

## 1. Core Principles

1. **Flow first, decoration second.** A reader should grasp the left-to-right or top-to-bottom direction in a single pass.
2. **Same role, same visual grammar.** Identical platforms, identical edge meanings, and identical group categories must always share color, shape, and structure across every chart in a set.
3. **Spacing must not break before meaning does.** When nodes are removed or hidden, redistribute the remaining nodes and edges before publishing.
4. **Hidden elements leave no trace.** Removing a group border, subtitle, or node also requires recomputing the outer frame and `viewBox`.

These principles override every later rule when they conflict.

---

## 2. Visual Tokens

Tokens are described by **relative weight and role**, never by absolute values. Pick concrete values once per chart set and reuse them everywhere.

### 2.1 Canvas

- Use a light, neutral solid background by default.
- Overview-style charts that compare several streams at once may use a very faint tonal variation in the background.
- Outer padding is controlled by `viewBox` cropping, not by enlarging the SVG element.
- The framing target is "tight to actual content," never "centered inside an arbitrary canvas."

### 2.2 Typography

Establish a hierarchy and keep it consistent across the set:

| Role | Relative weight |
|---|---|
| Default UI font | Sans-serif (e.g., Pretendard Variable family) |
| Identifier font | Monospace (e.g., JetBrains Mono family) for paths, commands, tags, variable names |
| Group header | Highest hierarchy in the chart |
| Subgroup header | Below group header, above node labels |
| Node main label | Slightly heavier than body text |
| Node sub label | One step lighter than the main label |
| Subgroup subtitle | Lightest auxiliary text |
| Edge label | Comparable to or slightly lighter than the node main label |

### 2.3 Nodes

- The node boundary is the entire `<g class="node">` group: icon box, image, main label, and sub label together. It is **not** the icon rectangle alone.
- Default node shape: rounded rectangle with a white fill and a soft border. Choose a square-ish aspect ratio that reads stably in a single-row chart.
- Overview compact nodes preserve the same shape language at a smaller scale; the icon shrinks with them but its visual center stays intact.
- Main label = the category the reader needs first (platform, resource type). Sub label = the identifier that distinguishes this node from siblings (path, command, tag, role detail). Use sub labels only when the main label alone is ambiguous.

### 2.4 Edges

| Style | Meaning | Visual weight |
|---|---|---|
| accent | User- or developer-triggered initiation | Most prominent line color and thickness |
| solid | Default delivery, deployment, or execution flow | Neutral baseline line |
| dashed | Auxiliary or weak link, used only when necessary | Lowest visual presence |

Edge geometry rules:

- All edges carry a terminal arrowhead by default.
- Arrowhead endpoints anchor to the **whole node group** (`<g class="node">`), not to the icon box or the icon image. An arrow that visually points at the icon alone is a mis-anchored edge — recompute it.
- Leave a small, consistent breathing gap between the arrowhead tip and the node boundary. When using SVG marker arrowheads, place the path endpoint slightly outside the node boundary so the marker glyph does not overlap the node interior.
- For bottom-to-top edges, target the outer edge of the lowest label region of the destination node, not the bottom of its icon box. Top-to-bottom edges follow the same rule against the topmost label region.
- For two-bend (Z-shaped or L-shaped) edges of the form `start → vertical → horizontal → vertical → end`, the two vertical segments must be equal in length, which means the mid-axis y is the midpoint of the start and end y values.
- Whatever breathing gap you choose, apply it identically across the entire chart.

---

## 3. Layout

### 3.1 Alignment

- The default form is a **single-row left-to-right linear flow**.
- When complexity increases, rows may stack, but every row internally maintains the same column rhythm.
- In overview charts that show several streams in parallel, every row aligns to the same x-axis columns.

### 3.2 Spacing Rhythm

- Within a row, every node-to-node gap is identical, which makes every same-row edge identical in length.
- Edges that travel in the same direction maintain the same length rhythm wherever possible.
- Horizontal and vertical edges may carry different rhythms, but each axis has its own consistent system.
- After removing a node, redistribute the remaining nodes so no single edge becomes anomalously long. The only exception: a direct connection is genuinely more accurate than the removed intermediary, in which case the long edge stays — but row/column alignment, label centering, and outer-frame balance must still be preserved.

### 3.3 Wrapping

When a single row is too long, apply this order:

1. Remove duplicates first.
2. If still too long, switch to a wrapped layout.
3. After wrapping, every row internally keeps its own equal spacing.
4. Row-transition edges may be vertical or L-shaped, but the reading direction of each row must be unambiguous.

A typical wrap: row 1 reads left-to-right, the transition edge is vertical, row 2 reads either right-to-left or left-to-right again. Pick one reading rule for the diagram and hold it for every subsequent row.

---

## 4. Outer Frame and Export

The completeness of a chart is decided more by its outer framing than by anything inside the nodes. After every structural change, the frame must be recomputed.

### 4.1 viewBox

`viewBox` is recalculated against the bounding box of the **currently visible** content: nodes, edges, arrowheads, text (including descenders), icons, group borders, strokes, markers, and shadows. Coordinates left over from hidden groups, removed nodes, or earlier layouts must be excluded — never inherit a previously generous canvas.

After recomputing `viewBox`, the four outer distances — first node to left edge, last node to right edge, top text to top edge, bottom text to bottom edge — should read as visually balanced.

### 4.2 PNG Export

Browser viewport size, `100vh` height, and full-page screenshots are not valid final outputs. The deliverable PNG must be cropped to the rendered visible content and then re-padded with the **same value on all four sides**.

Visible content includes nodes, edges, arrowheads, icons, text, group containers, section titles, and separators. It excludes browser viewport whitespace, `100vh`-induced page space, CSS layout padding, traces of hidden groups or subtitles, and any leftover `viewBox` margin from a prior layout.

Procedure:

1. Render the SVG/HTML normally. Constrain the page shell so it does not introduce empty space larger than the chart, and let the SVG height follow its `viewBox` ratio rather than being forced into the viewport.
2. Render a second pass with the same background but with the SVG visual elements hidden. The goal is a content-free image that shares the original background — including any faint gradient.
3. Diff the two renders to locate the actual content region. Do not crop by background color alone, since white icon fills will be misread as background, and corner-color trimming fails on gradients.
4. Crop the deliverable to that bounding box.
5. Re-pad the crop equally on all four sides. The padding target is "tight but not cramped," chosen once per chart set and reused; the absolute value matters less than its consistency across the set.
6. Save the deliverable with a timestamp postfix appended to the basename so iterative revisions stay traceable.

### 4.3 Verification of the Final PNG

Open the saved PNG and confirm, by eye:

- Top and bottom padding read as equal.
- Left and right padding read as equal.
- No descender, arrowhead, group border, or icon shadow is clipped.
- No empty region remains from a hidden element or a prior layout.

If the rendered PNG is visually unbalanced, do not chase the problem by re-tweaking `viewBox` alone — re-crop the rendered raster against visible content and re-apply equal padding. Documentation references only the verified PNG; raw viewport captures and pre-verification renders never appear in deliverables.

---

## 5. Labels

### 5.1 Node Labels

- Main label carries the category the reader needs first.
- Sub label appears only when the main label alone is ambiguous.
- Identifier-shaped values — paths, tags, commands, variable names — render in the monospace family.
- If a node uses main, sub, and secondary-sub labels, their hierarchy must be visually unambiguous.

### 5.2 Edge Labels

- Edges describe **what happens**; nodes describe **what something is**. Never duplicate that information across the two.
- Place edge labels at the geometric center of each edge.
- Default position is above the edge. Move the label below the edge when something competes for attention above it (a branching line, an adjacent label). Pick one above-offset value and one below-offset value per chart set and apply them consistently.
- For vertical edges, the label's primary axis sits at the midpoint of the edge.
- If only one edge has a missing label, decide whether the transition is meaningful: if yes, label it; if no, do not pad neighboring labels to compensate.

### 5.3 Length and Density

- Keep labels short and verb-led.
- Avoid stacking two transition meanings into one edge label.
- The exception: when a removed intermediary genuinely makes a single edge represent two stages, a composite label is allowed — but first try relocating the label to the most semantically natural adjacent edge.

---

## 6. Groups and Subgroups

### 6.1 When to Use a Group

Use a group container only when at least one of these holds:

- Several nodes share a single platform or category.
- A column itself carries meaning, as in overviews.
- A platform recurs across the chart and a background partition genuinely aids comprehension.

### 6.2 Group Style

Pick one tonal palette per role family and reuse it for every chart in the set:

| Role family | Background tone | Border |
|---|---|---|
| Input / source | Calm, trust-leaning hue | Same family, clearly defined |
| Processing / orchestration | Neutral, restrained hue | Same family, low visual pull |
| Storage / deployment artifact | Slightly warm or distinct hue | Same family, clearly delimited |
| Runtime / execution environment | Stable, conclusive hue | Same family, naturally connected |

Group containers use a softer, slightly larger rounded shape than individual nodes.

### 6.3 Subgroups

Subgroups bracket a portion of an existing pipeline. Their style is intentionally quiet: dashed border, near-white background, and titles or subtitles only when strictly necessary.

When the subgroup title and subtitle add nothing, hide them — and either remove the subgroup visually altogether or keep only its inner nodes. Either way, recompute the layout and the outer frame afterward.

---

## 7. Simplification

A flow chart documents **what the reader needs to follow**, not the entire system. A node is a removal candidate when any of the following is true:

- The previous node's sub label already names it.
- The incoming edge label already describes the transition outcome it represents.
- It exists, but the reader does not need it to follow the flow.
- Adding it stretches an edge without adding information.

Removing a node is incomplete until the layout, edge length rhythm, label placement, and `viewBox` have all been re-applied per the rules in §3 and §4.

---

## 8. Recommended Patterns

| Pattern | When to use | Notes |
|---|---|---|
| Overview | Several streams compared on one page | Read columns first, then each row as an independent flow. Same row index implies same semantic level. |
| Linear | Short single-pass flow | The most stable default. Should read with nodes and edges alone, no group container required. |
| Simplified Linear | Long flow distilled to its essential transitions | Keeps the linear shape; spacing and label discipline still apply. |
| Wrapped Linear | A linear flow too long for one row that does not warrant branching | Continues as a single sequential read across stacked rows. |

Pick one pattern explicitly; mixing two without intent is a quality regression.

---

## 9. Final Checklist

Run every item before declaring a chart done. Each item maps back to a rule above; this list is the gate, not a summary.

**Structure**
- Flow direction reads in a single pass.
- Same-semantic-level nodes share an axis.
- No duplicates remain.

**Spacing**
- Same-row edge lengths are equal.
- No segment is anomalously long without justification.
- Removals were followed by redistribution.

**Labels**
- Node and edge labels do not repeat the same information.
- Edge labels are short and verb-led.
- Identifiers render in monospace.

**Framing**
- Outer padding is tight, not generous.
- No empty region remains from a hidden element.
- `viewBox` was recomputed against current content.
- The deliverable PNG was cropped to visible content and re-padded equally on all four sides.

**Consistency**
- Same role family uses the same color, icon, and typographic grammar across the set.
- Charts in the same family share the same spacing rhythm.
- The chosen pattern (overview / linear / simplified / wrapped) is unambiguous.
