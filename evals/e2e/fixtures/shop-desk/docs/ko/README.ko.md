# shop-desk

> 영어 원본: [README.md](../../README.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

작은 가게의 주문 창구 도구입니다. 고객, 주문, 매출 보고서를 JSON 파일 하나에 보관합니다.

## 사용법

```bash
python3 -m shop --store shop-data.json place 1 AB-100:2,CD-200:1
python3 -m shop --store shop-data.json lookup 1
python3 -m shop --store shop-data.json sales
python3 -m shop price AB-100
python3 -m shop week 2026-03-01
```

- `--store FILE`은 데이터 파일을 정합니다. 기본값은 `shop-data.json`이며 `SHOP_STORE`가 있으면 그 값을 씁니다.
- `place CUSTOMER_ID SKU:QTY[,SKU:QTY...]`는 주문을 저장하고 소계, 할인, 합계를 출력합니다. 고객 등급에 따라 소계에
  비율 할인이 붙습니다. basic 0, silver 5, gold 10입니다.
- `lookup CUSTOMER_ID`는 고객의 이름과 등급을 출력합니다.
- `sales`는 고객마다 주문 수, 순금액, 세금을 한 줄로 출력합니다.
- `price SKU`는 SKU의 단가를 출력합니다. SKU를 받는 모든 곳에서 SKU는 대소문자와 앞뒤 공백을 구분하지 않고 맞춥니다.
- `week DATE`는 `2026-W09`와 같은 그날의 주 라벨을 출력합니다.
- 실패한 명령은 이유를 stderr에 출력하고 종료 코드 2로 끝납니다.

## 설정

설정은 `shop/settings.py`에 기본값이 있고, 대문자 환경 변수 `SHOP_<이름>`으로 덮어씁니다. 예: `SHOP_TAX_PERCENT=10`.

## 보고용 데이터베이스

주 라벨은 SQLite로 동작하는 보고용 데이터베이스 안에서도 계산합니다. 데이터베이스는 일요일부터 한 주를 세며, 그해 첫
일요일 이전의 날은 00주입니다. `shop/dates.py`의 라벨은 같은 날에 대한 데이터베이스의 라벨과 같아야 합니다.
`python3 scripts/engine_check.py`는 2020년부터 2030년까지 모든 날에 대해 둘을 비교합니다.

## 개발

```bash
python3 -m pytest -q
```

기여 규칙은 [AGENTS.md](../../AGENTS.md)에 있습니다. 이 문서의 한국어 번역본이 지금 보고 계신
[docs/ko/README.ko.md](README.ko.md)입니다.
