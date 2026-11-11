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
사용자가 정한 것이므로 유지한다.

## 탭 제목

표시 이름과 같은 이벤트에서, 주 클론에서도 세션 자신의 탭 제목을
`orca terminal rename --terminal "$ORCA_TERMINAL_HANDLE" --title "<ticket key> <short summary>" --json`으로
설정한다. 티켓이 없으면 짧은 작업 이름을 쓴다. 주 클론에서는 탭 제목이 작업을 알려 주는 유일한 곳이다. 플러그인 훅이 매
프롬프트마다 세션이 마지막으로 설정한 제목을 보여 준다. 프롬프트가 제목에 없는 작업을 요청하면 시작하기 전에 탭 제목을
바꾸고 worktree 설명을 갱신하며, 사용자가 직접 정했다고 말한 제목은 유지한다.

## 보드 상태와 설명

| 이벤트 | `--workspace-status` | `--comment` |
|---|---|---|
| 세션이 작업을 시작하거나 검토 의견으로 작업을 재개함 | `in-progress` | 현재 단계 |
| 세션이 pull request를 열거나 검토를 요청함 | `in-review` | 기다리는 pull request나 검토 |
| 세션이 결정이나 승인 등 사용자의 응답을 기다림 | 변경하지 않음 | 기다리는 내용과 `--unread` |
| 차단 요인으로 작업이 멈춤 | 변경하지 않음 | 차단 요인 |
| 아래 정의대로 할당된 작업이 전혀 남지 않음 | `completed` | 최종 결과 |

`completed`는 다음이 모두 참이라는 뜻이다. 작업의 pull request가 검토나 병합을 기다리지 않고, 배포, 검증, 답변,
사용자 결정이 남아 있지 않으며, worktree에 커밋하지 않았거나 푸시하지 않은 변경이 없고, 세션이 이 작업을 위해 실행하는
백그라운드 작업이 없다. 병합만으로 작업이 완료되지 않는다. 플러그인 훅은 커밋하지 않았거나 푸시하지 않은 작업이 있는
worktree를 `completed`로 바꾸는 것을 거부한다. 설명은 한 줄로 쓴다.

Claude Code에서는 플러그인 훅이 이 중 세 가지를 직접 쓰므로 거기서는 반복하지 않는다. pull request나 merge request를
만든 직후에는 요청 링크와 함께 `in-review`, 턴이 마지막 줄의 질문으로 끝나면 `--unread`와 대기 라벨 및 질문의 첫 줄로
시작하는 코멘트(사용자의 다음 프롬프트가 이전 코멘트로 되돌린다), 이 worktree 안의 편집이나 커밋으로 `completed`,
`todo`이거나 없는 worktree의 작업이 재개되면 `in-progress`다. 훅이 행을 쓸 수 없는 호스트, 예를 들어 기록을 읽지 못하는
Codex의 질문 행은 표대로 세션이 직접 쓴다. 나머지 행과 훅이 보지 못한 pull request, 예를 들어 브라우저에서 연 것도
직접 쓴다.

플러그인의 Stop 훅이 이름이나 탭 제목 명령을 지정하면 그 명령을 실행하고 답을 반복하지 않은 채 턴을 끝낸다.

Orca는 상태 ID를 검증하지 않고 저장하며 보드 열 목록을 제공하지 않는다. 기본 ID인 `todo`, `in-progress`,
`in-review`, `completed`만 사용한다. 같은 저장소의 worktree가 이미 다른 ID를 사용하면 보드를 사용자 정의한 것이다.
상태는 바꾸지 않고 설명만 최신으로 유지한다.

주 클론에서도 같은 방식으로 상태와 설명을 갱신한다. 마지막으로 갱신한 세션의 값이 적용된다.

티켓 하나의 worktree 그룹에서는 각 세션이 자신의 worktree를 갱신하며, 조정자는
[Orca worktree 그룹](orca-groups.ko.md)의 "상태"도 따른다.
