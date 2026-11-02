# 응답 언어와 DataGrip 가드

> 영어 원본: [guards.md](../../guards.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 문서는 호스트별 응답 언어 검사와 DataGrip 쿼리 보호 동작을 설명합니다.

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
