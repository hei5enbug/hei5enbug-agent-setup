# OmO 모델 설정기

> 영어 원본: [SKILL.md](SKILL.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

commit으로 고정된 upstream 체인과 `available-models.json`을 사용해 `oh-my-openagent.json`의
`agents.*`, `categories.*` 모델 경로를 provider와 모델 계열에 독립적으로 갱신한다. 빠진 upstream 대상을
추가하고 `agents.*.ultrawork`를 제거하며 관련 없는 설정은 모두 보존한다. 외부 설정 동기화는 확인받은 뒤에만
수행한다. 전체 경로 갱신, 특정 모델·reasoning·fallback 체인 변경과 폐기된 필드 이전에 사용한다.

파일 시스템, 안전한 JSON 편집과 고정된 upstream 소스 접근이 필요하다. 권위 있는 소스를 사용할 수 없으면
아래 규칙에 따라 모델 경로 변경을 보류한다.

영어 `SKILL.md`와 영어 참조 파일만 실행 원본으로 사용한다. 한국어 `.ko.md` 파일은 사람을 위한 번역본이다.

관련 없는 설정을 바꾸지 않고 현재 upstream `dev` 브랜치에서 모든 provider와 모델 계열의 경로를 갱신한다.

## 엄격한 범위

- `agents.*.{models,model,reasoning}`과 `categories.*.{models,model,reasoning}`만 쓴다.
- upstream이 정확한 이름을 정의한 경우에만 빠진 agent나 category를 추가한다. 새 항목에는 `models`만,
  또는 `model`과 선택적인 `reasoning`만 넣을 수 있다.
- 모든 `agents.*.ultrawork` 블록을 제거하고 다른 위치의 비슷한 키는 건드리지 않는다.
- `$schema`, `disabled_*`, `runtime_fallback`, `[opencode]` 같은 호스트 블록을 포함한 다른 키, 값, 순서와
  서식을 모두 보존한다.
- 대상, 필드, provider, 모델 또는 reasoning 수준을 지어내지 않는다.
- 폐기된 경로 필드를 쓰지 않는다. `variant`, `reasoningEffort`는 `reasoning`, `fallback_models`는 `models`로
  바뀌었다. 대상 설정에 폐기된 필드가 있으면 현재 형태로 다시 쓴다. 쓰기 대상에서 폐기 필드를 지우는 것은
  허용된 쓰기이며 보존 규칙 위반이 아니다.
- 대화에서 지정한 경로가 대상 설정이다. 지정하지 않으면 저장소 루트의 `oh-my-openagent.json`을 사용한다.
  사용자가 정확한 동기화를 명시적으로 승인한 뒤에만 외부 설정을 대상으로 삼는다.

## 필수 입력과 권위

편집 전에 이 파일, `available-models.json`과 대상 설정을 읽는다. 기본 provider나 모델 계열을 가정하지 않고
고정된 upstream 소스, `available-models.json`과 명시적인 사용자 정책에서 선택을 도출한다.

매번 [commit 기록](https://github.com/code-yeongyu/oh-my-openagent/commits/dev)에서 현재 `dev` SHA를 한 번
확정하고 [model-core 디렉터리](https://github.com/code-yeongyu/oh-my-openagent/tree/dev/packages/model-core/src)를
목록으로 사용한다. 아래 링크의 `dev`를 전체 SHA로 바꾸고 같은 commit에서 필수 파일을 모두 읽는다.
한 번의 실행에서 서로 다른 commit의 파일을 섞지 않는다.

| 소스 그룹 | 필수 파일 |
|---|---|
| 체인 | [agents](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/agent-model-requirements.ts) |
| 체인 | [categories](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/category-model-requirements.ts) |
| 체인 | [types](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/model-requirement-types.ts) |
| 최신성 계약 | [invariants](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/model-requirements-invariants.test.ts) |
| 런타임 일치 | [availability](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/model-availability.ts) |
| 런타임 일치 | [pipeline](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/model-resolution-pipeline.ts) |
| 런타임 일치 | [provider transforms](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/provider-model-id-transform.ts) |
| fallback 파싱 | [chain parser](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/fallback-chain-from-models.ts) |
| fallback 파싱 | [resolver](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/model-resolver.ts) |
| fallback 파싱 | [known variants](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/reasoning-level.ts) |
| 설정 형태 | [model reference](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-config-core/src/schema/model-ref.ts) |
| 설정 형태 | [reasoning vocabulary](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-config-core/src/schema/reasoning-vocabulary.ts) |
| 설정 형태 | [legacy field normalization](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-config-core/src/schema/fallback-models.ts) |
| 설정 형태 | [agents](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-config-core/src/schema/agent.ts) |
| 설정 형태 | [categories](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-config-core/src/schema/category.ts) |
| 설정 형태 | [host agent overrides](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-opencode/src/config/schema/agent-overrides.ts) |
| 설정 형태 | [host categories](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-opencode/src/config/schema/categories.ts) |
| 설정 형태 | [JSON Schema](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/assets/omo.schema.json) |
| 필드 이전 | [reasoning unification](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-opencode/src/config-migration/reasoning-unification.ts) |
| 필드 이전 | [expected output fixture](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-opencode/src/config-migration/2026-08-reasoning-unification/fixture-expected.json) |

- 조건부 테스트: 고정된 model-core 목록에서 검토 중인 후보와 관련된 provider 또는 모델별 resolution
  테스트를 모두 읽는다. 관련 없는 특수 테스트는 제외한다.

`model-requirements.ts` barrel은 체인 소스가 아니다. 기준 `$schema` 대상은 [`OMO_SCHEMA_URL`](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-opencode/src/config-migration/schema-url.ts)이 게시하는
`assets/omo.schema.json`이다. `assets/oh-my-opencode.schema.json`은 `[opencode]` 호스트 블록만 다루며
`oh-my-openagent.schema.json`은 없다. 설명 문서는 배경 자료일 뿐이다.

### 최신성 조건

1. 모든 필수 파일이 같은 commit을 사용하는지 확인한다.
2. 두 체인 객체가 대상 목록과 retired 식별자를 포함한 invariants 테스트의 모든 부정 조건에 맞는지 확인한다.
3. 불일치하면 확정한 SHA로 모든 파일을 다시 가져온다.
4. 필수 조회가 실패하거나 고정 파일이 계속 충돌하면 모델 경로 설정을 멈추고 보류로 보고한다.
   `agents.*.ultrawork` 정리만 계속할 수 있다.

우선순위는 체인 객체, 런타임 코드와 계약 테스트, 설정 스키마, 설명 문서, 로컬 가정 순이다.
`available-models.json`과 사용자 정책은 upstream 추천이 아니라 제약으로 취급한다.

## 결정 정책

upstream과 로컬 대상을 모두 나열한다. 각 대상의 순서가 있는 `fallbackChain`, variant, provider와
`requiresModel`, `requiresAnyModel`, `requiresProvider` 조건을 기록한다. upstream `fallbackChain[].variant`는
각 단계의 reasoning 수준을 담은 원본 데이터다. 고정된 reasoning 용어로 정규화해 대상의 `reasoning`에 쓰며
원본 키 이름을 복사하지 않는다.

명시적인 사용자 요청은 이름이 지정된 대상과 필드에만 적용한다.

- 요청 모델이 `allowlist`에 없으면 변경하지 않고 `SKIPPED — not in allowlist`로 보고한다.
- allowlist에 있으면 upstream 역할 적합성과 달라도 적용하고 경고한다.
- 요청을 다른 대상이나 모델로 일반화하지 않는다.

그 밖에는 allowlist 후보만 다음 순서로 선택한다.

1. 정확한 upstream 모델
2. 런타임이 인식하는 변환 또는 fuzzy 일치
3. 같은 provider의 버전 인접 대체
4. 체인 순서를 유지한 다음 upstream 후보
5. 대상이 지원하는 provider의 같은 역할 계열
6. 대상이 지원하는 provider의 `tiers`상 같은 등급

버전 인접 대체는 provider, 기본 계보, 기능 분류와 major 버전을 유지해야 한다.
속도 suffix나 minor·patch 버전만 다를 수 있다. 특수 파생 모델이나 다른 크기는 버전 인접이 아니며
런타임이 직접 인식하지 않으면 일반 대체다. 선택한 upstream 단계의 reasoning 수준을 보존한다.

명시적인 사용자 요청이나 `required_providers`가 아니면 대상 체인에 없는 provider를 추가하지 않는다.
정확하지 않은 모델마다 위 순서에서 얻은 대상별 이유가 필요하며 allowlist 포함만으로는 충분하지 않다.

upstream 부분집합을 결정한 뒤 다음을 적용한다.

- upstream 순서를 유지하고 경로 provider마다 fallback을 하나만 둔다.
- 중복이나 다른 대상에서 쓴다는 이유로 모델을 추가하지 않는다.
- primary와 fallback에 있는 provider를 `required_providers` 충족으로 계산한다.
- 필수 provider가 빠지면 그 provider의 allowlist upstream 후보를 우선하고, 없으면 같은 역할이나 등급에서
  가장 가까운 allowlist 모델을 가장 작은 항목 하나만 추가한다. upstream이 금지한 provider는 건너뛰고 알린다.
- 가능한 후보가 없으면 기존 대상을 유지한다. 임의 모델이나 빈 `models` 배열을 쓰지 않는다.
- upstream이 정의한 빠진 대상은 후보가 하나 이상 있을 때 추가한다. 아니면 `addition deferred`와 필요한
  모델을 보고한다.

### Antigravity 로컬 정책

`google/antigravity-X`를 upstream `X`와 wrapper 동등으로 취급한다. 둘 다 allowlist에 있으면 wrapper를 먼저,
원본 형제를 바로 뒤에 둔다. provider 다양성에서는 wrapper를 `google` 경로로 계산한다.
이 정책은 upstream 추천이 아니다.

## 직렬화

- primary를 첫 항목, fallback을 나머지 항목으로 한 순서 있는 `models` 배열 하나를 쓴다.
- reasoning이 없으면 문자열, 필요하면 `{ "model": "...", "reasoning": "..." }`을 사용한다.
  두 형태를 한 배열에 섞을 수 있다.
- upstream 단계나 사용자 요청이 지정한 경우에만 `reasoning`을 쓰고 모델 대체 시 단계 수준을 보존한다.
- 허용 값은 `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `auto`다.
- fallback 없는 primary는 항목 하나인 `models` 또는 선택적인 `reasoning`이 있는 `model`로 쓴다.
  빈 배열은 쓰지 않는다.
- 별도 `reasoning` 필드와 같은 의미인 `provider/model:level` suffix를 쓰지 않는다.
- `temperature`, `max_tokens`, `provider_options` 같은 알 수 없는 설정을 추가하지 않는다.

## 적용과 검증

쓰기 전에 모든 대상을 결정한다. 범위 안 필드만 적용하고 적격한 빠진 대상을 추가하며
`agents.*.ultrawork`를 제거한다.

다음을 모두 검증한다.

- JSON과 스키마 형태가 유효하다.
- 선택한 모든 모델이 allowlist에 있다.
- 모든 모델이 upstream·런타임 일치, 문서화된 가용성 대체, 명시적인 allowlist 요청 또는
  `required_providers` 예외다.
- upstream 조건, provider 범위, 체인 순서와 provider당 fallback 하나를 지킨다.
- 어떤 대상도 임의 또는 새로 비어 있는 체인으로 낮아지지 않는다.
- 쓴 대상에 `variant`, `reasoningEffort`, `fallback_models`가 남지 않는다.
- 추가한 대상이 upstream에 있고 합법적인 경로 필드만 포함한다.
- 모든 `agents.*.ultrawork`가 제거됐다.
- 대상 밖 데이터와 서식이 그대로다.

필수 검사로 대상의 정확한 체인에 없는 모든 provider나 모델을 설명한다.
버전 인접, 역할, 등급, 명시적 요청 또는 필수 provider 이유를 밝히고 이유가 없으면 제거한다.

## 보고

| 항목 | 동작 | Primary | Reasoning | Fallbacks | 이유 |
|---|---|---|---|---|---|

`MODIFIED`, `ADDED`, `UNCHANGED`, `SKIPPED`, `DEFERRED`, `ULTRAWORK_REMOVED`, `FIELD_MIGRATED`만 사용한다.
경로 값은 유지하면서 폐기된 필드에서 옮긴 대상에는 `FIELD_MIGRATED`를 쓴다.

대체 유형, 범위 예외나 공백, 사용자 요청의 upstream 이탈 경고, 보류 대상, upstream과 로컬의 충돌,
추가한 모든 대상을 표시한다. 추가 항목은 이름이 upstream에 있음을 확인하고 전체 체인 이유를 제공한다.
정확 일치, 런타임 fuzzy·변환, 버전 인접, Antigravity wrapper, 일반 가용성 대체와 provider 범위를 구분한다.

## 외부 동기화

보고 뒤 프로젝트 밖의 별도 `oh-my-openagent.json` 파일을 찾는다. 있으면 다음처럼 질문한다.

> Found a separate oh-my-openagent config outside this project.
> Would you like to apply the same model changes there too?

명시적인 확인 없이 외부 설정을 동기화하지 않는다. 확인하면 승인된 각 파일에 같은 권위, allowlist, 범위,
검증과 보고 절차를 적용한다. 프로젝트 대상을 외부 동기화 대상으로 부르지 않는다.
외부 설정이 없으면 아무 말도 하지 않는다.
