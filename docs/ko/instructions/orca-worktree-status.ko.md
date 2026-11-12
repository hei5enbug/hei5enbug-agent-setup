# Orca worktree 상태

> 영어 원본: [orca-worktree-status.md](../../../instructions/orca-worktree-status.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

`ORCA_TERMINAL_HANDLE`로 식별되는 Orca 터미널에서 실행 중인 세션은 작업의 첫 파일 변경 전에, 그리고 그 작업의 최종 보고 전에
다시 이 문서를 읽는다. 세션의 Orca worktree와 탭에 작업 이름을 유지하고, 세션이 남긴 완료된 자식 worktree를 삭제한다.

어떤 훅이나 세션도 스스로 보드 상태, worktree 설명, 읽지 않음 플래그를 쓰지 않는다. 이는 사용자가 정하거나,
`session-triage`의 재개 메모처럼 요청에서 그 쓰기를 승인한다. 유일한 예외는
"작업이 끝날 때의 정리"의 `completed`다. Orca는 세션이 질문하면 스스로 사용자에게 알린다.

`orca worktree current --json`으로 worktree를 찾고
`orca worktree set --worktree id:<worktree id> --display-name <name> --json`으로 이름을 정한다. 이 플래그는 Orca
메타데이터만 바꾸며, 파일, Git 상태, 실행 중인 터미널은 바꾸지 않는다. 다른 세션의 작업을 위해 만든 worktree는 갱신하지
않는다.

## 이름

작업용으로 만든 worktree에서는 작업을 시작할 때 `--display-name "<ticket key> <short summary>"`를 설정한다.
티켓이 없으면 짧은 작업 이름을 쓴다. 이후에는 작업 범위가 바뀔 때만 이름을 바꾸며, worktree가
`displayNameMode: automatic`을 표시하거나 이 세션이 마지막으로 설정한 이름을 유지하고 있을 때만 바꾼다. 다른 이름은
사용자가 정한 것이므로 유지한다.

## 탭 제목

표시 이름과 같은 이벤트에서, 주 클론에서도 세션 자신의 탭 제목을
`orca terminal rename --terminal "$ORCA_TERMINAL_HANDLE" --title "<ticket key> <short summary>" --json`으로
설정한다. 티켓이 없으면 짧은 작업 이름을 쓴다. 주 클론에서는 탭 제목이 작업을 알려 주는 유일한 곳이다. 플러그인 훅이 매
프롬프트마다 세션이 마지막으로 설정한 제목을 보여 준다. 프롬프트가 제목에 없는 작업을 요청하면 시작하기 전에 탭 제목을
바꾸고, 사용자가 직접 정했다고 말한 제목은 유지한다.

플러그인의 Stop 훅이 이름이나 탭 제목 명령을 지정하면 그 명령을 실행하고 답을 반복하지 않은 채 턴을 끝낸다.

## 작업이 끝날 때의 정리

최종 보고 전에 세션 자신의 저장소의 자식 worktree 각각과, 어느 저장소든 작업 티켓 그룹의 worktree 각각을, 어느 세션이
시작했든 확인한다. 그룹은 티켓의 이슈 링크를 참조로 갖거나 정확한 키를 표시 이름이나 브랜치에 담은 모든 worktree다.
[Orca worktree 그룹](orca-groups.ko.md)의 "구성"에 있는 두 조회, 즉 참조 조회와 정확한 키 검색을 모두 실행하고, 참조 조회가
무언가를 찾았더라도 두 결과의 worktree를 모두 확인한다. 티켓이 없는 작업은 저장소의 자식 worktree만
확인한다. 주 클론, 현재 worktree, 자식 worktree가 있는 worktree, 원격 브랜치는 절대 삭제하지 않는다.

worktree가 완료된 것은, 기준 브랜치가 다른 해시로 적용된 커밋을 포함해 브랜치의 모든 커밋의 내용을 담고 있으며 터미널이
없거나 열린 질문 없이 유휴 상태인 터미널만 있을 때, 또는 에이전트 세션이 실행되지 않고 브랜치가 푸시되었을 때다. 푸시된
경우란 `git fetch` 뒤 `git rev-list --count @{upstream}..HEAD`가 0인 것이며, 업스트림이 없는 브랜치는 통과하지 못한다.
완료된 worktree에는 다음을 수행한다.

1. `git status --porcelain`이 비어 있고 `git status --porcelain --ignored`가 `__pycache__`, `.pytest_cache`,
   `node_modules` 같이 다시 만들 수 있는 캐시나 빌드 산출물만 나열하는지 확인한다.
2. `orca terminal list --worktree id:<worktree id> --json`이 나열하는 터미널을
   `orca terminal close --terminal <handle> --json`으로 닫는다. worker이면
   `orca orchestration worker-release --dispatch <id> --json`을 사용한다.
3. 작업 디렉터리가 그 안에 있는 프로세스가 없는지, 예를 들어 `lsof -d cwd -Fpn`으로 확인하고,
   `orca ports --worktree id:<worktree id> --json`에 리스너가 없는지 확인한다. worktree의 세션이 시작한 프로세스는
   중단한다. 터미널을 닫아도 데몬이나 컨테이너처럼 별도 세션으로 분리된 프로세스는 중단되지 않는다.
4. `orca worktree rm --worktree id:<worktree id> --delete-branch --json`으로 worktree와 로컬 브랜치를 삭제한다.

프로세스가 남아 있으면 worktree와 브랜치를 그대로 두고 보고에 그 프로세스를 적는다. 완료되지 않았거나 검사에 실패한 worktree는
질문 없이 그대로 두고, 푸시하지 않은 커밋이나 실패한 검사 같은 이유와 함께 보고에 나열한다.

그다음 그 범위에서 세션이 유지하는 workspace 중 어떤 종류의 터미널도 없고, 즉 Claude Code나 Codex 세션도 셸도 없고,
커밋하지 않았거나 푸시하지 않은 변경이 없는 것, 예를 들어 주 클론이나 티켓의 폴더마다
`orca worktree set --worktree id:<workspace id> --workspace-status completed --json`으로 `completed`를 설정한다. Orca는
상태 ID를 검증하지 않고 저장한다. 같은 저장소의 worktree가 이미 `todo`, `in-progress`, `in-review`, `completed`가 아닌
ID를 사용하면 보드를 사용자 정의한 것이므로 그 상태는 바꾸지 않는다. 플러그인 훅은 커밋하지 않았거나 푸시하지 않은 작업이
있는 worktree를 `completed`로 바꾸는 것을 거부한다. 보고에는 세션이 확인한 worktree를 모두 적는다. 삭제한 것은 각각, 유지한 것은 각각 그 이유와 함께 적는다.
