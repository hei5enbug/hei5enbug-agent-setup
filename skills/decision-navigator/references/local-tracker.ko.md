# 로컬 추적기 계약

> 영어 원본: [local-tracker.md](local-tracker.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

모든 의사 결정 탐색기 상태는 저장소의 `.decision-navigator/` 아래에 둔다.
저장소에 remote가 있어도 외부 이슈 추적기를 읽거나 쓰지 않는다.

## 작업 구조

```text
.decision-navigator/<effort>/
├── map.md
├── tickets/
│   ├── 01-first-question.md
│   └── 02-second-question.md
├── claims/
│   ├── 01-first-question.lock/
│   └── map.lock/
└── artifacts/
    ├── research/
    └── prototypes/
```

짧고 읽기 쉬운 작업 slug를 사용한다. 지도 순서대로 `01`부터 티켓 번호를 붙인다.
`claims/`에는 임시 잠금 디렉터리와 메타데이터를 둔다. `.decision-navigator/.gitignore`에
`*/claims/`가 있는지 확인하고 추가할 때 기존 항목을 보존한다. 지도, 티켓과 아티팩트는 저장소의 일반
정책에 따라 버전 관리할 수 있지만 점유 정보는 로컬에만 둔다.

## 티켓 형식

```markdown
# 티켓 이름

Type: grilling
Status: open
Blocked by:

## Question

이 티켓이 해결할 결정 또는 조사.

## Answer
```

허용 유형은 `research`, `prototype`, `grilling`, `task`다. 허용 상태는 `open`, `resolved`다.
점유는 잠금으로만 나타내며 다른 상태 값을 사용하지 않는다.

차단 티켓의 파일 이름 stem을 쉼표로 구분한다.

```text
Blocked by: 01-first-question, 03-api-limits
```

## 원자적 잠금

티켓 점유와 직렬화된 지도 갱신에 포함된 도우미를 사용한다.

```text
python3 <skill-root>/scripts/local_lock.py claim \
  .decision-navigator/<effort>/tickets/01-first-question.md \
  --owner "<session-owner>"
```

세션에 안정적인 소유자 문자열을 선택하고 잠금을 해제할 때 재사용한다. 잠금은 다음 명령으로 확인한다.

```text
python3 <skill-root>/scripts/local_lock.py inspect <resource-path>
```

다음 명령으로 해제한다.

```text
python3 <skill-root>/scripts/local_lock.py release \
  <resource-path> --owner "<session-owner>"
```

도우미는 잠금 디렉터리를 원자적으로 만들어 동시 요청자 하나만 성공하게 한다.
잠금을 만든 뒤 티켓의 `Status:`를 다시 읽는다. 티켓이 더 이상 `open`이 아니거나 다시 읽지 못하면
실패를 알리기 전에 새 잠금을 제거한다. 같은 순간 다른 세션이 해결하거나 손상한 티켓은 점유되지 않고
빈 잠금도 남기지 않는다. 점유에 실패하면 해당 티켓을 건너뛰고 경계를 새로 읽는다.

`inspect`는 읽기 전용이며 `claims/`나 잠금을 만들지 않는다. `claim.json`이 문자열 `owner`와 `resource`
필드를 가진 JSON 객체가 아니면 손상된 메타데이터로 알린다. `release --force`는 경고를 출력한 뒤에도
이런 잠금을 제거한다.

잠금이 오래돼 보인다는 이유만으로 강제 해제하지 않는다. 메타데이터를 확인하고 `release --force` 전에 질문한다.

## 경계

숫자 순서대로 티켓을 검사한다. 경계 티켓은 다음 세 조건을 모두 만족해야 한다.

1. `Status: open`이다.
2. `Blocked by:`에 나열된 모든 파일의 `Status:`가 `resolved`다.
3. `claims/` 아래 대응하는 디렉터리가 없다.

점유가 성공한 뒤 선택한 티켓을 다시 읽는다.

## 해결 트랜잭션

티켓을 해결하는 동안 점유를 유지하고 다음 순서로 처리한다.

1. 답을 쓰고 `Status: resolved`로 바꾼다.
2. 같은 소유자로 `map.md`를 점유한다.
3. `map.md`를 다시 읽고 새 컨텍스트 포인터, 안개와 티켓 변경을 병합한다.
4. `map.md`를 저장하고 잠금을 해제한다.
5. 티켓 잠금을 해제한다.

지도 잠금을 가진 동안 새 티켓 파일을 만들어 두 세션이 같은 번호를 할당하지 못하게 한다.
실패하면 추측하지 않고 두 잠금을 보존한 채 정확한 복구 지점을 알린다.

## 범위와 삭제

티켓이 범위 밖으로 이동하면 `resolved`로 바꾸고 `## Answer` 아래 이유를 설명하며 지도의
`Out of scope`에서 연결한다. 사용자 승인 없이 지도, 티켓 또는 아티팩트를 삭제하지 않는다.
소유한 잠금은 도우미로 해제하고 잠금 디렉터리를 직접 제거하지 않는다.
