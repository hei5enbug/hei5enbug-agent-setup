# 설정

> 영어 원본: [configuration.md](../../../docs/configuration.md)
> 이 문서는 비권위 한국어 번역본이다.

옵션은 `plugin.json`이나 호스트의 설정 화면에서 정한다.

| 옵션 | 값 | 기본값 |
|---|---|---|
| `delivery` | `auto` 또는 `manual` | `auto` |

배포 방식은 세션 컨텍스트에 `Delivery: <label>.` 줄로 나타난다. 값이 없거나 알 수 없으면 `auto`를 쓴다.
