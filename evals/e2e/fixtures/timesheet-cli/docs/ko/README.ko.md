# timesheet-cli

> 영어 원본: [README.md](../../README.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

시간 기록을 다루는 작은 명령줄 도구입니다. 기록은 JSON 파일 `data/entries.json`에 있습니다.

## 명령

| 명령 | 하는 일 |
|---|---|
| `add DATE PROJECT MINUTES` | 기록을 더합니다. `DATE`는 `YYYY-MM-DD`입니다. |
| `list [--on DATE]` | 기록을 한 줄씩, 날짜가 이른 것부터 보여 줍니다. |
| `totals` | 프로젝트별 분을 보여 줍니다. |
| `report` | 목록을 보여 준 뒤 합계를 보여 줍니다. |
| `export [--from DATE] [--to DATE]` | 기록을 내보내기 폴더의 CSV 파일에 씁니다. |

모든 날짜 옵션은 `YYYY-MM-DD`를 읽습니다.

## 저장

- 더하기는 병렬로 실행해도 안전합니다. 저장소가 데이터 파일을 바꾸는 동안 잠금 파일을 잡아서, 동시에 둘을 더해도 기록을 잃지 않습니다.
- `timesheet.store.load_cached()`는 `timesheet.cache.TtlCache`로 한 프로세스 안에서 읽은 파일을 한 시간 동안 보관합니다.
