---
name: flowchart-design
description: >-
  Design, revise, validate, and export clear static flow diagrams across SVG, HTML/CSS, Figma,
  FigJam, draw.io, Mermaid, and raster deliverables. Use for flowcharts, process maps, architecture
  flows, decision flows, diagram-system unification, spacing and routing repair, overlap removal,
  accessible labeling, viewBox tightening, or PNG export correction. Works across agent hosts by
  separating the semantic graph from tool-specific rendering and using capability-based fallbacks.
compatibility: >-
  The semantic and layout workflow works in any agent host. Editable rendering, image inspection,
  browser measurement, and export require corresponding host capabilities. A text-specification
  fallback remains available without them.
---

# Flowchart Design Standard

A shared specification for static flow charts authored across different tools (SVG, HTML/CSS, Figma, draw.io).
The goal: any chart that follows this document looks like it came from the same design system as every other chart that follows it.
The rules below describe **relative behavior, not absolute values**.
Node counts, edge geometry, and domain semantics differ by chart, so choose concrete sizes and offsets for the current work.
Apply them **consistently within a chart set** instead of copying values from this document.

This standard prioritizes layout principles, spacing discipline, label rules, simplification criteria, and outer-frame handling over any project-specific terminology.

## 0. Portable Workflow

Complete the same logical stages regardless of the host or drawing tool.

### 0.1 Discover Capabilities

Select the strongest available path without requiring a named product:

1. **Native editable canvas** when the host can create and inspect diagram nodes and connectors.
2. **Code-native vector** when files can be edited and rendered; prefer SVG for deterministic geometry.
3. **Diagram DSL** when only text-to-diagram rendering is available; use it for topology, then export or refine when visual control permits.
4. **HTML/CSS** when browser rendering is available and the diagram benefits from measured text/layout.
5. **Text specification** when no rendering capability exists; return the semantic graph, layout contract, and renderer-ready source rather than pretending visual verification occurred.

Parallelism, image inspection, and browser automation improve verification but are optional. Missing capabilities must be reported accurately and must not change the semantic graph.

### 0.2 Build the Semantic Graph First

Before choosing coordinates, normalize the source into:

- nodes with stable IDs, concise labels, roles, and optional detail;
- directed edges with source, target, outcome label, and edge type;
- decision branches with distinguishable outcomes;
- groups that express real ownership or phase boundaries;
- explicit start/end points and external systems;
- the intended primary reading direction.

Reject or resolve orphan nodes, duplicate IDs, dangling edges, cycles presented as linear flows, and branch labels that do not distinguish outcomes.
If business meaning is ambiguous, ask before encoding it visually.

### 0.3 Choose a Layout Contract

Choose one pattern from section 8 and state the reading direction, node ranks, group nesting, edge-routing policy, token set, label grammar, target formats, and editability requirement.

Do not let automatic layout silently change semantic order. When a renderer cannot honor the contract, simplify the layout or select a more controllable representation.

### 0.4 Render Incrementally

Render in this order: frame and ranks, nodes, primary edges, branches, groups, labels, decoration. Re-measure after any label or node removal.
Use established design-system components and variables when available; otherwise define one compact local token set.

### 0.5 Validate at Three Levels

1. **Semantic**: every source fact is represented once, edge directions and branch outcomes are correct, and no invented transition appears.
2. **Geometric**: alignment, spacing, routing, containment, crop, and overlap rules pass.
3. **Rendered**: inspect the actual final SVG, PNG, or canvas export at delivery size. Source correctness alone is insufficient.

If rendered inspection is unavailable, mark the result `not visually verified` and identify the exact remaining check.

---

## 1. Core Principles

1. **Flow first, decoration second.** A reader should grasp the left-to-right or top-to-bottom direction in a single pass.
2. **Same role, same visual grammar.** Identical platforms, identical edge meanings, and identical group categories must always share color, shape, and structure across every chart in a set.
3. **Spacing must not break before meaning does.** When nodes are removed or hidden, redistribute the remaining nodes and edges before publishing.
4. **Hidden elements leave no trace.** Removing a group border, subtitle, or node also requires recomputing the outer frame and `viewBox`.
5. **No accidental overlap.** Two elements that are not in a containment relationship (group → contents, node → its own internal icon and labels) must not visually overlap.
   "Visually" includes glyph stroke and icon stroke, not just bounding box centers.

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
- Main label = the category the reader needs first (platform, resource type). Sub label = the identifier that distinguishes this node from siblings (path, command, tag, role detail).
  Use sub labels only when the main label alone is ambiguous.

**Internal zones must be mutually exclusive.** Each node has predeclared rectangular zones — `icon zone`, `main-label zone`, `sub-label zone`, optional `body zone`. No zone may overlap another.
A label centered with `text-anchor="middle"` at the node's horizontal center is still a violation if the label's measured width pushes its bounding box into the icon zone — in that case, choose one:

- (a) switch to `text-anchor="start"` anchored at `icon-zone-right + padding`,
- (b) widen the node, or
- (c) shorten the label (drop sub-categorical words, abbreviate).

Eyeballing the center is forbidden. Compute the label's bounding box from `font-size × glyph-count` (monospace) or measure the rendered SVG (proportional) before publishing.
Same-role nodes (e.g., every processing stage in a row) must pass this check; whichever node has the longest label sets the floor.

**Same-node grid coherence.** Within a single node, all text elements share the same horizontal anchor (`x`).
If main, sub, and body labels use different `x` values, the node's internal grid is broken — the reader perceives misalignment even when each individual label looks centered in its own context.
If two anchors are genuinely needed, declare each one in the node's zone definition.
For example, a centered main label may sit beside an icon while a body block stays left-aligned.
Apply the same anchor pair to every node of the same role.
Per-text ad-hoc anchors are forbidden.

### 2.4 Edges

| Style | Meaning | Visual weight |
|---|---|---|
| accent | User- or developer-triggered initiation | Most prominent line color and thickness |
| solid | Default delivery, deployment, or execution flow | Neutral baseline line |
| dashed | Auxiliary or weak link, used only when necessary | Lowest visual presence |

Edge geometry rules:

- All edges carry a terminal arrowhead by default.
- Arrowhead endpoints anchor to the **whole node group** (`<g class="node">`), not to the icon box or the icon image.
  An arrow that visually points at the icon alone is a mis-anchored edge — recompute it.
- Leave a small, consistent breathing gap between the arrowhead tip and the node boundary.
  When using SVG marker arrowheads, place the path endpoint slightly outside the node boundary so the marker glyph does not overlap the node interior.
- For bottom-to-top edges, target the outer edge of the lowest label region of the destination node, not the bottom of its icon box.
  Top-to-bottom edges follow the same rule against the topmost label region.
- For two-bend edges, the two vertical segments must be equal in length.
  This makes the mid-axis y the midpoint of the start and end y values.
- Whatever breathing gap you choose, apply it identically across the entire chart.
- **Breathing gap is symmetric at both ends of an edge.** If the start has 3 px to its source node boundary, the end must have 3 px to its target node boundary as well.
  Asymmetric gaps — one end touching, the other not — signal author inattention and read as the edge being wedged into one endpoint.
  This applies to control edges between bands and to in-band pipeline edges.
  An edge starting at a container boundary but ending above a node boundary has a wrong endpoint.

---

## 3. Layout

### 3.1 Alignment

- The default form is a **single-row left-to-right linear flow**.
- When complexity increases, rows may stack, but every row internally maintains the same column rhythm.
- In overview charts that show several streams in parallel, every row aligns to the same x-axis columns.
- **Cross-band column alignment.** Related items in stacked bands share the same x-axis column.
  Examples include an upper stage and its lower artifact, or an orchestrator and the stages it controls.
  For an m:n mapping, draw an explicit connector, make the column counts match, or treat the bands as independent.
  Half-aligned columns — where some items align across bands but others drift by a non-zero offset — are worse than no alignment, because the reader infers a relationship that breaks under inspection.

### 3.2 Spacing Rhythm

- Within a row, every node-to-node gap is identical, which makes every same-row edge identical in length.
- Edges that travel in the same direction maintain the same length rhythm wherever possible.
- Horizontal and vertical edges may carry different rhythms, but each axis has its own consistent system.
- After removing a node, redistribute the remaining nodes so no single edge becomes anomalously long.
  Keep a long edge only when a direct connection is more accurate than the removed intermediary.
  Preserve alignment, label centering, and outer-frame balance in that case.
- **Within-container content spacing is uniform.** Adjacent items inside a single container — a band, group, subgroup, or storage box — are spaced within ±5% of the mean gap of that container.
  An outlier gap (e.g., a single 240 px gap among items otherwise spaced at 180–190 px) reads as either a missing item or a category break; if neither is intended, redistribute.
  If a category break is intended, mark the wider gap with an explicit separator — a thin divider, a sub-caption, or labeled whitespace — so the reader can tell an intentional gap from a layout slip.

### 3.3 Wrapping

When a single row is too long, apply this order:

1. Remove duplicates first.
2. If still too long, switch to a wrapped layout.
3. After wrapping, every row internally keeps its own equal spacing.
4. Row-transition edges may be vertical or L-shaped, but the reading direction of each row must be unambiguous.

A typical wrap: row 1 reads left-to-right, the transition edge is vertical, row 2 reads either right-to-left or left-to-right again.
Pick one reading rule for the diagram and hold it for every subsequent row.

---

## 4. Outer Frame and Export

The completeness of a chart is decided more by its outer framing than by anything inside the nodes. After every structural change, the frame must be recomputed.

### 4.1 viewBox

`viewBox` is recalculated against the bounding box of the **currently visible** content: nodes, edges, arrowheads, text (including descenders), icons, group borders, strokes, markers, and shadows.
Coordinates left over from hidden groups, removed nodes, or earlier layouts must be excluded — never inherit a previously generous canvas.

After recomputing `viewBox`, the four outer distances — first node to left edge, last node to right edge, top text to top edge, bottom text to bottom edge — should read as visually balanced.

### 4.2 PNG Export

Browser viewport size, `100vh` height, and full-page screenshots are not valid final outputs.
The deliverable PNG must be cropped to the rendered visible content and then re-padded with the **same value on all four sides**.

Visible content includes nodes, edges, arrowheads, icons, text, group containers, section titles, and separators.
It excludes browser viewport whitespace, `100vh`-induced page space, CSS layout padding, traces of hidden groups or subtitles, and any leftover `viewBox` margin from a prior layout.

Procedure:

1. Render the SVG/HTML normally.
   Constrain the page shell so it does not introduce empty space larger than the chart, and let the SVG height follow its `viewBox` ratio rather than being forced into the viewport.
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

If the rendered PNG is visually unbalanced, do not chase the problem by re-tweaking `viewBox` alone — re-crop the rendered raster against visible content and re-apply equal padding.
Documentation references only the verified PNG; raw viewport captures and pre-verification renders never appear in deliverables.

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
- Default position is above the edge. Move the label below the edge when something competes for attention above it (a branching line, an adjacent label).
  Pick one above-offset value and one below-offset value per chart set and apply them consistently.
- For vertical edges, the label's primary axis sits at the midpoint of the edge.
- If only one edge has a missing label, decide whether the transition is meaningful: if yes, label it; if no, do not pad neighboring labels to compensate.
- **Edge label background plate must cover the edge line.** Add a plate only when the edge would pass through the label glyph.
  Use a canvas-colored rectangle slightly larger than the text bounding box so it hides the line.
  If the label is offset from the edge so the edge line never crosses the glyph, the plate is unnecessary — do not add one.
  A plate that does not cover any edge segment is visual noise without function: the plate exists to fix a specific collision, and absence of collision means absence of plate.

### 5.3 Length and Density

- Keep labels short and verb-led.
- Avoid stacking two transition meanings into one edge label.
- A composite label is allowed when removing an intermediary makes one edge represent two stages.
  First try moving the label to the most semantically natural adjacent edge.

### 5.4 Accessibility and Text Equivalence

- Do not encode meaning by color alone; pair role color with shape, label, icon, or line style.
- Keep text contrast readable against fills and background at final delivery size.
- Give every decision edge an explicit outcome label unless its destination makes the result unambiguous.
- Preserve a text equivalent: ordered node/edge data, accessible SVG title/description, or an adjacent structured summary.
- Use stable reading order in editable canvases and DOM/SVG source where supported.
- Do not place essential prose only inside a raster image.

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

When the subgroup title and subtitle add nothing, hide them — and either remove the subgroup visually altogether or keep only its inner nodes.
Either way, recompute the layout and the outer frame afterward.

### 6.4 Container and Caption Discipline

**Container span matches its declared logical scope.** A container may wrap stages, artifact paths, or nodes.
Its left and right edges match the outer edges of the wrapped items.
If a uniform inset is desired instead, apply the same inset on all four sides and document it as an explicit padding constant.
Mismatch between "what the container is supposed to cover" and "what its coordinates actually cover" is a visual contradiction: readers infer scope from coordinates, not from author intent.

**Group caption alignment follows a single rule per chart.** Every group, band, and subgroup caption in a chart uses the same horizontal alignment rule — one of:

- (a) canvas-left padding (a constant `x` for every caption),
- (b) the caption's own container left edge, or
- (c) the caption's first wrapped item left edge.

Pick one rule per chart and apply it uniformly.
Mixing two rules — some captions at canvas-left, others at container-left — reads as inconsistent layout even if each caption is "correctly" placed under one of the rules considered in isolation.

**Source-code comments match actual coordinates.** Inline layout comments must match actual coordinates and attributes.
This applies to SVG, HTML/CSS, and programmatic draw.io or Figma output.
A comment that claims `spans X 230-1150` next to `x=270, width=820` is a lie — it obscures author intent and breaks reviewability.
Comments are part of the chart's contract, not docstrings; when coordinates change, the comment updates in the same edit.

---

## 7. Simplification

A flow chart documents **what the reader needs to follow**, not the entire system. A node is a removal candidate when any of the following is true:

- The previous node's sub label already names it.
- The incoming edge label already describes the transition outcome it represents.
- It exists, but the reader does not need it to follow the flow.
- Adding it stretches an edge without adding information.

Removing a node is incomplete until the layout, edge length rhythm, label placement, and `viewBox` have all been re-applied using "Layout" and "Outer Frame and Export" in this file.

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
- No element overlaps another outside a containment relationship. Long identifier labels (≥ 8 monospace chars, or visually wide proportional labels) were measured, not eyeballed.
- All text elements inside a single node share the same horizontal anchor, or the anchors are explicitly declared per node-role.

**Spacing**
- Same-row edge lengths are equal.
- No segment is anomalously long without justification.
- Removals were followed by redistribution.
- Edge breathing gaps are symmetric at both ends.
- Within-container spacing of homogeneous items is uniform within ±5% of the mean.

**Labels**
- Node and edge labels do not repeat the same information.
- Edge labels are short and verb-led.
- Identifiers render in monospace.
- Edge label background plates (when present) actually cover the edge line they sit on; plates that cover no edge segment were removed.

**Framing**
- Outer padding is tight, not generous.
- No empty region remains from a hidden element.
- `viewBox` was recomputed against current content.
- The deliverable PNG was cropped to visible content and re-padded equally on all four sides.
- Container left/right edges match their declared logical span (or share an explicit uniform inset on all four sides).

**Consistency**
- Same role family uses the same color, icon, and typographic grammar across the set.
- Charts in the same family share the same spacing rhythm.
- The chosen pattern (overview / linear / simplified / wrapped) is unambiguous.
- All group / band / subgroup captions follow a single horizontal-alignment rule.
- Source-code comments about layout match actual coordinates.

**Semantic integrity**
- Stable node IDs are unique and every edge resolves to two existing nodes.
- Edge direction and decision outcomes match the source material.
- No source fact is duplicated as separate nodes without intent.
- Cycles, retries, and error paths are visually distinguishable from the primary flow.
- The chart has explicit entry and terminal states, or documents why it does not.

**Accessibility**
- Color is not the only carrier of meaning.
- Text contrast and final-size legibility were checked.
- A text-equivalent node/edge representation or accessible description exists.
- Reading order matches the visible flow where the format supports it.

**Delivery evidence**
- Editable source and rendered deliverable correspond to the same revision.
- The final exported artifact, not only source markup, was inspected.
- Unavailable visual or accessibility checks are disclosed rather than assumed.
- Output paths and formats match the request; temporary renders are not presented as final files.
