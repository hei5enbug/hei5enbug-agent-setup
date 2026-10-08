# 로컬 게이트웨이로 Claude Code에서 GPT 모델 쓰기

> 영어 원본: [claude-gpt-gateway-plan.md](claude-gpt-gateway-plan.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 실행 중 읽거나 사용하지 않는다.

2026-10-08에 제안한 구현 계획이다. 근거는 2026-10-08에 Claude Code `2.1.294`와 [근거](#근거)에 적은 공식 페이지로
확인했다.

이 계획의 실행을 승인하면 2026-10-07의 두 결정을 뒤집는다. 하나는 로컬 프록시를 채택하지 않은 결정이고, 다른 하나는
[GPT 연결 작업](claude-gpt-remaining.ko.md)과 [남은 작업](model-routing-remaining.ko.md)에 있는 "게이트웨이 금지"
조항이다. 사용자가 실행을 승인할 때까지 이 조항은 유지된다. 네이티브 `turn.step` 경로는 계속 막혀 있다.
`2.1.294` Mods 선언에서도 `ToolInfo`에는 `name`, `description`, `mcp`만 있기 때문이다.
[GPT 연결 작업](claude-gpt-remaining.ko.md#필수-실환경-근거)이 요구하는 실환경 관측은 그대로 적용하며,
AC1–AC10이 이를 이 경로에 대응시킨다.

## 의도와 범위

- 목표: 플러그인의 GPT 런처로 시작한 Claude Code 세션에서 사용자가 `/model`로 언제든지 Claude 모델과 고정된 GPT
  모델 `gpt-6.1-sol`, `gpt-6-luna` 사이를 전환한다. Claude 모델은 사용자 본인의 Claude 로그인으로 실행한다.
  GPT 모델은 OpenAI의 Sign in with ChatGPT를 통해 사용자 본인의 ChatGPT 플랜으로 실행한다.
- 범위:
  - Anthropic Messages 형식으로 통신하는 `127.0.0.1`의 로컬 게이트웨이. 고정된 GPT ID를 지정한 요청은 OpenAI
    Responses API로 변환하고, 나머지 요청은 모두 바꾸지 않고 Anthropic으로 전달한다.
  - `scripts/claude_gpt.py launch`. 게이트웨이를 시작하고, 그 게이트웨이를 향해 Claude Code를 실행하며, 종료할 때
    게이트웨이를 멈춘다.
  - 이 브랜치에 있는 기존 헬퍼의 재사용: Sign in with ChatGPT 프로필, 명시적 API 키 프로필, Responses 스트리밍,
    도구 호출 검증, 저장된 추론 상태.
  - 런처 세션에서만 고정된 GPT ID를 통과시키는 Mod 변경.
  - 오프라인 테스트, 실제 Claude Code 바이너리를 쓰는 오프라인 종단 간 검사, README 절, 기록 갱신, 실환경 인수
    배치 한 번.
- 범위 밖:
  - 네이티브 `turn.step` 경로, 서드파티 프록시, Codex 자격 증명, Codex OAuth 클라이언트, ChatGPT `backend-api`
    엔드포인트.
  - 메인 모델로서의 Astra 계열 고정 모델, 게이트웨이 모델 탐색, `gpt-6-luna`용 선택기 행.
  - 원격·다중 사용자 접근, 그리고 제공자·프로필·과금 방식 사이의 자동 대체.
  - 서브에이전트·worker·리뷰어 고정값, 사용자 설정, Claude Code 바이너리의 변경.
- 제약:
  - GPT 요청은 Sign in with ChatGPT 계약을 따른다. `POST https://api.openai.com/v1/responses`에 `store: false`와
    `stream: true`를 쓰고, 시스템 텍스트는 `instructions`에 넣으며, function 도구는 namespace로 묶는다.
    `previous_response_id`는 쓰지 않고, Preview limitations가 나열한 미지원 필드와 호스팅 도구도 쓰지 않는다.
  - Claude 요청은 Claude Code 게이트웨이 계약을 따른다. `anthropic-*` 헤더와 본문 필드는 허용 목록이 아니라 열린
    목록으로 전달하고, `anthropic-beta`의 OAuth capability를 유지하며, 모든 이벤트를 순서대로 버퍼링 없이 스트리밍한다.
  - 게이트웨이는 Claude 자격 증명을 읽거나 저장하거나 기록하거나 바꾸지 않는다. 자격 증명은 바꾸지 않은 요청에
    담긴 채로 `https://api.anthropic.com`에만 나간다. 게이트웨이는 Codex 자격 증명을 읽지 않는다.
  - GPT 자격 증명은 헬퍼의 보호된 프로필 저장소에만 둔다. 어떤 자격 증명도 로그, 오류, 설정, 모델이 보는 텍스트,
    테스트 픽스처에 들어가지 않는다.
  - 런타임 파일은 모델을 전체 고정 ID로만 적는다.
- 보호 대상: 일반 `claude` 세션, 사용자·프로젝트·관리 설정, 설치된 플러그인 캐시, 기본 훅과 가드, Codex 격리, 역할
  고정값, `hooks/claude-gpt/`의 네이티브 경로 거부.
- 알려진 한계: 사용자가 `/model` 선택기에서 `Enter`를 누르거나 `/model <이름>`을 직접 입력하면, Claude Code는 그
  모델을 새 세션의 기본값으로 저장한다. 선택기에서 `s`를 누르거나 `--model`로 시작하면 저장된 기본값이 유지된다.
  Mods에는 모델을 바꾸는 API가 없고 플러그인은 사용자 설정을 수정하지 않으므로, 플러그인이 이 동작을 바꿀 수 없다.
  README와 선택기 행은 `s`를 누르라고 안내한다. 그래도 GPT 기본값이 저장되면, 일반 세션은 요청을 보내기 전에 GPT
  턴을 거부하고 Claude 기본값으로 되돌리는 방법을 알려 준다.
- 인수 기준:
  - AC1 자격: Sign in with ChatGPT 권한 부여에 `chatgpt.tokens.use.direct`가 들어 있고, `gpt-6.1-sol` 요청 한 번이
    플랜 사용량으로 완료된다. 응답에는 고정된 모델과 실제로 쓰인 effort가 나온다.
  - AC2 일반 세션: 런처 없이 실행하면 동작, 설정, 훅이 바뀌지 않는다. 고정된 GPT ID는 알려진 한계 때문에 기본값으로
    저장된 경우까지 포함해, 네트워크 요청 전에 복구 방법과 함께 거부된다.
  - AC3 Claude 경로: 런처 세션에서 Claude 요청은 사용자의 Claude 로그인으로, 본문과 전달된 헤더가 그대로인 채
    Anthropic에 도달한다. `anthropic-beta`의 OAuth capability와 `/status`가 모두 이를 보여 준다. Claude 선택기 행은
    남아 있고, 스트림은 버퍼링되지 않는다.
  - AC4 GPT 턴: 텍스트가 스트리밍된다. Claude Code의 일반 권한 확인과 훅을 거쳐 한 도구 호출은 승인되고 다른 호출은
    거부된다. scratch 폴더에서 범위를 제한한 편집 한 번이 성공한다. 오류와 거부를 포함한 도구 결과가 모델로
    돌아가고, 여러 단계의 도구 루프가 끝까지 진행되며, 응답에 사용량이 나온다.
  - AC5 전환: 런처 세션에서 `/model` 선택기로 Claude에서 GPT로, 다시 Claude로 전환해도 합성 사실 하나와 앞선 도구
    결과가 유지된다. 이후 `--model gpt-6.1-sol`과 함께 `--resume`해도 둘 다 유지된다. 재개할 때 도구 호출은
    다시 실행되지 않는다.
  - AC6 실패: 사용량 한도, 인증, 미지원 기능, 스트림 중간 실패는 Anthropic 형식 오류로 한 번만 나타난다. 형식이
    잘못됐거나 중복되거나 알 수 없거나 잘린 도구 호출은 실행되지 않는다. 제공자·프로필·과금 대체는 일어나지 않고,
    일부 출력 뒤에는 아무것도 재시도하지 않는다. 턴을 취소하면 상위 요청이 닫힌다.
  - AC7 격리: 게이트웨이는 실행마다 바뀌는 비밀 경로 뒤에서 `127.0.0.1`에만 바인딩한다. 로그, 오류, 모델이 보는
    텍스트에 자격 증명이 나타나지 않는다. Codex와 Claude 자격 증명 파일은 읽지 않는다. GPT 프로필 상태는 헬퍼의
    프로필 저장소에만 있다.
  - AC8 Claude 할당량과의 독립성: Anthropic이 Claude 요청을 `429`로 거부해도 GPT 턴은 계속 동작한다.
  - AC9 되돌리기: 런처가 종료된 뒤 게이트웨이 프로세스나 포트가 남지 않는다. 알려진 한계에 따라 사용자가 저장한
    기본값을 빼면 남는 설정 변경도 없다.
  - AC10 역할과 사용량: GPT로 전환한 뒤와 재개한 뒤에도 서브에이전트는 고정된 Claude 모델과 effort로 실행된다.
    배치는 GPT 턴, Claude 턴, 재시도, 게이트웨이 오버헤드의 사용량을 보고한다.
- 선택적 후속 작업: 상태 줄의 플랜 표시, `gpt-6-luna`용 선택기 행, Astra 계열 고정 모델, API 키 프로필의 실환경 확인,
  실제 할당량 소진 상태의 관측. API 키 프로필은 오프라인 테스트로 계속 다룬다.
- 중단 조건:
  - S3가 `subscription_sharing_user_not_eligible`, `chatgpt.tokens.use.direct`가 없는 권한 부여, 정책 오류 중 하나를
    돌려준다. 계획 전체를 멈추고, 커밋하지 않은 S2 변경을 버리고, 결과를 보고한다. 사용자가 명시적으로 요청할 때만
    API 키 과금으로 계속한다.
  - S1에서 Claude Code가 base URL 경로를 버리거나, 불러온 지연 도구를 아래 규칙으로 변환할 수 없는 형태로
    표현하거나, 내용이 나오기 전에 도착한 스트림 `error` 이벤트 뒤에 재시도하는 것이 확인된다. 멈추고 이 계획을
    고친다.
  - 인용한 공식 계약이 S7 전에 바뀐다. 해당 행을 다시 확인한 뒤 계속한다.
  - 실환경 허용량을 다 쓰거나, 어떤 검사에서든 출력에 자격 증명이 나타난다. 새 요청을 멈춘다.

## 근거

메인 세션이 직접 가져와 확인한 행은 1–5, 9–11, 13이다. 나머지 행은 요약을 돌려주는 researcher의 조회 결과에
근거한다. 계획이 의존하는 동작은 S1과 S7에서 확인한다.

| # | 확인한 내용 | 출처 |
|---|---|---|
| 1 | ChatGPT 플랜 사용은 "open-source and locally hosted apps"용으로 문서화돼 있다. 유료·호스팅 앱은 관심 신청 양식을 쓴다. | [Plan usage overview](https://developers.openai.com/siwc/token-sharing-open-source) |
| 2 | "Eligible ChatGPT Plus and Pro users can use their ChatGPT plan"; 플랜 사용은 "is available to all open-source partners and selected private clients". 이 저장소는 Apache-2.0으로 공개돼 있다. | [Quickstart](https://developers.openai.com/siwc/quickstart) |
| 3 | 등록은 `client_id=dynamic_agent_client`로 시작한다. 플랜 scope는 `offline_access resource.invoke chatgpt.tokens.use.direct`이고, resource는 `https://api.openai.com/v1`이며, 콜백은 `127.0.0.1`의 HTTP다. | [Registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in) |
| 4 | 토큰은 `POST https://api.openai.com/v1/responses`로 보낸다. "do not point it at ChatGPT's `backend-api` endpoints". 사용량 한도 오류는 `response.failed`로 도착할 수 있다. | [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference) |
| 5 | `store: false`와 `stream: true`가 필수다. 시스템 역할 항목, `previous_response_id`, `max_output_tokens`, `metadata`, `temperature`, `top_p` 등 나열된 필드를 거부한다. 도구는 namespace나 `additional_tools`에 넣는다. 호스팅 도구와 `tool_search`는 지원하지 않는다. | [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations) |
| 6 | `subscription_sharing_usage_limit_exceeded`(429): 플랜 요청을 멈춘다. `subscription_sharing_user_not_eligible`(403): OAuth를 반복하지 않는다. `subscription_sharing_unsupported_capability`(400): 같은 본문을 다시 보내지 않는다. 503 코드: 제한된 백오프. | [Errors and recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery) |
| 7 | 액세스 토큰은 1시간, 갱신 토큰은 30일이며 갱신할 때마다 교체된다. 갱신은 직렬화한다. Plus의 5시간 한도는 앱 사이에서 공유되고, Pro에는 이 한도가 없다. | [Token reference](https://developers.openai.com/siwc/token-sharing-open-source/token-reference), [Accounts and sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions) |
| 8 | function 호출과 함께 돌아온 추론 항목은 다시 보낸다. 추론 항목에는 기본적으로 `encrypted_content`가 들어 있다. | [Reasoning guide](https://developers.openai.com/api/docs/guides/reasoning) |
| 9 | `ANTHROPIC_BASE_URL`만 지정하면 claude.ai 로그인이 그대로 쓰인다. 게이트웨이 자격 증명 변수나 `apiKeyHelper`는 로그인을 대체한다. Anthropic으로 트래픽을 넘기는 게이트웨이는 "must forward the OAuth capability in `anthropic-beta`". Anthropic은 "doesn't support routing Claude Code to non-Claude models through any gateway". | [Other LLM gateways](https://code.claude.com/docs/en/llm-gateway) |
| 10 | 서드파티 개발자는 사용자의 플랜 자격 증명으로 요청을 라우팅하거나 그 자격 증명을 중개할 수 없다. 이 제한은 "an end user from signing in to the unmodified Claude Code binary with their own Claude subscription"을 막지 않는다. | [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance) |
| 11 | LiteLLM의 ChatGPT 제공자와 CLIProxyAPI는 Codex CLI 클라이언트 `app_EMoamEEZ73f0CkXaXp7hrann`을 쓴다. LiteLLM은 `https://chatgpt.com/backend-api/codex`를 호출한다. | [LiteLLM constants](https://github.com/BerriAI/litellm/blob/main/litellm/llms/chatgpt/common_utils.py), [CLIProxyAPI auth](https://github.com/router-for-me/CLIProxyAPI/blob/main/internal/auth/codex/openai_auth.go) |
| 12 | Claude Code는 `POST /v1/messages?beta=true`, 선택 사항인 `/v1/messages/count_tokens`, `HEAD /api/hello`를 호출하고, `message_stop`까지 모든 스트림 이벤트가 순서대로 오기를 기대한다. 알 수 없는 모델 ID에는 200K 창을 적용한다. `CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1`은 모든 요청에 effort를 보낸다. | [Gateway compatibility guide](https://code.claude.com/docs/en/llm-gateway-protocol), [Environment variables](https://code.claude.com/docs/en/env-vars) |
| 13 | `/model <이름>`과 선택기의 `Enter`는 기본값을 `~/.claude/settings.json`에 저장한다. 선택기의 `s`, `--model`, `-p`에서의 `/model`은 기본값을 유지한다. `ANTHROPIC_CUSTOM_MODEL_OPTION`은 ID 검증을 건너뛴다. | [Model configuration](https://code.claude.com/docs/en/model-config) |
| 14 | Mods `2.1.294`는 `$.env.get`으로 환경 변수를 읽을 수 있고 모델을 바꾸는 API가 없다. `ToolInfo`에는 여전히 입력 스키마가 없다. `claude plugin list --json`은 설치된 플러그인을 나열한다. | 설치된 Claude Code `2.1.294` |

서드파티 프록시는 11행 때문에 제외한다. 이들은 다른 클라이언트의 OAuth 신원을 빌려 쓰고, LiteLLM은 4행이 금지한
엔드포인트를 쓴다. 기존 헬퍼는 이미 3행과 4행의 흐름을 따른다.

## 구현 전략

```text
claude (수정하지 않은 바이너리, 런처와 같은 버전의 플러그인 설치)
   | ANTHROPIC_BASE_URL=http://127.0.0.1:<port>/<secret>
   v
로컬 게이트웨이 ---- 모델이 gpt-6.1-sol 또는 gpt-6-luna ---> api.openai.com/v1/responses (ChatGPT 플랜)
   |
   +---------------- 그 밖의 요청, 바꾸지 않음 -----------> api.anthropic.com (사용자의 Claude 로그인)
```

### 라우팅

게이트웨이는 `POST /v1/messages`와 `POST /v1/messages/count_tokens`의 JSON `model` 필드만 읽는다. 값이
`gpt-6.1-sol` 또는 `gpt-6-luna`와 정확히 같으면 GPT 경로로 보낸다. 나머지 요청, 메서드, 경로는 모두 Claude 경로로
보낸다. 비밀 경로 접두사가 없는 요청은 `404`를 받고 전달되지 않는다.

### Claude 경로

게이트웨이는 비밀 접두사를 떼고 메서드, 경로, 쿼리, 헤더, 본문 바이트를 바꾸지 않은 채
`https://api.anthropic.com`으로 보낸다. hop-by-hop 헤더만 빼고 `Host`만 다시 쓴다. 리디렉션은 따라가지 않는다.
상태, 헤더, 본문을 청크 단위로 Claude Code에 돌려주며, 스트림에 읽기 타임아웃을 더하지 않는다. AC3를 위해 로그에는
`anthropic-beta`에 OAuth capability가 있는지만 남기고, 헤더 값은 남기지 않는다.

### GPT 경로

게이트웨이는 Anthropic 요청을 헬퍼의 버전 1 요청으로 바꾼 뒤 헬퍼의 Responses 코드로 실행한다.

| Anthropic 입력 | 헬퍼 또는 Responses 입력 |
|---|---|
| `system` 문자열 또는 텍스트 블록 | `instructions`. 빈 줄로 이어 붙이고 `cache_control`은 버린다 |
| 사용자 텍스트와 `image` 블록 | 사용자 메시지 텍스트와 `input_image` data URL |
| base64 PDF를 담은 `document` 블록 | `file_data`를 담은 `input_file` |
| 어시스턴트 텍스트와 `tool_use` | 어시스턴트 출력 텍스트와 같은 `call_id`의 `function_call` |
| `tool_result` 텍스트 | `function_call_output` 텍스트 |
| 권한 거부를 포함해 `is_error: true`인 `tool_result` | `Tool error:`로 시작하고 결과 텍스트가 뒤따르는 `function_call_output` |
| `tool_result` 이미지 | 첨부를 가리키는 `function_call_output` 텍스트, 그 뒤에 `input_image`를 담은 사용자 메시지 |
| `thinking`과 `redacted_thinking` | 버린다 |
| `server_tool_use`와 웹 검색 결과 | 결과는 각 제목과 URL을 담은 일반 텍스트가 되고, 호출은 버린다 |
| 클라이언트 도구(`input_schema`) | 헬퍼의 `claude` namespace에 든 function 도구 |
| `defer_loading: true`인 도구 | 대화 앞부분의 `tool_reference` 블록이 이름을 가리킨 뒤에만 보낸다 |
| 웹 검색 같은 서버 도구 | 버린다 |
| `tool_choice`의 `auto`, `any`, `tool`, `none` | `auto`, `required`, 지정한 함수, `none` |
| `output_config.effort` | 같은 값의 `reasoning.effort`. 없으면 모델 기본값 |
| `max_tokens`, `temperature`, `top_p`, `top_k`, `stop_sequences`, `metadata`, `thinking`, `context_management` | 무시한다. 플랜 사용 경로가 거부하거나 지원하지 않기 때문이다 |

헬퍼의 스키마 검사는 모든 JSON Schema 키워드를 받아들인다. 도구 인자는 헬퍼가 이해하는 키워드(`type`,
`properties`, `required`, `items`, `enum`, `additionalProperties`)로만 검증하고, 나머지는 Claude Code의 자체 입력
검증에 맡긴다. 헬퍼는 추론 항목을 `call_id`를 키로 해서 프로필의 상태 디렉터리에 기존 크기 제한 안에서 보관하고,
가장 오래된 것부터 지운다. 같은 `call_id`를 담은 이후 요청은 그 항목을 다시 받는다. 항목을 잃어도 권장되는 추론
맥락만 빠질 뿐 요청은 그대로 실행된다.

응답은 Anthropic 스트림으로 바뀐다. 텍스트는 `text_delta`로 스트리밍한다. 도구 호출은 헬퍼가
`response.completed`를 검증하고 상위 스트림을 오류 없이 끝까지 읽을 때까지 보류한다. 그 뒤에야 각각
`input_json_delta` 하나를 담은 `tool_use` 블록으로 보낸다. `response.completed` 뒤에 실패하면 스트림 `error`
이벤트를 보내고 `tool_use` 블록은 보내지 않는다. `stop_reason`은 호출이 있으면 `tool_use`, 없으면 `end_turn`이다.
사용량은 `input_tokens`에서 캐시 토큰을 뺀 값을 `input_tokens`로, 캐시 토큰을 `cache_read_input_tokens`로,
`output_tokens`를 `output_tokens`로 옮긴다. `call_id`가 `^[A-Za-z0-9_-]{1,64}$`에 맞지 않으면
`unsupported_call_id`로 턴을 실패시킨다. GPT ID의 `count_tokens`는 `404`를 돌려주므로 Claude Code는 자체 추정치를
쓴다.

### 오류

HTTP 상태는 게이트웨이가 응답 헤더를 보내는 순간 확정된다. 게이트웨이는 OpenAI가 `200`을 돌려주고 스트림을 연
뒤에만 `200`과 `message_start`를 보내고, 첫 내용이 나올 때까지 10초마다 `ping`을 보낸다.

| 상황 | 헤더 전: 상태와 유형 | 헤더 후 | `x-should-retry` |
|---|---|---|---|
| `subscription_sharing_usage_limit_exceeded` | `429 rate_limit_error`, ChatGPT Settings > Usage 안내 | `rate_limit_error` 스트림 `error` | `false` |
| 자격 없음, scope 누락, 잘못된 사용자, 최종 갱신 오류 | `auth` 명령을 안내하는 `401 authentication_error` 또는 `403 permission_error` | 같은 유형의 스트림 `error` | `false` |
| 미지원 기능 또는 effort | GPT 필드를 가리키는 `400 invalid_request_error`. `output_config`는 절대 가리키지 않는다 | 같은 유형의 스트림 `error` | `false` |
| 503 코드 | `503 api_error` | `api_error` 스트림 `error` | 헤더 전에만 `true` |
| 미완료 응답, 검증 실패, 끊긴 스트림 | 해당 없음 | `api_error` 스트림 `error` | 해당 없음 |

헬퍼는 HTTP 상태와 다음 허용 목록의 제공자 코드를 `http_error`나 `provider_failed`로 뭉개지 않고 구조화된 필드로
보존한다: `subscription_sharing_usage_limit_exceeded`, `subscription_sharing_usage_unavailable`,
`subscription_sharing_user_not_eligible`, `subscription_sharing_unsupported_capability`,
`subscription_sharing_route_not_supported`, `subscription_sharing_invalid_user`,
`subscription_sharing_user_unavailable`. `output_config` 규칙은 Claude Code가 effort를 빼고 조용히 재시도하는 것을
막는다. Claude Code가 연결을 닫으면 게이트웨이는 상위 응답을 닫고, 미완료 응답에서 나온 도구 호출은 내보내지 않는다.

### 런처

`scripts/claude_gpt.py launch --profile <profile-id> [-- <claude 인자>]`가 현재의 거부 동작을 대체한다.

1. 환경에 `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_USE_BEDROCK`,
   `CLAUDE_CODE_USE_VERTEX`, `CLAUDE_CODE_USE_FOUNDRY` 중 하나가 있거나, 읽을 수 있는 사용자·프로젝트·로컬·관리 설정
   파일이 `apiKeyHelper`나 이 변수들 중 하나를 `env` 블록에 지정하면 거부한다. Claude Code 인자 `--settings`,
   `--setting-sources`, `--bare`도 인증 수단을 더하거나 뺄 수 있으므로 거부한다. 키나 인자가 있는지만 확인하고,
   자격 증명 값은 읽지 않는다.
2. `claude plugin list --json`에서 `hei5enbug-agent-setup@hei5enbug`가 활성화돼 있고, 로컬 캐시버스터 접미사를
   제외한 `<major>.<minor>.<patch>`가 런처의 `pyproject.toml`과 같아야 한다. 그래야 설치된 Mod가 GPT 턴을
   통과시킨다. 그렇지 않으면 거부한다.
3. 명시적으로 지정한 프로필을 불러오고, 필요하면 토큰을 갱신한다. 로그인은 절대 시작하지 않는다.
4. OS가 정한 포트와 256비트 무작위 경로 비밀값으로 `127.0.0.1`에서 게이트웨이를 시작한다.
5. 부모 환경에 다음을 더해 `PATH`의 `claude`를 실행한다: `ANTHROPIC_BASE_URL`과 같은 URL의
   `HEI5ENBUG_GPT_GATEWAY_URL`, `ANTHROPIC_CUSTOM_MODEL_OPTION=gpt-6.1-sol`,
   `ANTHROPIC_CUSTOM_MODEL_OPTION_NAME=gpt-6.1-sol`, `ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION`(값은
   `ChatGPT plan via local gateway; press s to keep your default` 또는
   `OpenAI API key via local gateway; press s to keep your default`), `CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1`.
   나머지 인자는 그대로 넘기고 표준 입출력을 상속한다.
6. `claude`가 끝나면 게이트웨이를 멈추고 그 종료 코드를 돌려준다.

프로필은 게이트웨이가 살아 있는 동안 그 게이트웨이에 묶여 있다. 런처로 `--resume`하면 다시 지정한 프로필이 묶인다.
게이트웨이는 터미널에 아무것도 쓰지 않는다. 정리한 코드, 요청 ID, 토큰 수만 헬퍼 프로필 루트의
`logs/gateway.log`에 모드 `0600`으로 덧붙이고, 1MB에서 파일 하나로 순환한다.

### Mod

`hooks/mod/gpt.js`는 메인 루프에서 두 고정 ID의 `turn.step`을 계속 가로챈다.
`$.env.get("HEI5ENBUG_GPT_GATEWAY_URL")`과 `$.env.get("ANTHROPIC_BASE_URL")`이 둘 다 있고 값이 같으면
`next(event)`를 호출한다. 그렇지 않으면 지금처럼 거부하되, 메시지에 런처 명령, Claude 기본값으로 되돌리는
`/model claude-opus-5-5`, 알려진 한계에 대한 설명을 담는다.

### 코드 위치

구현은 `main`에 들어간다. 이 브랜치에서 `scripts/claude_gpt.py`, `tests/test_claude_gpt.py`, `claude-gpt` extra
(`PyJWT[crypto]>=2.10`)와 그 `uv.lock` 항목을 되살린 뒤 바꾼다. `scripts/claude_gpt_gateway.py`와
`tests/test_claude_gpt_gateway.py`를 새로 만든다. `hooks/claude-gpt/`와 `config/claude-gpt-hooks.json`은 이
브랜치에 남는다. AGENTS.md 표에 따르면 사용자가 쓰는 새 런처는 외부 계약 변경이므로 릴리스 수준은 minor다.
사용자는 설치된 플러그인 캐시가 아니라 소스 체크아웃에서 `uv run --extra claude-gpt`로 런처를 실행한다. S6과 S7은
AGENTS.md가 로컬 재설치에 쓰라고 한 캐시버스터로 작업 트리를 플러그인으로 설치해, 실행되는 Claude Code가 새 Mod를
불러오게 한다.

## 실행 조각

Worker 모델과 effort: 구현 실행 규칙에 따른 호스트의 구현 worker 경로이며, 호스트의 에이전트 규칙이 고정한 값이다.
메인이 맡는 조각은 메인 세션의 모델과 effort를 유지한다. 모든 worker 할당에는 할당된 worker라는 사실, 다른
worker가 작업 공간을 수정할 수 있다는 사실, 그들의 변경을 보존해야 한다는 사실을 적는다. S2부터 S5까지는 S7이
끝날 때까지 커밋하지 않는다.

| 조각 | 결과와 변경 | 담당 | 허용·보호 경로 | 선행 조건 | 공유 자원과 병렬 조건 | 검증과 완료 근거 |
|---|---|---|---|---|---|---|
| S1 요청 형태 | 오프라인 캡처: 일회용 가짜 Anthropic 서버가 런처의 모델 환경과 비밀 base URL 경로로 실행한 `claude -p` `2.1.294`에 스크립트된 스트림을 돌려준다. 실행 A는 실제 Claude 설정과 `--model claude-opus-5-5`로 OAuth 요청 형태를 기록한다. 실행 B는 플러그인이 없는 scratch `CLAUDE_CONFIG_DIR`과 더미 `ANTHROPIC_AUTH_TOKEN`을 써서 설치된 Mod가 거부하지 못하게 하고, `--model gpt-6.1-sol`과 `gpt-6-luna`로 GPT ID 형태를 기록한다. 기록은 구조만 남긴다: 접두사를 포함한 경로, 헤더 이름, 본문 키, 블록 유형, 도구 플래그, `tool_reference` 블록, effort와 thinking 필드, `count_tokens`, 백그라운드 요청, `--resume`. 스크립트된 턴은 ToolSearch를 호출하고, PNG와 PDF를 Read하고, 거부되는 도구를 받는다. 캡처한 도구 스키마를 모두 헬퍼의 현재 스키마 검사에 통과시킨다. `x-should-retry: false`인 `429` 뒤와, 내용 전에 온 스트림 `error` 뒤의 Claude Code 동작을 관찰한다. | 메인 | scratch 파일만. 헤더 값은 기록하지 않는다 | 없음 | 모델 요청 없음 | 라우팅, 지연 도구, 스키마, effort, 오류 규칙을 확정하거나 멈추게 하는 구조 보고서 |
| S2 헬퍼 | 헬퍼, 테스트, 패키징을 되살린다. 이미지·파일 파트, null 허용 effort, `tool_choice`, `is_error` 결과, `call_id` 기준 추론 상태, 관대한 스키마 검사, 구조화된 HTTP 상태와 제공자 코드, `claude_gpt_gateway.launch(profile_id, claude_args)`를 호출하는 `launch`를 추가한다. | Worker | 허용: `scripts/claude_gpt.py`, `tests/test_claude_gpt.py`, `pyproject.toml`, `uv.lock`. 보호: 나머지 전부 | S1 | 잠금 파일 | `uv run --extra claude-gpt --extra dev pytest tests/test_claude_gpt.py` |
| S3 자격 | 사용자가 S2 헬퍼로 `auth subscription`을 실행하고, 메인이 `status`와 도구 없는 `gpt-6.1-sol` 버전 1 `request` 한 번을 실행한다. | 메인과 사용자 | 추적 경로 없음 | S2, 그리고 실행과 실환경 허용량에 대한 사용자 승인 | 실환경 허용량 중 GPT 요청 1회 | 부여된 scope, 정리한 상태, 응답 모델과 effort, 사용량 증빙. 또는 계획을 멈추게 하는 자격 오류 |
| S4 게이트웨이 | `scripts/claude_gpt_gateway.py`에 서버, 라우팅, Claude 경로, GPT 변환, 스트림 작성기, 오류 대응, 취소, 비공개 로그, 런처 검사를 추가한다. 테스트는 소켓 없이 프로세스 안의 가짜 객체를 쓰고, 형식 오류·중복·알 수 없음·잘림 도구 호출을 포함한다. | Worker | 허용: `scripts/claude_gpt_gateway.py`, `tests/test_claude_gpt_gateway.py`. 보호: 나머지 전부 | S3 | S2 헬퍼 API를 가져다 쓴다. S5와 병렬 가능 | `uv run --extra claude-gpt --extra dev pytest tests/test_claude_gpt_gateway.py tests/test_claude_gpt.py` |
| S5 Mod와 README | `hooks/mod/gpt.js`를 위 설명대로 바꾸고, 두 README에 인증, 실행, `s`를 쓰는 전환, 알려진 한계, 플랜 한도, 되돌리기를 적는다. | Worker | 허용: `hooks/mod/gpt.js`, `hooks/mod/gpt.test.ts`, `README.md`, `README.ko.md`. 보호: 나머지 전부 | S3 | S4와 공유 파일 없음 | `claude plugin validate .`, `claude plugin test .`, `python3 -m pytest tests/test_korean_mirrors.py` |
| S6 오프라인 종단 간 검사 | 작업 트리를 캐시버스터로 플러그인 설치한다. scratch 하네스가 가짜 Anthropic·OpenAI 상위 서버와 함께 Python API로 게이트웨이를 시작하고, 스크립트된 서브에이전트 요청을 포함해 실제 `claude -p`를 실행한다. | 메인 | scratch 파일과 로컬 플러그인 설치만. 헤더 값은 기록하지 않는다 | S4와 S5 | 하네스가 소유한 로컬 포트 | 실환경 전용 부분을 뺀 AC2–AC10 근거 |
| S7 실환경 인수 | scratch 폴더에서 2개 케이스로 된 배치 한 번. 케이스 1은 런처를 통한 대화형 실행이다. Claude 모델에서 사용자가 합성 사실을 말하고 Claude가 파일을 읽는다. 사용자가 선택기와 `s`로 `gpt-6.1-sol`로 전환한다. GPT가 파일을 읽고, 사용자가 승인한 범위 제한 편집 한 번을 하고, 사용자가 거부하는 쓰기를 시도한다. 사용자가 GPT 턴 하나를 Esc로 취소한다. 사용자가 `s`로 다시 전환하고, Claude가 그 사실과 앞선 도구 결과를 기억한다. 케이스 2는 런처를 통해 `--model gpt-6.1-sol`과 `-p`로 케이스 1을 `--resume`하고, GPT가 둘 다 기억하며 researcher 서브에이전트 하나를 시작한다. | 메인과 사용자 | scratch 파일만 | S6, 그리고 실환경 허용량 승인 | 최대 2개 케이스, Claude Code 시작 4회, 20분, S3를 포함한 GPT 요청 10회 | 각 AC의 통과·실패·미검증과 함께 빌드, 모델, effort, 인증 방식, 요청 수, 트랜스크립트 역할 기록, 사용량 증빙 |
| S8 통합과 기록 | 계획한 버전을 정하고, `README.md`의 모든 개발 검사를 실행하고, 이 브랜치의 기록을 결과에 맞게 고치고, `suggest-commit`으로 커밋한다. 푸시는 사용자가 요청할 때만 한다. | 메인 | `main`의 버전 파일과 이 브랜치의 기록 | S7 | 모든 worker가 멈춘 뒤 실행 | `HEAD`에서 모든 개발 검사 통과 |

## 통합 검증

| 기준 | 오프라인 근거 | 실환경 근거 |
|---|---|---|
| AC1 | scope 검사, 갱신, 구조화된 제공자 코드에 대한 S2 테스트 | S3 |
| AC2 | 두 환경 상태와 저장된 GPT 기본값에 대한 S5 Mod 테스트, 런처 없이 실행한 S6 | 필요 없음 |
| AC3 | S4 바이트 동일성 테스트, 가짜 Anthropic 서버를 통한 S6 전달 | S7 Claude 턴과 `/status` |
| AC4 | S4 변환·스트림 테스트, 승인·거부·오류 결과·편집을 포함한 S6 도구 루프 | S7 케이스 1 |
| AC5 | `--model`을 쓴 S6 `--resume`과 재실행 검사 | S7 케이스 1과 2 |
| AC6 | S4 오류 표·도구 호출 거부·취소 테스트, S1 재시도 관찰, S6 부분 실패와 취소 | S7 Esc 취소. 실환경 부분 실패는 실제로 일어났을 때만 기록 |
| AC7 | S4 바인딩·비밀 경로·로그 테스트, 출력과 로그에 픽스처 비밀값이 없다는 검사 | S7 로그 점검 |
| AC8 | 가짜 Anthropic 서버가 `429`를 돌려주는 S6 | 선택적 실제 관측 |
| AC9 | 종료 뒤 S6 프로세스·포트 검사 | S7 프로세스 검사 |
| AC10 | 전환과 재개 뒤에도 고정 모델을 유지하는 S6 서브에이전트 요청 | S7 케이스 2 트랜스크립트 기록과 사용량 보고 |

오프라인 성공은 실환경 동작, 계정 자격, 플랜 한도를 증명하지 않는다. 실환경 결과는 따로 기록한다. 이 계획은
런타임에 장애 주입 스위치를 넣지 않으므로 실환경 부분 실패를 일부러 일으킬 수 없다. S7에서 실제로 일어나지 않으면 그
관측은 실환경 미검증으로 남고, 사용자가 S6 오프라인 근거를 받아들일 때까지 A11은 그 항목 때문에 열린 상태로 남는다.
