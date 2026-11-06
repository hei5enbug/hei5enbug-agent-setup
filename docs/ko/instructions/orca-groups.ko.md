# Orca worktree 그룹

> 영어 원본: [orca-groups.md](../../../instructions/orca-groups.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

저장소를 둘 이상 변경하는 작업의 Orca 세션을 시작하기 전, 그리고 나중의 세션이 그런 작업에 참여하기 전에 이 문서를
읽는다. 그룹은 티켓이나 이슈 하나를 위해 만든 모든 Orca worktree이며, 그 키나 링크로 식별한다. 티켓이나 이슈가 없으면
현재 요청을 기준으로 한다. 저장소 하나만 다루는 작업은 [다른 저장소 작업](cross-repository.ko.md)만 따른다.

## 그룹 구성

- 루트는 작업을 시작하고 조정하는 세션의 worktree다. "세션 위치"가 정한 곳에 그대로 둔다. 배포나 병합 순서는 어느
  저장소가 먼저 배포되거나 병합되어야 하는지에 따라 정하며, 루트가 결정하지 않는다.
- 티켓을 위해 무언가를 만들기 전에 그 그룹을 찾는다. `orca reference find <issue link> --json`을 실행한다.
  티켓 키만 사용하는 방식은 `orca jira connection --json`이 `connected: true`를 보고할 때만 동작한다.
  아무것도 나열되지 않으면 `orca worktree list --json`에서도 브랜치나 표시 이름에 정확한 티켓 키가 포함된
  worktree를 찾는다. 그 키로 시작하는 더 긴 키는 제외한다. 참조 없이 만든 구성원은 첫 번째 검색에서 빠지기 때문이다.
  어느 쪽이든 worktree가 나열되면 그룹이 이미 있는 것이다. 나열된 worktree 중 `parentWorktreeId`가 다른 나열된
  worktree를 가리키지 않는 것이 루트이며, 새 구성원은 그 아래에 둔다. 그 밖의 경우에는 이 세션의 worktree가 루트가 된다.
- 루트 세션에서 다른 각 저장소의 구성원을 루트의 자식이자 루트 orchestration Run의 worker로 만들어 질문하고 보고할 수
  있게 한다. 다른 저장소 작업의 2단계대로 브랜치와 기준 브랜치를 고른다. 에이전트 없이 구성원의 worktree를
  `orca worktree create --repo id:<repoId> --name <branch> --base-branch <base>
  --parent-worktree id:<root id> --reference <issue link> --json`으로 만들고, 다른 저장소 작업의 4단계를 적용한 뒤
  `orca worktree list`에서 브랜치를 확인한다. 그 뒤에만 해당 worktree에서 worker를 시작해 브랜치가 확정되기 전에
  실행되지 않게 한다.
  `orca orchestration worker-start --worktree path:<worktree path> --agent <host> --task-title "<ticket key>
  <repository>" --spec-file <brief file> --json`을 사용하고, 다른 저장소 작업의 6단계대로 작업 요약을 쓴다.
  `orca orchestration run-list --json`에 목표가 티켓 키, 공백, 티켓 요약 순서인 Run이 있으면 `--run <run id>`를 전달해
  모든 구성원이 참여하게 한다. 같은 문자로 시작하기만 하는 더 긴 키는 다른 티켓이다. 없으면
  `orca orchestration run-create --objective "<ticket key>
  <summary>" --json`으로 Run을 먼저 만들어 나중의 세션이 찾을 수 있게 한다.
- 다른 구성원을 기다리지 않고 자신의 부분을 끝낼 수 있을 때만 구성원을 시작한다. 다른 구성원이 아직 공유하지 않은
  계약, 스키마, API, 결정이 필요하면 worktree와 worker 모두 만들지 않는다. 상태 표에 해당 항목을 기다리는 것으로
  적고, 그 항목이 공유된 뒤에 시작한다. 그런 의존성이 없는 구성원은 함께 시작한다.
  플러그인이 메모리 부족으로 시작을 거부하면 그 구성원을 메모리 대기 상태로 적고, 다른 구성원이 끝나거나 정리된
  뒤에 시작한다. 메모리를 폴링하지 않는다.
- 루트를 포함한 모든 구성원에 Jira 연결이 필요 없는 전체 이슈 링크로 티켓을 연결한다.
  `orca worktree create`에 `--reference <issue link>`를 쓰거나, 이 옵션 없이 만든 worktree에는
  `orca reference add`를 사용한다. 그래도 연결에 실패하면 worktree의 브랜치나 표시 이름에 티켓 키를 남기고 실패를 보고한다.
- 나중에 그룹에 참여하는 세션은 `orca worktree create --repo id:<repoId> --name
  <branch> --base-branch <base> --agent <host> --parent-worktree id:<root id> --reference <issue link> --json`으로
  worktree를 만들고, 다른 저장소 작업과 같은 방식으로 인수인계하며, `orca orchestration run-list --json`의 목표로
  찾은 루트의 Run을 통해 루트에 알린다.
- 조정 세션 하나가 여러 티켓을 맡을 수 있다. 각 티켓의 worktree는 해당 세션의 worktree 아래에 두고 각자의 참조를
  가진다. 그 밖의 경우 다른 티켓은 별도 그룹을 만든다.
- 자신의 부분을 주 체크아웃에서 완료한 저장소는 구성원이 될 수 없다. 그대로 두고 루트의 상태에 명시하며, 사용자가
  요청할 때만 작업을 worktree로 옮긴다.
- 임의로 worktree의 부모를 바꾸지 않는다. 사용자가 요청할 때만 각 구성원에 대해
  `orca worktree set --worktree <member> --parent-worktree <new root>`를 사용해 루트를 옮긴다.
- 부모와 자식은 실행 호스트가 같아야 한다. 다른 호스트의 저장소에는 다른 저장소 작업의 저장소별 배치 규칙을 적용한다.

## 공유

- 구성원은 다른 구성원의 작업이 의존하는 내용을 알게 되는 즉시 공유한다. 계약, 스키마, API 변경, 결정, pull request
  링크, 배포나 병합 순서, 차단 요인이 여기에 해당한다. 일상적인 진행 상황은 공유하지 않는다.
- worker는 `orca orchestration send --to @all --subject <topic> --body <text> --json`으로 다른 구성원에게 보내고,
  `--to` 없이 보내 루트의 Run에도 전달한다. 루트는 `--to dispatch:<id>`로 구성원 하나에게 보낸다. worker가 아닌
  구성원은 `run:<run id>`로 보낸다. 다음 항목의 답을 제외하면 터미널 핸들을 수신자로 지정하지 않는다. 그 사서함은
  터미널이 닫히면 사라진다.
  공유할 변경을 다른 세션의 입력창에 직접 입력하지 않는다. 터미널 전송은 여전히 "다른 세션에 메시지 보내기"를 따른다.
- 계속 진행하려면 다른 구성원의 답이 필요한 구성원은 루트에 묻고 턴을 끝낸다. worker는
  `orca orchestration ask --question <text>`를 실행하고, 루트는
  `orca orchestration reply --id <message id> --body <text>`로 답한다. `ask`는 Dispatch 밖에서 실패하므로 worker가
  아닌 구성원은 `orca orchestration send --to run:<run id> --from $ORCA_TERMINAL_HANDLE --subject "Question: <topic>"
  --body <text> --json`을 보내고 `orca orchestration check --terminal $ORCA_TERMINAL_HANDLE --wait --timeout-ms
  1800000 --json`으로 기다린다. 호스트가 백그라운드 작업 완료를 알려 주면 백그라운드에서 기다린다. 루트는 그 터미널이
  기다리는 동안 `orca orchestration send --to <that member's terminal handle> --subject "Answer: <topic>" --body <text>
  --json`으로 답한다. 루트는 작업이나 사용자 지침에서 답을 도출할 수 있을 때만 답하고, 그렇지 않으면 사용자에게 묻는다.
- Orca가 새 메시지로 구성원을 깨웠으면 다음 단계마다 새 메시지를 읽고, 공유된 변경을 먼저 반영한다.

## 상태

- 루트는 구성원 표를 유지한다. 저장소, worktree, 브랜치, pull request, 검사, 미해결 차단 요인을 담고,
  아직 시작하지 않은 구성원은 무엇을 기다리는지도 적는다.
- `worker_done`, 질문, 공유된 변경 같은 이벤트가 생기면 표를 갱신한다. 오랫동안 소식이 없을 때만
  `orca orchestration worker-read`로 구성원을 읽고, 계속 폴링하지 않는다.
- 구성원의 승인 창이나 사용자에게 한 질문에 대신 답하지 않는다. 사용자에게 보고한다.
- 사용량 한도 등으로 루트가 멈추기 전에 [중단과 재개](pause-and-resume.ko.md)에 따라 재개 메모에 표를 기록해,
  재개한 세션이 이어서 진행할 수 있게 한다.
- 구성원의 보드 상태가 `completed`이면 완료된 것이다. Orca worktree 상태가 사용자 지정 때문에 보드를 변경하지 않는
  경우에는 구성원의 최종 보고가 남은 작업 없이 일을 마쳤다고 하면 완료된 것이다.
- 루트 자신의 보드 상태는 [Orca worktree 상태](orca-worktree-status.ko.md)에 따른 그룹의 요약이다. 모든 구성원이
  완료되고 루트 자신도 남은 작업이 없을 때만 `completed`가 된다.

## 완료된 구성원 정리

구성원이 완료되면 어느 세션이 시작했든 루트가 즉시 정리한다. 루트 자신이 끝날 때도 전체 그룹에서
놓친 완료된 구성원이 있는지 한 번 더 확인한다. 그룹 구성원에게는 이 절차가 다른 저장소 작업의 "인수인계 후"를
대신한다. 그 검사는 그대로 적용한다. 터미널이 열린 질문 없이 유휴 상태이고, worktree에 커밋하지 않은 변경이 없으며,
기준 브랜치에 해당 브랜치의 내용이 들어 있고, 무시된 파일은 다시 만들 수 있는 캐시나 빌드 산출물뿐이어야 한다.
검사에 실패하면 아무것도 삭제하지 않고 사용자에게 한 번 묻는다.

1. 구성원이 백그라운드 셸 작업이나 모니터 같은 자신의 백그라운드 작업을 중단하게 하고, 남은 작업이 없음을 확인한다.
2. `orca ports --worktree id:<worktree id> --json`으로 구성원의 worktree에 연결된 리스너를 찾고, 예를 들어
   `lsof -d cwd -Fpn`으로 작업 디렉터리가 그 안에 있는 프로세스를 찾는다. 구성원의 터미널이나 세션이 시작한 것은
   중단한다. 사용자가 그곳에서 실행한 프로세스처럼 세션이 시작하지 않은 프로세스는 보고하고, 사용자가 승인하지 않으면
   실행 상태로 둔다. 터미널을 닫으면 `nohup` 작업을 포함한 해당 세션의 프로세스는 중단되지만, 데몬이나 컨테이너처럼
   별도 세션으로 분리된 프로세스는 중단되지 않는다.
3. 구성원의 터미널을 닫는다. worker이면 `orca orchestration worker-release --dispatch <id> --json`을 사용하고,
   그렇지 않으면 `orca terminal close --terminal <handle> --json`을 사용한다.
4. `orca worktree rm --worktree id:<worktree id> --delete-branch --json`으로 worktree와 로컬 브랜치를 삭제한다.
   2단계에서 그곳의 프로세스를 실행 상태로 남겼다면 worktree와 브랜치를 유지하고 대신 이를 보고한다. 그 프로세스가
   끝나거나 사용자가 중단을 승인한 뒤에만 삭제한다.

이후 구성원의 터미널, 프로세스, 리스너가 남지 않았는지 확인하고, 닫거나 중단한 항목을 각각 보고한다. 주 체크아웃에서
작업한 구성원은 백그라운드 작업, 프로세스, 터미널만 중단하거나 닫는다. 체크아웃과 기본 브랜치는 절대 건드리지 않는다.

구성원이 남아 있는 동안 루트를 삭제하거나 삭제하자고 제안하지 않는다. Orca는 부모를 즉시 삭제하며, 자식들은 계층을
잃고 최상위 항목이 된다.
