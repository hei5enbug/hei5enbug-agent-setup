# Portable OpenCode Setup

> 이 문서는 `SKILL.md`를 한국어로 옮긴 참고 문서입니다. 에이전트가 실행할 때 사용하는
> 기준 문서는 영어 `SKILL.md`입니다. 두 문서의 내용이 다르면 `SKILL.md`를 기준으로 합니다.

기존 시스템의 OpenCode와 oh-my-openagent 설정을 덮어쓰지 않고, 이 커스텀 설정에서 빠진 부분만 어떤 기기에서든 추가합니다.

## 언어 계약

실행 지침은 영어 `SKILL.md`만 사용합니다. `README.ko.md`는 사람을 위한 참고용 한국어 번역이며, 스킬을 실행할 때 읽거나 사용하지 않습니다.

## 사용 시기

- 새 개발 기기를 설정할 때
- 이 설정을 다른 사용자와 공유할 때
- 클린 설치 후 복구할 때

## 사전 요구 사항

- opencode CLI가 설치되어 있어야 합니다.
- oh-my-openagent 플러그인이 설치되어 있어야 합니다.

## 추가 전용 정책

- 기존 OpenCode와 oh-my-openagent 설정은 기본적으로 모두 보존합니다.
- 누락된 플러그인, MCP, AAI 앱, 프로바이더 모델, 에이전트, 카테고리, 설정만 추가합니다.
- 배열과 맵은 중복을 제거하면서 병합하며, 배열이나 객체 전체를 교체하지 않습니다.
- 기존 에이전트나 카테고리의 `model`, `variant`, `fallback_models` 값은 덮어쓰지 않습니다. 최신 upstream `dev` 추천값과 다르면 기존 값을 보존하고 수동 검토가 필요한 충돌로 보고합니다.
- `team_mode.*`나 `runtime_fallback` 같은 스칼라 설정이 이미 있으면 덮어쓰지 않습니다. 누락된 스칼라 키만 추가합니다.
- 유일한 삭제 예외는 대상 `oh-my-openagent.json` 안의 모든 `agents.*.ultrawork` 블록입니다. 이름이 비슷한 키나 다른 파일의 내용은 삭제하지 않습니다.
- 대상 파일을 변경하기 전에 해당 파일만 timestamp가 붙은 백업으로 만듭니다. 설정 과정에서 관련 없는 백업 파일은 복사하지 않습니다.

## 1단계: 플러그인 설치

`setup-manifest.json`의 `plugins` 배열에 있는 opencode 플러그인 중 누락된 것만 설치합니다. 이미 설치된 플러그인은 그대로 둡니다. TUI 플러그인은 이 portable setup의 의도적인 범위 밖입니다.

```bash
# 예시 (매니페스트의 모든 서버 플러그인 설치)
opencode plugin add opencode-claude-auth
opencode plugin add opencode-antigravity-auth
opencode plugin add @datadog/opencode-plugin
opencode plugin add oh-my-openagent
```

## 2단계: MCP 설정

### 상시 연결 MCP

`setup-manifest.json`의 `mcps.always_on`에 있는 MCP 중 누락된 항목을 활성화합니다. 각 항목에는 `{ "enabled": true }`만 있는 스텁이 아니라 실제 OpenCode MCP 정의가 있어야 합니다. 로컬 stdio MCP에는 OpenCode의 로컬 MCP 형식을 사용합니다.

```json
{
  "type": "local",
  "command": ["npx", "-y", "package-name"],
  "environment": {},
  "enabled": true
}
```

MCP 항목은 추가 전용으로 병합합니다. 불완전한 항목에는 누락된 키를 추가하고, 관련 없는 기존 환경 변수는 보존합니다. 아래 AAI Gateway 온디맨드 규칙과 충돌하지 않는 한 기존 MCP 항목을 삭제·비활성화·재작성하지 않습니다.

`setup-manifest.json`에 정의된 현재 직접 연결 MCP 명령은 다음과 같습니다.

| MCP | 명령 | 설명 |
|---|---|---|
| `context7` | `npx -y @upstash/context7-mcp` | 문서 검색 |
| `grep_app` | `npx -y @kenkaiiii/kencode-search` | grep.app 방식의 코드 검색 대체 도구 |
| `aai-gateway` | `npx -y aai-gateway` | 온디맨드 Agent Apps용 게이트웨이 |

이 스킬에서 별도의 `websearch` MCP를 추가하지 않습니다. 사용자가 추가 웹 검색 MCP를 명시적으로 요청하지 않는 한 웹 검색은 대상 기기의 OpenCode 설치가 제공한다고 봅니다.

AAI Gateway 앱 MCP인 `github-mcp`, `azure-devops-mcp`, `atlassian-rovo`, `postman-mcp`를 OpenCode MCP로 직접 등록하지 않습니다. 이 도구들은 필요할 때만 스키마를 불러오도록 AAI Gateway의 온디맨드 앱 목록을 통해서만 사용할 수 있게 합니다.

## 3단계: AAI 앱 설정

### 프리셋 앱 (자동 등록)

`setup-manifest.json`의 `aai_apps.preset`에 있는 모든 프리셋 앱을 사용할 수 있게 합니다. 기존 프리셋 앱은 삭제하지 않습니다. 이는 탐색 확인으로 취급합니다. 대상 기기에 `opencode`, `codex`, `claude`가 설치되어 있지 않으면 관련 없는 CLI를 자동으로 설치하지 말고 사용할 수 없다고 보고합니다.

### 온디맨드 앱

`setup-manifest.json`의 `aai_apps.on_demand`에 있는 온디맨드 앱 중 누락된 것만 AAI Gateway를 통해 등록합니다.
`aai-gateway`가 연결된 뒤 `search:discover`와 `mcp:import` 같은 AAI Gateway 도구를 사용해 최신 버전을 검색하고 설치한 다음 AAI Gateway에 등록합니다. 특정 기기에서 직접 항상 보이는 도구 접근이 필요한 경우가 아니라면 이 앱들을 직접 OpenCode MCP로도 설정하지 않습니다.

## 4단계: 프로바이더 모델 설정

5단계에서 확인한 최신 upstream 모델 경로에 필요한 누락된 Antigravity/Gemini 커스텀 모델만 `provider.google` 아래에 추가합니다. 기존 프로바이더 모델, 별칭, 자격 증명, 프로바이더별 설정은 보존합니다.
대상 기기의 OpenCode 모델 탐색 결과, 설치된 프로바이더 기능, 기존 프로바이더 설정으로 가용 모델 집합을 만들고, 대상 기기에서 확인한 정보만 사용합니다.

upstream에서 추천했지만 대상 프로바이더가 확인하지 않은 모델은 대체 모델을 추측하지 말고 사용할 수 없다고 보고합니다. 탐색에 프로바이더 인증이 필요하면 로그인 뒤로 이 단계를 미룹니다. 최신 upstream 소스를 가져올 수 없으면 이 단계를 건너뛰고, 로컬이나 캐시된 모델 추천 스냅샷을 대체 자료로 사용하지 않습니다.

## 5단계: Oh My OpenAgent 설정

매번 실행할 때 `code-yeongyu/oh-my-openagent`의 현재 GitHub `dev` 브랜치에서 다음 파일을 가져옵니다.

- `packages/model-core/src/agent-model-requirements.ts`
- `packages/model-core/src/category-model-requirements.ts`
- `packages/model-core/src/model-requirement-types.ts`
- `src/config/schema/fallback-models.ts`
- `src/config/schema/agent-overrides.ts`
- `src/config/schema/categories.ts`

최신 TypeScript 코드가 모델 추천과 모델 관련 항목 형태의 유일한 기준입니다. 체크인된 모델 라우팅 예시, 캐시, 이전 실행 결과, 생성된 출력, 설명 문서로 대체하지 않습니다.
최신 소스를 가져올 수 없으면 프로바이더 모델이나 에이전트·카테고리 모델 라우팅을 추가하지 않고, 독립적인 설정 단계만 계속 수행하며 `agents.*.ultrawork`를 삭제한 뒤 모델 작업을 보류했다고 보고합니다.

### 결정적 모델 매핑

누락된 항목과 모든 비교에 같은 규칙을 적용합니다.

1. 현재 TypeScript 코드가 정의한 최신 upstream 관문 플래그를 정확히 평가합니다. 대상 기기에서 관문을 평가할 수 없으면 해당 항목을 보류하고 이유를 보고합니다.
2. 최신 `fallbackChain` 순서를 보존합니다. 대상 기기의 프로바이더 탐색 결과나 기존 설정이 가용성을 확인한 모델만 남깁니다. 최신 체인에 없는 모델을 만들거나 대체하지 않습니다.
3. 실행 가능한 체인의 첫 항목을 `model`로 사용하고, 항목에 `variant`가 있으면 형제 `variant` 필드에 복사합니다.
4. 남은 실행 가능한 항목은 원래 순서대로 `fallback_models`에 직렬화합니다. variant가 없으면 문자열을 사용합니다. 있으면 `{ "model": "...", "variant": "..." }`를 사용합니다.
5. 실행 가능한 항목이 하나도 남지 않으면 누락된 에이전트나 카테고리를 만들지 않고 보류했다고 보고합니다.
6. 이렇게 계산한 결과는 누락된 항목을 추가하거나 기존 항목과 비교할 때만 사용합니다. 기존 항목의 모델 필드는 절대 덮어쓰지 않습니다.

### 에이전트

최신 `AGENT_MODEL_REQUIREMENTS`에 정의된 에이전트 이름을 열거합니다. 누락된 에이전트에는 대상 기기의 가용성을 확인한 뒤 최신 추천값의 `model`, 선택적 `variant`, `fallback_models`만 추가합니다. 기존 에이전트의 모델 필드는 보존하고 최신 추천과 다르면 덮어쓰지 말고 차이를 보고합니다.

### 카테고리

최신 `CATEGORY_MODEL_REQUIREMENTS`에 정의된 카테고리 이름을 열거합니다. 누락된 카테고리에는 대상 기기의 가용성을 확인한 뒤 최신 추천값의 `model`, 선택적 `variant`, `fallback_models`만 추가합니다. 기존 카테고리의 모델 필드는 보존하고 최신 추천과 다르면 덮어쓰지 말고 차이를 보고합니다.

### 오래된 Ultrawork 설정 정리

대상 `oh-my-openagent.json` 안에 있는 모든 `agents.*.ultrawork` 블록을 삭제합니다. 모델 값을 보존하는 에이전트의 블록도 포함합니다. 다른 키를 삭제하거나 다른 파일을 변경하지 않습니다.

### 전역 설정

다음 최상위 키가 없을 때만 추가합니다. 기존 값은 보존하고 차이가 있으면 덮어쓰지 말고 보고합니다.

| 키 | 값 |
|---|---|
| `team_mode.enabled` | `true` |
| `team_mode.max_parallel` | `3` |
| `team_mode.max_total` | `5` |
| `team_mode.timeout_minutes` | `60` |
| `team_mode.visualization` | `tmux` |
| `runtime_fallback` | `true` |
| `disabled_hooks` | `["no-sisyphus-gpt"]` |

## 6단계: 인증 상태

`antigravity-accounts.json`이나 다른 인증 토큰 파일을 복사하지 않습니다. 새 기기에서 Antigravity 로그인 흐름을 실행해 인증 상태를 다시 만듭니다.

```bash
opencode auth antigravity
```

예상 설정 디렉터리에 `antigravity-accounts.json`이 생성되었는지 확인합니다. 인증 때문에 모델 탐색을 보류했다면 로그인 후 4단계와 5단계를 다시 시도합니다.

## 7단계: 백업

대상 파일을 수정하기 전에 해당 파일 옆에 timestamp가 붙은 백업을 만듭니다. 이 스킬이 변경할 `opencode.json`, `oh-my-openagent.json` 같은 파일만 백업하며, 이 저장소의 관련 없는 백업 파일을 복사하거나 기존 백업을 덮어쓰지 않습니다.

## 검증 체크리스트

- [ ] 1단계의 모든 플러그인이 설치되어 있습니다.
- [ ] 상시 연결 MCP에 `type: "local"`, 실행 가능한 `command` 배열이 있고 `opencode mcp list`에서 연결되어 있습니다.
- [ ] AAI 앱 MCP가 OpenCode MCP로 직접 등록되지 않았습니다.
- [ ] AAI 프리셋 앱과 온디맨드 앱이 AAI Gateway에 나열되어 있습니다.
- [ ] `provider.google`에 기존 프로바이더 설정을 보존한 채 누락된 커스텀 모델이 들어 있습니다.
- [ ] 모델 가용성을 대상 기기의 탐색 결과와 설정에서만 확인했습니다.
- [ ] 추가한 모든 모델 경로가 최신 `fallbackChain` 순서와 결정적 직렬화 규칙을 따릅니다.
- [ ] 최신 upstream에 있는 누락된 에이전트·카테고리와 설정을 기존 값을 덮어쓰지 않고 추가했습니다.
- [ ] 최신 upstream과 다른 기존 모델 값은 보존하고 수동 검토 충돌로 보고했습니다.
- [ ] 대상 `oh-my-openagent.json`에 `agents.*.ultrawork` 블록이 없고 관련 없는 키를 삭제하지 않았습니다.
- [ ] 보고서에 모델 추천에 사용한 정확한 upstream 브랜치와 가져온 시각이 있습니다.
- [ ] 새 기기에서 새 로그인 후 `antigravity-accounts.json`이 존재합니다.
- [ ] 해당하는 경우 백업을 복사했습니다.

## 제약 사항

- **비밀 정보 금지.** 이 스킬이나 커밋되는 파일에 `antigravity-accounts.json`, API 키, 토큰, 자격 증명을 넣지 않습니다.
- **저장소 입력은 읽기 전용.** 설정 재현 중에는 저장소 입력을 수정하지 않습니다. 여기에는 `setup-manifest.json`과 체크인된 `oh-my-openagent.json`이 포함됩니다. 매니페스트는 모델이 아닌 설정 항목을 정의합니다.
  모델 추천은 최신 upstream `dev` 코드만 정의하며, 로컬 모델 가용성은 대상 기기가 정의합니다.
- **기기별 경로.** 파일을 복사할 때 새 기기의 실제 설정 디렉터리 경로를 사용합니다.
- **암묵적 덮어쓰기 금지.** 사용자가 덮어쓰기나 복원 동작을 명시적으로 요청하지 않는 한 기존 설정은 추가할 수만 있고 교체할 수 없습니다.
