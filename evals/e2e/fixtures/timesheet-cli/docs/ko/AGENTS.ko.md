# 저장소 규칙

> 영어 원본: [AGENTS.md](../../AGENTS.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

- Python 3.11 이상, 표준 라이브러리만 사용합니다.
- 변경을 끝났다고 보고하기 전에 `python3 -m pytest -q`를 실행합니다. 변경을 통과시키려고 기존 테스트를 고치지 않습니다.
- 설정은 `config/settings.toml`에 있습니다. 코드는 `timesheet.settings`를 통해서만 읽습니다.
- 날짜를 받는 모든 명령은 `timesheet.dates.parse_date`로 읽습니다.

## 문서

- 문서는 영어로 씁니다. 영어 Markdown 문서마다 `docs/ko/<경로>.ko.md`에 한국어 미러가 있고, 같은 변경에서 함께 고칩니다.
- 명령의 사용자 가시 변경은 `README.md`에 적습니다.
