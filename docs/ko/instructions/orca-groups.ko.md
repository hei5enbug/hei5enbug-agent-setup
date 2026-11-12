# Orca worktree 그룹

> 영어 원본: [orca-groups.md](../../../instructions/orca-groups.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

저장소를 둘 이상 변경하는 작업의 Orca 세션을 시작하기 전, 그리고 나중의 세션이 그런 작업에 참여하기 전에 이 문서를
읽는다. 그룹은 티켓이나 이슈 하나를 위해 만든 모든 Orca worktree이며, 그 키나 링크로 식별한다. 티켓이나 이슈가 없으면
현재 요청을 기준으로 한다. 모든 worktree는 자기 저장소의 workspace 아래에 두거나, 사용자가 티켓을 위해 정한 Orca 폴더
workspace 아래에 두며, 다른 저장소의 worktree 아래에는 절대 두지 않는다. 그룹을 묶는 것은 Orca의 계층이 아니라
티켓이다. 저장소 하나만 다루는 작업은 [다른 저장소 작업](cross-repository.ko.md)만 따른다.

## 그룹 구성

- 조정자는 작업을 시작하는 세션이며, 어디에서 실행되든 같다. 배포나 병합 순서는 어느 저장소가 먼저 배포되거나
  병합되어야 하는지에 따라 정하며, 조정자가 결정하지 않는다.
- 조정자 자신의 worktree를 포함한 모든 구성원을 세 가지로 묶는다. `--reference <issue link>`, 티켓 키로 시작하는
  표시 이름, 목표가 `<ticket key> <summary>`인 orchestration Run 하나다. 전체 이슈 링크에는 Jira 연결이 필요 없으며,
  이 옵션 없이 만든 worktree에는 `orca reference add`로 추가한다. 그래도 연결에 실패하면 브랜치나 표시 이름에 티켓
  키를 남기고 실패를 보고한다.
- 티켓을 위해 무언가를 만들기 전에 그 그룹을 찾는다. `orca reference find <issue link> --json`을 실행한다. 티켓 키만
  사용하는 방식은 `orca jira connection --json`이 `connected: true`를 보고할 때만 동작한다. 아무것도 나열되지
  않으면 `orca worktree list --json`에서 표시 이름이나 브랜치에 정확한 티켓 키가 포함된 worktree를 찾는다. 그 키로
  시작하는 더 긴 키는 제외한다. Run은 `orca orchestration run-list --json`에서 목표로 찾는다. 목표는 티켓 키, 공백,
  요약 순서이며, 같은 문자로 시작하기만 하는 더 긴 키는 다른 티켓이다. Run이 없으면 조정자가
  `orca orchestration run-create --objective "<ticket key> <summary>" --json`으로 만든다.
- 조정자는 다른 각 저장소의 구성원을 Run의 worker로 만들어 질문하고 보고할 수 있게 한다. 다른 저장소 작업의
  2단계대로 브랜치와 기준 브랜치를 고른다. 에이전트 없이 해당 저장소 자신의 workspace 아래에
  `orca worktree create --repo id:<repoId> --name <branch> --base-branch <base> --parent-worktree
  id:<repoId>::<clone path> --reference <issue link> --json`으로 worktree를 만들고, 다른 저장소 작업의 4단계를 적용한
  뒤 `orca worktree list`에서 브랜치를 확인하고 표시 이름을 설정한다. 그 뒤에만 worker를 시작해 브랜치가 확정되기 전에
  실행되지 않게 한다.
  `orca orchestration worker-start --worktree path:<worktree path> --agent <host> --run <run id> --task-title
  "<ticket key> <repository>" --spec-file <brief file> --json`을 사용하고, 다른 저장소 작업의 6단계대로 작업 요약을 쓴다.
- 나중에 참여하는 세션은 같은 방식으로 `--agent <host>`를 붙여 worktree를 만들고, 다른 저장소 작업과 같은 방식으로
  인수인계하며, Run을 통해 조정자에게 알린다.
- 다른 구성원을 기다리지 않고 자신의 부분을 끝낼 수 있을 때만 구성원을 시작한다. 다른 구성원이 아직 공유하지 않은
  계약, 스키마, API, 결정이 필요하면 worktree와 worker 모두 만들지 않는다. 상태 표에 해당 항목을 기다리는 것으로
  적고, 그 항목이 공유된 뒤에 시작한다. 그런 의존성이 없는 구성원은 함께 시작한다.
  플러그인이 메모리 부족으로 시작을 거부하면 그 구성원을 메모리 대기 상태로 적고, 다른 구성원이 끝나거나 정리된
  뒤에 시작한다. 메모리를 폴링하지 않는다.
- 사용자가 티켓의 worktree를 묶을 Orca 폴더 workspace를 정하면, 저장소의 workspace 대신 그 폴더가 부모다.
  `orca worktree create`에, 이미 있는 worktree에는 `orca worktree set`에 `--parent-worktree folder:<id>`를 쓴다.
  사용자가 정하지 않았으면 저장소 자신의 workspace를 쓴다.
- 조정 세션 하나가 여러 티켓을 맡을 수 있다. 각 티켓은 자신의 참조, 이름, Run을 가진다.
- 자신의 부분을 주 체크아웃에서 완료한 저장소는 구성원이 될 수 없다. 그대로 두고 조정자의 상태에 명시하며, 사용자가
  요청할 때만 작업을 worktree로 옮긴다.

## 공유

- 구성원은 다른 구성원의 작업이 의존하는 내용을 알게 되는 즉시 공유한다. 계약, 스키마, API 변경, 결정, pull request
  링크, 배포나 병합 순서, 차단 요인이 여기에 해당한다. 일상적인 진행 상황은 공유하지 않는다.
- worker는 `orca orchestration send --to @all --subject <topic> --body <text> --json`으로 다른 구성원에게 보내고,
  `--to` 없이 보내 조정자의 Run에도 전달한다. 조정자는 `--to dispatch:<id>`로 구성원 하나에게 보낸다. worker가 아닌
  구성원은 `run:<run id>`로 보낸다. 다음 항목의 답을 제외하면 터미널 핸들을 수신자로 지정하지 않는다. 그 사서함은
  터미널이 닫히면 사라진다.
  공유할 변경을 다른 세션의 입력창에 직접 입력하지 않는다. 터미널 전송은 여전히 "다른 세션에 메시지 보내기"를 따른다.
- 계속 진행하려면 다른 구성원의 답이 필요한 구성원은 조정자에게 묻고 턴을 끝낸다. worker는
  `orca orchestration ask --question <text>`를 실행하고, 조정자는
  `orca orchestration reply --id <message id> --body <text>`로 답한다. `ask`는 Dispatch 밖에서 실패하므로 worker가
  아닌 구성원은 `orca orchestration send --to run:<run id> --from $ORCA_TERMINAL_HANDLE --subject "Question: <topic>"
  --body <text> --json`을 보내고 `orca orchestration check --terminal $ORCA_TERMINAL_HANDLE --wait --timeout-ms
  1800000 --json`으로 기다린다. 호스트가 백그라운드 작업 완료를 알려 주면 백그라운드에서 기다린다. 조정자는 그 터미널이
  기다리는 동안 `orca orchestration send --to <that member's terminal handle> --subject "Answer: <topic>" --body <text>
  --json`으로 답한다. 조정자는 작업이나 사용자 지침에서 답을 도출할 수 있을 때만 답하고, 그렇지 않으면 사용자에게 묻는다.
- Orca가 새 메시지로 구성원을 깨웠으면 다음 단계마다 새 메시지를 읽고, 공유된 변경을 먼저 반영한다.

## 상태

- 조정자는 구성원 표를 유지한다. 저장소, worktree, 브랜치, pull request, 검사, 미해결 차단 요인을 담고,
  아직 시작하지 않은 구성원은 무엇을 기다리는지도 적는다.
- `worker_done`, 질문, 공유된 변경 같은 이벤트가 생기면 표를 갱신한다. 오랫동안 소식이 없을 때만
  `orca orchestration worker-read`로 구성원을 읽고, 계속 폴링하지 않는다.
- 구성원의 승인 창이나 사용자에게 한 질문에 대신 답하지 않는다. 사용자에게 보고한다.
- 사용량 한도 등으로 조정자가 멈추기 전에 [중단과 재개](pause-and-resume.ko.md)에 따라 재개 메모에 표를 기록해,
  재개한 세션이 이어서 진행할 수 있게 한다.
- 구성원의 최종 보고나 `worker_done`이 남은 일이 없다고 하면 그 구성원은 완료된 것이다.

## 완료된 구성원 정리

그룹의 모든 세션은 작업이 끝날 때 완료된 worktree를, 어느 세션이 시작했든,
[Orca worktree 상태](orca-worktree-status.ko.md)의 "작업이 끝날 때의 정리"대로 삭제한다. 이에 더해 구성원이 완료되면
조정자가 같은 검사와 절차로 즉시 정리하고, 조정자 자신이 끝날 때도 전체 그룹에서 놓친 완료된 구성원이 있는지 한 번 더
확인한다. 그룹 구성원에게는 이 절차가 다른 저장소 작업의 "인수인계 후"를 대신한다. 주 체크아웃에서 작업한 구성원은
백그라운드 작업, 프로세스, 터미널만 중단하거나 닫는다. 체크아웃과 기본 브랜치는 절대 건드리지 않는다.

조정자가 worker의 터미널을 닫기 전에, worker가 백그라운드 셸 작업이나 모니터 같은 자신의 백그라운드 작업을 중단하게
하고 남은 작업이 없음을 확인한다. 이후 구성원의 터미널, 프로세스, 리스너가 남지 않았는지 확인하고, 닫거나 중단한 항목을
각각 보고한다.
