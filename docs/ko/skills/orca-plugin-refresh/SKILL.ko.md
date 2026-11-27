# Orca 플러그인 새로고침

> 영어 원본: [SKILL.md](../../../../skills/orca-plugin-refresh/SKILL.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

---
name: orca-plugin-refresh
description: >-
  Claude Code와 Codex에서 hei5enbug-agent-setup과 사용자가 지정한 플러그인을 업데이트한 뒤, 설치된 버전을
  실행 중인 Orca 에이전트 세션에 적용한다. 유휴 세션은 reload하거나 compact하고, 바쁜 Claude Code 세션에는
  명령을 대기열에 넣고 작업을 방해할 수 있는 경우 사용자에게 묻는다. 오래된 Claude Code 릴리스나 교체된
  Codex 플러그인 폴더를 쓰는 세션은 재개하고, Codex 업데이트를 막는 바쁜 Codex 세션은 사용자에게 묻는다.
  스킬 이름이 없어도 실행 중인 Orca 세션을 더 새로운 Claude Code 릴리스로 새로고침하거나
  재시작해 달라는 요청, 또는 설치된 업데이트를 세션에 적용해 달라는 요청에 사용한다. 설치가 이미 끝났으면
  apply-installed를 사용한다. 작업 트리 생성, 터미널 읽기, Orca 브라우저 작업에는 사용하지 않는다.
compatibility: >-
  macOS 또는 Linux, Python 3.12 이상, hei5enbug 마켓플레이스의 사용자 범위
  hei5enbug-agent-setup 플러그인이 필요하다. 설치 버전을 확인하고 설치본을 업데이트하려면 claude와 codex
  CLI가 필요하다. 세션 적용에는 Orca 터미널과 Orca CLI가 필요하다.
---

이 영어 `SKILL.md`만 실행 가능한 원본으로 사용한다.

이 스킬은 `hei5enbug-agent-setup`과 사용자가 고른 다른 플러그인을 업데이트한 뒤, 설치된 버전을 실행 중인
Orca 세션에 세션을 끝내지 않고 적용한다. 세션을 재시작하거나 대화를 교체하지 않는다. 다만 `apply`는 모든
재개 확인을 통과한 오래된 릴리스의 Claude Code 세션이나 플러그인 폴더가 교체된 유휴 Codex 세션을 먼저 묻지 않고 재개한다(3단계). 확인에 막힌 세션은 사용자가 승인할 수 있다(6단계).

## 업데이트가 실행 중인 세션에 반영되는 방법

| 구분 | Claude Code | Codex |
|---|---|---|
| 스킬, 에이전트, 훅 | `/reload-plugins`가 모든 플러그인을 다시 불러온다 | 플러그인 폴더가 교체된 세션은 재개한다 |
| 세션 지침 | `/compact` | `/compact`; 다음 턴에서 지침을 불러온다 |

플러그인의 세션 시작 훅은 Orca 터미널마다 호스트, 플러그인 디렉터리, 대화 기록 경로, 실행 지침의 digest가
담긴 표식을 기록한다. 해당 터미널의 대화형 세션만 표식을 쓴다. 그 터미널에서 시작한 자식 프로세스
`claude -p`나 `codex exec`은 표식을 쓰지 않는다. Orca의 터미널 기록에 에이전트가 없으면, 스크립트는 그 호스트의
입력 줄이 화면 맨 아래에 있을 때만 그 터미널을 표식의 호스트로 본다. 그래서 오래된 표식이 남은 셸은 대상이 되지 않는다.
표식이 없거나 digest가 다르거나, Codex 세션의 플러그인
디렉터리가 교체됐거나, Claude Code 세션이 삭제된 디렉터리를 가리킬 때만 스크립트가 세션을 compact한다. 이
판단은 이 플러그인의 지침 digest만 따르고 다른 플러그인은 보지 않는다. 교체 전에 시작한 Codex 프로세스는
compact 대신 재개 규칙을 따른다. Claude Code가 대화가 너무 짧아
compact할 수 없다고 답하고 대화 기록에 프롬프트가 없으면 스크립트가 `/clear`를 보낸다. 비어 있는 세션에는
잃을 내용이 없기 때문이다. 한 번도 턴을 진행하지 않은 Codex 세션은 첫 턴에서 새 지침을 불러오므로 따로
처리하지 않는다.

## 작업 흐름

`<script>`는 이 `SKILL.md`가 있는 디렉터리의 `scripts/orca_plugin_refresh.py`다.

Codex 플러그인을 업데이트하거나 훅 신뢰 경고를 보고하기 전에 `references/codex-releases.md`를 읽는다.
스크립트가 `questions`에 반환한 질문을 묻거나 `decide`를 실행하기 전에 `references/busy-sessions.md`를 읽는다.

1. **설치 경로를 고른다.** 새 버전을 설치하려면 `python3 <script> refresh --json`을 한 번 실행한다. 이 명령은
   업데이트를 하고, 반환된 run id로 3단계의 `apply`와 7단계의 `orphans`를 이어 실행해 `update`, `apply`, `orphans` 절이 있는
   JSON 객체 하나를 출력한다. 다른 플러그인도 함께 새로고침하려면 사용자가 말한 ID마다 `--also <plugin@marketplace>`를 전달한다. 이 플래그는 여러 번
   쓸 수 있고 `--installed`와 함께도 쓸 수 있다. `--also`가 없으면 스크립트는 `HEI5ENBUG_REFRESH_PLUGINS`
   환경 변수(쉼표로 구분한 ID)를 쓰고, 그것도 없으면 저장된 `refresh_plugins` 플러그인 옵션을 쓴다. 비어
   있지 않은 첫 출처가 이긴다. ID를 지어내지 않는다. 잘못된 ID는 위치와 함께 `plugin_id_invalid`를 반환하고
   아무것도 실행하지 않는다. 사용자에게 고친 ID를 물어본다. 스크립트는 중복과 이 플러그인 자신의 ID를 빼고
   함께 새로고침할 플러그인을 최대 10개까지 남기며, 초과한 플러그인은 `companions_dropped`로 알린다. 설치를 이 스킬
   밖에서 이미 마쳤거나 사용자가 설치된 버전을 적용해 달라고 하면 `python3 <script> refresh --installed --json`을
   실행한다. 이 명령은 설치 경로를 읽고 플러그인 마켓플레이스나 설치 명령을 실행하지 않는다. 두 명령은 먼저
   `claude update`를 한 번 실행해 세션이 가장 새로운 Claude Code 릴리스와 비교되게 한다. 다만 `DISABLE_UPDATES`가
   업데이트를 끄거나 `claude`가 `PATH`에 없으면 실행하지 않는다. 셸 제한 시간은 600초 이상으로 한다.
2. **업데이트 결과를 처리한다.** `update` 절에서 각 호스트의 버전 변화를 보고한 뒤 `hosts.<host>.plugins`의 모든 플러그인을
   상태, 버전, 경고와 함께 보고한다.
   - `updated` 또는 `current`: 버전이 바뀌었거나 그대로이며 설치본이 검증됐다.
   - `not_installed`: 해당 호스트에 설치되어 정확히 한 번 활성화된 상태가 아니며 아무것도 실행하지 않았다.
   - `local_source`: 플러그인이 로컬 폴더에서 로드되므로 스크립트는 설치하지 않으며, 커밋하지 않은 코드가
     배포되는 일은 없다. Claude Code는 `/reload-plugins`로 그 폴더를 다시 불러온다.
   - `deferred`: 호스트의 설치 게이트가 막았다. 아래 Codex 게이트를 본다.
   - `error`: `code`와 `message`를 알린다. 이 플러그인이나 세션 적용을 막지 않는다.

   `hosts.claude.claude_code`도 보고한다. `status`(`updated`, `current`, `skipped`, `failed`), 전후 릴리스
   `before`와 `after`, 건너뛴 경우의 `reason`, 실패한 경우의 `exit_status`와 `detail` 및 `claude_update_failed`
   경고를 알리며, 이 경고는 플러그인 결과나 `apply`를 막지 않는다.

   이 플러그인 자체가 호스트에서 로컬 소스로 로드되면 그 호스트는 `local_source: true`로 보고하고, 설치 명령을
   실행하지 않으며, `apply`에는 계속 쓸 수 있다. 이 플러그인의 호스트에 `error`가 있으면 코드와 메시지를 알린다.
   해당 호스트의 세션은 건드리지 않는다.
   Claude Code는 업데이트가 옛 버전 옆에 새 버전을 추가하고 실행 중인 세션이 `/reload-plugins` 전까지 불러온
   디렉터리를 유지하므로 언제든 설치한다. Codex 업데이트는 옛 설치본을 삭제하므로, 호출자가 Codex 턴 안에
   있으면 `update_deferred_active_session`, 최근 30분 안의 Codex 세션이 턴을 끝내지 않았으면
   `codex_turn_in_progress`, Codex 세션을 읽을 수 없으면 `update_deferred_unknown_session_state`로
   보류한다. 보류된 Codex 호스트는 `root`와 함께 보고한다. 처음 두 코드는 `questions`에 바쁜 세션마다
   `codex_install` 질문이 하나씩 있다. 3단계처럼 질문한 뒤 `decide`를 실행하면 턴이 끝난 뒤 재실행 없이 설치한다.
   세 번째 코드는 `recovery_command`를 알려 주고 `update`를 다시 실행하라고 알린다. 스스로 다시 시도하지 않는다. 게이트는 Codex 설치 직전마다 다시 확인하므로 실행 도중 시작된 턴은 그 플러그인과 이후의 모든 Codex 설치를
   보류하고, 막힌 플러그인은 `deferred`가 되며 Claude Code는 영향받지 않는다. 이후 명령은 반환된 `script` 경로로 실행한다. Codex
   업데이트가 이 스킬을 불러온 설치 디렉터리를 삭제할 수 있기 때문이다. 모든 경고를 보고한다.
   - `unreleased_same_version`: 버전이 바뀌지 않아 Claude Code가 설치본을 유지한다. 이 파일이 Claude Code에
     반영되려면 버전을 올려야 한다고 알린다.
   - `unreleased_check_unavailable`: Claude Code가 같은 버전의 파일을 놓쳤는지 확인할 수 없다. 이유를 알린다.
   - `claude_home_project_record`: 홈 폴더에서 세션이 실행되어 Claude Code가 사용자 설치를 같은 사본의 홈 폴더 프로젝트
     설치로 한 번 더 나열했다. 스크립트가 둘을 한 설치로 보았으므로 할 일은 없다.
3. **세션에 적용한다.** 이 플러그인의 호스트 업데이트가 성공했거나 설치본만 적용한 실행이 그 호스트를 오류 없이
   반환하면 `refresh`가 1단계의 셸 제한 시간 안에서 포그라운드로 `apply`를 직접 실행하고, 결과는 `apply` 절에 담긴다.
   모든 호스트에 오류가 있으면 출력에는 `update`만 있다. 이 단계는 사용자에게 확인을 묻지 않는다. 어떤 세션에 명령을 보낼지는 스크립트의 확인이 정한다.
   스크립트는 약 20초 동안 입력 줄이 비어 있거나 입력한 글을 지운 유휴 세션에 명령을 보내거나, 바쁜 Claude Code
   세션에 명령을 대기열로 입력한다. 이미 보낸 명령의 결과를 계속 확인하며 정확히 되돌릴 수 있는 글은 되돌린다.
   아직 바쁘거나 준비되지 않은 세션은 기다리지 않고 분리된 도우미 하나에 `deferred`로 넘긴다. 출력에 `questions`가
   있으면 스크립트가 반환하자마자 다른 보고보다 먼저 질문 도구로 각각 묻고 `decide`를 실행한다.
   `already_running` 오류는 다른 실행이 지금 명령을 보내고 있다는 뜻이다. 끝날 때까지 기다린 뒤 `apply`를
   다시 실행한다. 업데이트에 실패한 호스트는 계속 차단하고, 성공한 호스트는 진행할 수 있다.
   `apply`는 무엇이든 보내기 전에 `host_release_outdated`를 보고하는 다른 Claude Code 세션과 플러그인 폴더가
   교체된 다른 Codex 세션 중 모든 재개 확인을 통과한 세션을 각각 재개한다. 바쁜 Codex 세션은 턴이 끝난 뒤 도우미가 재개한다. 재개한 세션에는 `/reload-plugins`를 보내지 않고, 이후 `/compact`는 지침이 오래됐을 때만
   보낸다. `apply`가 재개했거나 재개를 시도한 세션을 보고하기 전에 `references/resume.md`를 읽는다.
4. **모든 세션 결과를 보고한다.** 터미널 접미사, 호스트, 작업 트리, 상태, 완료한 작업, 세부 내용을 표시한다.
   - `done`: 필요한 작업이 모두 확인됐다. `already_current`는 할 일이 없었다는 뜻이다.
     `fresh_session_loads_on_first_turn`은 턴을 진행하지 않은 Codex 세션을 나타낸다.
     `empty_session_cleared`는 비어 있는 Claude Code 세션에 `/clear`를 보냈다는 뜻이다.
     `instructions_load_on_next_turn`은 compact된 Codex 세션이 다음 턴에 지침을 불러온다는 뜻이다.
     `applied_by_session`은 세션이 넘긴 뒤 `/reload-plugins`를 스스로 실행했다는 뜻이다.
     `instructions_on_next_compaction`은 프롬프트가 있는 Claude Code 세션이 reload 확인 뒤 `/compact`를 너무 짧다는 이유로
     거부당했다는 뜻이며, 지침은 다음 compact 또는 재시작 때 갱신된다.
   - `skipped`: 세션이 계속 바빴거나, 입력 줄을 읽을 수 없거나, 보내기 직전에 입력이 바뀌었거나, 제한 시간에
     도달했거나, 세션이 닫혔다. `terminal_orphaned`는 고아 터미널(Orca 탭이 닫힌 터미널)이 연결되지 않았거나 쓸 수 없다는
     뜻이며, 새로고침한 고아 세션은 `orphaned`를 보고한다. `input_clear_failed`는 입력 줄을 지우지 못해 아무것도 보내지 않았거나
     (`input`이 `clear_failed`), 스크립트가 글을 다시 입력했다는 뜻이다. `orchestration_mail_pending`은 Orca가
     그 세션 앞으로 읽지 않은 오케스트레이션 메일을 아직 갖고 있었거나 그 여부를 알 수 없어서, 아무것도 입력하거나 보내지
     않았다는 뜻이다. `queued_unconfirmed`는 대기열의 명령이 한 시간 안에 확인되지 않았으며 여전히 실행될 수 있다는 뜻이다.
   - 모든 세션은 `ready_signal`(전송을 허용한 신호인 `host_record` 또는 `tui_idle`)도 보고하고, 입력을 붙들었다면
     `input`(`restored`, 정확히 되돌릴 수 없는 입력이면 `cleared`)도 보고한다.
     Claude Code 세션은 `release`도 보고하며, 설치된 릴리스보다 오래된 릴리스로 실행 중이거나 실행 파일이 없어졌으면 두 버전과
     함께 `host_release_outdated`를 보고한다.
   - `failed`: 보낸 작업이 확인되지 않았거나 Claude Code가 거부했다. `plugin_load_error`는 reload 답이
     `N error(s) during load`를 알렸거나 활성화된 플러그인보다 적게 불러왔다는 뜻이며, `plugin_load`에 보고된 개수가
     있다. `--force`를 요청하는 reload 거부는
     플러그인의 MCP 도구가 바뀌었다는 뜻이다. 사용자 승인 없이 강제로 진행하지 않는다.
     `compact_dialog_open`은 `/compact`가 "acts on the main conversation, not this
     agent" 대화상자가 아닌 다른 대화상자를 열었다는 뜻이며, 스크립트는 키를 보내지 않고 그대로 둔다. 그 대화상자는
     선택을 `Run /compact on the main conversation`으로 옮겨 답하며 `Cancel`은 절대 확인하지 않는다. `probe_interrupted_check_input`은 스크립트가 입력 줄을 확인하는 동안 입력 줄이 바뀌고
     원래 상태로 돌아오지 않았거나, 그런 확인 중단이 계속됐다는 뜻이다. 스크립트는 직접 입력하지 않은 내용을 지우지 않으므로, 해당 세션 입력 줄에 불필요한 `x`가 있는지
     확인하라고 알린다. `probe_character_left`도 같은 뜻이며, 남은 `x`는 줄의 `probe_position`(1부터 시작) 위치에 있다.
     `input_restore_unconfirmed`는 저장한 글이 입력 줄에 다시 있는지 확인되지 않았다는 뜻이고,
     `input_not_restored_line_in_use`는 사용자가 새 글을 입력해 저장한 글을 다시 입력하지 않았으며 그 글은 사라졌다는
     뜻이다. 해당 세션의 입력 줄을 확인하라고 알린다. `helper_start_failed`는 이 세션의 후속 작업을 시작하지
     못했다는 뜻이다. `apply`를 다시 실행한다.
   - `blocked`: 해당 호스트의 플러그인 업데이트가 실패했거나 설치 manifest, 훅 대상, 지침 digest가 검증되지
     않았다.
   - `deferred`: 세션이 바쁘거나 준비되지 않아 분리된 도우미가 마무리한다. 5단계를 따른다. `commands_queued`는 명령을 입력했고 턴을 기다린다는 뜻이다.
   - `awaiting_answer`: 아무것도 입력하지 않았고 세션이 사용자 답변을 기다린다.
   - `queued_after_turn`: 이 스킬이 실행 중인 세션이다. 5단계를 따른다.
5. **도우미가 마무리하게 한다.** `apply`가 `deferred`나 `queued_after_turn`을 보고하면 첫 결과를 알리고 턴을
   끝낸다. 분리된 도우미 하나가 넘겨받은 모든 세션과 이 세션을 지켜본다. 각 세션 자신의 턴 기록이 먼저
   판단하고, Orca의 한가함 콜백(`orca terminal wait --for tui-idle`)은 그 기록이 판단하지 못할 때만 판단한다.
   세션이 한가해졌다고 알려 오면 도우미는 3초 뒤 다시 확인하고, 설치된 플러그인이 이번 실행과 그대로인지와 세션이 이미 새 지침을 불러왔는지 확인한 뒤에만 남은
   작업을 보낸다. 백그라운드 작업, 서브에이전트, 깨우기가 알림을 남겨야 하는 동안에는 `/reload-plugins`만 보내고
   `/compact`나 `/clear`는 남은 알림 없이 끝나는 턴을 기다린다. 입력 줄을 읽을 수 없는 경우처럼 다른 이유로 미뤄진 세션은 확인할 때마다 다시 살핀다. 넘긴 뒤
   Claude Code 세션의 reload는 넘긴 뒤 대화 기록에 성공한 reload가 있거나, 넘긴 뒤 표식이 source `startup`이나 `resume`으로
   다시 쓰일 때까지 남는다. compact나 clear가 다시 쓴 표식은 어떤 폴더를 가리켜도 reload를 끝내지 못한다. 설치된 모든
   플러그인을 읽는 것은 새 프로세스뿐이기 때문이다. 한 시간 안에 준비되지 않은 세션에는 보내지 않고 `not_idle_before_deadline`이나 마지막 이유로 남긴다.
   터미널이 닫힌 세션은 곧바로 `terminal_gone`으로 건너뛰고 그 대기를 끝낸다. 상태에는 세션마다 최종 결과가
   정해지는 즉시 기록되므로, 도우미가 도는 동안에도 `status`로 진행 상황을 볼 수 있다.
   상태의 `others_finished_at`이 설정돼 있고 이 세션만 아직 `queued_after_turn`이면 다른 모든 세션은 최종 상태이므로
   기다리지 말고 보고한다. 이 세션의 작업은 턴이 끝난 뒤 실행되며, 사용자가 이 세션에서 `/reload-plugins`(나열돼
   있으면 `/compact`도)를 실행하면 완료로 센다.
   모든 세션이 끝나면 도우미는 `python3 <script> status --run-id <run_id> --json`을 실행하라는 프롬프트를 이
   세션에 한 번 보내고, 자신이 시작한 Orca 대기를 모두 끝낸 뒤 종료한다. 그 프롬프트가 오면 명령을 실행하고
   `hosts`의 플러그인 상태와 함께 모든 세션을 보고한다. `not_refreshed`는 업데이트를 받지 못한 세션 목록이다.
   상태의 `self_notification`이 `sent`가 아니면 프롬프트를 전달하지 못한 것이다. 그래도 상태에 작업 결과가
   남아 있다.
6. **재개를 제안한다.** `resume_approval_needed`를 보고한 세션(`plugin_load_error`, 또는 실패한 확인이 `resume_check`에 있는 `codex_plugin_folder_replaced`나
   `host_release_outdated`)을 모두 한 번 보여 주고 사용자가 승인할 세션을 묻는다.
   고치면 그 세션이 끝나고 같은 대화가 다시 열린다.
   `resume`을 실행하기 전에 `references/resume.md`를 읽고, 승인된 터미널에만 실행한다.
7. **고아 터미널 닫기를 제안한다.** `orphans` 절에서 고아 에이전트 터미널마다
   호스트, 작업 트리, 유휴 시간을 보여 주며 추천되지 않은 터미널은 `failed_check`를 알린다. 추천된(`recommended`) 터미널 중
   어느 것을 닫을지 사용자에게 한 번 묻는다. `close`를 실행하기 전에 `references/orphaned-terminals.md`를 읽고, 승인된
   터미널에만 실행한다.

`--compact`의 기본값은 `auto`이며 낡은 세션만 compact한다. 사용자가 명시적으로 요청한 경우에만
`--compact always` 또는 `--compact never`를 전달한다. `plan`과 `self-apply`는 스크립트가 스스로 사용하는
내부 하위 명령이므로 직접 실행하지 않는다. 스크립트가 건너뛴 세션을 마무리하는 경우 외에는 Orca 터미널에 명령을
직접 보내지 않는다. 수동 마무리는 해당 세션에 대한 사용자 승인을 받고 `references/manual-finish.md`를 먼저 읽어
그 확인을 통과한 뒤에만 하며, 모든 결과를 `record-manual`로 기록한다. 이 요청에서 사용자가 승인한 세션에
`resume`을 실행하거나 `apply` 또는 Codex 설치를 시작하는 `decide`가 재개하는 경우, `interrupt` 답변으로 `decide`가 처리하는 경우, 또는 사용자가 승인한 건너뛴 세션을 `references/manual-finish.md`가
설명하는 대로 직접 마무리하는 경우 외에는 세션을 끝내지 않는다. 이 요청에서 사용자가 승인한 터미널에
`close`를 실행하는 경우 외에는 터미널을 닫지 않는다. 스스로 `--force`를 전달하지 않는다.

스크립트는 모든 세션이 `done`, `deferred`, `awaiting_answer`, `queued_after_turn` 중 하나이거나 업데이트 또는 `apply-installed` 결과가 ok이면
`0`으로 종료한다. 그렇지 않으면, 그리고 사용법 오류에도 `2`로 종료한다. 이 플러그인에 호스트 오류가 있거나
함께 새로고침할 플러그인 중 하나라도 상태가 `error`이면 업데이트 또는 `apply-installed` 결과는 ok가 아니다. `refresh`는 업데이트 결과가 ok이고
모든 세션이 `done`, `deferred`, `awaiting_answer`, `queued_after_turn` 중 하나일 때만 `0`으로 종료한다.

스크립트가 세션을 건너뛰거나 미루거나 실패 처리한 이유를 사용자에게 설명하기 전과 수동으로 마무리하기 전에 `references/safety-and-limits.md`를 읽는다.
