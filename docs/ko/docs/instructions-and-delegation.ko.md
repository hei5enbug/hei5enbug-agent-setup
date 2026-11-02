# 지침과 위임

> 영어 원본: [instructions-and-delegation.md](../../instructions-and-delegation.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 문서는 지침을 불러오는 방식과 작업을 배정하고 검증하며 범위 안에서 끝내는 규칙을 설명합니다.

## 지침 자동 적용

macOS와 Linux에서 플러그인 훅은 `instructions/session/core.md`, `instructions/session/common.md`와 현재 호스트의 지침을
합친다. Codex에는 `codex.md`, Claude Code에는 `claude-code.md`를 사용한다. `core.md`는 모든 에이전트에 적용되는 규칙을 담는다.
호스트의 `PATH`에서 `python3`로, 또는 훅 Python 인터프리터 옵션이 가리키는 인터프리터([기능 옵션](configuration.ko.md#기능-옵션) 참고)로 Python 3.12
이상을 실행할 수 있어야 한다.
훅은 Python 표준 라이브러리만 사용한다.
루트 `AGENTS.md`는 이 저장소 개발에만 적용하며 훅은 이 파일을 읽지 않는다.

`hooks/hooks.json`은 두 호스트에서 모두 동작하는 훅을 담는다. Claude Code는 이 파일을 자동으로 찾고
`.claude-plugin/plugin.json`의 `hooks` 경로인 모드 설정과, Claude Code 전용 프롬프트 알림을 담은
`hooks/claude-hooks.json`을 이어서 합친다. Codex는 `.codex-plugin/plugin.json`이 나열한 파일인
`hooks/hooks.json`과, Codex 전용 에이전트 차단 훅과 DataGrip 권한 요청 훅을 담은 `hooks/codex-hooks.json`을 불러온다.
Codex가 제공하는 `PLUGIN_ROOT`가 설치 디렉터리를 가리키면 로더는 Codex 지침을 선택한다.
스크립트 위치는 두 호스트가 제공하는 `CLAUDE_PLUGIN_ROOT`로 찾는다.
사용자 전역 지침 파일이나 작업 저장소의 지침 파일은 복사하거나 덮어쓰지 않는다.

| 시점 | 동작 |
|---|---|
| 세션 시작·재개 | `SessionStart`가 설치된 지침 파일을 전달한다. 필요하면 `host_settings.py check`가 찾은 문제를 한 줄짜리 안내로 추가한다. 최대 세 개를 보여 주고 나머지는 개수로 알린다. 예를 들면 Claude의 `defaultMode`가 `dontAsk`이거나, `permissions.ask` 규칙이 Bash·MCP 도구에 적용되거나, 기존 Codex 설정에 `[features] plugin_hooks = true`가 없는 경우다(Codex 설정은 양쪽 호스트에서 확인). `host_settings` 옵션이 `apply`인 Codex에서는 먼저 `apply`를 실행하며, 이는 허용 목록의 Codex 설정을 바꿀 수 있다([호스트 설정](configuration.ko.md#호스트-설정) 참고). 바꾼 내용은 안내 한 줄로 알린다. 안내는 컨텍스트 한도 안에 들어가야 한다. Orca 터미널에서는 플러그인 디렉터리와 지침 요약값을 담은 표식도 남긴다. |
| 세션 초기화·컨텍스트 압축 | `SessionStart`가 지침을 다시 전달한다. |
| 서브에이전트 시작 | `SubagentStart`가 짧은 역할 컨텍스트를 전달한다. `core.md`와, 구현 에이전트에는 "Assigned workers" 규칙을 더한다. |
| 역할 실행기의 자식 세션 시작 | `core.md`만 받는다. 역할 규칙은 실행기가 할당 앞에 붙인다. |
| 도구 호출 종료 | 진행 상황 안내가 다른 언어로 쓰였으면 `PostToolUse`가 언어 알림을 추가한다. |
| 답변 종료 | 답변이 응답 언어로 쓰이지 않았으면 `Stop`이 다시 쓰도록 요청한다. |
| Claude Code에서 사용자가 프롬프트 제출 | `UserPromptSubmit`이 메인 세션의 "Implementation worker route", "Worker agent model", "Review model" 줄을 세션 시작 시 기록한 줄과 비교하고, `/config` 변경으로 달라졌으면 새 줄을 한 번 제공한다. |
| DataGrip 쿼리 실행 직전 | `PreToolUse`가 두 호스트에서 `execute_sql_query` 실행 전에 DataGrip 쿼리 가드를 실행하고, `PermissionRequest`는 Codex에서만 실행한다. |
| Bash, MCP 또는 대상 파일 도구 호출 실행 | `PreToolUse`가 상태 파일 보호와 민감 읽기 검사를 포함한 승인 가드를 실행한다. `PermissionRequest`는 Claude Code에서 호스트 프롬프트를 흡수하고 Codex에서는 승인된 뒤 네이티브 창을 건너뛰며, `PostToolUse`와 `PostToolUseFailure`는 승인을 기록한다. 양쪽 호스트의 `UserPromptSubmit`은 승인 요청 횟수를 초기화하고 사용자 승인을 기록하며 즉시 재시도 컨텍스트를 제공한다. |
| 조건에 맞는 작업 시작 | 에이전트가 `instructions/`의 필수 참조를 읽는다. |
| 플러그인 업데이트 설치 | 새 세션이 설치된 버전을 읽는다. 저장소에 푸시하는 것만으로는 반영되지 않는다. |

핵심 규칙은 요청이 바뀌어도 세션 컨텍스트에 남는다.
서비스 접근, 보호된 보안 값 접근, 에이전트 사용, 문서 작성, 구현 실행의 세부 규칙은 관련 작업 전에만 읽는다.
요청을 처리하던 중 관련 작업이 생겨도 먼저 참조를 읽는다.
세션 컨텍스트는 구현 계획과 설계 문서를 구분하고 두 작업의 실행 조건을 유지한다.
`instructions/implementation-planning.md`는 구현 계획의 6단계 절차와 템플릿을 관리한다.
`technical-design-writer`는 설계 문서와 RFC를 담당한다.
`instructions/independent-model-validation.md`는 두 결과물에 공통으로 적용되는 독립 검증 규칙을 관리한다.
컨텍스트 헤더는 `$I`를 설치된 플러그인의 `instructions` 폴더로 정의한다. 로더는 각 세션 지침에서 이 폴더 안의 파일을
가리키는 조건부 링크를 `$I/<path>`로 쓰므로 설치 경로가 길어져도 컨텍스트가 늘어나지 않는다.
플러그인 안의 다른 파일을 가리키는 링크는 절대 경로를 유지한다.
세션을 시작할 때 조건부 참조 본문까지 읽지는 않는다.

Codex는 현재 플러그인 훅 정의를 사용자가 검토하고 신뢰한 뒤에 실행한다.
훅이 꺼져 있거나 조직 정책이 플러그인 훅을 금지하면 자동 적용되지 않는다.
설치·업데이트 후 호스트의 훅 설정에서 활성화 여부를 확인하고, Codex에서는 신뢰 여부도 확인한다.
에이전트 차단 훅, 언어 가드, DataGrip 쿼리 가드처럼 업데이트가 새로 추가하거나 바꾼 훅은 Codex의 `/hooks`에서 신뢰하기 전까지 건너뛴다.
Codex의 신뢰는 플러그인 파일 내용도 포함하므로, 플러그인을 업데이트할 때마다 모든 플러그인 훅이 `modified`가 된다.
플러그인은 자기 훅만, 그리고 설치본이 Codex 설치 표식 외에는 공식 저장소의 깨끗한 git checkout이고, skip-worktree나
assume-unchanged로 표시한 추적 파일이 없고, HEAD가 공식 저장소가 지금 `main`이나 `v*` 태그로 광고하는 커밋(`git ls-remote`)이거나
임시 저장소로 받아 온 그 `main` 끝의 조상일 때만 다시 신뢰한다. 로컬 참조와 태그는 근거가 되지 않으며, 네트워크에 닿지 못하면
신뢰하지 않는다. `orca-plugin-refresh`는 Codex 설치 직후에, 역할 실행기는 준비 확인이나 사전 점검에서
가드가 신뢰되지 않았음을 발견했을 때 이렇게 한다. `codex app-server`의 `config/value/write` 메서드로 각 훅의 현재 해시를
기록하고 `hooks/list`로 결과를 확인한다. 그 밖의 경우, 즉 로컬에서 고친 설치본이나 다른 플러그인은 업데이트할 때마다
`/hooks`에서 훅을 다시 신뢰해야 한다.
Claude Code mod는 Codex 훅이 아니므로 이 신뢰 절차가 적용되지 않는다.
업데이트 후에는 Claude Code를 재시작하거나 Codex에서 새 세션을 시작한다.
훅은 호스트의 신뢰 설정을 우회하지 않으며, 실행 중인 세션의 플러그인 버전을 바꾸지 않는다.
`orca-plugin-refresh` 스킬은 이 표식으로 실행 중인 Orca 세션에 업데이트를 재시작 없이 반영한다.

세션 지침 누락·빈 파일·잘못된 로컬 참조, 9,600 UTF-8 바이트를 넘는 메인 컨텍스트나 4,000 UTF-8 바이트를 넘는 역할 컨텍스트는 표준 오류로 알린다.
이때 지침 일부만 전달하지 않는다. 메인 상한은 Claude Code가 훅 필드 하나에서 전달하는 10,000자보다 작고,
세션 시작 훅은 `additionalContextLimit`을 `0`으로 두어 Codex가 파일 경로와 미리보기 대신 컨텍스트 전체를 전달하게 한다.
세션 시작 훅의 오류가 호스트 실행을 반드시 중단시키지는 않으므로, 오류를 해결한 뒤 자동 적용을 사용한다.
세션 지침 파일은 짧게 유지하고 세부 사항은 조건부 참조로 옮긴다.
Windows 실행과 실제 모델의 지침 준수 여부는 테스트 범위에 포함하지 않는다.

실행 시점과 신뢰 설정은 공식 [Codex 훅 문서](https://learn.chatgpt.com/docs/hooks)와
[Claude Code 훅 문서](https://code.claude.com/docs/en/hooks)를 따른다.

## 상황별 위임

메인 세션은 [공통 지침](../instructions/session/common.ko.md)에 따라 직접 처리할지 위임할지 판단합니다.
알려진 경로 조회, 변경 파일이 두 개 이하인 구현, 통합 수정은 메인이 처리합니다. 범위가 한정된 조사, 많은 근거 수집,
독립적으로 수행할 수 있는 더 큰 구현은 예상 이득이 조정 비용보다 클 때 작업자를 사용합니다. 의존성이 긴밀한 작업은 한 담당자가 이어서 처리합니다.
모든 작업에서 실제 비용이 줄어든다고 보장하는 정책은 아닙니다.

메인은 요구사항, 설계, 작업 경계, 수용 판단과 최종 보고를 맡습니다.
[구현 실행 규칙](../instructions/implementation-execution.ko.md)은 메인 담당 작업을 포함한 모든 구현의 작업 준비,
할당 항목과 수용을 정의합니다. [구현 위임 규칙](../instructions/implementation-delegation.ko.md)은 작업자 소유권,
충돌 없는 일정, 복구와 할당받은 worker 규칙을 정의하며, 구현을 위임하기 전에 읽습니다. 직접 작업은 메인의 현재
모델과 사고 강도를 유지합니다. 위임할 때는 작업 범위, 필요한 맥락, 허용·보호 경로, 선행 조건, 수용 검사와 호스트의
고정 설정만 전달합니다. 작업자는 하위 에이전트를 만들 수 없습니다.

UI 코드, 시각 디자인, 다이어그램 작업은 대신 호스트의 designer 경로로 보냅니다. 다만 호스트 세션 파일이 메인 세션에
맡긴 종류는 예외입니다. Claude Code에서는 메인 세션이 문서 안의 ASCII와 Mermaid 다이어그램을 그리고, 기존 SVG
다이어그램을 고치며, 노드 일곱 개 이하의 새 SVG나 PNG 흐름도를 만듭니다. 레이아웃과 컴포넌트 구조를 바꾸지 않는
문구·스타일 값 수정은 구현 worker가 맡을 수 있고, 설계 문서와 RFC는 메인 세션이 맡습니다.

다섯 기능은 `investigation`, `implementation`, `design`, `language`, `review` 입니다. 모든 대체 항목은 다른 모델 계열입니다. 다른 호스트의 모델이 필요한
대체 항목은 역할 실행기를 거치고, 현재 호스트에서 바로 실행할 수 있는 대체 항목은 이름이 붙은 에이전트를 씁니다.
`config/model-registry.json`은 모델 고정값과 역량 고정값의 단일 출처이며, 스크립트와 mod가 이 파일을 읽습니다.
기능별 호스트 항목은 [모델 라우팅 계약](../../../instructions/model-routing.md#capability-pins)의 역량 고정값 절에 있습니다.

| 호스트 | 구현 에이전트 | 모델과 사고 강도 |
|---|---|---|
| Codex | Claude를 실행하는 `role_runner.py implementation --host codex`; 대체는 rollout 기록으로 검증한 플러그인 `worker` 역할 | `claude-sonnet-5-5`, `high`(최대 `xhigh`); 대체는 `codex_worker_model`, `codex_worker_effort`(기본 `gpt-5.6-luna`, `high`) |
| Claude Code | `implementation_worker`가 `auto`(기본)이면 메인 세션이 작업마다 고릅니다. 쉬운 작업은 `hei5enbug-agent-setup:worker`, 보통·어려운 작업은 `hei5enbug-agent-setup:sonnet-worker`이며, Claude 경로가 실패하거나 사용량 한도로 중단되면 `role_runner.py implementation --fallback`을 씁니다. 고정 설정은 `sonnet`, `sol`, `codex`(`role_runner.py worker`), `haiku`(대체 경로는 `role_runner.py agent --name hei5enbug-agent-setup:worker --fallback`)를 강제합니다 | `worker_model`, `worker_effort`(기본 `claude-haiku-5-5`, `high`)(쉬움); `claude-sonnet-5-5`, `high`(보통·어려움); `gpt-6.1-sol`, `high`(최대 `xhigh`)(대체); `gpt-5.6-luna`, `high`(최대 `xhigh`)(`codex`) |
| Codex, designer | rollout 기록으로 검증한 플러그인 `designer` 역할, 대체는 `role_runner.py agent --name designer --fallback` | `gpt-6-astra`, `high`(최대 `xhigh`); 대체 `claude-opus-5-5`, `high`(최대 `xhigh`) |
| Claude Code, designer | 서브에이전트 기록이나 mod의 역할 고정으로 검증한 `hei5enbug-agent-setup:designer`, 대체는 `role_runner.py design` | `claude-opus-5-5`, `xhigh`; 대체 `gpt-6-astra`, `high`(최대 `xhigh`) |
| Codex, 로컬 scout | rollout 기록으로 검증한 플러그인 `scout` 역할 | `gpt-5.6-luna`, `high`(최대 `xhigh`) |
| Claude Code, 로컬 scout | `role_runner.py scout`, 대체 시 `hei5enbug-agent-setup:scout` | `gpt-5.6-luna`, `high`(최대 `xhigh`); 대체 시 `claude-sonnet-5-5`, `medium` |
| Codex, 공개 researcher | 웹 검색만 쓰고 셸 네트워크는 쓰지 않는 `role_runner.py researcher`, 세션 기록으로 검증 | `gpt-5.6-luna`, `high`(최대 `xhigh`) |
| Claude Code, 공개 researcher | 웹 검색만 쓰고 셸 네트워크는 쓰지 않는 `role_runner.py researcher`, 대체 시 웹 검색과 가져오기 도구를 가진 `hei5enbug-agent-setup:scout` | `gpt-5.6-luna`, `high`(최대 `xhigh`); 대체 시 `claude-sonnet-5-5`, `medium` |
| Codex, 스킬 검토 | `role_runner.py review`; 대체는 rollout 기록으로 검증한 플러그인 `reviewer` | `claude-opus-5-5`, `high`(최대 `xhigh`); 대체 `gpt-6.1-sol`, `high`(최대 `xhigh`) |
| Claude Code, 스킬 검토 | `review_model` 설정을 쓰는 `role_runner.py reviewer`; 대체는 `hei5enbug-agent-setup:reviewer` | `review_model`(기본 `gpt-6-astra`), `high`(최대 `xhigh`); 대체 `claude-opus-5-5`, `high` |
| Skill Builder 시험 실행 및 기타 비검토 참여자 | Skill Builder 어댑터에 따른 호스트의 상위 모델 | Codex: `gpt-6.1-sol`, `xhigh`; Claude Code: `claude-opus-5-5`, `high` |

Claude Code에서는 `scripts/role_runner.py`가 scout, researcher, reviewer, Codex worker 역할을 실행하고, `--instructions <file>`이
역할 정의를 주면 레지스트리의 기능(capability), 예를 들어 Claude 모델 기능도 실행합니다. 에이전트 모드는 `--name <name>`으로 받은
플러그인 에이전트의 다른 모델 계열 대체 항목을 실행합니다. 메인 세션은 할당을 파일로 쓰고 세션 폴더에서
`python3 <plugin>/scripts/role_runner.py <role-or-capability>` 또는
`python3 <plugin>/scripts/role_runner.py agent --name <name> --fallback` 을
`--assignment <file> --result <file>`과 함께 실행합니다. `reviewer`에는 `--model <id>`, `worker`, 쓰기 기능, 쓰기 접근 에이전트에는
`--add-dir <dir>`, MCP 도구나 네트워크가 필요한 기능이나 에이전트에는 `--mcp`, 기능의 호스트 항목을 고르려면 `--host claude|codex`,
대체 항목에는 `--fallback`, 실행을 이어 가려면 상태 줄의 `evidence.session`으로 `--resume <session_id>`를 더할 수 있습니다.
`--effort <level>`은 항목에 지정된 범위 안에서 사고 강도를 높이며, 하한이 기본값입니다. `--user-requested`는 사용자가 그
작업에 지정한 모델이나 사고 강도를 표시합니다. 이 플래그가 있으면 `--model <id>`를 모든 역할, 기능, 에이전트 모드에 쓸 수 있고, `via: runner`가 아닌 기능 항목도 그 항목의 모델로
실행기에서 실행하며
`--effort <level>`은 모델의 사고 강도 규칙이 허용하는 모든 수준을 쓸 수 있습니다. 실행기가 실행할 수 없는 모델이나 모델이
허용하지 않는 사고 강도는 대체 실행 없이 종료 코드 2로 끝나고, 상태 줄에 `"user_requested": true`가 추가됩니다. `--assignment`와 `--result`를
반복하면 같은 대상의 읽기 전용 할당을 최대 여섯 개 병렬로 실행하고 각각 상태 줄을 출력하며, 실행기는 그중 가장 높은 종료 코드로
끝납니다. 읽기 전용 자식은 호스트의 스킬 목록 없이 실행합니다. Codex에는 `-c skills.max_context_tokens=1`을,
Claude에는 `--disable-slash-commands`를 넘깁니다.
실행기는 역할 규칙을 할당 앞에 붙이고, 고정된 모델·사고 강도·권한으로 실행하며(`codex exec`, Claude 검토 모델은 `claude -p`),
호스트의 rollout 또는 transcript 기록을 확인한 뒤 마지막 줄에 JSON 상태를 출력합니다. `--mcp`가 없으면 Codex 자식에는
`codex mcp list --json`이 보여 주는 서버마다 `-c mcp_servers.<name>.enabled=false`를 넘기고, Claude 자식은
`--strict-mcp-config`를 유지합니다. 편집 가능한 Claude 자식은 `--tools`와 `--allowedTools`에 `Bash`도 받습니다.
가드는 메인 세션이 승인하지 않은 쓰기와 모든 되돌릴 수 없는 작업을 거부합니다.
자식마다 `HEI5ENBUG_PARENT_SESSION`을 넘겨 메인 세션의 승인을 쓰게 합니다. 읽기 전용 Codex 실행 전에는
`codex app-server`에 그 폴더의 훅 목록(`hooks/list`)을 묻습니다. 켜져 있고, 동기 실행이며, 신뢰되었거나 관리형이고,
`Bash`에 맞는 승인 가드 `PreToolUse` 훅이 있어야 하며, 없으면 모델 호출 없이 종료 코드 4로 끝납니다. 실행 뒤에는
rollout에 도구 호출이 기록되어 있으면 `heartbeats/codex-<thread_id>.PreToolUse`를 요구합니다. 쓰기가 가능한 Codex
실행은 먼저 “Run the shell command `true` exactly once, then reply with OK only.”를 보내고, 할당을 보내기 전에 그
하트비트를 요구합니다. 그래서 어떤 쓰기든 실행되기 전에 가드가 도구 호출을 한 번 검사한 상태가 됩니다. 일반 파일이나
`UserPromptSubmit`·`SessionStart` 하트비트로는 두 검사 모두 통과하지 못합니다. Codex의 신뢰는 플러그인 파일 내용도
포함합니다. Codex CLI 0.164.0에서 `README.md`를 포함한 플러그인 파일 하나만 고쳐도 모든 플러그인 훅이 `modified`가
되었으므로, 플러그인을 업데이트할 때마다 Codex는 훅을 건너뜁니다. 그러면 실행기는 위에서 설명한 대로 검증된 공식 설치본에서
이 플러그인의 훅을 다시 신뢰하고 다시 확인하거나 사전 점검을 한 번 더 합니다. 이것이 허용되지 않거나 실패하면
`/hooks`에서 다시 신뢰하기 전까지 `auto_trust`에 이유를 담아 종료 코드 4로 끝납니다. Claude는 플러그인 훅에 신뢰 절차를 적용하지
않으므로 자식의 `heartbeats/claude-<session_id>.UserPromptSubmit` 또는 기존 일반 하트비트를 요구합니다.
필수 하트비트가 없으면 종료 코드 4입니다. 종료 코드 0은 결과가 검증되었다는
뜻이고, 2는 고쳐야 할 사용 오류, 3은 역할을 실행하지 못했다는 뜻, 4는 필수 훅 증거가 없거나 기록된 모델, 사고 강도, 샌드박스가 달라 결과를
폐기했다는 뜻입니다. 3이나 4이면 메인 세션이 해당 역할의 플러그인 에이전트 대체 경로를 씁니다. 독립 검증에는 대체 경로가
없으며, 수행하지 못했다고 보고합니다. `via`가 `agent`인 기능 항목은 실행기가 실행하지 않고 종료 코드 2로 끝나므로, 메인
세션이 그 항목에는 에이전트 경로를 씁니다.

준비된 독립 작업은 호스트 한도와 공통 실행 상한 안에서 함께 수행할 수 있습니다. 역할, 모델, 사고 강도, 사용량,
위임 권한 또는 설정 근거 때문에 위임할 수 없으면 메인이 제한을 알리고, 실행 중인 해당 작업자를 멈춘 뒤 승인된 작업을
이어갑니다. 부분 결과, 사용자 설정, 권한과 수용 검사는 유지하고 작업자 모델을 몰래 바꾸지 않습니다.

요청의 마지막 단계에서 남은 작업이 없으면 메인 세션이 [독립 모델 검증](../../../instructions/independent-model-validation.md)에 따라
합쳐진 결과를 독립 검토 한 번으로 질문 없이 자동 실행합니다. Claude가 작성한 결과는 `gpt-6.1-sol` 또는 `gpt-6-astra`가,
GPT가 작성한 결과는 `claude-opus-5-5` 또는 `claude-fable-5-1`이 검토합니다. 메인 세션은 구성요소 하나로 한정되면 가벼운 모델을
`high`로, 여러 컴포넌트, 공개 계약, 보안, 동시성, 훅이나 가드가 관련되면 더 강한 모델 또는 `xhigh`로 고릅니다.
worker 한 명의 변경 같은 더 이른 검토는 해당 산출물에 대한 사용자의 승인이 필요하며 거절하면 다시 묻지 않습니다.
할당받은 worker와 더 큰 요청 안에서 실행되는 스킬은 자체 최종 검토를 실행하지 않습니다. 검토자를 사용할 수 없거나 역할 실행기가 종료 코드 3이나 4로 끝나면 독립 검증을 수행하지 못한 것이며, 다른
모델로 대체하지 않습니다. 작성자의 일상적인 점검과 검사는 계속 수행합니다.

Codex는 사용자의 직접 요청 또는 적용되는 `AGENTS.md`·스킬 지침이 있어야 서브에이전트를 사용할 수 있습니다.
훅 지침만으로는 권한이 생기지 않으므로 승인이 없으면 메인이 직접 처리합니다.

## 작업 효율

[작업 효율 규칙](../instructions/work-efficiency.ko.md)은 규모 있는 구현 전에만 불러옵니다.
[모델 평가 규칙](../instructions/model-evaluation.ko.md) 은
반복 모델 평가 전에, [실패 및 유지보수 규칙](../instructions/failure-and-maintenance.ko.md)은 플러그인 유지보수나 반복 실행
실패 진단 전에 불러옵니다. 요청한 결과와 필수 검사가 완료 기준입니다. 검사 근거는 관련 입력이 바뀔 때까지 재사용하고,
선택 조사나 수행하지 않은 선택 검토 때문에 수용된 작업을 계속 열어 두지 않습니다.
작업 효율 규칙은 멈춤, 인계, 예상되는 압축에 쓰는 [재개 메모 규칙](../instructions/pause-and-resume.ko.md)과 끝난 세션이 만든
파일에 대한 [정리 제안](../instructions/session-cleanup.ko.md)을 연결합니다. 규모 있는 구현을 하지 않는 세션은 이 규칙을
불러오지 않으므로 재개 메모도 정리 제안도 받지 않습니다.

추가 모델 비교는 대표 사례 최대 3개, 전체 묶음 15분, 두 호스트를 합쳐 비교 실행 시작 최대 6회로 시작합니다.
사전 확인 실행과 재시도도 이 예산에 포함하며, 재개해도 예산을 초기화하지 않습니다. 일반 구현, 단위 테스트,
필수 빌드와 마무리 검토에는 이 상한을 적용하지 않습니다. 확대하려면 남은 질문과 명시적으로 승인된 더 큰 예산이
있어야 합니다.

영구적 실패는 조건이 바뀌어야 다시 시도하고, 일시적 실패는 같은 조건에서 한 번만 재시도합니다.
브라우저 쓰기는 [서비스 접근 규칙](../../../instructions/services.md#browser-ownership)에 따라 실제 공유 제어 자원마다
한 담당자가 맡습니다. 이 지침은 에이전트 판단을 안내하며, 모든 실행의 준수나 시간·토큰 절감 효과를 입증하지는 않습니다.

## 지침 언어

플러그인 스킬, 참조, 에이전트와 세션 지침은 영어 파일을 실행 가능한 기준 원본으로 사용합니다.
사람이 읽는 모든 영어 Markdown 파일에는 의미가 같은 `.ko.md` 번역본을 `docs/ko/` 아래에 둡니다.
번역본 경로는 저장소 루트 기준 원본 경로를 따릅니다.
번역본은 영어 원본을 연결하고 비권위 자료임을 밝히며 에이전트 실행 중 읽거나 사용하지 않습니다.
원본과 번역본은 함께 수정, 이동 또는 삭제합니다.

코드, 스키마, 테스트 자료, 생성 아티팩트와 영어가 아닌 문서는 한국어 복사본을 만들지 않습니다.
호출 문구, 예시, 필수 출력 이름 또는 평가 자료처럼 한국어 자체가 대상 데이터일 때만 영어 실행 파일에
한국어를 유지할 수 있습니다. 자동 검사는 번역본 존재와 실행 경로 분리를 확인하고 의미 일치는 사람이나
모델이 별도로 검토합니다.

## 에이전트 등록

`agents/` 디렉터리는 Claude Code 플러그인에 함께 배포되므로, 번들을 설치하면
`hei5enbug-agent-setup:scout`, `hei5enbug-agent-setup:worker`, `hei5enbug-agent-setup:sonnet-worker`,
`hei5enbug-agent-setup:designer`, `hei5enbug-agent-setup:reviewer`가 추가됩니다.
직접 복사할 필요가 없습니다. 매니페스트에는 영어 정의 다섯 개만 있으므로 `docs/ko/`의 한국어 번역본은
서브에이전트로 등록되지 않습니다.

Codex는 `~/.codex/agents/`와 `.codex/agents/`에서만 서브에이전트를 찾으므로 플러그인이 등록할 수 없습니다.
대신 세션 훅이 `standalone-agents/codex-scout.toml`, `codex-worker.toml`, `codex-designer.toml`,
`codex-reviewer.toml`을 대응하는 `~/.codex/agents/<role>.toml`이 없을 때만 복사합니다.
네 파일은 Claude Code에도 있는 역할을 정의하며 샌드박스를 고정합니다. 역할 파일은 사고 강도를 지정하지 않으므로
생성할 때마다 넘깁니다. Codex `reviewer` 역할에는
모델 키가 없으며, 스킬 지침은 대체 경로에서 모델과 사고 강도를 명시합니다. 플러그인 `worker`는
Codex 내장 `worker`를 대신하고, `scout`는 내장 `explorer`를 건드리지 않습니다. 직접 고친 파일은 절대 덮어쓰지 않으며,
다음 Codex 세션부터 적용됩니다. 고친 파일은 바뀌지 않으므로 모델은 지정하지 않고, Codex 지침이 생성할 때마다
고정 모델을 넘깁니다. `worker` 역할 파일은 사고 강도도 지정하지 않으므로 생성할 때 `codex_worker_model`과
`codex_worker_effort` 설정을 넘깁니다. 다른 쌍을 고정한 채 고친 역할 파일이 우선하며, 에이전트 가드는 맞지 않는 생성을 거부합니다.
훅은 이전 버전이 만든 `explorer.toml`과 `researcher.toml`을 지우고 `worker.toml`, `scout.toml`,
`designer.toml`, `reviewer.toml`을 바꾸지만, 그 버전에서 배포한
파일과 바이트 단위로 같을 때만 그렇게 하므로 직접 고친 파일은 남습니다. 플러그인을 끄면 설치된 `worker` 역할은
수정을 거부하지 않고 일반 구현 worker로 동작합니다.

두 호스트 모두 내장 서브에이전트를 막습니다. Claude Code에서는 mod가 내장 `general-purpose`, `Explore`, `Plan`,
`claude` 에이전트를 에이전트 목록에서 숨기고(`agent.offer`), 이들과 모든 fork를 거부합니다(`agent.spawn`). 목적이 좁은
내장 종류인 `claude-code-guide`와 `statusline-setup`은 플러그인 에이전트, 사용자·프로젝트·CLI·관리 설정이 제공하는 정의와
함께 통과합니다. Codex에서는 `PreToolUse` 훅인 `scripts/agent_guard.py`가 기존 동작을 그대로 유지합니다. 종류를 비운 호출,
`default`, `explorer`, 역할 파일이 없는 모든 종류를 거부하며, 플러그인 역할이 생기기 전의 내장
`worker`도 여기에 포함됩니다. 독립된 읽기 전용 작업자가 필요한 스킬은 실제 모델·사고 강도·도구가 스킬 계약과
일치하는 역할을 사용합니다. `scout`는 로컬 근거 조사 티켓을 포함해 범위가 제한된 로컬 조사 하나를 맡고, 웹 검색과 가져오기 도구로 범위가 정해진 공개 조사 질문 하나도 맡습니다. 스킬 검토 역할은 먼저
설정한 검토 모델을 사용하고 그 실행기를 쓸 수 없으면
`reviewer`로 대체합니다. reviewer는 결과만 반환하며 메인 세션이 같은 자료를 한 번 검토해 판단합니다. 시험 출력을 쓰는
스킬은 필요한 경우 검증된 평가 실행기를 사용합니다.
조건부 [모델 라우팅 계약](../../../instructions/model-routing.md)을 참고하세요.
