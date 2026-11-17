# shop-lite

> 영어 원본: [README.md](../../README.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

센트 단위로 장바구니 가격을 계산하는 라이브러리와, 합계를 견적하는 작은 명령줄 도구입니다.

## 사용법

```bash
python3 -m shop quote 1999x2 500x1
python3 -m shop quote 2000x3 --discount 10
```

- `quote ITEM... [--discount PERCENT]`는 주문 합계를 출력합니다. `ITEM`은 `단가_센트x수량`입니다.
- `PERCENT`는 0부터 100까지의 정수입니다. 할인 금액은 센트 단위로 내림합니다.
- 배송비는 5.00이고, 할인 뒤 금액이 50.00에 이르면 무료입니다. 배송비는 할인 뒤에 판단합니다.
- 명령이 실패하면 이유를 stderr에 출력하고 종료 코드 1로 끝납니다.

## 개발

```bash
python3 -m pytest -q
```

기여 규칙은 [AGENTS.md](../../AGENTS.md)에 있습니다. 이 문서의 한국어 번역본이 지금 보고 계신
[docs/ko/README.ko.md](README.ko.md)입니다.
