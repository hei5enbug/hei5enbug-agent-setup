---
name: ultimate-design
description: >
  Mode-based UI/UX design intelligence. Auto-detects project context across 4 axes
  (output type · industry · style · charts), then activates the right mode:
  Build (web UI/apps), Art (visual art), Audit (quality review), Theme (styling), Platform (native).
  67 UI styles, 160 industries, 34 landing patterns, 25 chart types.
  Synthesized from Anthropic, OpenAI, Vercel, Google Chrome team official skills.
---

# Ultimate UI/UX Design Skill

Mode-based design intelligence — auto-detects your project, activates the right rules.

---

## Step 0: Context Detection

Before any design work, **scan the project and classify automatically**. See `references/context-detection.md` for full procedure.

### Quick Flow

```
1. Scan project root (ls → recognize manifests heuristically, NOT hardcoded)
2. Read README/manifest → detect industry
3. Read CSS/tokens/config → detect existing design system
4. Read route structure → detect page type
5. Classify across 4 axes → present result → user confirms
```

### 4-Axis Classification

| Axis | Source | Count |
|------|--------|:-----:|
| Output Type | `data/landing.csv` + route detection | Landing(34) · App · Dashboard · Art · Doc |
| Industry | `data/ui-reasoning.csv` | 160 categories |
| Style | `data/styles.csv` | 67 (General 49 + Landing 8 + Dashboard 10) |
| Charts | `data/ui-reasoning.csv` patterns | 25 types (Dashboard only) |

### Detection Output

```
감지 결과:
┌───────────────────────────────────────────────┐
│ 모드: 🔨 Build                                │
│ 유형: Landing Page (Hero + Features 패턴)      │
│ 산업: {matched} ({source})                    │
│ 스타일: {recommended} ({basis})               │
│ 기존 디자인: {preserve/replace}               │
│ 폰트: {current} → {recommended}              │
│ 팔레트: {4 hex colors}                        │
└───────────────────────────────────────────────┘
이대로 진행할까요?
```

- **Existing project**: detect → present → user confirms (0 questions)
- **Greenfield**: ask 1 question only — "어떤 분야의 프로젝트인가요?"
- **User already specified**: skip intake, start immediately

---

## Step 1: Mode Router

| Trigger | Mode | References |
|---------|------|-----------|
| build/create/implement + UI/website/landing/app/dashboard | 🔨 **Build** | `references/composition-layout.md` + `references/motion-imagery-copy.md` |
| poster/art/canvas/visual design/PDF art | 🎨 **Art** | `references/canvas-art.md` |
| audit/review/check/accessibility/performance/lighthouse/SEO | 🔍 **Audit** | `references/web-quality.md` |
| theme/style/apply theme/restyle | 🎭 **Theme** | `themes/presets.md` |
| iOS/SwiftUI/Liquid Glass/UIKit/WidgetKit | 📱 **Platform** | `references/platform-patterns.md` |
| _(always active)_ | 🎯 **Shared** | `references/visual-system.md` + `references/anti-patterns.md` |
| compound ("build + audit") | Chain | Build → complete → Audit |

---

## 🎯 Shared Layer (ALL modes)

These rules apply regardless of which mode is active.

### Typography — Hard Rules

- **NEVER** use Inter, Roboto, Arial, or system font stacks.
- Pair a distinctive **display font** with a refined **body font**.
- **NEVER converge** on common choices (Space Grotesk, etc.) across generations.
- Each design must use different fonts. Vary deliberately.
- Consult `data/typography.csv` for 57 curated pairings.

### Color — Hard Rules

- Use **CSS custom properties** for all colors. Never hardcode hex in components.
- **Dominant color + sharp accent** outperforms timid, evenly-distributed palettes.
- No purple gradients on white backgrounds (AI slop signature).
- Consult `data/colors.csv` for 161 industry-matched palettes.

### Anti-Patterns — Hard Rules (10개), Reject These Failures (7개)

정본: `references/anti-patterns.md` — 여기에 모든 품질 게이트 규칙이 있습니다.
핵심 원칙: No cards by default, no AI slop, no filler copy, one idea per section.
전체 목록은 반드시 정본 문서를 참조하세요.

### Pre-Delivery Checklist (🔨 Build + 🔍 Audit 전용)

정본: `references/anti-patterns.md` — 7항목 체크리스트.
🎨 Art Mode, 🎭 Theme Mode에서는 해당 항목이 적용되지 않습니다.

### Litmus Checks (7개)

정본: `references/anti-patterns.md` — 핸드오프 전 반드시 7개 체크 수행.

---

## 🔨 Build Mode

For web UI, apps, landing pages, dashboards.

### Design Thinking (Before Coding)

1. **Purpose**: What problem? Who uses it?
2. **3 Theses** (write before building):
   - _Visual thesis_: one sentence — mood, material, energy
   - _Content plan_: hero → support → detail → CTA
   - _Interaction thesis_: 2–3 motion ideas that change the feel
3. **Bold direction** (그린필드 또는 명시적 재설계 시): Pick an extreme from the aesthetic spectrum (brutally minimal, maximalist chaos, retro-futuristic, organic/natural, luxury/refined, playful/toy-like, editorial, brutalist, art deco, soft/pastel, industrial...)
   기존 디자인 시스템이 감지된 경우에는 보존이 기본값입니다. `references/context-detection.md`의 축 3 참조.
4. **Differentiation**: What makes this UNFORGETTABLE?

### Composition — See `references/composition-layout.md`

- Start with composition, not components.
- Prefer full-bleed hero. Treat first viewport as a poster.
- Default to cardless layouts.
- **Landing**: Hero → Support → Detail → CTA (34 patterns in `data/landing.csv`)
- **App**: Linear-style restraint (calm hierarchy, strong typography, minimal chrome)
- **Dashboard**: Data density + utility copy + chart patterns

### Motion — See `references/motion-imagery-copy.md`

Ship at least 2–3 intentional motions:
1. Hero entrance sequence
2. Scroll-linked or sticky effect
3. Hover/reveal transition

### Design System Generation

```bash
python3 scripts/search.py "craft brewery" --design-system --stack nextjs
```

Uses `data/ui-reasoning.csv` (160 industries) × `data/styles.csv` (67 styles) × `data/colors.csv` (161 palettes) to auto-generate a complete design system.

---

## 🎨 Art Mode

For visual art, posters, canvas pieces. **NOT for web UI** — use Build Mode for that.

See `references/canvas-art.md` for the full workflow:

1. **Design Philosophy Creation**: Name a movement (1–2 words) → Write philosophy (4–6 paragraphs)
2. **Deduce the Subtle Reference**: Embed a niche conceptual thread — like a jazz musician quoting another song
3. **Canvas Creation**: Express the philosophy visually → output `.pdf` or `.png`
4. **Refinement Pass**: Refine what exists. Don't add — polish.

| | Build Mode | Art Mode |
|---|---|---|
| Text | Functional (headings, body, CTA) | 90% visual, 10% essential text |
| Output | HTML/CSS/JS | PDF/PNG |
| Success | Usability, conversion, accessibility | Museum quality, craftsmanship |

---

## 🔍 Audit Mode

For quality review. Activates immediately — no design intake needed.

See `references/web-quality.md` for 150+ audit patterns.

| Category | Key Checks |
|----------|-----------|
| Core Web Vitals | LCP < 2.5s · INP < 200ms · CLS < 0.1 |
| Performance | Budget: JS < 300KB, Total < 1.5MB |
| Accessibility | WCAG 2.2 · Contrast 4.5:1 · Keyboard nav · ARIA |
| SEO | Meta tags · JSON-LD · Mobile-friendly |
| Lighthouse | Performance ≥ 90 · Accessibility 100 · Best Practices ≥ 95 · SEO ≥ 95 |

---

## 🎭 Theme Mode

For applying themes to existing artifacts (slides, docs, reports, landing pages).

See `themes/presets.md` for 10 pre-built themes:
Ocean Depths · Sunset Boulevard · Forest Canopy · Modern Minimalist · Golden Hour · Arctic Frost · Desert Rose · Tech Innovation · Botanical Garden · Midnight Galaxy

**Workflow**: Show theme showcase → User selects → Apply colors + fonts consistently.
Custom theme creation supported — describe mood/brand → generate.

---

## 📱 Platform Mode

For native platform patterns. See `references/platform-patterns.md`.

Currently covers **iOS 26 Liquid Glass**:
- SwiftUI: `.glassEffect()`, `GlassEffectContainer`, morphing transitions
- UIKit: `UIGlassEffect`, `UIGlassContainerEffect`
- WidgetKit: accented rendering, container backgrounds

---

## Resources

| Resource | Path | Content |
|----------|------|---------|
| Context Detection | `references/context-detection.md` | Project scan logic, 4-axis classification |
| Composition & Layout | `references/composition-layout.md` | Hero rules, landing sequences, app UI |
| Motion, Imagery & Copy | `references/motion-imagery-copy.md` | Animation, imagery narrative, copy strategy |
| Visual System | `references/visual-system.md` | 67 styles, colors, typography |
| Anti-Patterns | `references/anti-patterns.md` | AI slop prevention, quality gates |
| Web Quality | `references/web-quality.md` | Lighthouse, CWV, accessibility, SEO |
| Canvas Art | `references/canvas-art.md` | Design philosophy → visual art |
| Platform Patterns | `references/platform-patterns.md` | iOS Liquid Glass |
| Theme Presets | `themes/presets.md` | 10 themes + custom creation |
| Design System CLI | `scripts/search.py` | Auto-generate design systems |
| Style Data | `data/styles.csv` | 67 UI styles |
| Color Data | `data/colors.csv` | 161 palettes |
| Typography Data | `data/typography.csv` | 57 font pairings |
| Industry Reasoning | `data/ui-reasoning.csv` | 160 industry patterns |
| UX Guidelines | `data/ux-guidelines.csv` | 99 UX rules |
| Landing Patterns | `data/landing.csv` | 34 landing page patterns |

---

## Attribution

This skill synthesizes knowledge from these open-source projects:

| Source | Repository | License |
|--------|-----------|---------|
| UI/UX Pro Max | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | MIT |
| Frontend Design | [anthropics/skills](https://github.com/anthropics/skills) | Apache 2.0 |
| Frontend Skill | [openai/skills](https://github.com/openai/skills) | See repo |
| Web Design Guidelines | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | See repo |
| Canvas Design | [anthropics/skills](https://github.com/anthropics/skills) | Apache 2.0 |
| Theme Factory | [anthropics/skills](https://github.com/anthropics/skills) | Apache 2.0 |
| Liquid Glass Design | [affaan-m/everything-claude-code](https://github.com/affaan-m/everything-claude-code) | MIT |
| Web Quality Skills | [addyosmani/web-quality-skills](https://github.com/addyosmani/web-quality-skills) | MIT |
