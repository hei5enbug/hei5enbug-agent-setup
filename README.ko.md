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
├── .agents/plugins/marketplace.json
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── .codex-plugin/plugin.json
└── skills/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── humanize-korean/
    ├── markdown-to-confluence/
    ├── omo-model-config/
    ├── portable-opencode-setup/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

각 스킬 폴더는 자신만의 `SKILL.md`와 필요한 참조 문서·스크립트를 담고 있습니다.
플러그인
매니페스트는 호스트별 디렉터리에 스킬을 복사하지 않고 같은 `skills/` 디렉터리를 Codex와
Claude Code에 패키징합니다.

## 플러그인 설치

GitHub 저장소에서 스킬 묶음을 한 번 설치합니다.

### Codex

```bash
codex plugin marketplace add hei5enbug/hei5enbug-agent-setup --ref main
codex plugin add hei5enbug-agent-setup@hei5enbug
```

### Claude Code

```bash
claude plugin marketplace add hei5enbug/hei5enbug-agent-setup
claude plugin install hei5enbug-agent-setup@hei5enbug
```

## 플러그인 업데이트

두 플러그인 매니페스트는 같은 의미적 버전을 사용합니다. 릴리스를 배포하기 전에
`.codex-plugin/plugin.json`과 `.claude-plugin/plugin.json`의 버전을 함께 올립니다.

릴리스 배포 후 Codex를 업데이트합니다.

```bash
codex plugin marketplace upgrade hei5enbug
codex plugin add hei5enbug-agent-setup@hei5enbug
```

릴리스 배포 후 Claude Code를 업데이트합니다.

```bash
claude plugin marketplace update hei5enbug
claude plugin update hei5enbug-agent-setup@hei5enbug
```

업데이트한 스킬 버전을 불러오려면 새 Codex 스레드를 시작하거나
Claude Code를 다시 시작합니다.

## 지침 언어

에이전트가 실행하는 스킬 지침은 영어로 작성합니다. 스킬 폴더의 `README.ko.md`는 대응하는
영어 문서의 내용을 동기화해 번역한 비권위 한국어 문서입니다. 한국어 사용자를 위한 참고
문서이며, 에이전트가 스킬을 실행할 때 읽거나 사용하지 않습니다. 영어 실행 파일 안의 한국어는
호출 문구, 예시, 필수 출력 이름, 평가 자료처럼 한국어 자체가 필요한 자료에만 남깁니다.

## 스킬 목록

| 스킬 | 하는 일 |
|---|---|
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | 여러 세션에 걸친 작업을 의사 결정 티켓으로 나누고, 구현 경로가 분명해질 때까지 티켓을 하나씩 해결합니다. |
| [`deep-interview`](skills/deep-interview/SKILL.md) | 답변마다 요구사항의 모호함 정도를 점수로 측정하는 소크라테스식 인터뷰를 진행하며, 그 점수가 기준값 이하로 내려가기 전에는 실행 단계로 넘어가지 않습니다. [한국어 안내](skills/deep-interview/README.ko.md) |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | SVG, HTML/CSS, Figma, draw.io 등 어떤 도구로 만들어도 하나의 디자인 시스템처럼 보이게 하는 플로우차트 공통 디자인 기준입니다. |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | 내용은 그대로 두고, AI가 쓴 듯한 한글 문장을 사람이 쓴 것처럼 자연스러운 한국어로 다시 씁니다. [한국어 안내](skills/humanize-korean/README.ko.md) |
| [`markdown-to-confluence`](skills/markdown-to-confluence/SKILL.md) | 마크다운 문서를 Confluence 페이지로 발행하고, 이후 수정에서도 목차 매크로·본문 이미지·첨부·이미지로 만든 다이어그램이 그대로 유지되게 합니다. |
| [`omo-model-config`](skills/omo-model-config/SKILL.md) | 업스트림 allowlist를 기준으로 OpenCode/oh-my-openagent의 모델 라우팅(`model`, `variant`, `fallback_models`)을 안전하게 수정합니다. |
| [`portable-opencode-setup`](skills/portable-opencode-setup/SKILL.md) | 새 기기에 OpenCode/oh-my-openagent 설정 중 빠진 부분만 추가하며, 기존 설정은 건드리지 않습니다. [한국어 안내](skills/portable-opencode-setup/README.ko.md) |
| [`skill-builder`](skills/skill-builder/SKILL.md) | 초안 작성 → 테스트 → 검토 → 개선 순환을 통해 에이전트 스킬을 만들고, 검증하고, 패키징합니다. |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | 현재 diff와 최근 커밋 이력을 읽어, 이 저장소의 스타일에 맞는 커밋 메시지 5개를 제안합니다. |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | 개발 설계 문서를 새로 쓰거나 정리할 때 따르는 규칙과, 목차를 단계적으로 좁혀 가는 5단계 절차입니다. [한국어 안내](skills/technical-design-writer/README.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | 현재 에이전트와 반대쪽 Claude/Codex 세션이 교환 횟수를 제한한 토론을 벌여 쟁점을 드러내고 수렴시킵니다. [한국어 안내](skills/tiki-taka/README.ko.md) |

## 관련 링크

- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — `omo-model-config`와 `portable-opencode-setup`이 설정을 다루는 대상 플러그인 시스템
