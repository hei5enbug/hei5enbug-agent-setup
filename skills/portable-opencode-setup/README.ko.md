---
name: portable-opencode-setup
description: 기존 설정을 보존하면서 커스텀 opencode/oh-my-openagent 설정의 누락된 부분만 추가합니다. 플러그인, MCP, AAI 앱, 프로바이더 모델, 에이전트/카테고리 라우팅, 팀 모드, 백업을 포함하며 비밀 정보를 포함하지 않습니다.
---

# Portable OpenCode Setup

기존 설정을 덮어쓰지 않고 커스텀 opencode 및 oh-my-openagent 설정의 누락된 부분만 모든 기기에 추가합니다.

## 사용 시기

- 새로운 개발 기기를 설정할 때.
- 다른 사용자와 이 설정을 공유할 때.
- 클린 설치 후 복구할 때.

## 사전 요구 사항

- opencode CLI가 설치되어 있어야 합니다.
- oh-my-openagent 플러그인이 설치되어 있어야 합니다.

## 추가 전용 정책

- 기존 OpenCode 및 oh-my-openagent 설정은 기본적으로 모두 보존합니다.
- 누락된 플러그인, MCP, AAI 앱, 프로바이더 모델, 에이전트, 카테고리, 설정만 추가합니다.
- 배열과 맵은 중복 제거 방식으로 병합하며, 전체 배열이나 객체를 교체하지 않습니다.
- 기존 에이전트/카테고리의 `model`, `variant`, `fallback_models` 값을 덮어쓰지 않습니다. 이 리포지토리의 소스 파일과 값이 다르면 수동 검토가 필요한 충돌로 보고합니다.
- `team_mode.*`, `runtime_fallback` 같은 스칼라 설정이 이미 있으면 덮어쓰지 않습니다. 누락된 키만 추가합니다.
- 대상 파일을 변경하기 전에 해당 파일만 timestamp가 붙은 백업으로 생성합니다. 설정 중 관련 없는 백업 파일은 복사하지 않습니다.

## 1단계: 플러그인 설치

`setup-manifest.json`의 `plugins` 배열에 있는 opencode 플러그인 중 누락된 것만 설치합니다. 이미 설치된 플러그인은 그대로 둡니다.
TUI 플러그인은 이 portable setup 범위에서 의도적으로 제외합니다.

```bash
# 예시 (매니페스트의 서버 플러그인 항목 설치)
opencode plugin add opencode-claude-auth
opencode plugin add opencode-antigravity-auth
opencode plugin add @datadog/opencode-plugin
opencode plugin add oh-my-openagent
```

## 2단계: MCP 설정

### 상시 연결 MCP
`setup-manifest.json`의 `mcps.always_on`에 있는 MCP 중 누락된 항목만 opencode 설정에서 활성화합니다. 각 항목은 `{ "enabled": true }`만 있는 스텁이 아니라 실제 OpenCode MCP 정의를 포함해야 합니다.
로컬 stdio MCP는 OpenCode의 local MCP 형식을 사용합니다:

```json
{
  "type": "local",
  "command": ["npx", "-y", "package-name"],
  "environment": {},
  "enabled": true
}
```

MCP 항목은 추가 전용으로 병합합니다. 불완전한 항목에는 누락 키만 추가하고, 관련 없는 기존 환경 변수는 보존하며, 아래 AAI Gateway 온디맨드 규칙과 충돌하지 않는 한 기존 MCP 항목을 제거/비활성화/재작성하지 않습니다.

`setup-manifest.json`의 현재 직접 연결 MCP 명령은 다음과 같습니다:

| MCP | 명령 | 참고 |
|-----|------|------|
| `context7` | `npx -y @upstash/context7-mcp` | 문서 검색용입니다. |
| `grep_app` | `npx -y @kenkaiiii/kencode-search` | grep.app 스타일 코드 검색 대체입니다. |
| `aai-gateway` | `npx -y aai-gateway` | 온디맨드 Agent App 게이트웨이입니다. |

이 스킬에서는 별도 `websearch` MCP를 추가하지 않습니다. 사용자가 추가 web-search MCP를 명시적으로 요청하지 않는 한, web search는 대상 기기의 OpenCode 설치가 제공하는 기본 기능으로 취급합니다.

AAI Gateway 앱 MCP(`github-mcp`, `azure-devops-mcp`, `atlassian-rovo`, `postman-mcp`)는 OpenCode MCP로 직접 등록하지 않습니다. 이 앱들은 AAI Gateway의 온디맨드 앱 목록으로만 유지하여, 매 프롬프트마다 도구 스키마가 노출되지 않고 필요할 때만 로드되게 합니다.

## 3단계: AAI 앱 설정

### 프리셋 앱 (자동 등록)
`setup-manifest.json`의 `aai_apps.preset`에 있는 모든 프리셋 앱이 사용 가능한지 확인합니다. 기존 프리셋 앱은 제거하지 않습니다.
프리셋 앱은 discovery check로 취급합니다. 대상 기기에 `opencode`, `codex`, `claude`가 설치되어 있지 않다면 관련 없는 CLI를 자동 설치하지 말고 사용 불가로 보고합니다.

### 온디맨드 앱
`setup-manifest.json`의 `aai_apps.on_demand`에 있는 온디맨드 앱 중 누락된 것만 AAI Gateway를 통해 등록합니다. `aai-gateway`가 연결된 뒤 AAI Gateway 도구(`search:discover`, `mcp:import` 등)를 사용해 최신 버전을 검색하고, 설치한 뒤 AAI Gateway에 등록합니다.
특정 기기에서 직접적이고 항상 노출되는 도구 접근이 필요한 경우가 아니라면, 이 앱들을 OpenCode MCP로도 중복 설정하지 마세요.

## 4단계: 프로바이더 모델 설정

`provider.google` 아래에 이 환경에서 사용하는 Antigravity/Gemini 커스텀 모델 중 누락된 것만 추가합니다. 기존 프로바이더 모델, 별칭, 인증 정보, 프로바이더별 설정은 보존합니다. 로컬 allowlist는 `skills/omo-model-config/available-models.json`을 사용하고, 원하는 모델이 이 파일에 없으면 대체 모델을 추측하지 말고 보고합니다.

## 5단계: Oh My OpenAgent 설정

이 리포지토리의 `oh-my-openagent.json` (`skills/omo-model-config/oh-my-openagent.json`)을 누락 항목을 확인하기 위한 참조로 사용합니다. 이 파일은 덮어쓰기 템플릿이 아닙니다.

### 에이전트
다음 에이전트가 존재하는지 확인합니다. 누락된 에이전트는 소스 파일의 전체 정의를 추가합니다. 이미 존재하는 에이전트는 현재 `model`, `variant`, `fallback_models`를 보존하며, 소스 파일과 값이 다르면 덮어쓰지 않고 차이점만 보고합니다:

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
다음 카테고리가 존재하는지 확인합니다. 누락된 카테고리는 소스 파일의 전체 정의를 추가합니다. 이미 존재하는 카테고리는 현재 `model`, `variant`, `fallback_models`를 보존하며, 소스 파일과 값이 다르면 덮어쓰지 않고 차이점만 보고합니다:

- `visual-engineering`
- `ultrabrain`
- `deep`
- `artistry`
- `quick`
- `unspecified-low`
- `unspecified-high`
- `writing`

### 전역 설정
다음 최상위 키가 누락된 경우에만 추가합니다. 기존 값은 보존하고, 값이 다르면 덮어쓰지 않고 차이점만 보고합니다:

| 키 | 값 |
|-----|-------|
| `team_mode.enabled` | `true` |
| `team_mode.max_parallel` | `3` |
| `team_mode.max_total` | `5` |
| `team_mode.timeout_minutes` | `60` |
| `team_mode.visualization` | `tmux` |
| `runtime_fallback` | `true` |
| `disabled_hooks` | `["no-sisyphus-gpt"]` |

## 6단계: 인증 상태

`antigravity-accounts.json` 또는 기타 인증 토큰 파일을 복사하지 **마세요**. 새 기기에서 antigravity 로그인 흐름을 실행하여 인증 상태를 다시 생성합니다:

```bash
opencode auth antigravity
```

`antigravity-accounts.json`이 예상 설정 디렉터리에 생성되었는지 확인합니다.

## 7단계: 백업

대상 파일을 수정하기 전에 해당 파일 옆에 timestamp가 붙은 백업을 만듭니다. `opencode.json`, `oh-my-openagent.json`처럼 이 스킬이 실제로 변경할 파일만 백업하며, 이 리포지토리의 관련 없는 백업 파일을 복사하거나 기존 백업을 덮어쓰지 않습니다.

## 검증 체크리스트

- [ ] 1단계의 모든 플러그인이 설치되었습니다.
- [ ] 상시 연결 MCP에 `type: "local"`, 실행 가능한 `command` 배열이 있으며 `opencode mcp list`에서 연결 상태입니다.
- [ ] AAI 앱 MCP가 OpenCode MCP로 직접 등록되어 있지 않습니다.
- [ ] AAI 프리셋 및 온디맨드 앱이 AAI Gateway에 나열됩니다.
- [ ] `provider.google`에 누락된 커스텀 모델이 추가되었고 기존 프로바이더 설정은 보존되었습니다.
- [ ] 이 리포지토리 기준으로 누락된 에이전트/카테고리/설정이 기존 값을 덮어쓰지 않고 추가되었습니다.
- [ ] 소스와 기존 설정의 차이점은 수동 검토가 필요한 충돌로 보고되었습니다.
- [ ] 새 기기에서 새 로그인 후 `antigravity-accounts.json`이 존재합니다.
- [ ] 해당되는 경우 백업이 복사되었습니다.

## 제약 사항

- **비밀 정보 없음.** 이 스킬이나 커밋된 파일에 `antigravity-accounts.json`, API 키, 토큰, 또는 자격 증명을 절대 포함하지 마세요.
- **읽기 전용 소스 파일.** 이 리포지토리의 JSON 파일(`oh-my-openagent.json`, `available-models.json`)은 소스 오브 트루스입니다. 설정 재현 중에 이 파일들을 수정하지 마세요.
- **기기별 경로.** 파일을 복사할 때는 새 기기의 실제 설정 디렉터리 경로를 사용하세요.
- **암묵적 덮어쓰기 금지.** 사용자가 명시적으로 덮어쓰기 또는 복원을 요청하지 않는 한, 기존 설정은 보강만 하고 교체하지 않습니다.
