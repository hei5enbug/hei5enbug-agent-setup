# 스킬 테스트 사례 작성

> 영어 원본: [test-cases.md](../../../../../skills/skill-builder/references/test-cases.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

## 테스트 사례

첫 반복에는 실제적인 프롬프트를 2~3개 만든다.
같은 형태를 반복해서 시험하지 말고 스킬이 실제로 만나게 될 입력 유형을 다양하게 한다.
사례가 늘어나면 올바른 동작이 최소한의 변경이거나 변경하지 않는 것인 사례를 최소 하나 포함한다. 지나치게
공격적인 스킬은 받아들일 만한 입력까지 고쳐 이 사례에서 실패한다.
사용자의 판단이 필요하면 사례를 공유해 확인받는다. 사용자가 이미 실행을 승인했고 기대 동작이 분명하면
그대로 진행하고 선택한 사례를 보고한다.

파일 시스템을 쓸 수 있으면 사례를 `evals/evals.json`에 저장한다.

```json
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "A realistic user task",
      "expected_output": "A concise description of success",
      "files": []
    }
  ]
}
```

assertion이나 benchmark 아티팩트가 필요하면 `references/schemas.md`를 읽는다.
