# ledger-lite

> 영어 원본: [README.md](../../README.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

작은 복식부기 장부입니다. CSV에서 분개를 읽고, 잔액을 계산하고, 월말 보고서를 만들고, 은행 거래 내역을 장부와
대조합니다.

## 개념

- **분개(Entry)**: 한 계정에 날짜와 금액을 기록한 항목입니다. 차변은 양수, 대변은 음수이므로 일관된 장부의 분개 합은 0입니다.
- **장부(Journal)**: 날짜순으로 정렬한 분개 목록입니다. `Journal.balance(account, as_of)`는 특정 날짜의 잔액을 돌려줍니다.
- **대조(Reconciliation)**: `reconcile(journal, lines)`는 거래 내역 한 줄마다 금액이 같고 며칠 안에 있는 은행 계정 분개를
  짝지은 뒤 양쪽에 남은 항목을 알려 줍니다.

## 파일

분개 파일의 열은 `date,account,amount,memo`입니다. 거래 내역 파일의 열은 `date,description,amount`입니다. 날짜는 ISO 형식
`YYYY-MM-DD`를 씁니다.

## 개발

테스트는 `SAMPLE_DATA_DIR` 환경 변수가 가리키는 디렉터리에서 샘플 파일을 읽습니다. 실행 방법은
[docs/testing.md](../testing.md)를 보세요. 한국어 미러는 [docs/ko/docs/testing.ko.md](docs/testing.ko.md)입니다.

저장소 규칙은 [AGENTS.md](../../AGENTS.md)에 있습니다. 이 문서의 한국어 번역본이 지금 보고 계신
[docs/ko/README.ko.md](README.ko.md)입니다.
