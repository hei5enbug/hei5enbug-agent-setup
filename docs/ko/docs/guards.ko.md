# 응답 언어, DataGrip, 공개 경계 가드

> 영어 원본: [guards.md](../../guards.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 문서는 호스트별 응답 언어 검사, DataGrip 쿼리 보호, 공개 경계 검사의 동작을 설명합니다.

## 응답 언어

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

## DataGrip 쿼리 가드

두 호스트의 `PreToolUse` 훅과 Codex 전용 `PermissionRequest` 훅인 `scripts/datagrip_guard.py`는
DataGrip MCP 도구 `execute_sql_query` 실행 전에 동작합니다.
가드는 `projectPath`가 가리키는 DataGrip 프로젝트의 `.idea/dataSources.xml`에서 연결 정보를 읽습니다.
운영이 아니고 확인된 연결에서는 PostgreSQL과 SQL Server의 읽기 쿼리를 승인 없이 실행합니다. PostgreSQL 읽기는 읽기 전용 트랜잭션에서
`SET LOCAL statement_timeout = '60s';`와 함께 실행됩니다. 운영 연결에서는 PostgreSQL 읽기 전에 기록된 계획이 필요하고, SQL Server 읽기에는
잠금 안전장치가 붙습니다([운영 읽기 규칙](approval-guard.ko.md#운영-데이터베이스-읽기) 참고). `approval_guard`를 켜면 비파괴적인 PostgreSQL·SQL Server
쓰기는 다른 모든 쓰기와 세션 쓰기 승인(`write:session`)을 공유합니다. 알 수 없는 연결, 그 밖의 데이터베이스 종류,
가드가 해석하지 못한 텍스트도 같은 승인을 사용합니다. 연결 이름의 `승인`은 그 자체로는 아무 효과가 없습니다.
코드에 `delete`, `drop`, `truncate`가 이름으로 든 문장과 SQL 분류기가 파괴적으로 판단한 문장은 매번 승인을 요청합니다.
`DO`, `EXEC`, `EXECUTE`, `CALL`로 시작하는 문장도 여기에 포함됩니다. 여기서 코드는 문자열 리터럴, 주석, 따옴표나 대괄호로 묶은
식별자를 뺀 나머지 텍스트이므로, 그 안에서만 `delete`를 언급하는 `SELECT`는 읽기로 남습니다. 운영이 아닌 PostgreSQL
연결([운영 데이터베이스 읽기](approval-guard.ko.md#운영-데이터베이스-읽기) 참고)에서 `pglast` 파서가 텍스트를 확인하면, 자기 문장에 `WHERE`가 있는 `DELETE`와, 본문이
PL/pgSQL로 파싱되고 `DROP`, `TRUNCATE`, `EXECUTE`, `ALTER`, `GRANT`, `REVOKE`, `CALL`, 중첩 `DO`, `WHERE` 없는 `DELETE`,
위험 함수 호출(따옴표로 감싼 이름도 검사하며, 여기서는 `set_config`와 `pg_sleep`는 허용)이 없는 `DO` 블록이 대신 세션
쓰기입니다. 세미콜론 없이 문장을 이어 쓸 수 있는 SQL Server와 파서가 확인하지 못한 텍스트는 계속 매번 묻습니다.
SQL Server 읽기에는 `SET NOCOUNT`,
`LOCK_TIMEOUT`, `DEADLOCK_PRIORITY`, `TRANSACTION ISOLATION LEVEL READ UNCOMMITTED|READ COMMITTED|SNAPSHOT`,
`ARITHABORT`,
`ANSI_NULLS`, `ANSI_WARNINGS`, `ANSI_PADDING`, `QUOTED_IDENTIFIER`, `CONCAT_NULL_YIELDS_NULL`, `XACT_ABORT`,
`STATISTICS IO|TIME`,
`SHOWPLAN_XML|ALL|TEXT` 문장도 함께 쓸 수 있습니다.
Codex에서는 쓰기가 준비된 상태면 Codex의 네이티브 승인 창을 열고, 그렇지 않으면 코드와 함께 거부합니다.
매번 묻는 쿼리는 항상 코드와 함께 거부합니다([승인 가드](approval-guard.ko.md#승인-가드)를 참고하세요). 토글을 끄면 모든 쓰기가 이전처럼 승인을 요청합니다. Codex에서는 `/hooks`
에서 이 훅을 신뢰해야 합니다.

선택 사항으로 `pglast` 파서를 한 번 설치할 수 있습니다.

```bash
uv venv --python 3.12 "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser"
uv pip install --python "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser/bin/python" pglast==8.4
```

파서가 없으면 PostgreSQL은 더 엄격한 텍스트 검사로 대체합니다. 이 검사는 승인을 더 자주 요청할 수 있지만, 승인 없이 쓰기가 실행되는 일은 여전히 없습니다.

## 공개 경계 검사

두 호스트 모두 `approval_guard` 옵션의 활성화 여부와 관계없이 모든 프로젝트에서 `Bash`의 `PreToolUse` 훅이
`scripts/public_boundary_hook.py`를 호출합니다. 이 훅은 플러그인의 `.githooks/` 폴더에서 스캐너를 불러오며,
공개할 텍스트, 커밋, 태그에 홈 경로, 비밀 값 형태, 이메일 주소, 비공개 단어가 있으면 `git` 또는 `gh` 쓰기를
실행 전에 차단합니다. 차단할 때는 발견한 항목마다 종류와 위치만 보고하며, 일치한 값은 보고하지 않습니다.
`git`이나 `gh` 단어가 없는 명령, 읽기 전용 명령, 다른 저장소를 대상으로 한 명령은 출력 없이 통과합니다.
`git`이나 `gh` 단어가 나타나기 전에는 표준 라이브러리 외에 아무것도 불러오지 않습니다.

설치된 플러그인이 공개로 선언한 저장소는 보호 대상입니다. 루트 `issue-target.json`에 `"public": true`가 있고,
`tracker`의 종류가 `github`이며 위치가 `<owner>/<repo>`인 경우입니다. 설치된 플러그인은
`CLAUDE_CONFIG_DIR`(기본값 `~/.claude`) 아래 Claude Code의 `plugins/installed_plugins.json`에 있는 플러그인,
`CODEX_HOME`(기본값 `~/.codex`)의 `plugins/cache/<marketplace>/<plugin>/<version>` 아래 각 플러그인의 최신 캐시 버전,
그리고 실행 중인 플러그인의 루트(`CLAUDE_PLUGIN_ROOT`, Codex에서는 `PLUGIN_ROOT`)입니다. `gh` 쓰기는 `--repo`나 `-R`이
보호 대상 저장소를 지정하면 검사 범위에 듭니다. 그 옵션이 없으면 `GH_REPO`가 지정한 저장소를 따릅니다. 이 값은 해당 명령에
인라인으로 설정하거나, 같은 명령의 앞선 `export`로 설정하거나, 훅의 환경에 설정할 수 있습니다. 둘 다 없으면 작업 디렉터리의
`origin`을 따릅니다. 앞에 붙인 `NAME=value`는 해당 명령에만 적용됩니다. `git` 커밋과 태그는 그 저장소의
`origin`이 보호 대상 저장소일 때 검사 범위에 듭니다. 그 저장소는 작업 디렉터리의 체크아웃이거나, 명령이 `--git-dir`,
`GIT_DIR`, `GIT_WORK_TREE`로 지정한 git 디렉터리입니다. `git push`는 닿는 목적지 중 하나라도 보호 대상이면 검사 범위에
듭니다. 목적지는 명시한 URL이나 remote 이름이며 remote의 push URL로 확인하고, 없으면 브랜치의 push remote, 그다음
`origin`입니다. 이 값들의 변수는 명령 자신의 할당으로 확장하며, 확인할 수 없는 대상은 보호 대상으로 봅니다. 확인할 수 없는
`--repo`, `GH_REPO`, push 목적지는 검사하고, 확인할 수 없는 git 디렉터리는 차단합니다. 저장소를 고르는 디렉터리(`-C`,
`--git-dir`, `--work-tree`, `GIT_DIR`, `GIT_WORK_TREE`)는 공개되는 텍스트로 검사하지 않습니다.

`--body-file -`, `-F -`, `git commit -F -`처럼 본문을 표준 입력에서 읽는 쓰기는 그 출처와 함께 검사합니다. heredoc은
명령의 일부로, 파이프라인은 `|`로 끝나는 앞 줄의 명령을 포함한 앞선 명령과, 와일드카드를 확장한 뒤 `cat`이나 `<`
리디렉션이 지정한 파일로, `echo`나 `printf`는 그 텍스트로
검사합니다. 그 밖의 명령이 파이프라인에 내용을 넣으면 실행 전에 출력을 검사할 수 없으므로 쓰기를 차단합니다. 스캐너가
없거나 실패하면 훅은 `git`이나 `gh` 명령도 차단합니다.

비공개 단어는 `HEI5ENBUG_PUBLIC_BOUNDARY_WORDS`가 지정한 파일과, 설치된 각 플러그인이 루트의
`public-boundary.json`에 정확히 `{"version": 1, "private_words_file": "<path>"}`로 선언한 파일에서 가져옵니다.
경로는 상대 경로이며 해당 플러그인 루트 안에 있어야 합니다. 텍스트 단어 파일은 한 줄에 단어나 구절 하나를 담고, `#` 주석
줄을 사용합니다. `.json` 파일은 [선언](development.ko.md#비공개-단어-목록-선언)에서 설명한 대로 `words`와 선택 항목인
`patterns`, `allowed_identity_emails`를 담습니다. 선언이 유효하지 않거나 파일을 읽을 수 없으면 플러그인 이름과 이유만
담은 문제로 보고하며, 단어는 보고하지 않습니다. 검사를 완료할 수 없으므로 쓰기를 차단합니다. 이 저장소에는 목록을 두지 않습니다.

공개 쓰기를 검사할 때 목록을 찾지 못하면 훅은 매번 그 사실을 알립니다. 통과한 쓰기는 사용자용 `systemMessage`와
모델용 `hookSpecificOutput.additionalContext`가 있는 JSON을 출력합니다. 차단된 쓰기는 오류 출력에 같은 문장을 추가합니다.

이 저장소의 체크아웃에서 설치된 플러그인이 오래되었거나 없는 세션을 위해 `.claude/settings.json`과
`.codex/hooks.json`의 프로젝트 훅도 유지하므로, 그곳에서는 호출 한 번에 두 훅이 모두 실행될 수 있습니다.
