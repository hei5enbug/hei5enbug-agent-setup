# Portable OpenCode Setup

> 이 문서는 한국어 사용자가 내용을 확인하기 위한 참고 번역입니다. 에이전트가 스킬을
> 실행할 때 읽거나 사용하는 지침이 아닙니다. 유일한 실행 지침은 `SKILL.md`입니다.

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
- 기존 에이전트/카테고리의 `model`, `variant`, `fallback_models` 값을 덮어쓰지 않습니다. 인터넷에서 확인한 최신 upstream `dev` 추천값과 다르면 기존 값을 보존하고 수동 검토가 필요한 충돌로 보고합니다.
- `team_mode.*`, `runtime_fallback` 같은 스칼라 설정이 이미 있으면 덮어쓰지 않습니다. 누락된 키만 추가합니다.
- 유일한 삭제 예외는 대상 `oh-my-openagent.json` 안의 모든 `agents.*.ultrawork` 블록입니다. 비슷한 이름의 키나 다른 파일의 내용은 지우지 않습니다.
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

`provider.google` 아래에는 5단계에서 인터넷의 최신 upstream 모델 경로를 확인한 뒤 필요한 Antigravity/Gemini 커스텀 모델 중 누락된 것만 추가합니다. 기존 프로바이더 모델, 별칭, 인증 정보, 프로바이더별 설정은 보존합니다. 사용할 수 있는 모델은 대상 기기의 OpenCode 모델 검색 결과, 설치된 프로바이더 기능과 기존 프로바이더 설정으로만 확인합니다. 대상 프로바이더가 확인하지 못한 upstream 추천 모델은 대체 모델을 추측하지 말고 보고합니다. 모델 검색에 로그인이 필요하면 6단계 뒤로 미루고 다시 시도합니다. 최신 upstream 소스를 가져오지 못하면 이 단계를 건너뛰며, 로컬 파일이나 캐시를 모델 추천의 대신으로 사용하지 않습니다.

## 5단계: Oh My OpenAgent 설정

실행할 때마다 `code-yeongyu/oh-my-openagent`의 현재 GitHub `dev` 브랜치에서 다음 파일을 가져옵니다:

- `packages/model-core/src/agent-model-requirements.ts`
- `packages/model-core/src/category-model-requirements.ts`
- `packages/model-core/src/model-requirement-types.ts`
- `src/config/schema/fallback-models.ts`
- `src/config/schema/agent-overrides.ts`
- `src/config/schema/categories.ts`

인터넷에서 가져온 최신 TypeScript 코드만 모델 추천과 모델 관련 항목 형식의 기준으로 사용합니다. 저장된 모델 경로 예시, 캐시, 이전 실행 결과, 생성된 보고서나 설명 문서를 대신 사용하지 않습니다. 최신 소스를 가져오지 못하면 프로바이더 모델과 에이전트/카테고리 모델 경로를 추가하지 않습니다. 다른 설정 단계와 `agents.*.ultrawork` 제거만 계속하고, 미룬 모델 작업을 보고합니다.

### 모델 경로를 항상 같은 방식으로 바꾸는 규칙

누락 항목 추가와 기존 값 비교에 다음 규칙을 똑같이 사용합니다:

1. 최신 TypeScript 코드에 있는 gate 조건을 그대로 확인합니다. 대상 기기에서 조건을 확인할 수 없으면 그 항목을 추가하지 않고 이유를 보고합니다.
2. 최신 `fallbackChain` 순서를 지키고, 대상 기기의 프로바이더 검색이나 기존 설정에서 사용할 수 있다고 확인된 모델만 남깁니다. 최신 체인에 없는 모델을 만들거나 대신 넣지 않습니다.
3. 사용할 수 있는 첫 번째 체인 항목을 `model`로 사용하고, 그 항목에 `variant`가 있으면 같은 단계의 `variant`에 넣습니다.
4. 남은 항목은 원래 순서대로 `fallback_models`에 넣습니다. `variant`가 없으면 문자열, 있으면 `{ "model": "...", "variant": "..." }` 형태로 저장합니다.
5. 사용할 수 있는 항목이 하나도 없으면 누락된 에이전트나 카테고리를 만들지 않고, 작업을 미룬 이유를 보고합니다.
6. 이 결과는 누락 항목을 추가하거나 기존 값과 비교할 때만 사용합니다. 기존 모델 값은 절대 덮어쓰지 않습니다.

### 에이전트
최신 `AGENT_MODEL_REQUIREMENTS`에 정의된 에이전트 이름을 모두 확인합니다. 누락된 에이전트에는 대상 기기에서 사용할 수 있다고 확인된 최신 추천값의 `model`, 선택적인 `variant`, `fallback_models`만 추가합니다. 이미 존재하는 에이전트의 모델 값은 보존하며, 최신 추천값과 다르면 덮어쓰지 않고 차이점만 보고합니다.

### 카테고리
최신 `CATEGORY_MODEL_REQUIREMENTS`에 정의된 카테고리 이름을 모두 확인합니다. 누락된 카테고리에는 대상 기기에서 사용할 수 있다고 확인된 최신 추천값의 `model`, 선택적인 `variant`, `fallback_models`만 추가합니다. 이미 존재하는 카테고리의 모델 값은 보존하며, 최신 추천값과 다르면 덮어쓰지 않고 차이점만 보고합니다.

### 오래된 Ultrawork 설정 정리

대상 `oh-my-openagent.json` 안에서 모든 `agents.*.ultrawork` 블록을 제거합니다. 모델 값을 보존하는 에이전트에 있어도 제거합니다. 이 정리를 위해 다른 키를 지우거나 다른 파일을 수정하지 않습니다.

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
로그인이 필요해 모델 검색을 미뤘다면 로그인 뒤 4단계와 5단계를 다시 실행합니다.

## 7단계: 백업

대상 파일을 수정하기 전에 해당 파일 옆에 timestamp가 붙은 백업을 만듭니다. `opencode.json`, `oh-my-openagent.json`처럼 이 스킬이 실제로 변경할 파일만 백업하며, 이 리포지토리의 관련 없는 백업 파일을 복사하거나 기존 백업을 덮어쓰지 않습니다.

## 검증 체크리스트

- [ ] 1단계의 모든 플러그인이 설치되었습니다.
- [ ] 상시 연결 MCP에 `type: "local"`, 실행 가능한 `command` 배열이 있으며 `opencode mcp list`에서 연결 상태입니다.
- [ ] AAI 앱 MCP가 OpenCode MCP로 직접 등록되어 있지 않습니다.
- [ ] AAI 프리셋 및 온디맨드 앱이 AAI Gateway에 나열됩니다.
- [ ] `provider.google`에 누락된 커스텀 모델이 추가되었고 기존 프로바이더 설정은 보존되었습니다.
- [ ] 모델 사용 가능 여부를 대상 기기의 검색 결과와 설정만으로 확인했습니다.
- [ ] 추가한 모델 경로가 최신 `fallbackChain` 순서와 정해진 저장 형식을 따릅니다.
- [ ] 최신 upstream 기준으로 누락된 에이전트/카테고리와 설정이 기존 값을 덮어쓰지 않고 추가되었습니다.
- [ ] 최신 upstream과 다른 기존 모델 값은 보존되었고 수동 검토가 필요한 충돌로 보고되었습니다.
- [ ] 대상 `oh-my-openagent.json`에서 모든 `agents.*.ultrawork` 블록이 없어졌고 관련 없는 키는 지워지지 않았습니다.
- [ ] 보고서에 모델 추천에 사용한 정확한 upstream 브랜치와 확인 시간이 기록되었습니다.
- [ ] 새 기기에서 새 로그인 후 `antigravity-accounts.json`이 존재합니다.
- [ ] 해당되는 경우 백업이 복사되었습니다.

## 제약 사항

- **비밀 정보 없음.** 이 스킬이나 커밋된 파일에 `antigravity-accounts.json`, API 키, 토큰, 또는 자격 증명을 절대 포함하지 마세요.
- **읽기 전용 리포지토리 입력.** 설정 재현 중 `setup-manifest.json`이나 커밋된 `oh-my-openagent.json`을 수정하지 마세요. 매니페스트는 모델 밖의 설정 항목을 정하고, 인터넷의 최신 upstream `dev` 코드는 모델 추천의 기준이며, 대상 기기는 로컬 모델 사용 가능 여부의 기준입니다.
- **기기별 경로.** 파일을 복사할 때는 새 기기의 실제 설정 디렉터리 경로를 사용하세요.
- **암묵적 덮어쓰기 금지.** 사용자가 명시적으로 덮어쓰기 또는 복원을 요청하지 않는 한, 기존 설정은 보강만 하고 교체하지 않습니다.
