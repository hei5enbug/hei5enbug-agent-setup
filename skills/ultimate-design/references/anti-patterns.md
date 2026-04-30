# Anti-Patterns & Quality Gates (🎯 Shared — applies to ALL modes)

> **정본 문서**: Hard Rules, Litmus Checks, Reject These Failures의 단일 정본(SSOT).
> 다른 파일에서는 이 문서를 참조만 하고 내용을 복사하지 않습니다.

This reference merges non-negotiable guardrails from OpenAI Frontend Skill and Anthropic Frontend Design guidance.

## AI Slop Prevention

### Forbidden fonts and convergence

- Do not use Inter, Roboto, Arial, system fonts, or Space Grotesk convergence.
  → 이 폰트들은 AI 생성 UI의 가장 흔한 시그니처. 사용 즉시 "AI가 만든 것"으로 인식됨.
- Avoid converging on common font choices across generations.
- Pair a characterful display face with a refined body face.

### Forbidden color direction

- Do not ship cliche purple gradients on white backgrounds.
  → AI 생성 디자인의 가장 흔한 색상 패턴. 즉시 저렴한 인상을 줌.
- Avoid timid, evenly distributed palettes with no dominant color logic.

### Forbidden layout/pattern behavior

- Avoid predictable layouts and component patterns.
  → 동일한 레이아웃 반복은 템플릿 느낌을 주며 브랜드 고유성을 파괴함.
- Avoid cookie-cutter design that lacks context-specific character.
- No design should be the same. Vary between light/dark, different fonts, different aesthetics.
- No generic AI-generated aesthetics.

## Composition Anti-Patterns (즉시 거부)

| 패턴 | 이유 |
|------|------|
| Generic SaaS card grid as the first impression | 카드 그리드는 시각적 위계를 평탄하게 만들어 브랜드 인상이 사라짐 |
| Beautiful image with weak brand presence | 이미지가 아무리 좋아도 브랜드를 전달하지 못하면 누구의 페이지인지 알 수 없음 |
| Strong headline with no clear action | 관심을 끌지만 사용자가 다음에 뭘 해야 하는지 모르면 이탈함 |
| Busy imagery behind text | 배경 노이즈가 텍스트 가독성을 파괴하고 핵심 메시지를 묻음 |
| Sections that repeat the same mood statement | 같은 감정을 반복하면 페이지가 진행감 없이 정체됨 |
| Carousel with no narrative purpose | 목적 없는 캐러셀은 사용자가 스와이프할 이유를 주지 않아 무시됨 |
| App UI made of stacked cards instead of layout | 카드 스택은 정보 밀도를 떨어뜨리고 앱을 대시보드 목업처럼 보이게 함 |

## Hard Rules (정본 — OpenAI frontend-skill 원본 10개)

1. No cards by default.
2. No hero cards by default.
3. No boxed or center-column hero when the brief calls for full bleed.
4. No more than one dominant idea per section.
5. No section should need many tiny UI devices to explain itself.
6. No headline should overpower the brand on branded pages.
7. No filler copy.
8. No split-screen hero unless text sits on a calm, unified side.
9. No more than two typefaces without a clear reason.
10. No more than one accent color unless the product already has a strong system.

## Litmus Checks (정본 — 7개)

Run all seven checks before handoff:

1. Is the brand or product unmistakable in the first screen?
2. Is there one strong visual anchor?
3. Can the page be understood by scanning headlines only?
4. Does each section have one job?
5. Are cards actually necessary?
6. Does motion improve hierarchy or atmosphere?
7. Would the design still feel premium if all decorative shadows were removed?

## Pre-Delivery Checklist (🔨 Build + 🔍 Audit 전용)

> 🎨 Art Mode, 🎭 Theme Mode에서는 해당 항목이 적용되지 않습니다.

- Icons: use SVG icons (Heroicons/Lucide); do not use emoji as UI icons.
- Click targets: every clickable element has `cursor: pointer`.
- Motion timing: hover/micro-interaction transitions are 150–300ms with `ease-out`.
- Contrast: text contrast meets at least 4.5:1 for normal text (WCAG AA).
- Focus: visible keyboard focus states on all interactive elements.
- Reduced motion: include `@media (prefers-reduced-motion: reduce)` handling.
- Responsive QA: verify layouts at 375px, 768px, 1024px, and 1440px widths.

## UX Guidelines Reference

See `../data/ux-guidelines.csv` for 99 curated UX rules.
