# Orca 플러그인 업데이트와 세션 재개

> 영어 원본: [SKILL.md](SKILL.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다.
> 에이전트 실행 시 읽거나 사용하지 않는다.

등록된 Orca 관리 Claude Code와 Codex 세션에서 `hei5enbug-agent-setup` 업데이트를 검토한다.
승인된 계획에 따라 업데이트하고 세션을 재개한다.
이 스킬은 다른 플러그인이나 Orca 자체를 업데이트하지 않는다.

## 사전 조건

- macOS 또는 Linux의 Orca 관리 Claude Code 또는 Codex terminal에서 실행한다.
- Orca terminal 목록은 모든 대상 agent terminal의 프로세스 incarnation ID와 절대 워크트리 경로를 제공해야 한다.
  둘 중 하나라도 없으면 업데이트 계획 전에 중단한다. 실행 중에 재사용될 수 있는 handle만으로는 `/exit` 대상을
  증명할 수 없고, floating agent terminal에는 세션을 재개할 워크트리가 없다.
- 두 호스트에 `https://github.com/hei5enbug/hei5enbug-agent-setup.git`에서 설치한 사용자 범위의
  `hei5enbug-agent-setup@hei5enbug` 플러그인이 활성화되어 있어야 한다.
- Codex 플러그인 훅은 활성화·검토·신뢰 상태여야 한다.
  Claude Code 플러그인 훅도 켜야 한다.
- 대상 세션에는 이 플러그인이 만든 lifecycle registry 항목이 있어야 한다.
  이전 세션에는 항목이 없다. 기능을 설치하고 훅을 검토·신뢰한 뒤 기존 세션을 한 번씩
  수동으로 재시작하거나 재개한다.
  Codex는 prompt가 시작될 때만 항목을 만든다. 그래서 prompt를 한 번도 받지 않은 Codex 세션은
  prompt를 받거나 닫힐 때까지 계획을 막는다.
  terminal 미리보기나 대화 기록 파일에서 native session ID를 추측하지 않는다.
- `apply`를 실행하기 전에 현재 세션의 호스팅 서비스 접근 규칙을 따라
  마켓플레이스를 갱신한다.

플랫폼, 저장소, 설치 범위, 훅 상태 또는 session registry를 확인할 수 없으면 중단한다.
다른 마켓플레이스 소스를 선택하거나 session ID를 추정하지 않는다.

## 절차

불러온 스킬 파일의 위치에서 플러그인 루트를 찾는다. 스크립트는
`<plugin-root>/scripts/orca_plugin_refresh.py`에 있다. `plan`은 현재 Orca terminal, 로컬 lifecycle registry,
설치된 플러그인 버전과 캐시된 마켓플레이스 매니페스트를 읽는다.
마켓플레이스나 플러그인은 업데이트하지 않는다.
Orca 사용자 데이터 경로에 권한 제한 계획 파일을 저장하고 미리보기를 반환한다.

실행:

```bash
python3 <plugin-root>/scripts/orca_plugin_refresh.py plan --json
```

목표 버전, 대상 호스트와 terminal, worktree, 짧은 terminal handle, 상태와 차단 항목을 보여준다.
채팅에 native session ID를 표시하지 않는다. 계획이 차단되면 `apply`를 실행하지 않는다.
initiator 외 모든 세션이 idle이고 registry에 등록되어 있으며 보내지 않은 입력이 없어야 한다고 설명한다.
Claude Code의 백그라운드 작업이나 세션 범위의 예약된 재실행이 남아 있어도 idle로 보지 않는다.
차단을 해결한 뒤 새 계획을 만들도록 안내한다.

계획이 실행 가능하면 정확한 `plan_id`의 적용을 사용자에게 승인받는다.
일반적인 업데이트 요청을 미리보기 생략 승인으로 보지 않는다.
다음 명시적 승인을 받은 뒤 실행한다.

```bash
python3 <plugin-root>/scripts/orca_plugin_refresh.py apply --plan-id <plan_id> --json
```

`apply`는 terminal 집합, session ID, worktree, 마켓플레이스와 설치 버전을 다시 확인한다.
적용 승인을 처리하는 initiator만 busy 상태를 허용한다. 나머지 대상은 모두 idle이어야 한다.
transaction lease를 기록하고 분리된 worker를 시작한 뒤 transaction ID를 반환한다.
ID를 알린 뒤 현재 turn을 끝낸다. worker는 turn 종료를 기다린 뒤 플러그인을 업데이트하고 세션을 재시작한다.
transaction 중에는 대상 세션에 새 prompt를 보내거나 상태를 반복 조회하지 않는다.
lifecycle hook은 정상 실행되는 동안 worker가 lease를 해제할 때까지 새 prompt를 차단한다.
재개된 initiator session에는 완료 알림이 전달된다.

호스트가 훅 실행을 건너뛰거나 시간 초과시키면 입력 차단을 보장할 수 없다.
worker는 종료 직전에 계획한 native session ID의 현재 registry handle, 프로세스 incarnation,
lease와 Orca idle 상태를 다시 확인한다.
계획한 세션을 확인할 수 없다면 중단한다. 같은 worktree에 다른 terminal 하나만 남았다는 이유로 대체하지 않는다.

worker는 두 마켓플레이스를 갱신하고 계획 버전과 revision을 재확인한 뒤 플러그인을 업데이트한다.
각 세션은 원래 worktree에서 같은 native session ID로 재개한다.
종료 직전에 Orca `tui-idle`과 보내지 않은 입력을 다시 확인한다.
`/exit`를 보낸 뒤 agent가 terminal에서 사라질 때까지 기다린다. terminal의 셸이 남아 있어도 마찬가지다.
그다음 그 탭을 닫고 새 terminal을 만든다.
Codex는 app-server가 종료된 대화를 1분 정도 열어 둘 수 있어서, Codex가 대화 잠금을 풀 때까지 먼저 기다린다.
Codex는 그 대화에 마지막으로 기록된 모델과 추론 강도로 재개한다.
세션을 강제로 종료하거나 worktree를 닫지 않는다.

재개된 Claude Code 세션은 `SessionStart`가 목표 플러그인 버전을 registry에 기록하면 완료로 본다.
Codex는 다음 turn이 시작될 때만 `SessionStart`를 실행한다. 그래서 재개된 Codex 세션은 새 프로세스가
대화 잠금을 쥐면 완료로 본다. 다음 prompt가 확인할 때까지 receipt에는
`plugin_registration: pending_next_turn`이 표시된다.

마켓플레이스 갱신으로 계획 버전 또는 revision이 바뀌면 설치나 세션 종료 전에 중단한다.
새 계획을 요청한다.
Claude Code가 marketplace command 승인을 요구하면 자동 승인하지 않고 수동 승인을 요청한다.
receipt의 hash를 사용해 command를 직접 확인한다.

```bash
claude plugin update hei5enbug-agent-setup@hei5enbug --json
```

command를 확인한 뒤 새 계획을 만든다. 동일한 hash를 명시적으로 승인한 뒤 적용한다.

```bash
python3 <plugin-root>/scripts/orca_plugin_refresh.py apply --plan-id <fresh_plan_id> --accept-command <sha256> --json
```

worker가 오류를 반환하면 안전한 상태와 복구 방법만 보여준다.
자동 재시도나 rollback은 하지 않는다.

## 상태와 복구

`apply`가 반환한 receipt 경로 또는 최신 transaction을 조회한다.

```bash
python3 <plugin-root>/scripts/orca_plugin_refresh.py status --transaction-id <transaction_id> --json
python3 <plugin-root>/scripts/orca_plugin_refresh.py status --json
```

worker가 예기치 않게 멈추면 대상 agent 세션 밖에서 worker가 종료됐는지 확인한다.
그 뒤 receipt의 복구 명령에 `--confirm-worker-stopped`를 붙여 실행한다.
복구는 일치하는 lease만 해제하고 현재 terminal 상태를 기록한다.
플러그인을 업데이트하거나 세션을 종료·재개하지 않는다.
worker가 재개하지 못한 세션은 비공개 receipt에 기록된 수동 resume 명령을 사용한다.
오류가 `codex_thread_still_open`이면 Codex가 대화를 닫을 때까지 기다린 뒤 그 명령을 실행한다.
상태에 `manual_resume_requires_terminal_check`가 표시되면 새 terminal에서 agent가 여전히 실행 중인지
확인하고, 종료를 확인한 뒤에만 명령을 실행한다. 그렇지 않으면 같은 세션을 두 프로세스가 재개할 수 있다.
terminal 신원을 확인할 수 없는 복구 세션은 lifecycle hook이 현재 handle을 기록할 때까지 busy로 유지한다.

상태에 `complete_but_not_confirmed` 또는 `complete_but_not_delivered`가 표시되면 receipt를 직접 읽는다.
Orca가 입력은 수락했지만 turn 시작은 확인하지 못했을 수 있으므로 완료 알림을 무작정 다시 보내지 않는다.

## 안전과 데이터

- `plan`과 `status`는 플러그인이나 terminal을 변경하지 않는다.
  `plan`은 Orca 사용자 데이터에 권한 제한 계획 파일을 쓴다.
- `apply`는 확인된 `hei5enbug` marketplace의 이 플러그인만 업데이트한다.
  미리보기에서 확인한 Claude Code 및 Codex 세션만 재시작한다.
- busy, 미등록, 오래된 계획, 중복 또는 구분할 수 없는 세션이나 보내지 않은 입력이 있는 세션이 있으면
  설치 전에 중단한다.
- Codex의 경우 worker는 `CODEX_HOME` 아래의 대화 잠금과 대화 기록의 모델·추론 강도 필드만 읽는다.
- 플러그인 훅은 호스트 입력을 원자적으로 잠그지 못한다. idle 미리보기만으로 작업 중단이 없음을
  보장하거나 훅 시간 초과 중 새 prompt가 통과하지 않는다고 말하지 않는다.
- registry에는 호스트, native session ID, Orca handle, worktree, cwd, 플러그인 버전, 상태와 시각을
  저장한다.
  prompt, 대화 기록, token, 임의 환경 변수는 저장하지 않는다.
  파일은 사용자 전용 권한이며 30일 지난 종료 기록은 다음 registry 기록 때 제거한다.
- transaction receipt에는 원시 CLI 출력과 환경 값을 저장하지 않는다.
  resume과 복구에 필요한 session ID는 Orca 사용자 데이터 경로에 보관한다.
- 플러그인 버전은 자동으로 되돌리지 않는다.
  일부 작업이 실패하면 receipt에 완료 단계와 안전한 다음 조치를 기록한다.
