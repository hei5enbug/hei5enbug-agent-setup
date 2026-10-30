# 큰 세션 기록 압축

> 영어 원본: [condensing.md](../../../../../skills/session-retro/references/condensing.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

세션이나 묶음의 파일 크기 합계가 1 MB를 넘을 때 쓴다. `SKILL.md`가 있는 디렉터리를 기준으로 경로를 해석해, 함께 들어
있는 스크립트를 세션 임시 폴더로 실행한다.

```text
python3 scripts/condense_records.py <session files> --out <temporary folder> [--since <YYYY-MM-DDTHH:MM> [--until <YYYY-MM-DDTHH:MM>]] [--tz <zone>]
```

2단계의 범위와 시간대를 그대로 넘긴다. 하루는 그날 자정부터 다음 자정까지다. 스크립트는 사용자 입력, 답변, 도구 호출,
오류마다 `L<original line number> <kind> <text>` 형식의 한 줄을 쓰고, 종류는 `user`, `reply`, `tool`, `error`이며, 긴
글은 버린 글자 수를 표시하며 자른다. 출력 경로와 줄 수가 담긴 JSON 객체 하나를 출력하고, 성공하면 0, 잘못된 인자면 2,
입력을 읽지 못하면 1로 끝난다. 작업자에게는 압축 파일과 원본 경로를 함께 주며, 작업자는 원래 줄 번호를 인용하고
원본은 인용을 확인할 때만 연다.
