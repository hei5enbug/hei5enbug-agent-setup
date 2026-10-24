# 일시 중지와 재개

> 영어 원본: [pause-and-resume.md](../../../instructions/pause-and-resume.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

[작업 효율](work-efficiency.ko.md) 규칙이 이 파일을 연결한다. 긴 작업을 계획적으로 멈추거나 넘기기 전,
또는 압축이 예상되기 전에 읽는다. 세션에 `/compact`를 보내는 플러그인 갱신이 그런 예다.

## 재개 메모

호스트의 세션 임시 폴더에, 그런 폴더가 없으면 운영체제 임시 폴더 아래에 짧은 메모를 쓰고 그 경로를 알린다.
사용자가 요청할 때만 프로젝트 안에 쓴다. 다음 제목을 쓴다.

```markdown
# Resume: <goal>

Continue from "Next action". This note and the records it cites are authoritative; do not redo verified steps.

## Goal
## Current step
## Verified
<each claim with its check: command, result, and the input state it covered>
## Current state
<branch, uncommitted changes, running processes, pending questions>
## Next action
## Key files
## Pitfalls
```

템플릿의 각 제목은 목표, 현재 단계, 검증된 사항, 현재 상태, 다음 행동, 핵심 파일, 함정을 뜻한다. 첫 문단은
"다음 행동"부터 이어 가고, 이 메모와 메모가 인용한 기록을 권위 있는 것으로 보며, 검증된 단계를 다시 하지 말라는 뜻이다.
"검증된 사항"에는 각 주장과 그 검사(명령, 결과, 검사가 다룬 입력 상태)를, "현재 상태"에는 브랜치, 커밋하지 않은
변경, 실행 중인 프로세스, 대기 중인 질문을 적는다.

"Verified"에는 검사로 증명한 것만 적고, 확인하지 않은 믿음은 "Current state"나 "Pitfalls"에 둔다. 비밀 값이나
다른 보호 값을 메모에 옮기지 않는다.

## 재개

재개 메모에서 이어 가는 세션은 메모의 다음 행동부터 시작한다. 이미 끝낸 재현이나 검증한 검사를 다시 실행하지
않는다. 입력이 바뀌지 않은 동안 [검사 근거 규칙](work-efficiency.ko.md#검사-근거)에 따라 그 결과를 재사용한다.
수용하기 전에는 결과가 기대는 물려받은 주장을 메모가 아니라 파일, diff, 테스트 출력 같은 실제 산출물과 대조해
확인한다. 메모와 현재 상태가 다르면 상태를 믿고 차이를 알린다.
