# Drawing groups and subgroups

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
