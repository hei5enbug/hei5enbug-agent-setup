# 저장소 규칙

> 영어 원본: [AGENTS.md](../../AGENTS.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

- Python 3.11 이상, 표준 라이브러리만 사용합니다. 런타임 의존성을 추가하지 않습니다.
- 금액은 `Decimal`로 다루고 `inventory.money.quantize`로 반올림합니다. 가격에 `float`를 쓰지 않습니다.
- 사용자가 일으킬 수 있는 실패는 모두 `InventoryError`의 하위 클래스로 던집니다. CLI가 이를 종료 코드 2로 바꿉니다.
- 시간은 주입된 `clock`에서 가져오고, 서비스 안에서 `datetime.now()`를 직접 부르지 않습니다.
- 변경을 끝났다고 보고하기 전에 `python3 -m pytest -q`를 실행합니다. 변경을 통과시키려고 기존 테스트를 고치지 않습니다.
- 새 동작에는 `tests/`에 테스트가 필요합니다.

## 문서

- 문서는 영어로 씁니다. 설계 문서는 `docs/design/<topic>.md`에 둡니다.
- 영어 Markdown 문서마다 `docs/ko/<path>.ko.md`에 한국어 미러가 있습니다. `<path>`는 저장소 안의 문서 경로입니다.
  미러는 원본과 같은 변경에서 함께 고칩니다. 예를 들어 `README.md`의 미러는 `docs/ko/README.ko.md`, `docs/design/x.md`의
  미러는 `docs/ko/docs/design/x.ko.md`입니다.
- 미러는 제목으로 시작하고, 영어 원본을 링크하며 번역본이 원본보다 우선하지 않는다고 밝히는 인용 줄을 둡니다.
- CLI나 설정의 사용자에게 보이는 변경은 `README.md`에 적습니다.
