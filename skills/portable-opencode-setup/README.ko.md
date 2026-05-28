---
name: portable-opencode-setup
description: 플러그인, npm 의존성, MCP, AAI 앱, 프로바이더 모델, 에이전트/카테고리 라우팅, 팀 모드, 백업을 포함한 커스텀 opencode/oh-my-openagent 설정을 모든 기기에서 재현합니다. 비밀 정보를 포함하지 않습니다.
---

# Portable OpenCode Setup

커스텀 opencode 및 oh-my-openagent 설정을 모든 기기에서 재현합니다.

## 사용 시기

- 새로운 개발 기기를 설정할 때.
- 다른 사용자와 이 설정을 공유할 때.
- 클린 설치 후 복구할 때.

## 사전 요구 사항

- opencode CLI가 설치되어 있어야 합니다.
- Node.js 및 npm이 사용 가능해야 합니다.
- oh-my-openagent 플러그인이 설치되어 있어야 합니다.

## 1단계: 플러그인 설치

`setup-manifest.json`의 `plugins` 배열에 있는 모든 opencode 플러그인을 설치합니다.

```bash
# 예시 (매니페스트의 모든 항목 설치)
opencode plugin add opencode-claude-auth
opencode plugin add opencode-antigravity-auth
opencode plugin add @datadog/opencode-plugin
opencode plugin add oh-my-openagent
opencode plugin add oh-my-openagent/tui
```

## 2단계: npm 의존성 설치

`setup-manifest.json`의 `npm_packages` 배열에 있는 모든 npm 패키지를 전역 또는 프로젝트 로컬로 설치합니다.

```bash
# 예시 (매니페스트의 모든 항목 설치)
npm install -g @ex-machina/opencode-anthropic-auth
npm install -g @opencode-ai/plugin
npm install -g oh-my-opencode
```

## 3단계: MCP 설정

### 상시 연결 MCP
`setup-manifest.json`의 `mcps.always_on`에 있는 모든 MCP를 opencode 설정에서 활성화합니다.

### 등록됨-비활성화 MCP
`setup-manifest.json`의 `mcps.registered_disabled`에 있는 모든 MCP를 등록하되, 기본적으로 비활성화 상태로 둡니다.

## 4단계: AAI 앱 설정

### 프리셋 앱 (자동 등록)
`setup-manifest.json`의 `aai_apps.preset`에 있는 모든 프리셋 앱이 사용 가능한지 확인합니다.

### 온디맨드 앱
`setup-manifest.json`의 `aai_apps.on_demand`에 있는 모든 온디맨드 앱을 등록합니다.

## 5단계: 프로바이더 모델 설정

`provider.google` 아래에 이 환경에서 사용하는 **10개의 Antigravity/Gemini 커스텀 모델**을 추가합니다. 정확한 모델 식별자는 로컬 `available-models.json` 또는 업스트림 문서를 참조하세요.

## 6단계: Oh My OpenAgent 설정

이 리포지토리의 `oh-my-openagent.json` (`skills/omo-model-config/oh-my-openagent.json`)을 소스 오브 트루스로 사용합니다.

### 에이전트
다음 에이전트의 `model`, `variant`, `fallback_models`가 소스 파일에 정확히 정의된 대로 설정되어 있는지 확인합니다:

- `sisyphus`
- `hephaestus`
- `oracle`
- `librarian`
- `explore`
- `multimodal-looker`
- `prometheus`
- `metis`
- `momus`
- `atlas`
- `sisyphus-junior`

### 카테고리
다음 카테고리의 `model`, `variant`, `fallback_models`가 정확히 정의된 대로 설정되어 있는지 확인합니다:

- `visual-engineering`
- `ultrabrain`
- `deep`
- `artistry`
- `quick`
- `unspecified-low`
- `unspecified-high`
- `writing`

### 전역 설정
다음 최상위 키를 설정합니다:

| 키 | 값 |
|-----|-------|
| `team_mode.enabled` | `true` |
| `team_mode.max_parallel` | `3` |
| `team_mode.max_total` | `5` |
| `team_mode.timeout_minutes` | `60` |
| `team_mode.visualization` | `tmux` |
| `runtime_fallback` | `true` |
| `disabled_hooks` | `["no-sisyphus-gpt"]` |

## 7단계: 인증 상태

`antigravity-accounts.json` 또는 기타 인증 토큰 파일을 복사하지 **마세요**. 새 기기에서 antigravity 로그인 흐름을 실행하여 인증 상태를 다시 생성합니다:

```bash
opencode auth antigravity
```

`antigravity-accounts.json`이 예상 설정 디렉터리에 생성되었는지 확인합니다.

## 8단계: 백업

이 리포지토리에 opencode 또는 oh-my-openagent 설정의 백업 파일이 존재하는 경우, 위 단계를 모두 완료한 후 새 기기의 설정 디렉터리로 복사합니다. 백업은 최종 복원 계층으로 처리하며, 주 설정 방법은 아닙니다.

## 검증 체크리스트

- [ ] 1단계의 모든 플러그인이 설치되었습니다.
- [ ] 2단계의 모든 npm 패키지가 설치되었습니다.
- [ ] 상시 연결 MCP가 연결되었습니다.
- [ ] 등록됨-비활성화 MCP가 설정에 표시되지만 비활성화되어 있습니다.
- [ ] AAI 프리셋 및 온디맨드 앱이 나엵니다.
- [ ] `provider.google`에 10개의 커스텀 모델이 포함되어 있습니다.
- [ ] `oh-my-openagent.json`이 이 리포지토리의 소스 파일과 일치합니다.
- [ ] 새 기기에서 새 로그인 후 `antigravity-accounts.json`이 존재합니다.
- [ ] 해당되는 경우 백업이 복사되었습니다.

## 제약 사항

- **비밀 정보 없음.** 이 스킬이나 커밋된 파일에 `antigravity-accounts.json`, API 키, 토큰, 또는 자격 증명을 절대 포함하지 마세요.
- **읽기 전용 소스 파일.** 이 리포지토리의 JSON 파일(`oh-my-openagent.json`, `available-models.json`)은 소스 오브 트루스입니다. 설정 재현 중에 이 파일들을 수정하지 마세요.
- **기기별 경로.** 파일을 복사할 때는 새 기기의 실제 설정 디렉터리 경로를 사용하세요.
