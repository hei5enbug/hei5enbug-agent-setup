# 바쁜 Claude Code 세션

> 영어 원본: [busy-sessions.md](../../../../../skills/orca-plugin-refresh/references/busy-sessions.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

## 대기열 경로와 질문

Claude Code는 턴 중에 입력한 명령을 대기열에 넣고 턴이 끝나면 하나씩 실행한다. 따라서 `apply`는 이 스킬을
실행하는 세션이 아닌 바쁜 Claude Code 세션을 기다리지 않는다. 일반적인 입력 확인과 초안 재확인, 턴이 여전히
진행 중인지 재확인한 뒤 `/reload-plugins`와 지침이 오래됐으면 `/compact`를 입력 줄에 즉시 입력하고,
붙들어 둔 글을 다시 입력한 뒤 반환한다. 세션은 세부 내용 `commands_queued`와 `queued` 목록을 가진 `deferred`가
된다. 이 세션 자체는 `queued_after_turn`을 유지한다.

도우미는 대기열 오프셋 뒤의 대화 기록으로 각 대기열 명령을 확인하고, compact는 대기열 입력 시각 뒤 다시 쓴
표식으로도 확인한다. 대기열 명령이 실행되지 않았고 턴이 바쁜 동안에는 더 보내지 않는다. 턴이 끝나고 reload나
compact 제한 시간이 지났는데도 증거가 없을 때만 일반적인 보류 경로로 돌아가 아직 필요한 작업을 다시 확인하므로,
각 명령은 한 번씩 보낸다. Claude Code가 MCP 도구 거부로 답한 reload는 `reload_needs_force`와 함께 `failed`가 된다.
한 시간 제한에서 확인되지 않은 항목은 `queued_unconfirmed`와 함께 `skipped`가 된다. 명령은 여전히 실행될 수 있다.

다섯 경우에 스크립트는 아무것도 입력하거나 지우지 않는다. 세션은 `awaiting_answer`가 되고 `questions`에는 그 세션의
`id`, 터미널, 호스트, 작업 트리, 제목, `reason`, `background`, `options`가 담긴 질문이 하나 있다. `background`는
백그라운드 작업, 서브에이전트, 모니터, 깨우기가 여전히 응답할 수 있으면 `true`, 없으면 `false`, 대화 기록으로
알 수 없으면 `null`이며 `null`은 `true`로 센다. `apply`, `refresh`, `status`가 질문을 나열하고,
종료 코드에서는 `awaiting_answer`를 ok로 센다.

| `reason` | 스크립트가 묻는 이유 |
|---|---|
| `dialog_open` | 권한 프롬프트나 다른 대화상자가 열려 있어 입력하면 거기에 답하게 된다. |
| `input_not_restorable` | 입력 줄에 붙여넣기 자리표시자처럼 정확히 다시 입력할 수 없는 글이 있다. |
| `reload_needs_force` | 이번 실행에서 세션용으로 바뀐 플러그인이 불러온 폴더나 설치 폴더에 MCP 서버를 선언하거나(루트의 `.mcp.json` 또는 `.claude-plugin/plugin.json`의 `mcpServers` 키), 폴더나 세션 표식을 읽을 수 없다. 이번 실행 밖에서 바뀐 플러그인은 예측하지 못하며, 그 거부는 `reload_needs_force`와 함께 `failed`로 남는다. |
| `orchestration_mail_pending` | Orca에 세션의 읽지 않은 오케스트레이션 메일이 있거나 받은 메일함을 읽을 수 없다. |
| `state_unreadable` | 턴 기록이나 입력 줄을 읽을 수 없다. |

## 선택지

각 질문에는 스크립트가 만든 영어 `effect` 문장이 있는 선택지 세 개가 있다. 스크립트가 반환하자마자 다른 보고보다
먼저 질문 도구로 `questions`의 모든 질문을 이 세 선택지와 함께 묻고(호출당 최대 네 질문) `decide`를 실행한다.

| 선택지 | 효과 |
|---|---|
| `wait` | 지금은 아무것도 입력하지 않는다. 세션이 유휴가 되면 도우미가 일반적인 확인을 거쳐 명령을 보낸다. `input_not_restorable`은 그 글이 줄에 남은 동안 아무것도 보내지 않고, 줄이 비거나 되돌릴 수 있게 되면 보내며, 한 시간 동안 줄이 바뀌지 않으면 그 이유와 함께 세션을 `skipped`로 끝낸다. |
| `interrupt` | 중단 규칙에서 설명한다. `dialog_open`에서는 Esc가 열린 프롬프트를 거절하며 효과 문장에 그 내용이 나온다. |
| `skip` | 아무것도 보내지 않는다. 세션은 `skipped_by_user`와 함께 `skipped`로 끝난다. |

어떤 답도 `--force`를 승인하지 않는다. 답이 없는 세션은 `awaiting_answer`로 남고 아무것도 보내지 않는다.

## decide 명령

모든 답에 대해 `python3 <script> decide --run-id <run_id> --answer <question id>=<wait|interrupt|skip> [--answer ...] --json`을
셸 제한 시간 600초 이상으로 한 번 실행한다. 세션 잠금을 얻고 처리한 세션을 반환한다. 알 수 없거나 이미 답한 질문 id는
`question_unknown`을 반환하고 아무것도 하지 않는다.

## 중단 규칙

1. 세션을 다시 계획한다. 이미 유휴 상태면 일반적으로 적용하고 계속 프롬프트를 보내지 않는다.
2. 그렇지 않으면 Esc를 한 번 보내고 턴 기록이 바쁨에서 벗어나기를 최대 15초 기다린다. 벗어나지 않으면 세션은
   `interrupt_unconfirmed`와 함께 `failed`가 되고, 더 보내지 않으며 Esc를 두 번 보내지 않는다.
3. `background`가 `false`면 재개 코드로 세션을 종료하고 재개하며(`/reload-plugins`, `/compact` 없음)
   `resumed_without_compaction`을 기록한다.
4. 그 외에는 종료하면 백그라운드 작업이 끝나므로 일반 전송 경로로 `/reload-plugins`와, 지침이 오래됐으면
   `/compact`를 보낸다.
5. 작업이 확인되면 플러그인 업데이트로 중단되기 전 하던 작업을 계속하라는 고정된 영어 프롬프트를 한 번 보내고
   `continue_prompt`를 보고한다. `done`에 이르지 않은 세션에는 프롬프트를 보내지 않는다.

## Codex 세션

설치 게이트가 턴 진행 중인 Codex 세션을 찾으면 `update`는 `codex_turn_in_progress`로 Codex 설치를 보류한다.
스킬을 실행하는 세션이 턴 중이면 `update_deferred_active_session`으로 보류한다. 호스트 결과에 `recovery_command`를
유지하고 바쁜 롤아웃마다 `questions`에 `codex_install` 질문을 하나씩 추가한다. 질문에는 위 필드와 `reason`
`codex_install`, 세션의 터미널과 `worktree`, `background` null이 있다. 어떤 Codex 세션 표식도 가리키지 않는
롤아웃은 `outside_orca`다. `terminal`은 null, `worktree`는 그 폴더이며 프롬프트 내용은 읽지 않는다. 스킬을 실행하는
세션에는 `own_session`이 있다. 어떤 답변도 Claude Code 설치와 세션에는 영향을 주지 않는다.

| 선택지 | 효과 |
|---|---|
| `wait` | 지금은 아무것도 보내지 않는다. 모든 `wait` 세션의 턴이 끝나면 분리된 도우미가 설치하고, 플러그인 폴더가 교체된 Codex 세션을 재개하며, 재실행은 필요 없다. |
| `interrupt` | 스킬을 실행하는 세션이 아닌 Orca 세션에만 제공한다. 모든 `wait` 세션이 유휴가 되면 스크립트가 Esc를 한 번 누르고 턴 중단 기록을 확인한 뒤 설치하고 세션을 재개해 계속하라고 요청한다. |
| `skip` | 이번 실행에서 Codex를 업데이트하지 않으며 어떤 Codex 세션에도 아무것도 보내지 않는다. |

Orca 밖의 세션과 스킬을 실행하는 세션에는 `wait`와 `skip`만 제공한다. `wait`에서는 스킬을 실행하는 세션도 폴더가
교체된 다른 세션처럼 턴이 끝난 뒤 재개한다. 스크립트는 바쁜 Codex 세션에 다른 것을 입력하지 않고 `codex queue`를
사용하지 않는다.

모든 Codex 답변에 대해 `decide`를 한 번 실행한다. 답하지 않은 모든 `codex_install` 질문에 그 호출에서 답해야 하며
그렇지 않으면 `answers_incomplete`다. 질문이 제공하지 않은 선택지는 `answer_invalid`다. 하나라도 `skip`이면 이번
실행에서 Codex를 업데이트하지 않는다(`hosts.codex.decision`은 `skip`, `codex_install.status`는 `skipped_by_user`).
모두 `interrupt`이면 `decide`의 포그라운드에서 설치하고, `wait`가 하나라도 있으면 분리된 도우미가 한 시간 제한으로 처리한다.

설치 작업의 순서는 다음과 같다.

1. 모든 `wait` 세션의 롤아웃에 턴 종료가 기록될 때까지 기다린다.
2. 여전히 바쁜 각 `interrupt` 세션에 Esc를 한 번 보내고 턴 중단 기록을 확인한다. 15초 안에 기록되지 않으면 그 세션에
   더 보내지 않고 `wait`로 취급한다.
3. 잠금을 얻고 게이트를 다시 확인한 뒤 `update`처럼 Codex 마켓플레이스 업데이트와 설치를 실행한다.
4. 오류 없이 Codex 호스트 결과를 기록하고 새 `script` 경로를 저장한다. 설치가 이전 사본을 삭제하므로 이후 명령은
   모두 새 경로를 사용한다.
5. Codex 세션을 계획하고 스킬을 실행한 세션을 포함해 폴더가 교체된 세션을 재개한다.
6. 중단된 세션에만 계속 프롬프트를 보낸다.

제한 시간에 도달하면 아무것도 설치하지 않고 `codex_install.status`는 `not_idle_before_deadline`이다. `decide`와
`status`의 결과에는 `status`(`pending`, `done`, `failed`, `skipped_by_user`, `not_idle_before_deadline`), 마지막
게이트 `detail`, 중단된 각 세션의 상태를 담은 `codex_install`이 있다.
