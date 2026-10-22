# 다른 저장소 작업

> 영어 원본: [cross-repository.md](../../../instructions/cross-repository.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

현재 세션의 작업 디렉터리가 속한 작업 저장소가 아닌 다른 Git 저장소의 파일을 변경하기 전과, 다른 에이전트
세션에 메시지를 보내기 전에 이 문서를 읽는다.
다른 저장소를 읽기만 할 때는 이 절차가 필요 없다.

대상 저장소에서 이 작업의 브랜치를 사용하는 worktree에서 변경한다. 기본 브랜치의 주 클론처럼 다른 브랜치를
사용하는 체크아웃에는 다른 작업이 있을 수 있으므로 그곳에서 변경하지 않는다.
변경은 대상 저장소의 세션이 담당하므로 해당 저장소의 지침, 훅, 브랜치 규칙을 따른다.

## Orca worktree

`orca status --json`이 접근 가능한 런타임을 보고하면 Orca CLI를 사용한다. 이 파일에 없는 플래그가 필요하면
`orca skills get orca-cli`를 한 번 실행한다.

1. `orca repo list --json`에서 대상을 찾는다. 기존 로컬 클론은 `orca repo add --path <path>`로 등록한다.
   로컬 클론이 없으면 사용자에게 어디에 클론할지 묻는다.
2. 무언가를 만들기 전에 대상에 적용되는 첫 번째 출처를 기준으로 브랜치 이름과 기준 브랜치를 정한다.
   이미 읽은 스킬 또는 플러그인 규칙, 대상의 `AGENTS.md` 또는 `CLAUDE.md` 순서로 확인하고, 없으면 저장소의
   기본 기준 브랜치에서 작업 이름을 딴 짧은 브랜치를 사용한다. 먼저 원격에서 기준 브랜치를 fetch한다.
3. `<host>`는 Claude Code에서는 `claude`, Codex에서는 `codex`다. `<clone>`은 `orca repo list`에 있는 대상의
   경로이고, 대상의 workspace는 `orca worktree list --repo id:<repoId> --json`에서 그 경로를 가진 항목이다.
   `git -C <clone> worktree list --porcelain`에서 선택한 브랜치의 worktree를 찾은 뒤, 아래에서 처음 맞는 경우를 따른다.
   - 그 worktree가 Orca 목록에 자기 항목을 가지고 있다: `orca terminal list --worktree id:<worktree id> --json`으로
     확인한다. 그곳에 에이전트 터미널이 열려 있으면 사용자에게 그 터미널로 작업 요약을 보낼지 묻는다. 없으면
     `orca terminal create --worktree id:<worktree id> --command <host> --json`으로 시작하고 5단계로 진행한다.
   - 그 worktree가 자기 항목이 없다: workspace 안에 있는 worktree이고, Orca는 workspace의 터미널 중 어느 것이
     그 안에서 실행 중인지 구분하지 못한다. 사용자에게 workspace의 터미널 제목을 보여 주고, 그중 하나로 작업 요약을
     보낼지 다음 경우처럼 새 터미널을 시작할지 묻는다.
   - 해당 브랜치의 worktree가 없고 `git -C <clone> check-ignore -q .claude/worktrees/<name>`이 성공한다. 여기서
     `<name>`은 브랜치 이름의 `/`를 `-`로 바꾼 것이고, 그 디렉터리가 이미 있으면 `-2` 같은 접미사를 붙인다:
     새 workspace 대신 workspace 안에 worktree를 만든다.
     `git -C <clone> worktree add -b <branch> <clone>/.claude/worktrees/<name> <remote>/<base>`를 실행하고, 로컬이나
     원격에 이미 있는 브랜치이면 `git -C <clone> worktree add <clone>/.claude/worktrees/<name> <branch>`를 실행한다.
     그다음 `orca terminal create --worktree id:<workspace id> --title <branch>
     --command "cd '<worktree path>' && <host>" --json`을 실행하고 5단계로 진행한다.
   - 그 밖의 경우: 대상이 그 경로를 무시하지 않으므로 그곳의 worktree가 클론에서 추적되지 않은 파일로 보인다.
     `orca worktree create --repo id:<repoId> --name <branch> --base-branch <base> --agent <host> --json`을 실행한다.
     작업 디렉터리가 Orca worktree이면 `--parent-worktree active`를, 아니면 `--no-parent`를 추가한다.
     `--prompt`는 전달하지 않는다.
4. `orca worktree create` 뒤에는 Orca가 설정된 접두사를 붙이고 `/`를 대체해 새 브랜치 이름을 직접 정한다. 결과의
   `branch`가 정한 이름과 다르고 정한 이름의 브랜치가 아직 없으면 `git -C <worktree path> branch -m <branch>`를
   실행한다. 이미 로컬이나 `origin`에 있으면 `git -C <worktree path> switch <branch>`를 실행한 뒤,
   `git -C <worktree path> branch -D <Orca branch>`로 Orca가 만든 미사용 브랜치를 삭제한다.
   `orca worktree show`는 이전 이름을 표시할 수 있으므로 `orca worktree list`에서 이름을 확인한다.
5. `orca terminal create`가 돌려준 핸들을 사용한다. `orca worktree create` 뒤에는
   `orca terminal list --worktree id:<worktree id> --json`으로 에이전트 터미널을 찾는다.
   `orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json`을 실행하고,
   `wait.satisfied`가 true이고 "다른 세션에 메시지 보내기"가 허용할 때만 보낸다. 더 긴 시간 제한으로 한 번 더
   기다리고, 여전히 false이면 인수인계가 시작되지 않았다고 보고한다.
6. `orca terminal send --terminal <handle> --text "<brief>" --enter --json`으로 작업 요약을 보낸다.
   요약에는 목표, 파일 경로를 포함해 지금까지 찾은 근거, 브랜치와 기준 브랜치, 수용 검사를 명시한다.
   전송 결과가 `accepted: true`이면 인수인계가 끝난 것이다. 작업 완료를 기다리지 않는다.

## 다른 세션에 메시지 보내기

- `tui-idle`은 실행 중인 턴이 없다는 뜻일 뿐이다. 보낼 때마다 `orca terminal read --terminal <handle> --screen`으로
  대상을 읽고, 열린 승인 창이나 질문이 없고 입력창이 비어 있을 때만 보낸다. 대상이 사용자를 기다리면 기다리지 말고
  그 사실을 보고한다. 대상의 프롬프트에는 절대 답하지 않는다.
- 입력창의 글은 호스트의 회색 제안일 수 있다. `--text x`를 보내 입력창에 `x`만 보이면 `--text $'\x7f'`로 지우고
  보낸다. 아니면 `x`를 지우고 아무것도 보내지 않으며, 사용자에게 그 글이 남아 있다고 알린다.
- 답은 마지막 메시지와 상태 줄로 판단하고, 늦게 갱신될 수 있는 작업 목록으로 판단하지 않는다.

## Orca가 없을 때

Orca CLI나 런타임을 사용할 수 없으면 일반 Git worktree를 사용할지 한 번 묻는다. 승인받으면 2단계와 같은 방식으로
브랜치를 정하고, 기존 모든 체크아웃 밖의 경로를 고른다. 새 브랜치이면
`git -C <target> worktree add -b <branch> <path> <base>`를 실행하고, 로컬이나 `origin`에 이미 있는 브랜치이면
`git -C <target> worktree add <path> <branch>`를 실행한다. 대상의 `AGENTS.md` 또는 `CLAUDE.md`를 읽고
이 세션에서 그곳의 파일을 변경한다. 승인받지 못하면 다른 저장소의 변경을 중단하고 보고한다.

## 새 worktree의 내용

새 worktree에는 `.env`나 로컬 설정 같은 무시된 파일도, 설치된 의존성도 없다. 보호 값을 복사하지 않는다.
그 파일이 필요한 세션이 사용자에게 보고한다.

## 인수인계 후

- 현재 요청에 대해 작업 저장소에서 할 일이 남지 않으면, 대상 worktree의 세션에서 계속하고 이 세션은
  종료하라고 사용자에게 한 줄로 권한다. 세션을 직접 종료하지 않는다.
- 할 일이 남았으면 계속 진행하고, 대상의 결과가 필요할 때만 `orca terminal read --terminal <handle> --json`으로
  읽는다.
- worktree나 그 브랜치는 사용자가 요청할 때만 삭제한다.
