# tally-desk

> 영어 원본: [README.md](../../README.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

팀별 작업 시간이며 `data/entries.json`에서 읽습니다. `TALLY_DATA`는 다른 입력 파일을 가리킵니다.

## 명령

- `tally totals`는 모든 날짜를 합해 팀마다 `<팀> <시간>`을 팀 이름순으로 출력합니다.
- `tally rate TEAM`은 `data/rates.json`에서 팀의 시간당 요율을 출력합니다.
- `tally cost TEAM`은 팀의 총 시간에 시간당 요율을 곱해 정수 단위로 출력합니다.

## 시각

`tally.clock.now()`는 현재 시각을 돌려줍니다. `TALLY_NOW`(`YYYY-MM-DDTHH:MM`)가 이를 덮어쓰며 테스트가 사용합니다.

## 요율

`tally.rates.rate_for`는 읽은 요율을 `tally.cache.ttl_cached`로 한 시간 동안 보관합니다.
