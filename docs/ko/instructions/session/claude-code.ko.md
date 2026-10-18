# Claude Code 전용 지침

> 영어 원본: [claude-code.md](../../../../instructions/session/claude-code.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

에이전트나 모델 runner를 호출하기 전에
[Claude Code 에이전트 규칙](../claude-agents.ko.md)을 읽는다.

응답 언어는 `language` 설정이다. 설정이 없으면 사용자의 언어로 답한다.

메인 세션이 문서 안의 ASCII와 Mermaid 다이어그램을 직접 그리고, 기존 SVG 다이어그램을 직접 고치며, 노드 일곱 개 이하의
새 SVG나 PNG 흐름도를 직접 만든다. 그 밖의 UI 코드와 시각 디자인은 designer에게 맡긴다.
