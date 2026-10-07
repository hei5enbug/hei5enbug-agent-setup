# hei5enbug-agent-setup

> 영어 원본: [README.md](README.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

내 작업 환경을 위한 개인용 에이전트 하네스입니다. Claude Code와 Codex용 스킬, 세션 지침, 가드 훅으로 이루어져 있습니다.

## 개요

플러그인 스킬은 `skills/` 아래 자신의 폴더에 지침·참조 문서·스크립트를 함께 둡니다.
같은 `SKILL.md`가 지원하는 모든 호스트에서 수정 없이 작동합니다.

## 지원 호스트

- Claude Code
- Codex

OpenCode 설정은 참고 소스로만 유지합니다. 이 플러그인은 OpenCode를 설치·유지·실행하지 않습니다.

## 구조

```
hei5enbug-agent-setup/
├── .agents/plugins/marketplace.json
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── .codex-plugin/plugin.json
├── .github/workflows/validate.yml
├── AGENTS.md
├── AGENTS.ko.md
├── CLAUDE.md
├── CLAUDE.ko.md
├── hooks/hooks.json
├── hooks/mod/
├── config/claude-mod.json
├── instructions/
│   ├── claude-agents.md
│   ├── codex-agents.md
│   ├── confluence.md
│   ├── documentation.md
│   ├── implementation-execution.md
│   ├── implementation-planning.md
│   ├── independent-model-validation.md
│   ├── model-routing.md
│   ├── protected-values.md
│   ├── services.md
│   └── session/
│       ├── claude-code.md
│       ├── codex.md
│       └── common.md
├── scripts/
│   ├── agent_guard.py
│   ├── datagrip_guard.py
│   ├── language_guard.py
│   ├── plugin_toggles.py
│   └── session_context.py
├── tests/
├── LICENSE
├── pyproject.toml
├── agents/
│   ├── ko/
│   │   ├── designer.ko.md
│   │   ├── researcher.ko.md
│   │   ├── scout.ko.md
│   │   └── worker.ko.md
│   ├── designer.md
│   ├── researcher.md
│   ├── scout.md
│   └── worker.md
├── standalone-agents/
│   ├── codex-designer.toml
│   ├── codex-researcher.toml
│   ├── codex-scout.toml
│   └── codex-worker.toml
└── skills/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── docs-rewrite/
    ├── document-to-confluence/
    ├── orca-plugin-refresh/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

각 플러그인 스킬 폴더는 자신의 `SKILL.md`와 필요한 참조 문서·스크립트를 담고 있습니다.
플러그인 매니페스트는 호스트별 디렉터리에 스킬을 복사하지 않고 같은 `skills/` 디렉터리를
Codex와 Claude Code에 패키징합니다.

`agents/` 디렉터리는 Claude Code 플러그인에 함께 배포되므로, 번들을 설치하면
`hei5enbug-agent-setup:scout`, `hei5enbug-agent-setup:worker`, `hei5enbug-agent-setup:researcher`,
`hei5enbug-agent-setup:designer`가 추가됩니다.
직접 복사할 필요가 없습니다. 매니페스트는 네 영어 정의만 나열하므로 `agents/ko/`의 한국어 번역본은 등록되지 않습니다.

Codex는 `~/.codex/agents/`와 `.codex/agents/`에서만 서브에이전트를 찾으므로 플러그인이 등록할 수 없습니다.
대신 세션 훅이 `standalone-agents/codex-scout.toml`, `codex-worker.toml`, `codex-researcher.toml`,
`codex-designer.toml`을 각각 대응하는 `~/.codex/agents/<role>.toml`이 없을 때만 복사합니다. 네 파일은 Claude Code와
같은 이름의 `scout`, `worker`, `researcher`, `designer`를 정의하고 사고 강도와 샌드박스를 고정합니다. 플러그인 `worker`는
Codex 내장 `worker`를 대신하고, `scout`는 내장 `explorer`를 건드리지 않습니다. 직접 고친 파일은 절대 덮어쓰지 않으며,
다음 Codex 세션부터 적용됩니다. 고친 파일은 바뀌지 않으므로 모델은 지정하지 않고, Codex 지침이 생성할 때마다
고정 모델을 넘깁니다. 훅은 이전 버전이 만든 `explorer.toml`을 지우고 `worker.toml`을 바꾸지만, 그 버전에서 배포한
파일과 바이트 단위로 같을 때만 그렇게 하므로 직접 고친 파일은 남습니다. 플러그인을 끄면 설치된 `worker` 역할은
수정을 거부하지 않고 일반 구현 worker로 동작합니다.

두 호스트 모두 내장 서브에이전트를 막습니다. Claude Code에서는 mod가 내장 `general-purpose`, `Explore`, `Plan`,
`claude` 에이전트를 에이전트 목록에서 숨기고(`agent.offer`), 이들과 모든 fork를 거부합니다(`agent.spawn`). 목적이 좁은
내장 종류인 `claude-code-guide`와 `statusline-setup`은 플러그인 에이전트, 사용자·프로젝트·CLI·관리 설정이 제공하는 정의와
함께 통과합니다. Codex에서는 `PreToolUse` 훅인 `scripts/agent_guard.py`가 기존 동작을 그대로 유지합니다. 종류를 비운 호출,
`default`, `explorer`, 역할 파일이 없는 모든 종류를 거부하며, 플러그인 역할이 생기기 전의 내장
`worker`도 여기에 포함됩니다. 독립된 읽기 전용 작업자가 필요한 스킬은 실제 모델·사고 강도·도구가 스킬 계약과
일치하는 역할을 사용합니다. 로컬 근거는 `scout`, 공개 근거는 `researcher`에 맡길 수 있습니다.
시험 출력을 쓰는 스킬은 필요한 경우 검증된 평가 실행기를 사용합니다.
조건부 [모델 라우팅 계약](instructions/model-routing.md)을 참고하세요.

### Claude Code mod

Claude Code에서는 `config/claude-mod.json`이 mod `hooks/mod/register.js`를 불러옵니다. 이 mod가 Claude 전용 가드인
내장 서브에이전트 차단, 역할 고정, 세션 승인, GPT 거부를 담당합니다. Claude Code 2.1.292에서 시험했습니다.
오래된 Claude Code, `disableAllHooks`, 관리 정책 등으로 mod가 로드되지 않으면 이 가드들은 동작하지 않고 호스트의 기본 권한
흐름이 적용됩니다.

역할 고정은 플러그인 역할마다 모델과 사고 강도를 모든 요청에 고정합니다. `scout`와 `researcher`는 `claude-sonnet-5-5`,
`medium`, `worker`는 `claude-sonnet-5-5`, `high`, `designer`는 `claude-opus-5-5`, `xhigh`입니다. 다른 모델로 응답한
서브에이전트는 중단됩니다. 이후 요청은 거부 응답으로 끝나고, 도구 호출은 거부되며, 결과는 경고로 바뀝니다. 이때 세션
컨텍스트에 `hei5enbug-agent-setup mod: role pinning active` 줄이 들어가며, 메인 세션은 이를 보고 작업 지시를 바로 보냅니다.

### Claude Code에서 GPT 사용

mod는 고정한 GPT 모델로 가는 요청을 추론 전에 거부합니다. 이 거부는 항상 켜져 있으며 토글이 없습니다.
Claude Code의 mod API가 도구 입력 스키마를 제공하지 않아 아직 이 경로를 쓸 수 없습니다.
헬퍼, 테스트, 설계 기록은 `gpt-route` 브랜치에 보존되어 있습니다.

### 응답 언어

언어 가드인 `scripts/language_guard.py`는 모든 답변과 진행 상황 안내가 응답 언어로 작성되었는지 확인합니다.
Claude Code는 `language` 설정에서 언어를 가져오며, 로컬 프로젝트 설정, 프로젝트 설정, 사용자 설정 순서로 읽습니다.
설정이 없으면 아무것도 강제하지 않습니다. Codex는 `HEI5ENBUG_RESPONSE_LANGUAGE`를 읽고, 설정하지 않으면 한국어를
사용합니다. 고유한 문자 체계가 있는 언어만 검사합니다. 한국어, 일본어, 중국어, 러시아어, 우크라이나어, 그리스어,
아랍어, 히브리어, 태국어, 힌디어입니다. 영어나 프랑스어 같은 다른 언어에는 지침만 적용됩니다.

검사는 코드, 인용, URL을 제외합니다. 글자 중 대상 문자 체계의 비율이 30% 이상이면 통과하며, 아주 짧은 글은 항상
통과합니다. 답변이 통과하지 못하면 `Stop` 훅이 다시 쓰도록 요청하며, 한 턴에 최대 3번까지 요청합니다.
다른 언어로 쓴 진행 상황 안내가 나오면 `PostToolUse` 훅이 알림을 추가합니다. 사용자가 다른 언어로 요청한 글은
코드 블록이나 인용 블록에 넣습니다.

### DataGrip 쿼리 가드

`PreToolUse` 훅과 `PermissionRequest` 훅인 `scripts/datagrip_guard.py`는 DataGrip MCP 도구 `execute_sql_query` 실행 전에 동작합니다.
가드는 `projectPath`가 가리키는 DataGrip 프로젝트의 `.idea/dataSources.xml`에서 연결 정보를 읽습니다. 이름에 `승인`이 들어간 연결은 항상 승인을 요청합니다.
PostgreSQL과 SQL Server의 읽기 쿼리는 승인 없이 실행되며, PostgreSQL 읽기 쿼리는 읽기 전용 트랜잭션 안에서 실행됩니다. 쓰기 쿼리, 가드가 분류하지 못한 쿼리, 알 수 없는 연결, 그
밖의 데이터베이스 종류는 항상 승인을 요청합니다. 가드는 호출을 거부하지 않습니다. Codex에서는 `/hooks`에서 이 훅을 신뢰해야 합니다.

선택 사항으로 `pglast` 파서를 한 번 설치할 수 있습니다.

```bash
uv venv --python 3.12 "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser"
uv pip install --python "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser/bin/python" pglast==8.4
```

파서가 없으면 PostgreSQL은 더 엄격한 텍스트 검사로 대체합니다. 이 검사는 승인을 더 자주 요청할 수 있지만, 승인 없이 쓰기가 실행되는 일은 여전히 없습니다.

### 세션 승인

Claude Code에서만 동작하는 mod가 외부로 나가는 특정 쓰기 작업을 세션마다 한 번만 승인하게 합니다. Bash와 MCP 도구를 호출할 때마다
`tool.check` 훅이 작업을 분류하고, 대상 종류가 그 세션에서 처음 실행될 때만 승인을 요청합니다. 호출이 성공하면 `tool.call` 훅이 승인된 종류를 세션 ID별로 mod 저장소(`$.store`)에
기록하므로, 그 세션에서 같은 종류의 작업은 이후 확인 없이 실행됩니다. git 태그 생성, 설정된
원격 저장소로의 태그 푸시, 태그와 플래그 `--title`, `--notes`, `--target`, `--generate-notes`, `--notes-from-tag`, `--latest`,
`--draft`, `--prerelease`, `--verify-tag`만 쓴 `gh release create`와 `gh release edit`, 이름에 쓰기 동사가 들어간 MCP 도구가 대상입니다. 이름이
get, list, search, read, fetch, query, download 같은 읽기 동사로 시작하는 MCP 도구는 대상이 아니며 기존 권한 절차를 그대로 따릅니다. DataGrip 쿼리
도구도 DataGrip 쿼리 가드가 처리하므로 마찬가지입니다. 도구나 명령 종류별로 따로 승인합니다.

되돌릴 수 없는 작업은 항상 승인을 요청합니다. 강제 푸시, 원격 브랜치나 태그 삭제, 태그 삭제, `gh release delete`, `gh repo delete`, 삭제·휴지통 이동·제거를 하는 MCP
도구가 여기에 해당하며, 이름이 읽기 동사로 시작해도 마찬가지입니다. `gh release upload`는 로컬 파일을 무엇이든 게시할 수 있으므로 항상 승인을 요청합니다. URL, 목록에 없는 원격 저장소,
`--repo`로 보내는 태그 푸시나 `--tags` 푸시에 브랜치가 섞인 경우, 첨부 파일·`--notes-file`·그 밖의 플래그가 붙은 `gh release create`와
`gh release edit`도 마찬가지입니다. mod가 확인할 수 없는 부분이 하나라도 있는 복합 명령도 항상 승인을 요청합니다. 대상 명령 뒤에 `git tag v1 && echo done`처럼 리터럴
텍스트만 쓴 단순 `echo`는 승인 적용을 막지 않습니다. 변수, 명령 치환, glob, 리다이렉트, 파이프가 있는 `echo`는 여전히 승인을 요청합니다. 서브에이전트는 승인을 물려받지 않습니다. 승인은
한 세션에만 속하며, mod는 7일이 지난 저장 항목을 지웁니다. 일반 푸시와 그 밖의 명령은 기존 권한 절차를 그대로 따릅니다.

이 작업들에 `permissions.ask` 규칙을 추가하지 마세요. ask 규칙은 세션 승인 뒤에도 매번 확인을 요청합니다.

## 기능 토글

끌 수 있는 기능은 일곱 가지이며 기본값은 모두 켜짐입니다. Claude Code에서는 `/config`나 `claude plugin configure`로 플러그인 옵션을
설정합니다. Codex에서는 세션을 시작하기 전에 환경변수를 설정합니다. 값이 `false`, `0`, `off`, `no`(대소문자 무시)이면 기능이 꺼집니다.

| 기능 | Claude Code `/config` 키 | Codex 환경변수 |
|---|---|---|
| 내장 서브에이전트 차단 | `agent_guard` | `HEI5ENBUG_AGENT_GUARD` |
| 세션 1회 승인 | `session_approval` | 해당 없음 |
| 역할 모델 고정 | `role_pinning` | 해당 없음 |
| 응답 언어 가드 | `language_guard` | `HEI5ENBUG_LANGUAGE_GUARD` |
| DataGrip 쿼리 가드 | `datagrip_guard` | `HEI5ENBUG_DATAGRIP_GUARD` |
| `~/.codex/AGENTS.md`의 서브에이전트 허용 블록 | 해당 없음 | `HEI5ENBUG_SUBAGENT_POLICY` |
| 질문 기능 플래그 | 해당 없음 | `HEI5ENBUG_CODEX_ASK_TOOL` |

GPT 거부는 항상 켜져 있습니다. 세션 지침과 운영 규칙에는 토글이 없으며, 끄려면 플러그인 자체를 비활성화합니다.

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

## 지침 자동 적용

macOS와 Linux에서 플러그인 훅은 `instructions/session/common.md`와 현재 호스트의 지침을 합친다.
Codex에는 `codex.md`, Claude Code에는 `claude-code.md`를 사용한다.
호스트의 `PATH`에서 `python3`로 Python 3.12 이상을 실행할 수 있어야 한다.
훅은 Python 표준 라이브러리만 사용한다.
루트 `AGENTS.md`와 `CLAUDE.md`는 이 저장소 개발에만 적용하며 훅은 두 파일을 읽지 않는다.

두 호스트 모두 `hooks/hooks.json`을 자동으로 찾는다.
Codex가 제공하는 `PLUGIN_ROOT`가 설치 디렉터리를 가리키면 로더는 Codex 지침을 선택한다.
스크립트 위치는 두 호스트가 제공하는 `CLAUDE_PLUGIN_ROOT`로 찾는다.
사용자 전역 지침 파일이나 작업 저장소의 지침 파일은 복사하거나 덮어쓰지 않는다.

| 시점 | 동작 |
|---|---|
| 세션 시작·재개 | `SessionStart`가 설치된 지침 파일을 전달한다. Orca 터미널에서는 플러그인 디렉터리와 지침 요약값을 담은 표식도 남긴다. |
| 세션 초기화·컨텍스트 압축 | `SessionStart`가 지침을 다시 전달한다. |
| 서브에이전트 시작 | `SubagentStart`가 같은 호스트의 지침을 전달한다. |
| 도구 호출 종료 | 진행 상황 안내가 다른 언어로 쓰였으면 `PostToolUse`가 언어 알림을 추가한다. |
| 답변 종료 | 답변이 응답 언어로 쓰이지 않았으면 `Stop`이 다시 쓰도록 요청한다. |
| DataGrip 쿼리 실행 직전 | `PreToolUse`와 `PermissionRequest`가 `execute_sql_query` 실행 전에 DataGrip 쿼리 가드를 실행한다. |
| Bash 또는 MCP 도구 호출 실행 | Claude Code에서는 mod의 `tool.check`와 `tool.call` 훅이 Bash와 MCP 도구에 세션 승인을 적용한다. |
| 조건에 맞는 작업 시작 | 에이전트가 `instructions/`의 필수 참조를 읽는다. |
| 플러그인 업데이트 설치 | 새 세션이 설치된 버전을 읽는다. 저장소에 푸시하는 것만으로는 반영되지 않는다. |

핵심 규칙은 요청이 바뀌어도 세션 컨텍스트에 남는다.
서비스 접근, 보호된 보안 값 접근, 에이전트 사용, 문서 작성, 구현 실행의 세부 규칙은 관련 작업 전에만 읽는다.
요청을 처리하던 중 관련 작업이 생겨도 먼저 참조를 읽는다.
세션 컨텍스트는 구현 계획과 설계 문서를 구분하고 두 작업의 실행 조건을 유지한다.
`instructions/implementation-planning.md`는 구현 계획의 6단계 절차와 템플릿을 관리한다.
`technical-design-writer`는 설계 문서와 RFC를 담당한다.
`instructions/independent-model-validation.md`는 두 결과물에 공통으로 적용되는 독립 검증 규칙을 관리한다.
로더는 각 세션 지침의 조건부 링크를 설치된 플러그인 내부의 절대 경로로 바꾼다.
세션을 시작할 때 조건부 참조 본문까지 읽지는 않는다.

Codex는 현재 플러그인 훅 정의를 사용자가 검토하고 신뢰한 뒤에 실행한다.
훅이 꺼져 있거나 조직 정책이 플러그인 훅을 금지하면 자동 적용되지 않는다.
설치·업데이트 후 호스트의 훅 설정에서 활성화 여부를 확인하고, Codex에서는 신뢰 여부도 확인한다.
에이전트 차단 훅, 언어 가드, DataGrip 쿼리 가드처럼 업데이트가 새로 추가하거나 바꾼 훅은 Codex의 `/hooks`에서 신뢰하기 전까지 건너뛴다.
이번 릴리스에서 `hooks/hooks.json`이 바뀌었으므로 업데이트 후 그 훅을 다시 신뢰해야 한다.
Claude Code mod는 Codex 훅이 아니므로 이 신뢰 절차가 적용되지 않는다.
업데이트 후에는 Claude Code를 재시작하거나 Codex에서 새 세션을 시작한다.
훅은 호스트의 신뢰 설정을 우회하지 않으며, 실행 중인 세션의 플러그인 버전을 바꾸지 않는다.
`orca-plugin-refresh` 스킬은 이 표식으로 실행 중인 Orca 세션에 업데이트를 재시작 없이 반영한다.

세션 지침 누락·빈 파일·잘못된 로컬 참조나 9,000 UTF-8 바이트를 넘는 컨텍스트는 표준 오류로 알린다.
이때 지침 일부만 전달하지 않는다.
세션 시작 훅의 오류가 호스트 실행을 반드시 중단시키지는 않으므로, 오류를 해결한 뒤 자동 적용을 사용한다.
세션 지침 파일은 짧게 유지하고 세부 사항은 조건부 참조로 옮긴다.
Windows 실행과 실제 모델의 지침 준수 여부는 테스트 범위에 포함하지 않는다.

실행 시점과 신뢰 설정은 공식 [Codex 훅 문서](https://learn.chatgpt.com/docs/hooks)와
[Claude Code 훅 문서](https://code.claude.com/docs/en/hooks)를 따른다.

## 상황별 위임

메인 세션은 [공통 지침](instructions/session/common.md)에 따라 직접 처리할지 위임할지 판단합니다.
작은 수정과 알려진 경로 조회는 메인이 처리합니다. 범위가 한정된 조사, 많은 근거 수집, 독립적으로 수행할 수 있는
규모 있는 구현은 예상 이득이 조정 비용보다 클 때 작업자를 사용합니다. 의존성이 긴밀한 작업은 한 담당자가 이어서 처리합니다.
모든 작업에서 실제 비용이 줄어든다고 보장하는 정책은 아닙니다.

메인은 요구사항, 설계, 작업 경계, 수용 판단과 최종 보고를 맡습니다.
[구현 실행 규칙](instructions/implementation-execution.md)은 담당 범위, 충돌 없는 일정, 검사와 복구를 정의합니다.
직접 작업은 메인의 현재 모델과 사고 강도를 유지합니다. 위임할 때는 작업 범위, 필요한 맥락, 허용·보호 경로,
선행 조건, 수용 검사와 호스트의 고정 설정만 전달합니다. 작업자는 하위 에이전트를 만들 수 없습니다.

UI 코드, 시각 디자인, 다이어그램 작업은 대신 호스트의 designer 경로로 보냅니다. 레이아웃과 컴포넌트 구조를 바꾸지 않는
문구·스타일 값 수정은 구현 worker가 맡을 수 있고, 설계 문서와 RFC는 메인 세션이 맡습니다.

| 호스트 | 구현 에이전트 | 모델과 사고 강도 |
|---|---|---|
| Codex | rollout 기록으로 검증한 플러그인 `worker` 역할 | `gpt-6-luna`, `xhigh` |
| Claude Code | 서브에이전트 기록으로 검증한 `hei5enbug-agent-setup:worker` | `claude-sonnet-5-5`, `high` |
| Codex, designer | 고정 모델의 `claude -p`, Claude를 쓸 수 없으면 플러그인 `designer` 역할 | `claude-opus-5-5`, `xhigh`, 대체 시 `gpt-6-astra`, `xhigh` |
| Claude Code, designer | 서브에이전트 기록으로 검증한 `hei5enbug-agent-setup:designer` | `claude-opus-5-5`, `xhigh` |

준비된 독립 작업은 호스트 한도와 공통 실행 상한 안에서 함께 수행할 수 있습니다. 역할, 모델, 사고 강도, 사용량,
위임 권한 또는 설정 근거 때문에 위임할 수 없으면 메인이 제한을 알리고, 실행 중인 해당 작업자를 멈춘 뒤 승인된 작업을
이어갑니다. 부분 결과, 사용자 설정, 권한과 수용 검사는 유지하고 작업자 모델을 몰래 바꾸지 않습니다.

중요한 변경과 검사를 마치면 [독립 모델 검증](instructions/independent-model-validation.md)에 따라 다른 계열 모델의
선택적 검토를 한 번 추천합니다. 양쪽 검토자 매핑 모두 `xhigh`를 사용합니다. 해당 결과에 대한 승인이 필요하며 거절하면
다시 묻지 않습니다. 검토자를 사용할 수 없어도 나머지 작업을 막지 않습니다. 작성자의 일상적인 점검과 검사는 계속 수행합니다.

Codex는 사용자의 직접 요청 또는 적용되는 `AGENTS.md`·스킬 지침이 있어야 서브에이전트를 사용할 수 있습니다.
훅 지침만으로는 권한이 생기지 않으므로 승인이 없으면 메인이 직접 처리합니다.

### Codex 자동 설정

Codex에서는 세션 훅이 두 설정을 관리하며, 두 설정 모두 다음 세션부터 적용됩니다. 훅은 아래 표시 블록을
`~/.codex/AGENTS.md` 끝에 유지하고, 파일이 없으면 만듭니다.

```text
<!-- hei5enbug:subagents -->
When hei5enbug-agent-setup is active, use subagents according to its situation-based delegation rules.
<!-- /hei5enbug:subagents -->
```

또한 `codex features list`에서 `default_mode_request_user_input` 기능이 꺼져 있으면 켜므로, Default 모드에서도
`request_user_input`을 쓸 수 있습니다. `HEI5ENBUG_SUBAGENT_POLICY=off`로 설정하면 표시 블록만 지우고 블록 밖은 절대 고치지
않습니다. `HEI5ENBUG_CODEX_ASK_TOOL=off`로 설정하면 기능을 다시 끄지만, 플러그인이 켠 경우에만 끄며 직접 켠 기능은 그대로
둡니다. 실패한 단계는 다음 세션 시작 때 다시 시도하며, 세션 지침 로드를 막지 않습니다. 실제 실행에는 호스트 규칙, 훅 신뢰와
사용 가능한 도구가 계속 적용됩니다.
[공식 Codex 서브에이전트 계약](https://learn.chatgpt.com/docs/agent-configuration/subagents)과
[평가 결론](docs/subagent-policy-decision.ko.md)을 참고하세요.

## 작업 효율

[작업 효율 규칙](instructions/work-efficiency.md)은 규모 있는 구현, 반복 모델 평가, 플러그인 유지보수 또는
반복 실행 실패 진단 전에만 불러옵니다. 요청한 결과와 필수 검사가 완료 기준입니다. 검사 근거는 관련 입력이
바뀔 때까지 재사용하고, 선택 조사나 수행하지 않은 선택 검토 때문에 수용된 작업을 계속 열어 두지 않습니다.

추가 모델 비교는 대표 사례 최대 3개, 전체 묶음 15분, 두 호스트를 합쳐 비교 실행 시작 최대 6회로 시작합니다.
사전 확인 실행과 재시도도 이 예산에 포함하며, 재개해도 예산을 초기화하지 않습니다. 일반 구현, 단위 테스트,
필수 빌드와 마무리 검토에는 이 상한을 적용하지 않습니다. 확대하려면 남은 질문과 명시적으로 승인된 더 큰 예산이
있어야 합니다.

영구적 실패는 조건이 바뀌어야 다시 시도하고, 일시적 실패는 같은 조건에서 한 번만 재시도합니다.
브라우저 쓰기는 [서비스 접근 규칙](instructions/services.md#browser-ownership)에 따라 실제 공유 제어 자원마다
한 담당자가 맡습니다. 이 지침은 에이전트 판단을 안내하며, 모든 실행의 준수나 시간·토큰 절감 효과를 입증하지는 않습니다.

## 플러그인 업데이트

두 플러그인 매니페스트, `pyproject.toml`, `uv.lock`은 같은 의미적 버전을 사용해야 합니다.
`HEAD`에서 닿는 가장 새로운 `v<version>` 태그가 릴리스 기준입니다. 기준 이후 첫 변경이 같은 커밋에서 이 파일들의
다음 버전을 정합니다. 이 파일들에만 있는 버전은 이미 `main`에 있더라도 계획한 다음 버전이므로, 다시 올리지 말고
이후에 배포되지 않은 변경을 모두 그 버전에 모읍니다. 릴리스에는 커밋을 추가하지 않습니다. `HEAD`에서 아래 개발
검사를 모두 통과시킨 뒤 `HEAD`에 `v<version>` 태그를 달고 태그를 푸시합니다.

릴리스가 배포되면 영향을 받는 코딩 에이전트 세션을 끝내고 일반 터미널에서 업데이트합니다.
로드된 플러그인 디렉터리를 교체하면 실행 중인 세션이 참조하는 훅 경로가 사라질 수 있습니다.

Codex를 업데이트합니다.

```bash
codex plugin marketplace upgrade hei5enbug
codex plugin add hei5enbug-agent-setup@hei5enbug
```

Claude Code를 업데이트합니다.

```bash
claude plugin marketplace update hei5enbug
claude plugin update hei5enbug-agent-setup@hei5enbug
```

업데이트한 스킬과 지침을 불러오려면 새 Codex 스레드를 시작하거나
Claude Code를 다시 시작합니다.

### 실행 중인 Orca 세션에 업데이트 반영

`orca-plugin-refresh`를 요청하면 이미 설치된 버전을 Orca가 관리하는 대기 세션에 재시작 없이 반영합니다.
이 스킬은 요청할 때만 실행됩니다. `apply-installed --json`은 설치 경로를 검증하고
`apply --run-id <run_id> --json`에 넘길 실행 ID를 만듭니다. 마켓플레이스나 설치 명령은 실행하지 않습니다.

캐시를 교체하는 업데이트는 별도의 오프라인 단계입니다. 기본 `update --json`은 보류하며,
`update --offline --json`은 영향을 받는 코딩 에이전트 세션이 끝난 뒤 일반 터미널에서 실행합니다.
활성 호스트·플러그인 환경이나 연결된 코딩 에이전트 터미널이 있으면 오프라인 확인과 모순되므로 계속 차단합니다.
사용 가능한 인벤토리를 읽을 수 없거나, 목록이 잘리거나, 지원하지 않는 형식이어도 보류합니다.
결과는 호스트별 상태를 보존하고 현재 설치 경로와 오프라인 복구 명령을 제공합니다. 보류된 호스트는 건드리지 않습니다.
Orca 인벤토리는 Orca 밖 세션의 종료를 입증할 수 없습니다. 직접 업데이트하거나 다른 프로세스가 로드된 디렉터리를
삭제하는 상황은 이 보호 범위 밖입니다. 명령과 한계는 [새로고침 절차](skills/orca-plugin-refresh/SKILL.ko.md)를 참고하세요.

| 부분 | Claude Code | Codex |
|---|---|---|
| 스킬, 에이전트, 훅 | 스킬이 `/reload-plugins`를 보냄 | 설치 후 다음 턴에 자동으로 반영 |
| 세션 지침 | 지침이 오래됐으면 스킬이 `/compact`를 보냄 | 지침이 오래됐으면 스킬이 `/compact`를 보내고, 세션은 다음 턴에 불러옴 |

스킬은 세션 시작 표식으로 지침이 오래됐는지 판단합니다. 표식이 없거나, 요약값이 다르거나, 교체되거나 지워진
플러그인 디렉터리를 가리키면 오래된 것으로 봅니다. 명령은 대기 상태이면서 입력 줄이 빈 터미널에만 보내고, 결과를
세션 대화 기록이나 화면으로 모두 확인합니다. Claude Code 세션에서는 흐린 추천 문구와 직접 친 글을 구별하려고 한
글자를 입력했다가 지울 수 있으며, 직접 친 글이 있는 세션에는 명령을 보내지 않습니다. 작업 중인 세션은 시간 예산이 끝날 때까지 다시 시도하고, 그래도 안 되면 건너뛴 것으로 보고합니다.
스킬을 실행한 세션은 턴이 끝난 뒤 분리된 도우미가 마지막에 처리합니다. Orca 밖 세션은 `/reload-plugins`나
`/compact`를 직접 실행해야 합니다. macOS와 Linux의 `hei5enbug` 마켓플레이스 사용자 범위 설치를 지원합니다.

## 개발 검사

번들 스크립트에는 Python 3.12 이상과 PyYAML이 필요하고, Node 테스트에는 Node.js가 필요합니다. mod 테스트와 플러그인 검증에는
Claude Code CLI가 필요하며 CI는 2.1.292 버전을 씁니다. `.github/workflows/validate.yml`이 macOS와 Linux에서 실행하는 검사와
플러그인 검증을 실행합니다.

```bash
python3 -m pip install -e ".[dev]"
for skill in skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$skill"; done
python3 -m pytest
node --test skills/document-to-confluence/tests/test_render_diagrams.mjs
claude plugin validate .
claude plugin test .
```

Orca CLI가 필요한 테스트는 Orca가 설치되어 있지 않으면 건너뛰므로 CI는 Orca 없이도 통과합니다. Orca를 설치한 뒤
`python3 -m pytest`를 다시 실행하면 이 테스트까지 확인합니다.

## 지침 언어

플러그인 스킬, 참조, 에이전트와 세션 지침은 영어 파일을 실행 가능한 기준 원본으로 사용합니다.
사람이 읽는 모든 영어 Markdown 파일에는 의미가 같은 `.ko.md` 번역본을 같은 위치에 둡니다.
번역본은 영어 원본을 연결하고 비권위 자료임을 밝히며 에이전트 실행 중 읽거나 사용하지 않습니다.
원본과 번역본은 함께 수정, 이동 또는 삭제합니다.

코드, 스키마, 테스트 자료, 생성 아티팩트와 영어가 아닌 문서는 한국어 복사본을 만들지 않습니다.
호출 문구, 예시, 필수 출력 이름 또는 평가 자료처럼 한국어 자체가 대상 데이터일 때만 영어 실행 파일에
한국어를 유지할 수 있습니다. 자동 검사는 번역본 존재와 실행 경로 분리를 확인하고 의미 일치는 사람이나
모델이 별도로 검토합니다.

## 스킬 목록

| 스킬 | 하는 일 |
|---|---|
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | 여러 세션에 걸친 작업을 의사 결정 티켓으로 나누고, 구현 경로가 분명해질 때까지 티켓을 하나씩 해결합니다. [한국어 안내](skills/decision-navigator/SKILL.ko.md) |
| [`deep-interview`](skills/deep-interview/SKILL.md) | 답변마다 요구사항의 모호함 정도를 점수로 측정하는 소크라테스식 인터뷰를 진행하며, 그 점수가 기준값 이하로 내려가기 전에는 실행 단계로 넘어가지 않습니다. [한국어 안내](skills/deep-interview/SKILL.ko.md) |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | SVG, HTML/CSS, Figma, draw.io 등 어떤 도구로 만들어도 하나의 디자인 시스템처럼 보이게 하는 플로우차트 공통 디자인 기준입니다. [한국어 안내](skills/flowchart-design/SKILL.ko.md) |
| [`docs-rewrite`](skills/docs-rewrite/SKILL.md) | 주장, 수치, 확신도를 그대로 둔 채 글이 자연스럽게 읽히도록 고쳐 쓰고, AI가 쓴 듯한 한국어 문체를 함께 고칩니다. [한국어 안내](skills/docs-rewrite/SKILL.ko.md) |
| [`document-to-confluence`](skills/document-to-confluence/SKILL.md) | Markdown, HTML, PDF, DOCX, Google Docs 문서를 Confluence 페이지로 변환하고, 문서 구조와 첨부 파일을 보존하며, 이후 원본 변경도 페이지에 반영합니다. [한국어 안내](skills/document-to-confluence/SKILL.ko.md) |
| [`skill-builder`](skills/skill-builder/SKILL.md) | 초안 작성 → 테스트 → 검토 → 개선 순환을 통해 에이전트 스킬을 만들고, 검증하고, 패키징합니다. [한국어 안내](skills/skill-builder/SKILL.ko.md) |
| [`orca-plugin-refresh`](skills/orca-plugin-refresh/SKILL.md) | 이 플러그인을 안전하게 오프라인으로 업데이트하고, 설치된 버전을 대기 중인 Orca 관리 Claude Code와 Codex 세션에 재시작 없이 반영합니다. [한국어 안내](skills/orca-plugin-refresh/SKILL.ko.md) |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | 스테이징된 변경과 스테이징되지 않은 변경을 함께, 또는 사용자가 지정한 범위를 최근 커밋 이력과 함께 읽어, 이 저장소의 스타일에 맞는 커밋 메시지 5개를 제안합니다. 커밋을 요청하면 가장 적절한 제목 하나로 바로 커밋합니다. [한국어 안내](skills/suggest-commit/SKILL.ko.md) |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | 구현 계획을 담당하지 않고 기술 설계 문서와 RFC를 작성하거나 검토합니다. [한국어 안내](skills/technical-design-writer/SKILL.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | 현재 에이전트와 반대쪽 Claude/Codex 세션이 교환 횟수를 제한한 토론을 벌여 쟁점을 드러내고 수렴시킵니다. [한국어 안내](skills/tiki-taka/SKILL.ko.md) |

## 관련 링크

- `omo-model-config`는 제거했습니다. 마지막 버전은 [`v1.3.0` 태그](https://github.com/hei5enbug/hei5enbug-agent-setup/tree/v1.3.0/standalone-skills/omo-model-config)에 있습니다.

## 라이선스

이 저장소는 Apache License 2.0을 따릅니다. 전문은 [`LICENSE`](./LICENSE)에 있습니다.
