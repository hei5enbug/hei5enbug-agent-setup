# 모델 고정

> 영어 원본: [model-pins.md](../../../dev-rules/model-pins.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 저장소 개발 규칙은 `AGENTS.md`를 보완한다. `tests/test_model_pins.py`의 `PINS_VERIFIED_ON`이 14일보다 오래됐으면
이 저장소를 변경하기 전에 적용한다.

1. `config/model-registry.json`의 `pins`에 있는 모델 계열 가운데 GPT Luna를 제외한 모든 계열의 가장 새로운 정식 모델을
   확인하고, `PINS_VERIFIED_ON`을 그 확인 날짜로 바꾼다. 공식 [Claude 모델 개요](https://platform.claude.com/docs/en/about-claude/models/overview),
   [OpenAI 모델 카탈로그](https://developers.openai.com/api/docs/models), 각 호스트의 모델 카탈로그를 사용하고
   미리보기 모델은 제외한다.
2. 계열에 더 새로운 릴리스가 있으면 같은 변경에서 `config/model-registry.json`의 `pins`와 모든 참조를 갱신하고
   `tests/test_model_pins.py`가 통과할 때까지 맞춘다.

GPT Luna는 사용자가 명시적으로 선택을 바꿀 때까지 사용자가 고른 `gpt-5.6-luna`를 유지하며, 기본 사고 강도는 `high`이고
사고 강도 규칙에 따라 `xhigh`를 쓴다(사용자 선택일 2026-10-20). `gpt-sol`과 `gpt-terra`는 2026-11-20 소유자의 교체 규칙에 따른
역할별 비교 기록으로만 바꾸므로, 2단계만으로 더 새로운 Sol 릴리스를 채택하지 않는다.

실행 파일은 모델을 이 전체 ID로만 적는다. 별칭이나 실행 시점의 최신 릴리스 조회는 추가하지 않는다.
