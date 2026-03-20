# hei5enbug-agent-setup

[English](./README.md) | **한국어** | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | [Español](./README.es.md) | [Deutsch](./README.de.md) | [Français](./README.fr.md)

## 개요

harness의 에이전트마다 요구하는 능력이 다릅니다. 
에이전트 역할과 태스크 카테고리에 맞춰 `model`, `variant`, 폴백 체인을 최적화 하는 setup을 제공합니다.

## 지원 도구

- [OpenCode](https://github.com/code-yeongyu/oh-my-opencode) ([Oh My OpenCode](https://github.com/code-yeongyu/oh-my-opencode) 플러그인 사용)

## 구조

```
hei5enbug-agent-setup/
├── oh-my-opencode.json       # 스킬이 읽고 수정하는 설정 파일
├── available-models.json     # 스킬이 모델 변경 시 검증에 사용하는 allowlist
└── .opencode/
    └── skills/
        └── omo-model-config/ # 안전한 설정 편집을 위한 커스텀 스킬
            └── SKILL.md
```

## 커스텀 스킬

### omo-model-config

에이전트 모델 할당을 안전하게 편집하는 워크플로우입니다. 다음 규칙을 적용합니다:

- **GitHub 우선 해석** — 업스트림 [oh-my-openagent](https://github.com/code-yeongyu/oh-my-openagent) 문서가 모델-역할 매칭의 주요 기준
- **가용성 게이트** — 모든 모델은 `available-models.json` allowlist에 존재해야 함
- **프로바이더 다양성 게이트** — 각 에이전트의 폴백 체인에 필수 프로바이더가 포함되어야 함
- **편집 범위 제한** — `model`, `variant`, `fallback_models` 필드만 수정하고 나머지는 보존

자세한 내용은 [`.opencode/skills/omo-model-config/SKILL.md`](.opencode/skills/omo-model-config/SKILL.md)를 참고하세요.

## 사용법

지원하는 에이전트 도구에서 프로젝트 루트로 열면 됩니다. 세션 시작 시 설정이 자동으로 로드됩니다.

```bash
cd hei5enbug-agent-setup
opencode
```

### 모델 할당 변경

에이전트 세션에서 `omo-model-config` 스킬을 호출합니다:

```
/omo-model-config
```

또는 에이전트에게 직접 요청할 수 있습니다:

```
"Oracle의 primary model을 claude-opus-4-6으로 변경해줘"
"Librarian fallback에 gpt-5.4 추가해줘"
```

스킬이 allowlist와 대조해 변경 사항을 검증하고, 프로바이더 다양성 규칙을 확인한 뒤 반영합니다.

## 설정

| 키 | 값 | 설명 |
|---|---|---|
| `runtime_fallback` | `true` | 기본 모델 사용 불가 시 자동으로 다음 모델로 폴백 |
| `disabled_hooks` | `["no-sisyphus-gpt"]` | Sisyphus 에이전트에서 GPT 모델 사용 허용 |

## 관련 링크

- [Oh My OpenCode](https://github.com/code-yeongyu/oh-my-opencode) — 설정을 구동하는 플러그인 시스템
- [oh-my-openagent docs](https://github.com/code-yeongyu/oh-my-openagent) — 업스트림 문서 및 모델 매칭 가이드
