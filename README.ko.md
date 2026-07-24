# hei5enbug-agent-setup

[English](./README.md) | **한국어** | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | [Español](./README.es.md) | [Deutsch](./README.de.md) | [Français](./README.fr.md)

AI 코딩 에이전트를 위한 커스텀 스킬 모음입니다. 호스트별로 다시 작성하지 않고 여러 에이전트 호스트에서 그대로 공유할 수 있도록 만들었습니다.

## 개요

각 스킬은 `skills/` 아래 자신만의 폴더를 가지며, 그 안에 지침·참조 문서·스크립트가 함께 들어 있어 독립적으로 동작합니다. 같은 `SKILL.md`가 지원하는 모든 호스트에서 수정 없이 그대로 작동합니다.

## 지원 호스트

- Claude Code
- Codex
- OpenCode ([Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) 플러그인 사용)

## 구조

```
hei5enbug-agent-setup/
└── skills/
    ├── deep-interview/
    ├── flowchart-design/
    ├── humanize-korean/
    ├── omo-model-config/
    ├── portable-opencode-setup/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

각 폴더는 자신만의 `SKILL.md`와 필요한 참조 문서·스크립트를 담고 있습니다. 공유하는 최상위 설정 파일은 없으며, 모든 스킬이 독립적으로 완결되어 있습니다.

## 스킬 목록

| 스킬 | 하는 일 |
|---|---|
| [`deep-interview`](skills/deep-interview/SKILL.md) | 답변마다 요구사항의 모호함 정도를 점수로 측정하는 소크라테스식 인터뷰를 진행하며, 그 점수가 기준값 이하로 내려가기 전에는 실행 단계로 넘어가지 않습니다. |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | SVG, HTML/CSS, Figma, draw.io 등 어떤 도구로 만들어도 하나의 디자인 시스템처럼 보이게 하는 플로우차트 공통 디자인 기준입니다. |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | 내용은 그대로 두고, AI가 쓴 듯한 한글 문장을 사람이 쓴 것처럼 자연스러운 한국어로 다시 씁니다. |
| [`omo-model-config`](skills/omo-model-config/SKILL.md) | 업스트림 allowlist를 기준으로 OpenCode/oh-my-openagent의 모델 라우팅(`model`, `variant`, `fallback_models`)을 안전하게 수정합니다. |
| [`portable-opencode-setup`](skills/portable-opencode-setup/SKILL.md) | 새 기기에 OpenCode/oh-my-openagent 설정 중 빠진 부분만 추가하며, 기존 설정은 건드리지 않습니다. |
| [`skill-builder`](skills/skill-builder/SKILL.md) | 초안 작성 → 테스트 → 검토 → 개선 순환을 통해 에이전트 스킬을 만들고, 검증하고, 패키징합니다. |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | 현재 diff와 최근 커밋 이력을 읽어, 이 저장소의 스타일에 맞는 커밋 메시지 5개를 제안합니다. |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | 개발 설계 문서를 새로 쓰거나 정리할 때 따르는 규칙과, 목차를 단계적으로 좁혀 가는 5단계 절차입니다. |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | 현재 에이전트와 반대쪽 Claude/Codex 세션이 교환 횟수를 제한한 토론을 벌여 쟁점을 드러내고 수렴시킵니다. |

## 알려진 제약

`tiki-taka`는 반대쪽 에이전트 경로를 `~/.claude/skills`와 `~/.codex/skills`로 고정해 두었습니다. 그 외 호스트에서 실행하려면 이 경로를 먼저 수정해야 합니다.

## 관련 링크

- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — `omo-model-config`와 `portable-opencode-setup`이 설정을 다루는 대상 플러그인 시스템
