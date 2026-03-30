# Theme Presets (🎭 Theme Mode)

> **폰트 적용 범위**: 이 프리셋들은 PDF, 슬라이드, 보고서 등 **오프라인/정적 산출물**용으로 설계되어,
> 별도 설치 없이 사용 가능한 오픈소스 시스템 폰트(DejaVu, FreeSans)를 사용합니다.
>
> **🔨 Build Mode에서 웹 UI에 적용할 때는** 반드시 `data/typography.csv`의 웹 폰트 페어링으로 교체하세요.
> 공유 레이어의 "NEVER use system fonts" 규칙은 Build/Art Mode에 적용됩니다.

## Ocean Depths
**Best For**: Corporate presentations, financial reports, professional consulting decks, trust-building content.
| Role | Color | Hex |
|------|-------|-----|
| Primary | Deep Navy | `#1a2332` |
| Accent | Teal | `#2d8b8b` |
| Secondary | Seafoam | `#a8dadc` |
| Background | Cream | `#f1faee` |
**Headers**: DejaVu Sans Bold | **Body**: DejaVu Sans

## Sunset Boulevard
**Best For**: Creative pitches, marketing presentations, lifestyle brands, event promotions, inspirational content.
| Role | Color | Hex |
|------|-------|-----|
| Primary | Burnt Orange | `#e76f51` |
| Accent | Coral | `#f4a261` |
| Secondary | Warm Sand | `#e9c46a` |
| Background | Deep Purple | `#264653` |
**Headers**: DejaVu Serif Bold | **Body**: DejaVu Sans

## Forest Canopy
**Best For**: Environmental presentations, sustainability reports, outdoor brands, wellness content, organic products.
| Role | Color | Hex |
|------|-------|-----|
| Primary | Forest Green | `#2d4a2b` |
| Accent | Sage | `#7d8471` |
| Secondary | Olive | `#a4ac86` |
| Background | Ivory | `#faf9f6` |
**Headers**: FreeSerif Bold | **Body**: FreeSans

## Modern Minimalist
**Best For**: Tech presentations, architecture portfolios, design showcases, modern business proposals, data visualization.
| Role | Color | Hex |
|------|-------|-----|
| Primary | Charcoal | `#36454f` |
| Accent | Slate Gray | `#708090` |
| Secondary | Light Gray | `#d3d3d3` |
| Background | White | `#ffffff` |
**Headers**: DejaVu Sans Bold | **Body**: DejaVu Sans

## Golden Hour
**Best For**: Restaurant presentations, hospitality brands, fall campaigns, cozy lifestyle content, artisan products.
| Role | Color | Hex |
|------|-------|-----|
| Primary | Mustard Yellow | `#f4a900` |
| Accent | Terracotta | `#c1666b` |
| Secondary | Warm Beige | `#d4b896` |
| Background | Chocolate Brown | `#4a403a` |
**Headers**: FreeSans Bold | **Body**: FreeSans

## Arctic Frost
**Best For**: Healthcare presentations, technology solutions, winter sports, clean tech, pharmaceutical content.
| Role | Color | Hex |
|------|-------|-----|
| Primary | Ice Blue | `#d4e4f7` |
| Accent | Steel Blue | `#4a6fa5` |
| Secondary | Silver | `#c0c0c0` |
| Background | Crisp White | `#fafafa` |
**Headers**: DejaVu Sans Bold | **Body**: DejaVu Sans

## Desert Rose
**Best For**: Fashion presentations, beauty brands, wedding planning, interior design, boutique businesses.
| Role | Color | Hex |
|------|-------|-----|
| Primary | Dusty Rose | `#d4a5a5` |
| Accent | Clay | `#b87d6d` |
| Secondary | Sand | `#e8d5c4` |
| Background | Deep Burgundy | `#5d2e46` |
**Headers**: FreeSans Bold | **Body**: FreeSans

## Tech Innovation
**Best For**: Tech startups, software launches, innovation showcases, AI/ML presentations, digital transformation content.
| Role | Color | Hex |
|------|-------|-----|
| Primary | Electric Blue | `#0066ff` |
| Accent | Neon Cyan | `#00ffff` |
| Secondary | Dark Gray | `#1e1e1e` |
| Background | White | `#ffffff` |
**Headers**: DejaVu Sans Bold | **Body**: DejaVu Sans

## Botanical Garden
**Best For**: Garden centers, food presentations, farm-to-table content, botanical brands, natural products.
| Role | Color | Hex |
|------|-------|-----|
| Primary | Fern Green | `#4a7c59` |
| Accent | Marigold | `#f9a620` |
| Secondary | Terracotta | `#b7472a` |
| Background | Cream | `#f5f3ed` |
**Headers**: DejaVu Serif Bold | **Body**: DejaVu Sans

## Midnight Galaxy
**Best For**: Entertainment industry, gaming presentations, nightlife venues, luxury brands, creative agencies.
| Role | Color | Hex |
|------|-------|-----|
| Primary | Deep Purple | `#2b1e3e` |
| Accent | Cosmic Blue | `#4a4e8f` |
| Secondary | Lavender | `#a490c2` |
| Background | Silver | `#e6e6fa` |
**Headers**: FreeSans Bold | **Body**: FreeSans

## Custom Theme Creation

When a user description does not match an existing preset, generate a new theme using this process:
1. Extract intent: audience, emotional tone, brand personality, and context (e.g., investor pitch vs creative campaign).
2. Define visual direction: choose one dominant mood and map it to a four-color palette with clear role separation (Primary, Accent, Secondary, Background).
3. Pick typography pairing: select a header font with character and a body font optimized for readability; ensure stylistic harmony.
4. Validate accessibility: verify contrast for text/background combinations and adjust lightness/chroma while preserving mood.
5. Name the theme: use a concise evocative name that reflects palette + type identity.
6. Present in preset format: include Best For guidance, role/color/hex table, and header/body font mapping, then apply consistently across the artifact.
