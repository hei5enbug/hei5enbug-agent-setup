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
매번 묻는 쿼리는 항상 코드와 함께 거부합니다([승인 가드](approval-guard.ko.md#승인-가드)를 참고하세요). 토글을 끄면 모든 쓰기가 이전처럼 승인을 요청합니다. Claude Code에서는 시작된 스킬의 유지된 항목이 선언한 비운영 연결의 쿼리가 묻지 않고 실행됩니다([쓰기나 호출 매칭](approval-guard.ko.md#쓰기나-호출-매칭) 참고). Codex에서는 `/hooks`
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
  명령을 허용합니다. 사용자가 티켓을 위해 정한 Orca 폴더 workspace인 `folder:<id>` 부모는 어느 저장소에도 속하지
  않으므로 허용합니다.
- **작업이 남은 완료.** `orca worktree set --workspace-status completed`는 대상 worktree, 즉 현재 worktree나
  `--worktree` 선택자가 `id:<repoId>::<path>`나 `path:`로 가리키는 worktree에 커밋하지 않은 변경이나 업스트림에 없는
  커밋이 있으면 거부하며, 거부 사유에 남은 것을 나열합니다. 세션은 코멘트를 쓰지 않으므로 거부 사유가 코멘트를 요구하지
  않습니다. 깨끗한 worktree, 다른 상태, 확인할 수 없는 대상은 허용합니다.
- **호스트가 만드는 worktree.** Orca 터미널에서 `path` 없는 `EnterWorktree`는 Orca가 목록에 올리지 않는 worktree를
  만들므로, 대신 쓸 `orca worktree create` 명령을 알려 주며 거부합니다. 기존 `path`로 들어가는 호출과 Orca 밖의
  호출은 허용합니다.
- **주 클론 이름.** 비어 있지 않은 이름을 주는 `orca worktree set --display-name`은 `--worktree` 선택자가 가리키는
  worktree가 모두 `orca worktree list`에서 저장소의 주 클론일 때 거부합니다. `active`와 `current`는
  `orca worktree current`로 읽습니다. 그대로 두면 주 클론의 모든 세션이 한 작업의 이름 아래 보이므로, 거부 사유는 세션에
  이름을 붙이는 `orca terminal rename`을 알려 줍니다. Orca의 자동 이름을 되돌리는 빈 이름, 목록에 없는 대상, Orca를 읽을
  수 없는 경우는 허용합니다. 2026-11-06에 한 세션이 저장소의 주 클론에 티켓 이름을 고정했기 때문에 생겼습니다. 그때도
  글로 된 규칙은 이미 이를 금지하고 있었습니다.
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

훅 스크립트 하나인 `scripts/orca_status_hook.py`가 세션의 탭 제목을 유지하고, 이름이나 탭 제목이 없으면 세션에 알립니다.
Orca에는 아무것도 쓰지 않습니다. 보드 상태, worktree 설명, 읽지 않음 플래그는 오래된 값이 되므로 쓰지 않으며, 상태는
사용자가 정하고 세션이 질문하면 Orca가 스스로 사용자에게 알립니다. 이 훅은 `ORCA_TERMINAL_HANDLE`이 설정된 경우에만
실행되고, 서브에이전트나 지정된 작업자에서는 실행되지 않으며, Orca, Git, 기록을 읽지 못하면 그 이벤트를 통과시킵니다.
Codex는 도구 호출을 스크립트 텍스트로 기록하므로 Claude Code 기록만 읽습니다.

훅은 세션의 탭 제목을 기억합니다. 이 터미널을 `"$ORCA_TERMINAL_HANDLE"`이나 그 값으로 가리키고 `--title` 또는
`--title=`이 `$`나 백틱 없는 글자 그대로의 값인 `orca terminal rename`을 Bash로 실행한 `PostToolUse` 뒤에 그 제목을 상태
파일에 저장하고, 이후의 이름 변경이 그것을 교체합니다. 다른 터미널의 이름 변경이나 훅이 글자 그대로 읽을 수 없는 제목은
무시하고 이전 제목을 유지합니다. 기억한 제목이 있는 세션의 모든 `UserPromptSubmit`에서 훅은
`Current Orca tab title: <title>. If this prompt asks about or for work the title does not name, such as another
ticket, pull request, repository, document, or goal, retitle the tab before starting it. A follow-up, fix, review,
merge, or question on the titled work keeps the title, as does one the user set.` 한 줄(약 300자)을 컨텍스트에 더하며,
기억한 제목이 없는 세션에는 아무것도 더하지 않습니다. 제목은 도구 입력에서 얻으므로 Codex에서도 동작합니다. 상태는
`$XDG_STATE_HOME/hei5enbug-agent-setup/orca-status/<session id>.json`에 둡니다.

두 가지는 아직 모델이 필요하므로, `Stop` 훅이 상태마다 한 번 턴을 이어 가게 하며, 정확한 명령을 알려 주고 답을 반복하지
않고 턴을 끝내라고 요청하는 두 문장 이하의 알림을 보냅니다. Claude Code는 이 알림을 훅 오류가 아니라
`Stop hook feedback`으로 표시합니다. 주 클론이 아니고, 자동 이름을 그대로 쓰며, 이 세션에서 파일을 고치거나 커밋한 작업용
worktree에는 `orca worktree set --display-name`을 알립니다. `orca worktree set`을 실행하고도 `orca terminal rename`을 한
번도 실행하지 않은 세션에는 탭 제목을 알리며, 둘 다 해당하면 알림 하나에 두 명령을 담습니다. 각 알림은 세션당 최대 한 번
일어나고, 훅 때문에 이어진 멈춤에서는 다시 일어나지 않습니다. 알림 한 번에 측정한 한 컴퓨터 기준 약 265,000 캐시 읽기와
출력 토큰이 들며, 매 프롬프트에 약 300자를 더하는 탭 제목 줄을 빼면 이것이 반복되는 유일한 모델 비용입니다. Orca는 탭
제목을 보고하지 않으므로 훅은 세션 자신의 `orca terminal rename` 명령만으로 제목을 판단합니다.

## 최종 보고 검토

Claude Code 전용 `Stop` 훅인 `scripts/final_report_hook.py`는 변경 뒤에 나가는 최종 보고를
`instructions/shared-text.md`의 독립 텍스트 검토가 확인하지 않았을 때 턴을 한 번 이어 가게 합니다. 이유는
`hookSpecificOutput.additionalContext`로 돌려주며, Claude Code는 이를 훅 오류가 아니라 `Stop hook feedback`으로
표시합니다. 두 가지 이유를 각각 한 턴에 한 번까지만 보냅니다. `stop_hook_active`가 true인 멈춤을 모두 건너뛰는 대신, 세션
기록의 현재 턴에서 자신이 앞서 보낸 피드백을 찾습니다. 그래서 이 훅이나 다른 훅이 이어 간 멈춤도 검사하고, 요청한 검토
뒤에 보낸 보고도 검토한 초안과 비교합니다. 아래 조건이 모두 맞을 때만 턴을 이어 가게 합니다.

- 이벤트가 주 세션의 것입니다. `agent_id`가 없고, `HEI5ENBUG_ASSIGNED_ROLE`과 `HEI5ENBUG_PARENT_SESSION`이 모두
  설정되지 않았습니다.
- 현재 턴이 같은 이유를 아직 받지 않았습니다.
- `background_tasks`가 없거나 비어 있습니다. 작업이 아직 돌고 있으면 그 답은 최종 보고가 아니기 때문입니다.
- 마지막 실제 사용자 프롬프트부터 끝까지의 현재 턴이 파일을 바꿨습니다. `Edit`, `Write`, `MultiEdit`,
  `NotebookEdit` 호출, Bash `git commit`, 또는 heredoc 본문을 뺀 Bash 명령이 `>`, `>>`, `>|`, `&>`, `tee`,
  `sed -i`, `perl -i`로 파일을 쓰는 경우가 그렇습니다. 이런 쓰기는 `$`, `~`, `&`로 시작하지 않고 `/dev/`, `/tmp/`,
  `/private/`, `/var/folders/` 아래가 아닌 글자 그대로의 경로일 때만 셉니다. 또 Bash 명령이 `env` 등 래퍼 뒤에 오는 경우를
  포함해 `python`, `python3`, `python3.N`, `node`, `ruby`, `perl`을 실행하면서 코드를 stdin의 heredoc이나 `-c`, `-e`로
  받고, 그 코드(heredoc 본문 포함)에 `write_text(`, `write_bytes(`, `.write(`(`stdout`, `stderr`에 대한 것은 제외),
  쓰기 모드(`w`, `a`, `x`)의 `open(`, `json.dump(`, `shutil.copy`, `shutil.move`, `os.replace(`, `os.rename(`,
  `writeFileSync(`, `appendFileSync(`, `File.write(` 같은 쓰기 호출이 있으면 셉니다. 훅은 그런 스크립트가 쓰는 경로를
  해석하지 않습니다. 위임한 작업도 셉니다. 위임된 실행의 편집은 주 세션 기록에 남지 않기 때문입니다. `subagent_type`을
  대소문자 구분 없이 봤을 때 `scout`, `review`, `explore`, `plan`, `guide`, `statusline` 중 어느 것도 포함하지 않거나
  `subagent_type`이 없는 `Agent`·`Task` 호출(기본 에이전트는 쓸 수 있기 때문)과, `role_runner.py`를 파일 이름 기준으로
  (`python3` 뒤에 붙은 경우도 포함해) 실행하면서 첫 위치 인자가 `worker`, `implementation`, `designer`, `language`,
  `writer`, `agent`인 Bash 명령이 그렇습니다.
- 그 턴이 `text_review.py review --kind final-report`와 `text_review.py check --kind final-report`를 하나도 실행하지
  않았습니다. 그 턴이 쓴 문서처럼 다른 종류의 글을 검토한 것은 치지 않습니다.
  `python3` 뒤에 붙은 실행도 셉니다.
- `last_assistant_message`가 보고입니다. 앞뒤 공백을 뺀 길이가 400자 이상이고, 비어 있지 않은 마지막 줄이 `?`나
  `？`로 끝나지 않습니다.

이유는 네 문장 이내이며, 이 턴이 파일을 바꿨고 어떤 텍스트 검토도 확인하지 않은 최종 보고로 끝난다고 말하고, 플러그인의
`instructions/shared-text.md`의 "Independent text review" 절과 `text_review.py review --kind final-report --draft <file> ...`
명령을 알리며, 그 결과를 반영하라고 요청하고, 이 턴이 다른 사람을 위해 쓴 나머지 모든 글도 각자의 `--kind`로 같은 방식으로
검토하라고 요청한 뒤, 보고를 다시 보내라고 요청합니다. 훅은 기록을 한 번만 스트리밍으로 읽고 하위 프로세스를
시작하지 않습니다. 기록이 없거나 읽기나 파싱에 실패하거나 입력 형식이 잘못되면 멈춤을 통과시키고, 통과할 때는 아무것도
출력하지 않습니다. 이슈 #69의 평가 실행에서 에이전트가 텍스트 규칙을 읽지도 검토를 실행하지도 않고 최종 보고를 보냈고,
다른 실행에서는 Bash heredoc으로 문서를 쓴 뒤 검토 없이 보고를 보냈기 때문에 이 훅이 있습니다.

훅은 턴이 파일을 바꿨고, 통과한 `text_review.py review`나 `check --kind final-report`가 `final_report_sha256`을 냈는데
보낸 보고의 SHA-256이 그 값과 다를 때도 턴을 이어 가게 하며, 보고의 길이는 상관없고 비어 있지 않은 마지막 줄이 `?`나 `？`로 끝나는
메시지만 제외합니다. 양쪽 모두 줄바꿈 방식, 줄 끝 공백, 반복된 빈 줄, 앞뒤 빈 줄의 차이는
무시합니다. 이유는 보고가 마지막으로 통과한 검토가 확인한 초안과 다르다고 말하고, 그 글을 그대로 보내거나 바뀐 보고를
다시 검토하라고 요청합니다. 검토가 해시를 낸 적이 없는 턴은 이 규칙으로 이어 가게 하지 않습니다. 이슈 #69의 다른 평가 실행에서
에이전트가 검토를 통과한 뒤 최종 보고에 줄을 더해 보냈고, 채점자가 그 줄에서 문제를 찾았기 때문에 이 규칙이 있습니다.
인터프리터 스크립트 감지와 길이에 상관없는 불일치 규칙은 이슈 #69의 이후 평가 실행 둘 때문에 있습니다. 한 실행은
`python3` heredoc 스크립트로만 파일을 고친 뒤 검토 없이 711자 보고를 보냈고, 다른 실행은 통과한 초안과 다른 296자 보고를
보냈습니다.

## 훅 시간 제한과 기기 부하

각 훅은 등록이 선언한 timeout의 절반을 받으며, 시간은 런처가 시작한 때부터 셉니다. 셸이 자식 프로세스 없이 시계를 읽을 수 있으면 런처가 그 시각을
`HEI5ENBUG_HOOK_STARTED_AT`(에포크 기준 초)에 기록하고, 이 값이 없는 훅은 자기 프로세스 시작부터 셉니다. 선언된 timeout은
`scripts/hook_runtime.py`에 한 번만 있고, 테스트가 이를 모든 훅 파일과 비교합니다. 마감 뒤에 시작한 훅은 아무 일도 하지 않고
시간 초과 결과를 바로 돌려줍니다. 시간이 다 된 훅은 하던 일을 멈추고, 출력하려던 내용을 버리고, 스스로 답합니다.

- 출력이 호출이나 권한 요청을 거부할 수 있는 훅은 거부합니다. 대상은 `PreToolUse`와 `PermissionRequest`의 승인 가드, Orca 배치 훅,
  에이전트 가드, DataGrip 가드이며, 이유에 플러그인과 훅의 이름을 밝히고, 기기가 바빠서 끝내지 못했다고 말하고, 부하가 내려간 뒤 다시 시도하거나
  어느 세션이 기기를 쓰는지 확인하라고 안내하는 결정을 냅니다. 공개 경계 훅은 종료 코드 2와 같은 문장을 stderr에 내어 막습니다.
- 그 밖의 모든 훅은, 그렇지 않았다면 턴을 이어 가게 했을 `Stop` 훅도 포함해, 종료 코드 0과 출력 없음으로 끝나므로 에이전트의 작업이 이어집니다.

Orca 배치 훅의 `orca`와 `git` 호출에는 자체 고정 제한이 없으므로 멈춘 호출은 위의 거부로 끝납니다. 에이전트나 사용자에게 닿는 실패,
예를 들어 0이 아닌 종료 코드, stderr 문구, 거부는 플러그인과 훅의 이름, 건너뛰거나 막은 일, 다음 단계를 밝히고 추적 정보를 담지 않습니다.
잘못된 입력이나 관련 없는 입력은 여전히 조용히 끝납니다. 모든 도구 호출이나 프롬프트마다 도는 훅은 자식 프로세스를 시작하지 않고, 그 입력에
대한 결정에 필요한 것만 네트워크로 부릅니다. 예를 들어 `orca` 명령일 때만 `orca`를 실행합니다. [설정](configuration.md)의 백그라운드 인터프리터 해결이 유일한 예외입니다.

사용자가 프롬프트를 보낼 때마다 승인 가드의 `UserPromptSubmit` 단계는, 1분 평균 부하가 논리 CPU 수의 두 배 이상이거나, 가용 메모리가 물리 메모리의 10% 미만이거나,
작업 폴더가 있는 볼륨의 여유 공간이 10% 미만이면 프롬프트 맥락에 한 줄을 더합니다. 줄은 부족한 자원마다 현재 값과 기준을 밝히고, 빌드나 전체 테스트 실행, 여러 병렬
에이전트 같은 무거운 작업 전에 사용자에게 알리라고 에이전트에게 말합니다. CPU나 메모리라면 에이전트가 대부분을 쓰는 프로세스나 Orca 세션을 밝히거나 두드러진 것이 없다고 말하고,
그 세션을 확인하고 부하가 내려갈 때까지 기다리라고 권합니다. 저장 공간이라면 기다려도 소용없으므로 공간을 비우라고 권합니다. 에이전트는 가벼운 작업을 스스로 막거나 늦추지 않습니다.
줄은 세션마다 부족 상태가 시작될 때 한 번만 나옵니다. 줄이 나온 뒤에는 세 조건이 모두 거짓인 프롬프트가 나올 때까지 줄이 없고, 그 뒤 조건 하나가 참인 다음 프롬프트에서 다시 나옵니다.
계수기는 자식 프로세스 없이 운영체제에서 읽으며(`os.getloadavg`, `os.cpu_count`, `os.statvfs`, Linux는 `/proc/meminfo`, macOS는 `ctypes`로 읽는 `sysctl`),
읽을 수 없는 계수기는 부족하지 않은 것으로 칩니다. 부하 평균이 논리 코어 10개에서 60~69였던 기기에서 Codex 세션이 많은 명령 앞에 `hook timed out after 5s`를 보였고,
시간 초과된 검사는 적용되지 않았기 때문에 이 규칙이 있습니다.
