# inventory-service

> 영어 원본: [README.md](../../README.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

창고 두 곳을 쓰는 가게를 위한 작은 재고·주문 관리 서비스입니다. 상품, 창고별 재고, 주문, 재고 감사 기록을 JSON 파일
하나에 저장하고 명령줄 도구를 함께 제공합니다.

## 빠른 시작

```bash
python3 -m inventory warehouse add MAIN "Main warehouse" --priority 10
python3 -m inventory warehouse add EAST "East depot" --priority 20
python3 -m inventory item add WIDGET "Widget" 10.00 --category hardware
python3 -m inventory stock receive MAIN WIDGET 20
python3 -m inventory order create --customer kim@example.com --line WIDGET=3
python3 -m inventory report
```

명령 앞에 `--data FILE`을 붙이면 데이터 파일을 고를 수 있습니다. 모든 명령은 성공하면 0, 요청이 거절되면 2로
끝나며 이유는 stderr에 출력됩니다.

## 개념

- **상품(Item)**: SKU, 이름, 분류, 단가를 가진 제품입니다.
- **창고(Warehouse)**: 재고 위치입니다. `priority` 숫자가 작을수록 먼저 차감합니다.
- **주문(Order)**: 주문을 넣으면 창고에서 재고를 즉시 차감하고 각 수량이 어느 창고에서 나왔는지 기록합니다.
  주문은 `placed`, 그다음 `shipped` 또는 `cancelled`가 됩니다. `placed` 주문만 취소할 수 있습니다.
- **가격**: 한 줄에 10개, 50개, 100개 이상이면 각각 5%, 10%, 15%를 깎아 줍니다. 세금은 소계에 더합니다.

## 설정

| 변수 | 기본값 | 의미 |
|---|---|---|
| `INVENTORY_DATA_FILE` | `inventory.json` | JSON 데이터 파일 경로입니다. |
| `INVENTORY_CURRENCY` | `USD` | 보고서에 표시하는 세 글자 통화 코드입니다. |
| `INVENTORY_TAX_RATE` | `0.08` | 주문 소계에 더하는 0 이상 1 미만의 세율입니다. |

## CSV 가져오기

`import items FILE`은 `sku,name,price[,category]` 열을 읽습니다. `import stock FILE`은
`sku,warehouse,quantity` 열을 읽습니다. 검증에 실패한 행은 건너뛰고 요약에 나열합니다.

## 개발

```bash
python3 -m pytest -q
python3 tools/linecov.py inventory/importer.py
```

`tools/linecov.py`는 테스트를 실행한 뒤 모듈 하나의 라인 커버리지와 실행되지 않은 줄 번호를 출력합니다. pytest 외에는
아무것도 필요하지 않습니다. `--min 90`을 붙이면 커버리지가 더 낮을 때 종료 코드 1로 끝납니다.

기여자와 에이전트를 위한 규칙은 [AGENTS.md](../../AGENTS.md)에 있습니다. 이 문서의 한국어 번역본이 지금 보고 계신
[docs/ko/README.ko.md](README.ko.md)입니다.
