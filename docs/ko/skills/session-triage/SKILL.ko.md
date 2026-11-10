# 세션 정리

> 영어 원본: [SKILL.md](../../../../skills/session-triage/SKILL.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

Orca에서 실행 중인 모든 Claude Code와 Codex 에이전트 세션을 상태(사용자 대기, 멈춤, 완료, 작업 중)별 표로 보여 주고,
한 번의 승인을 받아 조치한다. 멈춘 세션에는 지시를 보내고, 유휴 세션은 재개 메모를 남기고 종료해 메모리를 확보하며,
완료된 세션의 변경 사항이 없는 worktree를 제거하거나, 탭 이름을 현재 작업으로 바꾼다. 사용자가 Orca에서 실행 중인
에이전트 세션을 보거나 분류하거나 정리해 달라고 할 때, 자기를 기다리거나 멈춘 세션을 찾아 달라고 할 때, 그 세션이
쓰는 메모리를 확보해 달라고 할 때 사용한다. 예를 들면 "세션 정리해줘", "대기 중인 세션 보여줘", "free memory used by
my agent sessions" 같은 요청이다. 플러그인이 메모리 부족으로 시작을 거부하면서 이 스킬을 제안한 뒤 사용자가 동의한
경우에도 사용한다. 플러그인 업데이트와 세션 다시 불러오기(`orca-plugin-refresh`), 디스크 정리(`local-data-cleanup`),
worktree 생성에는 사용하지 않는다.

Python 3.12 이상과 실행 중인 Orca에 접근할 수 있는 `orca` CLI가 필요하다. `ORCA_CLI_COMMAND`로 실행 파일을
바꿀 수 있다. `git`은 정리 검사에만 필요하다.

이 영어 `SKILL.md`만 실행 원본으로 사용한다.

사용자에게 Orca의 모든 에이전트 세션을 간결하게 한눈에 보여 주고, 한 번의 승인으로 모두 조치할 수 있게 한다.
사용자 결정이 필요 없는 읽기, 분류, 초안 작성, 검증은 모두 직접 한다. 한 번 묻고 실행한다.

## 경계

- 현재 세션(`is_current`)에는 worktree 코멘트나 읽지 않음 표시까지 포함해 절대 조치하지 않고, 다른 세션의
  프롬프트에 사용자 대신 답하지 않는다.
- 프로세스를 강제 종료하지 않는다. 세션은 유휴 프롬프트에 해당 세션의 종료 명령을 입력해서만 끝내고, 터미널은
  그 에이전트가 종료되고 그 worktree에서 다른 것이 실행되지 않을 때만 닫는다.
- 현황판 상태를 바꾸지 않는다. `sleep`에 필요한 코멘트, `retitle`이 설정하는 탭 제목, `restore name`이 지우는 고정된 표시 이름만 쓴다.
- 한 번의 승인은 질문에 나열한 조치만 허용한다. 침묵은 승인이 아니다. 목록 밖의 조치는 새로 물어야 한다.
- 검사가 실패하거나 결과를 읽을 수 없으면 해당 세션을 건너뛰고 이유를 밝힌다. 우회하려고 재시도하지 않는다.

## 작업 순서

### 1. 한 번 읽기

```text
python3 scripts/session_overview.py
```

이 `SKILL.md`가 있는 디렉터리를 기준으로 한 상대 경로로, 실행할 때마다 한 번만 실행한다. 읽기 전용이며
`host_total_mb`, `host_available_mb`, `sessions[]`, `worktrees_without_agent[]`, `renamed_main_worktrees[]`,
`warnings[]`를 담은 JSON 객체 하나를 출력한다. `worktrees_without_agent[]`는 에이전트 세션이 실행되지 않는 모든 주 worktree가 아닌
worktree를 터미널이 있든 없든 담고(`terminal_handles`가 비어 있을 수 있다), 주 worktree는 라이브 터미널이 있는 동안만
담는다. 종료 코드 2는 Orca에 접근할 수 없거나 필수 조회가 실패했다는 뜻이다. 한 줄짜리 이유를
보고하고 멈춘다. 행에 영향을 주는 경고를 모두 보여 준다. 메모리나 터미널 핸들이 `null`이면 그 값을 모른다는 뜻이며,
절대 0이 아니다.

### 2. 분류

각 세션의 `last_assistant_message`, `state`, `board_status`, `comment`, `prompt`, `minutes_in_state`로
판단한다. 마지막 메시지의 끝에는 그 세션이 요청하는 내용이 있다.

| 분류 | 의미 |
|---|---|
| `needs you` | 사용자에게 질문, 결정, 승인을 요청한다. |
| `working` | `state`가 `working`이다. |
| `stalled` | 턴이 끝났지만 작업은 끝나지 않았고, 사용자에게 요청한 것도 없다. |
| `finished` | 작업을 마쳤고 남은 것이 없다. |
| current | `is_current`다. 보여 주되 절대 조치하지 않는다. |

`done`인 세션도 명확하게 끝났다는 내용이 없으면 `finished`가 아니라 `stalled`다. 메시지만으로 판단할 수 없으면
추측하지 말고 해당 행에 그렇게 적는다.

### 3. 세션마다 조치 하나 권고

| 조치 | 사용 조건 |
|---|---|
| `answer` | `needs you`다. 사용자만 답한다. 질문을 한 줄로 보여 준다. |
| `continue` | `stalled`다. 지시 하나를 보낸다. 그 세션 자신의 마지막 메시지에서 다음 단계가 도출될 때만 지시를 작성하고, 아니면 사용자에게 지시를 묻는다. |
| `sleep` | 검토, 일정, 사용자처럼 오래 걸리는 무언가를 기다리며, 호스트 메모리가 부족하거나 오래 기다렸다. 에이전트 CLI를 종료하고 터미널은 유지한다. 종료하면 작업을 잃을 세션에는 사용하지 않는다. 세션 밖에서 이를 실행할 프로세스나 스케줄러를 찾은 경우가 아니면, 화면에 감시 작업, 백그라운드 작업이나 터미널, 실행 중인 서브에이전트가 보이거나 마지막 메시지에서 나중에 스스로 계속하겠다고 한 세션에는 사용하지 않는다. |
| `clean up` | `finished`이고, 주 worktree가 아니며 자식이 없는 worktree다(`is_main_worktree`가 false, `child_count`가 0). 주 worktree가 아니고 `child_count`가 0이며 작업이 원격에 있는 `worktrees_without_agent` 행도 해당하며, 원격 여부는 아래 검사로 판단한다. |
| `retitle` | 사용자가 탭 이름을 붙여 달라고 했거나, 행의 작업이 `display_name`, `comment`, `prompt`로 분명한데 탭에는 경로 조각, 브랜치, 프로그램 이름만 보인다. 세션이 하는 일을 보고 판단해 탭 이름을 `<ticket key> <short summary>`나 짧은 작업 이름으로 바꾼다. Orca는 탭 제목을 보고하지 않으므로 사용자가 직접 입력한 제목과 기본값을 구별할 수 없다. 제안하는 제목을 보여 주면서 개별 선택 항목으로만 제안하고 미리 선택하지 않는다. |
| `keep` | 모든 `working` 세션과 현재 세션을 포함한 나머지 전부다. |

`host_available_mb`가 다른 에이전트 세션을 시작하는 플러그인의 기본 기준값인 2048 MB보다 작으면 호스트 메모리가
부족하다고 본다. 값을 모르면 그렇게 밝히고 부족하다고 하지 않는다. 터미널 핸들을 모르는 세션에는 `answer`나
`keep`만 권고할 수 있다.

### 4. 표 하나를 보여 주고 한 번 묻기

사용자의 언어로 `needs you`를 먼저 정렬한 표 하나를 보여 준다. 세션, 저장소 또는 표시 이름, 분류, 기다리는 대상이나
마지막으로 한 일을 한 줄로, 현재 상태 경과 시간(분), 메모리, 권고 조치(`retitle`이면 제안하는 제목)를 적는다. 호스트의 전체 메모리와 사용 가능한
메모리, 터미널 메모리를 알 수 없는 `worktrees_without_agent` 행(각 행에 질문 전에 실행한 `clean up` 또는 `keep`과
실패한 검사), 경고도 덧붙인다. 표 아래에는 `renamed_main_worktrees` 행마다 표시 이름, 경로, 모드를 보여 주고
권고 조치 `restore name`을 적는다. 주 클론은 그 안의 모든 세션이 공유하므로 고정된 이름은 그 세션 모두에게 오해를
준다.

그다음 제안하는 조치를 나열한 질문 하나를 한다. `sleep`, `continue`(보낼 정확한 지시 포함), `clean up`을
호스트 질문 도구가 허용하는 방식에 따라 미리 선택하거나 개별 선택할 수 있게 하고, `retitle`과 `restore name` 항목은
개별 선택만 가능하게 하며 미리 선택하지 않는다. 답을 기다리고 그전에 아무것도
실행하지 않는다. 조치할 것이 없으면 그렇다고 말하고 묻지 않는다.

### 5. 승인된 조치 실행

무언가를 보내기 전에 `orca terminal read --terminal <handle> --screen`을 실행한다. 승인 프롬프트나 질문이
열려 있지 않고 입력줄이 비어 있을 때만 보낸다. 입력줄의 텍스트는 호스트의 회색 제안일 수 있다.
`--enter` 없이 `--text x`를 보내고, 입력줄에 `x`만 보이면 `--text $'\x7f'`로 지운 뒤 계속한다.
그렇지 않으면 `x`를 지우고 해당 세션을 건너뛴 뒤 사용자 입력이 있다고 말한다. 종료 명령 직전에 화면을 다시 확인한다.

- `continue`: `orca terminal send --terminal <handle> --text "<instruction>" --enter --json`.
- `sleep`: 해당 `agent_type`의 종료 명령을 보내고, 화면에 셸 프롬프트가 보일 때까지 기다린 뒤 출력된 재개 명령을
  읽는다. 예를 들면 `claude --resume <id>`나 `codex resume <id>`다. 그다음 다음 명령을 실행하고 현황판 상태는
  그대로 둔다.
  `orca worktree set --worktree "id:<worktree_id>" --comment
  "<one-line sleep note with the resume command> · <previous comment>" --json`.
  재개 명령이 보이지 않으면 그렇게 밝히고 코멘트에 세션의 `conversation_name`을 남긴다.
- `retitle`: `orca terminal rename --terminal <handle> --title "<title>" --json`. 터미널에 아무것도 입력하지 않으므로
  화면 확인이 필요 없다.
- `restore name`: `orca worktree set --worktree "id:<worktree_id>" --display-name "" --json`. 빈 이름은 고정된
  이름을 지워 Orca가 다시 자동 이름을 보여 주게 한다. 그다음 `orca worktree list --json`으로 그 worktree를 다시 읽고,
  해당 항목이 `displayNameMode: automatic`을 보일 때만 복원됐다고 보고한다. 아니면 항목이 보이는 모드를 보고한다.
  그 질문에서 사용자가 승인하지 않았다면 절대 실행하지 않는다.
- `clean up`: 먼저 다음 조건을 모두 확인한다. 하나라도 실패하면 실행하는 대신 사용자에게 묻는다.
  - worktree가 메인 worktree가 아니고, 하위 worktree가 없고, 현재 세션의 worktree가 아니다.
  - `orca terminal list --worktree "id:<worktree_id>" --json`에 이 세션의 터미널만 있고, 개요의 다른 행에 같은
    `worktree_id`가 없어서 그 체크아웃을 쓰는 다른 세션이나 셸이 없다.
  - 화면에 유휴 프롬프트가 보이고, 열린 질문이 없고, 감시 작업, 백그라운드 작업, 실행 중인 서브에이전트가 없다.
  - `git -C <path> status --porcelain`이 비어 있고, 무시된 파일은 다시 만들 수 있는 캐시뿐이다.
  - 브랜치의 커밋이 기준 브랜치에 있다(`git -C <path> merge-base --is-ancestor HEAD <base ref>`; squash 병합은
    통과하지 못하므로 묻는다).

  그다음 `sleep`처럼 에이전트를 종료하고 셸 프롬프트를 확인한다. 그곳에서 아직 실행 중인 것을 찾는다.
  `orca ports --worktree "id:<worktree_id>" --json`과, 터미널 자체의 셸을 제외하고 작업 디렉터리가 그 경로 안에
  있는 프로세스(예: `lsof -d cwd -Fpn`로 확인)를 본다. 남은 것이 있으면 터미널과 worktree를 그대로 두고 보고한다.
  없으면 `orca terminal close --terminal <handle> --json`과
  `orca worktree rm --worktree "id:<worktree_id>" --delete-branch --json`을 실행한다. `finished`가 아닌 세션에는
  절대 실행하지 않는다.

  `worktrees_without_agent` 행에는 에이전트 세션이 없으므로 종료 명령을 보내지 않고 `finished` 분류도 필요 없다.
  같은 검사를 하되 다음이 다르다. `terminal_handles`의 모든 터미널이 아무것도 실행하지 않는 유휴 셸 프롬프트를
  보이고, 개요의 다른 행에 같은 `worktree_id`가 없다. `terminal_handles`가 비어 있으면 터미널 검사와 닫기 단계를
  건너뛰고 나머지 검사는 모두 유지한다. `git -C <path> fetch` 뒤
  `git -C <path> rev-list --count @{upstream}..HEAD`가 0이면 기준 브랜치 검사 대신 이 조건으로 통과한다. 업스트림이
  없는 브랜치는 통과하지 못한다. 인수인계 메모처럼 다시 만들 수 없는 무시된 파일은 먼저 현재 세션의 worktree로 복사한
  뒤 계속한다. 그다음 위와 같이 실행 중인 프로세스를 찾고, `terminal_handles`의 각 터미널을 `orca terminal close`로
  닫고, 같은 `orca worktree rm`을 실행하고, 작업을 보관하는 원격 브랜치를 보고한다. 검사에 실패한 행은 그대로 두고,
  그 행에 실패한 검사를 명시한다.

종료 명령:

| 에이전트 | 명령 |
|---|---|
| Claude Code | `/exit` (별칭 `/quit`) |
| Codex | `/quit` (`/exit`도 같음) |

### 6. 보고

조치마다 결과를 보고한다. 호스트의 사용 가능한 메모리를 전후로 보고하되, 이후 값은
`orca diagnostics memory --json`만 다시 실행해 구한다. 사용자만 처리할 수 있는 남은 항목도 나열한다.

나중에 요청을 받아 잠재운 세션을 깨울 때는 그 터미널의 화면을 읽고, 빈 셸 프롬프트가 보일 때만 기록해 둔
재개 명령을 보낸다.
