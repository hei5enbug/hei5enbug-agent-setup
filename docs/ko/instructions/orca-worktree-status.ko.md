# Orca worktree 상태

> 영어 원본: [orca-worktree-status.md](../../../instructions/orca-worktree-status.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

`ORCA_TERMINAL_HANDLE`로 식별되는 Orca 터미널에서 실행 중인 세션은 작업의 첫 파일 변경, pull request, 진행을 막는
질문 전에 이 문서를 읽는다. 세션의 Orca worktree에 현재 하는 일과 남은 작업 여부를 표시해, 터미널을 하나씩 읽지
않아도 사이드바와 보드에서 알 수 있게 한다.

`orca worktree current --json`으로 worktree를 찾고
`orca worktree set --worktree id:<worktree id> <flags> --json`으로 갱신한다. 이 플래그는 Orca 메타데이터만 바꾸며,
파일, Git 상태, 실행 중인 터미널은 바꾸지 않는다. 아래 이벤트가 있을 때만 갱신하고 폴링하지 않는다. 다른 세션의 작업을
위해 만든 worktree는 갱신하지 않는다.

## 이름

작업용으로 만든 worktree에서는 작업을 시작할 때 `--display-name "<ticket key> <short summary>"`를 설정한다.
티켓이 없으면 짧은 작업 이름을 쓴다. 이후에는 작업 범위가 바뀔 때만 이름을 바꾸며, worktree가
`displayNameMode: automatic`을 표시하거나 이 세션이 마지막으로 설정한 이름을 유지하고 있을 때만 바꾼다. 다른 이름은
사용자가 정한 것이므로 유지한다. 여러 세션이 공유하는 저장소의 주 클론, 즉 `isMainWorktree: true`인 항목의 이름은
바꾸지 않는다.

## 보드 상태와 설명

| 이벤트 | `--workspace-status` | `--comment` |
|---|---|---|
| 세션이 작업을 시작하거나 검토 의견으로 작업을 재개함 | `in-progress` | 현재 단계 |
| 세션이 pull request를 열거나 검토를 요청함 | `in-review` | 기다리는 pull request나 검토 |
| 세션이 결정이나 승인 등 사용자의 응답을 기다림 | 변경하지 않음 | 기다리는 내용과 `--unread` |
| 차단 요인으로 작업이 멈춤 | 변경하지 않음 | 차단 요인 |
| 마지막 단계가 무엇이든 세션에 할당된 작업이 전혀 남지 않음 | `completed` | 최종 결과 |

세션에 할당된 배포, 검증, 답변이 남아 있으면 병합만으로 작업이 완료되지 않는다. 설명은 한 줄로 쓴다.

Orca는 상태 ID를 검증하지 않고 저장하며 보드 열 목록을 제공하지 않는다. 기본 ID인 `todo`, `in-progress`,
`in-review`, `completed`만 사용한다. 같은 저장소의 worktree가 이미 다른 ID를 사용하면 보드를 사용자 정의한 것이다.
상태는 바꾸지 않고 설명만 최신으로 유지한다.

주 클론에서도 같은 방식으로 상태와 설명을 갱신한다. 마지막으로 갱신한 세션의 값이 적용된다.

티켓 하나의 worktree 그룹에서는 각 세션이 자신의 worktree를 갱신하며, 루트는
[Orca worktree 그룹](orca-groups.ko.md)의 "상태"도 따른다.
