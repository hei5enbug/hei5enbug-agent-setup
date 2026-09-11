# 컨텍스트 형식

> 영어 원본: [context-format.md](context-format.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

## 단일 컨텍스트

대부분의 저장소는 루트 `CONTEXT.md` 하나를 사용한다.

```markdown
# 컨텍스트 이름

컨텍스트를 설명하는 한두 문장.

## Language

**Order**: 분야 용어의 짧은 정의. _피할 표현_: Purchase, transaction
```

개념마다 선호하는 단어 하나를 선택하고 혼동되는 대안을 `_Avoid_` 아래 나열한다.
정의는 한두 문장으로 제한하고 프로젝트 분야에 고유한 용어만 포함한다.

## 여러 컨텍스트

루트 `CONTEXT-MAP.md`가 있으면 컨텍스트별 용어집을 가리킨다.

```markdown
# Context Map

## Contexts

- [Ordering](./src/ordering/CONTEXT.ko.md) — 주문을 받고 추적한다
- [Billing](./src/billing/CONTEXT.ko.md) — 송장을 만들고 결제를 받는다

## Relationships

- **Ordering → Billing**: Ordering은 송장 생성을 위해 처리된 주문을 제공한다.
```

티켓에서 관련 컨텍스트를 추론한다. 결정이 불명확한 경계를 가로지르면 질문한다.
