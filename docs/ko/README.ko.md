# hei5enbug-agent-setup

> 영어 원본: [README.md](../../README.md)
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
├── issue-target.json
├── docs/
│   ├── rule-enforcement.md
│   └── ko/
│       ├── AGENTS.ko.md
│       ├── README.ko.md
│       ├── agents/
│       ├── instructions/
│       └── skills/
├── hooks/hooks.json
├── hooks/claude-hooks.json
├── hooks/codex-hooks.json
├── hooks/mod/
├── config/claude-mod.json
├── config/model-registry.json
├── instructions/
│   ├── claude-agents.md
│   ├── codex-agents.md
│   ├── confluence.md
│   ├── cross-repository.md
│   ├── documentation.md
│   ├── failure-and-maintenance.md
│   ├── implementation-delegation.md
│   ├── implementation-execution.md
│   ├── implementation-planning.md
│   ├── independent-model-validation.md
│   ├── model-evaluation.md
│   ├── model-routing.md
│   ├── protected-values.md
│   ├── services.md
│   └── session/
│       ├── claude-code.md
│       ├── codex.md
│       ├── common.md
│       └── core.md
├── scripts/
│   ├── agent_guard.py
│   ├── approval_guard.py
│   ├── approval_state.py
│   ├── approve_wrapper.sh
│   ├── datagrip_guard.py
│   ├── hook_python.sh
│   ├── host_settings.py
│   ├── language_guard.py
│   ├── plugin_toggles.py
│   ├── role_runner.py
│   ├── session_context.py
│   └── verify_spawn.py
├── tests/
├── LICENSE
├── pyproject.toml
├── agents/
│   ├── designer.md
│   ├── reviewer.md
│   ├── scout.md
│   ├── sonnet-worker.md
│   └── worker.md
├── standalone-agents/
│   ├── codex-designer.toml
│   ├── codex-reviewer.toml
│   ├── codex-scout.toml
│   └── codex-worker.toml
└── skills/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── docs-rewrite/
    ├── document-to-confluence/
    ├── local-data-cleanup/
    ├── mistake-enforcer/
    ├── orca-plugin-refresh/
    ├── report-skill-gap/
    ├── session-retro/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

각 플러그인 스킬 폴더는 자신의 `SKILL.md`와 필요한 참조 문서·스크립트를 담고 있습니다.
플러그인 매니페스트는 호스트별 디렉터리에 스킬을 복사하지 않고 같은 `skills/` 디렉터리를
Codex와 Claude Code에 패키징합니다.

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
일치하는 역할을 사용합니다. `scout`는 로컬 근거 조사 티켓을 포함해 범위가 제한된 로컬 조사 하나를 맡고, 웹 검색과 가져오기 도구로 범위가 정해진 공개 조사 질문 하나도 맡습니다. 스킬 검토 역할은 먼저 설정한 검토 모델을 사용하고 그 실행기를 쓸 수 없으면
`reviewer`로 대체합니다. reviewer는 결과만 반환하며 메인 세션이 같은 자료를 한 번 검토해 판단합니다. 시험 출력을 쓰는
스킬은 필요한 경우 검증된 평가 실행기를 사용합니다.
조건부 [모델 라우팅 계약](../../instructions/model-routing.md)을 참고하세요.

### Claude Code mod

Claude Code에서는 `config/claude-mod.json`이 mod `hooks/mod/register.js`를 불러옵니다. 이 mod가 Claude 전용 가드인
내장 서브에이전트 차단, 역할 고정, GPT 거부를 담당합니다. 양쪽 호스트의 승인은 [승인 가드](#승인-가드)가 보관합니다.
mod는 Claude Code 2.1.292에서 시험했습니다.
오래된 Claude Code, `disableAllHooks`, 관리 정책 등으로 mod가 로드되지 않으면 이 가드들은 동작하지 않고 호스트의 기본 권한
흐름이 적용됩니다.

역할 고정은 플러그인 역할마다 모델과 사고 강도를 모든 요청에 고정합니다. `scout`는 `claude-sonnet-5-5`와 `medium`,
`worker`는 `worker_model`과 `worker_effort`(기본 `claude-haiku-5-5`와 `high`), `sonnet-worker`는 `claude-sonnet-5-5`와 `high`, `designer`는
`claude-opus-5-5`와 `xhigh`, `reviewer`는 `claude-opus-5-5`와 `high`를 씁니다.
다른 모델로 응답한 서브에이전트는 중단됩니다. 이후 요청은 거부되고 도구 호출은 막히며 결과는 경고로 바뀝니다.
역할 고정이 활성화된 경우에만 등록된 mod `prompt.submit` 훅이 대화마다 메인 세션의 첫 프롬프트에
`hei5enbug-agent-setup mod: role pinning active` 줄을 컨텍스트로 붙이고, `/clear`나 `/resume` 뒤에도 다시 붙입니다.
이 줄이 있으면 메인 세션은 작업 지시를 바로 보내고 위임마다 설정과 서브에이전트 기록을 확인하지 않아도 됩니다.
mod는 `prompt.context`와 `classic.*` 훅을 쓰지 않습니다. 관리 설정이나 Team·Enterprise 로그인에서 로드되는 Claude Code
내장 가드 `cc-plugin-sec-default`가 사용자가 설치한 모든 mod의 이 훅들을 건너뛰기 때문입니다.

mod는 화면 표시 두 가지도 그리며, 둘 다 모델 컨텍스트에는 아무것도 넣지 않습니다. `risk_highlight`를 켜면 대화 기록의 도구
호출 줄마다 승인 가드가 그 호출에 내린 판정에 따라 색 라벨이 붙습니다. 되돌릴 수 없거나 매번 묻는 호출은 빨강, 쓰기는
노랑입니다. 몇 초 안에 안전하게 읽을 수 있으면 빨간 호출의 라벨 아래 줄에 그 호출이 무엇을 바꾸는지도 보입니다. 예를
들어 `git reset --hard`가 버릴 파일과 줄 수, `git clean`이 지울 파일, `kubectl delete`가 지울 리소스입니다. 이
미리보기는 평소 대화 기록의 접힌 줄에도 나오고, 응답 언어를 따르며, 라벨처럼 줄 끝에서 잘릴 뿐 다음 줄로 넘어가지
않습니다. 결정은 권한 확인 창에서 그대로 합니다.
`work_board`를 켜면 입력창 위 한 줄 요약이 컨텍스트 사용량, 프롬프트 캐시 적중률, Claude 5시간·주간 사용량, Codex 주간 사용량을 보여 주고, 초기화 전에 소진될 한도는 색으로 표시합니다. 실행 중인 서브에이전트나 편집 충돌이
있으면 그 수도 함께 보여 줍니다. `/work-board`는 직접 크기를 바꾸지 않았다면 너비 40칸의 패널을 열어 서브에이전트마다 상태,
경과 시간, 수정한 파일을 보여 주고, 두 에이전트가 같은 파일을 고치면 그 파일을 빨강으로 표시하며, 소진 예측이 포함된 전체
사용량 줄도 보여 줍니다.

`secret_redaction`을 켜면 mod가 Bash, Read, Grep, MCP 결과에서 잘 알려진 비밀값 형식을 Claude가 읽기 전에 가립니다.
클라우드·서비스 API 키, 개인 키 블록, JWT, URL 안의 비밀번호 등이며, 변수 이름과 자리 표시용 값은 그대로 둡니다. 찾은 값은
그 세션에서 발급한 ID가 붙은 `[REDACTED:<종류>:<ID>]`로 바뀝니다. 새 내용에 발급된 표시가 들어간 편집이나 쓰기는 새 파일이든
기존 파일이든 거부합니다. 그대로 쓰면 비밀값 대신 표시가 저장되기 때문이며, 거부 메시지는 응답 언어를 따릅니다. 문서나
테스트처럼 표시를 글자로 적기만 한 내용은 허용합니다. 형식 목록은 `config/secret-patterns.json`에 있고 승인 가드가 명령을 보여 줄 때도 같은 목록을 씁니다. 결과는
앞 4MB까지만 검사합니다.

### 응답 언어

언어 가드인 `scripts/language_guard.py`는 모든 답변과 진행 상황 안내가 응답 언어로 작성되었는지 확인합니다.
Claude Code는 `language` 설정에서 언어를 가져오며, 로컬 프로젝트 설정, 프로젝트 설정, 사용자 설정 순서로 읽습니다.
설정이 없으면 아무것도 강제하지 않습니다. Codex는 `HEI5ENBUG_RESPONSE_LANGUAGE`를 읽고, 설정하지 않으면 한국어를
사용합니다. 고유한 문자 체계가 있는 언어만 검사합니다. 한국어, 일본어, 중국어, 러시아어, 우크라이나어, 그리스어,
아랍어, 히브리어, 태국어, 힌디어입니다. 영어나 프랑스어 같은 다른 언어에는 지침만 적용됩니다.

검사는 코드, 인용, URL을 제외합니다. 글자 중 대상 문자 체계의 비율이 30% 이상이면 통과하며, 아주 짧은 글은 항상
통과합니다. 답변이 통과하지 못하면 `Stop` 훅이 다시 쓰도록 요청하며, 한 턴에 최대 3번까지 요청합니다.
위임된 자식 세션은 검사하지 않습니다. 역할 실행기의 자식처럼 `HEI5ENBUG_ASSIGNED_ROLE`이나
`HEI5ENBUG_PARENT_SESSION`이 설정된 세션은 조정 세션에 답변을 돌려주고, 조정 세션이 사용자에게 응답합니다.
다른 언어로 쓴 진행 상황 안내가 나오면 `PostToolUse` 훅이 알림을 추가합니다. 이 훅은 비동기로 실행되므로 알림은 다음
턴에 모델에 전달됩니다. 사용자가 다른 언어로 요청한 글은 코드 블록이나 인용 블록에 넣습니다.

### DataGrip 쿼리 가드

두 호스트의 `PreToolUse` 훅과 Codex 전용 `PermissionRequest` 훅인 `scripts/datagrip_guard.py`는
DataGrip MCP 도구 `execute_sql_query` 실행 전에 동작합니다.
가드는 `projectPath`가 가리키는 DataGrip 프로젝트의 `.idea/dataSources.xml`에서 연결 정보를 읽습니다.
운영이 아니고 확인된 연결에서는 PostgreSQL과 SQL Server의 읽기 쿼리를 승인 없이 실행합니다. PostgreSQL 읽기는 읽기 전용 트랜잭션에서
`SET LOCAL statement_timeout = '60s';`와 함께 실행됩니다. 운영 연결에서는 PostgreSQL 읽기 전에 기록된 계획이 필요하고, SQL Server 읽기에는
잠금 안전장치가 붙습니다([승인 가드](#승인-가드)의 운영 읽기 규칙 참고). `approval_guard`를 켜면 비파괴적인 PostgreSQL·SQL Server
쓰기는 다른 모든 쓰기와 세션 쓰기 승인(`write:session`)을 공유합니다. 알 수 없는 연결, 그 밖의 데이터베이스 종류,
가드가 해석하지 못한 텍스트도 같은 승인을 사용합니다. 연결 이름의 `승인`은 그 자체로는 아무 효과가 없습니다.
코드에 `delete`, `drop`, `truncate`가 이름으로 든 문장과 SQL 분류기가 파괴적으로 판단한 문장은 매번 승인을 요청합니다.
`DO`, `EXEC`, `EXECUTE`, `CALL`로 시작하는 문장도 여기에 포함됩니다. 여기서 코드는 문자열 리터럴, 주석, 따옴표나 대괄호로 묶은
식별자를 뺀 나머지 텍스트이므로, 그 안에서만 `delete`를 언급하는 `SELECT`는 읽기로 남습니다. 운영이 아닌 PostgreSQL
연결("운영 데이터베이스 읽기" 참고)에서 `pglast` 파서가 텍스트를 확인하면, 자기 문장에 `WHERE`가 있는 `DELETE`와, 본문이
PL/pgSQL로 파싱되고 `DROP`, `TRUNCATE`, `EXECUTE`, `ALTER`, `GRANT`, `REVOKE`, `CALL`, 중첩 `DO`, `WHERE` 없는 `DELETE`,
위험 함수 호출(따옴표로 감싼 이름도 검사하며, 여기서는 `set_config`와 `pg_sleep`는 허용)이 없는 `DO` 블록이 대신 세션
쓰기입니다. 세미콜론 없이 문장을 이어 쓸 수 있는 SQL Server와 파서가 확인하지 못한 텍스트는 계속 매번 묻습니다.
SQL Server 읽기에는 `SET NOCOUNT`,
`LOCK_TIMEOUT`, `DEADLOCK_PRIORITY`, `TRANSACTION ISOLATION LEVEL READ UNCOMMITTED|READ COMMITTED|SNAPSHOT`, `ARITHABORT`,
`ANSI_NULLS`, `ANSI_WARNINGS`, `ANSI_PADDING`, `QUOTED_IDENTIFIER`, `CONCAT_NULL_YIELDS_NULL`, `XACT_ABORT`, `STATISTICS IO|TIME`,
`SHOWPLAN_XML|ALL|TEXT` 문장도 함께 쓸 수 있습니다.
Codex에서는 쓰기가 준비된 상태면 Codex의 네이티브 승인 창을 열고, 그렇지 않으면 코드와 함께 거부합니다.
매번 묻는 쿼리는 항상 코드와 함께 거부합니다([승인 가드](#승인-가드)를 참고하세요). 토글을 끄면 모든 쓰기가 이전처럼 승인을 요청합니다. Codex에서는 `/hooks`에서 이 훅을 신뢰해야 합니다.

선택 사항으로 `pglast` 파서를 한 번 설치할 수 있습니다.

```bash
uv venv --python 3.12 "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser"
uv pip install --python "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser/bin/python" pglast==8.4
```

파서가 없으면 PostgreSQL은 더 엄격한 텍스트 검사로 대체합니다. 이 검사는 승인을 더 자주 요청할 수 있지만, 승인 없이 쓰기가 실행되는 일은 여전히 없습니다.

### 승인 가드

`PreToolUse` 훅은 Bash, MCP, Claude 파일 도구(`Read`, `Edit`, `Write`, `MultiEdit`, `NotebookEdit`),
Codex `apply_patch` 호출 전에 `scripts/approval_guard.py`를 실행합니다. 같은 스크립트가 `PermissionRequest`,
`PostToolUse`, `PostToolUseFailure`, `UserPromptSubmit`도 처리합니다. 양쪽 호스트에서 읽기는 승인 없이 실행됩니다. 호출은 세 층 중
하나에 들어가거나, 거부되거나, 통과합니다.

- **읽기**는 승인 없이 실행됩니다.
- **세션 승인**은 세션당 한 번 묻고, 세션이 끝날 때까지 같은 종류의 이후 호출을 모두 허용합니다. 두 가지가 있습니다.
  `write:session`은 명령이나 대상과 관계없이 운영 환경 변경, git 푸시, MCP, DataGrip, tabularis 쓰기를 포함한 모든
  쓰기를 허용하며, 분류할 수 없는 호출도 텍스트에 파괴적 작업이 없으면 쓰기입니다. `sensitive:session`은 보호 값이
  노출될 수 있는 호출인 모든 민감 읽기를 허용합니다. 하나를 승인해도 다른 하나는 승인되지 않으며, 둘 다 필요한
  호출은 한 번 물어 둘 다 승인합니다.
- **매번**은 호출할 때마다 묻고 승인을 남기지 않으므로 다음 실행에도 다시 묻습니다. 아래 목록이 이 작업들입니다.
  Claude 프롬프트는 `Asks every time:`으로 시작합니다. 이런 호출이 세션 승인도 필요로 하면 승인이 그 승인까지 주고,
  프롬프트가 이를 밝힙니다.
- **요청**은 실제 호출 전에 세션 승인 묶음을 요청합니다.
- **비밀**은 명령이 비밀 값을 출력하므로 두 호스트 모두에서 거부됩니다.
- **금지**는 두 호스트 모두에서 거부됩니다. 가드 스크립트를 실행하거나 승인 상태를 편집하는 경우입니다(아래 자기 승인 규칙 참고).
- **통과**는 가드가 다루지 않는 호출이므로 호스트의 기존 권한 절차가 결정합니다.

매번 묻는 목록에는 원격·운영 시스템에 영향을 주거나 복구할 수 없는 로컬 데이터를 지우는 작업을 둡니다.
그래서 한 번 승인해도 다음 실행에는 다시 묻습니다. 버려도 되거나 복구할 수 있는 로컬 작업은 이 목록에서 제외합니다.
아래 로컬 범위 규칙에서 이를 설명합니다.

1. 파괴적 `git push`: 강제·force-with-lease·삭제·mirror·prune push와 `+`·`:` refspec.
   단 로컬 범위 규칙에서 설명하는 lease로 보호된 기능 브랜치 푸시는 제외합니다.
2. 커밋하지 않은 작업 버리기: dry run 없는 강제 `git clean`, `git stash drop`·`git stash clear`.
   추적 파일에 커밋하지 않은 변경이 있거나 저장소 상태를 읽을 수 없을 때의 `git reset --hard`,
   강제 checkout이나 `.` checkout, 작업 트리의 `.`·`:/` restore도 포함합니다.
3. 보호 경로나 외부 경로, 풀 수 없는 대상의 재귀 삭제. 단 로컬 범위 규칙에서 설명하는 복구 가능한 작업 트리 삭제는 제외합니다.
4. `psql`, `sqlcmd`, DataGrip, tabularis, MCP SQL 필드로 보내는 파괴적 데이터베이스 문장
5. 원격 인프라 삭제: `kubectl`, `oc`, `helm`, `az`, `terraform`, `tofu`, `aws`, `gcloud`, `gsutil`의 파괴적 동사
   (`delete`, `drain`, `uninstall`, `destroy`, `purge`, `terminate` 등), `--` 앞의 `--force`와 `--prune`,
   `kubectl`·`oc` `exec` 안의 파괴적 명령, 파괴적 `gh` 호출
6. 패키지 게시: `npm`, `pnpm`, `yarn`, `uv`, `poetry`, `cargo`의 `publish`, `twine upload`, `gem push`
7. 원격 엔진을 대상으로 한 `docker`·`podman`의 삭제: `rm`, `rmi`, `prune`, `compose down -v`, `exec` 안의 파괴적 명령.
   DELETE 같은 파괴적 메서드를 쓴 `curl`. 이름에 삭제 단어가 든 MCP 도구와 action
8. 샌드박스 보호 없는 Codex 실행
9. 가드가 분류하지 못한 호출과 텍스트에 파괴적 작업이 있는 분류 불가 호출(스크립트와 실행형 도구의 코드 입력 포함)

로컬 범위 규칙은 버려도 되거나 복구할 수 있는 로컬 작업을 매번 묻는 목록에서 제외합니다.

- **임시 루트**는 `/tmp`, `/private/tmp`, `/var/folders`, `/private/var/folders`, `$TMPDIR`, `~/.cache`,
  Claude Code 작업 폴더 `~/.claude/jobs/<id>/tmp`입니다. 임시 루트 안의 재귀 삭제는 통과합니다.
  리다이렉션(`>`, `>>`, heredoc), `mkdir`, `touch`, `tee`, `cp`·`mv`의 목적지는 심볼릭 링크를 푼 뒤
  모든 목적지가 임시 루트 안에 있으면 통과합니다. 원본은 어디에 있어도 됩니다. 다만 기존 폴더로 `cp`·`mv`할 때는
  `<folder>/<source name>`으로 판단하므로 그 위치의 심볼릭 링크가 루트 밖으로 나가거나 원본 이름을 알 수 없으면
  (glob이나 변수) 이 규칙을 적용하지 않습니다. 명령 전체가 이런 쓰기와 `cat`, `echo`, `ls`, `cd` 같은
  무해한 명령 몇 개로만 이루어지면 세션 승인 없이 Claude Code 자체 권한 프롬프트에 허용으로 응답합니다.
  `./README.md`처럼 임시 루트 안임을 증명할 수 없는 목적지는 기존 절차를 따릅니다.
  그곳에 쓰는 스크립트는 여전히 쓰기입니다.
- **복구 가능한 작업 트리 삭제**: 모든 대상이 명령이 실행되는 폴더가 속한 Git 작업 트리 안에 있고, Git이 각 대상을
  변경 사항(staged, unstaged, untracked)이 없는 추적 대상이거나 추적되지 않고 무시된(`git check-ignore`) 대상으로
  보고하면 재귀 `rm`은 세션 쓰기이며 "Recursive removal of tracked files" 또는 "Recursive removal of ignored files"로
  표시합니다. Git은 추적되지 않은 파일 보고와 무시 설정을 명령줄에서 강제한 채 실행하므로 저장소 설정으로 파일을 숨길 수
  없습니다. 작업 트리 루트, `.git`, 심볼릭 링크, 존재하지 않는 경로, `assume-unchanged`나 `skip-worktree` 항목,
  Git이 무시하지 않는 추적되지 않은 파일,
  같은 텍스트 앞쪽에서 파일을 바꿀 수 있는 명령(반복문 머리는 포함하고 단순한 `[ ... ]` 검사는 제외), 저장소를 바꿀 수 있는
  Git 변수, Git 실패나 시간 초과는 계속 매번 묻습니다.
- **로컬 컨테이너 엔진**: 엔진이 로컬이면 `docker`·`podman`의 삭제·정리(`rm`, `rmi`,
  `container`, `image`, `volume`, `network`의 `rm`·`prune`, `system prune`, `-v` 유무와 관계없는
  `compose down`)와 파일을 지우는 `exec` 명령은 세션 쓰기입니다. 하위 명령 앞에 `--host`, `-H`,
  `--remote`, `-r`, `--url`, `--connection`, `--identity` 옵션이 있으면 엔진은 원격입니다.
  `-Htcp://h`, `--remote=true` 같은 모든 표기를 포함합니다. `CONTAINER_HOST`나 `CONTAINER_CONNECTION`이
  설정되어 있거나, `DOCKER_HOST`가 `unix://` 소켓, 경로, 단독 호스트 `localhost`, `127.0.0.1`, `::1`
  이외의 값일 때도 원격입니다. 이름이 있는 Docker 컨텍스트는 `--context`·`-c`, 그다음 `DOCKER_CONTEXT`,
  그다음 Docker 설정의 `currentContext`에서 가져옵니다. 설정은 `--config`, `DOCKER_CONFIG`,
  `~/.docker/config.json` 순서로 찾습니다. 이 컨텍스트는
  `<config dir>/contexts/meta/<sha256 of the name>/meta.json`의 `Endpoints.docker.Host`가
  `unix://`나 `npipe://`로 시작할 때만 로컬이므로 Docker Desktop의 `desktop-linux`는 로컬입니다.
  메타 파일이 없거나 읽을 수 없거나 형식이 잘못된 경우, 호스트가 없는 경우, `tcp://`·`ssh://` 같은 다른 스킴이면
  원격입니다. `default` 컨텍스트는 로컬입니다. podman은 `containers.conf`(`CONTAINERS_CONF`,
  사용자·시스템 파일과 각각의 `.d` 폴더)에 `active_service`나 `remote = true`가 설정되어 있거나,
  저장된 시스템 연결 기본값이 있으면 원격이며, 해당 설정을 읽을 수 없을 때도 원격입니다.
  원격 엔진에는 계속 매번 묻습니다. 함수, 변수, `eval`, `sh -c` 텍스트의 파괴적 단어가 로컬
  `docker`·`podman` 삭제만 가리키는 경우도 세션 쓰기입니다.
- **lease로 보호된 푸시**: 다음 조건을 모두 충족하는 `git push`는 매번 묻지 않고 세션 쓰기로 처리합니다.
  강제 관련 플래그는 `--force-with-lease`(단독, `=<ref>`, `=<ref>:<expect>`)와 `--force-if-includes`만 있어야 합니다.
  원격 이름을 명시해야 하며 `upstream`은 제외합니다. URL, 경로, git이 읽을 수 없는 원격에는 계속 매번 묻습니다.
  모든 대상 브랜치를 명시해야 하며 `main`, `master`, `develop`, `trunk`는 제외합니다.
  `git symbolic-ref refs/remotes/<remote>/HEAD`를 읽을 수 있으면 해당 원격의 HEAD 브랜치도 제외합니다.
  대상은 `src:dst`, `dst` 또는 lease ref에서 가져옵니다. `HEAD`, `@`, 비어 있거나 암묵적인 대상, glob,
  `refs/heads/` 이외의 `refs/` 이름에는 계속 매번 묻습니다. `--force`, `-f`, `--delete`, `-d`, `--mirror`,
  `--prune`, `--all`, `--tags`, `+`·`:dst` refspec, 알 수 없는 옵션, `-C` 이외의 전역 옵션,
  대상을 바꾸는 `GIT_*` 변수, 컨테이너 안의 `exec`도 계속 매번 묻습니다.
  예를 들어 `git push --force-with-lease origin feature/ABC-1`은 세션 쓰기이고,
  `git push --force-with-lease origin main`은 매번 묻습니다.
- **변경 없는 추적 트리**: 저장소에서 `git status --porcelain --untracked-files=no`가 3초 안에
  아무것도 출력하지 않으면 `git reset --hard`, `git checkout -f`, `git checkout .`, `git restore .`은
  세션 쓰기입니다. `-C`가 지정한 경로도 따릅니다. 다음 경우에는 계속 매번 묻습니다. 오류나 시간 초과가 발생한 경우,
  `-C`와 무해한 `--no-pager`, `-P`, `--no-optional-locks`, `--paginate`, `-p` 이외의 전역 옵션이 있는 경우
  (`-c`, `--config-env`, `--git-dir`, `--work-tree`, `--namespace`, `--bare` 모두 해당),
  또는 다음 예외 이외의 `GIT_*` 변수가 있는 경우입니다. 예외는 `GIT_EDITOR`, `GIT_SEQUENCE_EDITOR`,
  `GIT_PAGER`, `GIT_TERMINAL_PROMPT`, `GIT_ASKPASS`, `GIT_SSH`, `GIT_SSH_COMMAND`, `GIT_TRACE*`,
  `GIT_PROGRESS_DELAY`, `GIT_FLUSH`, `GIT_MERGE_AUTOEDIT`입니다.
  `kubectl`·`oc`·`docker`·`podman`의 `exec` 안의 명령에도 매번 묻습니다.
  같은 명령의 앞선 세그먼트 중 파일 출력 없는 단순 읽기가 아닌 것이 있어도 매번 묻습니다.
  예를 들어 `printf x >> a; git reset --hard`는 매번 묻습니다.

승인이 필요한 호출은 응답 언어로 한 줄, 100자 이내로 보입니다. Claude Code는 `language` 설정에서 언어를 가져오며, 설정이
없으면 영어입니다. Codex는 `HEI5ENBUG_LANGUAGE`를 쓰고, 없으면 응답 언어 가드의 `HEI5ENBUG_RESPONSE_LANGUAGE`를 쓰며 그
기본값은 한국어입니다. 줄에 맞지 않는 설명은 줄이되 최소 20자는 남깁니다.
복합 호출은 설명을 모두 남기되 각각 40자로 줄이며 줄 길이는 제한하지 않습니다. Claude는 다음 줄을 보여 줍니다.

| 종류 | 한국어 | 영어 |
|---|---|---|
| 쓰기 | `쓰기 승인: kubectl apply on (default) dev/web. 한 번 승인하면 이 세션의 쓰기는 더 묻지 않습니다.` | `Write: kubectl apply on (default) dev/web. Approve once; later writes in this session will not ask.` |
| 매번 | `매번 승인: git push --force (origin main).` | `Asks every time: git push --force (origin main).` |
| 민감 읽기 | `민감 조회 승인: cat .env (값이 노출될 수 있음). 한 번 승인하면 이 세션의 민감 조회는 더 묻지 않습니다.` | `Sensitive read: cat .env (may show a value). Later ones in this session won't ask.` |

다른 세션 승인도 함께 주는 호출의 줄 끝에는 "Also approves writes for this session."처럼 그 승인을 밝히는 짧은 문장이 붙습니다.
요청은 `--why` 문구를 설명으로 보여 줍니다.

| CLI | 읽기 | 비밀 (거부) | 민감 (세션) | 매번 | 프롬프트의 대상 |
|---|---|---|---|---|---|
| `kubectl`, `oc` | `get`, `describe`, `logs`, `diff`, `config view`, `config get-contexts`, `config current-context`, `--dry-run=client` 또는 `--dry-run=server`가 붙은 모든 호출 | 값을 출력하는 출력 형식이 붙은 `get secret`(이름, 네임스페이스, UID, 레이블, 소유자 참조, finalizer, 타임스탬프, 리소스 버전, `type`, `kind`, `apiVersion`, `immutable`만 읽는 `jsonpath` 또는 `custom-columns` 템플릿은 읽기입니다. `annotations`에는 마지막으로 적용한 매니페스트가 들어갈 수 있으므로 계속 비밀로 분류합니다), `secrets` 경로의 `get --raw`, `config view --raw`, `create token` | `exec ... env` 또는 `printenv` | `delete`, `drain`, `--` 앞의 `--force`·`--prune`, `exec` 안의 파괴적 명령 | kubeconfig, 그다음 컨텍스트 / 네임스페이스 |
| `helm` | `list`, `status`, `get notes`, `repo list` | 없음 | `get all`, `get manifest`, `get values` | `uninstall` | kubeconfig, 그다음 컨텍스트 / 네임스페이스 |
| `az` | `list`, `show`, `exists`, `query`, `query-*`, `version`; `--resource` 없이 `https://management.azure.com`이나 풀 수 없는 변수 URL에 보내는 `rest` GET | `keyvault secret show`와 `download`, `list-keys`, `account get-access-token`, Key Vault `/secrets`·`/keys` URL에 대한 `rest` GET | 없음 | `delete`, `purge`, `rest` DELETE | 구독 / 리소스 그룹 |
| `terraform`, `tofu` | `plan`, `show`, `validate`, `state list`, `fmt -check`, `-json`·`-raw` 없는 `output` | 없음 | `state show`, `state pull`, `output -json`, `output -raw` | `destroy`, `apply -destroy`, `state rm` | 디렉터리 : 워크스페이스 |
| `aws` | `describe-*`, `list-*`, 비밀 조회가 아닌 `get-*`, `s3 ls` | `secretsmanager get-secret-value`와 `batch-get-secret-value`, `--with-decryption`이 붙은 `ssm get-parameter*`, `kms decrypt` | 없음 | `delete-*`, `terminate-*`, `s3 rm`, `s3 sync --delete` | 프로파일 / 리전 |
| `gcloud`, `gsutil` | 명령 경로에서 처음 나오는 동사가 `list`, `describe`, `get-*`, `ls`, `cat` | `secrets versions access`, `auth print-access-token` | 없음 | `delete`, `gsutil rm`, `gsutil rb` | 프로젝트 |
| `docker`, `podman` | `ps`, `images`, `logs`, `<object> ls` | 없음 | `inspect`, `exec ... env` 또는 `printenv` | 원격 엔진 대상: `rm`, `rmi`, `prune`, `compose down -v`, `exec` 안의 파괴적 명령(로컬 엔진: 세션 쓰기) | 컨텍스트 |
| `psql`, `sqlcmd` | 읽기인 쿼리. 가드가 다루는 `psql` 읽기는 `default_transaction_read_only=on`과 `statement_timeout=60000`으로 실행됩니다. | 없음 | 없음 | `delete`·`drop`·`truncate`가 이름으로 든 텍스트와 `DO`·`EXEC`·`EXECUTE`·`CALL`로 시작하는 문장 등을 포함한 파괴적 SQL | 호스트 / 데이터베이스 |
| `curl` | 데이터·폼·업로드·JSON 플래그가 없는 GET/HEAD | 없음 | argv의 자격 증명(`-u`, `--user`, `Authorization` 헤더) | DELETE 같은 파괴적 메서드 | 메서드 / 스킴과 호스트 |
| `kustomize` | 모든 호출 | 없음 | 없음 | 없음 | 없음 |
| `mysql`, `mongosh`, `redis-cli` | 없음. 명시적인 로컬 호스트는 통과 | 없음 | 없음 | 파괴적 작업이 든 분류 불가 텍스트 | 없음 |
| `git` | `status`, `show`, `log`, `diff`, `ls-remote`, `ls-tree`, `ls-files`, `cat-file`, `rev-list`, `show-ref`, `for-each-ref`, `merge-base`, `blame`, `shortlog`, `diff-tree`, `describe`, `rev-parse`, 태그 목록과 검증 | 없음 | 없음 | 강제·삭제·미러·prune 푸시(lease로 보호된 기능 브랜치 푸시는 세션 쓰기), dry run 없는 강제 `clean`, `stash drop`·`stash clear`. 추적 트리에 변경이 없을 때(이때는 세션 쓰기)를 제외한 `reset --hard`, 강제 checkout이나 `.` checkout, 인덱스만 복원하는 경우를 제외한 `.`·`:/` restore | 명령 |
| `gh` | `view`, `list`, `ls`, `status`, `checks`, `diff`, `search`, `watch`, `browse` 같은 읽기 동사, `auth status`, `config get`/`list`, 버전·도움말, `api` GET과 인라인 GraphQL query | `auth token` | 없음 | 모든 영역의 `delete`, `api` DELETE | 명령 |

그 밖에 가드가 다루는 비파괴적 CLI 작업은 세션 쓰기 승인을 사용합니다. 로컬 `kubectl`·`oc` `config` 변경(`use-context`,
`delete-context` 등), `helm repo remove`, 로컬 git 태그 삭제·강제 변경도 여기에 해당합니다. 원격 SQL 클라이언트의
파일·표준 입력·대화형 사용은 분류 불가 쓰기이며, 파괴적 텍스트가 있으면 매번 묻는 목록에 들어갑니다. `psql`, `mysql`,
`redis-cli`, `mongosh`에서 명시적인 로컬 호스트(`localhost`, `127.0.0.1`, `::1`, 소켓 경로)는 통과합니다.
`gh api`의 데이터 플래그와 `--input`은 명시적인 GET으로 덮어쓰지 않는 한 쓰기를 뜻합니다.
인라인 GraphQL 필드는 `#` 주석과 앞쪽 공백을 제거한 뒤 `query`나 `{`로 시작하고 `mutation` 단어가 없어야 읽기입니다.
mutation과 쿼리 파일은 쓰기입니다. 알려지지 않은 `gh` 동작도 쓰기이며, `gh pr checkout`과 `gh repo clone`은
호스트 판단에 맡깁니다. git 태그 생성과 푸시, 릴리스 생성·편집·업로드 같은 `gh` 쓰기는 양쪽 호스트에서 같은 승인을 사용합니다.

패키지 게시(`npm`, `pnpm`, `yarn`, `uv`, `poetry`, `cargo`, `twine upload`, `gem push`)는
게시 하위 명령 앞에 옵션이 있어도 매번 묻습니다.
재귀 `rm`은 세션 폴더와 그 상위 폴더, 홈 폴더, `/`, `.git`과 그 내용, 풀 수 없는 대상 등
보호 경로나 외부 경로에 대해 매번 묻습니다. 그 밖에 세션 폴더나 임시 루트(로컬 범위 규칙 참고) 안에서의 삭제는 통과합니다.
대상이 정확히 `$(mktemp -d ...)` 또는 백틱 치환이거나 `${TMPDIR:-<default>}`로 시작하면, 먼저 임시 루트(`TMPDIR`가
있으면 그 값, 없으면 기본값)로 풀고 다른 경로와 똑같이 검사합니다. 그래서 홈 폴더, 세션 폴더, `.git` 차단은 그대로 적용됩니다.
같은 명령 텍스트에서 앞서 대입한 변수는 값이 정적 단어 하나(리터럴, `~`, `$HOME`, `$TMPDIR`, `${TMPDIR:-<default>}`,
또는 이미 푼 다른 변수)이면 풉니다. 텍스트의 모든 경로가 거치는 `if`, `case`, `{ }`, `( )` 본문 안의 대입과
`for` 반복문의 단어도 포함합니다. 삭제는 가능한 모든 값에 대해 검사하고 가장 엄격한 결과를 따릅니다.
`&&`나 `||` 목록에서 앞선 명령이 성공하거나 실패할 때만 실행되는 대입은 조건부입니다. 그 목록에서 뒤따르는 명령은 앞의 연결이
모두 `&&`일 때만 새 값만 보고, `||` 뒤와 목록 뒤(`;`, 줄바꿈, `&` 다음)에서는 새 값과 이전 값을 함께 봅니다. 환경이 제공하지
않는 변수의 이전 값은 빈 문자열입니다. 따옴표 없는 참조는 공백에서 나뉘므로 값의 각 단어를 따로 대상으로 검사합니다.
따옴표 없이 빈 값으로 풀리는 대상은 뺍니다. 따옴표를 친 빈 대상은 아무것도 지우지 않습니다. 다만 빈 값 때문에 `$D/y`가
`/y`가 되는 것처럼 대상이 세션 폴더와 임시 루트 밖의 경로로 바뀌면 계속 묻습니다. 뒤따르는 `cd`는 상대 대상의 기준만 바꿉니다.
명령 치환, 백틱, `read`, 산술, 알 수 없는 변수, `set --`, `shift`, 일부 경로에서만 대입한 값은 풀지 못한 채 매번 묻습니다.
가드가 명령이 실행하는 셸 스크립트를 읽을 때는 스크립트를 하나의 텍스트로 판단하므로 한 줄에서 대입한 변수를 다음 줄에서 풉니다.
그 스크립트의 `$0`, 폴더 관용구 `$(dirname "$0")`, `$(cd "$(dirname "$0")" && pwd)`, `${BASH_SOURCE[0]%/*}`,
`$1`부터 `$9`는 각각 스크립트 경로, 스크립트 폴더, 호출의 리터럴 인자로 풀며, 인자가 반복문 변수이면 가능한 모든 값으로 풉니다.
스크립트 경로는 명령이 쓴 경로를 셸처럼 심볼릭 링크를 풀지 않고 절대 경로로만 만든 것입니다.
`kubectl`·`oc`·`docker`·`podman`의 `exec` 안의 명령에도 일반 분류기를 적용합니다.
파괴적 명령은 매번 묻되, 로컬 `docker`·`podman` 컨테이너 안의 파일 삭제는 세션 쓰기입니다.
비밀 출력은 차단하며, 나머지 `exec` 호출은 쓰기입니다.
샌드박스 우회 플래그나 설정 재정의를 포함해 `danger-full-access`를 쓰는 모든 `codex` 호출은 매번 묻습니다.
`codex exec` 또는 `e`에서 하위 명령 앞뒤의 `--add-dir`·`-C`·`--cd`, 또는 `role_runner.py --add-dir`로
worker가 세션 폴더 밖에 접근하면 쓰기입니다.

쓰기는 `<cli>:<subcommand>@<target>`로 나타내며 subcommand는 첫 번째 플래그 앞의 단어들입니다. 프롬프트에는
`<cli> <subcommand> on <target>`으로 보이고, `write:session` 승인 하나가 이런 쓰기를 모두 허용합니다.
`kubectl`, `oc`, `helm`의 대상은 kubeconfig(`--kubeconfig`, 그다음 `KUBECONFIG`, 없으면 `(default)`)와
컨텍스트 및 네임스페이스입니다. 컨텍스트를 주지 않으면 같은 kubeconfig로 현재 컨텍스트를 읽습니다.
그 밖에 분석할 수 있는 하위 명령은 모두 쓰기이므로 `kubectl apply`와 `helm upgrade`는 세션에서 첫 쓰기가 승인될 때까지만 묻습니다.
`$(...)`나 백틱 치환의 본문은 별도 명령처럼 분류해 호출에 합칩니다. 명령 동사가 확장되지 않은 변수인 치환은 분류 불가 쓰기이며,
파괴적 작업이 있으면 매번 묻습니다. `eval`, `xargs`, `c`가 든 플래그 묶음을 쓴 `sh -c` 안의 명령도 분류합니다.
영역 자체가 비밀을 출력하면 명령 전체를 거부합니다. 가드가 다루는 명령의 heredoc은 분류 불가 쓰기이며,
파괴적 작업이 있으면 매번 묻습니다. heredoc 본문은 받는 명령이 `cat`, `tee`, `echo`, `printf`, `head`, `tail`, `wc`,
`sort`, `uniq`, `cut`, `tr`, `base64`, `xxd`, `od`, `grep`, `egrep`, `fgrep`, `rg`, `jq`, `column`, `fold`,
`fmt`, `nl`, `tac`, `rev`, `cmp`, `diff`, `git`, `gh`이고 출력이 뒤로 파이프되지 않으며,
쓰는 파일을 같은 명령 텍스트 뒤에서 `bash`, `sh`, `zsh`, `source`로 실행하지 않으면 데이터로 보고 검사하지 않습니다.
파일 확장자는 이 규칙에 영향을 주지 않습니다. 그 밖의 수신 명령이면 본문을 계속 검사합니다.
따옴표 없는 구분자 때문에 셸이 실행하는 치환만 계속 분류합니다. 프로그램 단어가 치환이나 확장되지 않은 변수에서 오면서
가드가 다루는 CLI를 언급하는 세그먼트는 분류 불가입니다. `command -v` 조회는 아무것도 실행하지 않으므로 분류하지 않습니다.

복합 명령은 전체로 판단합니다. 비밀 세그먼트가 있으면 거부합니다. 매번 묻는 목록에 드는 세그먼트가 하나라도 있으면
매번 묻고, 그 승인은 나머지 세그먼트가 필요로 하는 세션 승인도 함께 줍니다. 그 밖에 쓰기가 하나라도 있으면 검증되지 않은
세그먼트나 파일 출력이 있어도 명령 전체를 쓰기로 봅니다. 가드가 다루는 읽기는 나머지 세그먼트가 `grep`, `head`, `jq` 같은 필터이고,
출력 리다이렉션이 `/dev/null` 또는 `2>&1`로만 가는 경우에만 읽기로 남습니다.
`sudo`, `env`, `nice`, `time` 같은 래퍼는 옵션과 함께 건너뛰고 나서 실행 파일을 읽습니다.
쓰기와 매번 묻는 호출의 대상은 플래그나 환경 변수에서 가져옵니다. 둘 다 없으면 그 호출에 대해서만
`kubectl config current-context`와 `az account show`를 3초 제한으로 실행합니다.

`psql` 읽기는 `PGOPTIONS`에 `-c default_transaction_read_only=on -c statement_timeout=60000`을 더한
서브셸에서 실행하도록 다시 써서, 가드의 읽기 검사가 함수 호출을 놓치더라도 서버가 쓰기를 거부하게 하고 이 옵션이 뒤따르는 명령에 남지 않게 합니다.

가드는 `bash`, `sh`, `zsh`, `./`, `source`, `.`로 실행하는 셸 파일과 Python 파일,
선택한 또는 기본 타깃과 한 단계 선행 타깃의 Makefile 레시피, `npm`·`pnpm`·`yarn run <name>`이 가리키는
`package.json` 스크립트 텍스트를 읽습니다. 파일 경로는 이벤트의 `cwd` 기준이며 크기 제한은 256 KiB입니다.
같은 명령 텍스트 앞부분에서 `;`, `&&`, 줄바꿈으로 구분한 일반 `NAME=value` 문은 뒤의 단순 명령에 치환됩니다.
`for ... do ... done` 루프 본문도 포함하며, 따옴표 없는 확장에는 sh 단어 분할을 적용합니다.
값이 명령 치환 없는 정적 단어 하나이고(`$(mktemp -d ...)`는 삭제 대상처럼 풉니다), 조건 없는 대입일 때만 적용합니다.
즉 `export`가 아니고 괄호, 블록, 함수, 중괄호 그룹, 파이프, 백그라운드 안에 없어야 하며,
왼쪽이 대입만으로 이루어진 경우를 제외하면 `||`·`&&` 뒤에도 없어야 합니다.
이런 문맥 안의 대입은 그 뒤에서 해당 이름을 알 수 없는 상태로 만듭니다.
`read`, `export`, `for NAME in` 같은 명령은 치환을 해제합니다.
단순 명령이 뒤따르는 `xargs`는 입력을 알 수 없는 피연산자 하나로 보고 해당 세그먼트의 대입을 적용해 그 명령으로 분류합니다.
`DOCKER_HOST=ssh://h xargs docker rm`은 매번 묻습니다. 읽기나 `cat`·`grep` 같은 파일 읽기 명령은
알 수 없는 피연산자가 보호 파일을 가리킬 수 있으므로 민감 읽기가 되며, `xargs rm -rf`는 매번 묻습니다.
셸, `eval`, 중첩된 `xargs`, 알 수 없는 옵션, 명령 이름의 자리표시자는 기존의 불투명 처리를 유지합니다.
`cd <dir>`는 현재 셸에서 조건 없이 실행될 때만, 즉 괄호 밖에서 앞에 아무것도 없거나 `;`가 있고
뒤에 아무것도 없거나 `;` 또는 `&&`가 있을 때만 뒤따르는 세그먼트의 기준 경로를 옮깁니다.
앞선 독립 대입이 정한 `$NAME`, `${NAME}`은 경로에서 확장하지만, 접두 대입(`NAME=value cmd`)은 자기 명령의 인자를
확장하지 않습니다. 대입하지 않은 변수는 스크립트를 읽을 수 없게 하므로 분류 불가입니다.
셸의 각 줄과 Makefile 레시피에는 CLI 분류기를 적용합니다. Python 스크립트 파일이나 `python3 -` heredoc의 구문 트리가
읽기 전용임을 증명할 수 있으면 읽기입니다. 목록에 있는 표준 모듈만 가져오고, 프로세스·네트워크·환경·동적 실행이나
파일 변경 함수(`replace`, `remove`, `touch`, `mkdir` 이름 포함)를 호출하지 않아야 합니다.
파일은 리터럴 읽기 모드로만 열고, 자격 증명으로 보이는 경로나 단어를 언급하지 않아야 합니다.
`open` 함수에 연결된 모든 이름을 검사하므로 `from io import open as f`도 예외가 아닙니다.
검사가 판단하지 못하는 경우는 기존 결과를 유지합니다. 보호 파일을 인자나 옵션 값(`--file=.env`)으로 전달할 때도 그렇습니다.
`-c` 표기가 `-c code`, `-ccode`, `-Ic code` 중 무엇이든 heredoc이 아닌 인라인 코드를 분류합니다.
Python 인라인 코드, heredoc, 표준 입력 파일, 스크립트 파일은
프로세스를 실행하거나 클라우드·데이터베이스 SDK를 가져오면 쓰기입니다. 키워드 인자를 포함한 리터럴 프로세스 명령은 분류합니다.
파괴적 프로세스 명령, 파괴적 SDK 호출 이름, 프로세스를 실행하거나 SDK를 가져온 Python 안의 파괴적 텍스트는 매번 묻습니다.
나머지 Python은 문자열에 CLI 명령이 있어도 통과하지만(`python3 -c` 코드는 읽기가 되지 않습니다),
명시적인 `--execute`가 있으면 쓰기입니다. Node와 그 밖의 셸·Python이 아닌 실행 파일은 통과합니다.
읽기는 승인 없이 실행하고 쓰기는 세션 쓰기 승인이 필요합니다. 파괴·강제·비밀 호출은 기존 규칙을 따릅니다.
읽을 수 없거나 더 큰 스크립트 파일은 분류 불가입니다. 검사한 셸 스크립트가 대상 CLI를 언급하거나
`boto3`, `azure`, `kubernetes`, `psycopg`, `psycopg2`, `pymysql`, `sqlalchemy`, `pymongo`, `redis`,
`google.cloud`를 가져오지만 호출을 분류하지 못한 경우도 분류 불가입니다. 이런 호출은 텍스트에 파괴적 작업이 없으면 쓰기이고,
있으면 매번 묻습니다. 이들 중 아무것도 언급하지 않는 스크립트는 통과합니다. 플러그인 자체의
`python3 <plugin root>/scripts/host_settings.py check`는 읽기, `apply`는 세션 쓰기입니다. 단 스크립트가 이 가드의
플러그인 루트에 속하고 앞에 인터프리터 옵션이 없을 때만 그렇습니다.

MCP 도구 이름은 `_`, `-`, camelCase 경계에서 나뉩니다. 이름의 파괴적 단어는 매번 묻습니다.
문자열 필드 `sql`, `statement`, `queryText`와, SQL 문장처럼 시작하는 `query` 필드(검색어는 제외)에는 DataGrip SQL
분류기를 적용합니다. 읽기는 승인 없이, 파괴적 문장은 매번 승인 후 실행하고, 나머지 SQL은 세션 쓰기입니다.
실행 이름 단어(`repl`, `exec`, `execute`, `eval`, `run`, `code`, `script`, `command`)는 코드 입력을 `language` 필드나
생김새에 따라 명령 또는 Python 스크립트처럼 분류합니다. 비밀·금지 결과는 평소처럼 거부하고, 매번 묻는 결과는 매번 묻고,
그 밖의 경우는 코드가 없는 도구를 포함해 세션 쓰기입니다. 명시적인 `action` 입력은 일반 이름 동사보다 우선합니다.
파괴적 동작은 매번 묻고, 파괴적 SQL 필드는 그 밖의 동작보다 우선합니다.
SQL이 없으면 읽기 동작은 읽기, 쓰기 동작은 쓰기입니다.
이 입력이 없으면 읽기 동사로 시작하는 이름은 뒤에 쓰기 단어가 있어도 읽기이고, `getjiraissue`처럼 소문자 한 덩어리로 쓴 이름은
읽기 동사로 시작하고 뒤에 쓰기·삭제 단어가 없으면 읽기입니다.
그 밖에는 쓰기 단어가 읽기 단어보다 우선하고, 아는 동사가 없으면 쓰기입니다.
세션 쓰기 승인 하나로 DataGrip과 tabularis 쓰기를 포함한 해당 세션의 모든 비파괴적 MCP 쓰기가 허용됩니다.

`mcp__tabularis__run_query`의 `connection_id`는 tabularis의 `connections.json`에서 ID나 이름으로 찾습니다.
설정 폴더는 macOS의 `~/Library/Application Support/tabularis`, Linux의 `$XDG_CONFIG_HOME/tabularis` 또는
`~/.config/tabularis`, Windows의 `%APPDATA%\tabularis`입니다. 테스트에서는 `HEI5ENBUG_TABULARIS_DIR`로 바꿉니다.
가드는 `id`, `name`, `params.driver`만 추출하며 다른 연결 필드나 비밀번호는 출력하지 않습니다.
`postgresql`에는 PostgreSQL 분류기를, `sqlserver`·`sqlserver-entra`에는 SQL Server 분류기를 적용합니다.
운영이 아닌 연결의 읽기는 승인 없이 실행하고, 비파괴적인 쓰기는 세션 쓰기입니다. 다른 드라이버,
알 수 없는 연결, 읽을 수 없는 파일, 해석할 수 없는 쿼리 텍스트는 세션 쓰기 승인을 사용합니다.
코드의 `delete`·`drop`·`truncate`(리터럴, 주석, 따옴표 식별자 안은 제외)와 SQL 분류기가 파괴적으로 판단한 문장은 매번 묻습니다.
`DO`·`EXEC`·`EXECUTE`·`CALL`로 시작하는 문장도 여기에 포함됩니다. 다만 위에서 말한 운영이 아닌 PostgreSQL 연결의 대상 지정
`DELETE`와 안전한 `DO`는 세션 쓰기입니다.
이런 쿼리는 `sql:always:tabularis:<id>:<digest>` 키를 씁니다.
다른 tabularis 도구는 기존 이름 규칙을 따릅니다.

**운영 데이터베이스 읽기.** `run_query`와 DataGrip `execute_sql_query`에서 연결 이름을 대소문자 경계, 공백, `_`, `-`, `.`, 괄호로 나눈 단어에
`dev`, `develop`, `development`, `test`, `testing`, `qa`, `stg`, `stage`, `staging`, `sandbox`, `local`, `demo` 중 하나가 있거나
이름에 `개발`, `테스트`, `스테이징`, `검증`, `로컬`이 들어 있고, `prod`, `production`, `prd`, `live` 단어와 `운영`이 없으면
운영이 아닙니다. 그 밖의 모든 연결은 운영이며, 알 수 없는 연결과 `승인`이 든 이름도 포함합니다.
- `ANALYZE`가 없는 PostgreSQL `EXPLAIN [(옵션)] <읽기>`는 어떤 연결에서도 읽기입니다. 운영 연결에서 성공하면 `PostToolUse` 훅이
  추정 비용과 행 수(JSON `Plan`의 `Total Cost`와 `Plan Rows`, 또는 텍스트 계획 첫 줄)를 호스트·세션·도구·연결·정확한 읽기 텍스트(앞뒤
  공백과 끝의 세미콜론만 뺀 것)별로 30분 동안 상태 파일에 기록합니다. 오류나 해석할 수 없는 결과는 기록하지 않습니다.
- 두 한도 이하인 기록이 있는 PostgreSQL 운영 읽기는 실행합니다. 기록이 없으면 먼저 실행할 `EXPLAIN (FORMAT JSON) <읽기>` 형식을 알려 주며
  거부하고, 한도를 넘거나 기록을 해석할 수 없으면 매번 묻습니다.
- SQL Server 운영 읽기는 계획 없이(두 도구 모두 SQL Server 예상 계획을 돌려줄 수 없습니다) 실행하며, `SET LOCK_TIMEOUT 5000;`과
  `SET DEADLOCK_PRIORITY LOW;` 접두가 항상 맨 앞에 붙습니다. 읽기가 `LOCK_TIMEOUT`을 0부터 한도 밖의 값으로 정하거나
  `DEADLOCK_PRIORITY`를 `LOW`나 -5 이하 정수가 아닌 값으로 정하면 매번 묻습니다. tabularis `limit`은 요청값(기본 100)과 최대 결과 행 수 중
  작은 값이 됩니다.
- 한도 기본값은 `postgres_max_cost` 10000, `max_estimated_rows` 100000, `max_result_rows` 1000, `sqlserver_lock_timeout_ms` 5000입니다.
  `$XDG_CONFIG_HOME/hei5enbug-agent-setup/db-read-limits.json`(기본 `~/.config`)에
  `{"default": {...}, "connections": {"<연결 이름 또는 id>": {...}}}`를 둘 수 있고, 연결 항목은 키별로 default를 덮어씁니다.
  알 수 없는 키, 0 이하이거나 숫자가 아닌 값, 잘못된 파일은 무시합니다. 편집 도구나 셸로 이 파일이나 그 폴더를 바꾸면, 따옴표나
  이스케이프로 이름을 나눠도 매번 묻습니다. 그 폴더 안에서 대상을 풀 수 없는 쓰기도 묻습니다. 다른 곳에서 풀 수 없는 값으로 조립한
  경로는 잡지 못합니다.
- `approval_guard`를 끄면 아무것도 기록하지 않으므로 읽기를 막지 않습니다.

`curl`은 GET/HEAD 이외의 요청 메서드와 `-d`, `--data*`, `-F`, `--form`, `-T`, `--upload-file`, `--json`이 없으면
읽기입니다. 나머지는 `curl <METHOD> on <scheme://host>`로 보이는 쓰기이며, DELETE 같은 파괴적 메서드는 매번 묻습니다.
argv의 `-u`·`--user` 또는 `Authorization` 헤더는 메서드 자체의 결과에 민감 읽기 승인을 더합니다. 읽기는
`sensitive:session`이 필요하고, 쓰기는 `write:session`과 `sensitive:session`이 모두 필요하며, 파괴적 메서드는 여전히
매번 묻습니다. 프롬프트가 보여 주거나 대기 상태에 저장하는 설명은 `-u`·`--user` 값, `Authorization`·`Cookie`·`X-Api-Key`
헤더 값, URL의 사용자 정보, 키 이름이 비밀을 가리키는 `key=value`·`--key value` 쌍을 가립니다.

Claude `Read`와 Bash 읽기(`cat`, `less`, `head`, `tail`, `grep`, `rg`)가 `~/.kube/config`, 모든 `KUBECONFIG` 경로,
`~/.aws/credentials`, `~/.aws/config`, `~/.azure/**`, `~/.config/gcloud/**`, `~/.pgpass`, `~/.docker/config.json`,
`~/.netrc`, `.env*` 파일을 읽으면 민감 호출입니다. 단 이름이 `.example`, `.sample`, `.template`, `.dist`로 끝나는
템플릿은 제외합니다. 필터 없는 `printenv`, 명령 없는 `env`,
`kubectl exec ... env|printenv`, `docker inspect`, `docker exec ... env`, `terraform`의 state와 JSON·raw 출력,
`helm get all`·`get manifest`·`get values`도 같습니다. 한 세션의 첫 민감 읽기는 한 번 묻고, 그 뒤로는 모든 민감 읽기를
세션이 끝날 때까지 실행합니다. 비밀 거부는 그대로여서, 비밀 값을 출력하는 명령은 승인한 뒤에도 거부합니다.
비밀이 아닌 변수 이름만 지정한 `printenv`는 읽기입니다. `env`나 `printenv`에 지원되는 `grep`·`rg` 필터를 적용하고,
일치한 이름 중 비밀 이름이 없으면 읽기입니다. 개수만 출력하는 경우도 읽기입니다. 변수 이름만 남기거나 값을 가리는
파이프도 읽기입니다. `cut -d= -f1`, `awk -F= '{print $1}'`, 이름에 고정한 패턴의 `grep -o`, `grep -c`, 첫 `=` 뒤를 전부
바꾸는 `sed` 치환이 그렇습니다. 확인할 수 없는 필터는 계속 민감 호출입니다.
지원되는 필터는 명령 목록 안에서도 같은 분류를 유지하며, 가드는 다른 요소의 결과와 기존 규칙대로 합칩니다.
다만 `export`, 변수 대입, `source`, `eval`처럼 목록이 먼저 환경을 바꿀 수 있으면 이 규칙을 적용하지 않습니다.
`python3 <plugin root>/skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py status ...`는 해석된 스크립트가
이 가드의 플러그인 루트에 속하고 앞에 인터프리터 옵션이 없으면 읽기입니다.

Claude Code에서는 승인이 필요한 호출에 위의 한 줄 이유를 담은 `PreToolUse` `ask`를 내고, 세션이 이미 승인한 호출에는
`allow`를 냅니다. 가드는 호스트 자체의 `PermissionRequest` 프롬프트에도 응답하므로 세션 쓰기 승인 하나가 그 프롬프트를 흡수합니다.

- 프로젝트 폴더(`CLAUDE_PROJECT_DIR`, 없으면 작업 폴더) 안이나 로컬 프로젝트·프로젝트·사용자 설정의
  `permissions.additionalDirectories` 안 경로에 대한 편집 도구(`Edit`, `Write`, `MultiEdit`, `NotebookEdit`)는 허용합니다.
  `$`가 든 경로, 가드의 상태 폴더, `.env*`와 자격 증명 파일 같은 보호 경로, 호스트의 보호 폴더와 파일(`.git`, `.claude`,
  `.vscode`, `.idea`, `.husky`, 셸 시작 파일, `.gitconfig`, `.gitmodules`, `.mcp.json`, `.claude.json`, `.ripgreprc`)이
  절대 경로 어디에든 있는 경로(허용된 폴더 자체가 그중 하나여도 마찬가지), 그 폴더 밖의 경로는 호스트에 맡깁니다.
- 가드가 다루지 않는 Bash 명령도 허용합니다. 단 `ssh`, `scp`, `rsync`, `sudo`, `su`, `doas`를 실행하거나, 재귀 삭제,
  강제 푸시, `dd of=` 쓰기, `mkfs` 실행을 하거나, 파괴적 작업이 이름으로 든 명령은 제외합니다. 가드가 분류했고 세션이 이미
  승인한 호출도 허용합니다. 읽기, 매번 묻는 호출, 그 밖의 경우에는 결정을 내지 않으므로 호스트가 결정합니다.
- 세션 쓰기 승인이 생기기 전에는 이런 첫 편집이 호스트의 네이티브 프롬프트를 보여 줍니다. 가드는 그 요청을 기록해 두고,
  편집이 끝나면 `write:session`을 기록합니다. 그래서 네이티브 프롬프트에서 승인한 첫 편집이 쓰기 승인을 주고, 이어지는
  `kubectl apply`는 다시 묻지 않습니다. 아래에서 설명하는 요청 한도를 다 쓰면 편집 프롬프트를 다시 보여 주는 대신 중단
  메시지와 함께 거부합니다.

한계: auto 모드에서는 가드가 허용한 호출을 호스트의 분류기가 여전히 거부할 수 있으며, 플러그인은 그 거부를 덮어쓰지
않습니다. `PermissionDenied` 훅의 `retry`는 모델에게 다시 시도해도 된다고 알릴 뿐이므로 훅으로도 되돌릴 수 없습니다.

Codex에서는 `PreToolUse`가 물을 수 없으므로, 준비된 상태에서는 네이티브 승인 창이 승인을 맡습니다.

- 승인이 필요한 Bash 호출은 `PreToolUse`가 명령을 `<plugin root>/scripts/approve_wrapper.sh '<원래 명령>'`으로 바꿔
  허용합니다. 래퍼는 인자 하나에 `bash -c`를 실행하는 두 줄짜리 스크립트입니다. 플러그인 소유 규칙 파일
  `~/.codex/rules/hei5enbug.rules`에는 래퍼 경로에 대한 `decision="prompt"` `prefix_rule` 하나가 있어서, Codex가 원래
  명령이 보이는 승인 창을 띄웁니다. 가드는 분류하기 전에 래퍼를 풀므로 판정은 원래 명령의 판정이고, 파괴적인 안쪽 명령이
  든 래퍼 호출도 계속 매번 묻습니다. `sh`, `bash`, `zsh`가 평범한 단어 하나로 래퍼를 실행하는 호출은, 단독이든
  `env`, `command`, `exec`, `nohup` 같은 래퍼 뒤에 있든 그 단어의 텍스트로 분류합니다. 인자 개수가 다르거나
  `source`, 치환, `xargs`를 쓰는 것처럼 래퍼 경로를 이름으로 든 그 밖의 명령은 "Unrecognized approval wrapper call"로
  매번 묻고, 래퍼 파일 자체는 분류하지 않습니다.
- MCP 호출은 서버의 `default_tools_approval_mode = "prompt"`가 Codex 창을 띄우게 합니다. 읽기는 감싸지 않으며,
  `PermissionRequest`가 `allow`로 응답해 창을 건너뜁니다. DataGrip 쿼리도 `datagrip_guard.py`를 통해 같은 경로를 따릅니다.
  세션에 한 번 묻는 호출만 창을 쓰고, 파괴적인 도구와 쿼리처럼 매번 묻는 MCP·DataGrip 호출은 창이 준비돼 있어도 코드 방식을
  유지합니다. 창의 모드는 `config.toml`에서 오므로, 명령줄 옵션으로 MCP 서버를 `prompt`에서 다른 모드로 옮겨 시작한 세션은
  그 서버의 비파괴적 쓰기를 승인 없이 실행할 수 있습니다. `apply_patch` 편집은 Codex에 맡깁니다.
- `PermissionRequest`는 호출이 필요로 하는 승인을 세션이 이미 가졌으면 창을 건너뜁니다. 그렇지 않으면 창이 줄 승인을
  기록해 둡니다. Codex는 사용자가 진행을 고른 뒤에만 호출을 실행하므로, 호출이 끝나면 `PostToolUse`나
  `PostToolUseFailure`가 `write:session`이나 `sensitive:session`을 기록합니다. 매번 묻는 Bash 호출은 창에서 매번 묻고 승인을
  남기지 않습니다. 사용자가 거절해도 승인이 남지 않습니다.

네이티브 창에는 다음이 모두 필요합니다. 훅 이벤트가 권한 모드 `default`를 알리고, 세션이 역할 실행기의 자식이 아니고,
세션 ID를 쓸 수 있고, `rules/hei5enbug.rules`가 이 플러그인 버전이 쓰는 텍스트와 정확히 같고, MCP 도구의 승인 모드가
`~/.codex/config.toml`에서 `prompt`여야 합니다. 그렇지 않으면 아래 코드 방식이 적용됩니다. `codex exec`이나
권한 우회 실행처럼 창을 보여 줄 수 없는 세션, 자식 worker, [호스트 설정](#호스트-설정)이 규칙 파일이나 MCP 모드를 쓰기
전이 여기에 해당합니다. 신뢰하지 않은 Codex 훅은 가드를 전혀 실행하지 않으므로 어떤 방식도 적용되지 않습니다. 아래의
신뢰 경고를 참고하세요.

쓰기 전에 묶음 승인을 요청할 수 있습니다.

```bash
python3 <plugin root>/scripts/approval_guard.py request --key write:session --why 'Deploy the requested change and update the issue'
```

`--key`는 `write:session`이나 `sensitive:session`을 받으며 여러 번 쓸 수 있습니다. Claude는 이유를 보여 주며 묻고,
질문한 호출이 `PostToolUse`나 `PostToolUseFailure`에 도달할 때만 세션 키를 기록합니다. 승인한 쓰기가 실패해도 세션 승인을
남깁니다. 기존 승인으로 허용한 호출은 그 승인을 다시 기록하지 않습니다. Codex는 묶음 코드 하나와 함께 거부하고,
사용자가 `승인 <CODE>`를 입력하거나 대기 요청이 하나일 때 `승인`만 입력하면 기록합니다.
명령은 키를 출력하고 0으로 종료하며 승인 상태를 직접 쓰지 않습니다.
예전 `<cli>:<kind>@<target>`과 `mcp:session` 형식도 받아 같은 세션 쓰기 승인으로 처리합니다. 파괴·강제 종류,
`sql:always:*`, 파괴적인 `mcp:<tool>` 키는 사전 승인할 수 없으므로 매번 묻는 작업은 요청할 수 없습니다.
명시적인 `unclassified` 요청 키 형식도 거부하지만, 세션 쓰기 승인은 비파괴적인 분류 불가 호출에도 적용됩니다.

Codex에서 코드 방식이 적용되면 승인이 필요한 호출을 두 줄짜리 코드와 함께 거부합니다. 영어로는 다음과 같습니다.

```text
Approval required: kubectl apply on (default) dev/web. Approving also covers later writes in this session. Ask the user to reply `approve K7M2QX` (or just `approve` when only one is pending).
After the user replies with the code, retry this exact call immediately and continue the task without asking again.
```

한국어로는 첫 줄이 다음과 같고 둘째 줄은 그대로입니다.

```text
승인 필요: kubectl apply on (default) dev/web. 승인하면 이 세션의 쓰기도 더 묻지 않습니다. 사용자에게 `승인 K7M2QX` 입력을 요청하세요(대기 요청이 하나면 `승인`만).
```

사용자는 채팅에 `승인 <CODE>` 또는 `approve <CODE>`를 입력합니다. 대기 중인 요청이 정확히 하나이면 `승인`이나
`approve`만 입력해도 됩니다. `UserPromptSubmit` 훅이 승인을 기록하면 에이전트는 같은 호출을 즉시 재시도하고
다시 묻지 않은 채 작업을 계속합니다. 양쪽 호스트 모두 `UserPromptSubmit` 컨텍스트에 승인한 설명과 이 재시도 지침을 제공합니다.
코드는 거부된 호출의 모든 키를 덮습니다. 매번 묻는 키는 한 번짜리 승인으로, 세션 키는 세션 승인으로 덮습니다.
세션 승인은 세션이 끝날 때까지 유지되며, 7일 동안 활동이 없는 세션의 상태는 지웁니다.
Codex의 일회 승인이 진행 중이고 `PostToolUse`나 `PostToolUseFailure`가 없으면 같은 키의 다음 시도는 코드 없이 한 번 재사용할 수 있습니다.
승인은 그 재시도로 옮겨 가며, 그 호출도 중단되면 새 승인을 요청해야 합니다.
`PermissionRequest`는 승인을 가진 호출만 허용하고 `PostToolUse`나 `PostToolUseFailure`가 정리합니다.

각 세션은 호출이 완료되거나 사용자가 새 프롬프트를 보낼 때까지 발급한 승인 요청을 키별로 셉니다. Claude의 확인 요청,
Codex의 네이티브 창, Codex의 코드 응답이 대상이며, 같은 대기 코드를 다시 보여 주는 것도 포함합니다. 사용자의 마지막
프롬프트 이후 `PostToolUse`나 `PostToolUseFailure` 없이 요청 세 번에 도달하면 네 번째 요청을 거부합니다. 영어 안내 문구는
“This approval was requested three times since the user's last message without the call
completing (declines included); stop retrying and tell the user.”입니다. 이미 받은 승인은 세 번째 코드로 승인한 재시도까지
실행합니다. `PostToolUse`나 `PostToolUseFailure`는 끝난 호출의 키별 횟수를 초기화하고, `UserPromptSubmit`은 모든 횟수를
초기화하므로, 중단된 뒤 사용자가 요청한 쓰기는 다시 승인을 묻습니다. 이미 세션 승인된 키는 다른 키의 요청 한도를 쓰지 않습니다.

에이전트는 스스로 승인할 수 없습니다. `approval_guard.py`, `datagrip_guard.py`, `approval_state.py`를 프로그램으로,
`-m`으로, 또는 이를 가져오는 Python 코드로 실행하는 Bash 명령은 두 호스트 모두에서 거부됩니다.
승인 또는 heartbeat 상태 디렉터리를 가리키는 명령은 모든 단순 명령이 허용된 읽기 명령일 때만 예외입니다.
허용 목록은 `ls`, `cat`, `head`, `tail`, `grep`, `wc`, `stat`, `file`, `find`, `echo`입니다. `find`는 `-type`, `-name`,
`-maxdepth`, `-print` 같은 읽기 옵션만 쓸 수 있고 글롭 문자를 쓸 수 없습니다. 명령에는 중괄호, 치환, 변수 대입 접두사,
`/dev/null` 이외의 출력 리다이렉션이 없어야 합니다. 허용하는 변수는 `$HOME`, `${HOME}`, `$XDG_STATE_HOME`,
`${XDG_STATE_HOME}`, `${XDG_STATE_HOME:-<절대 경로>}`뿐이며, 각각 단어의 맨 앞에서 `/`로 이어지는 경로 접두로만 쓸 수 있습니다.
예: `ls "$HOME/.local/state/hei5enbug-agent-setup/approvals"`. 가드는 경로를 검사하기 전에 이 변수를 풉니다. 그 밖의
`$`, `$(`, 백틱, `<(`, `>(`, 중괄호는 거부하며, 거부 사유가 원인을 밝힙니다(예: `It was denied because of "$(".`).
`cat`이나 `rg`로 가드 파일을 읽기만 하는 명령은 거부되지 않습니다. 위에서 검증한 `request` 명령만 실행 예외입니다.
두 상태 디렉터리 안의 파일 편집은 `apply_patch` 패치가 가리키는 경로를 포함해 양쪽 호스트 모두 거부합니다.

비밀 값이 필요한 명령은 비밀 도우미를 사용합니다: `python3 <plugin root>/scripts/secret_exec.py --secret
DB_PASSWORD=k8s:<context>/<namespace>/<secret>/<key> -- <command>`. 소스는 `k8s:`, `keyvault:<vault>/<name>`,
`aws:<secret id>[#<json key>]`, `gcp:<project>/<name>[/<version>]`입니다. `--file VAR=<source>`는 값 대신 임시 파일의 경로를
넘깁니다. 값은 환경 변수나 임시 파일을 통해서만 명령에 전달되며, 도우미가 명령 출력에서 값을 가립니다. 조회가 실패하면 도우미는 소스와 조회 명령의 종료 코드만 알리고, 조회 명령의
stderr는 출력하지 않습니다. 각 조회의 제한 시간은 30초입니다. 시간이 지나면 소스와 `timed out`을 알리고 2로 종료합니다.

역할 실행기의 자식에 `HEI5ENBUG_PARENT_SESSION=<host>:<session_id>`가 있으면 부모의 승인 키도 읽으며 상태는 바꾸지
않습니다. 잘못된 값은 무시합니다. 자식은 `UserPromptSubmit`에서 코드를 기록하거나 `request`를 실행할 수 없습니다.
부모에게 없는 세션 승인이 필요한 호출은 메인 세션에서 요청(`request --key write:session` 또는 `--key sensitive:session`)한
다음 다시 시도하라는 안내와 함께 거부합니다. 자식은 부모 세션이 가진 `write:session`과 `sensitive:session` 승인을 그대로
사용하며, Codex 자식은 네이티브 창을 쓰지 않습니다. 자식에서 매번 묻는 작업은 모두 거부하며 메인 세션이 직접 실행합니다.
편집 가능한 Claude 자식은 `--tools`와 `--allowedTools`에 `Bash`도 받지만, 자식의 가드는 승인되지 않은 쓰기와
매번 묻는 작업을 계속 거부합니다.

가드가 다루는 쓰기에 Claude `permissions.ask` 규칙을 추가하지 마세요. 이 규칙은 세션 승인 뒤에도 매번 확인을 요청합니다.
Claude의 `defaultMode: dontAsk`는 가드가 요청하는 승인을 거부합니다. 가드가 허용하는 `kubectl get` 같은 읽기를 `prompt`하거나
금지하는 사용자 소유 Codex `rules/*.rules` 파일도 그대로 적용됩니다. [호스트 설정](#호스트-설정)은 이런 설정을 보고만 하고
고치지 않습니다.

유효한 세션 ID가 있는 모든 이벤트는 토글 검사 전에 가능한 경우
`$XDG_STATE_HOME/hei5enbug-agent-setup/heartbeats/<host>-<session_id>`와 `.<EventName>` 파일을 만들거나 갱신합니다.
`PreToolUse`는 현재 `hooks/hooks.json`의 SHA-256도 `heartbeats/confirmed-<host>`에 한 줄로 기록합니다.
해시가 없거나 다르면 `UserPromptSubmit`이 세션당 한 번 경고를 추가하고 세션 상태에 표시 여부를 저장합니다.
경고는 훅 변경 뒤 가드의 도구 검사가 아직 관찰되지 않았다고 설명합니다. Codex 사용자에게 `/hooks`에서 플러그인 훅을
신뢰하도록 안내하고, 그전에는 쓰기가 승인 없이 실행될 수 있다고 알립니다.
분류기 예외는 “The approval guard failed to check this call” 이유로 매번 승인을 요청하고, stderr에
`approval_guard: classifier error: <예외 이름>`을 남깁니다. 가드를 끄면 여전히 아무것도 출력하지 않습니다.

승인 가드는 보안 경계가 아니라 안전장치입니다. 셸 전체 권한을 가진 에이전트는 우회할 수 있습니다. 가드가 다루지 않는 호출은 호스트의 기존 권한 절차를 따릅니다. 승인 상태는
`$XDG_STATE_HOME/hei5enbug-agent-setup/approvals/`(기본값 `~/.local/state`) 아래에 호스트와 세션마다 한 파일씩 저장됩니다.
승인은 세션이 끝날 때까지 유지되고, 7일 동안 활동이 없는 세션 파일은 다른 승인을 쓸 때 지워집니다. 가드를 끄려면
`approval_guard`를 `false`로 두거나, Codex에서는 `HEI5ENBUG_APPROVAL_GUARD=false`를 설정하세요.
Codex에서는 `/hooks`에서 훅을 신뢰해야 합니다.

`approval_scope` 옵션은 가드가 얼마나 자주 묻는지 정합니다. 기본값 `tiered`는 위 설명대로 동작합니다.
`session`은 세션당 한 번 묻습니다. 어떤 종류든 첫 승인이 그 세션의 이후 호출을 모두 덮습니다. 다만 세 가지는 계속
매번 묻고, 그 승인은 해당 호출에만 적용됩니다. 커밋하지 않은 작업 버리기(`git reset --hard`, `git clean`, 작업 트리
변경을 버리는 `git checkout`이나 `git restore`, `git worktree remove --force`, 커밋하지 않은 변경이나 무시되지 않은 새 파일이 있는 파일 삭제), 운영 DB 연결의 삭제 문장, 운영
context의 `kubectl delete` 같은 운영 인프라 삭제입니다. 연결이나 context 이름에 운영 단어가 있거나 개발 단어가 없으면
운영으로 보므로, 알 수 없는 이름은 운영으로 남습니다. 거부되는 호출은 두 범위 모두에서 계속 거부됩니다.

### 호스트 설정

일부 호스트 설정은 승인 프롬프트를 늘리거나 가드가 실행되지 못하게 합니다. `scripts/host_settings.py`는 이를 점검하고,
Codex에서만 짧은 허용 목록을 고칩니다.

```bash
python3 <plugin root>/scripts/host_settings.py check [--host claude|codex] [--json]
python3 <plugin root>/scripts/host_settings.py apply [--host claude|codex] [--json]
```

두 명령 모두 `--claude-dir`, `--codex-home`, `--codex-bin`도 받습니다. 호스트는 기본적으로 명령을 실행하는 호스트입니다.
`check`는 읽기이며 아무것도 쓰지 않습니다. 문제마다 한 줄을 보고합니다.

- Claude Code: `defaultMode`가 `dontAsk`인 경우와 Bash나 MCP 도구에 적용되는 `permissions.ask` 규칙(최대 세 개 표시).
- `~/.codex/config.toml`에 `[features] plugin_hooks`가 `true`가 아닌 경우(양쪽 호스트).
- Codex만: 플러그인 훅이 확인되지 않은 경우(heartbeat 해시 불일치), `config.toml`이 올바른 TOML이 아닌 경우,
  `rules/hei5enbug.rules`가 없거나 읽을 수 없거나 구버전이거나 플러그인 소유가 아닌 경우, MCP 서버에 `prompt` 승인 모드가 없는 경우,
  `approval_guard`가 꺼져 있어 모드 단계를 건너뛴 경우, 가드가 다루는 MCP 도구에 읽기에도 묻는 도구별 `prompt`가 있는 경우.
- Codex만: 사용자 소유 `rules/*.rules` 파일에서 `kubectl get`, `helm list`, `az show`, `git status` 같은 읽기 접두에 대한
  `prompt`·`forbidden` 규칙.

`apply`는 이 허용 목록만, 그것도 Codex에서만 바꿉니다. Claude Code에서는 아무것도 바꾸지 않고 그 사실만 알립니다.

- `[features] plugin_hooks`: `codex features list`에 보이면 `codex features enable plugin_hooks`로 켭니다. 그 명령이 없으면
  직접 설정하라고 알립니다.
- 플러그인 소유 파일 `~/.codex/rules/hei5enbug.rules`: 플러그인 버전의 텍스트로 만들거나 갱신합니다. [승인 가드](#승인-가드)가
  쓰는 래퍼 스크립트에 대한 `prompt` 규칙을 담고 있습니다. 그 경로가 심볼릭 링크이거나 기존 파일에 플러그인 소유 헤더
  줄이 없으면 `apply`는 알리기만 하고 아무것도 쓰지 않습니다.
- `approval_guard`가 켜져 있는 동안 모든 `[mcp_servers.<name>]` 표의 `default_tools_approval_mode = "prompt"`와, 이미 다른
  모드를 지정한 도구별 표의 `approval_mode = "prompt"`. 그 줄만 고치며, 결과가 의도대로 파싱되지 않으면 아무것도 쓰지 않습니다.

`apply`는 파일을 바꾸기 전에 `<file>.bak-hei5enbug-<YYYYMMDD>`로 복사해 두며, 하루에 한 번만 만듭니다. 바꾼 항목마다 한 줄을
출력하고, 두 번째 실행은 아무것도 바꾸지 않습니다. 사용자 소유 규칙 파일, Claude Code 설정, 훅 신뢰는 절대 고치지 않습니다.

세션 시작 시 훅이 하는 일은 `host_settings` 옵션이 정합니다. `apply`(기본값)는 Codex에서 먼저 `apply`를 실행해 바꾼 내용을 알리는
안내 한 줄을 추가하고, 이어서 `check`가 찾은 나머지 문제를 보고합니다. `report`는 보고만 합니다. 다른 값은 `apply`로 취급합니다.
Claude Code는 이 옵션을 `/config`에서 읽고, Codex는 `HEI5ENBUG_HOST_SETTINGS`에서 읽습니다.


## 기능 옵션

끌 수 있는 boolean 기능은 일곱 가지이며 각각 기본값은 켜짐입니다. Claude Code의 구현 worker 경로, worker 모델과 사고 강도,
검토 모델, 호스트 설정 모드, 훅 Python 인터프리터, 이 플러그인과 함께
새로고침할 플러그인(`refresh_plugins`)은 문자열 옵션입니다. 경로는 `auto`, `codex`, `haiku`, `sol`, `sonnet` 중 하나를 고르고, 값이 비어 있거나 알 수 없으면 `auto`를 씁니다.
`auto`에서는 메인 세션이 작업마다 worker를 고릅니다. 호스트 설정 모드는 `apply`와 `report` 중 하나를 고르고, 값이 비어 있거나
알 수 없으면 `apply`를 씁니다. 이 모드는 `SessionStart`가 허용 목록의 Codex 설정을 바꿔도 되는지 정합니다.
[호스트 설정](#호스트-설정)을 참고하세요.
검토 모델은 독립 검증과 스킬 검토 역할을 `high`로 실행하며,
[모델 라우팅](../../instructions/model-routing.md#keep-role-settings-fixed)의 사고 강도 규칙에 따라 `xhigh`로 실행합니다.
고정된 일곱 모델 ID 중 하나를 고릅니다. 값이 비어 있거나
알 수 없으면 `gpt-6-astra`를 씁니다. 플러그인 옵션은 `/config`나 `claude plugin configure`에서 설정합니다. Codex에서는 세션 시작 전에 환경변수를
설정합니다. boolean 기능은 값이 `false`, `0`, `off`, `no`(대소문자 무시)이면 꺼집니다.

Claude Code `worker` 에이전트는 `worker_model`과 `worker_effort`로 실행됩니다. mod가 이 값으로 worker를 생성하며, 잘못된 값이면 레지스트리 고정값을
씁니다. 세션 컨텍스트는 이 값을 `Worker agent model: <model> at <effort>.` 줄로 알립니다. Codex에는 플러그인 설정 화면이 없으므로 세션 훅이
Claude Code가 저장한 설정(`~/.claude/settings.json`의 `pluginConfigs`, 또는 `CLAUDE_CONFIG_DIR` 아래)에서 `codex_worker_model`과
`codex_worker_effort`를 읽기 전용으로 읽습니다. 환경변수가 이 값을 덮어쓰고, 잘못된 값이면 한 줄 안내와 함께 기본값을 씁니다. 세션 컨텍스트는
`Codex worker model: <model> at <effort>.` 줄로 알립니다. 값은 다음 Codex 세션부터 적용되며, 이 값을 읽을 때는
Codex 설정이나 Claude 설정을 쓰지 않습니다. Codex 설정을 쓰는 것은 [호스트 설정](#호스트-설정)의 허용 목록 변경뿐입니다.

| 기능 | Claude Code `/config` 키 | Codex 환경변수 |
|---|---|---|
| 내장 서브에이전트 차단 | `agent_guard` | `HEI5ENBUG_AGENT_GUARD` |
| 역할 모델 고정 | `role_pinning` | 해당 없음 |
| 도구 호출 위험 라벨 | `risk_highlight` | 해당 없음 |
| 서브에이전트 작업 현황판 | `work_board` | 해당 없음 |
| 도구 결과 비밀값 가리기 | `secret_redaction` | 해당 없음 |
| 구현 worker 경로 | `implementation_worker` (`auto`, `codex`, `haiku`, `sol`, 또는 `sonnet`) | 해당 없음 |
| Claude Code worker 모델과 사고 강도 | `worker_model` (기본 `claude-haiku-5-5`), `worker_effort` (기본 `high`) | 해당 없음 |
| Codex worker 모델과 사고 강도 | `codex_worker_model` (`gpt-5.6-luna` 또는 `gpt-6.1-sol`, 기본 `gpt-5.6-luna`), `codex_worker_effort` (`high` 또는 `xhigh`, 기본 `high`) | `HEI5ENBUG_CODEX_WORKER_MODEL`, `HEI5ENBUG_CODEX_WORKER_EFFORT` |
| 검토 모델 | `review_model` (고정 모델 ID, 기본 `gpt-6-astra`) | 해당 없음 |
| 응답 언어 가드 | `language_guard` | `HEI5ENBUG_LANGUAGE_GUARD` |
| DataGrip 쿼리 가드 | `datagrip_guard` | `HEI5ENBUG_DATAGRIP_GUARD` |
| 승인 가드 | `approval_guard` | `HEI5ENBUG_APPROVAL_GUARD` |
| 승인 범위 | `approval_scope`(`tiered` 또는 `session`, 기본값 `tiered`) | `HEI5ENBUG_APPROVAL_SCOPE` |
| 다른 저장소에 Orca 워크트리 사용 | `orca_worktree` | `HEI5ENBUG_ORCA_WORKTREE` |
| 호스트 설정 모드 | `host_settings` (`apply` 또는 `report`, 기본 `apply`) | `HEI5ENBUG_HOST_SETTINGS` |
| 훅 Python 인터프리터 | `python` (절대 경로, 기본값 빈 문자열) | `HEI5ENBUG_PYTHON` |
| 이 플러그인과 함께 새로고침할 플러그인 | `refresh_plugins` (쉼표로 구분한 `plugin@marketplace` ID, 기본값 빈 문자열) | `HEI5ENBUG_REFRESH_PLUGINS` |
| `~/.codex/AGENTS.md`의 서브에이전트 허용 블록 | 해당 없음 | `HEI5ENBUG_SUBAGENT_POLICY` |
| 질문 기능 플래그 | 해당 없음 | `HEI5ENBUG_CODEX_ASK_TOOL` |

훅 Python 인터프리터는 Python 3.12 이상 인터프리터의 절대 경로입니다. SQL 가드의 파서를 쓰려면 그 인터프리터에 `pglast`를 설치합니다.
모든 훅은 `scripts/hook_python.sh`를 거쳐 시작하며, 이 런처가 해당 인터프리터로 스크립트를 실행합니다. Claude Code의 `python` 옵션을 먼저 보고
그다음 `HEI5ENBUG_PYTHON`을 보며, `/`로 시작하고 실제로 존재하는 실행 파일을 가리키는 경로만 인정합니다. 값이 비어 있거나
상대 경로이거나 없는 경로이거나 유효하지 않으면 `PATH`의 `python3`로 돌아가므로, 옵션을 설정하지 않으면 이전과 똑같이 동작합니다. 경로를 지정하면 pyenv shim 같은 버전 관리자 shim을
거치지 않습니다. 측정한 한 대의 기기에서 shim은 훅 프로세스마다 약 150ms를 더했고, 프로젝트마다 다른 Python을 고를 수도 있습니다.

런처 환경이 일치하지 않으면 mod는 고정 GPT 요청을 공급자에 보내기 전에 거부합니다. 이 거부에는 토글이 없습니다.
세션 지침과 운영 규칙도 저장소 간 작업 규칙을 불러오는 `orca_worktree` 줄을 제외하면 토글이 없으며,
끄려면 플러그인 자체를 비활성화합니다.

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

macOS와 Linux에서 플러그인 훅은 `instructions/session/core.md`, `instructions/session/common.md`와 현재 호스트의 지침을
합친다. Codex에는 `codex.md`, Claude Code에는 `claude-code.md`를 사용한다. `core.md`는 모든 에이전트에 적용되는 규칙을 담는다.
호스트의 `PATH`에서 `python3`로, 또는 훅 Python 인터프리터 옵션이 가리키는 인터프리터("기능 옵션" 참고)로 Python 3.12 이상을 실행할 수 있어야 한다.
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
| 세션 시작·재개 | `SessionStart`가 설치된 지침 파일을 전달한다. 필요하면 `host_settings.py check`가 찾은 문제를 한 줄짜리 안내로 추가한다. 최대 세 개를 보여 주고 나머지는 개수로 알린다. 예를 들면 Claude의 `defaultMode`가 `dontAsk`이거나, `permissions.ask` 규칙이 Bash·MCP 도구에 적용되거나, 기존 Codex 설정에 `[features] plugin_hooks = true`가 없는 경우다(Codex 설정은 양쪽 호스트에서 확인). `host_settings` 옵션이 `apply`인 Codex에서는 먼저 `apply`를 실행하며, 이는 허용 목록의 Codex 설정을 바꿀 수 있다([호스트 설정](#호스트-설정) 참고). 바꾼 내용은 안내 한 줄로 알린다. 안내는 컨텍스트 한도 안에 들어가야 한다. Orca 터미널에서는 플러그인 디렉터리와 지침 요약값을 담은 표식도 남긴다. |
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
Codex 사용자는 업데이트할 때마다 `/hooks`에서 훅을 다시 신뢰해야 한다.
Claude Code mod는 Codex 훅이 아니므로 이 신뢰 절차가 적용되지 않는다.
업데이트 후에는 Claude Code를 재시작하거나 Codex에서 새 세션을 시작한다.
훅은 호스트의 신뢰 설정을 우회하지 않으며, 실행 중인 세션의 플러그인 버전을 바꾸지 않는다.
`orca-plugin-refresh` 스킬은 이 표식으로 실행 중인 Orca 세션에 업데이트를 재시작 없이 반영한다.

세션 지침 누락·빈 파일·잘못된 로컬 참조, 9,000 UTF-8 바이트를 넘는 메인 컨텍스트나 4,000 UTF-8 바이트를 넘는 역할 컨텍스트는 표준 오류로 알린다.
이때 지침 일부만 전달하지 않는다.
세션 시작 훅의 오류가 호스트 실행을 반드시 중단시키지는 않으므로, 오류를 해결한 뒤 자동 적용을 사용한다.
세션 지침 파일은 짧게 유지하고 세부 사항은 조건부 참조로 옮긴다.
Windows 실행과 실제 모델의 지침 준수 여부는 테스트 범위에 포함하지 않는다.

실행 시점과 신뢰 설정은 공식 [Codex 훅 문서](https://learn.chatgpt.com/docs/hooks)와
[Claude Code 훅 문서](https://code.claude.com/docs/en/hooks)를 따른다.

## 상황별 위임

메인 세션은 [공통 지침](instructions/session/common.ko.md)에 따라 직접 처리할지 위임할지 판단합니다.
알려진 경로 조회, 변경 파일이 두 개 이하인 구현, 통합 수정은 메인이 처리합니다. 범위가 한정된 조사, 많은 근거 수집,
독립적으로 수행할 수 있는 더 큰 구현은 예상 이득이 조정 비용보다 클 때 작업자를 사용합니다. 의존성이 긴밀한 작업은 한 담당자가 이어서 처리합니다.
모든 작업에서 실제 비용이 줄어든다고 보장하는 정책은 아닙니다.

메인은 요구사항, 설계, 작업 경계, 수용 판단과 최종 보고를 맡습니다.
[구현 실행 규칙](instructions/implementation-execution.ko.md)은 메인 담당 작업을 포함한 모든 구현의 작업 준비,
할당 항목과 수용을 정의합니다. [구현 위임 규칙](instructions/implementation-delegation.ko.md)은 작업자 소유권,
충돌 없는 일정, 복구와 할당받은 worker 규칙을 정의하며, 구현을 위임하기 전에 읽습니다. 직접 작업은 메인의 현재
모델과 사고 강도를 유지합니다. 위임할 때는 작업 범위, 필요한 맥락, 허용·보호 경로, 선행 조건, 수용 검사와 호스트의
고정 설정만 전달합니다. 작업자는 하위 에이전트를 만들 수 없습니다.

UI 코드, 시각 디자인, 다이어그램 작업은 대신 호스트의 designer 경로로 보냅니다. 다만 호스트 세션 파일이 메인 세션에
맡긴 종류는 예외입니다. Claude Code에서는 메인 세션이 문서 안의 ASCII와 Mermaid 다이어그램을 그리고, 기존 SVG
다이어그램을 고치며, 노드 일곱 개 이하의 새 SVG나 PNG 흐름도를 만듭니다. 레이아웃과 컴포넌트 구조를 바꾸지 않는
문구·스타일 값 수정은 구현 worker가 맡을 수 있고, 설계 문서와 RFC는 메인 세션이 맡습니다.

다섯 기능은 `investigation`, `implementation`, `design`, `language`, `review`입니다. 모든 대체 항목은 다른 모델 계열입니다. 다른 호스트의 모델이 필요한 대체 항목은 역할 실행기를 거치고, 현재 호스트에서 바로 실행할 수 있는 대체 항목은 이름이 붙은 에이전트를 씁니다.
`config/model-registry.json`은 모델 고정값과 역량 고정값의 단일 출처이며, 스크립트와 mod가 이 파일을 읽습니다.
기능별 호스트 항목은 [모델 라우팅 계약](../../instructions/model-routing.md#capability-pins)의 역량 고정값 절에 있습니다.

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
`python3 <plugin>/scripts/role_runner.py <role-or-capability>` 또는 `python3 <plugin>/scripts/role_runner.py agent --name <name> --fallback`을
`--assignment <file> --result <file>`과 함께 실행합니다. `reviewer`에는 `--model <id>`, `worker`, 쓰기 기능, 쓰기 접근 에이전트에는
`--add-dir <dir>`, MCP 도구나 네트워크가 필요한 기능이나 에이전트에는 `--mcp`, 기능의 호스트 항목을 고르려면 `--host claude|codex`,
대체 항목에는 `--fallback`, 실행을 이어 가려면 상태 줄의 `evidence.session`으로 `--resume <session_id>`를 더할 수 있습니다.
`--effort <level>`은 항목에 지정된 범위 안에서 사고 강도를 높이며, 하한이 기본값입니다. `--assignment`와 `--result`를
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
되었으므로, 플러그인을 업데이트할 때마다 `/hooks`에서 다시 신뢰하기 전까지 Codex는 훅을 건너뛰고 실행기는 종료 코드
4로 끝납니다. Claude는 플러그인 훅에 신뢰 절차를 적용하지
않으므로 자식의 `heartbeats/claude-<session_id>.UserPromptSubmit` 또는 기존 일반 하트비트를 요구합니다.
필수 하트비트가 없으면 종료 코드 4입니다. 종료 코드 0은 결과가 검증되었다는
뜻이고, 2는 고쳐야 할 사용 오류, 3은 역할을 실행하지 못했다는 뜻, 4는 필수 훅 증거가 없거나 기록된 모델, 사고 강도, 샌드박스가 달라 결과를
폐기했다는 뜻입니다. 3이나 4이면 메인 세션이 해당 역할의 플러그인 에이전트 대체 경로를 씁니다. 독립 검증에는 대체 경로가
없으며, 수행하지 못했다고 보고합니다. `via`가 `agent`인 기능 항목은 실행기가 실행하지 않고 종료 코드 2로 끝나므로, 메인
세션이 그 항목에는 에이전트 경로를 씁니다.

준비된 독립 작업은 호스트 한도와 공통 실행 상한 안에서 함께 수행할 수 있습니다. 역할, 모델, 사고 강도, 사용량,
위임 권한 또는 설정 근거 때문에 위임할 수 없으면 메인이 제한을 알리고, 실행 중인 해당 작업자를 멈춘 뒤 승인된 작업을
이어갑니다. 부분 결과, 사용자 설정, 권한과 수용 검사는 유지하고 작업자 모델을 몰래 바꾸지 않습니다.

중요한 변경과 검사를 마치면 [독립 모델 검증](../../instructions/independent-model-validation.md)에 따라 독립 검토를 한 번
실행하며, `scripts/codex_usage.py`가 읽은 Codex 주간 사용량이 70% 이하이면 묻지 않습니다. Claude Code에서는 Claude가 작성한 결과를 `review_model` 설정(기본 `gpt-6-astra`)이 검토하고, GPT가 작성한
결과는 `claude-fable-5-1`이 검토합니다. Codex는 그 파일의 매핑을 따릅니다. 모든 검토자는 `high`로 실행하며,
여러 컴포넌트, 공개 계약, 보안, 동시성, 훅이나 가드가 관련되면 `xhigh`로 실행합니다. 설정한
검토자가 작성자와 같은 모델 계열이면 교차 계열 검토가 아니라고 결과에 적습니다. 사용량이 70%를 넘거나 알 수 없거나 검토자가
Claude에서 실행되면 해당 결과에 대한 승인이 필요하며 거절하면 다시 묻지 않습니다. 검토자를 사용할 수 없거나 역할 실행기가 종료 코드 3이나 4로 끝나면 독립 검증을 수행하지 못한 것이며, 다른
모델로 대체하지 않습니다. 작성자의 일상적인 점검과 검사는 계속 수행합니다.

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
`request_user_input`을 쓸 수 있습니다. blocking을 강제하거나 클라이언트의 자동 응답 처리를 끄는 기능은 아닙니다.
필수 결정에는 [확인 질문 규칙](instructions/session/common.ko.md#확인-질문)을 따르고, 연결이 중단되면
[연결 복구](instructions/connection-recovery.ko.md)를 적용합니다.
`HEI5ENBUG_SUBAGENT_POLICY=off`로 설정하면 표시 블록만 지우고 블록 밖은 절대 고치지
않습니다. `HEI5ENBUG_CODEX_ASK_TOOL=off`로 설정하면 기능을 다시 끄지만, 플러그인이 켠 경우에만 끄며 직접 켠 기능은 그대로
둡니다. 실패한 단계는 다음 세션 시작 때 다시 시도하며, 세션 지침 로드를 막지 않습니다. 실제 실행에는 호스트 규칙, 훅 신뢰와
사용 가능한 도구가 계속 적용됩니다.
[공식 Codex 서브에이전트 계약](https://learn.chatgpt.com/docs/agent-configuration/subagents)을 참고하세요.

## 작업 효율

[작업 효율 규칙](instructions/work-efficiency.ko.md)은 규모 있는 구현 전에만 불러옵니다. [모델 평가 규칙](instructions/model-evaluation.ko.md)은
반복 모델 평가 전에, [실패 및 유지보수 규칙](instructions/failure-and-maintenance.ko.md)은 플러그인 유지보수나 반복 실행
실패 진단 전에 불러옵니다. 요청한 결과와 필수 검사가 완료 기준입니다. 검사 근거는 관련 입력이 바뀔 때까지 재사용하고,
선택 조사나 수행하지 않은 선택 검토 때문에 수용된 작업을 계속 열어 두지 않습니다.
작업 효율 규칙은 멈춤, 인계, 예상되는 압축에 쓰는 [재개 메모 규칙](instructions/pause-and-resume.ko.md)과 끝난 세션이 만든
파일에 대한 [정리 제안](instructions/session-cleanup.ko.md)을 연결합니다. 규모 있는 구현을 하지 않는 세션은 이 규칙을
불러오지 않으므로 재개 메모도 정리 제안도 받지 않습니다.

추가 모델 비교는 대표 사례 최대 3개, 전체 묶음 15분, 두 호스트를 합쳐 비교 실행 시작 최대 6회로 시작합니다.
사전 확인 실행과 재시도도 이 예산에 포함하며, 재개해도 예산을 초기화하지 않습니다. 일반 구현, 단위 테스트,
필수 빌드와 마무리 검토에는 이 상한을 적용하지 않습니다. 확대하려면 남은 질문과 명시적으로 승인된 더 큰 예산이
있어야 합니다.

영구적 실패는 조건이 바뀌어야 다시 시도하고, 일시적 실패는 같은 조건에서 한 번만 재시도합니다.
브라우저 쓰기는 [서비스 접근 규칙](../../instructions/services.md#browser-ownership)에 따라 실제 공유 제어 자원마다
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

릴리스가 끝난 뒤 `orca-plugin-refresh`를 요청하면 이 플러그인과 지정한 다른 플러그인을 업데이트하고, 설치된 버전을
Orca가 관리하는 대기 세션에 재시작 없이 반영합니다. 이 스킬은 요청할 때만 실행됩니다. `update --json`은 Claude Code와
Codex에 새 버전을 설치합니다. 다른 플러그인은 `--also <plugin@marketplace>`를 하나씩 붙여 지정합니다. 이 플래그가 없으면
`HEI5ENBUG_REFRESH_PLUGINS` 환경 변수(쉼표로 구분한 ID)를, 그것도 없으면 저장된 `refresh_plugins` 옵션을 쓰며, 비어 있지
않은 첫 출처가 이깁니다. 함께 새로고침할 플러그인은 호스트마다 업데이트하고 검증해 `updated`, `current`, `not_installed`,
`local_source`, `deferred`, `error` 중 하나로 보고합니다. 로컬 폴더에서 로드되는 플러그인은 설치하지 않으므로 커밋하지 않은
코드가 배포되지 않습니다. 함께 새로고침할 플러그인의 오류는 이 플러그인이나 세션 적용을 막지 않습니다.
`apply-installed --json`은 마켓플레이스나 설치 명령 없이 설치 경로와 함께 새로고침할 플러그인을 검증합니다. 두 명령 모두
`apply --run-id <run_id> --json`에 넘길 실행 ID를 만듭니다.

호스트마다 설치 게이트가 따로 있습니다. Claude Code는 업데이트가 옛 버전 옆에 새 버전을 추가하고 실행 중인 세션이
`/reload-plugins` 전까지 불러온 디렉터리를 유지하므로 항상 설치합니다. Codex 업데이트는 옛 설치본을 삭제하므로 진행 중인
Codex 턴이 없을 때까지 기다립니다. 명령 자체가 Codex 턴 안에서 실행되거나, 최근 30분 안의 Codex 세션 파일이 끝난 턴으로
끝나지 않거나, 그 파일을 읽을 수 없으면 보류합니다. 보류된 Codex 호스트는 건드리지 않고, 그 호스트의 함께 새로고침할
플러그인은 `deferred`로 보고하며, 결과는 현재 설치 경로와 Codex 턴이 끝난 뒤 실행할 `recovery_command`를 제공합니다.
바쁜 세션은 최대 한 시간까지 다시 시도합니다. 직접 업데이트하거나 다른 프로세스가 로드된 디렉터리를 삭제하는 상황은 이
보호 범위 밖입니다. 명령과 한계는 [새로고침 절차](skills/orca-plugin-refresh/SKILL.ko.md)를 참고하세요.

| 부분 | Claude Code | Codex |
|---|---|---|
| 스킬, 에이전트, 훅 | 스킬이 `/reload-plugins`를 보냄 | 설치 후 다음 턴에 자동으로 반영 |
| 세션 지침 | 지침이 오래됐으면 스킬이 `/compact`를 보냄 | 지침이 오래됐으면 스킬이 `/compact`를 보내고, 세션은 다음 턴에 불러옴 |

스킬은 세션 시작 표식으로 지침이 오래됐는지 판단합니다. 표식이 없거나, 요약값이 다르거나, 교체되거나 지워진
플러그인 디렉터리를 가리키면 오래된 것으로 봅니다. 명령은 대기 상태이면서 입력 줄이 빈 터미널에만 보내고, 결과를
세션 대화 기록이나 화면으로 모두 확인합니다. Claude Code 세션에서는 흐린 추천 문구와 직접 친 글을 구별하려고 한
글자를 입력했다가 지울 수 있으며, 직접 친 글이 있는 세션에는 명령을 보내지 않습니다. 작업 중인 세션은 최대 한 시간까지 다시 시도하고, 그래도 안 되면 건너뛴 것으로 보고합니다.
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
사람이 읽는 모든 영어 Markdown 파일에는 의미가 같은 `.ko.md` 번역본을 `docs/ko/` 아래에 둡니다.
번역본 경로는 저장소 루트 기준 원본 경로를 따릅니다.
번역본은 영어 원본을 연결하고 비권위 자료임을 밝히며 에이전트 실행 중 읽거나 사용하지 않습니다.
원본과 번역본은 함께 수정, 이동 또는 삭제합니다.

코드, 스키마, 테스트 자료, 생성 아티팩트와 영어가 아닌 문서는 한국어 복사본을 만들지 않습니다.
호출 문구, 예시, 필수 출력 이름 또는 평가 자료처럼 한국어 자체가 대상 데이터일 때만 영어 실행 파일에
한국어를 유지할 수 있습니다. 자동 검사는 번역본 존재와 실행 경로 분리를 확인하고 의미 일치는 사람이나
모델이 별도로 검토합니다.

## 스킬 목록

| 스킬 | 하는 일 |
|---|---|
| [`decision-navigator`](../../skills/decision-navigator/SKILL.md) | 여러 세션에 걸친 작업을 의사 결정 티켓으로 나누고, 구현 경로가 분명해질 때까지 티켓을 하나씩 해결합니다. [한국어 안내](skills/decision-navigator/SKILL.ko.md) |
| [`deep-interview`](../../skills/deep-interview/SKILL.md) | 답변마다 요구사항의 모호함 정도를 점수로 측정하는 소크라테스식 인터뷰를 진행하며, 그 점수가 기준값 이하로 내려가기 전에는 실행 단계로 넘어가지 않습니다. [한국어 안내](skills/deep-interview/SKILL.ko.md) |
| [`flowchart-design`](../../skills/flowchart-design/SKILL.md) | SVG, HTML/CSS, Figma, draw.io 등 어떤 도구로 만들어도 하나의 디자인 시스템처럼 보이게 하는 플로우차트 공통 디자인 기준입니다. [한국어 안내](skills/flowchart-design/SKILL.ko.md) |
| [`docs-rewrite`](../../skills/docs-rewrite/SKILL.md) | 주장, 수치, 확신도를 그대로 둔 채 글이 자연스럽게 읽히도록 고쳐 쓰고, AI가 쓴 듯한 한국어 문체를 함께 고칩니다. [한국어 안내](skills/docs-rewrite/SKILL.ko.md) |
| [`document-to-confluence`](../../skills/document-to-confluence/SKILL.md) | Markdown, HTML, PDF, DOCX, Google Docs 문서를 Confluence 페이지로 변환하고, 문서 구조와 첨부 파일을 보존하며, 이후 원본 변경도 웹 편집과 인라인 댓글을 잃지 않고 페이지에 반영합니다. [한국어 안내](skills/document-to-confluence/SKILL.ko.md) |
| [`local-data-cleanup`](../../skills/local-data-cleanup/SKILL.md) | Claude Code와 Codex의 로컬 데이터를 읽기 전용으로 조사하고, 후보마다 고정된 안전 규칙과 다른 호스트의 독립 판정을 확인해 크기순으로 보고하며, 사용자가 고른 항목만 삭제합니다. [한국어 안내](skills/local-data-cleanup/SKILL.ko.md) |
| [`mistake-enforcer`](../../skills/mistake-enforcer/SKILL.md) | 커밋, 되돌린 커밋, 리뷰 댓글, 사용자 교정에서 에이전트가 저장소에서 되풀이하는 실수를 유형별로 묶고, 효과가 있는 가장 높은 집행 수준을 고르며, 제안한 검사가 실제 과거 사례에서 실패하는지 증명합니다. 요청할 때만 실행됩니다. [한국어 안내](skills/mistake-enforcer/SKILL.ko.md) |
| [`report-skill-gap`](../../skills/report-skill-gap/SKILL.md) | 플러그인의 스킬이나 지침에 있는 빈틈 하나 또는 어떤 스킬도 다루지 않는 작업 흐름을 이슈 초안으로 만들고, 제안에서 사례의 식별자와 비공개 세부 정보를 뺀 뒤 담당 플러그인이 선언한 트래커에 등록합니다. 공개 트래커이면 미리 보여 줍니다. 이름을 불러야만 시작합니다. [한국어 안내](skills/report-skill-gap/SKILL.ko.md) |
| [`session-retro`](../../skills/session-retro/SKILL.md) | 한 저장소의 하루 Claude Code·Codex 세션을 읽기 전용 scout로 검토하고, 정정·실패·반복 작업을 플러그인별 근거 있는 스킬 개선안으로 바꾸며, 남은 결정을 묻고 요청하면 계획안을 씁니다. [한국어 안내](skills/session-retro/SKILL.ko.md) |
| [`skill-builder`](../../skills/skill-builder/SKILL.md) | 초안 작성 → 테스트 → 검토 → 개선 순환을 통해 에이전트 스킬을 만들고, 검증하고, 패키징합니다. [한국어 안내](skills/skill-builder/SKILL.ko.md) |
| [`orca-plugin-refresh`](../../skills/orca-plugin-refresh/SKILL.md) | 이 플러그인과 지정한 다른 플러그인을 호스트별 설치 게이트를 거쳐 Claude Code와 Codex에 업데이트하고, 설치된 버전을 대기 중인 Orca 관리 세션에 재시작 없이 반영합니다. [한국어 안내](skills/orca-plugin-refresh/SKILL.ko.md) |
| [`suggest-commit`](../../skills/suggest-commit/SKILL.md) | 스테이징된 변경과 스테이징되지 않은 변경을 함께, 또는 사용자가 지정한 범위를 최근 커밋 이력과 함께 읽어, 이 저장소의 스타일에 맞는 커밋 메시지 5개를 제안합니다. 커밋을 요청하면 가장 적절한 제목 하나로 바로 커밋합니다. [한국어 안내](skills/suggest-commit/SKILL.ko.md) |
| [`technical-design-writer`](../../skills/technical-design-writer/SKILL.md) | 구현 계획을 담당하지 않고 기술 설계 문서와 RFC를 작성하거나 검토합니다. [한국어 안내](skills/technical-design-writer/SKILL.ko.md) |
| [`tiki-taka`](../../skills/tiki-taka/SKILL.md) | 현재 에이전트와 반대쪽 Claude/Codex 세션이 교환 횟수를 제한한 토론을 벌여 쟁점을 드러내고 수렴시킵니다. [한국어 안내](skills/tiki-taka/SKILL.ko.md) |

### 이슈 트래커 선언

`report-skill-gap`은 담당 플러그인이 루트의 `issue-target.json`에 선언한 트래커에만 이슈를 등록합니다.
이 파일은 `.claude-plugin/`, `.codex-plugin/` 옆에 둡니다.
스킬은 모든 트래커를 이 파일에서 찾으므로, 이 플러그인은 자신을 기반으로 만든 플러그인을 알 필요가 없습니다.
이 플러그인은 자신의 저장소를 선언합니다.

```json
{
  "version": 1,
  "tracker": {"kind": "github", "location": "hei5enbug/hei5enbug-agent-setup"},
  "language": "en",
  "body_format": "markdown",
  "labels": ["bug", "enhancement"],
  "public": true,
  "write_approval": "preview"
}
```

| 필드 | 의미 |
|---|---|
| `version` | 항상 `1`입니다. |
| `tracker` | `kind`는 `github`, `gitlab`, `jira`, `other` 중 하나입니다. `location`은 GitHub에서는 `owner/repo`이고, 그 외에는 프로젝트 URL이나 키입니다. |
| `language` | 이슈에 쓰는 글의 언어 태그입니다. 예를 들어 `en`이나 `ko`입니다. |
| `body_format` | `markdown`, `jira-wiki`, `plain` 중 하나입니다. |
| `labels` | 스킬이 고를 수 있는 라벨입니다. 하나를 고르며, 목록이 비어 있으면 고르지 않습니다. |
| `public` | 누구나 트래커를 읽을 수 있으면 `true`입니다. 공개 트래커에서는 항상 미리 보여 줍니다. |
| `write_approval` | `preview`는 최종 내용을 보여 주고 승인을 기다립니다. `direct`는 스킬 이름을 부르면 등록합니다. |
| `content_rules` | 모든 이슈에서 내용을 제외하는 추가 규칙 파일의 경로입니다. 선택 사항이며 플러그인 루트를 기준으로 합니다. |

알 수 없는 키가 있으면 선언은 유효하지 않습니다.
파일이 없거나 유효하지 않은 플러그인은 대화에서 초안만 받고 이슈는 등록되지 않습니다.

## 관련 링크

- `omo-model-config`는 제거했습니다. 마지막 버전은 [`v1.3.0` 태그](https://github.com/hei5enbug/hei5enbug-agent-setup/tree/v1.3.0/standalone-skills/omo-model-config)에 있습니다.

## 라이선스

이 저장소는 Apache License 2.0을 따릅니다. 전문은 [`LICENSE`](../../LICENSE)에 있습니다.
