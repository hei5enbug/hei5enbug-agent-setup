# Context Detection (Step 0)

This module defines how the skill auto-detects project context across 4 axes before any design work begins.

## Section 1: Scan Procedure (4 steps)

Detection runs in order, reading only files that actually exist. Missing signals are skipped; if all signals are missing, enter Greenfield Fallback (Section 5).

### Step 1: Project Metadata

1. Run `ls` at project root and infer manifest candidates by filename patterns (heuristic recognition, not strict hardcoded allowlist).
2. Recognize common build/package manifests as examples (not exhaustive): `package.json`, `pyproject.toml`, `pom.xml`, `Cargo.toml`, `go.mod`, `Gemfile`, `composer.json`, `pubspec.yaml`, `build.gradle`, `Package.swift`, `*.csproj`, `mix.exs`, `deno.json`, `Makefile`, `CMakeLists.txt`.
3. If manifest exists, parse metadata/dependencies/description fields for stack + domain hints.
4. If no manifest exists, infer stack from source extensions (`.java`/`.kt` -> JVM, `.py` -> Python, `.rs` -> Rust, `.go` -> Go, `.swift` -> Swift, `.dart` -> Dart, `.js`/`.ts` -> JS/TS, `.html` -> static web).
5. If still no reliable signal, set context as greenfield candidate.

### Step 2: Design System

Scan framework-agnostic design signals across web + native:

- CSS variables/tokens (`--primary`, `--radius`, semantic scales)
- `tailwind.config.*`, theme files (`theme.ts`, `theme.js`, `styles.xml`, asset catalogs)
- token sources (`tokens.json`, Style Dictionary outputs)
- component system indicators (`components.json`, MUI/Chakra/Ant/Vuetify deps, SwiftUI/Compose theme artifacts)
- font signals (`@import` from font providers, `@font-face`, native font registration)

Outcome: detect whether an existing design system already exists and should be preserved.

### Step 3: Routes/Pages

Detect information architecture and output intent from page/route structure:

- app routers and page roots: `/app`, `/pages`, `/src/routes`, `/templates`, `/views`
- backend route declarations: `urls.py`, route files in server frameworks
- static entry patterns: `*.html` page sets
- route names as intent hints (e.g., `/dashboard`, `/pricing`, `/features`, `/blog`)

Outcome: infer whether this is Landing/App/Dashboard/Doc/Art-oriented work.

### Step 4: Charts

Detect charting dependencies and in-repo chart components:

- JS/TS: Recharts, Chart.js, ECharts, Nivo, ApexCharts, D3, Plotly, Vega/Vega-Lite
- Python: matplotlib, seaborn, plotly, bokeh, altair
- JVM/.NET/native: MPAndroidChart, Charts (iOS), JavaFX chart, etc.

Outcome: chart axis is activated only when Output Type is Dashboard.

## Section 2: 4-Axis Classification Rules

Each axis uses signal-first mapping with deterministic priority.

### Axis 1: Output Type (What)

Signals are taken from user request + route/page structure.

| Signal | Classification |
|---|---|
| User explicitly asks landing/homepage/product marketing | Landing (match `landing.csv` 34 pattern names/keywords) |
| User asks app/application/tool/workspace | App |
| User asks dashboard/admin/analytics/reporting | Dashboard |
| User asks poster/visual/campaign/art/canvas | Art |
| User asks docs/help/guide/knowledge base | Doc |
| Route signals include `/pricing`, `/features`, `/compare`, `/waitlist` | Landing |
| Route signals include `/dashboard`, `/analytics`, `/admin` | Dashboard |
| Route signals include `/docs`, `/guide`, `/kb`, `/wiki` | Doc |
| No explicit/user/route signal | App (default for existing product repos), else Greenfield Fallback |

Landing sub-pattern selection: fuzzy-match user/page keywords against `landing.csv` `Pattern Name` + `Keywords`; return best-scoring pattern.

### Axis 2: Industry (Who)

Signals are taken from README/manifest description/dependency names/API naming.

| Signal | Classification |
|---|---|
| `README.md` description, manifest description, package keywords | Fuzzy match against `ui-reasoning.csv` `UI_Category` (160 categories) |
| Domain-coded dependencies/endpoints (`/api/patients`, `stripe`, `shop`, `clinic`) | Increase category score for matching industries |
| User explicitly names industry | Direct match to closest `UI_Category` |
| Low-confidence match | Existing project -> `General`; no project signals -> Greenfield Fallback question |

Matching policy:

- tokenize + normalize (lowercase, punctuation-strip, singularize basic plurals)
- weighted scoring by source: user request > README/description > dependency clues > endpoint naming
- choose top category when confidence passes threshold; otherwise fallback rule above

### Axis 3: Style (How)

Signals are taken from existing CSS/theme/component library + user request.

| Signal | Classification |
|---|---|
| Existing design tokens/variables/theme/component system detected | **기본값: 보존.** 단, 사용자가 "redesign", "새로", "바꿔", "다르게" 등 명시적 재설계를 요청하면 극단적 방향 선택으로 전환. |
| User explicitly requests style | Direct match against `styles.csv` style categories (67 styles) |
| No user style + industry matched | Use `ui-reasoning.csv` `Style_Priority` as auto-recommendation |
| Neither existing style nor reliable industry | Recommend safe baseline (`Minimalism & Swiss Style` + accessibility guardrails) |

Decision policy:

1. **보존 우선**: 일관된 기존 디자인이 감지되면 보존이 기본값.
2. **명시적 재설계 요청 시 전환**: 사용자가 "redesign", "새로", "바꿔", "다르게" 등으로 재설계를 요청하면 → SKILL.md Build Mode의 "Bold direction" 절차를 따름 (극단적 미학 방향 선택).
3. **그린필드**: 기존 디자인이 없으면 자동으로 "Bold direction" 절차 진입.
4. Auto recommendation uses industry `Style_Priority` and filters by technical constraints (performance/accessibility/mobile flags from `styles.csv`).

### Axis 4: Charts (When Dashboard)

Apply only if Axis 1 = Dashboard.

| Signal | Classification |
|---|---|
| Existing chart dependency/component detected | Keep same library + infer available chart types |
| User specifies chart intent (`trend`, `comparison`, `distribution`, `composition`) | Map to chart type family |
| Dashboard without explicit chart intent | Recommend default chart set by industry + data shape |
| Non-Dashboard output | Chart axis disabled (`N/A`) |

Chart type mapping uses 25 chart types: line, area, bar, stacked bar, pie, donut, scatter, bubble, heatmap, treemap, radar, funnel, gauge, candlestick, box plot, histogram, violin, waterfall, sankey, network, map/choropleth, timeline, sparkline, table+mini chart, mixed combo.
(Note: chart patterns are referenced from `data/ui-reasoning.csv` industry recommendations, not a separate charts file.)

## Section 3: Detection Output Format

Use this exact confirmation box:

```text
감지 결과:
┌───────────────────────────────────────────────┐
│ 모드: 🔨 Build                                │
│ 유형: Landing Page (Hero + Features 패턴)      │
│ 산업: {matched industry} ({signal source})     │
│ 스타일: {recommended style} ({basis})          │
│ 기존 디자인: {preserve/replace decision}       │
│ 폰트: {current} → {recommended} 교체 제안      │
│ 팔레트: {4 hex colors}                        │
└───────────────────────────────────────────────┘
이대로 진행할까요?
```

## Section 4: Override Rules

- If user replies with agreement (`ㅇㅇ`, `좋아`, `진행`), proceed using detected context as-is.
- If user overrides one axis, update that axis first, then recompute dependent axes only.
- Dependency rules:
  - Output Type change can enable/disable Charts axis.
  - Industry change auto-recalculates Style recommendation + palette.
  - Style change updates typography/palette/motion, but does not change Industry unless explicitly requested.

## Section 5: Greenfield Fallback

Trigger only when all scan signals are absent.

Ask exactly one question:

`어떤 분야의 프로젝트인가요?`

After answer:

1. match user response to `ui-reasoning.csv` `UI_Category`
2. auto-recommend remaining 3 axes:
   - Output Type from request intent (default Landing for marketing intent, App otherwise)
   - Style from `Style_Priority`
   - Charts as `N/A` unless Dashboard intent appears

## Section 6: Design Thinking Integration

Immediately after context detection, generate both models automatically.

### OpenAI 3 theses auto-generation

- Visual thesis: derived from Axis 2 (Industry) + Axis 3 (Style) + preserve/replace decision
- Content plan: derived from Axis 1 Output Type (for Landing, include detected `landing.csv` pattern section order)
- Interaction thesis: derived from style motion profile + chart interactivity requirement (if Dashboard)

### Anthropic 4-step Design Thinking auto-resolution

- Purpose: inferred from Output Type + Industry
- Tone: inferred from Style Category + typography/color mood
- Constraints: inferred from stack/framework/performance/accessibility signals
- Differentiation: generated as one memorable element tied to industry + selected pattern/style
