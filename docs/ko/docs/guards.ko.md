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
Claude Code는 이 요청을 훅 오류가 아니라 `Stop hook feedback`으로 표시하고, Codex는 이어서 진행하라는 프롬프트로
받습니다. 위임된 자식 세션은 검사하지 않습니다. 역할 실행기의 자식처럼 `HEI5ENBUG_ASSIGNED_ROLE`이나
`HEI5ENBUG_PARENT_SESSION`이 설정된 세션은 조정 세션에 답변을 돌려주고, 조정 세션이 사용자에게 응답합니다.
다른 언어로 쓴 진행 상황 안내가 나오면 `PostToolUse` 훅이 같은 턴에서 모델의 다음 요청 전에 알림을 추가합니다.
Claude Code는 백그라운드 훅이 다음 모델 요청 전에 끝날 때만 그 출력을 같은 턴에 추가하므로 이 훅을 동기로
실행합니다. Codex는 이 훅을 백그라운드로 실행하고, 출력을 그 턴의 다음 모델 요청에 추가합니다. 사용자가 다른 언어로
요청한 글은 코드 블록이나 인용 블록에 넣습니다.

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
`origin`을 따릅니다. `gh issue comment <url>`처럼 이슈나 풀 리퀘스트 URL 피연산자는 그 URL의 저장소를 지정하며, `gh api`
엔드포인트의 `{owner}`와 `{repo}` 자리표시자는 `gh`와 같이 `GH_REPO`나 작업 디렉터리의 `origin`으로 채웁니다. 호스트가 붙은
저장소 이름은 `github.com`의 저장소만 보호합니다. `git.example.com/<owner>/<repo>`는 다른 저장소입니다. 호스트 없이 지정한
저장소와 현재 저장소는 `GH_HOST`가 설정한 호스트를 따르며(인라인, `export`, 훅의 환경 모두 해당), 없으면 `github.com`입니다. 댓글이나 메시지를
남기는 `gh`의 close, reopen, merge도 쓰기입니다. 앞에 붙인 `NAME=value`는 해당 명령에만 적용됩니다. `git` 커밋과 태그는 그 저장소의
`origin`이 보호 대상 저장소일 때 검사 범위에 듭니다. 그 저장소는 작업 디렉터리의 체크아웃이거나, 명령이 `--git-dir`,
`GIT_DIR`, `GIT_WORK_TREE`로 지정한 git 디렉터리입니다. `git push`는 닿는 목적지 중 하나라도 보호 대상이면 검사 범위에
듭니다. 목적지는 명시한 URL이나 remote 이름이며 remote의 push URL로 확인하고, 없으면 브랜치의 push remote, 그다음
`origin`입니다. push는 보내는 ref에서 닿는 모든 커밋을 검사합니다. ref를 지정하지 않으면 HEAD를 검사하고,
`push.default=matching`이나 `remote.<name>.push` 설정이 더 보낼 수 있으면 모든 로컬 브랜치도 검사합니다. `--all`이면
모든 브랜치, `--tags`이면 태그를 검사하고, 지정한 ref가 아직 없으면 HEAD와 모든 브랜치를 검사합니다. `2>&1` 같은
리다이렉트는 ref로 보지 않습니다. 이때 설정되어 있고 보호 대상인 목적지 remote의 원격 추적 ref에 있는 커밋만 제외합니다. 따라서 무관한
remote가 이미 가진 커밋도 검사합니다. 이 값들의 변수는 `git -c` 설정의 변수를 포함해 명령 자신의 할당으로 확장하며,
확인할 수 없는 대상은 보호 대상으로 봅니다. 확인할 수 없는 `--repo`, `GH_REPO`, push 목적지는 검사하고, 확인할 수 없는 git
디렉터리는 차단합니다. 확인할 수 없는 `-C`나 `cd` 값도 `git` 쓰기와 저장소를 지정하지 않은 `gh` 쓰기 앞에서는 차단합니다. 저장소를 고르는 디렉터리(`-C`,
`--git-dir`, `--work-tree`, `GIT_DIR`, `GIT_WORK_TREE`)는 공개되는 텍스트로 검사하지 않습니다.

`--body-file -`, `-F -`, `git commit -F -`처럼 본문을 표준 입력에서 읽는 쓰기는 그 출처와 함께 검사합니다. heredoc은
명령의 일부로, 파이프라인은 `|`로 끝나는 앞 줄의 명령을 포함한 앞선 명령과, 와일드카드를 확장한 뒤 `cat`이나 `<`
리디렉션이 지정한 파일로, `echo`나 `printf`는 그 텍스트로
검사합니다. 그 밖의 명령이 파이프라인에 내용을 넣으면 실행 전에 출력을 검사할 수 없으므로 쓰기를 차단합니다. 명령 치환으로
만든 본문이나 메시지는 치환이 heredoc, 리터럴 텍스트의 `echo`나 `printf`, 이름을 지정한 파일의 `cat`이면 검사하고, 그 밖에는
차단합니다. 이름 있는 파이프처럼 일반 파일이 아닌 입력 파일과 이름을 확인할 수 없는 파일도 그 파일을 기다리지 않고
쓰기를 차단합니다. `gh api`의 `-f`나 `--raw-field` 값은 리터럴 텍스트이며, `-F`나 `--field`만 `@file`을 읽습니다. 스캐너가
없거나 실패하면 훅은 `git`이나 `gh` 명령도 차단합니다.

다음 형태는 공개될 내용을 검사할 수 없으므로 훅이 차단합니다. 확인할 수 없는 `cd`나 `git -C` 디렉터리, heredoc이 아닌 명령
치환(리터럴 텍스트의 `echo`나 `printf`, 이름을 지정한 파일의 `cat`은 예외), 확인할 수 없는 표준 입력 파일 이름, 일반 파일이
아닌 입력 파일입니다. 대신 경로를 그대로 쓰거나, 본문을 heredoc이나 파일로 전달해야 합니다.

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
`skill-issue-creator` 스킬은 `skills/skill-issue-creator/scripts/scan_draft.py`를 호출해 게시 전에 같은 스캐너로
이슈 초안을 검사합니다. 트래커를 소유한 플러그인이 선언한 목록도 `--plugin-root`로 받아 읽으며, 그 플러그인이 설치되지
않았어도 읽습니다.

## 커밋과 푸시 시 필수 검사

두 호스트 모두 `Bash`의 `PreToolUse` 훅인 `scripts/required_checks_hook.py`를 실행합니다. 명령이 `git commit`이나
`git push`를 실행하면 모델의 문맥에 알림 하나를 추가합니다. `-C`나 `-c` 같은 전역 옵션을 쓰거나 `&&`, `;`, `|`,
서브셸 안에서 실행하는 경우도 포함합니다. 알림은 커밋이나 푸시 전에 답변에서 프로젝트 지침이나 변경한 스킬이
요구하는 각 검사를 완료로 나열하거나 미완료로 나열하고 그 이유를 밝히라고 안내합니다. 변경이 작다는 판단으로
미완료 검사를 면제해서는 안 됩니다. 다른 명령, 잘못된 형식의 입력, 명령이 없는 입력에는 아무것도 출력하지 않습니다.
훅은 차단하거나 승인하지 않고 문맥만 추가합니다. 이 훅을 둔 이유는 2026-10-04부터 2026-11-03까지 Claude Code 메인
세션 1,259개 중 7개에서 에이전트가 필수 검사를 스스로 판단해 건너뛰거나 실행하는 대신 제안만 한 채 작업을 마치거나
커밋하거나 푸시했기 때문입니다.

## Orca 세션 시작

두 호스트 모두 `Bash`와 `EnterWorktree`의 `PreToolUse` 훅인 `scripts/orca_placement_hook.py`를 실행합니다. 거부할
이유가 없는 명령, 이 단어들을 언급만 하는 텍스트, 잘못된 형식의 입력, 명령이 없는 입력에는 아무것도 출력하지
않습니다. 훅은 `$(...)`나 백틱 명령 치환의 안쪽도 검사하고, here-document 본문에서는 그런 치환만 검사합니다.
Codex에서는 `/hooks`에서 이 훅을 신뢰해야 합니다.

- **최상위 worktree.** `--no-parent`가 있는 `orca worktree create`나 `--worktree new-top-level`이 있는
  `orca orchestration worker-start`는 `instructions/cross-repository.md`의 "Session placement"에 따라 대신 사용할
  부모를 알려 주며 거부합니다. workspace가 없는 저장소이거나 사용자가 명시적으로 요청한 경우에는
  `orca worktree set --no-parent`로 기존 worktree를 최상위로 옮길 수 있습니다. 이 규칙을 둔 이유는 2026-11-06에
  조정 세션이 티켓 두 개를 위해 티켓 참조 없이 `--no-parent`로 worktree 세 개를 만들어, `orca reference find`가
  하나도 찾지 못했고 이후 세션이 그룹에 참여할 수 없었기 때문입니다.
- **다른 저장소의 부모.** `orca worktree create`, `--worktree new-child`로 worktree를 만드는 `worker-start`,
  `orca worktree set --parent-worktree`는 부모가 worktree와 다른 저장소에 속하면 거부합니다. 각 worktree는 자기
  저장소의 workspace 아래에 두고, 한 티켓의 worktree는 참조, 이름, Run으로 묶기 때문입니다
  (`instructions/orca-groups.md`). 훅은 `id:<repoId>`와 `id:<repoId>::<path>` 선택자에서는 Orca 저장소 ID를,
  `path:` 선택자에서는 Git 디렉터리를 비교합니다. `active`는 현재 worktree이며, 그 저장소 ID는
  `orca worktree current`에서 한 번 읽습니다. 이름이나 브랜치 선택자, 확인할 수 없는 저장소, 읽을 수 없는 Orca는
  명령을 허용합니다.
- **작업이 남은 완료.** `orca worktree set --workspace-status completed`는 대상 worktree, 즉 현재 worktree나
  `--worktree` 선택자가 `id:<repoId>::<path>`나 `path:`로 가리키는 worktree에 커밋하지 않은 변경이나 업스트림에 없는
  커밋이 있으면 거부하며, 거부 사유에 남은 것을 나열합니다. 깨끗한 worktree, 다른 상태, 확인할 수 없는 대상은
  허용합니다.
- **호스트가 만드는 worktree.** Orca 터미널에서 `path` 없는 `EnterWorktree`는 Orca가 목록에 올리지 않는 worktree를
  만들므로, 대신 쓸 `orca worktree create` 명령을 알려 주며 거부합니다. 기존 `path`로 들어가는 호출과 Orca 밖의
  호출은 허용합니다.
- **메모리 부족.** 사용 가능한 메모리가 `session_memory_min_mb` 옵션(기본값 2048 MB)보다 적으면 Orca를 통해
  에이전트 세션을 시작하는 명령을 거부합니다. 에이전트는 컴퓨터가 스왑을 쓰게 만드는 대신 세션을 대기열에 넣고
  다른 세션이 끝난 뒤에 시작합니다. 대상은 `--agent`가 있는 `orca worktree create`,
  `orca orchestration worker-start`, `orca agent launch`, `--command`가 `cd '<path>' &&` 같은 앞부분
  뒤에서라도 `claude`나 `codex`를 실행하는 `orca terminal create`이며, 명령 치환 안에서도 검사하지만 작은따옴표
  안이나 이스케이프된 `$` 뒤는 검사하지 않습니다. 다른 명령에는 적용하지 않습니다. 둘 이상이 적용되면 배치 거부가
  우선합니다. 사용 가능한 메모리는 macOS에서는 memory-pressure의 여유 비율에 물리 메모리를 곱한 값, Linux에서는
  `MemAvailable` 값이며, 대상 명령을 찾은 뒤에만 읽습니다. 1초 안에 읽을 수 없거나 다른 플랫폼이면 명령을
  허용합니다. 옵션을 `0`, `off`, `false`, `no`로 설정하면 규칙이 꺼지고, 값이 0 이상의 정수가 아니면 2048을
  사용합니다. Codex에서는 `HEI5ENBUG_SESSION_MEMORY_MIN_MB`를 설정합니다.

## Orca 상태

훅 스크립트 하나인 `scripts/orca_status_hook.py`가 세션의 Orca worktree를 작업에 맞춥니다. 이 훅은
`ORCA_TERMINAL_HANDLE`이 설정된 경우에만 실행되고, 서브에이전트나 지정된 작업자에서는 실행되지 않으며, Orca, Git,
기록을 읽지 못하면 그 이벤트를 통과시킵니다. Codex는 도구 호출을 스크립트 텍스트로 기록하므로 Claude Code 기록만
읽습니다. 그래서 Codex에서는 도구 호출이나 프롬프트 뒤에 쓰는 기록만 적용되며, 질문 행은 `instructions/orca-worktree-status.md`대로 세션이 직접 씁니다. 같은 턴에 답을 받은 질문 도구 호출은 아무것도 쓰지 않습니다.

기록에는 모델 턴이 필요 없으며 세션 자신의 현재 worktree에 적용됩니다. 각 기록은 이벤트마다 최대 한 번 일어납니다.

| 이벤트 | 훅 | 기록 |
|---|---|---|
| pull request나 merge request 생성: `gh pr create`, `az repos pr create`, `glab mr create`이며 도구 출력에 링크나 Azure DevOps 요청 ID가 보임, `--help`, `-h`, `--dry-run`은 해당하지 않음 | `PostToolUse` | 상태 `in-review`, 코멘트 `Waiting for review: <링크>` |
| 턴이 `?`로 끝나는 마지막 줄의 질문으로 끝났고 `orca worktree set`을 실행하지 않음 | `Stop` | `--unread`, 코멘트 `Waiting for you: <첫 줄, 약 80자> · <이전 코멘트>` |
| 사용자의 다음 프롬프트, 코멘트가 아직 훅이 쓴 그대로일 때 | `UserPromptSubmit` | 세션 상태 파일에 보관한 이전 코멘트 |
| 상태가 `completed`, `todo`이거나 없는 현재 worktree 안의 편집이나 `git commit`, 커밋은 `git -C <dir>`이나 앞의 `cd <dir> &&`가 가리키는 곳 기준 | `PostToolUse` | 상태 `in-progress`, 코멘트는 그대로 |

Claude Code `language` 설정이 한국어이면 라벨은 한국어(`리뷰 대기`, `답변 대기`)이고, 아니면 영어입니다. 기본 네 가지
밖의 상태 ID는 건드리지 않습니다. 보드를 사용자 정의한 것이므로 코멘트만 씁니다. worktree 안에서 확인한 뒤에는 작업 재개 기록이
60초 동안 Orca를 다시 읽지 않으며, 밖의 편집이나 커밋은 기록도 대기 시작도 하지 않습니다. `orca_status_writes` 옵션으로 이 기록을 끌 수 있으며, Claude Code에서는
`/config`, Codex에서는 `HEI5ENBUG_ORCA_STATUS_WRITES`를 씁니다. 상태는
`$XDG_STATE_HOME/hei5enbug-agent-setup/orca-status/<session id>.json`에 둡니다.

두 가지는 아직 모델이 필요하므로, `Stop` 훅이 상태마다 한 번 턴을 이어 가게 하며, 정확한 명령을 알려 주고 답을 반복하지
않고 턴을 끝내라고 요청하는 두 문장 이하의 알림을 보냅니다. Claude Code는 이 알림을 훅 오류가 아니라
`Stop hook feedback`으로 표시합니다. 주 클론이 아니고, 자동 이름을 그대로 쓰며, 이 세션에서 파일을 고치거나 커밋한 작업용
worktree에는 `orca worktree set --display-name`을 알립니다. `orca worktree set`을 실행하고도 `orca terminal rename`을 한
번도 실행하지 않은 세션에는 탭 제목을 알리며, 둘 다 해당하면 알림 하나에 두 명령을 담습니다. 각 알림은 세션당 최대 한 번
일어나고, 훅 때문에 이어진 멈춤에서는 다시 일어나지 않습니다. 알림 한 번에 측정한 한 컴퓨터 기준 약 265,000 캐시 읽기와
출력 토큰이 들며, 이것이 반복되는 유일한 모델 비용입니다. Orca는 탭 제목을 보고하지 않으므로 훅은 세션 자신의
`orca terminal rename` 명령만으로 제목을 판단합니다.
