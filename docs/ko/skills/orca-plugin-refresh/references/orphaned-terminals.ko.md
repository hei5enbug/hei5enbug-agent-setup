# 고아 터미널

> 영어 원본: [orphaned-terminals.md](../../../../../skills/orca-plugin-refresh/references/orphaned-terminals.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

고아 터미널은 Orca 탭이 닫혔는데 에이전트 프로세스가 계속 실행 중인 터미널이다. `orphans`와 `close`는 실행의 마지막에만
실행하고, `close`는 현재 요청에서 사용자가 승인한 터미널에만 실행한다.

## 나열

`python3 <script> orphans --run-id <run_id> --json`을 실행한다. 고아 Claude Code 또는 Codex 터미널을 모두
`host`, `worktree`, `idle_seconds`(transcript 또는 rollout이 마지막으로 기록된 뒤 지난 시간)와 함께 나열한다.
아무것도 닫지 않는다. Claude Code에서는 회색 프롬프트 제안과 입력한 글을 구분하려고 글자 하나를 입력했다가 지울 수 있다.

모든 점검을 통과한 터미널만 `recommended`다. 그렇지 않으면 `failed_check`가 처음 실패한 점검을 알려 준다.

| `failed_check` | 의미 |
|---|---|
| `terminal_unreachable` | 터미널이 연결되지 않았거나 쓸 수 없어 화면을 읽을 수 없다. |
| `turn_busy` | 호스트의 턴 기록이 진행 중인 턴을 보여 준다. |
| `turn_record_unavailable` | 턴 기록이 없거나 판단하지 못해 한가함을 확인할 수 없다. |
| `background_task_pending` | 백그라운드 작업, 하위 에이전트, 예약된 깨우기가 아직 알림을 남기고 있다. |
| `activity_unknown` | transcript의 마지막 기록 시각을 읽을 수 없다. |
| `recently_active` | transcript가 24시간 안에 기록됐다. |
| `input_not_empty` | 입력 줄에 입력한 글이 있다. |
| `input_unknown` | 입력 줄을 읽을 수 없다. |

목록을 보여 주고 어느 추천 터미널을 닫을지 사용자에게 한 번 묻는다. 닫기는 추천된 터미널만 제안한다.

## 닫기

`python3 <script> close --run-id <run_id> --terminal <handle> --json`을 실행하며, 승인된 터미널마다 `--terminal`을
반복한다. 핸들은 보고서의 `…` 접미사가 아니라 목록의 `handle` 전체다. 스크립트는 터미널을 하나씩 닫기 직전에 그 터미널이 여전히
고아이고, 에이전트 세션이며, 위의 모든 점검을 다시 통과하는지 확인한 뒤 `orca terminal close`를 실행한다.
transcript, 표식, 작업 트리는 지우지 않는다.

## 터미널별 보고

- `closed`: Orca가 터미널을 닫았고 `orca terminal list`에 더 이상 나타나지 않는다.
- `skipped`: 터미널이 열려 있다. `detail`은 위의 실패한 점검, `not_orphaned`(고아가 아니므로 닫지 않음),
  `terminal_not_found`, `not_an_agent_session` 중 하나다. 사용자에게 알리고 나중에 다시 고르게 한다.
- `failed`: 닫기를 요청했지만 터미널이 목록에 그대로 있거나(`close_unconfirmed`) Orca가 오류를 돌려줬다. 해당 터미널을
  확인하라고 알리며, 스크립트는 다시 시도하지 않는다.
